"""API do extrator de documentos (FastAPI + Mistral OCR).

Este arquivo só monta o app: ciclo de vida, middlewares, CORS e a ordem dos
routers. As rotas ficam em `app/rotas/` (uma área por arquivo) e nos módulos que
já tinham router próprio.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from . import (
    advbox,
    agente,
    armazenamento,
    assinatura_config,
    auth,
    case_brief_estado,
    chat,
    dados,
    documentacao,
    duplicidade,
    google_drive,
    historico_alteracoes,
    investigacao,
    jobs,
    jurisprudencia_api,
    localidades,
    observabilidade,
    operacao,
    perfis,
    revisao,
    skills_juridicas,
    supervisao,
    tactiq,
    tipos_caso,
    tipos_documento,
    usuarios,
    whatsapp,
)
from .banco import limite_de_espera_por_lock
from .rotas import (
    analise,
    assinatura as rotas_assinatura,
    casos as rotas_casos,
    categorias as rotas_categorias,
    chamada as rotas_chamada,
    contratos,
    documentos,
    entrevista as rotas_entrevista,
    entrevistas_caso,
    extracao,
    gastos,
    peticao_modelos,
    portal as rotas_portal,
    revisao as rotas_revisao,
    roteiros as rotas_roteiros,
    saude,
    tactiq as rotas_tactiq,
)
from .rotas.comum import BASE, log
from .rotas.saude import _tentar_aquecer

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

#: Quanto cada etapa da subida espera por um lock antes de desistir. Generoso para
#: o banco remoto sob carga, curto perto do "para sempre" que travava a API.
ESPERA_LOCK_NA_SUBIDA_MS = int(os.getenv("ESPERA_LOCK_NA_SUBIDA_MS", "15000"))


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
    # A subida não espera lock para sempre (ver `banco.limite_de_espera_por_lock`):
    # uma transação esquecida em outra máquina, no banco compartilhado, prendia o
    # uvicorn antes de abrir a porta. Cada etapa abaixo já tolera a própria falha.
    with limite_de_espera_por_lock(ESPERA_LOCK_NA_SUBIDA_MS):
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
            await run_in_threadpool(revisao.inicializar)
        except Exception:
            log.exception("Não foi possível inicializar a tabela de revisões")
        try:
            await run_in_threadpool(assinatura_config.inicializar)
        except Exception:
            log.exception("Não foi possível inicializar a configuração de assinatura eletrônica")
        try:
            await run_in_threadpool(tactiq.inicializar)
        except Exception:
            log.exception("Não foi possível inicializar a conexão Tactiq")
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
        try:
            await run_in_threadpool(historico_alteracoes.inicializar)
        except Exception:
            log.exception("Não foi possível inicializar o histórico de alterações")
        try:
            await run_in_threadpool(case_brief_estado.inicializar)
        except Exception:
            log.exception("Não foi possível inicializar o estado do case brief")
        try:
            # Sem os tipos de sistema, a reclassificação cai no nome do item de
            # checklist — o comportamento de antes do glossário, e não uma falha.
            await run_in_threadpool(tipos_documento.inicializar)
        except Exception:
            log.exception("Não foi possível inicializar o glossário de tipos de documento")
        try:
            # Depois do glossário: o checklist de uma ação criada aqui aponta para
            # os tipos de documento, e a validação precisa deles no lugar.
            await run_in_threadpool(tipos_caso.inicializar)
        except Exception:
            log.exception("Não foi possível inicializar o catálogo de tipos de caso")
    yield


app = FastAPI(
    title="Cláudia",
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
    # Os dois passos seguintes do login TAMBEM sao anteriores a sessao. Quem esta
    # confirmando o codigo do segundo fator, por definicao, ainda nao tem cookie:
    # ele so nasce depois do `verify`. Sem estas duas linhas o middleware devolve
    # "Autenticacao necessaria" antes de a rota rodar, e o login com segundo fator
    # fica impossivel de concluir -- com o agravante de nao deixar rastro: o
    # contador de tentativas do desafio nem chega a ser tocado, entao a tabela
    # mostra `tentativas = 0` e parece que ninguem tentou.
    "/api/user/authenticate/verify",
    "/api/user/authenticate/resend",
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
app.include_router(jurisprudencia_api.roteador)
app.include_router(localidades.roteador)
app.include_router(usuarios.roteador)
app.include_router(usuarios.roteador_sessao)
app.include_router(supervisao.roteador)
app.include_router(dados.roteador)
app.include_router(documentacao.roteador)
# A tela única de perguntas: web, acervo, caso e documentos (ver `app/chat/`).
app.include_router(chat.roteador)
app.include_router(operacao.roteador)
app.include_router(whatsapp.roteador)
app.include_router(tipos_documento.roteador)
app.include_router(tipos_caso.roteador)
app.include_router(google_drive.roteador)


@app.exception_handler(duplicidade.DocumentoDuplicado)
async def responder_documento_duplicado(_: Request, exc: duplicidade.DocumentoDuplicado):
    """O 409 de duplicidade leva a lista do que parece repetido, e não só a frase.

    `detail` continua sendo texto, como em todo erro desta API: quem só mostra a
    mensagem (o portal, o envio em lote) não precisa saber de duplicidade. A tela da
    equipe lê `codigo` e `duplicidades` para oferecer a confirmação.
    """
    return JSONResponse(exc.corpo(), status_code=409)


@app.middleware("http")
async def rede_de_seguranca(request: Request, call_next):
    """Último anteparo: nenhuma falha inesperada vira tela vermelha de 500.

    Registrado ANTES da autenticação para virar a camada mais interna entre os
    middlewares deste app — assim envolve as rotas e ainda fica por dentro do
    CORS (adicionado depois), garantindo cabeçalho CORS até na resposta de erro.
    HTTPException e as respostas já tratadas passam intactas; o que cai aqui é o
    imprevisto, que vira um 503 legível em vez de traceback cru no navegador.
    """
    try:
        return await call_next(request)
    except HTTPException:
        # Tratada pelo próprio FastAPI mais acima na pilha; não é imprevisto.
        raise
    except Exception:  # noqa: BLE001 — a rede de segurança precisa pegar tudo.
        log.exception("Falha não tratada em %s %s", request.method, request.url.path)
        return JSONResponse(
            {
                "detail": (
                    "Este recurso está indisponível no momento. Nada foi perdido; "
                    "tente de novo em instantes."
                )
            },
            status_code=503,
        )


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
        "X-Problemas",
    ],
)


armazenamento.inicializar()
try:
    skills_juridicas.importar_embutida(BASE / "escritorio-trabalhista.skill.zip")
except Exception:  # noqa: BLE001 - skill extra não pode impedir a API de subir
    log.warning("Skill jurídica embutida não pôde ser instalada", exc_info=True)
try:
    google_drive.inicializar()
except Exception:  # noqa: BLE001
    log.warning("Tabela de configuração do Google Drive não pôde ser criada", exc_info=True)


# Rotas próprias da API, uma área por arquivo em `app/rotas/`. A ordem só importa
# entre caminhos que podem casar o mesmo endereço (ex.: `/api/modelos/peticao/...`
# antes de `/api/modelos/{codigo}`); `tests/test_rotas_intactas.py` confere isso.
for _area in (
    gastos,
    saude,
    rotas_roteiros,
    contratos,
    peticao_modelos,
    rotas_entrevista,
    rotas_assinatura,
    rotas_categorias,
    rotas_tactiq,
    extracao,
    rotas_chamada,
    analise,
    rotas_casos,
    rotas_revisao,
    documentos,
    entrevistas_caso,
    rotas_portal,
):
    app.include_router(_area.roteador)


# Nomes que os testes e scripts ainda leem de `app.main`.
from .agente import dossie as dossie_agente  # noqa: E402,F401
from .celery_app import celery_app  # noqa: E402,F401
from .rotas.registro_documentos import (  # noqa: E402,F401
    MAX_ITENS_ZIP,
    _ArquivoEmMemoria,
    _expandir_zips,
)
from .rotas.saude import _ESTADO_LEITURA, _estado_da_leitura  # noqa: E402,F401
