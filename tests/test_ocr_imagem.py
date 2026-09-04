"""Qualidade da imagem que vai ao OCR: sem perda quando cabe, e DPI alto.

Duas alavancas de precisão do OCR, testadas sem tocar a API da Mistral:

  - `_codificar_para_ocr` prefere PNG (sem perda), porque reencodar em JPEG uma
    imagem já decodificada come a borda do glifo pequeno — o dígito do CPF, o
    código do CID. Só volta ao JPEG quando o PNG estoura o teto de tamanho.
  - `_escala_efetiva` rasteriza o PDF no maior DPI que cabe no teto de pixels:
    documento de uma página usa o alvo inteiro; PDF enorme é reduzido em vez de
    recusado.

Rodar: PYTHONPATH=. .venv/Scripts/python.exe tests/test_ocr_imagem.py
"""

from __future__ import annotations

import importlib
import os

import cv2
import numpy as np


def checar(condicao: bool, descricao: str) -> int:
    print(f"  {'PASS' if condicao else '>> FALHA'} {descricao}")
    return 0 if condicao else 1


def _imagem() -> np.ndarray:
    img = np.full((200, 320, 3), 240, np.uint8)
    cv2.putText(img, "CPF 12345678901", (8, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    return img


def testar_codificacao() -> int:
    falhas = 0
    from app import mistral_ocr as m

    # Padrão: PNG, e decodificável de volta.
    os.environ.pop("OCR_PNG_MAX_BYTES", None)
    m = importlib.reload(m)
    mime, dados = m._codificar_para_ocr(_imagem())
    falhas += checar(mime == "image/png", "por padrão codifica sem perda (PNG)")
    volta = cv2.imdecode(np.frombuffer(dados, np.uint8), cv2.IMREAD_COLOR)
    falhas += checar(volta is not None and volta.shape == _imagem().shape,
                     "os bytes do PNG voltam a ser uma imagem íntegra")

    # Teto minúsculo: o PNG estoura e cai para JPEG, ainda decodificável.
    os.environ["OCR_PNG_MAX_BYTES"] = "10"
    m = importlib.reload(m)
    mime, dados = m._codificar_para_ocr(_imagem())
    falhas += checar(mime == "image/jpeg", "acima do teto de tamanho, volta ao JPEG")
    falhas += checar(
        cv2.imdecode(np.frombuffer(dados, np.uint8), cv2.IMREAD_COLOR) is not None,
        "o JPEG de fallback também é uma imagem válida",
    )

    os.environ.pop("OCR_PNG_MAX_BYTES", None)
    importlib.reload(m)
    return falhas


def testar_escala() -> int:
    falhas = 0
    from app import pdf

    # Uma página A4 (595x842 pt) usa o alvo inteiro.
    escala = pdf._escala_efetiva([(595.0, 842.0)])
    falhas += checar(abs(escala - pdf.ESCALA_RENDERIZACAO) < 1e-9,
                     "documento de uma página rasteriza no DPI-alvo cheio")

    # Muitas páginas grandes: reduz para caber no teto, sem recusar.
    grandes = [(2000.0, 3000.0)] * 10
    escala = pdf._escala_efetiva(grandes)
    pixels = sum(w * h for w, h in grandes) * escala * escala
    falhas += checar(0 < escala < pdf.ESCALA_RENDERIZACAO,
                     "PDF enorme reduz a escala em vez de estourar")
    falhas += checar(pixels <= pdf.MAX_PIXELS_RENDERIZADOS + 1,
                     "a escala reduzida respeita o teto de pixels")
    return falhas


def main_teste() -> int:
    falhas = 0
    print("\ncodificação da imagem para o OCR")
    falhas += testar_codificacao()
    print("\nescala de rasterização do PDF")
    falhas += testar_escala()
    print("\nTODOS OS TESTES PASSARAM" if not falhas else f"\n{falhas} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
