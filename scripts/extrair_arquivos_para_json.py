"""Executa o OCR Mistral em arquivos locais e grava um lote JSON temporario.

O texto extraido nao e impresso no terminal porque pode conter dados pessoais.
Este utilitario e usado por importacoes administrativas controladas.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.pipeline import TMP_DIR, processar


def executar(arquivos: list[Path], destino: Path) -> None:
    resultados: list[dict] = []
    for arquivo in arquivos:
        resultado = processar(arquivo.read_bytes(), arquivo.name)
        resultado.pop("arquivos_temporarios", None)
        resultados.append(resultado)

        # O pipeline cria previews temporarios por padrao. O lote abaixo ja e a copia
        # transitoria necessaria para a importacao, entao evitamos duplicar dado pessoal.
        identificador = resultado["id"]
        for extensao in ("json", "xml"):
            (TMP_DIR / f"{identificador}.{extensao}").unlink(missing_ok=True)

    temporario = destino.with_suffix(destino.suffix + ".tmp")
    temporario.write_text(
        json.dumps(resultados, ensure_ascii=False), encoding="utf-8"
    )
    temporario.replace(destino)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destino", type=Path, required=True)
    parser.add_argument("arquivos", nargs="+", type=Path)
    argumentos = parser.parse_args()

    ausentes = [str(path) for path in argumentos.arquivos if not path.is_file()]
    if ausentes:
        parser.error(f"arquivo(s) nao encontrado(s): {', '.join(ausentes)}")

    executar(argumentos.arquivos, argumentos.destino)
    print(json.dumps({"processados": len(argumentos.arquivos)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
