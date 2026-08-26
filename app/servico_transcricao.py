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

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from . import gravacao, transcricao, transcricao_openrouter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("servico-transcricao")

ORIGENS = [
    o.strip()
    for o in os.getenv(
        "ORIGENS_PERMITIDAS", "http://localhost:3000,http://127.0.0.1:3000"
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
_whisper_aquecido = threading.Event()


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    """Carrega e AQUECE o Whisper no boot — quando o Whisper é o motor.

    Eram ~85s de carga que ninguém queria pagar na 1ª pergunta — e faltava a
    outra metade: com os pesos já na GPU, a primeira inferência de verdade
    ainda custava 30s (kernels CUDA e caches do cuDNN). Ver
    `transcricao.aquecer_modelo`.

    Com a OpenRouter ligada não há o que aquecer, e carregar o modelo assim mesmo
    gastaria os 85s e a RAM de um modelo que nunca seria chamado. A transcrição
    fica pronta na hora — o custo saiu do boot e foi para cada requisição.
    """
    if transcricao.usando_openrouter():
        log.info(
            "Transcrição pela OpenRouter (%s). Whisper local não será carregado.",
            transcricao_openrouter.MODELO,
        )
        if not transcricao_openrouter.configurada():
            log.warning(
                "OPENROUTER_API_KEY ausente: a transcrição vai falhar em toda "
                "resposta. Preencha o .env ou volte para MOTOR_TRANSCRICAO=whisper."
            )
        _whisper_aquecido.set()
        yield
        return

    def aquecer():
        try:
            transcricao.aquecer_modelo()
            _whisper_aquecido.set()
            log.info("Whisper pronto.")
        except Exception:
            log.exception("Falha ao carregar o Whisper")

    threading.Thread(target=aquecer, name="aquecer-whisper", daemon=True).start()
    yield


app = FastAPI(title="Transcrição de entrevista", version="1.0.0", lifespan=ciclo_de_vida)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENS,
    allow_origin_regex=ORIGENS_REGEX or None,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

_sessoes = transcricao.Sessoes()
_gravacoes = gravacao.Gravacoes()


@app.get("/saude")
def saude():
    return {
        "status": "ok",
        "motor": transcricao.MOTOR,
        "modelo": (
            transcricao_openrouter.MODELO
            if transcricao.usando_openrouter()
            else transcricao.MODELO
        ),
        # Com a OpenRouter não há modelo local: "pronto" é ter a chave.
        "modelo_carregado": (
            transcricao_openrouter.configurada()
            if transcricao.usando_openrouter()
            else transcricao.modelo_carregado()
        ),
        "modelo_aquecido": _whisper_aquecido.is_set(),
    }


# ----------------------------------------------------------------- gravação
#
# O áudio da entrevista sai daqui porque é aqui que ele já chega. Ver o
# cabeçalho de `app/gravacao.py` para o porquê de não ser o navegador a gravar.


@app.get("/entrevista/{entrevista_id}/gravacao")
def situacao_gravacao(entrevista_id: str):
    """Se há áudio desta entrevista, quanto ele dura e se o MP4 já está pronto."""
    try:
        return gravacao.metadados(entrevista_id)
    except gravacao.ErroGravacao as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/entrevista/{entrevista_id}/encerrar")
async def encerrar_gravacao(entrevista_id: str):
    """Fecha a gravação e converte para MP4.

    Fora do laço de eventos: são ~25s numa entrevista de 40 minutos, e segurar o
    laço aqui pararia a transcrição de qualquer outra entrevista em curso.

    É POST e não uma mensagem do WebSocket de propósito — assim o encerramento
    funciona mesmo quando a conexão já caiu, que é exatamente quando o áudio
    guardado importa mais.
    """
    # Devolve a vez ao laço antes de fechar o arquivo. São duas conexões
    # diferentes: os últimos blocos de PCM podem ter chegado ao sistema e ainda
    # não terem sido lidos quando este POST entrou, e fechar agora cortaria os
    # segundos finais da fala. O cliente já esvaziou a fila do lado dele.
    await asyncio.sleep(0.3)
    try:
        return await run_in_threadpool(_gravacoes.encerrar, entrevista_id)
    except gravacao.ErroGravacao as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/entrevista/{entrevista_id}/audio")
def baixar_audio(entrevista_id: str):
    """O MP4 para baixar ou tocar na própria tela.

    Só entrega o que já foi convertido: converter aqui deixaria a requisição
    pendurada por dezenas de segundos, sem nada na tela explicando o quê. Quem
    converte é o `POST .../encerrar`, e o 409 abaixo diz à tela para chamá-lo.
    """
    try:
        caminho = gravacao.caminho_mp4(entrevista_id)
    except gravacao.ErroGravacao as exc:
        raise HTTPException(400, str(exc)) from exc

    if not caminho.exists():
        situacao = gravacao.metadados(entrevista_id)
        if situacao["existe"]:
            raise HTTPException(409, "A gravação ainda não foi convertida.")
        raise HTTPException(404, "Não há gravação desta entrevista.")

    return FileResponse(
        caminho,
        media_type="audio/mp4",
        filename=gravacao.nome_para_baixar(entrevista_id),
    )


async def _enviar_parcial(ws: WebSocket, sessao: transcricao.AnswerSession) -> None:
    """Transcreve a janela atual e manda o texto provisório para a tela.

    Roda como tarefa própria, e essa é a diferença entre ver a frase sendo
    escrita e vê-la aparecer pronta no fim: esperar a transcrição dentro do laço
    de recepção pararia de consumir o áudio que continua chegando, e o texto
    andaria aos trancos, sempre atrás da fala.
    """
    try:
        texto = await run_in_threadpool(sessao.transcrever_parcial)

        # O diagnóstico sai SEMPRE, com texto ou sem.
        #
        # Prendê-lo ao parcial (que só é enviado quando há texto) o calaria
        # justamente no caso em que ele importa: nada sendo reconhecido. Era esse
        # silêncio que fazia "ouvindo — nada reconhecido ainda" parecer defeito
        # do modelo, quando a causa estava no áudio que nunca chegou inteiro.
        if sessao.estado is transcricao.Estado.LISTENING:
            await ws.send_json(
                {
                    "type": "diagnostico",
                    "sessionId": sessao.sessao_id,
                    "chegada": round(sessao.fator_chegada(), 2),
                }
            )

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
                # A linha que faltava para fechar o diagnóstico.
                #
                # O log do parcial já dizia quantos segmentos saíram, mas não se
                # algum chegou a CONGELAR — e é o congelado, só ele, que vira
                # `trecho` e alimenta a escuta que preenche o roteiro. Sem isto,
                # "não preenche nada" tinha duas causas indistinguíveis: o
                # Whisper não reconhecendo, ou a cauda nunca fechando por falta
                # de pausa (ver `_congelar` e MARGEM_CAUDA_S).
                log.info("trecho confirmado (%d car.) -> escuta: %.60s", len(trecho), trecho)
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

        → {"type":"start","sessionId":..,"questionId":..,"entrevistaId":..}
        → frames binários: Float32 PCM mono 16 kHz
        → {"type":"stop","sessionId":..}
        ← {"type":"aquecendo"}           o modelo ainda está carregando
        ← {"type":"partial","text":..}   ~1x por segundo de fala
        ← {"type":"final","text":..}     ao finalizar

    A conexão fica aberta entre perguntas, junto com o microfone.

    O `entrevistaId` é o que costura tudo num arquivo só: a escuta contínua, as
    respostas gravadas uma a uma e os complementos são sessões diferentes da
    MESMA entrevista, e o áudio delas vai para a mesma gravação.
    """
    await ws.accept()
    atual: str | None = None
    grav: gravacao.Gravacao | None = None
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

                    # Sem `entrevistaId` nada é gravado, e isso é intencional:
                    # quem não mandou o campo é um cliente antigo, que não tem
                    # como avisar o entrevistado de que o áudio está sendo
                    # guardado nem como oferecer o arquivo depois.
                    entrevista_id = str(evento.get("entrevistaId") or "")
                    if entrevista_id and gravacao.identificador_valido(entrevista_id):
                        try:
                            grav = _gravacoes.abrir(entrevista_id)
                        except gravacao.ErroGravacao:
                            # Disco cheio, pasta sem permissão: a entrevista
                            # continua e é transcrita. Perder o áudio é ruim;
                            # parar a conversa por causa dele é pior.
                            log.exception("Não foi possível gravar o áudio")
                            grav = None

                    await ws.send_json(
                        {"type": "started", "sessionId": atual, "gravando": grav is not None}
                    )
                    # São ~85s de carga do Whisper. Sem este aviso a tela fica
                    # muda e parece quebrada — e é justamente quando alguém já
                    # está falando, achando que está sendo transcrito.
                    # Com a OpenRouter não há carga a esperar; o aviso só faria
                    # sentido se a chave faltasse, e aí o erro vem na 1ª resposta
                    # com a mensagem certa.
                    if not transcricao.usando_openrouter() and not transcricao.modelo_carregado():
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
                pcm = transcricao.pcm_de_bytes(dados)
                sessao.acrescentar(pcm)
                # A gravação recebe o MESMO PCM, e não uma cópia do fluxo: é o
                # que garante que o arquivo seja exatamente o que foi
                # transcrito. Ela não tem o teto de 30 min da sessão — aquele
                # protege memória, e isto vai para o disco.
                if grav is not None:
                    grav.acrescentar(pcm)

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
        # Solta o arquivo sem encerrar a gravação: a aba pode ter recarregado no
        # meio da entrevista, e a próxima conexão continua no mesmo arquivo. O
        # cabeçalho do WAV fica acertado no intervalo, então o que já foi dito
        # está tocável mesmo que ninguém volte.
        if grav is not None:
            grav.fechar_arquivo()
