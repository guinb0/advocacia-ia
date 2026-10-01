"""SCORES por tese, calculados por CÓDIGO a partir do grafo (o modelo não dá nota). Cada score 0–1 vem com motivos.

factual_support      requisitos com fato utilizável, ponderados pela certeza (confirmado 1, alegado 0.5).
evidentiary_strength qualidade da melhor prova de cada requisito (classe da prova).
legal_support        proposições com autoridade, ponderadas pela certeza jurídica.
precedent_strength   o nível hierárquico da melhor autoridade favorável.
contradiction_risk   fatos da tese em contradição + defesas relevantes sem prova que as enfrente.
strategic_value      peso do pedido no valor da causa + função (pedido autônomo × só reflexo).

Usados para ORDENAR, ALERTAR e REVISAR — nunca para incluir ou excluir tese sozinhos.
"""

from __future__ import annotations

from typing import Any

from .fatos import ALEGADO, CONFIRMADO
from .proposicoes import BINDING, CONTESTED, PERSUASIVE, RESEARCH_REQUIRED, STRONG, UNSETTLED

_PESO_CERTEZA = {BINDING: 1.0, STRONG: 0.85, PERSUASIVE: 0.6, CONTESTED: 0.4, UNSETTLED: 0.2, RESEARCH_REQUIRED: 0.0}
NOMES = ("factual_support", "evidentiary_strength", "legal_support", "precedent_strength", "contradiction_risk", "strategic_value")


def _r(x: float) -> float:
    return round(max(0.0, min(1.0, x)), 2)


def _factual(t: dict[str, Any], fatos: dict[str, dict[str, Any]]) -> tuple[float, list[str]]:
    if not t["requisitos"]:
        return 0.0, ["nenhum requisito mapeado para a tese"]
    notas, motivos = [], []
    for r in t["requisitos"]:
        melhor = 0.0
        for ref in r["fatos"]:
            f = fatos.get(ref["id"]) or {}
            if f.get("contradicoes"):
                continue
            melhor = max(melhor, 1.0 if f.get("estado") == CONFIRMADO else 0.5 if f.get("estado") == ALEGADO else 0.0)
        notas.append(melhor)
        if melhor < 1.0:
            motivos.append(f"«{r['requisito']}»: " + ("só alegado" if melhor else "sem fato utilizável"))
    return _r(sum(notas) / len(notas)), motivos or [f"todos os {len(notas)} requisitos com fato confirmado"]


def _evidencia(t: dict[str, Any]) -> tuple[float, list[str]]:
    if not t["requisitos"]:
        return 0.0, ["sem requisitos"]
    notas, motivos = [], []
    for r in t["requisitos"]:
        provas = [p for p in r.get("provas") or [] if not p["contraditoria"]]
        melhor = max((p["peso"] for p in provas), default=0.0)
        notas.append(melhor)
        if provas:
            topo = max(provas, key=lambda p: p["peso"])
            motivos.append(f"«{r['requisito']}»: {topo['classe']}")
        else:
            motivos.append(f"«{r['requisito']}»: sem prova")
    return _r(sum(notas) / len(notas)), motivos


def _juridico(t: dict[str, Any]) -> tuple[float, list[str]]:
    props = t["proposicoes"]
    if not props:
        return 0.0, ["sem proposições"]
    notas = [_PESO_CERTEZA.get(p.get("certeza") or RESEARCH_REQUIRED, 0.0) for p in props]
    motivos = [f"«{p['texto'][:80]}»: {p.get('certeza') or 'não pesquisada'}" for p in props]
    return _r(sum(notas) / len(notas)), motivos


def _precedente(t: dict[str, Any]) -> tuple[float, list[str]]:
    favoraveis = [a for p in t["proposicoes"] for a in p.get("autoridades") or []
                  if a.get("posicao") not in ("contraria", "irrelevante") and a.get("vigente") is not False]
    if not favoraveis:
        return 0.0, ["nenhuma autoridade favorável vigente recuperada"]
    melhor = min(favoraveis, key=lambda a: a["prioridade"])
    return _r(1 - melhor["prioridade"] / 7), [f"melhor autoridade: {melhor['titulo']} (nível {melhor['prioridade']})"]


