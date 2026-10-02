"""CITATION GATE 2.0 (estende o gate de `autoridades`): toda citação passa por quatro checagens.

EXISTS          a autoridade está no registro e, se a citação desce a parágrafo/inciso, o dispositivo existe no
                texto oficial (art. 651-A, inciso que o artigo não tem → reprovada);
VALID_ON_DATE   vigente na data da petição — vigência DESCONHECIDA não passa (aguardando verificação);
NOT_SUPERSEDED  não revogada/superada; se superada, a sucessora vem do registro (Acervo);
SUPPORTS_CLAIM  o texto oficial sustenta a AFIRMAÇÃO em que a citação foi usada (entailment por LLM com JSON
                estrito e citação literal do texto oficial; o código confere que o trecho está mesmo no texto —
                se não estiver, é NO_SUPPORT).
TRANSCRIÇÃO     trecho entre aspas colado à citação tem de estar no texto VIGENTE; se bate com versão encerrada,
                REDACAO_ANTIGA_CITADA.

Classificação: EXACT_SUPPORT, PARTIAL_SUPPORT, CONTEXT_ONLY, NO_SUPPORT, CONTRADICTS, SUPERSEDED. Só passam
EXACT_SUPPORT e PARTIAL_SUPPORT com justificativa. Resultado em cache pelo par (hash da versão da autoridade,
hash da afirmação).
"""

from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from datetime import date
from threading import Lock
from typing import Any, Callable

from . import autoridades as aut
from .auditores import BLOQUEIA, _achado, _texto
from .autoridades import Autoridade, Citacao, extrair_citacoes, norm

EXACT_SUPPORT, PARTIAL_SUPPORT, CONTEXT_ONLY = "EXACT_SUPPORT", "PARTIAL_SUPPORT", "CONTEXT_ONLY"
NO_SUPPORT, CONTRADICTS, SUPERSEDED = "NO_SUPPORT", "CONTRADICTS", "SUPERSEDED"
CLASSES = (EXACT_SUPPORT, PARTIAL_SUPPORT, CONTEXT_ONLY, NO_SUPPORT, CONTRADICTS, SUPERSEDED)
NAO_AVALIADO = "NOT_EVALUATED"
AUDITOR = "CITATION_GATE"
TAMANHO_MINIMO_TRECHO_OFICIAL = 20
LOTE = 10

_CACHE: "OrderedDict[tuple[str, str], dict[str, Any]]" = OrderedDict()
_CACHE_MAX = 5000
_TRAVA = Lock()


def _h(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:24]


def hash_da_versao(a: Autoridade) -> str:
    return _h(f"{a.id}|{a.versao}|{a.texto or a.tese}")


def _compacto(t: str) -> str:
    return norm(" ".join(str(t or "").split()))


def limpar_cache() -> None:
    with _TRAVA:
        _CACHE.clear()


def afirmacao(texto: str, c: Citacao) -> str:
    """A frase em que a citação foi usada (com a anterior, quando a frase da citação é só a remissão)."""
    inicio = max(texto.rfind(". ", 0, c.inicio), texto.rfind("\n", 0, c.inicio)) + 1
    fins = [i for i in (texto.find(". ", c.inicio), texto.find("\n", c.inicio)) if i >= 0]
    fim = min(fins) + 1 if fins else len(texto)
    frase = texto[inicio:fim].strip()
    if len(frase) < 90 or re.match(r"(?:nos termos|conforme|consoante|a teor|na forma)\b", frase, re.I):
        anterior_inicio = max(texto.rfind(". ", 0, max(0, inicio - 2)), texto.rfind("\n", 0, max(0, inicio - 2))) + 1
        frase = texto[anterior_inicio:fim].strip()
    return frase[:900]


_ASPAS = re.compile(r"[“\"«]([^”\"»]{30,1500})[”\"»]")
_RETICENCIAS = re.compile(r"\(\s*(?:\.\.\.|…)\s*\)|\[\s*(?:\.\.\.|…)\s*\]|\.\.\.|…")
DISTANCIA_MAXIMA_DA_TRANSCRICAO = 160


