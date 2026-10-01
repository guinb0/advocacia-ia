"""Benchmark real: mede, sobre os casos anonimizados de `benchmark_real/casos/` (ver `extrair_casos.py`), o quanto a peça
gerada ficou longe da que o advogado aprovou — ANTES — e o que o motor jurídico acha do mesmo insumo — DEPOIS.

    cd back
    python -m benchmark_real.rodar            # ANTES: versão gerada × aprovada; sem rede, sem banco
    python -m benchmark_real.rodar --motor    # + DEPOIS: roda o motor (issue spotting, prova, contrateses) — usa o LLM

Nunca chama `peticao_local.gerar` (que grava no banco). O DEPOIS usa o `plano_estruturado` e o `case_brief` gravados
na versão gerada como insumo; os documentos do caso não são relidos (a extração não leva OCR), então a matriz de
fatos do motor é mais pobre que a da produção — o DEPOIS é uma estimativa conservadora.

Métricas (todas por caso e agregadas em `benchmark_real/resultados/<data>.json`, pasta fora do repositório):
- tese_recall / tese_precisao: tópicos da fundamentação aprovada que a peça (ou o motor) trouxe / que sobreviveram;
- pedidos_faltantes / pedidos_excedentes: pedidos que o advogado acrescentou / retirou;
- autoridades_removidas: citações da peça gerada que o advogado tirou (proxy de autoridade inválida ou imprópria);
- autoridades_acrescentadas: citações que só a aprovada tem (autoridade que faltou);
- fatos_corrigidos: datas e valores dos fatos gerados que não ficaram na aprovada (proxy de erro factual);
- valor_causa_divergencia: diferença relativa do valor da causa (proxy de erro de cálculo);
- contradicoes_sinalizadas: pendências de contradição que a geração levantou;
- reescrita: quanto do texto foi reescrito (1 − semelhança), por seção;
- DEPOIS: tempo e tokens do motor, lacunas, contrateses vulneráveis, e os achados dos auditores do motor na peça gerada
  × na aprovada (o auditor bom acha menos problema na versão que o advogado aprovou).
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

from app.juridico import autoridades as aut

PASTA = Path(__file__).resolve().parent
CASOS = PASTA / "casos"
RESULTADOS = PASTA / "resultados"
_VAZIAS = {"de", "da", "do", "das", "dos", "e", "a", "o", "as", "os", "em", "por", "para", "ao", "aos", "na", "no", "nas", "nos"}
_TITULO = re.compile(r"^\s*(#{1,6}\s*|(?:[IVXLC]+|\d+(?:\.\d+)*)\s*[-–—.)]\s*)")
_ITEM = re.compile(r"^\s*(?:[a-z]{1,2}|\d{1,3})\s*[).\-–]\s+|^\s*[-•*]\s+", re.I)
_DINHEIRO = re.compile(r"R\$\s*([\d.]+,\d{2})")
_DATA = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")


def _norm(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", texto)


def _tokens(texto: str) -> set[str]:
    return {t for t in _norm(texto).split() if t not in _VAZIAS and len(t) > 2}


def _secao(secoes: list[dict[str, Any]], *codigos: str) -> str:
    return "\n".join(s.get("content") or "" for s in secoes if s.get("code") in codigos)


def topicos(texto: str) -> list[set[str]]:
    """Subtítulos da fundamentação: numerados, em markdown ou em caixa alta, curtos e sem ponto final."""
    saida = []
    for linha in texto.splitlines():
        crua = linha.strip().strip("*_")
        if not 4 <= len(crua) <= 140 or crua.endswith((".", ";", ":")) and not _TITULO.match(crua):
            continue
        letras = [c for c in crua if c.isalpha()]
        if _TITULO.match(crua) or (letras and sum(c.isupper() for c in letras) / len(letras) >= 0.7):
            toks = _tokens(_TITULO.sub("", crua))
            if toks:
                saida.append(toks)
    return saida


def pedidos(texto: str) -> list[set[str]]:
    return [toks for linha in texto.splitlines() if _ITEM.match(linha) and (toks := _tokens(_ITEM.sub("", linha)))]


def _casa(a: set[str], b: set[str]) -> bool:
    return bool(a and b) and len(a & b) / min(len(a), len(b)) >= 0.6


def _cobertos(alvo: list[set[str]], candidatos: list[set[str]]) -> int:
    return sum(any(_casa(x, y) for y in candidatos) for x in alvo)


def _razao(acertos: int, total: int) -> float | None:
    return round(acertos / total, 3) if total else None


def _valor(texto: str) -> float | None:
    m = _DINHEIRO.search(texto)
    return float(m.group(1).replace(".", "").replace(",", ".")) if m else None


def _chaves(texto: str) -> set[str]:
    return {c.chave for c in aut.extrair_citacoes(texto) if c.tipo != "processo"}


def medir_antes(caso: dict[str, Any]) -> dict[str, Any]:
    g, a = caso["gerada"]["secoes"], caso["aprovada"]["secoes"]
    top_g, top_a = topicos(_secao(g, "LEGAL_GROUNDS")), topicos(_secao(a, "LEGAL_GROUNDS"))
    ped_g, ped_a = pedidos(_secao(g, "CLAIMS")), pedidos(_secao(a, "CLAIMS"))
    cit_g, cit_a = _chaves("\n".join(s["content"] for s in g)), _chaves("\n".join(s["content"] for s in a))
    fatos_g, fatos_a = _secao(g, "FACTS"), _secao(a, "FACTS")
    marcas_g = set(_DATA.findall(fatos_g)) | set(_DINHEIRO.findall(fatos_g))
    marcas_a = set(_DATA.findall(fatos_a)) | set(_DINHEIRO.findall(fatos_a))
    v_g, v_a = _valor(_secao(g, "VALUE")), _valor(_secao(a, "VALUE"))
    por_codigo_a = {s["code"]: s["content"] for s in a}
    reescrita = {s["code"]: round(1 - difflib.SequenceMatcher(None, s["content"], por_codigo_a.get(s["code"], "")).ratio(), 3)
                 for s in g if s["content"].strip()}
    return {
        "tese_recall": _razao(_cobertos(top_a, top_g), len(top_a)),
        "tese_precisao": _razao(_cobertos(top_g, top_a), len(top_g)),
        "pedidos_faltantes": len(ped_a) - _cobertos(ped_a, ped_g),
        "pedidos_excedentes": len(ped_g) - _cobertos(ped_g, ped_a),
        "autoridades_removidas": _razao(len(cit_g - cit_a), len(cit_g)),
        "autoridades_acrescentadas": len(cit_a - cit_g),
        "fatos_corrigidos": _razao(len(marcas_g - marcas_a), len(marcas_g)),
        "valor_causa_divergencia": round(abs(v_g - v_a) / v_a, 3) if v_g is not None and v_a else None,
        "contradicoes_sinalizadas": sum("contradi" in str(p).lower() for p in caso["gerada"].get("pendencias") or []),
        "reescrita": reescrita,
        "_topicos_aprovados": [sorted(t) for t in top_a],
    }


def medir_depois(caso: dict[str, Any], llm: Any, textos_skill: dict[str, str]) -> dict[str, Any]:
    from app.juridico import contrateses, orquestrador, proposicoes, teses  # noqa: PLC0415

    plano = caso["gerada"].get("plano_estruturado") or {}
    brief = caso["gerada"].get("case_brief") or {}
    fontes = [{"tipo": "documento", "nome": "case_brief", "texto": json.dumps(brief, ensure_ascii=False)}]
    contexto = json.dumps({"case_brief": brief, "outline": caso["gerada"].get("outline")}, ensure_ascii=False)[:60_000]
    t0 = time.monotonic()
    prep = orquestrador.analisar(plano_est=plano, contexto_caso=contexto, fontes=fontes, llm=llm, textos_skill=textos_skill,
                                 data_referencia=date.today(), llm_contrateses=llm)
    duracao = round(time.monotonic() - t0, 1)
    rac = prep["raciocinio"]
    incluidas = [t for t in rac["teses"] if t["decisao"] == teses.INCLUIR]
    top_motor = [_tokens(t["tese"]) for t in incluidas]
    top_a = [set(t) for t in medir_antes(caso)["_topicos_aprovados"]]

    def achados(secoes: list[dict[str, Any]]) -> int:
        return len(contrateses.auditar(secoes, rac)["achados"]) + len(proposicoes.auditar_certeza(secoes, rac)["achados"])

    etapas = prep["rastro"].etapas
    return {
        "tese_recall": _razao(_cobertos(top_a, top_motor), len(top_a)),
        "tese_precisao": _razao(_cobertos(top_motor, top_a), len(top_motor)),
        "lacunas": len(rac.get("lacunas") or []),
        "contrateses_vulneraveis": sum(c["vulneravel"] for t in rac["teses"] for c in t.get("contrateses") or []),
        "achados_na_gerada": achados(caso["gerada"]["secoes"]),
        "achados_na_aprovada": achados(caso["aprovada"]["secoes"]),
        "falhas_do_motor": rac.get("falhas") or [],
        "tempo_s": duracao,
        "tokens_aprox": sum(e.get("tokens_entrada_aprox", 0) + e.get("tokens_saida_aprox", 0) for e in etapas),
    }


def agregar(por_caso: dict[str, dict[str, Any]], lado: str) -> dict[str, float]:
    soma: dict[str, list[float]] = {}
    for m in por_caso.values():
        for nome, valor in (m.get(lado) or {}).items():
            if nome.startswith("_") or isinstance(valor, (dict, list, str)) or valor is None:
                continue
            soma.setdefault(nome, []).append(float(valor))
        if lado == "antes" and m.get("antes", {}).get("reescrita"):
            soma.setdefault("reescrita_media", []).append(sum(m["antes"]["reescrita"].values()) / len(m["antes"]["reescrita"]))
    return {k: round(sum(v) / len(v), 3) for k, v in sorted(soma.items())}


def _llm_do_motor() -> Any:
    from app import peticao_local  # noqa: PLC0415 - só o DEPOIS precisa do cliente do modelo

    return peticao_local._llm_raciocinio(300.0)  # noqa: SLF001


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--motor", action="store_true", help="roda também o motor jurídico (usa o LLM configurado)")
    args = ap.parse_args()
    arquivos = sorted(CASOS.glob("*.json"))
    if not arquivos:
        print(f"sem casos em {CASOS} — rode antes `python -m benchmark_real.extrair_casos`")
        return 1
    llm = textos = None
    if args.motor:
        from app.juridico import teses  # noqa: PLC0415

        llm, textos = _llm_do_motor(), teses.textos_da_skill_ativa()
    por_caso: dict[str, dict[str, Any]] = {}
    for arq in arquivos:
        caso = json.loads(arq.read_text(encoding="utf-8"))
        m: dict[str, Any] = {"categoria": caso.get("categoria"), "antes": medir_antes(caso)}
        if args.motor:
            try:
                m["depois"] = medir_depois(caso, llm, textos or {})
            except Exception as erro:  # noqa: BLE001 - um caso ruim não derruba o benchmark
                m["depois"] = {"erro": f"{type(erro).__name__}: {str(erro)[:200]}"}
        por_caso[caso["id"]] = m
    resultado = {"data": date.today().isoformat(), "casos": len(por_caso), "antes": agregar(por_caso, "antes"),
                 "depois": agregar(por_caso, "depois") if args.motor else None, "por_caso": por_caso}
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    destino = RESULTADOS / f"{resultado['data']}{'-motor' if args.motor else ''}.json"
    destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: resultado[k] for k in ("casos", "antes", "depois")}, ensure_ascii=False, indent=2))
    print(f"detalhe por caso em {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