def _risco(t: dict[str, Any], fatos: dict[str, dict[str, Any]]) -> tuple[float, list[str]]:
    ids = {ref["id"] for r in t["requisitos"] for ref in r["fatos"]} | set(t.get("fatos_relevantes") or [])
    contraditos = [i for i in ids if (fatos.get(i) or {}).get("contradicoes")]
    sem_prova = [c for c in t.get("contrateses") or [] if not c.get("tem_prova") and c.get("forca") != "baixa"]
    nao_respondidas = [c for c in t.get("contrateses") or [] if c.get("respondida") is False and c.get("forca") == "alta"]
    base = (len(contraditos) / len(ids)) if ids else 0.0
    risco = base + 0.15 * len(sem_prova) + 0.1 * len(nao_respondidas)
    motivos = []
    if contraditos:
        motivos.append(f"fatos em contradição: {', '.join(sorted(contraditos))}")
    if sem_prova:
        motivos.append(f"{len(sem_prova)} defesa(s) relevante(s) sem prova que as enfrente")
    if nao_respondidas:
        motivos.append(f"{len(nao_respondidas)} defesa(s) forte(s) sem resposta na peça")
    return _r(risco), motivos or ["sem contradição nem defesa relevante descoberta"]


def _estrategico(t: dict[str, Any], total: float) -> tuple[float, list[str]]:
    valor = float(t["pedido"].get("valor") or 0)
    participacao = valor / total if total else 0.0
    autonomo = bool(t["pedido"].get("texto"))
    nota = 0.5 * participacao + (0.5 if autonomo else 0.15)
    motivos = [f"pedido {'autônomo' if autonomo else 'ausente/só reflexo'}"]
    if valor:
        motivos.append(f"{participacao:.0%} do valor calculado das teses")
    return _r(nota), motivos


def calcular(raciocinio: dict[str, Any], matriz: dict[str, Any]) -> list[dict[str, Any]]:
    fatos = {f["id"]: f for f in matriz.get("fatos") or []}
    total = sum(float(t["pedido"].get("valor") or 0) for t in raciocinio.get("teses") or [])
    saida = []
    for t in raciocinio.get("teses") or []:
        partes = {
            "factual_support": _factual(t, fatos), "evidentiary_strength": _evidencia(t), "legal_support": _juridico(t),
            "precedent_strength": _precedente(t), "contradiction_risk": _risco(t, fatos), "strategic_value": _estrategico(t, total),
        }
        s = {k: {"valor": v, "motivos": m} for k, (v, m) in partes.items()}
        v = {k: x["valor"] for k, x in s.items()}
        s["prioridade"] = _r(0.3 * v["factual_support"] + 0.2 * v["evidentiary_strength"] + 0.2 * v["legal_support"]
                             + 0.1 * v["precedent_strength"] + 0.2 * v["strategic_value"] - 0.3 * v["contradiction_risk"])
        t["scores"] = s
        saida.append({"tese_id": t["tese_id"], "tese": t["tese"], **s})
    raciocinio["ordem_por_prioridade"] = [x["tese_id"] for x in sorted(saida, key=lambda x: x["prioridade"], reverse=True)]
    return saida


def alertas(raciocinio: dict[str, Any]) -> list[str]:
    """O que o advogado precisa revisar, a partir dos scores das teses sustentadas."""
    saida = []
    for t in raciocinio.get("teses") or []:
        s = t.get("scores") or {}
        if t["decisao"] != "SUPPORTED" or not s:
            continue
        if s["factual_support"]["valor"] < 0.5:
            saida.append(f"Tese «{t['tese']}» com suporte fático baixo ({s['factual_support']['valor']:.0%}): "
                         + "; ".join(s["factual_support"]["motivos"][:3]))
        if s["legal_support"]["valor"] == 0 and t["proposicoes"]:
            saida.append(f"Tese «{t['tese']}» sem autoridade verificada para nenhuma proposição — fundamento depende de pesquisa")
        if s["contradiction_risk"]["valor"] >= 0.5:
            saida.append(f"Tese «{t['tese']}» com risco alto: " + "; ".join(s["contradiction_risk"]["motivos"][:2]))
    return saida
