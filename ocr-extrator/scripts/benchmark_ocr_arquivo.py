"""Compara perfis de OCR em um arquivo real e conserva o resultado de cada um."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

RAIZ = Path(__file__).resolve().parents[1]
PERFIS = {
    "server_1280": {"OCR_DET_LADO_MAXIMO": "1280"},
    "server_960": {"OCR_DET_LADO_MAXIMO": "960"},
    "server_736": {"OCR_DET_LADO_MAXIMO": "736"},
    "server_1280_crop55": {
        "OCR_DET_LADO_MAXIMO": "1280",
        "OCR_COMPROVANTE_ALTURA": "0.55",
    },
    "server_1280_crop65": {
        "OCR_DET_LADO_MAXIMO": "1280",
        "OCR_COMPROVANTE_ALTURA": "0.65",
    },
    "mobile": {
        "OCR_DET_LADO_MAXIMO": "1280",
        "OCR_DETECTOR": "PP-OCRv5_mobile_det",
        "OCR_RECONHECEDOR": "latin_PP-OCRv5_mobile_rec",
    },
}


def executar(perfil: str, arquivo: Path, tipo: str, saida: Path) -> None:
    os.environ.update(PERFIS[perfil])
    sys.path.insert(0, str(RAIZ))
    from app.pipeline import processar

    inicio = time.perf_counter()
    doc = processar(
        arquivo.read_bytes(), arquivo.name, tipo_forcado=tipo,
        gerar_arquivos_temporarios=False,
    )
    resultado = {
        "perfil": perfil,
        "tempo_s": round(time.perf_counter() - inicio, 3),
        "etapas": doc["tempo_etapas_s"],
        "tentativas": doc["ocr"]["tentativas"],
        "confianca": doc["ocr"]["confianca_media"],
        "blocos": doc["ocr"]["blocos_detectados"],
        "campos": {campo["nome"]: campo["valor"] for campo in doc["campos"]},
        "texto": doc["texto_completo"],
    }
    saida.write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("arquivo", type=Path)
    parser.add_argument("--tipo", default="comprovante_residencia")
    parser.add_argument("--perfis", nargs="+", choices=PERFIS, default=list(PERFIS))
    parser.add_argument("--executar", choices=PERFIS)
    parser.add_argument("--saida", type=Path, default=RAIZ / "tmp" / "benchmark-ocr-arquivo.json")
    args = parser.parse_args()
    arquivo = args.arquivo.resolve()
    if args.executar:
        executar(args.executar, arquivo, args.tipo, args.saida)
        return 0

    resultados = []
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    for perfil in args.perfis:
        parcial = args.saida.with_name(f"{args.saida.stem}-{perfil}.json")
        print(f"[{perfil}] iniciando", flush=True)
        proc = subprocess.run([
            sys.executable, str(Path(__file__).resolve()), str(arquivo),
            "--tipo", args.tipo, "--executar", perfil, "--saida", str(parcial),
        ], cwd=RAIZ, timeout=900)
        if proc.returncode:
            raise SystemExit(proc.returncode)
        resultado = json.loads(parcial.read_text(encoding="utf-8"))
        resultados.append(resultado)
        print(f"[{perfil}] {resultado['tempo_s']}s, {len(resultado['campos'])} campos", flush=True)
    args.saida.write_text(json.dumps({"arquivo": str(arquivo), "resultados": resultados}, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
