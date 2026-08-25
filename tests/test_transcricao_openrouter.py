"""A transcrição pela OpenRouter — o formato do pedido e a defesa da resposta.

A rede é dublada: bater na OpenRouter a cada execução gastaria crédito e faria a
suíte depender de estar online. O que está coberto é o que estraga uma entrevista
se quebrar:

- o WAV saindo com taxa, canais ou largura errados — o modelo transcreveria
  ruído, ou nada, e o erro apareceria como "o Whisper não ouviu";
- o corpo do pedido fora do formato `input_audio` — a OpenRouter recusa;
- o modelo sendo prestativo: "Claro! Aqui está a transcrição:" entrando no
  depoimento, ou "(silêncio)" virando fala do cliente;
- falha de rede subindo como exceção qualquer em vez de `ErroTranscricao`, que é
  a que o parcial sabe descartar sem derrubar a resposta.

Rodar: .venv\\Scripts\\python.exe -m tests.test_transcricao_openrouter
"""

from __future__ import annotations

import base64
import io
import json
import os
import wave

import httpx
import numpy as np

os.environ.setdefault("OPENROUTER_API_KEY", "chave-de-teste")

from app import transcricao_openrouter as motor  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str, detalhe: str = "") -> None:
    global falhas
    if condicao:
        print(f"  PASS  {descricao}")
    else:
        falhas += 1
        print(f"  FALHA {descricao}" + (f"\n          {detalhe}" if detalhe else ""))


class RespostaFalsa:
    def __init__(self, conteudo, status=200):
        self._conteudo = conteudo
        self.status_code = status
        self.text = json.dumps(conteudo) if isinstance(conteudo, dict) else str(conteudo)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erro", request=None, response=self)

    def json(self):
        return self._conteudo


def resposta_com(texto):
    return {"choices": [{"message": {"content": texto}}]}


#: O que o `httpx.post` recebeu na última chamada dublada.
capturado: dict = {}


def dublar(conteudo, status=200):
    def falso_post(url, **kwargs):
        capturado.clear()
        capturado.update({"url": url, **kwargs})
        return RespostaFalsa(conteudo, status)

    motor.httpx.post = falso_post


_post_real = motor.httpx.post


# ------------------------------------------------------------------ o WAV

print("\nO WAV que vai para o modelo")

audio = np.sin(np.linspace(0, 200, motor.TAXA)).astype(np.float32)  # 1s
bruto = motor._wav(audio)

with wave.open(io.BytesIO(bruto), "rb") as w:
    checar(w.getnchannels() == 1, "mono")
    checar(w.getframerate() == motor.TAXA, f"16 kHz (veio {w.getframerate()})")
    checar(w.getsampwidth() == 2, "16 bits por amostra")
    checar(w.getnframes() == motor.TAXA, f"1s de áudio = {motor.TAXA} quadros")

# Pico acima de 1.0 não pode dar a volta e virar estouro (o int16 é cíclico).
estourado = motor._wav(np.array([2.0, -2.0, 0.0], dtype=np.float32))
with wave.open(io.BytesIO(estourado), "rb") as w:
    amostras = np.frombuffer(w.readframes(3), dtype=np.int16)
checar(
    amostras[0] > 0 and amostras[1] < 0,
    "pico acima de 1.0 satura em vez de dar a volta",
    str(amostras),
)


# ------------------------------------------------------- o corpo do pedido

print("\nO corpo do pedido")

dublar(resposta_com("bom dia, meu nome é Ana"))
texto = motor.transcrever(audio)
corpo = capturado["json"]
conteudo = corpo["messages"][-1]["content"]
parte_audio = next(p for p in conteudo if p["type"] == "input_audio")

checar(texto == "bom dia, meu nome é Ana", "devolve o texto do modelo")
checar(capturado["url"] == motor.URL, "bate no /api/v1/chat/completions")
checar(corpo["temperature"] == 0, "temperatura zero: transcrição não é criação")
checar(parte_audio["input_audio"]["format"] == "wav", "declara o formato wav")
checar(
    not parte_audio["input_audio"]["data"].startswith("data:"),
    "base64 puro, sem prefixo data: — a OpenRouter recusa com prefixo",
)
checar(
    base64.b64decode(parte_audio["input_audio"]["data"])[:4] == b"RIFF",
    "o base64 decodifica num WAV de verdade",
)
checar(
    "Authorization" in capturado["headers"]
    and capturado["headers"]["Authorization"].startswith("Bearer "),
    "manda a chave no Authorization",
)


