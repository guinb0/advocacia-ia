"""Se vale abrir o caso — dito pela entrevista, com o que processos iguais decidiram.

POR QUE ISTO NÃO É UMA PREVISÃO, E O TEXTO PRECISA DIZER ISSO

A tentação óbvia é devolver "72% de chance de ganhar". Seria mentira: o que o
pgvector tem é uma amostra de processos SEMANTICAMENTE parecidos, e semelhança
de texto não é semelhança de prova. O mesmo relato com CAT emitida e laudo
pericial vale outra coisa que sem nenhum dos dois.

Então o que sai daqui é descritivo: destes N processos parecidos, tantos foram
favoráveis no mérito — e é isso que está escrito na tela, com os números à
vista. A recomendação em si é sobre ABRIR O CASO para o advogado analisar, que é
uma decisão barata e reversível, e não sobre o mérito, que não é nossa.

O QUE REBAIXA A RECOMENDAÇÃO, MESMO COM AMOSTRA BOA

Lacuna obrigatória pesa mais que estatística. Um relato de doença ocupacional
sem data de afastamento e sem laudo não é um caso fraco — é um caso que ainda
não foi levantado, e mandar o advogado decidir sobre ele é desperdiçar a decisão.
Por isso lacuna nunca deixa passar de `com_ressalva`: o que falta é perguntar,
não concluir.
"""

from __future__ import annotations

import logging
from typing import Any

from . import rag

log = logging.getLogger("recomendacao")

#: Abaixo disto a amostra não sustenta afirmação nenhuma — devolve `indefinido`
#: em vez de inventar confiança em cima de dois ou três processos.
MINIMO_PROCESSOS = 4

#: Similaridade mediana abaixo disto quer dizer que o pgvector não achou nada
#: realmente parecido: os textos vieram por palavra em comum, não por caso em
#: comum. Medido nas consultas reais desta casa, um relato bem casado fica em
#: 0,72–0,75; abaixo de 0,65 a amostra já fala de outro assunto.
SIMILARIDADE_MINIMA = 0.65

#: Percentual de desfechos favoráveis NO MÉRITO (procedente + parcial) a partir
#: do qual a amostra deixa de ser sinal de alerta. Não é limiar de "vai ganhar":
#: é onde o parecido deixa de ser majoritariamente perdido.
FAVORAVEL_BOM = 60.0
FAVORAVEL_DUVIDOSO = 30.0


class ErroRecomendacao(RuntimeError):
    pass


def recomendar(
    relato: str,
    *,
    lacunas_obrigatorias: list[str] | None = None,
    limite: int = 12,
    connect_timeout: int = 10,
) -> dict[str, Any]:
    """Lê o relato da entrevista e diz se vale abrir o caso.

    `lacunas_obrigatorias` são as perguntas do roteiro que a entrevista ainda não
    respondeu. Quem as conhece é a tela, não este módulo — ele só as considera no
    veredito e as devolve para o advogado ver o que ainda falta levantar.
    """
    lacunas = [item for item in (lacunas_obrigatorias or []) if str(item).strip()]

    if not relato.strip():
        raise ErroRecomendacao("Sem relato não há o que recomendar.")

    similares = rag.buscar_similares(
        relato, limite=limite, connect_timeout=connect_timeout
    )
    if not similares:
        # Sem banco não se cala: a entrevista continua, e a tela precisa saber
        # que o que falta é a base, não o caso.
        return _sem_base(lacunas, "O banco de precedentes não devolveu nada comparável.")

    estatistica = rag._estatisticas_amostra(similares)
    merito = estatistica["desfechos_merito"]
    mediana = estatistica["similaridade_amostra"]["mediana"]

    if merito["processos"] < MINIMO_PROCESSOS:
        return _sem_base(
            lacunas,
            f"Só {merito['processos']} processo(s) da amostra tiveram decisão de mérito — "
            "pouco para afirmar qualquer coisa.",
            estatistica=estatistica,
            similares=similares,
        )

    if mediana < SIMILARIDADE_MINIMA:
        return _sem_base(
            lacunas,
            f"A semelhança mediana da amostra ({mediana:.2f}) é baixa: os processos "
            "recuperados provavelmente tratam de outro assunto.",
            estatistica=estatistica,
            similares=similares,
        )

    percentual = merito["percentual"]
    if percentual >= FAVORAVEL_BOM:
        veredito, motivo = "sim", (
            f"Dos {merito['processos']} processos parecidos com decisão de mérito, "
            f"{merito['favoraveis']} ({percentual:.0f}%) foram favoráveis ao trabalhador."
        )
    elif percentual >= FAVORAVEL_DUVIDOSO:
        veredito, motivo = "com_ressalva", (
            f"A amostra é dividida: {merito['favoraveis']} de {merito['processos']} "
            f"({percentual:.0f}%) favoráveis no mérito. Vale abrir, sabendo que casos "
            "parecidos têm ido para os dois lados."
        )
    else:
        veredito, motivo = "atencao", (
            f"Casos parecidos têm sido majoritariamente perdidos: só {merito['favoraveis']} "
            f"de {merito['processos']} ({percentual:.0f}%) favoráveis no mérito. Abrir "
            "exige prova que os deste grupo não tiveram."
        )

    # Lacuna obrigatória nunca deixa passar de `com_ressalva`: o que falta ainda
    # pode mudar o caso inteiro, e decidir antes de perguntar é decidir no escuro.
    if lacunas and veredito == "sim":
        veredito = "com_ressalva"
        motivo += (
            f" Rebaixado porque a entrevista ainda não respondeu "
            f"{len(lacunas)} item(ns) obrigatório(s)."
        )

    return {
        "recomendado": veredito,
        "motivo": motivo,
        "lacunas_obrigatorias": lacunas,
        "estatistica": estatistica,
        "precedentes": [t.referencia() for t in similares],
        "com_precedentes": True,
        "aviso": (
            "Descritivo da amostra semelhante, não previsão de êxito. A recomendação "
            "é sobre ABRIR o caso para análise; o mérito é decisão do advogado."
        ),
    }


def _sem_base(
    lacunas: list[str],
    motivo: str,
    *,
    estatistica: dict[str, Any] | None = None,
    similares: list[Any] | None = None,
) -> dict[str, Any]:
    """Sem amostra que sustente, o veredito é `indefinido` — nunca um palpite.

    Devolver "sim" por falta de contra-indicação seria pior que não responder: a
    tela mostraria um aval que ninguém deu.
    """
    return {
        "recomendado": "indefinido",
        "motivo": motivo,
        "lacunas_obrigatorias": lacunas,
        "estatistica": estatistica or {},
        "precedentes": [t.referencia() for t in (similares or [])],
        "com_precedentes": bool(similares),
        "aviso": (
            "Sem base comparável suficiente. A entrevista segue valendo; o que falta "
            "é precedente parecido, não caso."
        ),
    }
