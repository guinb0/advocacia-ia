"""Transcrição pela OpenRouter, no lugar do Whisper local.

O QUE MUDA EM RELAÇÃO AO WHISPER, E O QUE ISSO CUSTA

A OpenRouter **não tem endpoint de transcrição**. Não existe equivalente ao
`/v1/audio/transcriptions`: áudio entra pelo `/api/v1/chat/completions`, em
base64, como ARQUIVO COMPLETO. Não há entrada de áudio em streaming.

Isso tem três consequências que o resto do código precisa respeitar:

1. **Não há tempos de segmento.** O Whisper devolvia `(inicio, fim, texto)` por
   trecho, e era neles que o parcial descobria onde houve pausa para congelar sem
   cortar palavra. Aqui volta texto e mais nada, então `transcricao.py` sintetiza
   um trecho único cobrindo a janela e cai no corte forçado por tempo, que já
   existia para o caso de fala longa sem pausa.

2. **Cada transcrição é uma ida à rede, e é paga.** O parcial rodava duas vezes
   por segundo porque era CPU local e de graça. Nessa cadência aqui seriam ~120
   requisições por minuto POR ENTREVISTA. A cadência do parcial passa a ser outra
   quando este motor está ligado — ver `SEGUNDOS_ENTRE_PARCIAIS` em
   `transcricao.py`.

3. **O áudio sai da máquina.** Antes não saía: o Whisper roda local. A conversa é
   a mesma que a saudação do roteiro promete ser "totalmente sigilosa", e a
   OpenRouter é um roteador — ela escolhe para qual provedor mandar. Decisão do
   escritório, registrada aqui para quem for ler depois.

POR QUE O PROMPT É TÃO INSISTENTE

Um modelo de chat não é um transcritor: se você só mandar o áudio, ele resume,
comenta, corrige a gramática do falante ou responde ao que ouviu. Numa entrevista
que vira peça processual, "corrigir" o português do cliente é adulterar depoimento
— as palavras dele são a prova. Daí as regras explícitas de literalidade, e o
pedido de devolver vazio no silêncio em vez de inventar fala.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import wave

import httpx
import numpy as np

from . import ambiente

# Antes das constantes abaixo, que são lidas do ambiente na importação. O processo
# da 8200 pode subir sem o `iniciar.ps1` — ver o cabeçalho de `app/ambiente.py`.
ambiente.carregar()

log = logging.getLogger("transcricao-openrouter")

URL = "https://openrouter.ai/api/v1/chat/completions"

#: Modelo com entrada de áudio. Trocável sem mexer no código — a lista de quem
#: aceita áudio está em https://openrouter.ai/models (filtro de modalidade).
MODELO = os.getenv("OPENROUTER_MODELO_AUDIO", "").strip() or "google/gemini-3.7-flash"

#: Teto do texto FINAL, que não pode se perder: vale esperar.
TEMPO_LIMITE_S = ambiente.numero("OPENROUTER_TIMEOUT_S", 90.0)

#: Teto do PARCIAL, que é descartável — e por isso muito menor.
#:
#: Os dois eram o mesmo número, e isso travava a tela. Um parcial responde em ~6s;
#: quando um pedido pendurou por 106s (a OpenRouter derrubou a conexão sem
#: responder), `parcial_em_curso` segurou todos os seguintes por esse tempo todo e
#: a entrevista ficou em "ouvindo — nada reconhecido ainda" por quase dois
#: minutos, com o cliente falando. Desistir rápido não perde nada: o próximo
#: parcial já vem com o áudio acumulado, e o texto definitivo é transcrito à parte.
TEMPO_LIMITE_PARCIAL_S = ambiente.numero("OPENROUTER_TIMEOUT_PARCIAL_S", 20.0)

#: Teto do que vai numa requisição. Áudio longo em base64 estoura o corpo do POST
#: e o contexto do modelo; acima disto `transcrever` FATIA e emenda os textos.
#: 8 minutos a 16 kHz mono dão ~15 MB de WAV, ~20 MB em base64.
LIMITE_SEGUNDOS = ambiente.numero("OPENROUTER_LIMITE_AUDIO_S", 480.0)

#: Quanto se procura, para trás do corte, um ponto silencioso onde fatiar.
#: Cortar no meio de uma palavra a perde nas duas fatias — o modelo não reconhece
#: nem a metade que ficou antes nem a que ficou depois.
BUSCA_SILENCIO_S = 6.0

TAXA = 16_000

#: O DETECTOR DE FALA QUE ESTE MOTOR NÃO TINHA — e a causa da fala inventada.
#:
#: O Whisper local roda com `vad_filter=True`: silêncio é cortado antes de chegar
#: ao decodificador, e trecho sem voz simplesmente não produz texto. Aqui não há
#: nada disso. O buffer ia inteiro para a OpenRouter, e um modelo de chat, posto
#: diante de um WAV de sala vazia, não devolve string vazia: ele PREENCHE. Foi de
#: onde saíram, numa entrevista real, frases que ninguém disse — "Ô mãe, compra
#: isso pra mim?", "A senhora pode ficar em pé, por favor?" — espalhadas de minuto
#: em minuto, que é a cadência das janelas caladas.
#:
#: A instrução do prompt já mandava devolver vazio no silêncio (ver `INSTRUCAO`).
#: Não basta: pedir a um modelo generativo que não gere é conselho, não trava. A
#: trava é não mandar o áudio.
#:
#: De quebra, é dinheiro: cada janela silenciosa era uma requisição paga.
#:
#: Os dois números são conservadores de propósito. Fala baixa que passe do limiar
#: continua sendo transcrita; o que se quer barrar é sala vazia e ruído de fundo,
#: não sussurro. Ajustáveis pelo ambiente porque o piso de ruído muda com o
#: microfone e com a sala, e quem descobre isso é quem atende, não quem escreve.
LIMIAR_RMS = ambiente.numero("OPENROUTER_LIMIAR_RMS", 0.012)
#: Quanto o bloco precisa superar o piso de ruído MEDIDO no próprio trecho. Sala
#: barulhenta tem piso alto e passaria no limiar absoluto sozinha.
FATOR_ACIMA_DO_PISO = ambiente.numero("OPENROUTER_FATOR_RUIDO", 2.5)
#: Quanta fala precisa haver para valer a ida à rede. Menos que isto é estalo,
#: tosse, porta batendo — coisas que o modelo transforma em frase.
MINIMO_FALA_MS = ambiente.numero("OPENROUTER_MINIMO_FALA_MS", 300.0)
#: Granularidade da medida. 50ms é menor que a menor sílaba e maior que um clique.
BLOCO_MS = 50.0

INSTRUCAO = (
    "Você é um transcritor literal de áudio em português do Brasil. "
    "Devolva SOMENTE a transcrição do que foi falado, como foi falado.\n"
    "\n"
    "Regras:\n"
    "- Transcreva PALAVRA POR PALAVRA. Não resuma, não reescreva, não corrija a "
    "gramática, a concordância ou a pronúncia de quem fala. Este áudio é de uma "
    "entrevista jurídica e as palavras do entrevistado são prova — trocá-las por "
    "palavras melhores adultera o depoimento.\n"
    "- Não comente, não explique, não responda ao que foi dito, não faça perguntas. "
    "Sua saída inteira é a transcrição.\n"
    "- Não escreva prefixos como 'Transcrição:' nem blocos de código.\n"
    "- Não invente nomes de quem fala nem marque quem é quem.\n"
    "- Se o áudio estiver em silêncio, inaudível ou sem fala nenhuma, devolva uma "
    "string VAZIA. Nunca preencha silêncio com fala imaginada.\n"
    "- Use pontuação normal. Números podem ir por extenso ou em algarismos, como "
    "soarem mais naturais."
)

PEDIDO = "Transcreva este áudio seguindo as regras."


class ErroTranscricao(RuntimeError):
    pass


def tem_fala(audio: np.ndarray) -> bool:
    """Há voz neste trecho, ou é só silêncio e ruído de sala?

    Mede a energia em blocos de 50ms e conta quantos passam do limiar. O limiar
    é o absoluto (`LIMIAR_RMS`), levantado até o ruído do próprio trecho quando —
    e SÓ quando — o trecho tem parte calada para medir.

    ESSA RESSALVA É O PONTO DELICADO. O piso relativo (décimo percentil) só
    significa "o que a sala faz quando ninguém fala" se houver, no trecho, um
    momento em que ninguém falou. Num trecho UNIFORME o décimo percentil é a
    própria fala, e o limiar relativo passa a ser 2,5x ela: nada o alcança, e
    uma resposta longa dita sem pausa nenhuma seria descartada inteira. Perder
    depoimento é pior que transcrever ruído — então, sem faixa dinâmica, vale o
    absoluto sozinho.

    Verdadeiro quando os blocos acima do limiar somam `MINIMO_FALA_MS`. Eles não
    precisam ser seguidos: fala real tem micropausa dentro da palavra, e exigir
    continuidade recusaria o começo hesitante de uma resposta.
    """
    passo = int(TAXA * BLOCO_MS / 1000)
    blocos = len(audio) // passo
    if blocos < 2:
        return False
    quadro = np.asarray(audio[: blocos * passo], dtype=np.float32).reshape(blocos, passo)
    energia = np.sqrt(np.mean(np.square(quadro), axis=1))
    piso = float(np.percentile(energia, 10))
    alto = float(np.percentile(energia, 90))
    # Faixa dinâmica: há trecho calado e trecho falado no mesmo pedaço.
    limiar = max(LIMIAR_RMS, piso * FATOR_ACIMA_DO_PISO) if alto > piso * 2 else LIMIAR_RMS
    return float(np.count_nonzero(energia > limiar)) * BLOCO_MS >= MINIMO_FALA_MS


def configurada() -> bool:
    return bool(os.getenv("OPENROUTER_API_KEY", "").strip())


def _wav(audio: np.ndarray) -> bytes:
    """Empacota o float32 de -1..1 num WAV PCM 16 bits, 16 kHz mono.

    O worklet do navegador já entrega em 16 kHz mono (ver `pcm_de_bytes`), então
    aqui não há reamostragem — só a conversão de faixa e o cabeçalho. `clip` antes
    do `int16` evita que um pico acima de 1.0 dê a volta e vire estouro.
    """
    amostras = np.clip(audio, -1.0, 1.0)
    pcm16 = (amostras * 32767.0).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAXA)
        w.writeframes(pcm16.tobytes())
    return buffer.getvalue()


def _limpar(texto: str) -> str:
    """Tira o que o modelo às vezes acrescenta apesar das regras.

    Nenhuma destas defesas substitui o prompt — elas existem porque um modelo de
    chat erra para o lado de ser prestativo, e "Claro! Aqui está:" entrando na
    transcrição de uma entrevista é o tipo de sujeira que ninguém revisa depois.
    """
    limpo = texto.strip()
    if limpo.startswith("```"):
        linhas = [l for l in limpo.splitlines() if not l.strip().startswith("```")]
        limpo = "\n".join(linhas).strip()
    for prefixo in ("transcrição:", "transcricao:", "texto:", "áudio:", "audio:"):
        if limpo[: len(prefixo)].casefold() == prefixo:
            limpo = limpo[len(prefixo) :].strip()
    # O modelo pode dizer que não ouviu nada em vez de devolver vazio. Isso NÃO é
    # transcrição, e deixar passar colocaria a frase dele dentro do depoimento.
    baixo = limpo.casefold().strip(" .!")
    if baixo in {
        "",
        "(silêncio)",
        "(silencio)",
        "[silêncio]",
        "[inaudível]",
        "[inaudivel]",
        "sem fala",
        "não há fala audível",
        "nao ha fala audivel",
        "o áudio está em silêncio",
        "o audio esta em silencio",
    }:
        return ""
    return limpo


def _corte_silencioso(audio: np.ndarray, nominal: int) -> int:
    """Onde fatiar perto de `nominal`: no trecho mais quieto logo antes dele.

    Procura para TRÁS, nunca para frente, para a fatia não passar do teto. Se o
    áudio for uniforme (fala contínua, ou ruído sem pausa), o mínimo cai em algum
    lugar da janela e o corte acontece ali mesmo — pior que uma pausa de verdade,
    melhor que cortar sempre no mesmo milissegundo arbitrário.
    """
    janela = int(BUSCA_SILENCIO_S * TAXA)
    inicio = max(0, nominal - janela)
    if nominal - inicio < TAXA:
        return nominal
    trecho = np.abs(audio[inicio:nominal])
    passo = int(0.1 * TAXA)
    blocos = len(trecho) // passo
    if blocos < 2:
        return nominal
    energia = np.abs(trecho[: blocos * passo]).reshape(blocos, passo).mean(axis=1)
    return inicio + int(np.argmin(energia)) * passo


def _fatias(audio: np.ndarray) -> list[np.ndarray]:
    """O áudio em pedaços que cabem numa requisição, cortados no silêncio.

    Fatiar e emendar, em vez de truncar. A versão anterior cortava o começo do
    áudio quando ele passava do teto, e isso era perda SILENCIOSA de depoimento:
    uma sessão que encerrasse entre `LIMITE_SEGUNDOS` e `MEMORIA_MAXIMA_S` (8 e 10
    minutos, com os padrões de hoje) ainda tem o buffer inteiro em memória, e
    `transcrever_final` manda tudo de uma vez — o primeiro minuto da conversa
    sumiria do texto definitivo sem nenhum aviso.
    """
    teto = int(LIMITE_SEGUNDOS * TAXA)
    if len(audio) <= teto:
        return [audio]
    pedacos: list[np.ndarray] = []
    inicio = 0
    while inicio < len(audio):
        if len(audio) - inicio <= teto:
            pedacos.append(audio[inicio:])
            break
        fim = _corte_silencioso(audio, inicio + teto)
        if fim <= inicio:  # nunca deixa de avançar
            fim = inicio + teto
        pedacos.append(audio[inicio:fim])
        inicio = fim
    return pedacos


def transcrever(audio: np.ndarray, tempo_limite: float | None = None) -> str:
    """O texto do áudio. String vazia quando não há fala.

    Levanta `ErroTranscricao` só em falha de verdade (sem chave, rede fora,
    resposta ilegível). Quem chama decide se aquilo era um parcial descartável ou
    o texto final, que não pode se perder.

    Áudio acima do teto de uma requisição vai em fatias, e os textos são emendados
    na ordem — ver `_fatias` para por que não é truncado.
    """
    chave = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not chave:
        raise ErroTranscricao(
            "Transcrição desligada: falta OPENROUTER_API_KEY no .env."
        )

    # A trava contra fala inventada: trecho sem voz não vai para o modelo.
    # Antes da fatia, porque é o caso comum — a janela caladinha inteira.
    if not tem_fala(audio):
        log.debug("Sem fala em %.1fs de áudio: nada enviado.", len(audio) / TAXA)
        return ""

    pedacos = [p for p in _fatias(audio) if tem_fala(p)]
    if not pedacos:
        return ""
    if len(pedacos) > 1:
        log.info(
            "Áudio de %.0fs vai em %d fatias de até %.0fs.",
            len(audio) / TAXA,
            len(pedacos),
            LIMITE_SEGUNDOS,
        )
    espera = TEMPO_LIMITE_S if tempo_limite is None else tempo_limite
    textos = [_uma_requisicao(p, chave, espera) for p in pedacos]
    return " ".join(t for t in textos if t).strip()


def _uma_requisicao(audio: np.ndarray, chave: str, tempo_limite: float) -> str:
    """Uma ida à OpenRouter com um pedaço de áudio que cabe no corpo do POST."""
    dados = base64.b64encode(_wav(audio)).decode("ascii")
    try:
        resposta = httpx.post(
            URL,
            headers={
                "Authorization": f"Bearer {chave}",
                "Content-Type": "application/json",
                # A OpenRouter usa estes dois para atribuição no painel dela.
                "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "http://localhost:3000"),
                "X-Title": "Acervo - transcricao de entrevista",
            },
            json={
                "model": MODELO,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": INSTRUCAO},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": PEDIDO},
                            {
                                "type": "input_audio",
                                "input_audio": {"data": dados, "format": "wav"},
                            },
                        ],
                    },
                ],
            },
            timeout=tempo_limite,
        )
        resposta.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # 200 CARACTERES ERA POUCO, e o corte custou um diagnostico errado.
        #
        # A OpenRouter responde erro com `metadata`, e e ali que ela diz o que
        # fazer: `limit_source` (qual limite bateu) e `remedy_hint` (como
        # resolver). Com 200 caracteres a mensagem chegava cortada no meio do
        # `remedy_hint` -- deu para ver que era 402, nao para ver QUAL limite. O
        # palpite errado veio dai, e este e o unico canal de diagnostico que
        # existe: o log do conteiner ninguem alcanca de dentro do atendimento.
        detalhe = exc.response.text[:800] if exc.response is not None else ""
        log.warning("OpenRouter recusou (%s): %s", exc.response.status_code, detalhe)
        raise ErroTranscricao(
            f"A OpenRouter respondeu {exc.response.status_code}. {detalhe}"
        ) from exc
    except httpx.HTTPError as exc:
        log.warning("OpenRouter fora do ar: %s", str(exc)[:160])
        raise ErroTranscricao("A OpenRouter não respondeu a tempo.") from exc

    try:
        corpo = resposta.json()
        conteudo = corpo["choices"][0]["message"]["content"]
    except Exception as exc:
        raise ErroTranscricao("Resposta ilegível da OpenRouter.") from exc

    # Alguns modelos devolvem `content` como lista de partes em vez de string.
    if isinstance(conteudo, list):
        conteudo = "".join(
            p.get("text", "") for p in conteudo if isinstance(p, dict)
        )
    return _limpar(str(conteudo or ""))