# ------------------------------------------- o modelo tentando ser prestativo

print("\nDefesa contra o modelo prestativo")

for entrada, esperado, o_que in [
    ("Transcrição: bom dia", "bom dia", "tira o prefixo 'Transcrição:'"),
    ("```\nbom dia\n```", "bom dia", "tira o bloco de código"),
    ("(silêncio)", "", "silêncio vira vazio, não vira fala"),
    ("[inaudível]", "", "'[inaudível]' vira vazio"),
    ("O áudio está em silêncio.", "", "a frase do modelo sobre silêncio vira vazio"),
    ("   bom dia   ", "bom dia", "apara o espaço"),
    ("bom dia", "bom dia", "texto normal passa intacto"),
]:
    checar(motor._limpar(entrada) == esperado, o_que, f"{entrada!r} -> {motor._limpar(entrada)!r}")

# `content` como lista de partes, que alguns modelos devolvem.
dublar({"choices": [{"message": {"content": [{"type": "text", "text": "bom dia"}]}}]})
checar(motor.transcrever(audio) == "bom dia", "aceita content em lista de partes")


# ------------------------------------------------------------------ falhas

print("\nFalhas")

dublar({"erro": "sem credito"}, status=402)
try:
    motor.transcrever(audio)
    checar(False, "402 vira ErroTranscricao")
except motor.ErroTranscricao as e:
    checar("402" in str(e), "402 vira ErroTranscricao com o código na mensagem", str(e))
except Exception as e:
    checar(False, "402 vira ErroTranscricao", f"veio {type(e).__name__}")


def post_que_falha(url, **kwargs):
    raise httpx.ConnectError("rede fora")


motor.httpx.post = post_que_falha
try:
    motor.transcrever(audio)
    checar(False, "rede fora vira ErroTranscricao")
except motor.ErroTranscricao:
    checar(True, "rede fora vira ErroTranscricao (o parcial sabe descartar essa)")
except Exception as e:
    checar(False, "rede fora vira ErroTranscricao", f"veio {type(e).__name__}")

dublar({"sem": "choices"})
try:
    motor.transcrever(audio)
    checar(False, "resposta ilegível vira ErroTranscricao")
except motor.ErroTranscricao:
    checar(True, "resposta ilegível vira ErroTranscricao")

# Sem chave a mensagem tem de dizer o que fazer, não só falhar.
guardada = os.environ.pop("OPENROUTER_API_KEY")
try:
    motor.transcrever(audio)
    checar(False, "sem chave, falha")
except motor.ErroTranscricao as e:
    checar(".env" in str(e), "sem chave, a mensagem diz onde consertar", str(e))
finally:
    os.environ["OPENROUTER_API_KEY"] = guardada


# ------------------------------ o áudio longo demais é FATIADO, não truncado

print("\nÁudio acima do limite de uma requisição")

# Nada de truncar: uma sessão que encerre entre LIMITE_SEGUNDOS e MEMORIA_MAXIMA_S
# ainda tem o buffer inteiro em memória, e `transcrever_final` manda tudo de uma
# vez — cortar ali apagaria o começo do depoimento sem nenhum aviso.
enviados = []


def post_que_acumula(url, **kwargs):
    parte = kwargs["json"]["messages"][-1]["content"][1]["input_audio"]["data"]
    with wave.open(io.BytesIO(base64.b64decode(parte)), "rb") as w:
        enviados.append(w.getnframes() / w.getframerate())
    return RespostaFalsa(resposta_com(f"fatia {len(enviados)}"))


motor.httpx.post = post_que_acumula
longo = np.zeros(int((motor.LIMITE_SEGUNDOS + 120) * motor.TAXA), dtype=np.float32)
texto = motor.transcrever(longo)

