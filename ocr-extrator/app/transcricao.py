"""Transcrição incremental da resposta do entrevistado (faster-whisper).

Dois níveis de sessão, como o roteiro da entrevista pede:

    CaptureSession   o áudio compartilhado do Meet, aberto a entrevista inteira
        └── AnswerSession   uma resposta, entre "iniciar" e "finalizar"

A captura nunca fecha; o que liga e desliga é o envio. Isso evita pedir a
seleção da aba a cada pergunta, que é o incômodo que motivou tudo isto.

O chunk é só transporte: transcrever cada pedaço isolado picaria a frase e
perderia contexto ("fui" viraria "foi"). O áudio é acumulado e o modelo roda
sobre a janela, não sobre o fragmento.

Modelo `small` int8 medido nesta máquina: carrega em ~85s, transcreve a 3,6x
o tempo real. `base` é 3x mais rápido mas erra pessoa verbal; num relato que
vira peça processual, isso não compensa.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

log = logging.getLogger("transcricao")

# ATENÇÃO — a ordem deste import não é decorativa.
#
# No Windows, PaddlePaddle e CTranslate2 trazem cada um a sua cópia de MKL/
# OpenMP. Quem carregar primeiro define quais símbolos ficam no processo, e o
# segundo quebra. Medido:
#
#     ctranslate2 -> paddle   ambos carregam
#     paddle -> ctranslate2   OSError [WinError 127]
#
# O PaddleOCR sobe na thread de aquecimento (main.ciclo_de_vida), depois dos
# imports, então trazer o CTranslate2 já aqui garante que ele chegue antes.
# Sem isto o WebSocket de transcrição morre com "Falha na transcrição" assim
# que o primeiro parcial tenta rodar.
try:
    import ctranslate2 as _ct2  # noqa: F401  (importado pelo efeito colateral)
except Exception as _exc:  # pragma: no cover
    log.warning("CTranslate2 indisponível — a transcrição não vai funcionar: %s", _exc)

TAXA = 16_000                    # o Whisper opera em 16 kHz mono
SEGUNDOS_ENTRE_PARCIAIS = 0.5    # cadência do texto provisório na tela
LIMITE_CAUDA_S = 8.0             # cauda máxima antes de cortar à força
MARGEM_CAUDA_S = 1.5             # o que ainda pode mudar com o que vem depois
SOBREPOSICAO_PARCIAL_S = 1.0     # emenda quando o corte é forçado
LIMITE_SESSAO_S = 60 * 30        # 30 min de resposta — trava contra vazamento

# O QUE MANTÉM O TEXTO COLADO NA FALA
#
# O custo de um parcial é proporcional ao áudio que ele transcreve. Medido nesta
# máquina (RTX 4050, small float16), transcrevendo o mesmo relato:
#
#      2s -> 0,12s      8s -> 0,23s      30s -> 0,93s      60s -> 1,89s
#
# Com janela de 30s, cada parcial custava 0,93s contra uma cadência de 1s: metade
# das rodadas era descartada por já haver outra em curso, e o texto chegava um
# segundo atrás da fala. Era o "não está em tempo real".
#
# Agora só a CAUDA é transcrita: o trecho desde a última pausa. Quando o Whisper
# fecha um segmento (ele fecha nas pausas, por causa do VAD) e esse segmento já
# está longe do fim, o texto dele é congelado no prefixo e a cauda recomeça dali.
# A cauda fica quase sempre em 2-4s, então cada parcial custa décimos e o custo
# para de crescer com o tamanho da resposta.
#
#     [-------- prefixo congelado --------][- cauda -]
#      transcrito uma vez, não muda mais    retranscrita a cada rodada
#
# A margem existe para não congelar cedo demais: a última palavra antes de uma
# pausa curta ainda pode mudar quando chega a próxima frase. E o texto final é
# transcrito do áudio inteiro, de uma vez — nada disto contamina o registro.

def _preparar_cuda() -> bool:
    """Deixa as DLLs do CUDA visíveis e diz se dá para usar a GPU.

    O CTranslate2 carrega `cublas64_12.dll` por LoadLibrary comum, que ignora
    `os.add_dll_directory` — só enxerga o que está no PATH. As DLLs vêm nos
    pacotes `nvidia-cublas-cu12` / `nvidia-cudnn-cu12`, dentro do site-packages,
    então o caminho precisa entrar no PATH ANTES de importar o modelo.

    Vale muito a pena: medido nesta máquina (RTX 4050), o mesmo áudio de 11,4s
    leva 3,0s na CPU e 0,47s na GPU — 3,8x contra 24x o tempo real.
    """
    import glob
    import sysconfig

    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() < 1:
            return False
    except Exception:
        return False

    sp = sysconfig.get_paths()["purelib"]
    dirs = [d for d in glob.glob(os.path.join(sp, "nvidia", "*", "bin")) if os.path.isdir(d)]
    if not dirs:
        return False

    os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ.get("PATH", "")
    return True


_TEM_GPU = _preparar_cuda()

MODELO = os.getenv("WHISPER_MODELO", "small")
# GPU quando houver: float16 na GPU é 6x mais rápido que int8 na CPU, com a
# mesma saída. `WHISPER_DISPOSITIVO=cpu` força o contrário.
DISPOSITIVO = os.getenv("WHISPER_DISPOSITIVO") or ("cuda" if _TEM_GPU else "cpu")
COMPUTE = os.getenv("WHISPER_COMPUTE") or ("float16" if DISPOSITIVO == "cuda" else "int8")

_modelo = None
_trava_modelo = threading.Lock()

# O CTranslate2 não é reentrante: duas transcrições simultâneas na mesma
# instância corrompem a saída. Como o PaddleOCR já disputa CPU nesta máquina,
# serializar aqui também evita que as duas cargas briguem.
_trava_inferencia = threading.Lock()


def carregar_modelo():
    """Carrega uma vez e reusa. ~85s na primeira chamada."""
    global _modelo
    with _trava_modelo:
        if _modelo is None:
            from faster_whisper import WhisperModel

            inicio = time.perf_counter()
            log.info("Carregando Whisper (%s, %s, %s)…", MODELO, DISPOSITIVO, COMPUTE)
            try:
                _modelo = WhisperModel(MODELO, device=DISPOSITIVO, compute_type=COMPUTE)
            except Exception as exc:
                # GPU sem VRAM livre, driver antigo, DLL faltando: a entrevista
                # não pode parar por isso — cai na CPU, só mais devagar.
                if DISPOSITIVO != "cpu":
                    log.warning("GPU indisponível (%s); usando CPU.", str(exc)[:120])
                    _modelo = WhisperModel(MODELO, device="cpu", compute_type="int8")
                else:
                    raise
            log.info("Whisper pronto em %.1fs (%s)", time.perf_counter() - inicio, DISPOSITIVO)
        return _modelo


def modelo_carregado() -> bool:
    return _modelo is not None


@dataclass(frozen=True)
class Trecho:
    """Um segmento do Whisper: onde começa, onde termina e o que foi dito."""

    inicio: float
    fim: float
    texto: str


class Estado(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    FINISHING = "FINISHING"
    COMPLETED = "COMPLETED"


@dataclass
class AnswerSession:
    """Uma resposta. Acumula áudio e devolve texto provisório e final."""

    sessao_id: str
    pergunta_id: str
    estado: Estado = Estado.IDLE
    audio: list[np.ndarray] = field(default_factory=list)
    amostras: int = 0
    #: Transcrição da janela atual — a parte do texto que ainda pode mudar.
    texto_parcial: str = ""
    #: O que já saiu da janela e foi congelado. Ver `transcrever_parcial`.
    prefixo_parcial: str = ""
    texto_final: str = ""
    #: Um parcial rodando por vez, por sessão. Quem controla é o serviço.
    parcial_em_curso: bool = False
    _amostras_ultima_parcial: int = 0
    _inicio_cauda: int = 0
    #: Relógio da primeira amostra, para medir se o áudio chega em tempo real.
    _t0: float = 0.0
    #: Quanto do prefixo já foi ENTREGUE ao cliente como trecho confirmado.
    _prefixo_entregue: int = 0

    def acrescentar(self, pcm: np.ndarray) -> None:
        if self.amostras >= LIMITE_SESSAO_S * TAXA:
            return
        if self._t0 == 0.0:
            self._t0 = time.monotonic()
        self.audio.append(pcm)
        self.amostras += len(pcm)

    def fator_chegada(self) -> float:
        """Quantos segundos de áudio chegam por segundo de relógio.

        1,0 é tempo real. Abaixo disso a transcrição não tem como acompanhar a
        fala — não adianta acelerar o modelo se o áudio não chega. Acima de 1,0
        é gravação sendo despejada de uma vez, não entrevista ao vivo.
        """
        decorrido = time.monotonic() - self._t0
        return (self.amostras / TAXA) / decorrido if decorrido > 0.1 else 0.0

    @property
    def duracao_s(self) -> float:
        return self.amostras / TAXA

    def hora_de_parcial(self) -> bool:
        novas = self.amostras - self._amostras_ultima_parcial
        return novas >= SEGUNDOS_ENTRE_PARCIAIS * TAXA

    def iniciar_parcial(self) -> bool:
        """Reserva a vez do próximo parcial. `False` se não é hora ou já há um.

        A reserva marca o relógio AQUI, e não quando a transcrição termina: o
        modelo pode levar mais que a cadência, e medir na saída faria a próxima
        rodada disparar imediatamente, empilhando trabalho que ninguém vê.
        """
        if self.parcial_em_curso or not self.hora_de_parcial():
            return False
        self.parcial_em_curso = True
        self._amostras_ultima_parcial = self.amostras
        return True

    def texto_em_construcao(self) -> str:
        """O que a tela mostra enquanto a pessoa fala: congelado + janela atual."""
        return " ".join(p for p in (self.prefixo_parcial, self.texto_parcial) if p).strip()

    def trecho_confirmado(self) -> str:
        """O que foi congelado desde a última vez que alguém perguntou.

        É o que sustenta a entrevista de microfone aberto: em vez de esperar o
        fim da resposta para ter texto, o cliente recebe cada trecho assim que
        ele para de mudar, e o manda para a escuta preencher o roteiro.

        Só sai do PREFIXO, nunca da cauda: o prefixo é o que já passou de uma
        pausa e não muda mais. Entregar a cauda faria o roteiro ser preenchido
        com texto que a frase seguinte ainda vai corrigir.
        """
        novo = self.prefixo_parcial[self._prefixo_entregue :].strip()
        self._prefixo_entregue = len(self.prefixo_parcial)
        return novo

    def _juntar(self) -> np.ndarray:
        if not self.audio:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self.audio)

    def transcrever_parcial(self) -> str:
        """Texto provisório da cauda, congelando o que já passou de uma pausa.

        Descarta a rodada se já houver uma transcrição em curso. Enfileirar
        parciais fazia a fila crescer mais rápido que o processamento: os
        parciais chegavam com 11s, 19s, 27s de atraso e o WebSocket morria por
        keepalive. Parcial é aproximação para a tela — perder um não custa
        nada, porque o próximo já traz o texto acumulado.
        """
        cauda = self._juntar()[self._inicio_cauda :]
        if len(cauda) < TAXA * 0.5:  # menos de meio segundo não vale rodar
            return self.texto_em_construcao()

        if not _trava_inferencia.acquire(blocking=False):
            return self.texto_em_construcao()
        inicio = time.perf_counter()
        try:
            trechos = _segmentos_sem_trava(cauda)
        finally:
            _trava_inferencia.release()

        # Uma linha por parcial, com os quatro números que separam as causas de
        # "está demorando": inferência lenta, áudio chegando devagar, microfone
        # mudo, ou cauda que não congela. Sem isto o diagnóstico vira palpite.
        nivel = float(np.sqrt(np.mean(np.square(cauda)))) if len(cauda) else 0.0
        log.info(
            "parcial: cauda=%.1fs inferencia=%dms nivel=%.4f chegada=%.2fx segmentos=%d",
            len(cauda) / TAXA,
            int((time.perf_counter() - inicio) * 1000),
            nivel,
            self.fator_chegada(),
            len(trechos),
        )

        self.texto_parcial = " ".join(t.texto for t in trechos).strip()
        self._congelar(trechos, len(cauda) / TAXA)
        return self.texto_em_construcao()

    def _congelar(self, trechos: list[Trecho], duracao_cauda: float) -> None:
        """Tira da cauda o que já não vai mudar, encurtando a próxima rodada."""
        corte = 0.0
        for t in trechos:
            if t.fim > duracao_cauda - MARGEM_CAUDA_S:
                break
            corte = t.fim

        if corte > 0:
            confirmados = [t.texto for t in trechos if t.fim <= corte]
            self.prefixo_parcial = " ".join(
                p for p in (self.prefixo_parcial, *confirmados) if p
            ).strip()
            self.texto_parcial = " ".join(t.texto for t in trechos if t.fim > corte).strip()
            # O corte cai numa pausa, então não parte palavra: o áudio
            # congelado acaba exatamente onde o segmento acabou.
            self._inicio_cauda += int(corte * TAXA)
            return

        if duracao_cauda > LIMITE_CAUDA_S:
            # Fala longa sem pausa nenhuma (ou VAD que não fechou segmento).
            # Corta assim mesmo, senão o custo do parcial volta a crescer sem
            # limite. Aqui a emenda pode repetir ou comer uma palavra — é o
            # preço de não ter onde cortar, e vale só para o texto na tela.
            self.prefixo_parcial = self.texto_em_construcao()
            self.texto_parcial = ""
            self._inicio_cauda = max(0, self.amostras - int(SOBREPOSICAO_PARCIAL_S * TAXA))

    def transcrever_final(self) -> str:
        """Texto definitivo: o áudio inteiro de uma vez, que é o de melhor contexto."""
        self.estado = Estado.FINISHING
        completo = self._juntar()
        self.texto_final = _transcrever(completo) if len(completo) >= TAXA * 0.3 else ""
        self.estado = Estado.COMPLETED
        return self.texto_final

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.sessao_id,
            "questionId": self.pergunta_id,
            "status": self.estado.value,
            "duracao_s": round(self.duracao_s, 1),
            "texto": self.texto_final or self.texto_em_construcao(),
        }


def _transcrever(audio: np.ndarray) -> str:
    """Transcrição garantida — espera a vez. Usada no texto final."""
    with _trava_inferencia:
        return _transcrever_sem_trava(audio)


def _transcrever_sem_trava(audio: np.ndarray) -> str:
    """O texto corrido. Quem chama garante a exclusão mútua."""
    return " ".join(t.texto for t in _segmentos_sem_trava(audio)).strip()


def _segmentos_sem_trava(audio: np.ndarray) -> list[Trecho]:
    """O trabalho em si, com as fronteiras que o VAD encontrou.

    Os tempos importam tanto quanto o texto: é neles que o parcial descobre
    onde houve pausa, e é na pausa que dá para congelar sem cortar palavra.
    Com `vad_filter`, o faster-whisper já devolve os tempos referentes ao áudio
    original, não ao áudio comprimido — então servem para fatiar o buffer.
    """
    modelo = carregar_modelo()
    segmentos, _ = modelo.transcribe(
        audio,
        language="pt",
        beam_size=1,          # ganho de qualidade não paga o custo em CPU
        vad_filter=True,      # corta silêncio: o entrevistado pensa antes de falar
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,  # evita repetir frase da janela anterior
    )
    return [Trecho(s.start, s.end, s.text.strip()) for s in segmentos if s.text.strip()]


def pcm_de_bytes(dados: bytes) -> np.ndarray:
    """Float32 little-endian vindo do AudioWorklet, já em 16 kHz mono.

    A conversão de taxa acontece no navegador (AudioContext a 16 kHz), que é
    mais barato que reamostrar no servidor e evita dependência de ffmpeg.
    """
    if len(dados) % 4:
        dados = dados[: len(dados) - (len(dados) % 4)]
    return np.frombuffer(dados, dtype=np.float32).copy()


class Sessoes:
    """Registro das respostas em andamento, por conexão WebSocket."""

    def __init__(self) -> None:
        self._itens: dict[str, AnswerSession] = {}
        self._trava = threading.Lock()

    def abrir(self, sessao_id: str, pergunta_id: str) -> AnswerSession:
        with self._trava:
            s = AnswerSession(sessao_id=sessao_id, pergunta_id=pergunta_id)
            s.estado = Estado.LISTENING
            self._itens[sessao_id] = s
            return s

    def obter(self, sessao_id: str) -> AnswerSession | None:
        with self._trava:
            return self._itens.get(sessao_id)

    def fechar(self, sessao_id: str) -> AnswerSession | None:
        with self._trava:
            return self._itens.pop(sessao_id, None)
