"""Benchmark sintético do motor jurídico: roda os casos de `casos.py` com modelo FALSO determinístico e mede contra o
gabarito. Sem rede e sem banco — roda no CI (`.gitlab-ci.yml`, job motor-juridico) e é comparado a `linha_de_base.json`.

    python -m tests.benchmark.sintetico            # mostra as métricas e compara com a linha de base
    python -m tests.benchmark.sintetico --gravar   # grava a linha de base (só depois de revisar a melhora)
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from app.juridico import contrateses, proposicoes, prova, raciocinio, scores
from app.juridico.autoridades import Registro

from .casos import CASOS

HOJE = date(2026, 10, 15)
ARQUIVO_BASE = Path(__file__).resolve().parent / "linha_de_base.json"
#: métricas em que MENOR é melhor; as demais, maior é melhor
MENOR_E_MELHOR = {"falsos_positivos_caso_limpo"}


def _classificador(caso: dict[str, Any], rac: dict[str, Any]) -> Any:
    """Modelo falso: devolve a posição do gabarito do caso, com trecho LITERAL do texto da autoridade."""
    por_titulo = {a.titulo: a for a in caso.get("autoridades") or []}
    indice = {p["texto"]: p["id"].rsplit(".", 1)[1] for t in rac["teses"] for p in t["proposicoes"]}
    tabela = caso.get("classificacao") or {}

    def llm(instrucao: str, entrada: str) -> dict[str, Any]:
        itens = []
        for bloco in entrada.split("### ")[1:]:
            id_ = bloco.split("\n", 1)[0].strip()
            prop = bloco.split("PROPOSIÇÃO: ", 1)[1].split("\n", 1)[0].strip()
            titulo = bloco.split("TEXTO (", 1)[1].split("): ", 1)[0]
            a = por_titulo.get(titulo)
            posicao = (tabela.get(a.id) or {}).get(indice.get(prop, ""), "irrelevante") if a else "irrelevante"
            texto = (a.texto or a.tese) if a else ""
            itens.append({"id": id_, "posicao": posicao, "trecho": texto[:60] if posicao != "irrelevante" else ""})
        return {"itens": itens}
    return llm


def rodar_caso(caso: dict[str, Any]) -> dict[str, Any]:
    matriz = {"fatos": copy.deepcopy(caso["fatos"]), "contradicoes": []}
    rac = raciocinio.montar({"teses": copy.deepcopy(caso["teses"])}, matriz)
    prova.montar(rac, matriz)
    prova.lacunas(rac)
    contrateses.gerar(rac, matriz)
    registro = Registro(caso.get("autoridades") or [])
    proposicoes.pesquisar(rac, registro, data_referencia=HOJE, llm=_classificador(caso, rac) if caso.get("autoridades") else None)
    secoes = [{"code": "LEGAL_GROUNDS", "content": caso["peticao"]}]
    contra = contrateses.auditar(secoes, rac)
    certeza = proposicoes.auditar_certeza(secoes, rac)
    scores.calcular(rac, matriz)
    return {"raciocinio": rac, "achados": [*contra["achados"], *certeza["achados"]], "certeza": certeza["achados"]}


def _somar(conta: dict[str, list[int]], nome: str, acertos: int, total: int) -> None:
    c = conta.setdefault(nome, [0, 0])
    c[0] += acertos
    c[1] += total


def medir(caso: dict[str, Any], saida: dict[str, Any], conta: dict[str, list[int]]) -> dict[str, Any]:
    g, rac = caso["gabarito"], saida["raciocinio"]
    reqs = {r["id"]: r for t in rac["teses"] for r in t["requisitos"]}
    detalhe: dict[str, Any] = {}
    if "requisitos" in g:
        erros = {k: reqs.get(k, {}).get("estado") for k, v in g["requisitos"].items() if reqs.get(k, {}).get("estado") != v}
        _somar(conta, "requisitos_acerto", len(g["requisitos"]) - len(erros), len(g["requisitos"]))
        detalhe["requisitos_errados"] = erros
    if "lacunas" in g:
        detectadas = {x["requisito_id"] for x in rac["lacunas"]}
        esperadas = set(g["lacunas"])
        _somar(conta, "lacunas_recall", len(detectadas & esperadas), len(esperadas))
        _somar(conta, "lacunas_precisao", len(detectadas & esperadas), len(detectadas))
        detalhe["lacunas"] = sorted(detectadas)
    if "vulneraveis" in g:
        detectadas = {(t["tese_id"], c["requisito_id"]) for t in rac["teses"] for c in t["contrateses"] if c["vulneravel"]}
        esperadas = {tuple(x) for x in g["vulneraveis"]}
        _somar(conta, "vulneraveis_recall", len(detectadas & esperadas), len(esperadas))
        _somar(conta, "vulneraveis_precisao", len(detectadas & esperadas), len(detectadas))
        detalhe["vulneraveis"] = sorted(detectadas)
    if "respondidas" in g:
        por_req = {c["requisito_id"]: c["respondida"] for t in rac["teses"] for c in t["contrateses"]}
        certas = sum(por_req.get(k) == v for k, v in g["respondidas"].items())
        _somar(conta, "respondidas_acerto", certas, len(g["respondidas"]))
    if "certeza" in g:
        props = {p["id"]: p for t in rac["teses"] for p in t["proposicoes"]}
        certas = sum((props.get(k) or {}).get("certeza") == v for k, v in g["certeza"].items())
        _somar(conta, "certeza_acerto", certas, len(g["certeza"]))
        detalhe["certeza"] = {k: (props.get(k) or {}).get("certeza") for k in g["certeza"]}
    if "linguagem_absoluta" in g:
        props = {p["id"]: p for t in rac["teses"] for p in t["proposicoes"]}
        acusadas = {pid for pid, p in props.items() for a in saida["certeza"] if p["texto"][:120] in a["detalhe"]}
        esperadas = set(g["linguagem_absoluta"])
        _somar(conta, "linguagem_absoluta_recall", len(acusadas & esperadas), len(esperadas))
        _somar(conta, "linguagem_absoluta_precisao", len(acusadas & esperadas), len(acusadas))
    if "pericia" in g:
        linhas = {x["requisito_id"]: x for x in rac.get("matriz_de_prova") or []}
        certas = sum("EXPERT_EVIDENCE_NEEDED" in (linhas.get(k) or {}).get("prova_futura_necessaria", []) for k in g["pericia"])
        _somar(conta, "pericia_recall", certas, len(g["pericia"]))
    if "risco_minimo" in g:
        teses = {t["tese_id"]: t for t in rac["teses"]}
        certas = sum(teses[k]["scores"]["contradiction_risk"]["valor"] >= v for k, v in g["risco_minimo"].items())
        _somar(conta, "risco_de_contradicao_acerto", certas, len(g["risco_minimo"]))
    if g.get("limpo"):
        ruido = len(saida["achados"]) + len(rac["lacunas"])
        _somar(conta, "falsos_positivos_caso_limpo", ruido, 0)
        detalhe["ruido"] = [f"{a['codigo']}: {a['detalhe'][:80]}" for a in saida["achados"]] + [x["requisito_id"] for x in rac["lacunas"]]
    return detalhe


def rodar() -> dict[str, Any]:
    proposicoes.limpar_cache()
    conta: dict[str, list[int]] = {}
    por_caso = {}
    for caso in CASOS:
        por_caso[caso["id"]] = medir(caso, rodar_caso(caso), conta)
    metricas = {}
    for nome, (acertos, total) in sorted(conta.items()):
        metricas[nome] = acertos if nome in MENOR_E_MELHOR else (round(acertos / total, 3) if total else 1.0)
    return {"casos": len(CASOS), "metricas": metricas, "por_caso": por_caso}


def regressoes(atual: dict[str, Any], base: dict[str, Any]) -> list[str]:
    saida = []
    for nome, valor_base in base["metricas"].items():
        valor = atual["metricas"].get(nome)
        if valor is None:
            saida.append(f"{nome}: sumiu da medição")
        elif nome in MENOR_E_MELHOR and valor > valor_base:
            saida.append(f"{nome}: {valor} > {valor_base} (linha de base)")
        elif nome not in MENOR_E_MELHOR and valor < valor_base:
            saida.append(f"{nome}: {valor} < {valor_base} (linha de base)")
    return saida


def main() -> int:
    atual = rodar()
    print(json.dumps(atual, ensure_ascii=False, indent=2))
    if "--gravar" in sys.argv:
        ARQUIVO_BASE.write_text(json.dumps({"casos": atual["casos"], "metricas": atual["metricas"]}, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
        print(f"linha de base gravada em {ARQUIVO_BASE}")
        return 0
    if not ARQUIVO_BASE.exists():
        print("sem linha de base — rode com --gravar")
        return 1
    erros = regressoes(atual, json.loads(ARQUIVO_BASE.read_text(encoding="utf-8")))
    for e in erros:
        print("REGRESSÃO:", e)
    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