checar(len(enviados) == 2, f"o áudio vai em fatias ({len(enviados)} requisição(ões))")
checar(
    all(s <= motor.LIMITE_SEGUNDOS + 0.5 for s in enviados),
    f"nenhuma fatia passa do teto ({[round(s) for s in enviados]})",
)
checar(
    abs(sum(enviados) - len(longo) / motor.TAXA) < 1,
    "as fatias somam o áudio INTEIRO — nada de depoimento perdido",
    f"{sum(enviados):.0f}s de {len(longo) / motor.TAXA:.0f}s",
)
checar(texto == "fatia 1 fatia 2", f"os textos são emendados na ordem ({texto!r})")

# O corte procura o ponto mais quieto, para não partir palavra no meio.
fala = np.ones(int(20 * motor.TAXA), dtype=np.float32) * 0.5
silencio_em = int(16 * motor.TAXA)
fala[silencio_em : silencio_em + int(0.4 * motor.TAXA)] = 0.0
corte = motor._corte_silencioso(fala, int(20 * motor.TAXA))
checar(
    silencio_em <= corte <= silencio_em + int(0.5 * motor.TAXA),
    "o corte cai no silêncio, e não no fim nominal",
    f"corte em {corte / motor.TAXA:.1f}s, silêncio em {silencio_em / motor.TAXA:.1f}s",
)

# ------------------------------ o trecho único que o resto do módulo consome

print("\nA ponte com transcricao.py")

os.environ["MOTOR_TRANSCRICAO"] = "openrouter"
from app import transcricao  # noqa: E402

dublar(resposta_com("bom dia"))
trechos = transcricao._segmentos_openrouter(audio)
checar(len(trechos) == 1, "a janela vira UM trecho — a API não dá tempos por segmento")
checar(trechos[0].texto == "bom dia", "com o texto do modelo")
checar(
    abs(trechos[0].fim - 1.0) < 0.01,
    f"e o fim é a duração da janela ({trechos[0].fim:.2f}s)",
)

dublar(resposta_com("(silêncio)"))
checar(
    transcricao._segmentos_openrouter(audio) == [],
    "silêncio não vira trecho — senão '(silêncio)' entraria no depoimento",
)


# ------------------------------------------- parcial desiste, final espera

print("\nParcial e final têm urgências opostas")

esperas = []


def post_que_anota_timeout(url, **kwargs):
    esperas.append(kwargs["timeout"])
    return RespostaFalsa(resposta_com("ok"))


motor.httpx.post = post_que_anota_timeout

motor.transcrever(audio, motor.TEMPO_LIMITE_PARCIAL_S)
checar(
    esperas[-1] == motor.TEMPO_LIMITE_PARCIAL_S,
    f"o parcial desiste em {motor.TEMPO_LIMITE_PARCIAL_S:.0f}s",
)
motor.transcrever(audio)
checar(esperas[-1] == motor.TEMPO_LIMITE_S, f"o final espera {motor.TEMPO_LIMITE_S:.0f}s")
checar(
    motor.TEMPO_LIMITE_PARCIAL_S < motor.TEMPO_LIMITE_S,
    "e o do parcial é MENOR — foi o contrário disso que travou a tela por 106s",
)

# O caminho real: `transcrever_parcial` tem de passar o teto curto adiante. Sem
# isso a separação existiria no papel e não no fluxo que importa.
import numpy as _np  # noqa: E402

esperas.clear()
sessao = transcricao.AnswerSession(sessao_id="t", pergunta_id="p")
sessao.estado = transcricao.Estado.LISTENING
sessao.acrescentar(_np.zeros(3 * motor.TAXA, dtype=_np.float32))
sessao.transcrever_parcial()
checar(
    esperas and esperas[-1] == motor.TEMPO_LIMITE_PARCIAL_S,
    "transcrever_parcial usa o teto curto de ponta a ponta",
    str(esperas),
)


motor.httpx.post = _post_real
print(f"\n{'TUDO OK' if not falhas else f'{falhas} FALHA(S)'}")
raise SystemExit(1 if falhas else 0)
