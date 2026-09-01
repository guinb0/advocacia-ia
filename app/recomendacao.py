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

import hashlib
import logging
import json
import os
import threading
from typing import Any

import httpx

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
    """Falta base NA ENTREVISTA para recomendar — o texto já diz o que falta."""


class BaseIndisponivel(RuntimeError):
    """O banco de precedentes não respondeu.

    Separado de `ErroRecomendacao` porque o conserto é outro: aqui não falta dado
    da entrevista, falta a VPN ou o servidor. A rota traduz cada um num status
    diferente, e a tela passa a dizer o que fazer em vez de "indisponível".
    """


# CACHE DO RELATO
#
# A tela refaz a consulta a cada mudança do relato consolidado, e cada uma custa
# ~30s: gera embedding e busca no pgvector atrás da VPN. Durante a entrevista o
# mesmo texto reaparece várias vezes — o entrevistador corrige um campo, o relato
# consolidado não muda, e a consulta ia de novo assim mesmo.
#
# A chave inclui as lacunas porque elas mudam o veredito: com obrigatória em
# aberto, `sim` é rebaixado para `com_ressalva`.
_trava = threading.Lock()
_cache: dict[str, dict[str, Any]] = {}
#: Teto pequeno: uma entrevista gera poucas variações do relato, e o processo
#: fica dias no ar.
LIMITE_CACHE = 200

#: Separador da chave de cache. Não pode ser vazio: sem ele, relato "ab" com
#: lacuna "c" daria a mesma chave que relato "a" com lacuna "bc", e uma
#: entrevista herdaria o veredito de outra.
SEP_CHAVE = "␟"


def _chave_cache(relato: str, lacunas: list[str]) -> str:
    # Separador explícito: sem ele, relato "ab" + lacuna "c" daria a mesma chave
    # que relato "a" + lacuna "bc", e uma entrevista herdaria o veredito de outra.
    partes = [relato.strip(), *sorted(lacunas)]
    cru = SEP_CHAVE.join(partes)
    return hashlib.sha256(cru.encode("utf-8")).hexdigest()


def limpar_cache() -> None:
    with _trava:
        _cache.clear()


def recomendar(
    relato: str,
    *,
    lacunas_obrigatorias: list[str] | None = None,
    limite: int = 12,
    connect_timeout: int = 10,
    detalhar: bool = False,
) -> dict[str, Any]:
    """Lê o relato da entrevista e diz se vale abrir o caso.

    `lacunas_obrigatorias` são as perguntas do roteiro que a entrevista ainda não
    respondeu. Quem as conhece é a tela, não este módulo — ele só as considera no
    veredito e as devolve para o advogado ver o que ainda falta levantar.
    """
    lacunas = [item for item in (lacunas_obrigatorias or []) if str(item).strip()]

    if not relato.strip():
        raise ErroRecomendacao("Sem relato não há o que recomendar.")

    chave = _chave_cache(relato, lacunas)
    with _trava:
        em_cache = _cache.get(chave)
    if em_cache is not None:
        # ~30s economizados. Durante a entrevista o mesmo relato consolidado
        # reaparece a cada correção de campo que não muda o texto.
        return {**em_cache, "do_cache": True}

    try:
        similares = rag.buscar_similares(
            relato, limite=limite, connect_timeout=connect_timeout
        )
    except rag.ErroRAG as exc:
        # Distinto de `ErroRecomendacao`: aqui não falta dado da entrevista, o
        # banco é que não respondeu. A rota devolve 503 com esta causa, em vez de
        # um "indisponível" que não diz se é esperar ou checar a VPN.
        raise BaseIndisponivel(str(exc)) from exc
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

    detalhes = _analisar_pontos(relato, similares) if detalhar else None
    resultado = {
        "recomendado": veredito,
        "motivo": motivo,
        "lacunas_obrigatorias": lacunas,
        "estatistica": estatistica,
        "precedentes": [t.referencia() for t in similares],
        "com_precedentes": True,
        "analise_comparativa": detalhes,
        "aviso": (
            "Descritivo da amostra semelhante, não previsão de êxito. A recomendação "
            "é sobre ABRIR o caso para análise; o mérito é decisão do advogado."
        ),
    }

    # Só o resultado BOM entra no cache. `indefinido` por falta de amostra pode
    # virar recomendação de verdade quando o relato crescer — guardá-lo
    # congelaria o veredito pelo resto da entrevista.
    with _trava:
        if len(_cache) >= LIMITE_CACHE:
            _cache.clear()
        _cache[chave] = resultado
    return {**resultado, "do_cache": False}


