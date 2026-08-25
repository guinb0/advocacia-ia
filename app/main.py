"""API do extrator de documentos (FastAPI + PaddleOCR)."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import jwt

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
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from . import (
    agente,
    advbox,
    analise_resposta,
    armazenamento,
    assinatura,
    auth,
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
    roteiros,
    triagem,
    valor_documento,
    whatsapp,
)
from . import jobs, observabilidade
from . import entrevista as entrevista_lib
from .agente import dossie as dossie_agente
from .extractors import ROTULOS_TIPO
from .tasks.ocr import processar_documento, processar_entrega
from .tasks.documentos import gerar_relatorio as gerar_relatorio_job
from .tasks.ia import gerar_estrategia as gerar_estrategia_job

# Onde o frontend atende — é o que monta o link enviado ao cliente.
URL_PORTAL = os.getenv("URL_PORTAL", "http://localhost:3000").rstrip("/")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")

BASE = Path(__file__).resolve().parent.parent
STATIC = BASE / "static"

MAX_BYTES = 20 * 1024 * 1024
EXTENSOES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".pdf"}
_ocr_aquecido = threading.Event()


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    """Inicializa a API sem duplicar o Paddle que pertence ao worker Celery.

    A tela envia arquivos a `/api/extrair/jobs`; quem os lê é o worker `ocr@`,
    aquecido em `tasks/ocr.py`. Carregar outro modelo aqui gastava memória e CPU
    sem reduzir a latência real. O opt-in preserva o endpoint síncrono legado.
    """
    if os.getenv("OCR_AQUECER_API", "0") == "1":
        threading.Thread(target=_tentar_aquecer, name="aquecer-ocr", daemon=True).start()
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


app = FastAPI(title="Extrator de Documentos — PaddleOCR", version="1.0.0", lifespan=ciclo_de_vida)
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
    "/api/eu",                    # saber quem se é
    "/api/user/my-account",       # idem, no endereço do padrão DFLegal
    "/api/user/change-password",  # trocar a PRÓPRIA senha não é área restrita
    "/api/usuarios/perfis",       # vocabulário dos perfis, não dado de ninguém
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
    #: Qual dos documentos da papelada. Ver `contrato.MODELOS`.
    documento: str = "contrato"


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
            422, f"Documento {pedido.documento!r} não existe. Conhecidos: {', '.join(contrato.CODIGOS)}."
        )

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
    arquivo = f"{alvo['arquivo']} - {nome_cliente}.docx".replace("/", "-").replace("\\", "-")

    return Response(
        content=docx,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={
            # `filename*` em UTF-8 porque nome de cliente tem acento, e o
            # `filename` sem aspas quebraria no primeiro espaço.
            "Content-Disposition": (
                f'attachment; filename="{pedido.documento}.docx"; '
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
            escuta.escutar, pedido.trecho, pedido.respostas, pedido.roteiro,
            pedido.pergunta_atual
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

    tarefa = threading.Thread(target=_analisar, name="entrevista-precedentes", daemon=True)
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
    lacunas = [str(item).strip()[:500] for item in pedido.lacunas_obrigatorias if str(item).strip()]
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
                    doc["rotulo"], len(enviados), exc,
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
                502, f"A ZapSign aceitou {doc['rotulo'].lower()} mas não devolveu o token."
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
        enviados.append(_resposta_assinatura(registro))
        faltando += doc["faltando"]

        log.info(
            "%s de %s enviada para assinatura (%d signatário(s)).",
            doc["rotulo"], cliente, resumo["total"],
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
    from . import ocr_engine

    ocr_via_worker = os.getenv("OCR_AQUECER_API", "0") != "1"
    return {
        "status": "ok",
        "modelo_carregado": ocr_engine.modelo_carregado(),
        "modelo_aquecido": _ocr_aquecido.is_set(),
        "ocr_via_worker": ocr_via_worker,
    }


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
            args=(job_id, str(caminho), arquivo.filename or "sem-nome", idioma, tipo_forcado),
            queue="gpu_background",
            priority=7,
        )
        await run_in_threadpool(jobs.vincular_tarefa, job_id, tarefa.id)
        return {"job_id": job_id, "task_id": tarefa.id, "status": "QUEUED", "progresso": 0}
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


def gerar_token_jitsi(sala: str) -> str:
    """Gera JWT HS256 para o Jitsi aceitar a conexão.

    O Jitsi valida tokens com aud/iss/sub = JITSI_JWT_APP_ID e room = nome da sala.
    O secret é compartilhado com o Prosody (configurado em docker-jitsi-meet/.env).
    """
    secret = os.environ.get("JITSI_JWT_APP_SECRET", "")
    if not secret:
        log.warning("JITSI_JWT_APP_SECRET não configurado — Jitsi vai rejeitar a conexão")
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
def criar_sala(sala: str | None = None):
    """Sorteia uma sala de chamada e devolve o link para mandar ao entrevistado.

    A entrevista acontece ANTES de o caso existir — é ela que decide a categoria
    —, então a sala não pode depender de caso nem de portal. O nome da sala é o
    segredo: 256 bits sorteados, do mesmo gerador que assina o portal. Quem tem
    o link entra; quem não tem não adivinha.

    Sala é efêmera e não é gravada em lugar nenhum: existe enquanto houver
    alguém dentro (ver `app/chamada.py`).

    O token JWT é exigido pelo Jitsi quando AUTH_TYPE=jwt. O cliente também
    chama este endpoint com o sala existente para obter o próprio token.
    """
    if sala is None:
        sala = chamada.gerar_sala()
    token = gerar_token_jitsi(sala)
    return {"sala": sala, "url": f"{URL_PORTAL}/chamada/{sala}", "token": token}


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

        espelho.enviar_entrevista(caso_id, entrevista_id)
    except Exception:  # noqa: BLE001 - fronteira com serviço externo
        log.warning("não foi possível ler a entrevista %s no agente", entrevista_id, exc_info=True)


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

    # O arquivo vai para o disco e a entrega é criada antes de entrar na fila.
    # Assim o upload responde sem manter a conexão aberta durante a inferência.
    destino = armazenamento.DIR_ARQUIVOS / caso_id
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{item}_{uuid.uuid4()}{Path(nome).suffix.lower()}"
    caminho.write_bytes(conteudo)

    entrega = armazenamento.registrar_entrega_pendente(caso_id, item, nome, caminho)

    # O checklist antes abria uma thread na API e carregava outra cópia do
    # Paddle no primeiro envio (97–200s). O worker OCR já nasce aquecido e é o
    # único dono do modelo; a requisição continua voltando imediatamente.
    try:
        tarefa = processar_entrega.apply_async(
            args=(
                entrega["id"], caso_id, str(caminho), nome, item_checklist.codigo,
                categoria.codigo, idioma, usar_para_rg_e_cpf,
            ),
            queue="gpu_background",
            priority=7,
        )
    except Exception as exc:
        armazenamento.falhar_entrega(entrega["id"], "Fila de OCR indisponível.")
        log.exception("Falha ao enfileirar a entrega %s", entrega["id"])
        raise HTTPException(503, "Fila de leitura indisponível. Tente novamente.") from exc

    return {"entrega": entrega, "processando": True, "task_id": tarefa.id}


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
        raise HTTPException(400, f"Item '{item}' não pertence ao checklist de {categoria.nome}.")

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
        "validacao": {"veredito": "APROVADO", "dados_utilizaveis": True, "score_legibilidade": 100},
        "campos": [],
        "texto_completo": texto,
    }
    tipo_confere = True if tipo else None

    entrega = armazenamento.registrar_entrega(caso_id, item, nome, caminho, extracao, tipo_confere)

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
            existente["id"], texto, dados.realizada_em or existente.get("realizada_em") or ""
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


@app.get("/api/entregas/{entrega_id}/arquivo.pdf")
def baixar_arquivo_entrega_pdf(entrega_id: str):
    """Preserva PDF original ou converte uma imagem apenas para o download."""
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")

    caminho = Path(entrega["caminho"]).resolve()
    if armazenamento.DIR_ARQUIVOS.resolve() not in caminho.parents or not caminho.is_file():
        raise HTTPException(404, "Arquivo não encontrado no disco.")

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
        background=BackgroundTask(pdf.caminho.unlink, missing_ok=True) if pdf.temporario else None,
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
    if not nome.endswith((".json", ".xml", ".pdf")) or "/" in nome or "\\" in nome or ".." in nome:
        raise HTTPException(400, "Nome de arquivo inválido.")

    caminho = (pipeline.TMP_DIR / nome).resolve()
    if pipeline.TMP_DIR.resolve() not in caminho.parents or not caminho.is_file():
        raise HTTPException(404, "Arquivo temporário não encontrado ou já expirado.")

    media = (
        "application/json" if nome.endswith(".json")
        else "application/pdf" if nome.endswith(".pdf")
        else "application/xml"
    )
    return FileResponse(caminho, media_type=media, filename=nome)


@app.delete("/api/temp")
def limpar():
    return {"removidos": pipeline.limpar_temporarios()}