def _literal(t: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", norm(t)).split())


def transcricao(texto: str, c: Citacao) -> str:
    """Trecho entre aspas colado à citação ("art. 477 ... dispõe: “...”" ou "“...” (art. 477 da CLT)")."""
    fim = c.inicio + len(c.trecho)
    janela_inicio = max(0, c.inicio - 1700)
    for m in _ASPAS.finditer(texto, janela_inicio, min(len(texto), fim + 1700)):
        if 0 <= m.start() - fim <= DISTANCIA_MAXIMA_DA_TRANSCRICAO or 0 <= c.inicio - m.end() <= DISTANCIA_MAXIMA_DA_TRANSCRICAO:
            return m.group(1)
    return ""


def conferir_transcricao(trecho: str, a: Autoridade, registro: Any) -> tuple[str, str] | None:
    """Transcrição literal × texto oficial vigente. Se bate com uma versão ENCERRADA do mesmo dispositivo,
    é redação antiga (ex.: texto tachado do Planalto copiado como se vigorasse)."""
    partes = [p for p in (_literal(x) for x in _RETICENCIAS.split(trecho)) if len(p) >= 12]
    if not partes or not a.texto:
        return None
    if all(p in _literal(a.texto) for p in partes):
        return None
    for outra in getattr(registro, "por_chave", {}).get(a.chave, []):
        if outra.id != a.id and outra.texto and all(p in _literal(outra.texto) for p in partes):
            return ("REDACAO_ANTIGA_CITADA",
                    f"a transcrição reproduz a redação {outra.versao or outra.id} (vigente até {outra.vigencia_fim or 'data não informada'}), "
                    f"não a vigente na data da petição ({a.versao or a.id}); transcreva o texto atual do Acervo")
    return ("TRANSCRICAO_DIVERGENTE_DO_TEXTO_OFICIAL",
            "o trecho entre aspas não consta do texto oficial vigente do dispositivo (redação antiga ou paráfrase entre aspas)")


def _dispositivo_existe(a: Autoridade, c: Citacao) -> tuple[bool, str]:
    """Parágrafo/inciso citado existe no texto oficial do artigo (quando o registro é do artigo inteiro)."""
    if c.tipo != "artigo" or not a.texto:
        return True, ""
    d = c.detalhe or {}
    texto = a.texto
    if d.get("inciso") and not a.inciso and not re.search(rf"(?m)(?:^|\s){re.escape(d['inciso'])}\s*[-–—]", texto):
        return False, f"o artigo não tem o inciso {d['inciso']} no texto oficial"
    par = d.get("paragrafo")
    if par and not a.paragrafo:
        achou = re.search(r"par[áa]grafo\s+[úu]nico", texto, re.I) if par == "unico" else re.search(rf"§\s*{re.escape(par)}\s*[º°o]?", texto)
        if not achou:
            return False, f"o artigo não tem o § {par} no texto oficial"
    return True, ""


_INSTRUCAO = f"""Você verifica se o TEXTO OFICIAL de uma norma/precedente sustenta a AFIRMAÇÃO em que ele foi citado numa petição.
Para cada item, classifique:
- {EXACT_SUPPORT}: o texto oficial diz exatamente o que a afirmação atribui a ele;
- {PARTIAL_SUPPORT}: sustenta parte da afirmação (explique qual parte em `justificativa`);
- {CONTEXT_ONLY}: trata do mesmo assunto, mas não sustenta a afirmação;
- {NO_SUPPORT}: não sustenta;
- {CONTRADICTS}: diz o contrário.
Devolva JSON estrito: {{"itens":[{{"id":"C1","classificacao":"...","trecho_oficial":"cópia LITERAL do texto oficial que sustenta (obrigatória em EXACT/PARTIAL)","justificativa":"..."}}]}}
Não use conhecimento externo: só o texto oficial fornecido."""


def _avaliar_lote(llm: Callable[[str, str], dict[str, Any]], lote: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    entrada = "\n\n".join(f"### {i['id']}\nAFIRMAÇÃO: {i['afirmacao']}\nTEXTO OFICIAL ({i['titulo']}): {i['texto'][:6000]}" for i in lote)
    saida = llm(_INSTRUCAO, entrada) or {}
    por_id: dict[str, dict[str, Any]] = {}
    for r in saida.get("itens") or []:
        if isinstance(r, dict) and str(r.get("id") or "") in {i["id"] for i in lote}:
            por_id[str(r["id"])] = r
    resultado = {}
    for i in lote:
        r = por_id.get(i["id"]) or {}
        classe = str(r.get("classificacao") or "").strip().upper()
        classe = classe if classe in CLASSES and classe != SUPERSEDED else NO_SUPPORT
        trecho = str(r.get("trecho_oficial") or "").strip()
        justificativa = str(r.get("justificativa") or "").strip()
        motivo = ""
        if classe in (EXACT_SUPPORT, PARTIAL_SUPPORT):
            minimo = min(TAMANHO_MINIMO_TRECHO_OFICIAL, len(_compacto(i["texto"])))
            if len(_compacto(trecho)) < minimo or _compacto(trecho) not in _compacto(i["texto"]):
                classe, motivo = NO_SUPPORT, "o trecho citado como sustentação não está no texto oficial"
        if not r:
            motivo = "o verificador não devolveu este item"
        resultado[i["id"]] = {"classificacao": classe, "trecho_oficial": trecho[:600], "justificativa": justificativa[:600], "motivo": motivo}
    return resultado


def verificar(
    secoes: list[dict[str, Any]], registro: Any, data_referencia: date | None, *,
    llm: Callable[[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registros: list[dict[str, Any]] = []
    pendentes: list[dict[str, Any]] = []
    for s in secoes:
        texto, code = _texto(s), str(s.get("code") or "")
        for c in extrair_citacoes(texto):
            r = registro.resolver(c, data_referencia)
            a: Autoridade | None = registro.por_id.get(r.get("authority_id")) if r.get("authority_id") else None
            existe = r["status"] not in (aut.REQUIRES_LEGAL_RESEARCH, aut.AMBIGUA) and a is not None
            motivo_existe = r.get("motivo", "") if not existe else ""
            if existe and a is not None:
                existe, motivo_existe = _dispositivo_existe(a, c)
            superada = r["status"] in (aut.SUPERADA, aut.FORA_DE_VIGENCIA) or (a is not None and a.status in aut.STATUS_INATIVOS)
            vigente = a.vigente_em(data_referencia) if a is not None else None
            sucessora = registro.por_referencia(a.superado_por) if a is not None and a.superado_por else None
            reg = {
                "trecho": c.trecho, "chave": c.chave, "secao": code, "afirmacao": afirmacao(texto, c),
                "authority_id": a.id if a else None, "versao": a.versao if a else "", "titulo": (a.titulo or a.chave) if a else "",
                "checks": {"EXISTS": existe, "VALID_ON_DATE": True if vigente is True else (None if vigente is None else False),
                           "NOT_SUPERSEDED": not superada, "SUPPORTS_CLAIM": None},
                "classificacao": SUPERSEDED if superada else (NO_SUPPORT if not existe else NAO_AVALIADO),
                "motivo": motivo_existe or (r.get("motivo", "") if superada else ""),
                "trecho_oficial": "", "justificativa": "", "cache": False,
                "sucessora": {"id": sucessora.id, "titulo": sucessora.titulo or sucessora.chave} if sucessora else None,
                "transcricao": None,
            }
            if existe and not superada and a is not None and c.tipo == "artigo":
                literal = transcricao(texto, c)
                problema = conferir_transcricao(literal, a, registro) if literal else None
                if problema:
                    reg["transcricao"] = {"codigo": problema[0], "motivo": problema[1], "trecho": literal[:300]}
            registros.append(reg)
            if existe and not superada and a is not None:
                texto_oficial = (a.texto or a.tese or "").strip()
                if not texto_oficial:
                    reg.update(classificacao=NO_SUPPORT, motivo="autoridade sem texto oficial no Acervo")
                    continue
                chave = (hash_da_versao(a), _h(_compacto(reg["afirmacao"])))
                with _TRAVA:
                    em_cache = _CACHE.get(chave)
                if em_cache:
                    reg.update(em_cache, cache=True)
                    continue
                pendentes.append({"reg": reg, "chave": chave, "afirmacao": reg["afirmacao"], "texto": texto_oficial, "titulo": reg["titulo"]})
    erro_llm = ""
    if pendentes and llm is not None:
        for inicio in range(0, len(pendentes), LOTE):
            lote = pendentes[inicio:inicio + LOTE]
            for k, p in enumerate(lote, start=1):
                p["id"] = f"C{k}"
            try:
                avaliados = _avaliar_lote(llm, lote)
            except Exception as erro:  # noqa: BLE001 - item fica NOT_EVALUATED e o gate não passa
                erro_llm = f"{type(erro).__name__}: {str(erro)[:160]}"
                continue
            for p in lote:
                resultado = avaliados[p["id"]]
                p["reg"].update(resultado)
                if not resultado.get("motivo"):
                    with _TRAVA:
                        _CACHE[p["chave"]] = resultado
                        while len(_CACHE) > _CACHE_MAX:
                            _CACHE.popitem(last=False)
    achados: list[dict[str, Any]] = []
    for reg in registros:
        classe = reg["classificacao"]
        reg["checks"]["SUPPORTS_CLAIM"] = {EXACT_SUPPORT: True, PARTIAL_SUPPORT: bool(reg["justificativa"])}.get(classe, None if classe == NAO_AVALIADO else False)
        reg["aprovada"] = bool(reg["checks"]["EXISTS"] and reg["checks"]["VALID_ON_DATE"] is True and reg["checks"]["NOT_SUPERSEDED"]
                               and reg["checks"]["SUPPORTS_CLAIM"] is True)
        if reg["authority_id"] is None:
            continue  # sem autoridade: o auditor LEGAL já bloqueia (REQUIRES_LEGAL_RESEARCH)
        if reg["transcricao"]:
            reg["aprovada"] = False
            achados.append(_achado(AUDITOR, reg["transcricao"]["codigo"], BLOQUEIA, reg["secao"], reg["transcricao"]["trecho"],
                                   reg["transcricao"]["motivo"]))
        if not reg["checks"]["EXISTS"]:
            achados.append(_achado(AUDITOR, "DISPOSITIVO_INEXISTENTE", BLOQUEIA, reg["secao"], reg["trecho"], reg["motivo"]))
        elif classe == SUPERSEDED:
            achados.append(_achado(AUDITOR, "AUTORIDADE_SUPERADA", BLOQUEIA, reg["secao"], reg["trecho"],
                                   reg["motivo"] + (f"; sucessora no Acervo: {reg['sucessora']['titulo']} [{reg['sucessora']['id']}]" if reg["sucessora"] else "")))
        else:
            if reg["checks"]["VALID_ON_DATE"] is not True:
                achados.append(_achado(AUDITOR, "VIGENCIA_NAO_COMPROVADA" if reg["checks"]["VALID_ON_DATE"] is None else "FORA_DE_VIGENCIA",
                                       BLOQUEIA, reg["secao"], reg["trecho"], "vigência na data da petição não comprovada no Acervo (AGUARDANDO_VERIFICACAO)"
                                       if reg["checks"]["VALID_ON_DATE"] is None else "não vigente na data da petição"))
            if classe == NAO_AVALIADO:
                achados.append(_achado(AUDITOR, "SUSTENTACAO_NAO_VERIFICADA", BLOQUEIA, reg["secao"], reg["trecho"],
                                       "a verificação de sustentação (entailment) não executou" + (f": {erro_llm}" if erro_llm else "")))
            elif classe == CONTRADICTS:
                achados.append(_achado(AUDITOR, "CITACAO_CONTRADIZ_A_AFIRMACAO", BLOQUEIA, reg["secao"], reg["trecho"], reg["justificativa"] or reg["motivo"]))
            elif classe in (NO_SUPPORT, CONTEXT_ONLY):
                achados.append(_achado(AUDITOR, "CITACAO_NAO_SUSTENTA_A_AFIRMACAO", BLOQUEIA, reg["secao"], reg["trecho"],
                                       f"{classe}: " + (reg["motivo"] or reg["justificativa"] or "o texto oficial não sustenta o que a peça afirma")))
            elif classe == PARTIAL_SUPPORT and not reg["justificativa"]:
                achados.append(_achado(AUDITOR, "SUSTENTACAO_PARCIAL_SEM_JUSTIFICATIVA", BLOQUEIA, reg["secao"], reg["trecho"], "sustentação parcial sem dizer qual parte"))
    return {"auditor": AUDITOR, "achados": achados, "citacoes": registros,
            "resumo": {k: sum(1 for r in registros if r["classificacao"] == k) for k in (*CLASSES, NAO_AVALIADO)},
            "erro_llm": erro_llm}
