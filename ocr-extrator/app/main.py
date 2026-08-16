"""API do extrator de documentos (FastAPI + PaddleOCR)."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import (
    agente,
    analise_resposta,
    armazenamento,
    assinatura,
    auth,
    casos,
    categorias,
    chamada,
    consultas,
    contrato,
    escuta,
    pipeline,
    portal,
    rag,
    relatorio,
    roteiros,
    triagem,
    valor_documento,
)
from . import entrevista as entrevista_lib
from .agente import dossie as dossie_agente
from .extractors import ROTULOS_TIPO

# Onde o frontend atende — é o que monta o link enviado ao cliente.
URL_PORTAL = os.getenv("URL_PORTAL", "http://localhost:3000").rstrip("/")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")

BASE = Path(__file__).resolve().parent.parent
STATIC = BASE / "static"

MAX_BYTES = 20 * 1024 * 1024
EXTENSOES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".pdf"}

@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    """Aquece o OCR no boot, tirando os ~25s de carga do 1º upload.

    Vai para uma thread solta: o servidor precisa responder /api/saude de
    imediato, senão o `iniciar.ps1` espera o modelo para liberar o frontend.
    """
    threading.Thread(target=_tentar_aquecer, name="aquecer-ocr", daemon=True).start()
    yield


app = FastAPI(title="Extrator de Documentos — PaddleOCR", version="1.0.0", lifespan=ciclo_de_vida)

# O frontend Next chama esta API direto do navegador, então precisa de CORS.
# Com autenticação passou a existir credencial em jogo (o Bearer), então a lista
# de origens deixou de ser `*` e virou explícita — um `*` permitiria que qualquer
# página lesse as respostas se conseguisse um token.
#: A porta do Next neste projeto é a **3100** (ver o README: 8100/3100 justamente porque
#: 8000/3000 costumam estar ocupadas). O default listava só a 3000, e o sintoma era
#: "Failed to fetch" na tela inteira — a API respondia 200, o navegador é que descartava.
#: As duas ficam na lista porque quem sobe o front com `next dev` puro cai na 3000.
ORIGENS = [
    o.strip()
    for o in os.getenv(
        "ORIGENS_PERMITIDAS",
        "http://localhost:3100,http://127.0.0.1:3100,"
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    # Sem declarar aqui, o navegador esconde estes dois do JavaScript mesmo com
    # a resposta chegando inteira: é o nome do arquivo do contrato e o aviso de
    # campo que a entrevista não respondeu.
    expose_headers=[
        "Content-Disposition",
        "X-Campos-Faltando",
        "X-Pendencias",
        "X-Impedimentos",
    ],
)

# Rotas que respondem sem token. Tudo que não estiver aqui exige autenticação —
# a lista é de exceções justamente para que uma rota nova nasça protegida.
# `/api/chamada/config` entra aqui porque quem mais precisa dela é o cliente, que
# não tem conta no Keycloak. Não há segredo na resposta: é a lista de STUN
# públicos, a mesma que qualquer navegador do mundo usa.
PUBLICAS = {
    "/",
    "/api/saude",
    "/api/config",
    "/api/chamada/config",
    "/docs",
    "/openapi.json",
    "/redoc",
}

# O portal do cliente não passa pelo Keycloak: o cliente não tem conta. Quem o
# protege é a senha do caso, conferida dentro de cada rota `/api/portal/...`
# (ver `_caso_do_portal`). O prefixo é fechado de propósito — nenhuma outra
# rota entra por aqui.
PREFIXO_PORTAL = "/api/portal/"

# Módulo do agente jurídico. Fica num APIRouter próprio porque é ponte para outro
# serviço: se a ligação for desligada, some um bloco inteiro de rotas em vez de
# restarem funções mortas espalhadas por este arquivo.
app.include_router(agente.roteador)


@app.middleware("http")
async def exigir_autenticacao(request: Request, call_next):
    caminho = request.url.path
    # O preflight não carrega o Authorization; recusá-lo quebraria todo o CORS.
    livre = (
        request.method == "OPTIONS"
        or caminho in PUBLICAS
        or caminho.startswith(PREFIXO_PORTAL)
    )

    if auth.ATIVA and not livre:
        try:
            request.state.usuario = auth.usuario_atual(request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    else:
        request.state.usuario = auth.USUARIO_ABERTO

    return await call_next(request)


armazenamento.inicializar()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/tipos")
def tipos():
    return {"tipos": [{"codigo": k, "descricao": v} for k, v in ROTULOS_TIPO.items()]}


@app.get("/api/roteiros")
def listar_roteiros():
    """Roteiros de entrevista disponíveis, sem as perguntas."""
    return {
        "roteiros": [
            {"codigo": r.codigo, "nome": r.nome, "descricao": r.descricao} for r in roteiros.listar()
        ]
    }


class PedidoContrato(BaseModel):
    """As respostas do roteiro, como a tela as tem em mãos."""

    respostas: dict[str, Any]
    #: Onde o contrato é assinado. Vazio: tenta deduzir do endereço.
    municipio: str = ""


@app.post("/api/contrato")
def gerar_contrato(pedido: PedidoContrato):
    """Preenche o modelo oficial do escritório com os dados da entrevista.

    Devolve o .docx para conferência e assinatura — nada é gerado por modelo de
    linguagem aqui: as cláusulas, os percentuais e as inscrições na OAB saem do
    arquivo em `docs/`, palavra por palavra (ver `app/contrato.py`).

    Nome completo e CPF válido são obrigatórios. Os demais campos que a
    entrevista não respondeu voltam no cabeçalho `X-Campos-Faltando`, e
    continuam visíveis entre colchetes no documento.
    """
    try:
        respostas = contrato.normalizar_respostas(pedido.respostas)
        docx, faltando = contrato.gerar(respostas, pedido.municipio)
    except contrato.DadosObrigatoriosContrato as exc:
        raise HTTPException(422, str(exc)) from exc
    except contrato.ErroContrato as exc:
        raise HTTPException(503, str(exc)) from exc

    nome_cliente = str(respostas["nome"])
    arquivo = f"Contrato - {nome_cliente}.docx".replace("/", "-").replace("\\", "-")

    return Response(
        content=docx,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={
            # `filename*` em UTF-8 porque nome de cliente tem acento, e o
            # `filename` sem aspas quebraria no primeiro espaço.
            "Content-Disposition": (
                f'attachment; filename="contrato.docx"; '
                f"filename*=UTF-8''{quote(arquivo)}"
            ),
            "X-Campos-Faltando": ", ".join(faltando),
        },
    )


@app.get("/api/contrato/campos")
def campos_do_contrato():
    """Marcadores que o modelo pede — para conferir o mapeamento da entrevista."""
    try:
        marcadores = contrato.marcadores_do_modelo()
    except contrato.ErroContrato as exc:
        raise HTTPException(503, str(exc)) from exc
    preenchiveis = set(contrato.valores_da_entrevista({}))
    return {
        "modelo": contrato.caminho_modelo().name,
        "marcadores": marcadores,
        # O que o modelo pede e a entrevista não sabe responder: some daqui e
        # vira colchete no contrato assinado.
        "sem_origem": [
            m for m in marcadores if m not in {contrato._chave(f"[{k}]") for k in preenchiveis}
        ],
    }


class PedidoRelatorio(BaseModel):
    """As respostas da entrevista concluída."""

    respostas: dict[str, Any]
    roteiro: str = Field(default="empregado_publico", max_length=60)
    entrevistador: str = Field(default="", max_length=120)
    #: O relato corrido da entrevista — é dele que sai a análise por precedentes.
    #: A tela já o monta para a triagem; mandá-lo aqui evita reconstruí-lo.
    relato: str = Field(default="", max_length=20_000)
    #: Gerar a seção de análise (busca de precedentes + DeepSeek). Melhor-esforço:
    #: base fora do ar não impede o relatório, só troca a seção por uma nota.
    analisar: bool = True


@app.post("/api/entrevista/relatorio")
async def gerar_relatorio(pedido: PedidoRelatorio):
    """O relatório ANALISADO da entrevista, em PDF, com o símbolo do escritório.

    É a entrega que a saudação do roteiro promete ao cliente. Quem o recebe não
    estava na conversa, então ele diz o que foi perguntado, o que foi respondido
    e — principalmente — o que ficou sem resposta (ver `app/relatorio.py`).

    Traz também uma análise assistida por precedentes (o mesmo motor do
    `/api/estrategia`): síntese, ações sugeridas, riscos e lacunas, cada um
    citando o precedente que o sustenta. É apoio à decisão, não conclusão — a
    classificação jurídica continua sendo da equipe.
    """
    analise: dict[str, Any] | None = None
    if pedido.analisar and pedido.relato.strip():
        try:
            analise = await run_in_threadpool(rag.sugerir_acoes, pedido.relato)
        except Exception:
            # Base instável é o caso esperado, não a exceção (ver CONTEXTO.md). O
            # relatório sai com a nota em vez de esperar ou falhar por causa dela.
            log.warning("Análise do relatório indisponível", exc_info=True)
            analise = {
                "indisponivel": (
                    "A base de precedentes não respondeu a tempo. O relatório "
                    "organiza as respostas; a análise por precedentes pode ser "
                    "gerada depois, na triagem do caso."
                )
            }

    try:
        pdf, dados = await run_in_threadpool(
            relatorio.gerar_pdf,
            pedido.respostas,
            pedido.roteiro,
            pedido.entrevistador,
            analise,
        )
    except relatorio.ErroRelatorio as exc:
        raise HTTPException(400, str(exc)) from exc

    arquivo = (
        f"Relatório de entrevista - {dados['cliente']}.pdf"
        .replace("/", "-")
        .replace("\\", "-")
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="entrevista.pdf"; '
                f"filename*=UTF-8''{quote(arquivo)}"
            ),
            # A tela precisa saber o que ficou pendente sem abrir o arquivo.
            "X-Pendencias": str(len(dados["faltando_obrigatorias"])),
            "X-Impedimentos": str(len(dados["impedimentos"])),
            # E se a análise entrou, para a tela poder avisar.
            "X-Analise": (
                "indisponivel"
                if analise and analise.get("indisponivel")
                else "sim"
                if analise
                else "nao"
            ),
        },
    )


class PedidoEscuta(BaseModel):
    """Um trecho de fala recém-transcrito, com o estado atual da entrevista."""

    trecho: str = Field(max_length=8_000)
    respostas: dict[str, Any] = Field(default_factory=dict)
    roteiro: str = Field(default="empregado_publico", max_length=60)


@app.post("/api/entrevista/escuta")
async def escutar_entrevista(pedido: PedidoEscuta):
    """O que este trecho de fala respondeu do roteiro, e o que ainda falta.

    É o que sustenta a entrevista de microfone aberto: em vez de o entrevistador
    apertar gravar a cada uma das 86 perguntas, a conversa corre e o roteiro se
    preenche atrás dela (ver `app/escuta.py`).

    Devolve os três de uma vez — o que entrou, o que ficou pela metade e o que
    ninguém falou. Separados não servem: saber o que falta sem ver o que já
    entrou faz repetir pergunta, que é do que o escritório reclamou.
    """
    try:
        return await run_in_threadpool(
            escuta.escutar, pedido.trecho, pedido.respostas, pedido.roteiro
        )
    except escuta.ErroEscuta as exc:
        raise HTTPException(503, str(exc)) from exc


class PedidoAnaliseResposta(BaseModel):
    """Uma resposta narrativa recém-dada, para conferência imediata."""

    pergunta_id: str = Field(max_length=120)
    pergunta: str = Field(max_length=1_000)
    resposta: str = Field(max_length=20_000)
    #: O pouco que já se sabe do caso — a categoria triada, tipicamente. Evita
    #: que a análise peça o que outra pergunta do roteiro já respondeu.
    contexto: str = Field(default="", max_length=4_000)


@app.post("/api/entrevista/analise")
async def analisar_resposta(pedido: PedidoAnaliseResposta):
    """O que esta resposta ainda não trouxe — em três itens, durante a entrevista.

    Roda uma vez por pergunta narrativa, então é deliberadamente mais curta que
    o `/api/estrategia`: o que não cabe entre uma pergunta e a seguinte não é
    lido (ver `app/analise_resposta.py`).

    Sai com `com_precedentes: false` quando o banco de precedentes não responde.
    A análise ainda vale, mas passa a ser a leitura do modelo sobre o texto — e
    não o que os processos semelhantes mostram. A tela precisa separar as duas.
    """
    try:
        # `analisar` é síncrona de ponta a ponta (psycopg e httpx bloqueantes);
        # rodá-la no laço de eventos travaria a transcrição ao vivo das outras
        # perguntas, que compartilha este processo.
        return await run_in_threadpool(
            analise_resposta.analisar,
            pedido.pergunta_id,
            pedido.pergunta,
            pedido.resposta,
            pedido.contexto,
        )
    except analise_resposta.ErroAnalise as exc:
        raise HTTPException(503, str(exc)) from exc


# ------------------------------------------- contrato → assinatura eletrônica
#
# O contrato é gerado, conferido pelo advogado e só então mandado assinar. O
# fluxo é o mesmo de sempre, com um passo a menos de trabalho manual: em vez de
# baixar o .docx, subir no painel da ZapSign e digitar os contatos, o servidor
# faz o upload e dispara os convites com o que a entrevista já respondeu.
#
# O que NÃO muda: o documento continua sendo o modelo do escritório palavra por
# palavra (`app/contrato.py`), e quem escolhe mandar assinar é o advogado.


class Signatario(BaseModel):
    """Alguém a mais na assinatura — testemunha, segundo contratante, sócio."""

    nome: str
    email: str = ""
    telefone: str = ""
    papel: str = ""


class PedidoAssinatura(PedidoContrato):
    """As respostas do roteiro, mais quem assina além do cliente."""

    #: Somados ao cliente (da entrevista) e ao escritório (do `.env`).
    signatarios: list[Signatario] = Field(default_factory=list)
    #: Vincula o contrato a um caso já aberto. Em geral vem vazio: na ordem do
    #: escritório o contrato é assinado antes de o caso existir.
    caso_id: str | None = None


def _chave_nome_identidade(nome: object) -> str:
    """Forma estável do nome usada somente para correlacionar contrato e caso."""
    return " ".join(str(nome or "").split()).casefold()


def _cpf_identidade(cpf: object) -> str:
    """CPF canônico; as duas origens já passaram pela validação do contrato."""
    return "".join(c for c in str(cpf or "") if "0" <= c <= "9")


def _identidade_atual_do_caso(caso_id: str) -> tuple[str, str]:
    """Relê a identidade inequívoca do Case State, sem confiar no navegador."""
    montado = dossie_agente.montar(caso_id)
    if montado is None:
        raise HTTPException(404, "Caso não encontrado.")

    respostas, motivos = dossie_agente.dados_do_contrato(montado)
    if motivos:
        # Os motivos podem conter contexto útil na tela do dossiê, mas esta rota
        # só precisa declarar o conflito sem devolver nenhum dado de identificação.
        raise HTTPException(
            409,
            "A identidade atual do caso não está válida e inequívoca para vincular o contrato.",
        )
    return str(respostas["nome"]), str(respostas["cpf"])


def _exigir_identidade_do_caso(caso_id: str, nome: object, cpf: object) -> None:
    nome_caso, cpf_caso = _identidade_atual_do_caso(caso_id)
    if (
        _chave_nome_identidade(nome) != _chave_nome_identidade(nome_caso)
        or _cpf_identidade(cpf) != _cpf_identidade(cpf_caso)
    ):
        raise HTTPException(
            409,
            "A identificação do contrato não corresponde à identidade atual do caso.",
        )


def _resposta_assinatura(registro: dict[str, Any]) -> dict[str, Any]:
    """O registro local sem o token da ZapSign.

    O token identifica o documento na conta do escritório e serve para consultar
    e excluir pela API deles. Quem precisa dele é o servidor; a tela trabalha
    com o `id` local, que não vale nada fora daqui.
    """
    limpo = dict(registro)
    limpo.pop("doc_token", None)
    limpo.pop("cpf", None)
    return limpo


@app.get("/api/assinatura/config")
def config_assinatura():
    """Se dá para mandar assinar, e com que modo de autenticação.

    A tela pergunta antes de oferecer o botão: sem a chave no `.env` o envio não
    existe, e é melhor dizer isso do que deixar o advogado clicar e tomar erro.
    """
    return assinatura.configuracao()


@app.post("/api/contrato/assinatura", status_code=201)
async def enviar_contrato_para_assinatura(pedido: PedidoAssinatura):
    """Gera o contrato e o manda para assinatura eletrônica.

    O .docx sobe como está — a ZapSign converte para PDF e é esse PDF que o
    cliente assina. Nome completo e CPF válido são obrigatórios. Outro campo que
    a entrevista não respondeu continua entre colchetes e volta em `faltando`.
    """
    if not assinatura.ativa():
        raise HTTPException(
            503,
            "Assinatura eletrônica desligada: falta ZAPSIGN_API_TOKEN no .env. "
            "O contrato continua podendo ser gerado e assinado à mão.",
        )

    try:
        respostas = contrato.normalizar_respostas(pedido.respostas)
        cliente = str(respostas["nome"])
        if pedido.caso_id:
            await run_in_threadpool(
                _exigir_identidade_do_caso,
                pedido.caso_id,
                cliente,
                respostas["cpf"],
            )
        docx, faltando = await run_in_threadpool(
            contrato.gerar, respostas, pedido.municipio
        )
    except contrato.DadosObrigatoriosContrato as exc:
        raise HTTPException(422, str(exc)) from exc
    except contrato.ErroContrato as exc:
        raise HTTPException(503, str(exc)) from exc

    nome_documento = f"Contrato de honorários — {cliente}"
    extras = [s.model_dump() for s in pedido.signatarios]

    # Montar a lista falha por dado que o usuário pode consertar — cliente sem
    # e-mail e sem telefone. É 400, e não 502: culpar a ZapSign por uma entrevista
    # incompleta manda o advogado procurar o problema no lugar errado.
    try:
        signatarios = assinatura.signatarios_do_contrato(respostas, extras)
    except assinatura.ErroAssinatura as exc:
        raise HTTPException(400, str(exc)) from exc

    try:
        resposta = await assinatura.enviar(nome_documento, docx, signatarios)
    except assinatura.ErroAssinatura as exc:
        raise HTTPException(502, str(exc)) from exc

    resumo = assinatura.resumir(resposta, assinatura.casar_com_enviados(signatarios, resposta))

    if not resumo["doc_token"]:
        raise HTTPException(502, "A ZapSign aceitou o documento mas não devolveu o token dele.")

    registro = armazenamento.registrar_assinatura(
        doc_token=resumo["doc_token"],
        nome=nome_documento,
        cliente=cliente,
        cpf=str(respostas["cpf"]),
        signatarios=resumo["signatarios"],
        estado=resumo["estado"],
        caso_id=pedido.caso_id,
    )

    log.info(
        "Contrato de %s enviado para assinatura (%d signatário(s)).",
        cliente,
        resumo["total"],
    )
    return {"assinatura": _resposta_assinatura(registro), "faltando": faltando}


@app.get("/api/assinaturas")
def listar_assinaturas(
    caso_id: str | None = None,
    cliente: str | None = None,
    cpf: str | None = None,
):
    """Os contratos já mandados assinar, do mais novo para o mais antigo.

    Devolve o último estado conhecido, sem consultar a ZapSign: a lista abre
    instantânea e uma consulta por contrato estouraria o limite de requisições
    deles numa carteira grande. Quem atualiza é o `GET` de um contrato só.
    """
    if cliente and not cpf:
        raise HTTPException(422, "Informe o CPF junto com o nome para evitar homônimos.")
    return {
        "assinaturas": [
            _resposta_assinatura(a)
            for a in armazenamento.listar_assinaturas(caso_id=caso_id, cliente=cliente, cpf=cpf)
        ]
    }


@app.get("/api/assinaturas/{assinatura_id}")
async def obter_assinatura(assinatura_id: str):
    """Quem já assinou e quem falta — consultado na ZapSign agora.

    Se a consulta falhar, devolve o último estado conhecido com `atualizado:
    false`. Some da tela é pior que estar desatualizado: o advogado precisa ver
    que o contrato existe mesmo quando a ZapSign está fora do ar.
    """
    registro = armazenamento.obter_assinatura(assinatura_id)
    if registro is None:
        raise HTTPException(404, "Contrato não encontrado.")

    try:
        documento = await assinatura.consultar(registro["doc_token"])
    except assinatura.ErroAssinatura as exc:
        return {
            "assinatura": _resposta_assinatura(registro),
            "atualizado": False,
            "aviso": str(exc),
        }

    # O que já se sabia de cada signatário: o papel e o link de assinatura, que a
    # consulta de detalhe não repete (ver `assinatura.resumir`).
    anteriores = {s.get("token", ""): s for s in registro["signatarios"]}
    resumo = assinatura.resumir(documento, anteriores)
    atualizado = armazenamento.atualizar_assinatura(
        assinatura_id, resumo["estado"], resumo["signatarios"]
    )
    return {
        "assinatura": _resposta_assinatura(atualizado or registro),
        "atualizado": True,
        "tem_assinado": resumo["tem_assinado"],
    }


@app.get("/api/assinaturas/{assinatura_id}/arquivo")
async def baixar_contrato_assinado(assinatura_id: str):
    """O PDF assinado, com a página de trilha de auditoria da ZapSign.

    Na primeira vez o arquivo é puxado de lá e guardado em `dados/contratos/`;
    depois sai do disco. Não é cache por velocidade: os links da ZapSign expiram
    em 60 minutos, e o escritório precisa da via assinada mesmo anos depois, com
    ou sem a conta ativa.
    """
    registro = armazenamento.obter_assinatura(assinatura_id)
    if registro is None:
        raise HTTPException(404, "Contrato não encontrado.")

    nome_arquivo = f"{registro['nome']}.pdf".replace("/", "-").replace("\\", "-")

    guardado = armazenamento.caminho_do_assinado(assinatura_id)
    if guardado is not None:
        return FileResponse(guardado, media_type="application/pdf", filename=nome_arquivo)

    try:
        url = await assinatura.url_do_assinado(registro["doc_token"])
        pdf = await assinatura.baixar(url)
    except assinatura.ErroAssinatura as exc:
        # 409: o pedido está correto, o documento é que ainda não foi assinado
        # por todos. 502 faria a tela culpar a rede por uma assinatura pendente.
        raise HTTPException(409, str(exc)) from exc

    destino = armazenamento.DIR_CONTRATOS / f"{assinatura_id}.pdf"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(pdf)
    armazenamento.definir_arquivo_assinatura(assinatura_id, destino)

    return FileResponse(destino, media_type="application/pdf", filename=nome_arquivo)


@app.post("/api/assinaturas/{assinatura_id}/caso")
def vincular_assinatura(assinatura_id: str, caso_id: str = Form(...)):
    """Liga o contrato ao caso aberto depois dele — a ordem do escritório."""
    registro = armazenamento.obter_assinatura(assinatura_id)
    if registro is None:
        raise HTTPException(404, "Contrato não encontrado.")
    _exigir_identidade_do_caso(caso_id, registro.get("cliente"), registro.get("cpf"))
    if not armazenamento.vincular_assinatura_ao_caso(assinatura_id, caso_id):
        raise HTTPException(404, "Contrato não encontrado.")
    return {"vinculado": True}


@app.delete("/api/assinaturas/{assinatura_id}")
def excluir_assinatura(assinatura_id: str):
    """Tira o contrato da lista local. Na ZapSign ele continua, com a auditoria."""
    if not armazenamento.excluir_assinatura(assinatura_id):
        raise HTTPException(404, "Contrato não encontrado.")
    return {"removido": True}


@app.get("/api/cep/{cep}")
async def consultar_cep(cep: str):
    """Endereço a partir do CEP, para adiantar o preenchimento da entrevista.

    Sai daqui apenas o CEP: nenhum dado do cliente acompanha a consulta. Ver
    `app/consultas.py` para o que as bases públicas resolvem — e o que não
    resolvem, que é praticamente tudo o mais.
    """
    try:
        return await consultas.buscar_cep(cep)
    except consultas.ErroConsulta as exc:
        # 422: o CEP é sintaticamente válido mas não existe, ou a base caiu. Não
        # é 404 da nossa rota — ela existe e respondeu.
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/roteiros/{codigo}")
def obter_roteiro(codigo: str):
    """Roteiro completo: blocos, perguntas e quais delas abrem o gravador."""
    roteiro = roteiros.obter(codigo)
    if roteiro is None:
        raise HTTPException(404, f"Roteiro '{codigo}' não encontrado.")
    return {**roteiro.to_dict(), "mapa_rastreio": roteiros.MAPA_RASTREIO}


@app.get("/api/categorias")
def listar_categorias():
    """Categorias de processo, cada uma com seu checklist de documentos."""
    return {"categorias": [c.to_dict() for c in categorias.listar()]}


@app.get("/api/categorias/{codigo}")
def obter_categoria(codigo: str):
    categoria = categorias.obter(codigo)
    if categoria is None:
        raise HTTPException(404, f"Categoria '{codigo}' não encontrada.")
    return categoria.to_dict()


@app.get("/api/saude")
def saude():
    from . import ocr_engine  # lê o atributo do módulo, não uma cópia do valor

    return {"status": "ok", "modelo_carregado": ocr_engine._engine is not None}


@app.get("/api/config")
def config():
    """Como o frontend deve falar com o Keycloak. Público e sem segredo — são os
    mesmos dados que apareceriam na URL de login."""
    return {"auth": auth.configuracao_publica()}


@app.get("/api/eu")
def eu(usuario: auth.Usuario = Depends(auth.usuario_atual)):
    """Quem está autenticado nesta requisição."""
    return usuario.to_dict()


def _aquecer_modelo() -> None:
    """Constrói os modelos do PaddleOCR rodando um OCR numa imagem em branco.

    A construção acontece dentro da thread dona do predictor (ver `ocr_engine`),
    porque é `rodar_ocr` quem a agenda lá — não chamar `get_engine` daqui.
    """
    import numpy as np

    from .ocr_engine import rodar_ocr

    rodar_ocr(np.full((80, 400, 3), 255, dtype=np.uint8))


def _tentar_aquecer() -> None:
    try:
        _aquecer_modelo()
        log.info("Modelo de OCR aquecido e pronto.")
    except Exception:
        # Sem rede na primeira execução, por exemplo: o upload tenta de novo.
        log.exception("Falha ao aquecer o modelo no boot")


@app.post("/api/aquecer")
def aquecer():
    """Baixa e carrega os modelos do PaddleOCR antes do primeiro upload."""
    try:
        _aquecer_modelo()
        return {"status": "pronto"}
    except Exception as exc:
        log.exception("Falha ao aquecer o modelo")
        raise HTTPException(status_code=500, detail=f"Falha ao carregar o modelo: {exc}") from exc


async def _ler_upload(arquivo: UploadFile) -> bytes:
    """Valida extensão e tamanho, devolvendo os bytes do arquivo enviado."""
    ext = Path(arquivo.filename or "").suffix.lower()
    if ext and ext not in EXTENSOES:
        raise HTTPException(400, f"Extensão '{ext}' não suportada. Use: {', '.join(sorted(EXTENSOES))}")

    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")
    if len(conteudo) > MAX_BYTES:
        raise HTTPException(413, f"Arquivo maior que {MAX_BYTES // (1024 * 1024)}MB.")
    return conteudo


async def _processar(conteudo: bytes, nome: str, idioma: str, tipo_forcado: str | None) -> dict:
    try:
        # O OCR leva segundos e é puro CPU: fora do event loop, senão o servidor
        # para de responder (inclusive ao /api/saude) enquanto processa.
        return await run_in_threadpool(pipeline.processar, conteudo, nome, idioma, tipo_forcado)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        log.exception("Erro ao processar %s", nome)
        raise HTTPException(500, f"Erro ao processar a imagem: {exc}") from exc


@app.post("/api/extrair")
async def extrair(
    arquivo: UploadFile = File(...),
    idioma: str = Form("pt"),
    tipo: str | None = Form(None),
):
    conteudo = await _ler_upload(arquivo)
    tipo_forcado = tipo if tipo and tipo not in ("auto", "", "None") else None
    resultado = await _processar(conteudo, arquivo.filename or "sem-nome", idioma, tipo_forcado)
    return JSONResponse(resultado)


# ------------------------------------------------------------------- casos


def _criar_portal(caso_id: str) -> dict[str, Any]:
    """Sorteia link e senha do portal e grava só o hash da senha."""
    token = portal.gerar_token()
    senha = portal.gerar_senha()
    senha_hash, sal = portal.hash_senha(senha)
    armazenamento.definir_portal(caso_id, token, senha_hash, sal)
    portal.limpar_tentativas(token)
    return {
        "url": f"{URL_PORTAL}/portal/{token}",
        "token": token,
        "senha": senha,
        "aviso": "Anote a senha agora: ela não pode ser consultada depois, só trocada.",
    }


@app.post("/api/triagem")
async def triar_entrevista(
    texto: str = Form(""),
    arquivo: UploadFile | None = File(None),
):
    """Lê a entrevista e sugere a categoria do caso — sem criar nada.

    Devolve um ranking com a evidência de cada categoria. Quem decide é o
    advogado: errar a categoria é errar o checklist inteiro, e o sistema passaria
    a cobrar documentos que a ação não usa.
    """
    conteudo = texto or ""

    if arquivo is not None and arquivo.filename:
        if not arquivo.filename.lower().endswith((".txt", ".md")):
            raise HTTPException(400, "Envie a entrevista em .txt (ou cole o texto).")
        bruto = await arquivo.read()
        if len(bruto) > 2 * 1024 * 1024:
            raise HTTPException(400, "Arquivo grande demais para uma entrevista (máx. 2 MB).")
        # Entrevista digitada no Word e salva como txt costuma vir em latin-1.
        for cod in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                conteudo = bruto.decode(cod)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise HTTPException(400, "Não foi possível ler o texto do arquivo.")

    if not conteudo.strip():
        raise HTTPException(400, "Cole a entrevista ou envie um arquivo .txt.")

    resultado = triagem.triar(conteudo)
    resultado["dados"] = triagem.extrair_dados_do_cliente(conteudo)
    resultado["caracteres"] = len(conteudo)
    return resultado


# --------------------------------------------------- chamada de voz (WebRTC)

_salas = chamada.Salas()


@app.get("/api/chamada/config")
def config_chamada():
    """Servidores ICE para o navegador montar a conexão. Público e sem segredo."""
    return {"iceServers": chamada.SERVIDORES_ICE}


@app.post("/api/chamada/sala", status_code=201)
def criar_sala():
    """Sorteia uma sala de chamada e devolve o link para mandar ao entrevistado.

    A entrevista acontece ANTES de o caso existir — é ela que decide a categoria
    —, então a sala não pode depender de caso nem de portal. O nome da sala é o
    segredo: 256 bits sorteados, do mesmo gerador que assina o portal. Quem tem
    o link entra; quem não tem não adivinha.

    Sala é efêmera e não é gravada em lugar nenhum: existe enquanto houver
    alguém dentro (ver `app/chamada.py`).
    """
    sala = chamada.gerar_sala()
    return {"sala": sala, "url": f"{URL_PORTAL}/chamada/{sala}"}


@app.websocket("/ws/chamada/{sala_id}")
async def ws_chamada(ws: WebSocket, sala_id: str, papel: str = "cliente"):
    """Sinalização: repassa SDP e ICE entre os dois lados da chamada.

    O servidor não vê nem toca o áudio — ele só apresenta os dois navegadores.
    A `sala_id` é o token do portal do caso, que o cliente já tem e que não é
    adivinhável (256 bits).

    Protocolo:
        â†’ {"type":"offer"|"answer"|"ice", ...}   repassado ao outro lado
        â† {"type":"pronto"}                      o outro lado entrou
        â† {"type":"saiu"}                        o outro lado caiu
    """
    if papel not in ("advogado", "cliente"):
        await ws.close(code=4001)
        return

    await ws.accept()
    papel_tipado: chamada.Papel = papel  # type: ignore[assignment]
    _, tem_outro = await _salas.entrar(sala_id, papel_tipado, ws)

    # Quem chega por último sabe que pode ofertar; quem já estava é avisado.
    await ws.send_json({"type": "entrou", "papel": papel, "outroPresente": tem_outro})
    if tem_outro:
        await _salas.repassar(sala_id, papel_tipado, {"type": "pronto", "papel": papel})

    try:
        while True:
            msg = await ws.receive_json()
            tipo = msg.get("type")
            if tipo in ("offer", "answer", "ice", "encerrar"):
                entregue = await _salas.repassar(sala_id, papel_tipado, msg)
                if not entregue:
                    await ws.send_json({"type": "ausente"})
            elif tipo == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Erro na sinalização da chamada")
    finally:
        # Só avisa a saída se esta conexão ainda era a dona da vaga: uma aba que
        # recarregou já foi substituída, e o "saiu" derrubaria a chamada nova.
        if await _salas.sair(sala_id, papel_tipado, ws):
            await _salas.repassar(sala_id, papel_tipado, {"type": "saiu", "papel": papel})


class PedidoEstrategia(BaseModel):
    relato: str = Field(min_length=30, max_length=50_000)
    limite_precedentes: int = Field(default=8, ge=3, le=15)


@app.post("/api/estrategia")
async def estrategia(pedido: PedidoEstrategia):
    """Sugere próximos atos com precedentes recuperados antes da geração.

    Esta rota não é pública: passa pelo Keycloak. A resposta é apoio à decisão
    e inclui número, fonte, resultado e similaridade de cada precedente usado.
    """
    try:
        return await run_in_threadpool(
            rag.sugerir_acoes, pedido.relato, limite=pedido.limite_precedentes
        )
    except rag.ErroRAG as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("Falha na análise estratégica")
        raise HTTPException(status_code=503, detail="Base estratégica indisponível.") from exc


@app.post("/api/casos", status_code=201)
def criar_caso(cliente: str = Form(...), categoria: str = Form(...), observacao: str = Form("")):
    """Cria o caso já com o portal do cliente pronto.

    O link nasce junto com o caso porque é isso que o escritório manda ao cliente
    logo depois de abrir o processo. A senha vai NESTA resposta e em nenhuma
    outra — o banco guarda apenas o hash.
    """
    if not cliente.strip():
        raise HTTPException(400, "Informe o nome do cliente.")
    if categorias.obter(categoria) is None:
        raise HTTPException(400, f"Categoria '{categoria}' não existe.")

    caso = armazenamento.criar_caso(cliente, categoria, observacao)
    return {**caso, "portal": _criar_portal(caso["id"])}


@app.get("/api/casos")
def listar_casos():
    return {"casos": armazenamento.listar_casos()}


@app.get("/api/casos/{caso_id}")
def obter_caso(caso_id: str):
    situacao = casos.montar_situacao(caso_id)
    if situacao is None:
        raise HTTPException(404, "Caso não encontrado.")
    return situacao


@app.patch("/api/casos/{caso_id}")
def atualizar_caso(caso_id: str, cliente: str | None = Form(None), observacao: str | None = Form(None)):
    if not armazenamento.atualizar_caso(caso_id, cliente, observacao):
        raise HTTPException(404, "Caso não encontrado ou nada para atualizar.")
    return armazenamento.obter_caso(caso_id)


@app.delete("/api/casos/{caso_id}")
def excluir_caso(caso_id: str):
    if not armazenamento.excluir_caso(caso_id):
        raise HTTPException(404, "Caso não encontrado.")
    return {"removido": True}


@app.post("/api/casos/{caso_id}/portal", status_code=201)
def gerar_portal(caso_id: str):
    """Troca a senha do portal. O link e a senha anteriores param de valer.

    Serve para casos criados antes do portal existir e para quando o cliente
    perde a senha — que não tem como ser recuperada, só substituída.
    """
    if armazenamento.obter_caso(caso_id) is None:
        raise HTTPException(404, "Caso não encontrado.")
    return _criar_portal(caso_id)


@app.get("/api/casos/{caso_id}/portal")
def consultar_portal(caso_id: str):
    """Estado do portal. Devolve o link, nunca a senha."""
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")

    token = caso.get("portal_token")
    return {
        "ativo": bool(token),
        "url": f"{URL_PORTAL}/portal/{token}" if token else None,
        # O token já vai no `url`; sai em campo próprio porque é ele que nomeia
        # a sala da chamada, e recortar a URL na tela seria pior.
        "token": token,
        "criado_em": caso.get("portal_criado_em"),
    }


@app.get("/api/casos/{caso_id}/pedido")
def pedido_do_caso(caso_id: str, incluir_opcionais: bool = False):
    """Texto pronto para o advogado mandar ao cliente com o que ainda falta."""
    pedido = casos.montar_pedido(caso_id, incluir_opcionais)
    if pedido is None:
        raise HTTPException(404, "Caso não encontrado.")
    return pedido


def _ler_documento(
    entrega_id: str,
    caso_id: str,
    conteudo: bytes,
    nome: str,
    item_checklist,
    categoria,
    idioma: str,
    usar_para_rg_e_cpf: bool,
) -> None:
    """O OCR propriamente dito, já fora do ciclo da requisição.

    Roda numa thread de fundo: a requisição do upload não espera por isto. O
    PaddleOCR continua serializado na thread dele (ver `ocr_engine`), então
    vários envios simplesmente entram na fila em vez de brigar por CPU.
    """
    try:
        if item_checklist.tipo_ocr in {"rg", "cpf"}:
            tipo_extracao = "cin" if usar_para_rg_e_cpf else None
        else:
            tipo_extracao = item_checklist.tipo_ocr

        resultado = pipeline.processar(conteudo, nome, idioma, tipo_extracao)

        unificar = usar_para_rg_e_cpf
        if not unificar and item_checklist.tipo_ocr in {"rg", "cpf"}:
            unificar = casos.cobre_rg_e_cpf(resultado)

        try:
            itens_atendidos = (
                casos.itens_para_identidade_unificada(categoria, item_checklist)
                if unificar
                else [item_checklist.codigo]
            )
        except ValueError:
            itens_atendidos = [item_checklist.codigo]
            unificar = False

        detectado = resultado.get("tipo", {}).get("detectado")
        confere = casos.tipo_confere(item_checklist, detectado, unificar)
        armazenamento.concluir_entrega(entrega_id, resultado, confere, itens_atendidos)
        _entregar_ao_agente(caso_id, entrega_id)
    except Exception as exc:
        log.exception("Falha ao ler o documento da entrega %s", entrega_id)
        armazenamento.falhar_entrega(entrega_id, str(exc))


def _entregar_ao_agente(caso_id: str, entrega_id: str) -> None:
    """Empurra a extração recém-lida para o agente jurídico, se o caso estiver ligado.

    Só para caso **já vinculado**: vincular sozinho criaria caso no agente para toda
    foto que o cliente manda pelo portal, inclusive as de caso que ninguém abriu lá.

    Falha aqui não pode escapar. Já estamos fora da requisição, o documento está
    salvo e lido, e derrubar esta thread por indisponibilidade de outro serviço
    deixaria a entrega marcada como erro de leitura — que não foi o que aconteceu.
    """
    try:
        from .agente import espelho

        espelho.enviar_entrega(caso_id, entrega_id)
    except Exception:  # noqa: BLE001 - fronteira com serviço externo
        log.warning("não foi possível entregar %s ao agente jurídico", entrega_id, exc_info=True)


async def _registrar_documento(
    caso: dict[str, Any],
    item: str,
    arquivo: UploadFile,
    idioma: str,
    usar_para_rg_e_cpf: bool,
) -> dict[str, Any]:
    """OCR + registro da entrega. Compartilhado pelo advogado e pelo portal.

    O cliente passa pelo mesmo caminho de propósito: a validação de tipo, a
    legibilidade e o vínculo RG/CPF não podem depender de quem enviou.
    """
    caso_id = caso["id"]
    categoria = categorias.obter(caso["categoria"])
    if categoria is None:
        raise HTTPException(409, f"Categoria '{caso['categoria']}' não existe mais.")

    item_checklist = next((i for i in categoria.itens if i.codigo == item), None)
    if item_checklist is None:
        raise HTTPException(400, f"Item '{item}' não pertence ao checklist de {categoria.nome}.")

    # Valida a opção manual antes de gastar o OCR, para o erro sair na hora.
    if usar_para_rg_e_cpf:
        try:
            casos.itens_para_identidade_unificada(categoria, item_checklist)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    conteudo = await _ler_upload(arquivo)
    nome = arquivo.filename or "sem-nome"

    # O arquivo vai para o disco e a entrega é criada ANTES do OCR: é isso que
    # permite responder o upload em milissegundos. Medido nesta máquina, a
    # leitura leva de 12s (ociosa) a 200s (saturada) — tempo demais para segurar
    # uma requisição de celular, que morreria por timeout no meio.
    destino = armazenamento.DIR_ARQUIVOS / caso_id
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{item}_{uuid.uuid4()}{Path(nome).suffix.lower()}"
    caminho.write_bytes(conteudo)

    entrega = armazenamento.registrar_entrega_pendente(caso_id, item, nome, caminho)

    # Passar o tipo esperado orienta a extração dos campos, mas o classificador
    # continua opinando por conta própria — é a opinião dele que revela se veio o
    # arquivo trocado. A decisão fica em `_ler_documento`, junto do OCR.
    threading.Thread(
        target=_ler_documento,
        args=(
            entrega["id"], caso_id, conteudo, nome,
            item_checklist, categoria, idioma, usar_para_rg_e_cpf,
        ),
        name=f"ocr-{entrega['id'][:8]}",
        daemon=True,
    ).start()

    return {"entrega": entrega, "processando": True}


@app.post("/api/casos/{caso_id}/documentos", status_code=201)
async def enviar_documento(
    caso_id: str,
    item: str = Form(...),
    arquivo: UploadFile = File(...),
    idioma: str = Form("pt"),
    usar_para_rg_e_cpf: bool = Form(False),
):
    """Recebe um documento, roda o OCR e marca o item do checklist."""
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")
    return await _registrar_documento(caso, item, arquivo, idioma, usar_para_rg_e_cpf)


# ---------------------------------------------------------------- entrevista
#
# A entrevista é do caso, não do agente: o arquivo do atendimento existe mesmo com a
# integração desligada, e é aqui que ele fica. Quem manda o texto para o agente virar
# fato é a ponte (`app/agente/rotas.py`), depois de o arquivo estar guardado.


@app.post("/api/casos/{caso_id}/entrevista", status_code=201)
async def enviar_entrevista(
    caso_id: str,
    arquivo: UploadFile = File(...),
    realizada_em: str = Form(""),
    entrevistador: str = Form(""),
):
    """Guarda o arquivo da entrevista e o texto lido dele."""
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")

    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")
    if len(conteudo) > MAX_BYTES:
        raise HTTPException(413, "Arquivo grande demais.")

    nome = Path(arquivo.filename or "entrevista.txt").name
    try:
        texto = entrevista_lib.extrair_texto(nome, conteudo)
    except entrevista_lib.ErroDeLeitura as erro:
        raise HTTPException(400, str(erro)) from erro

    destino = armazenamento.DIR_ARQUIVOS / caso_id / "entrevistas"
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{uuid.uuid4().hex[:8]}-{nome}"
    caminho.write_bytes(conteudo)

    return armazenamento.registrar_entrevista(
        caso_id,
        arquivo=nome,
        caminho=caminho,
        texto=texto,
        realizada_em=realizada_em.strip(),
        entrevistador=entrevistador.strip(),
    )


@app.get("/api/casos/{caso_id}/entrevistas")
def listar_entrevistas(caso_id: str):
    if armazenamento.obter_caso(caso_id) is None:
        raise HTTPException(404, "Caso não encontrado.")
    return {"entrevistas": armazenamento.listar_entrevistas(caso_id)}


@app.get("/api/casos/{caso_id}/entrevista/{entrevista_id}")
def obter_entrevista(caso_id: str, entrevista_id: str):
    """A entrevista com o texto inteiro — é o que o advogado abre para reler."""
    return _entrevista_do_caso(caso_id, entrevista_id)


@app.get("/api/casos/{caso_id}/entrevista/{entrevista_id}/arquivo")
def baixar_entrevista(caso_id: str, entrevista_id: str):
    """O arquivo original, como o advogado o enviou."""
    registro = _entrevista_do_caso(caso_id, entrevista_id)
    caminho = Path(registro["caminho"]).resolve()
    if armazenamento.DIR_ARQUIVOS.resolve() not in caminho.parents or not caminho.is_file():
        raise HTTPException(404, "Arquivo da entrevista não encontrado.")
    return FileResponse(
        caminho,
        filename=registro["arquivo"],
        media_type="application/octet-stream",
    )


@app.delete("/api/casos/{caso_id}/entrevista/{entrevista_id}")
def excluir_entrevista(caso_id: str, entrevista_id: str):
    """Remove a entrevista do caso. Os fatos que ela gerou continuam no agente."""
    _entrevista_do_caso(caso_id, entrevista_id)
    armazenamento.excluir_entrevista(entrevista_id)
    return {"removido": True}


def _entrevista_do_caso(caso_id: str, entrevista_id: str) -> dict[str, Any]:
    registro = armazenamento.obter_entrevista(entrevista_id)
    if registro is None or registro["caso_id"] != caso_id:
        raise HTTPException(404, "Entrevista não encontrada neste caso.")
    return registro


@app.post("/api/casos/{caso_id}/identidade-unificada")
async def vincular_identidade_unificada(caso_id: str, entrega_id: str = Form(...)):
    """Faz uma entrega de RG/CPF existente valer para os dois itens quando for CIN."""
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")

    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None or entrega["caso_id"] != caso_id:
        raise HTTPException(404, "Entrega não encontrada neste caso.")

    categoria = categorias.obter(caso["categoria"])
    item = next((i for i in categoria.itens if i.codigo == entrega["item_codigo"]), None) if categoria else None
    if item is None:
        raise HTTPException(400, "Esta entrega não pertence a um item de checklist válido.")
    try:
        itens_atendidos = casos.itens_para_identidade_unificada(categoria, item)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    caminho = Path(entrega["caminho"]).resolve()
    if armazenamento.DIR_ARQUIVOS.resolve() not in caminho.parents or not caminho.is_file():
        raise HTTPException(404, "Arquivo original não encontrado.")

    # O botão é a confirmação expressa de que se trata de identidade unificada.
    # Reprocessamos no layout da CIN para extrair e validar o CPF sem depender de
    # o classificador conseguir nomear corretamente todas as versões do documento.
    resultado = await _processar(caminho.read_bytes(), entrega["arquivo"], "pt", "cin")

    atualizada = armazenamento.atualizar_para_identidade_unificada(
        entrega_id, resultado, itens_atendidos
    )
    if atualizada is None:
        raise HTTPException(404, "Entrega não encontrada.")
    return {"entrega": atualizada, "extracao": resultado}


# ------------------------------------------------------ portal do cliente
#
# Estas rotas são públicas (não passam pelo Keycloak): quem as protege é a senha
# do caso. Cada uma confere a sessão do portal por conta própria — não há
# dependência global que faça isso por elas.


def _caso_do_portal(token: str, request: Request) -> dict[str, Any]:
    """Resolve o caso pelo token E exige uma sessão válida deste caso."""
    caso = armazenamento.obter_caso_por_token(token)
    if caso is None:
        # Mesma resposta de sessão inválida: não confirmamos se o link existe.
        raise HTTPException(404, "Link inválido ou expirado.")

    cabecalho = request.headers.get("authorization", "")
    sessao = cabecalho[7:].strip() if cabecalho.lower().startswith("bearer ") else ""
    if not portal.validar_sessao(sessao, token):
        raise HTTPException(401, "Informe a senha para acessar seus documentos.")
    return caso


@app.post("/api/portal/{token}/entrar")
def portal_entrar(token: str, senha: str = Form(...)):
    espera = portal.bloqueado(token)
    if espera > 0:
        raise HTTPException(
            429,
            f"Muitas tentativas. Tente novamente em {espera // 60 + 1} minuto(s) "
            "ou peça uma senha nova ao escritório.",
        )

    caso = armazenamento.obter_caso_por_token(token)
    # Link inexistente e senha errada devolvem a mesma coisa, para o link não
    # virar um oráculo que diz quais casos existem.
    if caso is None or not caso.get("portal_senha_hash"):
        portal.registrar_falha(token)
        raise HTTPException(401, "Link ou senha incorretos.")

    if not portal.conferir_senha(senha, caso["portal_senha_hash"], caso["portal_sal"]):
        portal.registrar_falha(token)
        raise HTTPException(401, "Link ou senha incorretos.")

    portal.limpar_tentativas(token)
    return {**portal.criar_sessao(token), "cliente": caso["cliente"]}


@app.get("/api/portal/{token}/situacao")
def portal_situacao(token: str, request: Request):
    """O checklist na visão do cliente: o que chegou e o que falta."""
    caso = _caso_do_portal(token, request)
    situacao = casos.montar_situacao(caso["id"])
    if situacao is None:
        raise HTTPException(404, "Caso não encontrado.")
    return casos.visao_do_cliente(situacao)


@app.post("/api/portal/{token}/documentos", status_code=201)
async def portal_enviar(
    token: str,
    request: Request,
    item: str = Form(...),
    arquivo: UploadFile = File(...),
):
    """Upload feito pelo cliente. Mesmo caminho do advogado, resposta enxuta."""
    caso = _caso_do_portal(token, request)
    await _registrar_documento(caso, item, arquivo, "pt", False)

    situacao = casos.montar_situacao(caso["id"])
    return casos.visao_do_cliente(situacao) if situacao else {}


@app.get("/api/entregas/{entrega_id}")
def obter_entrega(entrega_id: str):
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")
    entrega.pop("caminho", None)  # caminho no disco não interessa ao cliente HTTP
    return entrega


@app.post("/api/entregas/{entrega_id}/leitura")
async def ler_documento(entrega_id: str):
    """Interpreta o texto que o OCR extraiu: para que este documento serve.

    Existe porque o classificador do OCR conhece documento de IDENTIDADE, e os
    que decidem a ação — CAT, laudo, boletim, CNIS, contracheque — caem em
    "desconhecido" com o texto lido e ninguém para lê-lo (ver
    `app/valor_documento.py`).

    Não decide item do checklist: o status continua vindo do arquivo entregue,
    não de opinião de modelo. O que sai daqui é leitura, rotulada como tal.
    """
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")
    if not entrega.get("extracao"):
        raise HTTPException(409, "O documento ainda está sendo lido pelo OCR.")

    # Só os itens em aberto: mandar os doze faria o modelo "resolver" o que já
    # foi entregue, e o prompt cresceria sem ganho.
    situacao = casos.montar_situacao(entrega["caso_id"])
    pendencias: list[dict[str, str]] = []
    categoria_nome = ""
    if situacao:
        categoria = situacao.get("categoria") or {}
        categoria_nome = str(
            (categoria.get("nome") if isinstance(categoria, dict) else categoria) or ""
        )
        pendencias = [
            {"codigo": str(i.get("codigo", "")), "nome": str(i.get("nome", ""))}
            for i in situacao.get("itens", [])
            if i.get("status") == "pendente"
        ]

    try:
        return await run_in_threadpool(
            valor_documento.ler, entrega["extracao"], pendencias, categoria_nome
        )
    except valor_documento.ErroValor as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/entregas/{entrega_id}/arquivo")
def baixar_arquivo_entrega(entrega_id: str, download: bool = False):
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")

    caminho = Path(entrega["caminho"]).resolve()
    if armazenamento.DIR_ARQUIVOS.resolve() not in caminho.parents or not caminho.is_file():
        raise HTTPException(404, "Arquivo não encontrado no disco.")

    # `inline` deixa o navegador exibir o arquivo em vez de baixá-lo, que é o que
    # permite a pré-visualização no checklist. Passar só `filename=` produzia
    # `Content-Disposition: attachment` e obrigava a baixar para ver o que chegou.
    # Com `?download=1` o comportamento antigo continua disponível.
    return FileResponse(
        caminho,
        filename=entrega["arquivo"],
        content_disposition_type="attachment" if download else "inline",
    )


@app.delete("/api/entregas/{entrega_id}")
def excluir_entrega(entrega_id: str):
    if not armazenamento.excluir_entrega(entrega_id):
        raise HTTPException(404, "Entrega não encontrada.")
    return {"removido": True}


@app.get("/api/temp/{nome}")
def baixar_temp(nome: str):
    """Serve o JSON/XML temporário gerado para um documento."""
    if not nome.endswith((".json", ".xml")) or "/" in nome or "\\" in nome or ".." in nome:
        raise HTTPException(400, "Nome de arquivo inválido.")

    caminho = (pipeline.TMP_DIR / nome).resolve()
    if pipeline.TMP_DIR.resolve() not in caminho.parents or not caminho.is_file():
        raise HTTPException(404, "Arquivo temporário não encontrado ou já expirado.")

    media = "application/json" if nome.endswith(".json") else "application/xml"
    return FileResponse(caminho, media_type=media, filename=nome)


@app.delete("/api/temp")
def limpar():
    return {"removidos": pipeline.limpar_temporarios()}
