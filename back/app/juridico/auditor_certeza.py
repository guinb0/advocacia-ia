"""FACT_CERTAINTY: a redação respeita o nível de certeza de cada fato.

- dado REQUIRES_EXPERT_CONFIRMATION ou INFERRED afirmado sem ressalva (sem «perícia», «será apurado»,
  «indica», «alega»…) → bloqueia;
- dado CONTRADICTED usado no corpo → bloqueia;
- dado INDICATED_BY_DOCUMENTS escrito como prova cabal («comprova», «restou demonstrado») → bloqueia;
- afirmação categórica do que só a perícia pode dizer (incapacidade permanente, nexo comprovado) quando o
  plano manda requerer perícia → bloqueia.

A frase é a unidade: o valor do dado e uma palavra do que ele é (rótulo) precisam estar na mesma frase,
para «30%» de incapacidade não se confundir com «30%» de adicional.
"""

from __future__ import annotations

import re
from typing import Any

from . import canonico
from .auditores import BLOQUEIA, _achado, _texto
from .autoridades import norm
from .fatos import _variantes

AUDITOR = "FACT_CERTAINTY"
_RESSALVA = re.compile(
    r"per[íi]cia|pericial|perito|ser[áa]\s+(?:apurad|demonstrad|comprovad|confirmad)|a\s+ser\s+(?:apurad|confirmad|demonstrad)|"
    r"\bindic|sugere|aponta|alega|afirma\s+(?:o|a)\s+(?:autor|reclamante)|segundo\s+(?:o|a)|conforme\s+(?:relat|alega|narr)|em\s+tese|"
    r"eventual|poss[íi]vel|prov[áa]vel|requer|pugna|demonstrar[áa]|comprovar[áa]|se\s+confirmad|declarou|relata|narra|teria|haveria", re.I)
_CONCLUSIVO = re.compile(r"\bcomprova(?:m|do|da|dos|das)?\b|prova\s+cabal|restou\s+(?:comprovad|demonstrad|provad)|incontrovers|inequ[íi]voc|"
                         r"\bprovad[oa]\b|cabalmente", re.I)
_SO_PERICIA = re.compile(
    r"incapacidade\s+(?:laborativa\s+)?(?:total|permanente|definitiva|irrevers[íi]vel)|"
    r"nexo\s+(?:causal|concausal|t[ée]cnico)[^.;]{0,40}(?:est[áa]|restou|foi|resta)\s+(?:comprovad|demonstrad|configurad|evidenciad)|"
    r"doen[çc]a\s+ocupacional\s+(?:comprovad|confirmad|configurad)|(?:sequelas?|les[ãa]o)\s+(?:permanentes?|irrevers[íi]ve(?:l|is))|"
    r"redu[cç][ãa]o\s+(?:da\s+capacidade\s+)?(?:laborativa\s+)?permanente|permanece\s+com\s+sequelas?", re.I)


def _frases(texto: str) -> list[str]:
    return [f.strip() for f in re.split(r"(?<=[.;!?])\s+|\n+", texto) if f.strip()]


def _rotulo_tokens(rotulo: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]{5,}", norm(rotulo))} - {"autor", "data", "valor", "atual"}


def _formas(campo: dict[str, Any]) -> list[str]:
    formas = {canonico.exibir(campo), str(campo.get("valor_original") or "")}
    if campo.get("tipo") == "percentual" and campo.get("valor") is not None:
        n = f"{float(campo['valor']) * 100:g}".replace(".", ",")
        formas |= {f"{n}%", f"{n} %", f"{n} por cento"}
    for f in list(formas):
        formas |= set(_variantes(f))
    return [f for f in formas if f and len(f) >= 2]


def _ocorrencias(secoes: list[dict[str, Any]], formas: list[str], rotulo: str) -> list[tuple[str, str]]:
    tokens = _rotulo_tokens(rotulo)
    saida = []
    for s in secoes:
        for frase in _frases(_texto(s)):
            if any(f in frase for f in formas) and (not tokens or tokens & set(re.findall(r"[a-z]{5,}", norm(frase)))):
                saida.append((str(s.get("code") or ""), frase))
    return saida


def auditar(secoes: list[dict[str, Any]], *, canon: dict[str, Any] | None, matriz: dict[str, Any] | None = None,
            exige_pericia: bool = False) -> dict[str, Any]:
    achados: list[dict[str, Any]] = []
    campos = list(((canon or {}).get("campos") or {}).values())
    for e in campos:
        if e.get("derivado") and e["certeza"] in canonico.AFIRMAVEIS:
            continue
        if e["certeza"] == canonico.CONTRADICTED:
            formas = [x for v in e.get("versoes") or [] for x in _variantes(str(v.get("valor") or ""))]
            for code, frase in _ocorrencias(secoes, formas, e["rotulo"]):
                achados.append(_achado(AUDITOR, "FATO_CONTRADITORIO_USADO", BLOQUEIA, code, frase[:220],
                                       f"{e['rotulo']} é contraditório entre as fontes; resolva antes de usar"))
            continue
        if e.get("valor") in (None, ""):
            continue
        formas = _formas(e)
        for code, frase in _ocorrencias(secoes, formas, e["rotulo"]):
            if e["certeza"] in (canonico.REQUIRES_EXPERT_CONFIRMATION, canonico.INFERRED) and not _RESSALVA.search(frase):
                achados.append(_achado(AUDITOR, "FATO_INCERTO_AFIRMADO", BLOQUEIA, code, frase[:220],
                                       f"{e['rotulo']} é {canonico.ROTULOS_CERTEZA[e['certeza']]} e foi afirmado como fato certo"))
            elif e["certeza"] == canonico.INDICATED_BY_DOCUMENTS and _CONCLUSIVO.search(frase):
                achados.append(_achado(AUDITOR, "INDICIO_COMO_PROVA", BLOQUEIA, code, frase[:220],
                                       f"{e['rotulo']} é só indicado pelos documentos e foi escrito como prova cabal"))
    for f in (matriz or {}).get("fatos") or []:
        if canonico.certeza_do_fato(f) != canonico.INDICATED_BY_DOCUMENTS or canonico.chave_canonica(str(f.get("chave") or "")):
            continue
        valor = str(f.get("valor") or "").strip()
        if len(valor) < 4:
            continue
        for code, frase in _ocorrencias(secoes, _variantes(valor), str(f.get("chave") or "").split(".")[-1].replace("_", " ")):
            if _CONCLUSIVO.search(frase):
                achados.append(_achado(AUDITOR, "INDICIO_COMO_PROVA", BLOQUEIA, code, frase[:220], f"{f['id']} é indício documental, não prova cabal"))
    pericia = exige_pericia or any(e["certeza"] == canonico.REQUIRES_EXPERT_CONFIRMATION for e in campos)
    if pericia:
        for s in secoes:
            for frase in _frases(_texto(s)):
                if _SO_PERICIA.search(frase) and not _RESSALVA.search(frase):
                    achados.append(_achado(AUDITOR, "AFIRMACAO_QUE_DEPENDE_DE_PERICIA", BLOQUEIA, str(s.get("code") or ""), frase[:220],
                                           "conclusão que só a perícia pode firmar, escrita como fato certo"))
    vistos, unicos = set(), []
    for a in achados:
        k = (a["codigo"], a["trecho"])
        if k not in vistos:
            vistos.add(k)
            unicos.append(a)
    return {"auditor": AUDITOR, "achados": unicos}
