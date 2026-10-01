"""Página inicial, saúde da API e da fila, configuração pública e arquivos temporários."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import (
    armazenamento,
    auth,
    captcha,
    dois_fatores,
    pipeline,
)
from ..celery_app import celery_app
from ..extractors import ROTULOS_TIPO
from .comum import STATIC, _ocr_aquecido, log

roteador = APIRouter()


@roteador.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@roteador.get("/api/tipos")
def tipos():
    return {"tipos": [{"codigo": k, "descricao": v} for k, v in ROTULOS_TIPO.items()]}


#: Onde a API alcança o serviço de transcrição por dentro da rede do cluster.
#:
#: Em produção o navegador chega na transcrição pelo Traefik, que só roteia
#: `/ws/transcricao` e `/entrevista` — o `/saude` dela NÃO é alcançável de fora.
#: A API está na mesma rede `interna` e pode perguntar por ela.
URL_TRANSCRICAO_INTERNA = os.getenv(
    "URL_TRANSCRICAO_INTERNA", "http://localhost:8200"
).rstrip("/")


@roteador.get("/api/saude/transcricao")
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


@roteador.get("/api/saude")
def saude(fila: bool = False):
    """Sonda de saúde. `?fila=1` acrescenta o estado da leitura de documentos.

    O acréscimo é OPCIONAL de propósito. Esta rota é a sonda de inicialização do
    `iniciar.ps1`, chamada em laço com 2 s de timeout; perguntar ao broker e aos
    workers em toda chamada colocaria segundos no caminho quente por um dado que
    quase ninguém está pedindo. Com o parâmetro, quem precisa diagnosticar pede —
    inclusive de fora do servidor, que é o ponto: `/metrics` mora fora de `/api/`
    e o proxy o devolve como 404.
    """
    from .. import ocr_engine

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


@roteador.get("/api/saude/fila")
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
    from ..ocr_saude import snapshot as snapshot_ocr
    from ..tasks.manutencao import MINUTOS_TRAVADA

    resposta: dict[str, Any] = {"broker": _sem_segredo(celery_app.conf.broker_url)}
    try:
        resposta["snapshot"] = snapshot_ocr()
    except Exception as exc:
        resposta["snapshot"] = {"state": "UNKNOWN", "error": type(exc).__name__}

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


@roteador.get("/api/config")
def config():
    """O que a tela precisa saber sobre a sessão. Público e sem segredo.

    Sobrou pouco depois que o Keycloak saiu: não há mais URL de servidor de
    identidade nem client_id para o navegador descobrir. O que fica é o que a
    tela decide com base nisto — mostrar ou não a tela de login, desenhar ou não
    o widget do captcha, e com que chave.

    A `site key` do Turnstile é pública por definição (o navegador precisa dela)
    e mesmo assim vem por aqui em vez de `NEXT_PUBLIC_TURNSTILE_SITE_KEY`: o
    `.env.example` já registra o estrago que variável embutida no bundle fez
    quando o sistema foi aberto de outro computador. Servida daqui, ela acompanha
    o servidor que respondeu."""
    return {
        "auth": auth.configuracao_publica(),
        "captcha": captcha.configuracao_publica(),
        "doisFatores": dois_fatores.configuracao_publica(),
    }


@roteador.get("/api/eu")
def eu(usuario: auth.Usuario = Depends(auth.usuario_atual)):
    """Quem está autenticado nesta requisição."""
    return usuario.to_dict()


def _aquecer_modelo() -> None:
    """Carrega o PaddleOCR e conclui a primeira inferência."""
    from ..ocr_engine import aquecer_modelo

    aquecer_modelo()


def _tentar_aquecer() -> None:
    try:
        _aquecer_modelo()
        _ocr_aquecido.set()
        log.info("Modelo de OCR aquecido e pronto.")
    except Exception:
        # Sem rede na primeira execução, por exemplo: o upload tenta de novo.
        log.exception("Falha ao aquecer o modelo no boot")


@roteador.post("/api/aquecer")
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


@roteador.get("/api/temp/{nome}")
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


@roteador.delete("/api/temp")
def limpar():
    return {"removidos": pipeline.limpar_temporarios()}
