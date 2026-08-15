"""Guarda o áudio da entrevista e o entrega em .mp4.

POR QUE QUEM GRAVA É O SERVIDOR, E NÃO O NAVEGADOR

O PCM da entrevista já passa por aqui: é ele que alimenta o Whisper. Gravar do
mesmo fluxo garante a única propriedade que importa num arquivo que pode virar
prova — **o áudio é exatamente o que foi transcrito**, nem um trecho a mais nem
a menos. Um `MediaRecorder` no navegador seria uma segunda captura, com o seu
próprio começo e o seu próprio fim, e as duas divergiriam no dia em que uma
delas falhasse. Além disso, o que o navegador acumula morre com a aba; o que
chega aqui está no disco desde o primeiro segundo.

O ARQUIVO É MAIS CURTO QUE A ENTREVISTA, E ISSO É DE PROPÓSITO

Só entra o que foi ENVIADO. Durante a pausa o navegador para de mandar bytes —
é para isso que a pausa existe, para o advogado falar sem entrar na transcrição
— e entre uma pergunta e a seguinte também não vai nada. O arquivo, portanto,
tem o tempo de FALA, não o de relógio.

Emendar isso em silêncio seria editar o áudio sem dizer. Por isso cada retomada
vira um trecho no manifesto (`<id>.json`), com o instante do relógio em que ela
aconteceu: quem ouvir depois consegue reconstruir onde houve corte e de quanto
tempo ele foi.

POR QUE WAV PRIMEIRO E MP4 SÓ NO FIM

O MP4 guarda o índice (`moov`) no fecho do arquivo: um processo que morra no
meio da entrevista deixaria um arquivo que nenhum player abre. O WAV cru não
tem esse problema — o cabeçalho é reescrito no fim, e quando ele fica para trás
`_reparar_cabecalho` o refaz a partir do tamanho do arquivo. A entrevista
sobrevive à queda; o que se perde é o trabalho de conversão, que se refaz.

POR QUE 48 kbps, E POR QUE NÃO 64

Medido nesta máquina, convertendo 5 minutos de áudio 16 kHz mono:

    32 kbps -> 1,23 MB   2,91s   103x o tempo real
    48 kbps -> 1,82 MB   3,12s    96x o tempo real
    64 kbps -> 1,87 MB  14,96s    20x o tempo real

O encoder AAC nativo satura perto dos 48 kbps nessa taxa de amostragem: pedir
64 custa cinco vezes o tempo para entregar 3% mais bytes. A 48 kbps uma
entrevista de 40 minutos vira ~17 MB e converte em ~25s.

Nada disso instala dependência nova: o PyAV já vem com o faster-whisper, e traz
o FFmpeg embutido — não há `ffmpeg` no PATH desta máquina e continua não sendo
preciso haver.
"""

from __future__ import annotations

import json
import logging
import os
import re
import struct
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import IO, Any

import numpy as np

log = logging.getLogger("gravacao")

BASE = Path(__file__).resolve().parent.parent
PASTA = Path(os.getenv("PASTA_GRAVACOES") or BASE / "dados" / "entrevistas")

TAXA = 16_000                 # o mesmo do worklet e do Whisper
BITRATE = 48_000              # ver o cabeçalho: acima disto o encoder satura
CABECALHO_WAV = 44            # RIFF canônico, sem nenhum chunk extra

#: Teto de segurança para microfone esquecido aberto. Seis horas de WAV são
#: ~345 MB; o que passar disso não é entrevista, é descuido.
LIMITE_HORAS = 6

#: Silêncio de relógio a partir do qual o que vem depois é outro trecho. Abaixo
#: disso é a cadência normal do worklet (256 ms por bloco) com alguma folga de
#: rede; acima, houve pausa, troca de pergunta ou conexão caída.
INTERVALO_TRECHO_S = 2.0


class ErroGravacao(Exception):
    """Falha que impede entregar o áudio — a entrevista em si não para por isso."""


def identificador_valido(identificador: str) -> bool:
    """O id vem do navegador e vira NOME DE ARQUIVO. Nada além de uuid passa.

    Sem esta trava, um id com `..` escreveria e leria fora de `dados/entrevistas`.
    """
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{8,64}", identificador))


