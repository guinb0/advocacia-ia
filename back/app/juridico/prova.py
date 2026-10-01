"""MATRIZ DE PROVA por requisito e EVIDENCE GAP DETECTOR.

Para cada requisito do grafo (`raciocinio`): fato necessário, prova disponível (com classe e qualidade),
o que é contraditório, o que falta e a prova que terá de ser produzida em juízo.

Classes: PRIMARY_DOCUMENT, OFFICIAL_RECORD, MEDICAL_RECORD, PARTY_STATEMENT, WITNESS_NEEDED,
EXPERT_EVIDENCE_NEEDED, INFERENCE_ONLY — a do documento vem de `dados/classes_de_prova.json` (nome/tipo do
documento); fato só da entrevista é PARTY_STATEMENT; inferido é INFERENCE_ONLY.

Lacuna = requisito com prova fraca, ausente ou contraditória, com a prova típica e a alternativa de
`dados/provas_tipicas.json` («Tese: horas extras / Força: média / Ausente: cartões de ponto / Alternativa: testemunhal»).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .autoridades import norm
from .fatos import ALEGADO, CONFIRMADO, INFERIDO

_DADOS = Path(__file__).resolve().parent / "dados"
PRIMARY_DOCUMENT, OFFICIAL_RECORD, MEDICAL_RECORD = "PRIMARY_DOCUMENT", "OFFICIAL_RECORD", "MEDICAL_RECORD"
PARTY_STATEMENT, WITNESS_NEEDED, EXPERT_EVIDENCE_NEEDED, INFERENCE_ONLY = "PARTY_STATEMENT", "WITNESS_NEEDED", "EXPERT_EVIDENCE_NEEDED", "INFERENCE_ONLY"
CLASSES = (PRIMARY_DOCUMENT, OFFICIAL_RECORD, MEDICAL_RECORD, PARTY_STATEMENT, WITNESS_NEEDED, EXPERT_EVIDENCE_NEEDED, INFERENCE_ONLY)
FORTE, MEDIA, FRACA, AUSENTE = "forte", "media", "fraca", "ausente"
ROTULO_FORCA = {FORTE: "forte", MEDIA: "média", FRACA: "fraca", AUSENTE: "ausente"}


@lru_cache(maxsize=1)
def _classes() -> dict[str, Any]:
    with (_DADOS / "classes_de_prova.json").open(encoding="utf-8") as f:
        dados = json.load(f)
    return {"pesos": dados["pesos"], "documentos": [(d["classe"], [re.compile(p) for p in d["padroes"]]) for d in dados["documentos"]]}


@lru_cache(maxsize=1)
def _tipicas() -> dict[str, dict[str, str]]:
    with (_DADOS / "provas_tipicas.json").open(encoding="utf-8") as f:
        return json.load(f)["provas"]


def peso(classe: str) -> float:
    return float(_classes()["pesos"].get(classe, 0.0))


def classe_do_documento(nome: str) -> str | None:
    alvo = norm(nome)
    for classe, padroes in _classes()["documentos"]:
        if any(p.search(alvo) for p in padroes):
            return classe
    return None


def classe_do_fato(f: dict[str, Any]) -> str:
    if f.get("estado") == INFERIDO:
        return INFERENCE_ONLY
    documento = str(f.get("documento") or "")
    if f.get("estado") == ALEGADO or not documento:
        return PARTY_STATEMENT if f.get("estado") != CONFIRMADO else (classe_do_documento(str(f.get("fonte") or "")) or PRIMARY_DOCUMENT)
    return classe_do_documento(documento) or PRIMARY_DOCUMENT


def prova_tipica(requisito_id: str) -> dict[str, str]:
    tab = _tipicas()
    sufixo = requisito_id.split(".", 1)[1] if "." in requisito_id else requisito_id
    return tab.get(requisito_id) or tab.get(f"*.{sufixo}") or tab["*.*"]


#: cada prova independente além da melhor soma isto (corroboração), sem passar de 1
CORROBORACAO = 0.15


def qualidade(provas: list[dict[str, Any]]) -> float:
    """A melhor prova não contraditória + corroboração das demais. Só a alegação da parte (0,4) é FRACA;
    duas fontes que se confirmam chegam a MÉDIA."""
    pesos = sorted((p["peso"] for p in provas if not p["contraditoria"]), reverse=True)
    if not pesos:
        return 0.0
    return min(1.0, pesos[0] + CORROBORACAO * len([x for x in pesos[1:] if x > 0]))


def _forca(qualidade: float) -> str:
    if qualidade >= 0.85:
        return FORTE
    if qualidade >= 0.5:
        return MEDIA
    if qualidade > 0:
        return FRACA
    return AUSENTE


def montar(raciocinio: dict[str, Any], matriz: dict[str, Any]) -> list[dict[str, Any]]:
    """Anota cada requisito do grafo com as provas e devolve a matriz (uma linha por requisito)."""
    fatos = {f["id"]: f for f in matriz.get("fatos") or []}
    linhas = []
    for t in raciocinio.get("teses") or []:
        for r in t["requisitos"]:
            provas = []
            for ref in r["fatos"]:
                f = fatos.get(ref["id"])
                if not f:
                    continue
                classe = classe_do_fato(f)
                provas.append({"fato_id": f["id"], "classe": classe, "peso": peso(classe), "documento": str(f.get("documento") or ""),
                               "fonte": str(f.get("fonte") or ""), "estado": f.get("estado"), "contraditoria": bool(f.get("contradicoes"))})
            provas.sort(key=lambda p: (not p["contraditoria"], p["peso"]), reverse=True)
            nota = qualidade(provas)
            forca = _forca(nota)
            tipica = prova_tipica(r["id"] if r["instituto"] else "*.*")
            precisa_pericia = tipica.get("futura") == EXPERT_EVIDENCE_NEEDED and (forca != FORTE or r["id"].endswith(".pericia"))
            futura = [tipica["futura"]] if forca in (FRACA, AUSENTE) or precisa_pericia else []
            if t.get("exige_pericia") and r["id"].endswith(".pericia") and EXPERT_EVIDENCE_NEEDED not in futura:
                futura.append(EXPERT_EVIDENCE_NEEDED)
            r["provas"] = provas
            r["forca_da_prova"] = forca
            linhas.append({
                "tese_id": t["tese_id"], "tese": t["tese"], "requisito_id": r["id"], "requisito": r["requisito"],
                "provas_disponiveis": provas, "qualidade": round(nota, 2), "forca": forca, "ausente": forca == AUSENTE,
                "contraditoria": any(p["contraditoria"] for p in provas), "prova_futura_necessaria": futura,
                "prova_tipica": tipica["tipica"], "alternativa": tipica["alternativa"],
            })
    raciocinio["matriz_de_prova"] = linhas
    return linhas


def lacunas(raciocinio: dict[str, Any]) -> list[dict[str, Any]]:
    """Evidence Gap Detector: requisito com prova fraca, ausente ou contraditória."""
    saida = []
    for linha in raciocinio.get("matriz_de_prova") or []:
        if linha["forca"] not in (FRACA, AUSENTE) and not linha["contraditoria"]:
            continue
        motivo = ("a única prova está em contradição entre as fontes" if linha["contraditoria"] and linha["forca"] in (FRACA, AUSENTE)
                  else "há prova, mas parte dela é contraditória" if linha["contraditoria"]
                  else "nenhuma prova no caso" if linha["forca"] == AUSENTE else "só a alegação da parte ou inferência")
        saida.append({
            "tese_id": linha["tese_id"], "tese": linha["tese"], "requisito_id": linha["requisito_id"], "requisito": linha["requisito"],
            "forca": linha["forca"], "ausente": linha["prova_tipica"], "alternativa": linha["alternativa"],
            "classe_futura": (linha["prova_futura_necessaria"] or [WITNESS_NEEDED])[0], "motivo": motivo,
        })
    raciocinio["lacunas"] = saida
    return saida


def forca_da_tese(raciocinio: dict[str, Any], tese_id: str) -> str:
    linhas = [x for x in raciocinio.get("matriz_de_prova") or [] if x["tese_id"] == tese_id]
    if not linhas:
        return AUSENTE
    return _forca(sum(x["qualidade"] for x in linhas) / len(linhas))


def resumo_da_lacuna(lacuna: dict[str, Any], forca_tese: str) -> str:
    return (f"Tese: {lacuna['tese']} / Força: {ROTULO_FORCA.get(forca_tese, forca_tese)} / Requisito: {lacuna['requisito']} / "
            f"Ausente: {lacuna['ausente']} / Alternativa: {lacuna['alternativa']}")


def pendencias(raciocinio: dict[str, Any], *, limite: int = 8) -> list[str]:
    """As lacunas das teses sustentadas, na forma que o advogado lê no relatório."""
    teses = {t["tese_id"]: t for t in raciocinio.get("teses") or []}
    saida = []
    for lac in raciocinio.get("lacunas") or []:
        t = teses.get(lac["tese_id"])
        if t is None or t["decisao"] != "SUPPORTED":
            continue
        saida.append("Lacuna de prova — " + resumo_da_lacuna(lac, forca_da_tese(raciocinio, lac["tese_id"])))
    return saida[:limite]