def _analisar_pontos(relato: str, similares: list[Any]) -> dict[str, Any] | None:
    """Compara fatos e provas sem transformar correlação em causa ou prognóstico."""
    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not chave:
        return None
    usados = similares[:8]
    contexto = []
    validos: set[str] = set()
    for indice, trecho in enumerate(usados, 1):
        ref = f"P{indice}"
        validos.add(ref)
        dados = trecho.referencia()
        contexto.append(
            f"[{ref}] processo={dados.get('processo')} resultado={dados.get('resultado')} "
            f"vara={dados.get('vara')} similaridade={dados.get('similaridade')}\n"
            f"{trecho.texto[:2600]}"
        )
    instrucao = """Você auxilia um advogado trabalhista durante a entrevista.
Compare o relato SOMENTE com os precedentes fornecidos. Identifique fatos e provas
realmente coincidentes, não simples palavras iguais. O rótulo do resultado pertence
ao processo inteiro: não invente causalidade se o trecho não explicar a decisão.
Contraste favoráveis e improcedentes. Toda afirmação deve citar P1, P2 etc.; descarte
o ponto se não houver apoio textual. Seja concreto e útil para mudar a condução da
entrevista. Não estime chance de vitória.

As `perguntas_criticas` serão lidas por um entrevistador que pode não ter
formação jurídica. Escreva cada uma como uma pergunta curta, direta e pronta
para ser dita ao cliente. Não use jargão, não mande o entrevistador interpretar
a resposta e não escreva orientações abstratas como "investigue o nexo".

Responda somente JSON:
{"sintese":"...","pontos_comuns":[{"ponto":"...","impacto":"...","forca":"alta|media|baixa","precedentes":["P1"]}],"diferencas_decisivas":[{"ponto":"...","por_que_importa":"...","precedentes_favoraveis":["P1"],"precedentes_contrarios":["P2"]}],"provas_prioritarias":[{"prova":"...","motivo":"...","precedentes":["P1"]}],"perguntas_criticas":["..."]}
"""
    try:
        resposta = httpx.post(
            os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
            + "/chat/completions",
            headers={"Authorization": f"Bearer {chave}"},
            json={
                "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": instrucao},
                    {"role": "user", "content": f"RELATO:\n{relato[:10000]}\n\nPRECEDENTES:\n" + "\n\n".join(contexto)},
                ],
            },
            timeout=35,
        )
        resposta.raise_for_status()
        dados = json.loads(resposta.json()["choices"][0]["message"]["content"])
        for chave_lista in ("pontos_comuns", "provas_prioritarias"):
            limpos = []
            for item in dados.get(chave_lista) or []:
                if not isinstance(item, dict):
                    continue
                refs = [str(ref) for ref in item.get("precedentes", []) if str(ref) in validos]
                if refs:
                    item["precedentes"] = refs
                    limpos.append(item)
            dados[chave_lista] = limpos[:5]
        diferencas = []
        for item in dados.get("diferencas_decisivas") or []:
            if not isinstance(item, dict):
                continue
            item["precedentes_favoraveis"] = [str(r) for r in item.get("precedentes_favoraveis", []) if str(r) in validos]
            item["precedentes_contrarios"] = [str(r) for r in item.get("precedentes_contrarios", []) if str(r) in validos]
            if item["precedentes_favoraveis"] or item["precedentes_contrarios"]:
                diferencas.append(item)
        dados["diferencas_decisivas"] = diferencas[:5]
        dados["perguntas_criticas"] = [str(x).strip() for x in dados.get("perguntas_criticas", []) if str(x).strip()][:6]
        dados["referencias"] = {f"P{i}": trecho.referencia() for i, trecho in enumerate(usados, 1)}
        return dados
    except Exception:
        log.warning("Análise comparativa da recomendação indisponível", exc_info=True)
        return None


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
        "analise_comparativa": None,
        "aviso": (
            "Sem base comparável suficiente. A entrevista segue valendo; o que falta "
            "é precedente parecido, não caso."
        ),
    }
