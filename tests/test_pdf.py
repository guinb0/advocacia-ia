"""Conversão local de PDFs para a imagem que alimenta o OCR.

Rodar: .venv\\Scripts\\python.exe -m tests.test_pdf
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image

from app.pipeline import decodificar


def main() -> int:
    primeira = Image.new("RGB", (600, 800), "white")
    segunda = Image.new("RGB", (600, 800), "lightgray")
    arquivo = io.BytesIO()
    primeira.save(arquivo, format="PDF", save_all=True, append_images=[segunda], resolution=72)

    imagem = decodificar(arquivo.getvalue())
    esperado_minimo = 2 * 800 * 2  # duas páginas renderizadas em escala 2.0
    passou = imagem.ndim == 3 and imagem.shape[2] == 3 and imagem.shape[0] >= esperado_minimo
    print(f"imagem renderizada: {imagem.shape}")
    print("PASS" if passou else "FALHA")
    return 0 if passou else 1


if __name__ == "__main__":
    raise SystemExit(main())
