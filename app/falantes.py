"""Quem falou o quê, inferido do texto — porque o áudio não sabe.

O QUE ISTO É, E O QUE NÃO É

O microfone é da sala e tem um canal só: as duas vozes chegam misturadas, sem
etiqueta. Separá-las de verdade é diarização — outro modelo, mais memória de
placa e mais latência, sobre uma GPU que já divide 6 GB entre o Whisper e o OCR.

Isto aqui não é diarização. É **inferência a partir do texto**, e ela acerta pelo
mesmo motivo que o resto do sistema funciona: o entrevistador LÊ o roteiro. O
enunciado que ele lê é o mesmo texto que este módulo tem em mãos, e uma pergunta
seguida de "sim" é uma pergunta seguida de uma resposta.

ONDE ELA ERRA, E POR QUE ISSO PRECISA ESTAR ESCRITO NO DOCUMENTO

Quando uma pessoa só fala os dois lados — um teste do sistema, o entrevistador
lendo a pergunta e já respondendo em voz alta o que o cliente disse por telefone
— a inferência atribui a duas pessoas o que foi de uma. Não há sinal no texto que
distinga esse caso.

Por isso nada aqui afirma: o rótulo sai como leitura, o trecho sem sinal fica
SEM rótulo em vez de receber um chute, e o cabeçalho do documento diz que a
atribuição é inferida. Um documento que erra dizendo "o cliente afirmou" é pior
que um documento que não atribui — este vai para peça processual.

O ORIGINAL NÃO É REESCRITO

O texto de cada trecho sai daqui igual ao que entrou. O que se acrescenta é o
rótulo ao lado. Quem quiser conferir a transcrição crua continua tendo a
transcrição crua.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from . import roteiros

__all__ = ["ENTREVISTADOR", "CLIENTE", "INDEFINIDO", "atribuir"]

ENTREVISTADOR = "ENTREVISTADOR"
CLIENTE = "CLIENTE"
#: Sem sinal suficiente. Preferido ao chute: ver o cabeçalho do módulo.
INDEFINIDO = ""

#: Quanto do trecho precisa vir do enunciado do roteiro para ser leitura dele.
#: Mais frouxo que o 0,8 da escuta (`_e_o_enunciado`) de propósito: lá um falso
#: positivo DESCARTA uma resposta do cliente, aqui ele só troca um rótulo — e o
#: erro fica visível no documento, ao lado do texto que o desmente.
COBERTURA_ROTEIRO = 0.6

#: Uma frase precisa disto para ser julgada pelo roteiro. Abaixo, é resposta
#: curta, e resposta curta se decide pela pergunta que veio antes.
MINIMO_PALAVRAS = 4

#: Primeira pessoa: quem narra o próprio caso é o cliente. O entrevistador fala
#: na segunda ("o senhor sofreu") e na primeira do plural ("vamos falar de").
_EU = frozenset(
    {
        "eu", "meu", "minha", "meus", "minhas", "comigo", "mim",
        "fui", "fiquei", "tive", "sofri", "trabalho", "trabalhei", "trabalhava",
        "recebi", "recebia", "ganhava", "ganho", "entrei", "sai", "cai",
        "senti", "sinto", "consigo", "consegui", "levei", "fiz", "faco",
        "moro", "morava", "estou", "to", "tava", "estava",
    }
)

#: Confirmação e negação curtas: são resposta, e resposta é do cliente.
_RESPOSTA_CURTA = frozenset(
    {
        "sim", "nao", "isso", "isso mesmo", "exato", "exatamente", "correto",
        "uhum", "aham", "claro", "nunca", "jamais", "sempre", "certo",
        "sim senhor", "sim senhora", "nao senhor", "nao senhora", "perfeito",
    }
)

#: Palavras que não distinguem nada — entram igual na pergunta e na resposta.
_VAZIAS = frozenset(
    {
        "a", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos",
        "e", "em", "essa", "esse", "esta", "este", "foi", "ha", "isso", "ja",
        "la", "me", "na", "nas", "no", "nos", "o", "os", "ou", "para", "pela",
        "pelo", "por", "que", "se", "sem", "ser", "seu", "sua", "tem", "um",
        "uma", "voce", "voces", "senhor", "senhora", "sr", "sra", "dr", "dra",
        "doutor", "doutora",
    }
)

#: Corta em ponto final, interrogação e exclamação, PRESERVANDO o sinal — é ele
#: que diz se a frase é pergunta. Um trecho costuma trazer a pergunta e a
#: resposta juntas, e rotular o trecho inteiro perderia justamente a troca.
_FRASES = re.compile(r"[^.!?…]+[.!?…]*", re.UNICODE)

#: Ponto ENTRE dígitos não termina frase: é CPF, CEP, valor, número de processo.
#: Sem isto "897.003.841-87" vira três frases, e duas delas ficam sem rótulo por
#: não terem palavra nenhuma. Medido na primeira execução.
_PONTO_EM_NUMERO = re.compile(r"(?<=\d)\.(?=\d)")
#: Area de uso privado do Unicode: nao aparece em transcricao de voz, entao
#: serve de marca temporaria sem risco de colidir com o texto do cliente.
_MARCA = ""


def _frases(texto: str) -> list[str]:
    protegido = _PONTO_EM_NUMERO.sub(_MARCA, texto)
    return [f.replace(_MARCA, ".") for f in _FRASES.findall(protegido)]


def _sem_acento(valor: str) -> str:
    decomposto = unicodedata.normalize("NFKD", valor)
    return "".join(letra for letra in decomposto if not unicodedata.combining(letra))


def _palavras(valor: str) -> list[str]:
    return [p.strip(".,;:!?()-…\"'") for p in _sem_acento(valor).casefold().split()]


def _proprias(valor: str) -> list[str]:
    return [p for p in _palavras(valor) if p and p not in _VAZIAS]


def _enunciados(codigo_roteiro: str) -> list[list[str]]:
    """As perguntas do roteiro, reduzidas a palavras comparáveis."""
    roteiro = roteiros.obter(codigo_roteiro)
    if roteiro is None:
        return []
    escritos = []
    for bloco in roteiro.blocos:
        for pergunta in bloco.perguntas:
            texto = " ".join([pergunta.texto, " ".join(pergunta.opcoes)])
            palavras = [p for p in _palavras(texto) if p]
            if palavras:
                escritos.append(palavras)
    return escritos


def _le_o_roteiro(frase: str, enunciados: list[list[str]]) -> bool:
    """A frase é o entrevistador lendo uma pergunta do roteiro?"""
    palavras = _proprias(frase)
    if len(palavras) < MINIMO_PALAVRAS:
        return False
    for escrito in enunciados:
        conjunto = set(escrito)
        cobertas = sum(1 for p in palavras if p in conjunto)
        if cobertas / len(palavras) >= COBERTURA_ROTEIRO:
            return True
    return False


def _quem(frase: str, enunciados: list[list[str]], anterior: str) -> str:
    """O falante da frase, ou vazio quando o texto não diz.

    A ordem das regras é a ordem da confiança que cada sinal merece.
    """
    limpa = frase.strip()
    if not limpa:
        return INDEFINIDO

    palavras = _palavras(limpa)
    nucleo = " ".join(p for p in palavras if p).strip()

    # 1. Resposta curta de confirmação. É o sinal mais forte que existe: ninguém
    #    faz uma pergunta dizendo "sim".
    if nucleo in _RESPOSTA_CURTA:
        return CLIENTE

    # 2. Leitura do roteiro. O entrevistador é o único que tem o texto na mão.
    if _le_o_roteiro(limpa, enunciados):
        return ENTREVISTADOR

    # 3. Interrogação. O cliente também pergunta ("como assim?"), mas é raro, e
    #    perto do enunciado do roteiro a pergunta é de quem conduz.
    if limpa.endswith("?"):
        return ENTREVISTADOR

    # 4. Primeira pessoa. Quem narra o próprio caso é o cliente.
    if any(p in _EU for p in palavras):
        return CLIENTE

    # 5. Sem sinal próprio: a frase que vem depois de uma pergunta é a resposta
    #    dela. Só isto — depois de uma fala do cliente NÃO se conclui nada, senão
    #    a conversa inteira se alternaria sozinha a partir de um único acerto.
    if anterior == ENTREVISTADOR:
        return CLIENTE

    return INDEFINIDO


def atribuir(
    trechos: list[dict[str, Any]], codigo_roteiro: str = "empregado_publico"
) -> dict[str, Any]:
    """Rotula cada frase da transcrição com quem provavelmente a disse.

    `trechos` são os registros crus da tela: `{"quando": ..., "texto": ...}`. O
    texto sai igual ao que entrou — o rótulo vem ao lado, nunca no lugar.
    """
    enunciados = _enunciados(codigo_roteiro)
    falas: list[dict[str, Any]] = []
    anterior = INDEFINIDO
    contagem = {ENTREVISTADOR: 0, CLIENTE: 0, INDEFINIDO: 0}

    for trecho in trechos:
        texto = str(trecho.get("texto") or "").strip()
        if not texto:
            continue
        for frase in _frases(texto):
            limpa = frase.strip()
            if not limpa:
                continue
            quem = _quem(limpa, enunciados, anterior)
            contagem[quem] += 1
            falas.append({"quando": trecho.get("quando"), "quem": quem, "texto": limpa})
            if quem != INDEFINIDO:
                anterior = quem

    return {
        "falas": falas,
        "total": len(falas),
        "entrevistador": contagem[ENTREVISTADOR],
        "cliente": contagem[CLIENTE],
        "indefinido": contagem[INDEFINIDO],
        # Dito no retorno para a tela não ter de saber disto por fora: quem
        # monta o documento precisa escrever que a atribuição é inferida.
        "metodo": (
            "Atribuição inferida do texto, não do áudio. O microfone é de canal "
            "único e não separa vozes; o que distingue os falantes aqui é o "
            "enunciado do roteiro, a forma interrogativa e a primeira pessoa. "
            "Frase sem sinal fica sem rótulo. Uma pessoa que fale os dois lados "
            "será atribuída a duas."
        ),
    }