def _cabecalho_wav(bytes_de_dados: int) -> bytes:
    """RIFF de 44 bytes, PCM 16 bits mono. Reescrito no fecho com o tamanho real."""
    return b"".join(
        (
            b"RIFF",
            struct.pack("<I", 36 + bytes_de_dados),
            b"WAVEfmt ",
            struct.pack("<IHHIIHH", 16, 1, 1, TAXA, TAXA * 2, 2, 16),
            b"data",
            struct.pack("<I", bytes_de_dados),
        )
    )


def _reparar_cabecalho(caminho: Path) -> None:
    """Refaz os tamanhos do RIFF a partir do arquivo — para o que ficou aberto.

    O cabeçalho só ganha os tamanhos certos quando a gravação fecha. Se o
    processo morreu antes, eles ficaram em zero e o arquivo abre como se
    estivesse vazio, mesmo com o áudio todo lá dentro.
    """
    dados = caminho.stat().st_size - CABECALHO_WAV
    if dados <= 0:
        raise ErroGravacao("Gravação sem áudio.")
    with open(caminho, "r+b") as arquivo:
        arquivo.seek(0)
        arquivo.write(_cabecalho_wav(dados))


def converter_para_mp4(origem: Path, destino: Path) -> None:
    """WAV -> MP4/AAC, com o índice no começo para tocar sem baixar tudo.

    Escreve num arquivo parcial e só então renomeia: uma conversão interrompida
    não pode deixar para trás um .mp4 truncado que a tela ofereceria para baixar
    como se estivesse pronto.
    """
    # Import tardio de propósito. O PyAV carrega as suas próprias DLLs de FFmpeg,
    # e este processo já convive com a ordem delicada entre CTranslate2 e Paddle
    # descrita em `transcricao.py`. Quem não converte não carrega nada disto.
    import av

    parcial = destino.with_suffix(".mp4.parcial")
    try:
        with (
            av.open(str(origem)) as entrada,
            av.open(
                str(parcial),
                "w",
                format="mp4",
                # `faststart` põe o índice no início: é o que deixa o áudio tocar
                # na própria tela sem esperar o download inteiro.
                options={"movflags": "+faststart"},
            ) as saida,
        ):
            fluxo = saida.add_stream("aac", rate=TAXA, layout="mono")
            fluxo.bit_rate = BITRATE
            # O AAC quer float planar; o WAV entrega inteiro empacotado.
            remontador = av.AudioResampler(format="fltp", layout="mono", rate=TAXA)

            for quadro in entrada.decode(audio=0):
                for pronto in remontador.resample(quadro):
                    saida.mux(fluxo.encode(pronto))
            # O remontador segura um resto; sem drenar, o fim da fala some.
            for pronto in remontador.resample(None):
                saida.mux(fluxo.encode(pronto))
            saida.mux(fluxo.encode(None))
    except Exception as exc:
        parcial.unlink(missing_ok=True)
        raise ErroGravacao(f"Não foi possível converter o áudio: {exc}") from exc

    os.replace(parcial, destino)


