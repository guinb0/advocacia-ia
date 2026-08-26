"""Bancada de EXTRAÇÃO DE CAMPOS — a medida que importa, e que faltava.

POR QUE ESTA BANCADA EXISTE

A `tests/bench.py` mede tempo. Tempo não é o problema aqui: o problema é campo que
não sai, em documento que está legível a olho nu. E já houve um caso registrado de
otimização que ficou 17x mais rápida e QUEBROU a extração — foi revertida, e o
motivo apontado foi o agrupamento de linhas (`_agrupar_em_linhas`). Sem medir campo,
esse tipo de regressão só aparece semanas depois, num caso real, como "o sistema não
leu meu RG".

O QUE ELA MEDE

Para cada amostra, quantos dos campos esperados saíram e com que valor. Não afirma
qual é o valor CERTO de cada documento — as amostras não têm gabarito conferido à
mão. Ela mede o que é comparável entre duas versões do código: quantos campos a
extração encontrou, e se o conjunto mudou. É uma trava de regressão, não uma nota.

Rodar:  .venv\\Scripts\\python.exe -m tests.bench_extracao
Comparar:  ... -m tests.bench_extracao --salvar antes.json
           (mexe no código)
           ... -m tests.bench_extracao --comparar antes.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

AMOSTRAS = Path(__file__).resolve().parent / "amostras"


def medir_uma(caminho: Path) -> dict:
    from app import pipeline

    inicio = time.perf_counter()
    try:
        r = pipeline.processar(
            caminho.read_bytes(), caminho.name, gerar_arquivos_temporarios=False
        )
    except Exception as exc:  # noqa: BLE001 — a bancada não pode morrer numa amostra
        return {"erro": f"{type(exc).__name__}: {exc}", "campos": {}, "segundos": 0.0}

    campos = {
        c["nome"]: {
            "valor": str(c.get("valor") or ""),
            "confianca": round(float(c.get("confianca") or 0), 3),
        }
        for c in (r.get("campos") or [])
        if str(c.get("valor") or "").strip()
    }
    validacao = r.get("validacao") or {}
    return {
        "tipo": (r.get("tipo") or {}).get("codigo", ""),
        "campos": campos,
        "n_campos": len(campos),
        "score": validacao.get("score_legibilidade"),
        "utilizaveis": validacao.get("dados_utilizaveis"),
        # O OCR devolve BLOCOS; `campos` sai da leitura desses blocos. Ter os dois
        # lado a lado é o que separa "o OCR não leu" de "leu e a extração perdeu" —
        # e essa distinção decide onde mexer.
        "blocos": (r.get("ocr") or {}).get("blocos_detectados", 0),
        "caracteres": (r.get("ocr") or {}).get("caracteres_detectados", 0),
        "conf_ocr": (r.get("ocr") or {}).get("confianca_media"),
        "rotacao": (r.get("imagem") or {}).get("rotacao_aplicada_graus"),
        "segundos": round(time.perf_counter() - inicio, 2),
    }


def rodar() -> dict:
    resultado = {}
    for caminho in sorted(AMOSTRAS.glob("*.png")):
        print(f"  {caminho.name} …", end="", flush=True)
        r = medir_uma(caminho)
        resultado[caminho.name] = r
        if "erro" in r:
            print(f" ERRO {r['erro'][:60]}")
        else:
            print(
                f" tipo={r['tipo'] or '—':14} campos={r['n_campos']:>2}"
                f"  blocos={r['blocos']:>3}  car={r['caracteres']:>4}"
                f"  conf={r['conf_ocr']}  score={r['score']}  {r['segundos']}s"
            )
    return resultado


def comparar(antes: dict, agora: dict) -> int:
    """Diz o que mudou. Devolve o número de amostras que PIORARAM."""
    piores = 0
    print("\n--- comparação com a linha de base ---")
    for nome in sorted(set(antes) | set(agora)):
        a, b = antes.get(nome, {}), agora.get(nome, {})
        na, nb = a.get("n_campos", 0), b.get("n_campos", 0)
        ca, cb = set(a.get("campos", {})), set(b.get("campos", {}))
        perdidos, ganhos = sorted(ca - cb), sorted(cb - ca)
        # Campo que existia nos dois mas MUDOU de valor: não é ganho nem perda de
        # contagem, e é justamente onde uma contaminação de coluna se esconde.
        mudados = sorted(
            c for c in ca & cb if a["campos"][c]["valor"] != b["campos"][c]["valor"]
        )

        if not perdidos and not ganhos and not mudados:
            print(f"  = {nome:20} {nb} campo(s), igual")
            continue
        sinal = "!" if perdidos else "+"
        if perdidos:
            piores += 1
        print(f"  {sinal} {nome:20} {na} -> {nb} campo(s)")
        for c in perdidos:
            print(f"      PERDEU  {c} = {a['campos'][c]['valor'][:40]!r}")
        for c in ganhos:
            print(f"      ganhou  {c} = {b['campos'][c]['valor'][:40]!r}")
        for c in mudados:
            print(
                f"      mudou   {c}: {a['campos'][c]['valor'][:28]!r}"
                f" -> {b['campos'][c]['valor'][:28]!r}"
            )
    return piores


def main() -> int:
    args = sys.argv[1:]
    print("Extração de campos, amostra a amostra:\n")
    agora = rodar()

    total = sum(r.get("n_campos", 0) for r in agora.values())
    print(f"\n  TOTAL: {total} campos em {len(agora)} amostras")

    if "--salvar" in args:
        destino = Path(args[args.index("--salvar") + 1])
        destino.write_text(json.dumps(agora, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  linha de base gravada em {destino}")
        return 0

    if "--comparar" in args:
        origem = Path(args[args.index("--comparar") + 1])
        piores = comparar(json.loads(origem.read_text(encoding="utf-8")), agora)
        print(
            "\n  NENHUMA amostra perdeu campo."
            if not piores
            else f"\n  ATENÇÃO: {piores} amostra(s) PERDERAM campo."
        )
        return 1 if piores else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
