"""JURISPRUDÊNCIA POR PROPOSIÇÃO, CERTEZA JURÍDICA, CONFLITO e PRECEDENT_QUALITY_AUDITOR.

Cada tese do grafo tem 2–5 proposições (o que a peça precisa convencer o juiz). Para cada uma:
- busca no MESMO provedor de autoridades da geração (`Registro.consultar`, com hierarquia, recência e status);
- classificação sustenta/contraria/irrelevante em lote pelo modelo, exigindo trecho LITERAL da autoridade
  (o código confere; sem trecho, vira «relacionada»), em cache pelo par (versão da autoridade, proposição);
- certeza jurídica: BINDING, STRONG, PERSUASIVE, CONTESTED, UNSETTLED, RESEARCH_REQUIRED;
- conflito: POSITION_A (a favor) × POSITION_B (contra), `controlling_authority` quando um lado tem autoridade
  vinculante mais alta, senão `unresolved_conflict`.
Sem classificação pelo modelo, a relação é «presumida» e a certeza nunca passa de PERSUASIVE.

O nível vai ao prompt do capítulo com o tom; `auditar_certeza` acusa linguagem absoluta em proposição
CONTESTED/UNSETTLED/RESEARCH_REQUIRED e `auditar_precedentes` a qualidade dos precedentes citados.
"""

from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from datetime import date
from threading import Lock
from typing import Any, Callable

from . import autoridades as aut
from .auditores import ALERTA, INFORMA, _achado, _texto
from .busca import Filtros
from .citacao import hash_da_versao
from .raciocinio import tokens

BINDING, STRONG, PERSUASIVE = "BINDING", "STRONG", "PERSUASIVE"
CONTESTED, UNSETTLED, RESEARCH_REQUIRED = "CONTESTED", "UNSETTLED", "RESEARCH_REQUIRED"
NIVEIS_DE_CERTEZA = (BINDING, STRONG, PERSUASIVE, CONTESTED, UNSETTLED, RESEARCH_REQUIRED)
INCERTOS = {CONTESTED, UNSETTLED, RESEARCH_REQUIRED}
SUSTENTA, CONTRARIA, RELACIONADA, IRRELEVANTE = "sustenta", "contraria", "relacionada", "irrelevante"
TOM = {
    BINDING: "afirme com segurança, apoiado na autoridade vinculante/norma indicada",
    STRONG: "afirme com firmeza, citando o entendimento do tribunal superior",
    PERSUASIVE: "sustente como entendimento favorável, sem linguagem absoluta («pacífico», «consolidado»)",
    CONTESTED: "reconheça que há divergência e sustente a posição favorável com a autoridade mais alta; nada de «pacífico»",
    UNSETTLED: "argumente com cautela: há autoridade contrária ou o tema não está assentado; distinga o caso",
    RESEARCH_REQUIRED: "não cite autoridade de memória; marque a pesquisa pendente",
}
AUDITOR_CERTEZA, AUDITOR_PRECEDENTES = "LEGAL_CERTAINTY", "PRECEDENT_QUALITY"
LOTE = 20
#: só as N primeiras autoridades de cada proposição (já na ordem da hierarquia) vão ao modelo — custo previsível
CLASSIFICAR_POR_PROPOSICAO = 3
ANOS_PRECEDENTE_ANTIGO = 8
_JURISPRUDENCIA = {"sumula", "sumula_vinculante", "oj", "tema", "controle_concentrado", "precedente"}

_CACHE: "OrderedDict[tuple[str, str], dict[str, Any]]" = OrderedDict()
_CACHE_MAX = 5000
_TRAVA = Lock()


def _h(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:24]


def _compacto(t: str) -> str:
    return aut.norm(" ".join(str(t or "").split()))


def limpar_cache() -> None:
    with _TRAVA:
        _CACHE.clear()


# ------------------------------------------------------------------ busca por proposição

