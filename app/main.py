"""API do extrator de documentos (FastAPI + Mistral OCR)."""

from __future__ import annotations

import json
import io
import logging
import os
import re
import threading
import time
import uuid
import zipfile

import httpx
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import jwt

from fastapi import (
    BackgroundTasks,
    Body,
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
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from . import (
    agente,
    advbox,
    analise_documentos,
    analise_resposta,
    armazenamento,
    assinatura,
    auth,
    carteira,
    casos,
    categorias,
    chamada,
    consultas,
    conversao_pdf,
    investigacao,
    localidades,
    usuarios,
    supervisao,
    dados,
    documentacao,
    docx_pdf,
    contrato,
    escuta,
    perfis,
    painel as painel_do_caso,
    panorama,
    pipeline,
    portal,
    rag,
    recomendacao,
    relatorio,
    roteamento,
    roteiros,
    triagem,
    valor_documento,
    whatsapp,
)
from . import jobs, observabilidade
from . import entrevista as entrevista_lib
from . import roteiro_ia
from .cache_leitura import por_alguns_segundos
from .agente import dossie as dossie_agente
from .celery_app import celery_app
from .extractors import ROTULOS_TIPO
from .tasks.ocr import processar_documento, processar_entrega
from .tasks.documentos import gerar_relatorio as gerar_relatorio_job
from .tasks.ia import gerar_estrategia as gerar_estrategia_job
from .tasks.roteiro import importar_roteiro as importar_roteiro_task

# Onde o frontend atende — é o que monta o link enviado ao cliente.
URL_PORTAL = os.getenv("URL_PORTAL", "http://localhost:3000").rstrip("/")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("api")

BASE = Path(__file__).resolve().parent.parent
STATIC = BASE / "static"

MAX_BYTES = 20 * 1024 * 1024
_ocr_aquecido = threading.Event()


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    """Inicializa a API sem duplicar o Paddle que pertence ao worker Celery.

    A tela envia arquivos a `/api/extrair/jobs`; quem os lê é o worker `ocr@`,
    aquecido em `tasks/ocr.py`. Carregar outro modelo aqui gastava memória e CPU
    sem reduzir a latência real. O opt-in preserva o endpoint síncrono legado.
    """
    if os.getenv("OCR_AQUECER_API", "0") == "1":
        threading.Thread(
            target=_tentar_aquecer, name="aquecer-ocr", daemon=True
        ).start()
    try:
        await run_in_threadpool(jobs.inicializar)
    except Exception:
        log.exception("Não foi possível inicializar a tabela de jobs")
    try:
        # Cria a matriz perfil x módulo e garante os perfis de sistema. Falhar
        # aqui não impede a API de subir: sem a tabela, `exigir_modulo` nega
        # tudo, que é o lado seguro de errar — o contrário abriria os módulos.
        await run_in_threadpool(perfis.inicializar)
    except Exception:
        log.exception("Não foi possível inicializar os perfis de acesso")
    try:
        # Cria a tabela de contas e garante que exista pelo menos uma, senão um
        # ambiente novo sobe com a autenticação ligada e nenhum jeito de entrar.
        await run_in_threadpool(usuarios.inicializar)
    except Exception:
        log.exception("Não foi possível inicializar as contas de usuário")
    try:
        await run_in_threadpool(localidades.inicializar)
    except Exception:
        log.exception("Não foi possível sincronizar as localidades do IBGE")
    try:
        await run_in_threadpool(documentacao.inicializar)
    except Exception:
        log.exception("Não foi possível inicializar a fila de documentação")
    yield


app = FastAPI(
    title="Extrator de Documentos — Mistral OCR",
    version="1.0.0",
    lifespan=ciclo_de_vida,
)
observabilidade.configurar(app)

# O frontend Next chama esta API direto do navegador, então precisa de CORS.
# Com autenticação passou a existir credencial em jogo (o cookie `JwtToken`), então a
# lista de origens deixou de ser `*` e virou explícita — um `*` permitiria que qualquer
# página lesse as respostas. Não é só boa prática: com `allow_credentials=True` o
# navegador RECUSA a resposta se a origem vier como `*`, então a lista explícita é o que
# faz o cookie funcionar.
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

#: Origens aceitas por PADRÃO DE ENDEREÇO, além da lista fixa acima.
#:
#: A lista fixa só serve a quem abre o sistema NA MÁQUINA que o hospeda. Abrindo
#: de outro computador da rede, a origem passa a ser `http://192.168.x.x:3000` e o
#: navegador descarta toda resposta — a API responde 200 e a tela mostra "Failed
#: to fetch", que é o sintoma mais enganoso que existe aqui.
#:
#: Não dá para resolver com `allow_origins=["*"]`: o login usa cookie, e a
#: especificação de CORS proíbe curinga junto de credencial. `allow_origin_regex`
#: é o mecanismo correto.
#:
#: O padrão cobre localhost e as três faixas privadas de IPv4 — a rede do
#: escritório. Endereço público NÃO entra: para publicar num domínio, preencha
#: `ORIGENS_PERMITIDAS` com ele, explicitamente.
ORIGENS_REGEX = os.getenv(
    "ORIGENS_REGEX",
    r"^https?://("
    r"localhost|127\.0\.0\.1|\[::1\]"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r")(:\d+)?$",
).strip()

# Rotas que respondem sem token. Tudo que não estiver aqui exige autenticação —
# a lista é de exceções justamente para que uma rota nova nasça protegida.
# `/api/chamada/config` entra aqui porque quem mais precisa dela é o cliente, que
# não tem conta no sistema. Não há segredo na resposta: é a lista de STUN
# públicos, a mesma que qualquer navegador do mundo usa.
#
# `/api/user/authenticate` é a porta: exigir token para pedir token trancaria o
# sistema por fora. `/api/user/logout` também, para que apagar o cookie funcione
# mesmo com a sessão já vencida — é justamente aí que a tela mais precisa dela.
PUBLICAS = {
    "/",
    "/api/saude",
    "/api/config",
    "/api/chamada/config",
    "/api/chamada/sala",
    "/api/user/authenticate",
    "/api/user/logout",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/metrics",  # raspado pelo Prometheus, que não manda Authorization
}

# O portal do cliente não passa pelo login do escritório: o cliente não tem conta.
# Quem o protege é a senha do caso, conferida dentro de cada rota `/api/portal/...`
# (ver `_caso_do_portal`). O prefixo é fechado de propósito — nenhuma outra
# rota entra por aqui.
PREFIXO_PORTAL = "/api/portal/"

# ENTRAR NUMA CHAMADA NÃO PODE PEDIR LOGIN.
#
# Quem abre o link da chamada é o cliente, e ele não tem conta — a página diz
# isso na cara: "não precisa instalar nada, criar conta nem informar o seu
# número". Só que a rota que devolve o token do Jitsi exigia sessão, e o
# navegador dele batia em 401: o link público abria uma tela de login.
#
# A sala vai no CAMINHO, e não no corpo, justamente para o middleware poder
# liberar por prefixo. E é seguro pelo mesmo motivo do portal: o nome da sala
# são 256 bits sorteados, e quem não tem o link não o adivinha. Criar sala NOVA
# continua exigindo sessão — isso é ato do escritório.
PREFIXO_CHAMADA = "/api/chamada/sala/"

# O QUE ALGUÉM SEM O PAPEL `advogado` ALCANÇA — e por que a lista é esta.
#
# Até aqui `exigir_papel` não era usado em rota nenhuma: bastava estar
# autenticado para chegar em tudo, o que funcionava porque só advogado tinha
# conta. Com o cadastro de usuários (`app/usuarios.py`) passou a existir o perfil
# `cliente`, e sem esta barreira uma conta dessas leria o acervo INTEIRO — todos
# os casos, documentos e entrevistas do escritório.
#
# A lista é fechada e curta de propósito: nega por padrão. Rota nova nasce
# fechada para quem não é advogado, que é o lado seguro de errar — o contrário
# vazaria acervo sem ninguém notar.
#
# Isto não fecha porta do cliente: ele nunca entrou por aqui. O caminho dele é o
# `/api/portal/...`, protegido pela senha do caso (ver o comentário acima).
#: Quem é "de dentro". O cliente não está aqui de propósito: o caminho dele é o
#: portal do caso, não esta API.
PAPEIS_INTERNOS = ("advogado", "secretario", "documentacao")

LIVRES_SEM_ADVOGADO = {
    "/api/eu",  # saber quem se é
    "/api/user/my-account",  # idem, no endereço do padrão DFLegal
    "/api/user/change-password",  # trocar a PRÓPRIA senha não é área restrita
    "/api/usuarios/perfis",  # vocabulário dos perfis, não dado de ninguém
}

# Módulo do agente jurídico. Fica num APIRouter próprio porque é ponte para outro
# serviço: se a ligação for desligada, some um bloco inteiro de rotas em vez de
# restarem funções mortas espalhadas por este arquivo.
app.include_router(agente.roteador)
app.include_router(advbox.roteador)
app.include_router(investigacao.roteador)
app.include_router(localidades.roteador)
app.include_router(usuarios.roteador)
app.include_router(usuarios.roteador_sessao)
app.include_router(supervisao.roteador)
app.include_router(dados.roteador)
app.include_router(documentacao.roteador)
app.include_router(whatsapp.roteador)


@app.middleware("http")
async def exigir_autenticacao(request: Request, call_next):
    caminho = request.url.path
    # O preflight não carrega credencial nenhuma; recusá-lo quebraria todo o CORS.
    livre = (
        request.method == "OPTIONS"
        or caminho in PUBLICAS
        or caminho.startswith(PREFIXO_PORTAL)
        or caminho.startswith(PREFIXO_CHAMADA)
    )

    if auth.ATIVA and not livre:
        try:
            request.state.usuario = auth.usuario_atual(request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

        # Autenticado não basta: sem `advogado`, só o que estiver na lista.
        if (
            not any(request.state.usuario.tem_papel(p) for p in PAPEIS_INTERNOS)
            and caminho not in LIVRES_SEM_ADVOGADO
        ):
            return JSONResponse(
                {"detail": "Esta área é restrita ao perfil Advogado."},
                status_code=403,
            )
    else:
        request.state.usuario = auth.USUARIO_ABERTO

    return await call_next(request)


# Registrado depois da autenticação para ficar na camada externa do Starlette.
# Assim até um 401 recebe CORS; antes o navegador escondia a resposta e exibia
# apenas o enganoso "Failed to fetch".
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENS,
    allow_origin_regex=ORIGENS_REGEX or None,
    # O cookie de sessão só acompanha a requisição se o servidor autorizar
    # credencial na origem — é o par do `credentials: "include"` do frontend.
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=[
        "Content-Disposition",
        "X-Campos-Faltando",
        "X-Pendencias",
        "X-Impedimentos",
        "X-Arquivos",
        "X-Faltando",
    ],
)


armazenamento.inicializar()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/tipos")
def tipos():
    return {"tipos": [{"codigo": k, "descricao": v} for k, v in ROTULOS_TIPO.items()]}


@app.get("/api/roteiros")
def listar_roteiros():
    """Roteiros de entrevista disponíveis, sem as perguntas.

    `importado` diz se aquele roteiro tem uma versão salva no catálogo. É o que
    a tela usa para oferecer "voltar ao original": só faz sentido em quem tem
    original para voltar.
    """
    salvos = {r["codigo"]: r for r in _roteiros_salvos()}
    return {
        "roteiros": [
            {
                "codigo": r.codigo,
                "nome": r.nome,
                "descricao": r.descricao,
                "importado": r.codigo in salvos,
                "origem": salvos.get(r.codigo, {}).get("origem", ""),
                "criado_por": salvos.get(r.codigo, {}).get("criado_por", ""),
                "atualizado_em": salvos.get(r.codigo, {}).get("atualizado_em", ""),
            }
            for r in roteiros.listar()
        ]
    }


def _roteiros_salvos() -> list[dict[str, Any]]:
    """O catálogo do banco, ou vazio se ele ainda não existe.

    A listagem de roteiros não pode falhar por causa da tabela: sem ela o
    escritório ainda tem o roteiro escrito em `app/roteiros.py`, que é o que se
    usa todo dia.
    """
    try:
        return armazenamento.listar_roteiros()
    except Exception:
        log.debug("Catálogo de roteiros indisponível.", exc_info=True)
        return []


class PedidoContrato(BaseModel):
    """As respostas do roteiro, como a tela as tem em mãos."""

    respostas: dict[str, Any]
    #: Onde o contrato é assinado. Vazio: tenta deduzir do endereço.
    municipio: str = ""
    #: Qual dos documentos da papelada. Ver `contrato.MODELOS`.
    documento: str = "contrato"
    formato: str = "docx"


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
    # Documento desconhecido é erro de quem chamou, não do serviço: sem esta
    # barreira ele cairia no 503 lá embaixo, mandando procurar o problema no
    # servidor em vez de na requisição.
    if pedido.documento not in contrato.CODIGOS:
        raise HTTPException(
            422,
            f"Documento {pedido.documento!r} não existe. Conhecidos: {', '.join(contrato.CODIGOS)}.",
        )
    if pedido.formato not in {"docx", "pdf"}:
        raise HTTPException(422, "Formato inválido: escolha docx ou pdf.")

    try:
        alvo = contrato.modelo(pedido.documento)
        respostas = contrato.normalizar_respostas(pedido.respostas)
        docx, faltando = contrato.gerar(
            respostas, pedido.municipio, codigo=pedido.documento
        )
    except contrato.DadosObrigatoriosContrato as exc:
        raise HTTPException(422, str(exc)) from exc
    except contrato.ErroContrato as exc:
        raise HTTPException(503, str(exc)) from exc

    nome_cliente = str(respostas["nome"])
    extensao = pedido.formato
    arquivo = f"{alvo['arquivo']} - {nome_cliente}.{extensao}".replace(
        "/", "-"
    ).replace("\\", "-")

    if pedido.formato == "pdf":
        try:
            conteudo = docx_pdf.converter(docx)
        except docx_pdf.ErroConversaoDocx as exc:
            raise HTTPException(503, str(exc)) from exc
        media_type = "application/pdf"
    else:
        conteudo = docx
        media_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    return Response(
        content=conteudo,
        media_type=media_type,
        headers={
            # `filename*` em UTF-8 porque nome de cliente tem acento, e o
            # `filename` sem aspas quebraria no primeiro espaço.
            "Content-Disposition": (
                f'attachment; filename="{pedido.documento}.{extensao}"; '
                f"filename*=UTF-8''{quote(arquivo)}"
            ),
            "X-Campos-Faltando": ", ".join(faltando),
        },
    )


# ------------------------------------------- modelos .docx do escritorio
#
# O contrato de honorarios nao e versionado (traz honorarios, CNPJ e as OAB), e
# por isso nao existe em `docs/` dentro do conteiner. Estas rotas sao como ele
# chega la: sobe uma vez, fica no banco, vale para todos os conteineres. Ver
# `contrato.caminho_modelo` e a tabela em `app/banco.py`.

PodeManterModelos = Depends(auth.exigir_modulo("contratos"))


#: Onde a API alcança o serviço de transcrição por dentro da rede do cluster.
#:
#: Em produção o navegador chega na transcrição pelo Traefik, que só roteia
#: `/ws/transcricao` e `/entrevista` — o `/saude` dela NÃO é alcançável de fora.
#: A API está na mesma rede `interna` e pode perguntar por ela.
URL_TRANSCRICAO_INTERNA = os.getenv(
    "URL_TRANSCRICAO_INTERNA", "http://localhost:8200"
).rstrip("/")


@app.get("/api/saude/transcricao")
async def saude_da_transcricao():
    """O estado do serviço de transcrição, visto de dentro do cluster.

    POR QUE ESTA ROTA EXISTE

    A transcrição parou em produção e o diagnóstico levou horas porque o sintoma
    — "fica ouvindo e nada aparece" — é o mesmo para chave ausente, crédito no
    fim, modelo fora do ar e serviço morto. O motivo real ficava no log do
    contêiner, que ninguém alcança do meio de um atendimento.

    `modelo_carregado` é o que responde a pergunta mais cara: com a OpenRouter
    ele significa **a chave está no ambiente do contêiner**. Falso aqui, com o
    serviço respondendo, é configuração faltando — não rede, não modelo.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as cliente:
            resposta = await cliente.get(f"{URL_TRANSCRICAO_INTERNA}/saude")
            resposta.raise_for_status()
            dados = resposta.json()
    except Exception as exc:
        # 200 com `alcancavel: false`, e não 5xx: a pergunta "o serviço está de
        # pé?" foi respondida com sucesso — a resposta é que não está.
        return {
            "alcancavel": False,
            "url": URL_TRANSCRICAO_INTERNA,
            "erro": f"{type(exc).__name__}: {str(exc)[:200]}",
        }

    return {
        "alcancavel": True,
        "url": URL_TRANSCRICAO_INTERNA,
        **dados,
        # Explícito para quem lê a resposta sem conhecer o código do serviço.
        "chave_presente": bool(dados.get("modelo_carregado")),
    }


@app.get("/api/modelos")
async def listar_modelos(_autorizado=PodeManterModelos):
    """Os modelos guardados no banco e de onde cada documento esta vindo.

    `origem` e o que responde a pergunta que aparece quando um contrato sai
    errado: o arquivo que gerou este documento e o que subiram pela tela, ou um
    que ficou no disco do servidor?
    """
    guardados = {
        m["codigo"]: m for m in await run_in_threadpool(armazenamento.listar_modelos)
    }
    saida = []
    for alvo in contrato.MODELOS:
        codigo = alvo["codigo"]
        registro = guardados.get(codigo)
        try:
            caminho = await run_in_threadpool(contrato.caminho_modelo, codigo)
            nome, disponivel = caminho.name, True
        except contrato.ErroContrato:
            nome, disponivel = "", False
        saida.append(
            {
                "codigo": codigo,
                "rotulo": alvo["rotulo"],
                "disponivel": disponivel,
                "origem": "banco"
                if registro
                else ("docs" if disponivel else "nenhuma"),
                "arquivo": registro["nome_arquivo"] if registro else nome,
                "enviado_por": registro["enviado_por"] if registro else "",
                "atualizado_em": registro["atualizado_em"] if registro else "",
            }
        )
    return {"modelos": saida}


@app.post("/api/modelos/{codigo}", status_code=201)
async def enviar_modelo(
    codigo: str,
    arquivo: UploadFile = File(...),
    usuario: auth.Usuario = PodeManterModelos,
):
    """Guarda o .docx daquele documento no banco, substituindo o anterior."""
    try:
        alvo = contrato.modelo(codigo)
    except contrato.ErroContrato as exc:
        raise HTTPException(404, str(exc)) from exc

    nome = arquivo.filename or f"{codigo}.docx"
    if Path(nome).suffix.lower() != ".docx":
        raise HTTPException(400, "O modelo precisa ser um arquivo .docx.")

    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")
    if len(conteudo) > MAX_BYTES:
        raise HTTPException(413, f"Arquivo maior que {MAX_BYTES // (1024 * 1024)}MB.")
    # Conferir ANTES de gravar: um .docx corrompido guardado no banco quebraria a
    # geracao de todo mundo, e o erro apareceria na hora de fechar um contrato.
    if not zipfile.is_zipfile(io.BytesIO(conteudo)):
        raise HTTPException(400, "Este arquivo nao e um .docx valido.")

    registro = await run_in_threadpool(
        armazenamento.salvar_modelo,
        codigo,
        nome_arquivo=nome,
        conteudo=conteudo,
        enviado_por=usuario.nome,
    )
    return {"codigo": codigo, "rotulo": alvo["rotulo"], **registro}


@app.delete("/api/modelos/{codigo}")
async def excluir_modelo(codigo: str, _autorizado=PodeManterModelos):
    """Tira o modelo do banco. O arquivo de `docs/` volta a valer, se houver."""
    if not await run_in_threadpool(armazenamento.excluir_modelo, codigo):
        raise HTTPException(404, f"Nenhum modelo guardado para {codigo!r}.")
    return {"codigo": codigo}


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
            m
            for m in marcadores
            if m not in {contrato._chave(f"[{k}]") for k in preenchiveis}
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


@app.post("/api/entrevista/relatorio/jobs", status_code=202)
async def enfileirar_relatorio(pedido: PedidoRelatorio):
    await run_in_threadpool(jobs.inicializar)
    job_id = await run_in_threadpool(jobs.criar, "PDF")
    tarefa = gerar_relatorio_job.apply_async(
        args=(job_id, pedido.model_dump()), queue="documents", priority=4
    )
    await run_in_threadpool(jobs.vincular_tarefa, job_id, tarefa.id)
    return {"job_id": job_id, "task_id": tarefa.id, "status": "QUEUED", "progresso": 0}


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

    arquivo = f"Relatório de entrevista - {dados['cliente']}.pdf".replace(
        "/", "-"
    ).replace("\\", "-")
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
    #: Qual pergunta está na vez NA TELA. Sem ela o backend adivinha "a primeira
    #: em aberto", e erra sempre que a condução pula adiante — que é o normal.
    pergunta_atual: str = Field(default="", max_length=80)


class PedidoProcessamentoEntrevista(BaseModel):
    """A conversa completa, enviada uma única vez depois do encerramento."""

    transcricao: str = Field(min_length=1, max_length=80_000)
    respostas: dict[str, Any] = Field(default_factory=dict)
    roteiro: str = Field(default="empregado_publico", max_length=60)
    #: Buscar precedentes no pgvector para sugerir perguntas e apontar lacunas.
    #: Melhor-esforço: banco fora do ar não impede o preenchimento do formulário.
    analisar: bool = True


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
            escuta.escutar,
            pedido.trecho,
            pedido.respostas,
            pedido.roteiro,
            pedido.pergunta_atual,
        )
    except escuta.ErroEscuta as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/entrevista/processar")
async def processar_entrevista(pedido: PedidoProcessamentoEntrevista):
    """Consolida a transcrição, preenche o formulário e diz o que mais perguntar.

    Duas leituras independentes, em PARALELO porque nenhuma depende da outra e
    quem conduz está esperando com o cliente ainda na sala:

    - `escuta.processar_entrevista` diz o que a conversa respondeu do roteiro,
      cada campo com o trecho da transcrição que o sustenta;
    - `rag.sugerir_acoes` compara o relato com o acervo vetorial e devolve o que
      processos parecidos mostraram ser necessário — perguntas que valem a pena
      e lacunas que costumam custar caro.

    Separadas de propósito. Num prompt só, o precedente contaminaria a leitura: o
    modelo passaria a "encontrar" na conversa o que a jurisprudência sugeriu que
    deveria estar lá, e o campo preenchido deixaria de ser o que o cliente disse.
    """
    analise: dict[str, Any] | None = None
    erro_analise = ""

    def _analisar() -> None:
        nonlocal analise, erro_analise
        if not pedido.analisar:
            return
        try:
            analise = rag.sugerir_acoes(pedido.transcricao[:12_000])
        except Exception as exc:  # noqa: BLE001 — melhor-esforço, ver docstring
            # O formulário não pode cair junto com o banco de precedentes: ele é
            # a parte que o escritório não consegue refazer à mão, e o pgvector
            # já ficou fora do ar (CONTEXTO.md).
            erro_analise = str(exc)[:200]
            log.warning("Análise por precedentes falhou: %s", erro_analise)

    tarefa = threading.Thread(
        target=_analisar, name="entrevista-precedentes", daemon=True
    )
    tarefa.start()

    try:
        resultado = await run_in_threadpool(
            escuta.processar_entrevista,
            pedido.transcricao,
            pedido.respostas,
            pedido.roteiro,
        )
    except escuta.ErroEscuta as exc:
        raise HTTPException(503, str(exc)) from exc
    finally:
        # Esperar aqui é o que permite devolver as duas juntas: a tela mostra um
        # resultado só, no fim da entrevista.
        tarefa.join(timeout=escuta.TEMPO_PROCESSAMENTO_S)

    return {**resultado, "analise": analise, "analise_indisponivel": erro_analise}


class PedidoAnaliseResposta(BaseModel):
    """Uma resposta narrativa recém-dada, para conferência imediata."""

    pergunta_id: str = Field(max_length=120)
    pergunta: str = Field(max_length=1_000)
    resposta: str = Field(max_length=20_000)
    #: O pouco que já se sabe do caso — a categoria triada, tipicamente. Evita
    #: que a análise peça o que outra pergunta do roteiro já respondeu.
    contexto: str = Field(default="", max_length=4_000)


class PedidoRecomendacao(BaseModel):
    """Estado consolidado da entrevista, nunca fragmento provisório do Whisper."""

    relato: str = Field(min_length=40, max_length=40_000)
    lacunas_obrigatorias: list[str] = Field(default_factory=list, max_length=120)
    limite_precedentes: int = Field(default=12, ge=4, le=30)


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


@app.post("/api/entrevista/recomendacao")
async def recomendar_entrevista(pedido: PedidoRecomendacao):
    """Diz se vale abrir o caso, apoiado na amostra semelhante do pgvector.

    É uma decisão de triagem reversível, não previsão de êxito. A rota recebe
    somente respostas já consolidadas e roda fora do event loop para não
    interromper a transcrição ao vivo enquanto consulta banco e embeddings.
    """
    lacunas = [
        str(item).strip()[:500]
        for item in pedido.lacunas_obrigatorias
        if str(item).strip()
    ]
    try:
        return await run_in_threadpool(
            recomendacao.recomendar,
            pedido.relato,
            lacunas_obrigatorias=lacunas,
            limite=pedido.limite_precedentes,
            # 6s era apertado: o pgvector fica atrás da VPN, com ~80ms de
            # latência e servidor compartilhado. Uma oscilação dentro desses 6
            # segundos virava "indisponível" numa consulta que costuma completar.
            connect_timeout=20,
            detalhar=True,
        )
    except recomendacao.ErroRecomendacao as exc:
        raise HTTPException(422, str(exc)) from exc
    except recomendacao.BaseIndisponivel as exc:
        # Causa dita, e não "indisponível": os dois consertos são diferentes —
        # este é checar a VPN e o servidor, não esperar nem refazer a entrevista.
        log.warning("Banco de precedentes fora: %s", str(exc)[:200])
        raise HTTPException(
            503,
            "O banco de precedentes não respondeu (ele fica atrás da VPN). "
            "A entrevista continua normalmente; a recomendação volta sozinha "
            "quando a conexão voltar.",
        ) from exc
    except Exception as exc:
        log.exception("Recomendação da entrevista falhou")
        raise HTTPException(
            503,
            "A recomendação falhou por um erro inesperado — está no log do "
            "servidor. A entrevista continua normalmente.",
        ) from exc


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
    if _chave_nome_identidade(nome) != _chave_nome_identidade(
        nome_caso
    ) or _cpf_identidade(cpf) != _cpf_identidade(cpf_caso):
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

    `whatsapp_proprio` é o nosso canal (Evolution), e não o da ZapSign. Os dois
    convivem: o e-mail da ZapSign sai sempre, e o WhatsApp entra por cima quando
    a instância do escritório está pareada. Enquanto não estiver, a tela não
    oferece o botão — mas o cliente continua recebendo o convite por e-mail.
    """
    return {**assinatura.configuracao(), "whatsapp_proprio": whatsapp.configurado()}


@app.post("/api/contrato/assinatura", status_code=201)
async def enviar_contrato_para_assinatura(pedido: PedidoAssinatura):
    """Gera a papelada INTEIRA e a manda para assinatura eletrônica.

    São três documentos e não um: contrato de honorários, procuração e
    declaração de hipossuficiência. Sem procuração o advogado não peticiona, e
    sem declaração não há gratuidade — mandar só o contrato deixava o cliente
    assinando uma vez e o escritório correndo atrás das outras duas assinaturas
    depois, fora do sistema.

    Cada documento vira um processo de assinatura próprio na ZapSign, porque é
    assim que ela funciona: um envelope por documento, com o seu próprio link e
    a sua própria trilha de auditoria. O cliente recebe três convites.

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
        documentos = await run_in_threadpool(
            contrato.gerar_todos, respostas, pedido.municipio
        )
    except contrato.DadosObrigatoriosContrato as exc:
        raise HTTPException(422, str(exc)) from exc
    except contrato.ErroContrato as exc:
        raise HTTPException(503, str(exc)) from exc

    extras = [s.model_dump() for s in pedido.signatarios]

    # Montar a lista falha por dado que o usuário pode consertar — cliente sem
    # e-mail e sem telefone. É 400, e não 502: culpar a ZapSign por uma entrevista
    # incompleta manda o advogado procurar o problema no lugar errado.
    try:
        signatarios = assinatura.signatarios_do_contrato(respostas, extras)
    except assinatura.ErroAssinatura as exc:
        raise HTTPException(400, str(exc)) from exc

    enviados: list[dict[str, Any]] = []
    faltando: list[str] = []
    for doc in documentos:
        nome_documento = f"{doc['rotulo']} — {cliente}"
        try:
            resposta = await assinatura.enviar(nome_documento, doc["docx"], signatarios)
        except assinatura.ErroAssinatura as exc:
            # Um documento recusado no meio da fila deixa os anteriores JÁ
            # enviados — e eles são válidos, o cliente vai recebê-los. Devolver
            # 502 e calar sobre isso faria o escritório mandar tudo de novo,
            # duplicando convites. Por isso o que já subiu vai na resposta.
            if enviados:
                log.warning(
                    "%s falhou depois de %d documento(s) já enviado(s): %s",
                    doc["rotulo"],
                    len(enviados),
                    exc,
                )
                return {
                    "assinaturas": enviados,
                    "faltando": sorted(set(faltando)),
                    "parcial": (
                        f"{doc['rotulo']} não foi aceita pela ZapSign ({exc}). "
                        f"Os {len(enviados)} documento(s) anteriores já foram enviados — "
                        "mande apenas o que faltou, para não duplicar convites."
                    ),
                }
            raise HTTPException(502, str(exc)) from exc

        resumo = assinatura.resumir(
            resposta, assinatura.casar_com_enviados(signatarios, resposta)
        )
        if not resumo["doc_token"]:
            raise HTTPException(
                502,
                f"A ZapSign aceitou {doc['rotulo'].lower()} mas não devolveu o token.",
            )

        registro = armazenamento.registrar_assinatura(
            doc_token=resumo["doc_token"],
            nome=nome_documento,
            cliente=cliente,
            cpf=str(respostas["cpf"]),
            signatarios=resumo["signatarios"],
            estado=resumo["estado"],
            caso_id=pedido.caso_id,
        )
        enviados_whatsapp = await whatsapp.enviar_links_assinatura_automaticos(registro)
        if enviados_whatsapp:
            log.info(
                "%d link(s) de assinatura enviados automaticamente pelo WhatsApp.",
                enviados_whatsapp,
            )
        enviados.append(_resposta_assinatura(registro))
        faltando += doc["faltando"]

        log.info(
            "%s de %s enviada para assinatura (%d signatário(s)).",
            doc["rotulo"],
            cliente,
            resumo["total"],
        )

    return {"assinaturas": enviados, "faltando": sorted(set(faltando))}


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
        raise HTTPException(
            422, "Informe o CPF junto com o nome para evitar homônimos."
        )
    return {
        "assinaturas": [
            _resposta_assinatura(a)
            for a in armazenamento.listar_assinaturas(
                caso_id=caso_id, cliente=cliente, cpf=cpf
            )
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
    registro_atual = atualizado or registro
    if (
        resumo["estado"] == "assinado"
        and armazenamento.caminho_do_assinado(assinatura_id) is None
    ):
        try:
            url = await assinatura.url_do_assinado(registro["doc_token"])
            pdf = await assinatura.baixar(url)
            destino = armazenamento.DIR_CONTRATOS / f"{assinatura_id}.pdf"
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(pdf)
            armazenamento.definir_arquivo_assinatura(assinatura_id, destino)
            registro_atual = (
                armazenamento.obter_assinatura(assinatura_id) or registro_atual
            )
            _anexar_documento_assinado_ao_caso(registro_atual, destino)
        except assinatura.ErroAssinatura as exc:
            log.warning(
                "Assinado %s ainda não pôde ser anexado ao caso: %s", assinatura_id, exc
            )
    return {
        "assinatura": _resposta_assinatura(registro_atual),
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
        _anexar_documento_assinado_ao_caso(registro, guardado)
        return FileResponse(
            guardado, media_type="application/pdf", filename=nome_arquivo
        )

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
    _anexar_documento_assinado_ao_caso(registro, destino)

    return FileResponse(destino, media_type="application/pdf", filename=nome_arquivo)


def _codigo_documento_assinado(nome: str) -> str:
    normalizado = contrato._sem_acento(nome)
    if normalizado.startswith("procuracao"):
        return "DOC.01"
    if normalizado.startswith("contrato"):
        return "ASS.CONTRATO"
    if normalizado.startswith("declaracao"):
        return "ASS.HIPOSSUFICIENCIA"
    return "ASS.DOCUMENTO"


def _anexar_documento_assinado_ao_caso(registro: dict[str, Any], caminho: Path) -> None:
    """Transforma a via assinada em anexo do caso, uma única vez.

    A procuração atende diretamente o DOC.01 do checklist. Os demais papéis
    também ficam presos ao dossiê, embora não substituam documentos probatórios
    específicos da ação.
    """
    caso_id = str(registro.get("caso_id") or "")
    if not caso_id or not caminho.is_file():
        return
    nome = f"{registro['nome']}.pdf".replace("/", "-").replace("\\", "-")
    for entrega in armazenamento.listar_entregas(caso_id):
        detalhe = armazenamento.obter_entrega(entrega["id"])
        origem = (detalhe or {}).get("extracao", {}).get("origem", {})
        if origem.get("assinatura_id") == registro.get("id"):
            return
    codigo = _codigo_documento_assinado(str(registro.get("nome") or ""))
    entrega = armazenamento.registrar_entrega_pendente(caso_id, codigo, nome, caminho)
    armazenamento.concluir_entrega(
        entrega["id"],
        {
            "tipo": {"codigo": "documento_assinado", "detectado": "documento_assinado"},
            "validacao": {
                "veredito": "valido",
                "dados_utilizaveis": True,
                "score_legibilidade": 100,
            },
            "origem": {"assinatura_id": registro["id"], "assinatura_eletronica": True},
        },
        True,
        [codigo],
    )


@app.post("/api/assinaturas/{assinatura_id}/caso")
def vincular_assinatura(assinatura_id: str, caso_id: str = Form(...)):
    """Liga o contrato ao caso aberto depois dele — a ordem do escritório."""
    registro = armazenamento.obter_assinatura(assinatura_id)
    if registro is None:
        raise HTTPException(404, "Contrato não encontrado.")
    _exigir_identidade_do_caso(caso_id, registro.get("cliente"), registro.get("cpf"))
    if not armazenamento.vincular_assinatura_ao_caso(assinatura_id, caso_id):
        raise HTTPException(404, "Contrato não encontrado.")
    atualizado = armazenamento.obter_assinatura(assinatura_id)
    guardado = armazenamento.caminho_do_assinado(assinatura_id)
    if atualizado and guardado:
        _anexar_documento_assinado_ao_caso(atualizado, guardado)
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


# ------------------------------------------------ roteiro vindo de documento
#
# O roteiro do escritório está escrito em `app/roteiros.py` porque foi transcrito
# à mão de um `.docx`. Cada nova categoria de causa tem o seu documento, e
# transcrever 86 perguntas em dataclasses leva um dia. Estas três rotas fecham
# esse caminho: o documento entra como arquivo, vira proposta de roteiro, e o
# advogado corrige o que o modelo errou antes de salvar.
#
# Nada aqui grava sozinho. A importação devolve uma PROPOSTA; salvar é um passo
# separado e deliberado, porque um roteiro é o que a entrevista inteira segue.


#: Manter o catálogo é trabalho de escritório, não de atendimento: o secretário
#: tem este módulo sem ter `entrevista`. Ver `app/perfis.py`.
PodeManterRoteiros = Depends(auth.exigir_modulo("roteiros"))


@app.post("/api/roteiros/importar", status_code=202)
async def importar_roteiro(
    tarefas: BackgroundTasks,
    arquivo: UploadFile = File(...),
    _autorizado=PodeManterRoteiros,
):
    """Agenda a leitura do documento e a montagem do roteiro neste servidor.

    202 e não 200: são de dez segundos a dois minutos entre OCR e as chamadas ao
    modelo, uma por bloco. A tela acompanha por `GET /api/jobs/{id}`, onde o
    campo `resultado.etapa` diz em que bloco a montagem está.

    Não depende do worker Celery: esta é uma operação administrativa rara e a
    produção pode continuar atendendo mesmo quando os workers estiverem fora.
    O processamento começa em thread logo depois de a resposta 202 ser enviada.
    """
    nome = arquivo.filename or "documento"
    extensao = Path(nome).suffix.lower()
    if extensao not in roteiro_ia.EXTENSOES_ROTEIRO:
        raise HTTPException(
            400,
            f"Extensão '{extensao or '(sem)'}' não suportada. "
            f"Use: {', '.join(sorted(roteiro_ia.EXTENSOES_ROTEIRO))}.",
        )

    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")
    if len(conteudo) > MAX_BYTES:
        raise HTTPException(413, f"Arquivo maior que {MAX_BYTES // (1024 * 1024)}MB.")

    pasta = BASE / "tmp" / "jobs"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{uuid.uuid4().hex}{extensao}"
    caminho.write_bytes(conteudo)

    try:
        await run_in_threadpool(jobs.inicializar)
        job_id = await run_in_threadpool(
            jobs.criar, "ROTEIRO", arquivo=str(caminho), conteudo=conteudo
        )
        tarefas.add_task(importar_roteiro_task.run, job_id, str(caminho), nome)
    except Exception as exc:
        caminho.unlink(missing_ok=True)
        log.exception("Falha ao agendar importação de roteiro")
        raise HTTPException(503, f"Processamento indisponível: {exc}") from exc

    return {"job_id": job_id}


class PedidoSalvarRoteiro(BaseModel):
    """O roteiro inteiro, como o editor da tela o tem em mãos."""

    roteiro: dict[str, Any]
    #: De onde ele veio — nome do arquivo importado, ou vazio se foi escrito à mão.
    origem: str = Field(default="", max_length=400)


@app.post("/api/roteiros", status_code=201)
async def salvar_roteiro(
    pedido: PedidoSalvarRoteiro,
    usuario: auth.Usuario = PodeManterRoteiros,
):
    """Grava o roteiro no catálogo. Regrava, se o código já existir.

    É por aqui que passa tanto o roteiro recém-importado quanto a edição feita no
    meio de um atendimento — e é de propósito que os dois usem a mesma validação:
    um roteiro escrito por um advogado às onze da noite pode quebrar a tela
    exatamente como um escrito pelo modelo.
    """
    try:
        roteiro = roteiros.de_dict(pedido.roteiro)
    except roteiros.RoteiroInvalido as exc:
        raise HTTPException(422, str(exc)) from exc

    try:
        registro = await run_in_threadpool(
            armazenamento.salvar_roteiro,
            roteiro.codigo,
            nome=roteiro.nome,
            descricao=roteiro.descricao,
            conteudo=roteiro.to_dict(),
            origem=pedido.origem.strip(),
            criado_por=usuario.nome,
        )
    except Exception as exc:
        log.exception("Falha ao salvar roteiro '%s'", roteiro.codigo)
        raise HTTPException(503, f"Não foi possível salvar o roteiro: {exc}") from exc

    roteiros.invalidar_cache()
    return {
        **roteiro.to_dict(),
        "mapa_rastreio": roteiros.MAPA_RASTREIO,
        "atualizado_em": registro.get("atualizado_em", ""),
    }


@app.delete("/api/roteiros/{codigo}")
async def excluir_roteiro(codigo: str, _autorizado=PodeManterRoteiros):
    """Tira o roteiro do catálogo.

    Num roteiro importado isto o apaga. Num que também existe em
    `app/roteiros.py`, desfaz a edição e devolve o do módulo — a saída para uma
    edição malfeita no meio do expediente, sem precisar de deploy.
    """
    removido = await run_in_threadpool(armazenamento.excluir_roteiro, codigo)
    if not removido:
        raise HTTPException(404, f"Roteiro '{codigo}' não está salvo no catálogo.")

    roteiros.invalidar_cache()
    return {"codigo": codigo, "revertido_para_o_modulo": codigo in roteiros.ROTEIROS}


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
def saude(fila: bool = False):
    """Sonda de saúde. `?fila=1` acrescenta o estado da leitura de documentos.

    O acréscimo é OPCIONAL de propósito. Esta rota é a sonda de inicialização do
    `iniciar.ps1`, chamada em laço com 2 s de timeout; perguntar ao broker e aos
    workers em toda chamada colocaria segundos no caminho quente por um dado que
    quase ninguém está pedindo. Com o parâmetro, quem precisa diagnosticar pede —
    inclusive de fora do servidor, que é o ponto: `/metrics` mora fora de `/api/`
    e o proxy o devolve como 404.
    """
    from . import ocr_engine

    ocr_via_worker = os.getenv("OCR_AQUECER_API", "0") != "1"
    corpo = {
        "status": "ok",
        "modelo_carregado": ocr_engine.modelo_carregado(),
        "modelo_aquecido": _ocr_aquecido.is_set(),
        "ocr_via_worker": ocr_via_worker,
    }
    if fila:
        corpo["leitura_de_documentos"] = _estado_da_leitura()
    return corpo


#: Última resposta de `_estado_da_leitura`, com o instante em que foi medida.
_ESTADO_LEITURA: dict[str, Any] = {"medido_em": 0.0, "dados": None}
_VALIDADE_ESTADO_LEITURA = 15.0


def _estado_da_leitura() -> dict[str, Any]:
    """Existe alguém para ler o próximo documento enviado?

    ESTA PERGUNTA NÃO TINHA RESPOSTA DE FORA DO SERVIDOR, e essa foi a razão de um
    documento ficar preso por horas sem ninguém saber por quê. `/api/saude` dizia
    "ok" — e dizia a verdade, porque olhava só para si mesma. Quem lê o documento
    é outro processo, e ninguém perguntava por ele.

    As métricas do Prometheus responderiam, mas moram em `/metrics`, fora de
    `/api/` — e o proxy manda tudo que não é `/api/*` para o frontend. De fora,
    aquilo é um 404. Por isso a resposta precisa sair por aqui.

    Nunca levanta: um diagnóstico que derruba a sonda de saúde troca um problema
    por outro pior. O que não der para medir volta como `null`/"desconhecido".
    """
    agora = time.monotonic()
    if (
        _ESTADO_LEITURA["dados"] is not None
        and agora - _ESTADO_LEITURA["medido_em"] < _VALIDADE_ESTADO_LEITURA
    ):
        return _ESTADO_LEITURA["dados"]

    dados: dict[str, Any] = {"leitor": "desconhecido", "esperando_na_fila": None}

    try:
        from redis import Redis

        conexao = Redis.from_url(
            celery_app.conf.broker_url, socket_connect_timeout=2, socket_timeout=2
        )
        # Quantas mensagens estão paradas no Redis QUE ESTA API USA. É a metade
        # da história que a API conhece de fato: ela publicou, e ninguém tirou.
        dados["esperando_na_fila"] = conexao.llen("gpu_background")
    except Exception as exc:  # noqa: BLE001 - diagnóstico não pode derrubar a sonda
        dados["erro_broker"] = f"{type(exc).__name__}"

    try:
        filas = celery_app.control.inspect(timeout=2).active_queues() or {}
        consome = any(
            q["name"] == "gpu_background" for lista in filas.values() for q in lista
        )
        dados["leitor"] = "no ar" if consome else "fora do ar"
        dados["workers"] = len(filas)
    except Exception:  # noqa: BLE001
        pass

    if dados["leitor"] == "fora do ar":
        dados["diagnostico"] = (
            "Nenhum worker consome 'gpu_background'. Documento enviado agora fica "
            "esperando indefinidamente."
        )
    elif dados["leitor"] == "no ar" and (dados["esperando_na_fila"] or 0) > 0:
        dados["diagnostico"] = (
            "Há worker no ar E mensagem parada na fila: provavelmente ele está "
            "noutro Redis, ou a task não está registrada nele."
        )

    _ESTADO_LEITURA.update(medido_em=agora, dados=dados)
    return dados


def _sem_segredo(url: str) -> str:
    """`redis://user:senha@host:6379/0` -> `redis://host:6379/0`."""
    if "@" not in url:
        return url
    esquema, _, resto = url.partition("://")
    return f"{esquema}://{resto.rpartition('@')[2]}"


@app.get("/api/saude/fila")
def saude_da_fila():
    """A leitura de documentos está de pé? — respondido sem shell no servidor.

    `/api/saude` responde "ok" com o leitor de documentos MORTO: ela olha só para
    este processo. Foi esse ponto cego que deixou documento parado em "aguardando
    a vez na fila de leitura" sem ninguém perceber — a API estava ótima, e era
    verdade; o que faltava era quem tirasse a mensagem da fila.

    O que esta rota mostra, e por que cada campo importa:

    - `broker`: o Redis que ESTA API usa. Compare com o do worker: em container, o
      padrão `redis://localhost:6380/0` aponta para o próprio container, e API e
      worker acabam em Redis diferentes — a fila enche de um lado e ninguém
      escuta do outro.
    - `consumindo_gpu_background`: `false` aqui é a resposta de quase todo caso.
    - `entregas_esperando`: quantos documentos estão parados, e há quanto tempo o
      mais antigo espera.

    Exige sessão: o endereço do broker não é informação pública.
    """
    from .tasks.manutencao import MINUTOS_TRAVADA

    resposta: dict[str, Any] = {"broker": _sem_segredo(celery_app.conf.broker_url)}

    try:
        inspecao = celery_app.control.inspect(timeout=5)
        filas = inspecao.active_queues() or {}
        resposta["workers"] = {
            nome: [q["name"] for q in lista] for nome, lista in filas.items()
        }
        resposta["consumindo_gpu_background"] = any(
            q["name"] == "gpu_background" for lista in filas.values() for q in lista
        )
    except Exception as exc:  # noqa: BLE001 - fronteira com o broker
        resposta["workers"] = {}
        resposta["consumindo_gpu_background"] = False
        resposta["erro_broker"] = f"{type(exc).__name__}: {exc}"

    travadas = armazenamento.entregas_travadas(0)  # 0 min: tudo que está esperando
    resposta["entregas_esperando"] = len(travadas)
    resposta["esperando_ha_mais_de_%d_min" % MINUTOS_TRAVADA] = sum(
        1 for e in armazenamento.entregas_travadas(MINUTOS_TRAVADA)
    )
    if travadas:
        resposta["mais_antiga_em"] = travadas[0]["criado_em"]

    if resposta["entregas_esperando"] and not resposta["consumindo_gpu_background"]:
        resposta["diagnostico"] = (
            "Há documento esperando e NENHUM worker consumindo 'gpu_background'. "
            "O leitor de documentos está fora do ar ou apontando para outro Redis."
        )
    elif not resposta["consumindo_gpu_background"]:
        resposta["diagnostico"] = (
            "Nenhum worker consumindo 'gpu_background'. Nada está preso agora, mas "
            "o próximo documento enviado ficará."
        )
    else:
        resposta["diagnostico"] = "Leitor de documentos no ar."
    return resposta


@app.get("/api/config")
def config():
    """O que a tela precisa saber sobre a sessão. Público e sem segredo.

    Sobrou pouco depois que o Keycloak saiu: não há mais URL de servidor de
    identidade nem client_id para o navegador descobrir. O que fica é o que a
    tela decide com base nisto — mostrar ou não a tela de login."""
    return {"auth": auth.configuracao_publica()}


@app.get("/api/eu")
def eu(usuario: auth.Usuario = Depends(auth.usuario_atual)):
    """Quem está autenticado nesta requisição."""
    return usuario.to_dict()


def _aquecer_modelo() -> None:
    """Carrega o PaddleOCR e conclui a primeira inferência."""
    from .ocr_engine import aquecer_modelo

    aquecer_modelo()


def _tentar_aquecer() -> None:
    try:
        _aquecer_modelo()
        _ocr_aquecido.set()
        log.info("Modelo de OCR aquecido e pronto.")
    except Exception:
        # Sem rede na primeira execução, por exemplo: o upload tenta de novo.
        log.exception("Falha ao aquecer o modelo no boot")


@app.post("/api/aquecer")
def aquecer():
    """Baixa e carrega os modelos do PaddleOCR antes do primeiro upload."""
    try:
        _aquecer_modelo()
        _ocr_aquecido.set()
        return {"status": "pronto"}
    except Exception as exc:
        log.exception("Falha ao aquecer o modelo")
        raise HTTPException(
            status_code=500, detail=f"Falha ao carregar o modelo: {exc}"
        ) from exc


async def _ler_upload(arquivo: UploadFile) -> bytes:
    """Aceita qualquer tipo de arquivo e aplica apenas limites de segurança.

    Imagens e PDFs seguem para o OCR. Os demais formatos continuam sendo
    preservados no caso e vão para conferência/triagem, em vez de serem
    recusados antes mesmo de o escritório recebê-los.
    """
    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")
    if len(conteudo) > MAX_BYTES:
        raise HTTPException(413, f"Arquivo maior que {MAX_BYTES // (1024 * 1024)}MB.")
    return conteudo


async def _processar(
    conteudo: bytes, nome: str, idioma: str, tipo_forcado: str | None
) -> dict:
    try:
        # O OCR leva segundos e é puro CPU: fora do event loop, senão o servidor
        # para de responder (inclusive ao /api/saude) enquanto processa.
        return await run_in_threadpool(
            pipeline.processar, conteudo, nome, idioma, tipo_forcado
        )
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
    resultado = await _processar(
        conteudo, arquivo.filename or "sem-nome", idioma, tipo_forcado
    )
    return JSONResponse(resultado)


@app.post("/api/extrair/jobs", status_code=202)
async def enfileirar_extracao(
    arquivo: UploadFile = File(...),
    idioma: str = Form("pt"),
    tipo: str | None = Form(None),
):
    """Libera a conexão HTTP e executa o OCR no worker da fila GPU background."""
    conteudo = await _ler_upload(arquivo)
    tipo_forcado = tipo if tipo and tipo not in ("auto", "", "None") else None
    pasta = BASE / "tmp" / "jobs"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{uuid.uuid4().hex}.upload"
    caminho.write_bytes(conteudo)
    try:
        await run_in_threadpool(jobs.inicializar)
        job_id = await run_in_threadpool(jobs.criar, "OCR", arquivo=str(caminho))
        tarefa = processar_documento.apply_async(
            args=(
                job_id,
                str(caminho),
                arquivo.filename or "sem-nome",
                idioma,
                tipo_forcado,
            ),
            queue="gpu_background",
            priority=7,
        )
        await run_in_threadpool(jobs.vincular_tarefa, job_id, tarefa.id)
        return {
            "job_id": job_id,
            "task_id": tarefa.id,
            "status": "QUEUED",
            "progresso": 0,
        }
    except Exception as exc:
        caminho.unlink(missing_ok=True)
        log.exception("Falha ao enfileirar OCR")
        raise HTTPException(503, f"Fila de processamento indisponível: {exc}") from exc


@app.get("/api/jobs/{job_id}")
async def consultar_job(job_id: str):
    try:
        uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(400, "Identificador de job inválido") from exc
    registro = await run_in_threadpool(jobs.obter, job_id)
    if registro is None:
        raise HTTPException(404, "Job não encontrado")
    return registro


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
        bruto = await arquivo.read()
        if len(bruto) > 2 * 1024 * 1024:
            raise HTTPException(
                400, "Arquivo grande demais para uma entrevista (máx. 2 MB)."
            )
        try:
            conteudo = entrevista_lib.extrair_texto(arquivo.filename, bruto)
        except entrevista_lib.ErroDeLeitura as exc:
            raise HTTPException(400, str(exc)) from exc

    if not conteudo.strip():
        raise HTTPException(400, "Cole a entrevista ou envie um arquivo com texto.")

    resultado = triagem.triar(conteudo)
    resultado["dados"] = triagem.extrair_dados_do_cliente(conteudo)
    resultado["caracteres"] = len(conteudo)
    resultado["texto_extraido"] = conteudo
    return resultado


# --------------------------------------------------- chamada de voz (WebRTC)


def gerar_token_jitsi(sala: str) -> str | None:
    """Gera JWT HS256 para o Jitsi aceitar a conexão — quando ele pede um.

    O Jitsi valida tokens com aud/iss/sub = JITSI_JWT_APP_ID e room = nome da sala.
    O secret é compartilhado com o Prosody (configurado em docker-jitsi-meet/.env).

    SEM SECRET, DEVOLVE `None` — E ISSO É UM ESTADO VÁLIDO

    O token só existe porque o Jitsi o exige quando sobe com `AUTH_TYPE=jwt`. Com
    `ENABLE_AUTH=0`, que é como o stack local está hoje, o servidor aceita
    conexão anônima e o token é decorativo: o que protege a sala continua sendo o
    nome dela, 256 bits sorteados que ninguém adivinha.

    A versão anterior registrava um aviso e seguia adiante para `jwt.encode`, que
    recusa chave vazia com `InvalidKeyError`. O resultado era 500 na criação da
    sala — e, no navegador, "Failed to fetch", porque resposta de exceção não
    tratada sai sem cabeçalho de CORS e o `fetch` rejeita antes de ver o status.
    Um aviso no log do servidor não ajuda quem está com o cliente na linha vendo
    a chamada não abrir.

    Ligando `AUTH_TYPE=jwt` no Jitsi, preencha `JITSI_JWT_APP_SECRET` com o mesmo
    valor do `docker-jitsi-meet/.env`: aí o token volta a ser obrigatório dos
    dois lados.
    """
    secret = os.environ.get("JITSI_JWT_APP_SECRET", "")
    if not secret:
        return None
    app_id = os.environ.get("JITSI_JWT_APP_ID", "level33-chamadas")
    agora = datetime.now(timezone.utc)

    payload = {
        "aud": app_id,
        "iss": app_id,
        "sub": app_id,
        "room": sala,
        "exp": agora + timedelta(hours=2),
        "nbf": agora - timedelta(seconds=10),
        "context": {
            "user": {
                "name": "Advogado",
                "id": "advogado",
                "moderator": True,
            }
        },
    }
    return jwt.encode(payload, secret, algorithm="HS256")


_salas = chamada.Salas()


@app.get("/api/chamada/config")
def config_chamada():
    """Servidores ICE para o navegador montar a conexão. Público e sem segredo."""
    return {"iceServers": chamada.SERVIDORES_ICE}


@app.post("/api/chamada/sala", status_code=201)
def criar_sala(payload: dict | None = None):
    """Sorteia uma sala de chamada e devolve o link para mandar ao entrevistado.

    A entrevista acontece ANTES de o caso existir — é ela que decide a categoria
    —, então a sala não pode depender de caso nem de portal. O nome da sala é o
    segredo: 256 bits sorteados, do mesmo gerador que assina o portal. Quem tem
    o link entra; quem não tem não adivinha.

    Sala é efêmera e não é gravada em lugar nenhum: existe enquanto houver
    alguém dentro (ver `app/chamada.py`).

    O token JWT é exigido pelo Jitsi quando AUTH_TYPE=jwt. O cliente também
    chama este endpoint com o sala existente para obter o próprio token. Sem
    `JITSI_JWT_APP_SECRET` o campo vem vazio, e é assim que deve ser: o Jitsi
    local roda com `ENABLE_AUTH=0` e aceita conexão anônima (ver
    `gerar_token_jitsi`).
    """
    sala = (payload or {}).get("sala") if payload else None
    if not sala:
        sala = chamada.gerar_sala()
    token = gerar_token_jitsi(sala)
    return {"sala": sala, "url": f"{URL_PORTAL}/chamada/{sala}", "token": token or ""}


@app.post("/api/casos/{caso_id}/analise-documentos")
def analisar_documentos_do_caso(caso_id: str):
    """O que os anexos dizem e a entrevista não registrou.

    Sob demanda, com botão, e não a cada upload: são vinte documentos num caso
    grande, e reanalisar a cada um pagaria vinte chamadas de modelo para
    responder a mesma pergunta. O advogado clica quando o checklist já está de
    pé, que é quando a resposta vale.

    Falta de chave e modelo mudo viram 503 com o que dá para fazer — os
    documentos continuam anexados e legíveis de qualquer forma.
    """
    if armazenamento.obter_caso(caso_id) is None:
        raise HTTPException(404, "Caso não encontrado.")
    try:
        return analise_documentos.analisar(caso_id)
    except analise_documentos.ErroAnaliseDocumentos as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/chamada/sala/{sala_id}/token", status_code=201)
def token_da_sala(sala_id: str):
    """O token para ENTRAR numa sala que já existe. Sem login, de propósito.

    É o que o cliente chama ao abrir o link da chamada. Ele não tem conta — a
    página promete que não precisa criar uma —, e a rota de cima exige sessão
    porque criar sala é ato do escritório. Sem esta separação, o link público
    abria uma tela de login.

    O QUE PROTEGE A SALA CONTINUA SENDO O NOME DELA

    São 256 bits sorteados pelo mesmo gerador que assina o portal. Quem tem o
    link entra; quem não tem não adivinha. É a mesma proteção que o portal do
    caso usa, e o motivo de a sala vir no CAMINHO: o middleware libera por
    prefixo, e o segredo viaja com a requisição sem depender do corpo.

    Não cria nada. Sala inexistente devolve token para um nome que ninguém está
    usando — e a chamada fica esperando alguém que não vem, que é o mesmo que
    acontece com um link antigo. Recusar aqui exigiria manter registro de salas,
    e a sala é efêmera de propósito (ver `app/chamada.py`).
    """
    sala_id = sala_id.strip()
    if not sala_id:
        raise HTTPException(422, "Identificador da sala vazio.")
    token = gerar_token_jitsi(sala_id)
    return {
        "sala": sala_id,
        "url": f"{URL_PORTAL}/chamada/{sala_id}",
        "token": token or "",
    }


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
            await _salas.repassar(
                sala_id, papel_tipado, {"type": "saiu", "papel": papel}
            )


class PedidoEstrategia(BaseModel):
    relato: str = Field(min_length=30, max_length=50_000)
    limite_precedentes: int = Field(default=8, ge=3, le=15)


@app.post("/api/estrategia/jobs", status_code=202)
async def enfileirar_estrategia(pedido: PedidoEstrategia):
    await run_in_threadpool(jobs.inicializar)
    job_id = await run_in_threadpool(jobs.criar, "AI")
    tarefa = gerar_estrategia_job.apply_async(
        args=(job_id, pedido.relato, pedido.limite_precedentes), queue="ai", priority=5
    )
    await run_in_threadpool(jobs.vincular_tarefa, job_id, tarefa.id)
    return {"job_id": job_id, "task_id": tarefa.id, "status": "QUEUED", "progresso": 0}


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
        raise HTTPException(
            status_code=503, detail="Base estratégica indisponível."
        ) from exc


@app.post("/api/casos", status_code=201)
def criar_caso(
    cliente: str = Form(...),
    categoria: str = Form(...),
    observacao: str = Form(""),
    #: O WhatsApp que a entrevista colheu. Opcional porque o caso também nasce
    #: pela carteira, digitado à mão, onde ninguém perguntou telefone ainda.
    telefone: str = Form(""),
):
    """Cria o caso já com o portal do cliente pronto.

    O link nasce junto com o caso porque é isso que o escritório manda ao cliente
    logo depois de abrir o processo. A senha vai NESTA resposta e em nenhuma
    outra — o banco guarda apenas o hash.
    """
    if not cliente.strip():
        raise HTTPException(400, "Informe o nome do cliente.")
    if categorias.obter(categoria) is None:
        raise HTTPException(400, f"Categoria '{categoria}' não existe.")

    caso = armazenamento.criar_caso(cliente, categoria, observacao, telefone)
    listar_casos.limpar_cache()  # type: ignore[attr-defined]
    return {**caso, "portal": _criar_portal(caso["id"])}


@app.get("/api/casos")
@por_alguns_segundos(5)
def listar_casos():
    return {"casos": armazenamento.listar_casos()}


@app.get("/api/carteira")
def fila_da_carteira(pagina: int = 1, tamanho: int = carteira.TAMANHO_PADRAO):
    """A fila de casos da carteira, uma página por vez.

    Substitui o `GET /api/casos` seguido de um `GET /api/casos/{id}` por caso que a tela
    fazia: eram N+1 requisições e a carteira inteira no navegador. Aqui são duas consultas
    e só a página pedida no payload — mas a ordem por risco e os contadores do topo são
    medidos sobre a carteira toda (ver `app/carteira.py`).
    """
    return carteira.montar(pagina=pagina, tamanho=tamanho)


@app.get("/api/casos/{caso_id}")
def obter_caso(caso_id: str):
    situacao = casos.montar_situacao(caso_id)
    if situacao is None:
        raise HTTPException(404, "Caso não encontrado.")
    return situacao


@app.get("/api/casos/{caso_id}/painel")
def painel_do_caso_analitico(caso_id: str):
    """Painel analítico do caso: histórico medido, comparação e riscos.

    Leitura pesada de propósito — passa pelo dossiê (que consulta o agente) e pelos casos
    anteriores da mesma categoria para montar a referência. É uma tela que se abre para
    estudar o caso, não um polling: quem quer só o estado atual usa `/api/casos/{id}`.
    """
    montado = painel_do_caso.montar(caso_id)
    if montado is None:
        raise HTTPException(404, "Caso não encontrado.")
    return montado


@app.get("/api/panorama")
def panorama_do_escritorio():
    """Painel analítico de todos os casos: o mesmo tipo de leitura, uma escala acima.

    Existe para que o gestor responda "como o escritório está andando" sem abrir caso
    por caso. Mede com as mesmas funções do painel do caso (`app/panorama.py` importa
    `painel.marcos_do_caso` e `painel.medir_etapas`), então os números das duas telas
    fecham entre si.

    Cinco consultas independentemente do tamanho da carteira, e nenhuma chamada ao
    agente jurídico — o que dependeria dele está declarado em `ausencias`.

    Não leva `exigir_papel`: o middleware `exigir_autenticacao` já fecha toda rota que
    não esteja em `LIVRES_SEM_ADVOGADO` para quem não é advogado ou secretário, e esta
    atravessa o acervo inteiro.
    """
    return panorama.montar()


@app.patch("/api/casos/{caso_id}")
def atualizar_caso(
    caso_id: str, cliente: str | None = Form(None), observacao: str | None = Form(None)
):
    if not armazenamento.atualizar_caso(caso_id, cliente, observacao):
        raise HTTPException(404, "Caso não encontrado ou nada para atualizar.")
    listar_casos.limpar_cache()  # type: ignore[attr-defined]
    return armazenamento.obter_caso(caso_id)


@app.delete("/api/casos/{caso_id}")
def excluir_caso(caso_id: str):
    if not armazenamento.excluir_caso(caso_id):
        raise HTTPException(404, "Caso não encontrado.")
    listar_casos.limpar_cache()  # type: ignore[attr-defined]
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


# O antigo `_ler_documento` (OCR do checklist numa thread da API) saiu daqui: quem
# lê o documento agora é `tasks.ocr.processar_entrega`, no worker que já mantém o
# Paddle aquecido. A ponte com o agente jurídico foi junto — a task chama
# `espelho.enviar_entrega` por conta própria, e não este `_entregar_ao_agente`.


def _ler_entrevista_no_agente(caso_id: str, entrevista_id: str) -> None:
    """Manda a entrevista recém-guardada para o agente virar fato, sem espera humana.

    Roda numa thread de fundo, fora do ciclo da requisição: quem anexou a entrevista
    não precisa mais clicar em "Ler no agente" depois — o fim da entrevista já é o
    gatilho. `espelho.enviar_entrevista` é idempotente (`enviada_em`), então um
    reenvio manual pela tela de sincronização não duplica fato.

    Falha aqui não pode escapar: a entrevista já está salva localmente, e derrubar
    esta thread por indisponibilidade do agente não desfaz esse registro.
    """
    try:
        from .agente import espelho

        resposta = espelho.enviar_entrevista(caso_id, entrevista_id)
    except Exception:  # noqa: BLE001 - fronteira com serviço externo
        log.warning(
            "não foi possível ler a entrevista %s no agente",
            entrevista_id,
            exc_info=True,
        )
        return

    # A entrevista virou fato. Falta LER o caso inteiro com ela dentro — a
    # classificação e a jurisprudência saem dos fatos do caso, sem distinguir se
    # vieram de documento ou da conversa, e é essa leitura combinada que interessa
    # ao advogado. Ela existia só nos dois botões do dossiê, e no fim de um
    # atendimento ninguém clica: o cliente acabou de sair.
    #
    # Só quando a leitura ACONTECEU agora. `ja_enviada` e `failure` significam que
    # nenhum fato novo entrou, e reclassificar o caso por isso seria gastar duas
    # chamadas de modelo para chegar ao mesmo resultado.
    if resposta.get("ja_enviada") or resposta.get("failure"):
        return
    try:
        espelho.analisar_caso_inteiro(caso_id)
    except Exception:  # noqa: BLE001 - idem; a entrevista já está lida e salva
        log.warning(
            "não foi possível analisar o caso %s após a entrevista",
            caso_id,
            exc_info=True,
        )


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
        log.warning(
            "não foi possível entregar %s ao agente jurídico", entrega_id, exc_info=True
        )


async def _registrar_documento(
    caso: dict[str, Any],
    item: str | None,
    arquivo: UploadFile,
    idioma: str,
    usar_para_rg_e_cpf: bool,
    lote_id: str | None = None,
) -> dict[str, Any]:
    """OCR + registro da entrega. Compartilhado pelo advogado e pelo portal.

    O cliente passa pelo mesmo caminho de propósito: a validação de tipo, a
    legibilidade e o vínculo RG/CPF não podem depender de quem enviou.

    `item` VAZIO é o envio sem destino — o cliente jogou o arquivo na área de
    envio em massa e não disse que documento é. A entrega nasce em triagem e o
    item sai da leitura, em `roteamento.decidir`. Quando o item vem preenchido,
    ele é um palpite: se o documento o desmentir, a entrega vai para o item certo.
    """
    caso_id = caso["id"]
    categoria = categorias.obter(caso["categoria"])
    if categoria is None:
        raise HTTPException(409, f"Categoria '{caso['categoria']}' não existe mais.")

    item = (item or "").strip() or None
    item_checklist = None
    if item is not None:
        item_checklist = next((i for i in categoria.itens if i.codigo == item), None)
        if item_checklist is None:
            raise HTTPException(
                400, f"Item '{item}' não pertence ao checklist de {categoria.nome}."
            )

    # Valida a opção manual antes de gastar o OCR, para o erro sair na hora.
    if usar_para_rg_e_cpf:
        if item_checklist is None:
            raise HTTPException(
                400, "A identidade unificada exige o item RG ou CPF no envio."
            )
        try:
            casos.itens_para_identidade_unificada(categoria, item_checklist)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    conteudo = await _ler_upload(arquivo)
    nome = arquivo.filename or "sem-nome"

    item_codigo = item or categorias.ITEM_TRIAGEM

    # O arquivo vai para o disco e a entrega é criada antes de entrar na fila.
    # Assim o upload responde sem manter a conexão aberta durante a inferência.
    destino = armazenamento.DIR_ARQUIVOS / caso_id
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{item_codigo}_{uuid.uuid4()}{Path(nome).suffix.lower()}"
    caminho.write_bytes(conteudo)

    entrega = armazenamento.registrar_entrega_pendente(
        caso_id, item_codigo, nome, caminho, conteudo=conteudo, lote_id=lote_id
    )

    # O checklist antes abria uma thread na API e carregava outra cópia do
    # Paddle no primeiro envio (97–200s). O worker OCR já nasce aquecido e é o
    # único dono do modelo; a requisição continua voltando imediatamente.
    try:
        tarefa = processar_entrega.apply_async(
            args=(
                entrega["id"],
                caso_id,
                str(caminho),
                nome,
                item_codigo,
                categoria.codigo,
                idioma,
                usar_para_rg_e_cpf,
            ),
            queue="gpu_background",
            priority=7,
        )
    except Exception as exc:
        armazenamento.falhar_entrega(entrega["id"], "Fila de OCR indisponível.")
        log.exception("Falha ao enfileirar a entrega %s", entrega["id"])
        raise HTTPException(
            503, "Fila de leitura indisponível. Tente novamente."
        ) from exc

    return {"entrega": entrega, "processando": True, "task_id": tarefa.id}


@app.post("/api/casos/{caso_id}/documentos", status_code=201)
async def enviar_documento(
    caso_id: str,
    item: str = Form(""),
    arquivo: UploadFile = File(...),
    idioma: str = Form("pt"),
    usar_para_rg_e_cpf: bool = Form(False),
):
    """Recebe um documento, roda o OCR e marca o item do checklist.

    `item` é opcional: sem ele, quem decide o item é a leitura do documento.
    """
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")
    return await _registrar_documento(caso, item, arquivo, idioma, usar_para_rg_e_cpf)


#: Teto de arquivos por envio em massa. Não é limite de tamanho — é para o
#: cliente não despejar a galeria inteira do celular numa requisição só e ficar
#: sem resposta enquanto duzentas fotos são gravadas antes do primeiro 201.
MAX_ARQUIVOS_POR_LOTE = 30


async def _registrar_lote(
    caso: dict[str, Any],
    arquivos: list[UploadFile],
    idioma: str,
) -> dict[str, Any]:
    """Vários documentos de uma vez, cada um achando o próprio item.

    Um arquivo que falha não derruba os outros: o lote devolve o que entrou e o
    que não entrou, com o motivo, porque quem mandou doze fotos precisa saber
    qual das doze precisa repetir.
    """
    if not arquivos:
        raise HTTPException(400, "Nenhum arquivo foi enviado.")
    if len(arquivos) > MAX_ARQUIVOS_POR_LOTE:
        raise HTTPException(
            400,
            f"São aceitos até {MAX_ARQUIVOS_POR_LOTE} arquivos por envio. "
            "Divida em partes menores.",
        )

    lote_id = uuid.uuid4().hex
    aceitos: list[dict[str, Any]] = []
    recusados: list[dict[str, str]] = []
    for arquivo in arquivos:
        nome = arquivo.filename or "sem-nome"
        try:
            registro = await _registrar_documento(
                caso, None, arquivo, idioma, False, lote_id
            )
            aceitos.append({"arquivo": nome, "entrega_id": registro["entrega"]["id"]})
        except HTTPException as exc:
            recusados.append({"arquivo": nome, "motivo": str(exc.detail)})
        except Exception as exc:  # noqa: BLE001 - um arquivo ruim não perde o lote
            log.exception("falha ao registrar %s no lote %s", nome, lote_id)
            recusados.append({"arquivo": nome, "motivo": str(exc)[:200]})

    if not aceitos:
        raise HTTPException(
            400, recusados[0]["motivo"] if recusados else "Nenhum arquivo aceito."
        )

    return {
        "lote_id": lote_id,
        "recebidos": aceitos,
        "recusados": recusados,
        "processando": True,
    }


@app.post("/api/casos/{caso_id}/documentos/lote", status_code=201)
async def enviar_documentos_em_lote(
    caso_id: str,
    arquivos: list[UploadFile] = File(...),
    idioma: str = Form("pt"),
):
    """Envio em massa: N documentos, sem escolher item para nenhum deles."""
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")
    return await _registrar_lote(caso, arquivos, idioma)


@app.patch("/api/entregas/{entrega_id}/itens")
def reatribuir_entrega(
    entrega_id: str,
    itens: list[str] = Body(..., embed=True),
    usuario: auth.Usuario = Depends(auth.usuario_atual),
):
    """Move um documento já lido para outro(s) item(ns) do checklist.

    É a palavra final sobre o roteamento automático, e a saída da triagem: o
    advogado olhou o arquivo e disse a que ele responde. Não refaz OCR — o texto
    e os campos já estão gravados, e o arquivo é o mesmo.

    Lista vazia devolve a entrega para a triagem, que é como se desfaz uma
    atribuição errada sem apagar o documento.
    """
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")

    caso = armazenamento.obter_caso(entrega["caso_id"])
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")
    categoria = categorias.obter(caso["categoria"])
    if categoria is None:
        raise HTTPException(409, f"Categoria '{caso['categoria']}' não existe mais.")

    escolhidos = list(dict.fromkeys(i.strip() for i in itens if i and i.strip()))
    validos = {i.codigo: i for i in categoria.itens}
    desconhecidos = [i for i in escolhidos if i not in validos]
    if desconhecidos:
        raise HTTPException(
            400,
            f"Item(ns) fora do checklist de {categoria.nome}: {', '.join(desconhecidos)}.",
        )

    if not escolhidos:
        return armazenamento.reatribuir_entrega(
            entrega_id,
            [],
            categorias.ITEM_TRIAGEM,
            roteamento.HUMANO,
            motivo="Devolvido à triagem pelo escritório.",
        )

    item_correto = validos[escolhidos[0]]
    if len(escolhidos) > 1:
        detectado = entrega.get("tipo_detectado")
        confere = casos.tipo_confere(item_correto, detectado, True)
        return armazenamento.reatribuir_entrega(
            entrega_id,
            escolhidos,
            escolhidos[0],
            roteamento.HUMANO,
            tipo_confere=confere,
            confianca=100,
            motivo=f"Atribuído por {usuario.nome or usuario.usuario or 'escritório'}.",
        )
    tipo_correto = item_correto.tipo_ocr or item_correto.codigo
    corrigida = armazenamento.corrigir_classificacao_entrega(
        entrega_id,
        item_codigo=item_correto.codigo,
        tipo_correto=tipo_correto,
        rotulo_correto=item_correto.nome,
        categoria=categoria.codigo,
        corrigido_por=usuario.nome or usuario.usuario or usuario.id or "escritório",
    )
    if corrigida:
        threading.Thread(
            target=_entregar_ao_agente,
            args=(entrega["caso_id"], entrega_id),
            name=f"agente-correcao-{entrega_id[:8]}",
            daemon=True,
        ).start()
    return corrigida


@app.post("/api/casos/{caso_id}/documentos/teste", status_code=201)
async def enviar_documento_de_teste(
    caso_id: str, item: str = Form(...), texto: str = Form("")
):
    """Marca um item do checklist como entregue com dados falsos, sem OCR nem arquivo real.

    Existe só para agilizar teste manual e automatizado do dossiê e da ponte com o
    agente: preenche a validação e a extração com um resultado plausível e fixo, sem
    passar pelo PaddleOCR nem exigir que alguém suba um documento de verdade a cada
    rodada. `texto`, opcional, entra como `texto_completo` da extração — é o que o
    agente de documento do outro lado lê para propor fato (`fields`/`text` no prompt);
    sem ele o documento chega "existe, mas está em branco" e nenhum fato nasce dele.
    Desligado por padrão — só responde com `PERMITIR_DADOS_TESTE=true` no
    ambiente, para não virar um jeito de "entregar" documento em produção sem
    documento nenhum.
    """
    if os.getenv("PERMITIR_DADOS_TESTE", "").strip().lower() != "true":
        raise HTTPException(404, "Rota de dados de teste desativada.")

    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")

    categoria = categorias.obter(caso["categoria"])
    if categoria is None:
        raise HTTPException(409, f"Categoria '{caso['categoria']}' não existe mais.")

    item_checklist = next((i for i in categoria.itens if i.codigo == item), None)
    if item_checklist is None:
        raise HTTPException(
            400, f"Item '{item}' não pertence ao checklist de {categoria.nome}."
        )

    # `None` quando o item não tem classificador (procuração, CAT, laudos...) — como
    # o Paddle de verdade nunca teria opinião sobre esses, inventar um tipo aqui
    # ("documento") mandaria ao agente um valor que ele não reconhece e que o
    # classificador real jamais produziria.
    tipo = item_checklist.tipo_ocr
    nome = f"teste-{item}.pdf"
    destino = armazenamento.DIR_ARQUIVOS / caso_id
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{item}_{uuid.uuid4()}.pdf"
    caminho.write_bytes(b"%PDF-1.7 dado de teste, sem documento real por tras")

    extracao = {
        "tipo": {"codigo": tipo, "detectado": tipo, "descricao": item_checklist.nome},
        "validacao": {
            "veredito": "APROVADO",
            "dados_utilizaveis": True,
            "score_legibilidade": 100,
        },
        "campos": [],
        "texto_completo": texto,
    }
    tipo_confere = True if tipo else None

    entrega = armazenamento.registrar_entrega(
        caso_id,
        item,
        nome,
        caminho,
        extracao,
        tipo_confere,
        conteudo=caminho.read_bytes(),
    )

    threading.Thread(
        target=_entregar_ao_agente,
        args=(caso_id, entrega["id"]),
        name=f"agente-teste-{entrega['id'][:8]}",
        daemon=True,
    ).start()

    return entrega


# ---------------------------------------------------------------- entrevista
#
# A entrevista é do caso, não do agente: o arquivo do atendimento existe mesmo com a
# integração desligada, e é aqui que ele fica. Assim que o arquivo é guardado, uma
# thread de fundo (`_ler_entrevista_no_agente`) já manda o texto para o agente virar
# fato — a rota `POST /api/agente/casos/{caso_id}/entrevista/{entrevista_id}` em
# `app/agente/rotas.py` continua existindo só para reenvio manual (ex.: agente estava
# fora do ar no momento do envio automático).


@app.post("/api/casos/{caso_id}/entrevista", status_code=201)
async def enviar_entrevista(
    request: Request,
    caso_id: str,
    arquivo: UploadFile = File(...),
    realizada_em: str = Form(""),
    entrevistador: str = Form(""),
):
    """Guarda o arquivo da entrevista e o texto lido dele.

    Sem `entrevistador` no formulário, assume QUEM ESTÁ LOGADO. O campo era texto
    livre e ficava vazio: de sete entrevistas gravadas, seis não diziam quem as
    fez, e a única preenchida trazia um nome digitado à mão. Assim não havia como
    responder "quantas cada um fez" — que é justamente o que a supervisão precisa
    (ver `app/supervisao.py`).

    O campo continua aceito, e continua vencendo quando vem preenchido: quem
    digita ali está registrando que OUTRA pessoa conduziu — uma entrevista antiga
    sendo cadastrada depois, por exemplo. Sobrescrever isso com o usuário da
    sessão trocaria um dado certo por um palpite.
    """
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

    entrevista = armazenamento.registrar_entrevista(
        caso_id,
        arquivo=nome,
        caminho=caminho,
        texto=texto,
        realizada_em=realizada_em.strip(),
        entrevistador=entrevistador.strip() or _quem_conduziu(request),
    )

    threading.Thread(
        target=_ler_entrevista_no_agente,
        args=(caso_id, entrevista["id"]),
        name=f"agente-entrevista-{entrevista['id'][:8]}",
        daemon=True,
    ).start()

    return entrevista


def _quem_conduziu(request: Request) -> str:
    """Nome de quem está logado, para atribuir a entrevista.

    Grava o NOME e não o `sub` porque é o que a supervisão mostra na tela e o que
    a coluna `entrevistador` já guardava — trocar para identificador tornaria
    ilegíveis as linhas antigas sem ganhar nada. Com `-SemAuth` volta vazio, que
    é honesto: sem autenticação não há quem atribuir.
    """
    usuario = getattr(request.state, "usuario", None)
    if usuario is None or usuario is auth.USUARIO_ABERTO:
        return ""
    return (usuario.nome or usuario.usuario or "").strip()[:120]


class TranscricaoAoVivo(BaseModel):
    """A conversa que o roteiro guiado transcreveu, indo para o caso."""

    #: Id da gravação no serviço de transcrição (porta 8200). É a chave da entrevista.
    gravacao_id: str = Field(min_length=1, max_length=64)
    #: A transcrição BRUTA, como saiu do Whisper — não o relato montado a partir
    #: das respostas. Ver o cabeçalho da rota.
    texto: str = ""
    realizada_em: str = ""
    #: O cliente avaliou o escritório no Google, confirmado na chamada.
    avaliacao_google: bool = False
    #: O atendimento foi ENCERRADO, não apenas salvo no meio do caminho.
    concluida: bool = False


@app.put("/api/casos/{caso_id}/entrevista-ao-vivo")
async def gravar_entrevista_ao_vivo(
    request: Request, caso_id: str, dados: TranscricaoAoVivo
):
    """Guarda no caso a entrevista que foi CONDUZIDA pelo roteiro guiado.

    O BURACO QUE ISTO FECHA

    Só existia um jeito de uma entrevista virar linha em `entrevistas`: alguém
    anexar um arquivo ao caso, à mão, depois. O atendimento ao vivo — roteiro,
    escuta, gravação — não gravava nada: a conversa transcrita ficava na aba do
    navegador e morria com ela. Como a supervisão lê essa tabela (ver
    `app/supervisao.py`), o fluxo em que o roteiro é REALMENTE seguido era o único
    que ela não enxergava. Ela media uma amostra e parecia medir o escritório.

    O QUE VAI GRAVADO É A TRANSCRIÇÃO BRUTA, NÃO O RELATO

    A tela tem os dois: o relato montado a partir das respostas e a conversa como
    o Whisper a ouviu. Aqui entra a segunda, e a diferença é a razão de a auditoria
    existir. O roteiro preenchido diz o que a escuta conseguiu extrair; auditá-lo
    mediria o acerto do reconhecimento de voz. A transcrição diz o que foi
    perguntado e respondido — que é a condução, e é ela que está em avaliação (ver
    o cabeçalho de `app/auditoria.py`).

    POR QUE PUT, E CHAMADA MAIS DE UMA VEZ

    O atendimento não termina quando o caso nasce: o caso é criado no meio da
    rolagem, com o cliente ainda na linha, e depois dele vêm a avaliação no Google,
    os documentos e o fechamento lido do roteiro. A tela grava ao criar o caso — para
    não perder tudo se a aba morrer — e de novo ao encerrar, com a conversa
    completa. `gravacao_id` é a chave: a segunda chamada REESCREVE a primeira em vez
    de criar outra entrevista, senão a supervisão contaria em dobro o trabalho de
    quem conduziu.
    """
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")

    texto = dados.texto.strip()
    existente = armazenamento.obter_entrevista_por_gravacao(dados.gravacao_id)

    # Uma gravação pertence a UM caso. Se ela já está noutro, o atendente criou dois
    # casos na mesma conversa — mover a entrevista em silêncio faria o primeiro caso
    # perder a entrevista dele sem ninguém saber.
    if existente and existente.get("caso_id") != caso_id:
        raise HTTPException(
            409,
            "Esta gravação já está registrada em outro caso. "
            "Anexe a entrevista ao caso certo pelo dossiê.",
        )

    destino = armazenamento.DIR_ARQUIVOS / caso_id / "entrevistas"
    destino.mkdir(parents=True, exist_ok=True)
    nome = f"Entrevista guiada {dados.realizada_em or date.today().isoformat()}.txt"

    if existente:
        # O arquivo em disco acompanha o texto: é ele que o dossiê baixa, e um
        # arquivo com a conversa pela metade ao lado de uma transcrição completa
        # seria pior que não ter arquivo.
        Path(existente["caminho"]).write_text(texto, encoding="utf-8")
        armazenamento.atualizar_transcricao(
            existente["id"],
            texto,
            dados.realizada_em or existente.get("realizada_em") or "",
        )
        entrevista = armazenamento.obter_entrevista(existente["id"]) or existente
    else:
        caminho = destino / f"{uuid.uuid4().hex[:8]}-{nome}"
        caminho.write_text(texto, encoding="utf-8")
        entrevista = armazenamento.registrar_entrevista(
            caso_id,
            arquivo=nome,
            caminho=caminho,
            texto=texto,
            realizada_em=dados.realizada_em or date.today().isoformat(),
            entrevistador=_quem_conduziu(request),
            gravacao_id=dados.gravacao_id,
        )

    # A marcação da avaliação vem de quem estava na chamada, no momento em que ela
    # aconteceu — que é o único momento em que ela significa o que afirma. A
    # supervisão pode corrigi-la depois, mas não é ela quem deveria criá-la.
    armazenamento.marcar_avaliacao_google(entrevista["id"], dados.avaliacao_google)

    # O agente só lê a entrevista ENCERRADA. Mandar a conversa pela metade geraria
    # fatos a partir de um relato que ainda ia mudar, e o dossiê guarda fato, não
    # rascunho. `enviada` evita reenviar quando o atendente volta ao roteiro.
    if dados.concluida and texto and not entrevista.get("enviada"):
        threading.Thread(
            target=_ler_entrevista_no_agente,
            args=(caso_id, entrevista["id"]),
            name=f"agente-entrevista-{entrevista['id'][:8]}",
            daemon=True,
        ).start()

    return armazenamento.obter_entrevista(entrevista["id"]) or entrevista


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
    """O arquivo original ou, se o volume mudou, a transcrição preservada no banco."""
    registro = _entrevista_do_caso(caso_id, entrevista_id)
    caminho = Path(registro["caminho"]).resolve()
    if armazenamento.DIR_ARQUIVOS.resolve() in caminho.parents and caminho.is_file():
        return FileResponse(
            caminho,
            filename=registro["arquivo"],
            media_type="application/octet-stream",
        )

    # Atendimentos criados dentro do container guardavam ``/app/dados/...``. Quando a
    # API roda no host Windows esse caminho não existe, embora a transcrição integral
    # continue na coluna ``texto``. O download não pode depender de onde o volume foi
    # montado: para entrevista textual, o conteúdo preservado é o próprio artefato.
    texto = str(registro.get("texto") or "")
    if not texto.strip():
        raise HTTPException(404, "Arquivo e transcrição da entrevista não encontrados.")
    nome = str(registro.get("arquivo") or f"Entrevista {entrevista_id}.txt")
    if not nome.casefold().endswith(".txt"):
        nome = f"{Path(nome).stem or 'Entrevista'}.txt"
    return Response(
        content=texto.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(nome)}"},
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
    item = (
        next((i for i in categoria.itens if i.codigo == entrega["item_codigo"]), None)
        if categoria
        else None
    )
    if item is None:
        raise HTTPException(
            400, "Esta entrega não pertence a um item de checklist válido."
        )
    try:
        itens_atendidos = casos.itens_para_identidade_unificada(categoria, item)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    caminho = armazenamento.caminho_duravel_da_entrega(entrega_id)
    if caminho is None:
        raise HTTPException(
            410, "O anexo antigo não possui cópia recuperável; reenvie o arquivo."
        )
    bruto = caminho.read_bytes()

    # O botão é a confirmação expressa de que se trata de identidade unificada.
    # Reprocessamos no layout da CIN para extrair e validar o CPF sem depender de
    # o classificador conseguir nomear corretamente todas as versões do documento.
    resultado = await _processar(bruto, entrega["arquivo"], "pt", "cin")

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
    arquivo: UploadFile = File(...),
    item: str = Form(""),
):
    """Upload feito pelo cliente. Mesmo caminho do advogado, resposta enxuta.

    O item deixou de ser obrigatório: o cliente pode mandar o documento pela
    linha do checklist (e aí ele é um palpite) ou sem linha nenhuma.
    """
    caso = _caso_do_portal(token, request)
    await _registrar_documento(caso, item, arquivo, "pt", False)

    situacao = casos.montar_situacao(caso["id"])
    return casos.visao_do_cliente(situacao) if situacao else {}


@app.post("/api/portal/{token}/documentos/lote", status_code=201)
async def portal_enviar_lote(
    token: str,
    request: Request,
    arquivos: list[UploadFile] = File(...),
):
    """Envio em massa pelo cliente: manda tudo, o sistema separa.

    É o caminho que tira do cliente a tarefa de saber o que é cada papel — ele
    fotografa a pilha inteira e cada arquivo acha o próprio item do checklist.
    """
    caso = _caso_do_portal(token, request)
    resultado = await _registrar_lote(caso, arquivos, "pt")

    situacao = casos.montar_situacao(caso["id"])
    return {
        **resultado,
        "situacao": casos.visao_do_cliente(situacao) if situacao else {},
    }


@app.get("/api/entregas/{entrega_id}")
def obter_entrega(entrega_id: str):
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")
    entrega.pop("caminho", None)  # caminho no disco não interessa ao cliente HTTP
    entrega.pop("conteudo", None)
    entrega.pop("conteudo_sha256", None)
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

    caminho = armazenamento.caminho_duravel_da_entrega(entrega_id)
    if caminho is None:
        raise HTTPException(
            410,
            "O registro existe, mas este anexo antigo não possui cópia recuperável. Reenvie o arquivo.",
        )

    # `inline` deixa o navegador exibir o arquivo em vez de baixá-lo, que é o que
    # permite a pré-visualização no checklist. Passar só `filename=` produzia
    # `Content-Disposition: attachment` e obrigava a baixar para ver o que chegou.
    # Com `?download=1` o comportamento antigo continua disponível.
    return FileResponse(
        caminho,
        filename=entrega["arquivo"],
        content_disposition_type="attachment" if download else "inline",
    )


@app.get("/api/entregas/{entrega_id}/arquivo.pdf")
def baixar_arquivo_entrega_pdf(entrega_id: str):
    """Preserva PDF original ou converte uma imagem apenas para o download."""
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")

    caminho = armazenamento.caminho_duravel_da_entrega(entrega_id)
    if caminho is None:
        raise HTTPException(
            410,
            "O registro existe, mas este anexo antigo não possui cópia recuperável. Reenvie o arquivo.",
        )

    destino = pipeline.TMP_DIR / f"entrega-{entrega_id}-{uuid.uuid4().hex}.pdf"
    try:
        pdf = conversao_pdf.converter_para_pdf(caminho, entrega["arquivo"], destino)
    except conversao_pdf.ErroConversaoPdf as exc:
        destino.unlink(missing_ok=True)
        raise HTTPException(415, str(exc)) from exc

    return FileResponse(
        pdf.caminho,
        media_type="application/pdf",
        filename=pdf.nome_download,
        background=BackgroundTask(pdf.caminho.unlink, missing_ok=True)
        if pdf.temporario
        else None,
    )


@app.get("/api/casos/{caso_id}/documentos.zip")
def baixar_documentos_do_caso(caso_id: str):
    """Tudo que o cliente enviou, num pacote só.

    Trinta documentos eram trinta cliques no checklist, um por linha, e a
    certeza de esquecer um. O pacote sai na ordem do checklist, com o nome do
    item em cada arquivo — do outro lado alguém confere contra a mesma lista.

    O ZIP é montado a cada pedido, e não guardado: documento novo entra no
    pacote seguinte sem ninguém precisar invalidar cache. Ele nasce em
    `pipeline.TMP_DIR`, que já é a pasta dos temporários, e é apagado assim que
    a resposta termina — arquivo de cliente não fica sobrando em disco.
    """
    destino = pipeline.TMP_DIR / f"documentos-{caso_id}-{uuid.uuid4().hex}.zip"
    resumo = casos.montar_zip(caso_id, destino)
    if resumo is None:
        destino.unlink(missing_ok=True)
        raise HTTPException(404, "Caso não encontrado.")

    if resumo["arquivos"] == 0:
        destino.unlink(missing_ok=True)
        raise HTTPException(404, "Este caso ainda não tem documentos enviados.")

    nome = re.sub(r"[^\w\- ]", "", resumo["cliente"]).strip() or caso_id[:8]
    return FileResponse(
        destino,
        media_type="application/zip",
        filename=f"Documentos - {nome}.zip",
        # Sem isto o .zip fica em disco até alguém limpar a pasta, e é papelada
        # de cliente. O `BackgroundTask` roda depois do último byte enviado.
        background=BackgroundTask(destino.unlink, missing_ok=True),
        headers={
            # O que NÃO entrou, para a tela poder avisar em vez de deixar o
            # atendente descobrir na hora de protocolar.
            "X-Arquivos": str(resumo["arquivos"]),
            "X-Faltando": str(len(resumo["faltando"])),
        },
    )


@app.delete("/api/entregas/{entrega_id}")
def excluir_entrega(entrega_id: str):
    if not armazenamento.excluir_entrega(entrega_id):
        raise HTTPException(404, "Entrega não encontrada.")
    return {"removido": True}


@app.get("/api/temp/{nome}")
def baixar_temp(nome: str):
    """Serve JSON, XML e PDFs temporários produzidos por workers."""
    if (
        not nome.endswith((".json", ".xml", ".pdf"))
        or "/" in nome
        or "\\" in nome
        or ".." in nome
    ):
        raise HTTPException(400, "Nome de arquivo inválido.")

    caminho = (pipeline.TMP_DIR / nome).resolve()
    if pipeline.TMP_DIR.resolve() not in caminho.parents or not caminho.is_file():
        raise HTTPException(404, "Arquivo temporário não encontrado ou já expirado.")

    media = (
        "application/json"
        if nome.endswith(".json")
        else "application/pdf"
        if nome.endswith(".pdf")
        else "application/xml"
    )
    return FileResponse(caminho, media_type=media, filename=nome)


@app.delete("/api/temp")
def limpar():
    return {"removidos": pipeline.limpar_temporarios()}
