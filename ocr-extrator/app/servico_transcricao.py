"""Serviço de transcrição — processo separado, só Whisper.

Por que não fica junto da API principal:

1. **CPU.** Medido nesta máquina: o mesmo áudio de 11s levou 3,2s transcrito
   isoladamente e 227s com o PaddleOCR carregado no mesmo processo. Os dois
   modelos disputavam os mesmos núcleos e a transcrição ao vivo ficava inútil.

2. **DLL.** No Windows, PaddlePaddle e CTranslate2 trazem cópias próprias de
   MKL/OpenMP; carregar o Paddle primeiro faz o CTranslate2 estourar com
   `OSError [WinError 127]`. Sem o Paddle aqui, o problema deixa de existir.

3. **Independência.** Reiniciar a transcrição não derruba o OCR, e vice-versa.

Sobe com:
    .venv\\Scripts\\python.exe -m uvicorn app.servico_transcricao:app --port 8200

O `iniciar.ps1` já faz isso.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from . import transcricao

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("servico-transcricao")

ORIGENS = [
    o.strip()
    for o in os.getenv(
        "ORIGENS_PERMITIDAS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if o.strip()
]


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    """Carrega o Whisper no boot: são ~85s que ninguém quer pagar na 1ª pergunta."""

    def aquecer():
        try:
            transcricao.carregar_modelo()
            log.info("Whisper pronto.")
        except Exception:
            log.exception("Falha ao carregar o Whisper")

    threading.Thread(target=aquecer, name="aquecer-whisper", daemon=True).start()
    yield


app = FastAPI(title="Transcrição de entrevista", version="1.0.0", lifespan=ciclo_de_vida)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

_sessoes = transcricao.Sessoes()


@app.get("/saude")
def saude():
    return {"status": "ok", "modelo_carregado": transcricao.modelo_carregado()}


async def _enviar_parcial(ws: WebSocket, sessao: transcricao.AnswerSession) -> None:
    """Transcreve a janela atual e manda o texto provisório para a tela.

    Roda como tarefa própria, e essa é a diferença entre ver a frase sendo
    escrita e vê-la aparecer pronta no fim: esperar a transcrição dentro do laço
    de recepção pararia de consumir o áudio que continua chegando, e o texto
    andaria aos trancos, sempre atrás da fala.
    """
    try:
        texto = await run_in_threadpool(sessao.transcrever_parcial)
        # A resposta pode ter sido finalizada enquanto o modelo rodava. Mandar o
        # parcial depois do final faria o texto voltar atrás na tela.
        if texto and sessao.estado is transcricao.Estado.LISTENING:
            await ws.send_json(
                {"type": "partial", "sessionId": sessao.sessao_id, "text": texto}
            )

            # E, separado do parcial, o que acabou de CONGELAR. O parcial é
            # aproximação que se reescreve; o trecho não muda mais, e é por isso
            # que ele — e só ele — pode alimentar o preenchimento do roteiro.
            trecho = sessao.trecho_confirmado()
            if trecho:
                await ws.send_json(
                    {"type": "trecho", "sessionId": sessao.sessao_id, "text": trecho}
                )
    except Exception:
        # Parcial é descartável: o próximo já vem com o texto acumulado, e o
        # final é transcrito do áudio inteiro de qualquer jeito.
        log.warning("Parcial descartado", exc_info=True)
    finally:
        sessao.parcial_em_curso = False


@app.websocket("/ws/transcricao")
async def ws_transcricao(ws: WebSocket):
    """Recebe áudio da entrevista e devolve a transcrição da resposta.

        → {"type":"start","sessionId":..,"questionId":..}
        → frames binários: Float32 PCM mono 16 kHz
        → {"type":"stop","sessionId":..}
        ← {"type":"aquecendo"}           o modelo ainda está carregando
        ← {"type":"partial","text":..}   ~1x por segundo de fala
        ← {"type":"final","text":..}     ao finalizar

    A conexão fica aberta entre perguntas, junto com o microfone.
    """
    await ws.accept()
    atual: str | None = None
    # Guardar a referência das tarefas é obrigatório: o asyncio só mantém uma
    # referência fraca, e uma tarefa coletada no meio some sem aviso.
    parciais: set[asyncio.Task] = set()

    try:
        while True:
            msg = await ws.receive()

            if msg.get("type") == "websocket.disconnect":
                break

            if (texto := msg.get("text")) is not None:
                evento = json.loads(texto)
                tipo = evento.get("type")

                if tipo == "start":
                    atual = str(evento.get("sessionId") or uuid.uuid4())
                    _sessoes.abrir(atual, str(evento.get("questionId", "")))
                    await ws.send_json({"type": "started", "sessionId": atual})
                    # São ~85s de carga do Whisper. Sem este aviso a tela fica
                    # muda e parece quebrada — e é justamente quando alguém já
                    # está falando, achando que está sendo transcrito.
                    if not transcricao.modelo_carregado():
                        await ws.send_json({"type": "aquecendo"})

                elif tipo == "stop":
                    sid = str(evento.get("sessionId") or atual or "")
                    sessao = _sessoes.fechar(sid)
                    if sessao is None:
                        await ws.send_json({"type": "error", "detail": "Sessão desconhecida."})
                    else:
                        # Marca o fim ANTES de transcrever: um parcial que ainda
                        # esteja rodando confere este estado e desiste de enviar,
                        # em vez de chegar depois do final e desfazer o texto.
                        sessao.estado = transcricao.Estado.FINISHING
                        final = await run_in_threadpool(sessao.transcrever_final)
                        await ws.send_json(
                            {
                                "type": "final",
                                "sessionId": sid,
                                "questionId": sessao.pergunta_id,
                                "text": final,
                                "duracao_s": round(sessao.duracao_s, 1),
                            }
                        )
                    atual = None

                elif tipo == "ping":
                    await ws.send_json({"type": "pong"})

            elif (dados := msg.get("bytes")) is not None:
                sessao = _sessoes.obter(atual) if atual else None
                if sessao is None:
                    continue  # áudio fora de resposta ativa: descartado
                sessao.acrescentar(transcricao.pcm_de_bytes(dados))

                if sessao.iniciar_parcial():
                    tarefa = asyncio.create_task(_enviar_parcial(ws, sessao))
                    parciais.add(tarefa)
                    tarefa.add_done_callback(parciais.discard)

    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Erro na transcrição")
        try:
            await ws.send_json({"type": "error", "detail": "Falha na transcrição."})
        except Exception:
            pass
    finally:
        # Um parcial em curso escreve num WebSocket que já morreu. Cancelar é só
        # limpeza: o `_enviar_parcial` engole o erro, mas a tarefa órfã ficaria
        # segurando o áudio da sessão na memória até terminar.
        for tarefa in parciais:
            tarefa.cancel()
        if atual:
            _sessoes.fechar(atual)
