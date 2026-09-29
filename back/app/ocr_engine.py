"""Fachada compatível do motor de OCR: OpenRouter (principal) + Mistral (reserva)."""

from __future__ import annotations

import numpy as np

from .extractors import Linha
from .mistral_ocr import (
    _openrouter_disponivel,
    configurada as _mistral_configurada,
    rodar_ocr_com_tempo as _rodar_ocr,
)


def motor_ativo() -> str:
    return "OpenRouter (Gemini) + Mistral OCR (reserva)"


def aquecer(lang: str = "pt") -> None:
    """Valida a configuração; a API externa não possui modelo local para aquecer."""
    del lang
    if not _openrouter_disponivel() and not _mistral_configurada():
        raise RuntimeError(
            "Nenhum motor de OCR configurado: falta OPENROUTER_API_KEY e MISTRAL_API_KEY."
        )


aquecer_modelo = aquecer


def modelo_carregado() -> bool:
    return _openrouter_disponivel() or _mistral_configurada()


def rodar_ocr_com_tempo(
    img_bgr: np.ndarray, lang: str = "pt"
) -> tuple[list[Linha], dict[str, float]]:
    return _rodar_ocr(img_bgr, lang)


def rodar_ocr(img_bgr: np.ndarray, lang: str = "pt") -> list[Linha]:
    linhas, _ = rodar_ocr_com_tempo(img_bgr, lang)
    return linhas