class Gravacao:
    """O áudio de UMA entrevista, do "podemos começar?" ao encerramento.

    Uma entrevista, um arquivo — mesmo que ela passe por várias sessões de
    transcrição (a escuta contínua, as respostas gravadas uma a uma, os
    complementos). Quem as costura é o `entrevistaId`, que o navegador gera uma
    vez e repete em todo `start`.
    """

    def __init__(self, identificador: str) -> None:
        if not identificador_valido(identificador):
            raise ErroGravacao("Identificador de entrevista inválido.")
        PASTA.mkdir(parents=True, exist_ok=True)

        self.identificador = identificador
        self.wav = PASTA / f"{identificador}.wav"
        self.mp4 = PASTA / f"{identificador}.mp4"
        self.manifesto = PASTA / f"{identificador}.json"

        # Entrevista já convertida não volta a receber áudio. Gravar por cima
        # dela apagaria a conversa inteira na conversão seguinte, e apagar
        # entrevista é o único estrago aqui que não se refaz. Quem voltar a
        # gravar tem que trazer um id novo — é o que o cliente faz.
        if self.mp4.exists():
            raise ErroGravacao(f"A entrevista {identificador} já foi encerrada.")

        self.inicio = time.time()
        self.amostras = 0
        self.trechos: list[dict[str, float]] = []
        self._arquivo: IO[bytes] | None = None
        self._ultima_escrita = 0.0
        self._trava = threading.Lock()

        # Retomada: o serviço reiniciou, ou a conexão caiu e voltou, no meio da
        # mesma entrevista. O arquivo continua de onde parou em vez de ser
        # sobrescrito — perder a primeira metade seria pior que qualquer emenda.
        if self.wav.exists():
            self.amostras = max(0, (self.wav.stat().st_size - CABECALHO_WAV) // 2)

    # ----------------------------------------------------------- escrita

    def _abrir(self) -> IO[bytes]:
        # `r+b` e não `ab`: em modo de acréscimo toda escrita vai para o fim do
        # arquivo, `seek` ou não `seek`, e o `fechar_arquivo` precisa voltar ao
        # byte zero para acertar o cabeçalho.
        if self._arquivo is None:
            novo = not self.wav.exists()
            self._arquivo = open(self.wav, "r+b" if not novo else "wb")
            if novo:
                self._arquivo.write(_cabecalho_wav(0))
            else:
                self._arquivo.seek(0, os.SEEK_END)
        return self._arquivo

    def acrescentar(self, pcm: np.ndarray) -> None:
        """Guarda mais um bloco do que está sendo transcrito."""
        if self.amostras >= LIMITE_HORAS * 3600 * TAXA:
            return
        agora = time.monotonic()
        with self._trava:
            arquivo = self._abrir()
            # Corte antes da conversão: o Float32 do worklet passa de 1,0 nos
            # picos, e o estouro do int16 daria estalo no lugar de volume alto.
            arquivo.write((np.clip(pcm, -1.0, 1.0) * 32767.0).astype("<i2").tobytes())

            # O trecho é o que separa "gravação contínua" de "retomada depois de
            # uma pausa" — ver o cabeçalho sobre por que isso fica registrado.
            if not self.trechos or agora - self._ultima_escrita > INTERVALO_TRECHO_S:
                self.trechos.append(
                    {
                        "inicio_s": round(self.amostras / TAXA, 2),
                        "relogio": round(time.time(), 3),
                        "duracao_s": 0.0,
                    }
                )
            self.amostras += len(pcm)
            self.trechos[-1]["duracao_s"] = round(
                self.amostras / TAXA - self.trechos[-1]["inicio_s"], 2
            )
            self._ultima_escrita = agora

    def fechar_arquivo(self) -> None:
        """Solta o arquivo e acerta o cabeçalho, sem encerrar a gravação.

        É o que roda quando a conexão cai: a entrevista pode continuar depois de
        um F5, e o `_abrir` reabre em modo de acréscimo. O cabeçalho fica certo
        no intervalo, então mesmo o WAV parado no disco é um arquivo tocável.
        """
        with self._trava:
            if self._arquivo is None:
                return
            self._arquivo.flush()
            self._arquivo.seek(0)
            self._arquivo.write(_cabecalho_wav(self.amostras * 2))
            self._arquivo.close()
            self._arquivo = None

    # ------------------------------------------------------------ fecho

    @property
    def duracao_s(self) -> float:
        return self.amostras / TAXA

    def encerrar(self) -> dict[str, Any]:
        """Fecha, converte e devolve o que a tela precisa mostrar.

        Demora: ~25s numa entrevista de 40 minutos (ver o cabeçalho). Quem chama
        deve rodar isto fora do laço de eventos.
        """
        self.fechar_arquivo()
        if self.amostras <= 0 or not self.wav.exists():
            raise ErroGravacao("A entrevista não gravou áudio nenhum.")

        # O `fechar_arquivo` acerta o cabeçalho do que ESTA execução escreveu.
        # Numa retomada em que ninguém falou depois do F5, não há arquivo aberto
        # para fechar e o cabeçalho continua o zerado da queda — refazer a partir
        # do tamanho vale para os dois casos e não custa nada.
        _reparar_cabecalho(self.wav)
        converter_para_mp4(self.wav, self.mp4)
        self._gravar_manifesto()
        # O WAV era o seguro contra queda no meio; com o MP4 pronto, ele é só
        # sete vezes o mesmo áudio ocupando disco.
        self.wav.unlink(missing_ok=True)
        return self.metadados()

    def _gravar_manifesto(self) -> None:
        self.manifesto.write_text(
            json.dumps(
                {
                    "entrevista_id": self.identificador,
                    "inicio": datetime.fromtimestamp(self.inicio).isoformat(timespec="seconds"),
                    "fim": datetime.now().isoformat(timespec="seconds"),
                    "duracao_audio_s": round(self.duracao_s, 1),
                    "duracao_relogio_s": round(time.time() - self.inicio, 1),
                    "taxa": TAXA,
                    "bitrate": BITRATE,
                    "trechos": self.trechos,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def metadados(self) -> dict[str, Any]:
        return metadados(self.identificador, duracao_s=self.duracao_s)


# ------------------------------------------------------------------ acervo


def caminho_mp4(identificador: str) -> Path:
    if not identificador_valido(identificador):
        raise ErroGravacao("Identificador de entrevista inválido.")
    return PASTA / f"{identificador}.mp4"


def nome_para_baixar(identificador: str) -> str:
    """`Entrevista 14-08-2026 15h32.mp4` — a data vem do manifesto, não do id."""
    quando = datetime.now()
    manifesto = PASTA / f"{identificador}.json"
    if manifesto.exists():
        try:
            quando = datetime.fromisoformat(
                json.loads(manifesto.read_text(encoding="utf-8"))["inicio"]
            )
        except Exception:  # manifesto ilegível não pode impedir o download
            pass
    return f"Entrevista {quando:%d-%m-%Y %Hh%M}.mp4"


def metadados(identificador: str, duracao_s: float | None = None) -> dict[str, Any]:
    """O que a tela mostra: existe, quanto dura, quanto pesa, já está pronto."""
    mp4 = caminho_mp4(identificador)
    wav = PASTA / f"{identificador}.wav"
    manifesto = PASTA / f"{identificador}.json"

    if duracao_s is None:
        if manifesto.exists():
            try:
                duracao_s = float(
                    json.loads(manifesto.read_text(encoding="utf-8"))["duracao_audio_s"]
                )
            except Exception:
                duracao_s = 0.0
        elif wav.exists():
            duracao_s = max(0, wav.stat().st_size - CABECALHO_WAV) / 2 / TAXA
        else:
            duracao_s = 0.0

    return {
        "entrevista_id": identificador,
        # `pronto` é o MP4 no disco. `existe` inclui o áudio que ainda está em
        # WAV — a tela precisa saber que o áudio NÃO se perdeu, mesmo antes de
        # a conversão rodar.
        "pronto": mp4.exists(),
        "existe": mp4.exists() or wav.exists(),
        "duracao_s": round(duracao_s, 1),
        "bytes": mp4.stat().st_size if mp4.exists() else 0,
        "nome": nome_para_baixar(identificador),
    }


class Gravacoes:
    """As entrevistas gravando agora, por `entrevistaId`."""

    def __init__(self) -> None:
        self._itens: dict[str, Gravacao] = {}
        self._trava = threading.Lock()
        #: Trava só das conversões, separada da do registro. A conversão leva
        #: dezenas de segundos, e segurar `_trava` durante ela travaria o
        #: `abrir` de uma entrevista que está começando.
        self._trava_conversao = threading.Lock()

    def abrir(self, identificador: str) -> Gravacao:
        with self._trava:
            atual = self._itens.get(identificador)
            if atual is None:
                atual = Gravacao(identificador)
                self._itens[identificador] = atual
                log.info("Gravando a entrevista %s em %s", identificador, atual.wav.name)
            return atual

    def obter(self, identificador: str) -> Gravacao | None:
        with self._trava:
            return self._itens.get(identificador)

    def encerrar(self, identificador: str) -> dict[str, Any]:
        """Fecha e converte. Serve também para o que ficou de uma queda anterior.

        O MP4 já pronto é devolvido como está: chamar duas vezes (dois cliques,
        um F5 no meio) não reconverte nem perde o arquivo.
        """
        mp4 = caminho_mp4(identificador)  # valida o id antes de qualquer espera

        # A trava é o que faz a segunda chamada ESPERAR a primeira em vez de
        # tentar converter o mesmo WAV em paralelo — e, quando ela entra, o
        # arquivo já está pronto e ela só o encontra.
        with self._trava_conversao:
            with self._trava:
                atual = self._itens.pop(identificador, None)

            if atual is not None:
                return atual.encerrar()

            if mp4.exists():
                return metadados(identificador)

            # Entrevista que o serviço não tem em memória mas cujo WAV está no
            # disco: o processo caiu, ou reiniciou, com a gravação aberta. É
            # justamente o caso em que perder o áudio seria imperdoável.
            wav = PASTA / f"{identificador}.wav"
            if not wav.exists():
                raise ErroGravacao("Não há gravação para esta entrevista.")
            _reparar_cabecalho(wav)
            converter_para_mp4(wav, mp4)
            wav.unlink(missing_ok=True)
            return metadados(identificador)
