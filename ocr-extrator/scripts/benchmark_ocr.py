"""Matriz reproduzível de velocidade e qualidade do OCR.

Cada perfil roda em processo novo porque o Paddle mantém modelo e opções em
singletons. O relatório compara tempo, confiança e valores exatos; otimização
que perde campo não pode vencer apenas por ser rápida.

Uso:
    .venv/Scripts/python scripts/benchmark_ocr.py
    .venv/Scripts/python scripts/benchmark_ocr.py --perfis baseline detector_1280
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

RAIZ = Path(__file__).resolve().parents[1]
SAIDA_PADRAO = RAIZ / "tmp" / "benchmark-ocr.json"

PERFIS: dict[str, dict[str, str]] = {
    "baseline": {"OCR_CROPS_DOCUMENTO": "0"},
    "sem_mkldnn": {"OCR_ENABLE_MKLDNN": "0"},
    "detector_1280": {"OCR_DET_LADO_MAXIMO": "1280"},
    "mobile": {"OCR_DETECTOR": "PP-OCRv5_mobile_det"},
    "sem_orientacao": {"OCR_DOC_ORIENTATION": "0", "OCR_TEXTLINE_ORIENTATION": "0"},
    "threads_16": {"OCR_CPU_THREADS": "16"},
    "recorte_documento": {"OCR_CROPS_DOCUMENTO": "1"},
}


def _executar(perfil: str, destino: Path) -> None:
    os.environ.update(PERFIS[perfil])
    sys.path.insert(0, str(RAIZ))
    from tests.test_pipeline import AMOSTRAS
    from app.pipeline import processar

    resultados = []
    # As quatro limpas cobrem layouts diferentes sem premiar uma configuração
    # especializada apenas em CNH.
    for nome, blob, tipo, obrigatorios, exatos, proibidos in AMOSTRAS[:4]:
        inicio = time.perf_counter()
        doc = processar(blob, nome, gerar_arquivos_temporarios=False)
        valores = {c["nome"]: c["valor"] for c in doc["campos"]}
        acertos = sum(valores.get(campo) == esperado for campo, esperado in exatos.items())
        total = len(exatos)
        resultados.append({
            "arquivo": nome,
            "tempo_s": round(time.perf_counter() - inicio, 3),
            "inferencia_s": round(sum(t["inferencia_s"] for t in doc["ocr"]["tentativas"]), 3),
            "confianca": doc["ocr"]["confianca_media"],
            "blocos": doc["ocr"]["blocos_detectados"],
            "tipo_correto": doc["tipo"]["codigo"] == tipo,
            "obrigatorios_ok": all(c in valores for c in obrigatorios),
            "exatos": acertos,
            "exatos_total": total,
            "proibidos_encontrados": [c for c in proibidos if c in valores],
        })
    destino.write_text(json.dumps({"perfil": perfil, "resultados": resultados}, indent=2), encoding="utf-8")


def _matriz(perfis: list[str], saida: Path) -> int:
    trabalhos = []
    for perfil in perfis:
        parcial = saida.with_name(f"{saida.stem}-{perfil}.json")
        print(f"\n[{perfil}] iniciando processo isolado", flush=True)
        inicio = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--executar", perfil, "--saida", str(parcial)],
            cwd=RAIZ,
            timeout=1800,
        )
        if proc.returncode != 0 or not parcial.exists():
            trabalhos.append({"perfil": perfil, "erro": f"processo terminou com {proc.returncode}"})
            continue
        dados = json.loads(parcial.read_text(encoding="utf-8"))
        dados["parede_s"] = round(time.perf_counter() - inicio, 2)
        trabalhos.append(dados)
        print(f"[{perfil}] concluído em {dados['parede_s']}s", flush=True)

    for trabalho in trabalhos:
        if "resultados" not in trabalho:
            continue
        rs = trabalho["resultados"]
        trabalho["resumo"] = {
            "tempo_total_s": round(sum(r["tempo_s"] for r in rs), 3),
            "inferencia_total_s": round(sum(r["inferencia_s"] for r in rs), 3),
            "confianca_media": round(sum((r["confianca"] or 0) for r in rs) / len(rs), 4),
            "valores_exatos": sum(r["exatos"] for r in rs),
            "valores_exatos_total": sum(r["exatos_total"] for r in rs),
            "todos_tipos_corretos": all(r["tipo_correto"] for r in rs),
            "todos_obrigatorios": all(r["obrigatorios_ok"] for r in rs),
            "sem_campos_proibidos": all(not r["proibidos_encontrados"] for r in rs),
        }
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps({"perfis": trabalhos}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRelatório: {saida}")
    return 0 if all("resultados" in p for p in trabalhos) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--perfis", nargs="+", choices=PERFIS, default=list(PERFIS))
    parser.add_argument("--executar", choices=PERFIS)
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    args = parser.parse_args()
    if args.executar:
        _executar(args.executar, args.saida)
        return 0
    return _matriz(args.perfis, args.saida)


if __name__ == "__main__":
    raise SystemExit(main())
