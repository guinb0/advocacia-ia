"""Fachada compatível do motor único de OCR: Mistral Document AI."""

from __future__ import annotations

import numpy as np

from .extractors import Linha
from .mistral_ocr import configurada, rodar_ocr_com_tempo as _rodar_mistral


def motor_ativo() -> str:
    return "Mistral OCR"


def aquecer(lang: str = "pt") -> None:
    """Valida a configuração; a API externa não possui modelo local para aquecer."""
    del lang
    if not configurada():
        raise RuntimeError("MISTRAL_API_KEY não foi configurada")


aquecer_modelo = aquecer


def modelo_carregado() -> bool:
    return configurada()


def rodar_ocr_com_tempo(
    img_bgr: np.ndarray, lang: str = "pt"
) -> tuple[list[Linha], dict[str, float]]:
    return _rodar_mistral(img_bgr, lang)


def rodar_ocr(img_bgr: np.ndarray, lang: str = "pt") -> list[Linha]:
    linhas, _ = rodar_ocr_com_tempo(img_bgr, lang)
    return linhas