def pesquisar(
    raciocinio: dict[str, Any], registro: Any, *, data_referencia: date | None, trt_competente: str = "", k: int = 5,
    llm: Callable[[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    filtros = Filtros(data_referencia=data_referencia, incluir_inativas=True, trt_competente=trt_competente)
    consultas = 0
    for t in raciocinio.get("teses") or []:
        for p in t["proposicoes"]:
            achados = registro.consultar(f"{p['texto']} {t['tese']}", filtros, k)
            consultas += 1
            p["autoridades"] = [{
                "id": a.id, "titulo": a.titulo or a.chave, "tipo": a.tipo, "tribunal": a.tribunal, "orgao": a.orgao,
                "prioridade": aut.prioridade(a, trt_competente), "data": a.data or a.vigencia_inicio,
                "vigente": a.vigente_em(data_referencia), "verificada": a.verificada, "vinculante": a.vinculante,
                "status": a.status, "superado_por": a.superado_por, "score": s, "posicao": RELACIONADA, "avaliada": False, "trecho": "",
            } for a, s in achados]
    erro = ""
    if llm is not None:
        erro = classificar(raciocinio, registro, llm)
    for t in raciocinio.get("teses") or []:
        for p in t["proposicoes"]:
            p.update(certeza(p))
            p["tom"] = TOM[p["certeza"]]
    return {"consultas": consultas, "erro_classificacao": erro, "classificadas": llm is not None and not erro}


_INSTRUCAO = """Você verifica se o TEXTO de uma autoridade (lei, súmula, tema, acórdão) SUSTENTA ou CONTRARIA uma PROPOSIÇÃO jurídica.
Para cada item: "sustenta" (o texto afirma a proposição), "contraria" (afirma o oposto) ou "irrelevante".
Em sustenta/contraria, `trecho` é cópia LITERAL do texto da autoridade que mostra isso (obrigatória).
Devolva JSON estrito: {"itens":[{"id":"A1","posicao":"sustenta|contraria|irrelevante","trecho":"..."}]}
Use só o texto fornecido, sem conhecimento externo."""


def classificar(raciocinio: dict[str, Any], registro: Any, llm: Callable[[str, str], dict[str, Any]]) -> str:
    pendentes = []
    por_id = getattr(registro, "por_id", None) or {}
    for t in raciocinio.get("teses") or []:
        if t["decisao"] != "SUPPORTED":
            continue
        for p in t["proposicoes"]:
            for item in (p.get("autoridades") or [])[:CLASSIFICAR_POR_PROPOSICAO]:
                a = por_id.get(item["id"])
                texto = (getattr(a, "texto", "") or getattr(a, "tese", "") or "").strip() if a else ""
                if not texto:
                    continue
                chave = (hash_da_versao(a), _h(_compacto(p["texto"])))
                with _TRAVA:
                    em_cache = _CACHE.get(chave)
                if em_cache:
                    item.update(em_cache, cache=True)
                    continue
                pendentes.append({"item": item, "chave": chave, "proposicao": p["texto"], "texto": texto, "titulo": item["titulo"]})
    erro = ""
    for inicio in range(0, len(pendentes), LOTE):
        lote = pendentes[inicio:inicio + LOTE]
        for n, x in enumerate(lote, start=1):
            x["id"] = f"A{n}"
        entrada = "\n\n".join(f"### {x['id']}\nPROPOSIÇÃO: {x['proposicao']}\nTEXTO ({x['titulo']}): {x['texto'][:2500]}" for x in lote)
        try:
            saida = llm(_INSTRUCAO, entrada) or {}
        except Exception as e:  # noqa: BLE001 - sem classificação a relação fica presumida
            erro = f"{type(e).__name__}: {str(e)[:160]}"
            continue
        por_id = {str(r.get("id")): r for r in saida.get("itens") or [] if isinstance(r, dict)}
        for x in lote:
            r = por_id.get(x["id"]) or {}
            posicao = str(r.get("posicao") or "").strip().lower()
            trecho = str(r.get("trecho") or "").strip()
            if posicao in (SUSTENTA, CONTRARIA) and (len(_compacto(trecho)) < 12 or _compacto(trecho) not in _compacto(x["texto"])):
                posicao = RELACIONADA
            if posicao not in (SUSTENTA, CONTRARIA, IRRELEVANTE):
                posicao = RELACIONADA
            resultado = {"posicao": posicao, "trecho": trecho[:400] if posicao in (SUSTENTA, CONTRARIA) else "", "avaliada": bool(r)}
            x["item"].update(resultado)
            if r:
                with _TRAVA:
                    _CACHE[x["chave"]] = resultado
                    while len(_CACHE) > _CACHE_MAX:
                        _CACHE.popitem(last=False)
    return erro


# ------------------------------------------------------------------ certeza e conflito

def _nivel_por_hierarquia(melhor: int) -> str:
    if melhor <= 2:
        return BINDING
    if melhor <= 4:
        return STRONG
    return PERSUASIVE


def certeza(p: dict[str, Any]) -> dict[str, Any]:
    validas = [a for a in p.get("autoridades") or [] if a.get("vigente") is not False and a.get("posicao") != IRRELEVANTE]
    avaliada = any(a.get("avaliada") for a in p.get("autoridades") or [])
    pro = [a for a in validas if a["posicao"] == SUSTENTA] if avaliada else [a for a in validas if a["posicao"] in (SUSTENTA, RELACIONADA)]
    contra = [a for a in validas if a["posicao"] == CONTRARIA]
    conflito = None
    if not pro and not contra:
        nivel = RESEARCH_REQUIRED
    elif pro and contra:
        bp, bc = min(a["prioridade"] for a in pro), min(a["prioridade"] for a in contra)
        controla = None
        if bp < bc and bp <= 2:
            controla = min(pro, key=lambda a: a["prioridade"])
        elif bc < bp and bc <= 2:
            controla = min(contra, key=lambda a: a["prioridade"])
        conflito = {"position_a": [a["id"] for a in pro], "position_b": [a["id"] for a in contra],
                    "controlling_authority": controla["id"] if controla else None, "unresolved_conflict": controla is None}
        nivel = (BINDING if controla in pro else UNSETTLED) if controla else CONTESTED
    elif pro:
        nivel = _nivel_por_hierarquia(min(a["prioridade"] for a in pro))
        if nivel == BINDING and not any(a.get("verificada") for a in pro):
            nivel = STRONG
    else:
        nivel = UNSETTLED
    if not avaliada and nivel in (BINDING, STRONG):
        nivel = PERSUASIVE
    return {"certeza": nivel, "conflito": conflito, "classificacao": "avaliada" if avaliada else "presumida"}


# ------------------------------------------------------------------ auditores

_ABSOLUTA = re.compile(
    r"pac[íi]fic|consolidad|indiscut[íi]vel|inquestion[áa]vel|un[âa]nim|sedimentad|remansos|iterativ[ao]|"
    r"sem\s+qualquer\s+d[úu]vida|n[ãa]o\s+h[áa]\s+(?:qualquer\s+)?d[úu]vida|firme\s+(?:a\s+)?jurisprud|jurisprud[êe]ncia\s+(?:[ée]\s+)?firme|"
    r"entendimento\s+(?:j[áa]\s+)?pac", re.I)


def _frases(texto: str) -> list[str]:
    return [f.strip() for f in re.split(r"(?<=[.;!?])\s+|\n+", texto) if f.strip()]


def auditar_certeza(secoes: list[dict[str, Any]], raciocinio: dict[str, Any] | None) -> dict[str, Any]:
    """Linguagem absoluta («pacífico», «consolidado») em frase sobre proposição sem certeza assentada."""
    achados = []
    incertas = [(t, p) for t in (raciocinio or {}).get("teses") or [] for p in t["proposicoes"] if p.get("certeza") in INCERTOS]
    for s in secoes:
        code = str(s.get("code") or "")
        if code in ("CLAIMS", "VALUE", "CLOSING", "HEADING"):
            continue
        for frase in _frases(_texto(s)):
            if not _ABSOLUTA.search(frase):
                continue
            alvo = tokens(frase)
            for t, p in incertas:
                chave = tokens(p["texto"]) or tokens(t["tese"])
                if chave and len(alvo & chave) >= max(2, round(len(chave) * 0.4)):
                    achados.append(_achado(AUDITOR_CERTEZA, "LINGUAGEM_ABSOLUTA_EM_PROPOSICAO_INCERTA", ALERTA, code, frase,
                                           f"proposição «{p['texto'][:120]}» tem certeza {p['certeza']}: {TOM[p['certeza']]}"))
                    break
    return {"auditor": AUDITOR_CERTEZA, "achados": achados}


def auditar_precedentes(secoes: list[dict[str, Any]], raciocinio: dict[str, Any] | None, registro: Any,
                        data_referencia: date | None) -> dict[str, Any]:
    """PRECEDENT_QUALITY_AUDITOR: regional havendo superior, antigo havendo superior recente, sem proposição, redundante."""
    achados: list[dict[str, Any]] = []
    props = [p for t in (raciocinio or {}).get("teses") or [] for p in t["proposicoes"]]
    por_autoridade: dict[str, list[dict[str, Any]]] = {}
    for p in props:
        for a in p.get("autoridades") or []:
            por_autoridade.setdefault(a["id"], []).append(p)
    citadas: list[tuple[str, Any, str]] = []
    for s in secoes:
        code = str(s.get("code") or "")
        for c in aut.extrair_citacoes(_texto(s)):
            r = registro.resolver(c, data_referencia)
            a = (getattr(registro, "por_id", None) or {}).get(r.get("authority_id")) if r.get("authority_id") else None
            if a is not None:
                citadas.append((code, a, c.trecho))
    ids_citados = {a.id for _, a, _ in citadas}
    por_prop_citadas: dict[str, set[str]] = {}
    for code, a, trecho in citadas:
        ligadas = por_autoridade.get(a.id) or []
        if a.tipo in _JURISPRUDENCIA and not ligadas:
            achados.append(_achado(AUDITOR_PRECEDENTES, "AUTORIDADE_SEM_PROPOSICAO", INFORMA, code, trecho,
                                   "precedente citado que não corresponde a nenhuma proposição das teses — confira a pertinência"))
        for p in ligadas:
            if a.tipo == "precedente":
                por_prop_citadas.setdefault(p["id"], set()).add(a.id)
            superiores = [x for x in p.get("autoridades") or [] if x["prioridade"] <= 2 and x["posicao"] != CONTRARIA
                          and x.get("vigente") is not False and x["id"] not in ids_citados and x["tipo"] not in ("artigo", "lei")]
            meu = aut.prioridade(a)
            if meu >= 5 and superiores:
                achados.append(_achado(AUDITOR_PRECEDENTES, "PRECEDENTE_REGIONAL_COM_SUPERIOR_DISPONIVEL", ALERTA, code, trecho,
                                       f"para «{p['texto'][:100]}» há {superiores[0]['titulo']} (tribunal superior) não citado"))
            minha_data = aut._data(a.data)  # noqa: SLF001
            if a.tipo == "precedente" and minha_data and data_referencia and (data_referencia - minha_data).days > ANOS_PRECEDENTE_ANTIGO * 365:
                recentes = [x for x in p.get("autoridades") or [] if x["prioridade"] < meu and aut._data(x.get("data"))  # noqa: SLF001
                            and aut._data(x["data"]) > minha_data and x["posicao"] != CONTRARIA]  # noqa: SLF001
                if recentes:
                    achados.append(_achado(AUDITOR_PRECEDENTES, "PRECEDENTE_ANTIGO_COM_ENTENDIMENTO_SUPERIOR_RECENTE", ALERTA, code, trecho,
                                           f"julgado de {minha_data.year}; há entendimento superior mais recente: {recentes[0]['titulo']}"))
    for pid, ids in por_prop_citadas.items():
        if len(ids) > 3:
            achados.append(_achado(AUDITOR_PRECEDENTES, "JULGADOS_REDUNDANTES", INFORMA, "", pid,
                                   f"{len(ids)} julgados citados para a mesma proposição; mantenha os mais altos e recentes"))
    vistos, unicos = set(), []
    for x in achados:
        k = (x["codigo"], x["trecho"])
        if k not in vistos:
            vistos.add(k)
            unicos.append(x)
    return {"auditor": AUDITOR_PRECEDENTES, "achados": unicos}


def resumo(raciocinio: dict[str, Any] | None) -> dict[str, int]:
    contagem = dict.fromkeys(NIVEIS_DE_CERTEZA, 0)
    for t in (raciocinio or {}).get("teses") or []:
        for p in t["proposicoes"]:
            if p.get("certeza") in contagem:
                contagem[p["certeza"]] += 1
    return contagem
