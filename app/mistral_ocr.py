"""Cliente leve do Document AI/OCR da Mistral, sem depender do SDK."""

from __future__ import annotations

import base64
import logging
import os
import time

import cv2
import httpx
import numpy as np

from .extractors import Linha

log = logging.getLogger("ocr.mistral")


def configurada() -> bool:
    return bool(os.getenv("MISTRAL_API_KEY", "").strip())


def _linhas_da_resposta(dados: dict) -> list[Linha]:
    linhas: list[Linha] = []
    y = 0.0
    for pagina in dados.get("pages") or []:
        scores = pagina.get("confidence_scores") or {}
        try:
            confianca = min(1.0, max(0.0, float(scores.get("average_page_confidence_score", 1.0))))
        except (TypeError, ValueError):
            confianca = 1.0
        for texto in str(pagina.get("markdown") or "").splitlines():
            texto = texto.strip().lstrip("#").strip()
            if not texto:
                continue
            linhas.append(Linha(texto, confianca, y, 0.0, float(len(texto)), 1.0))
            y += 1.0
        y += 10.0
    return linhas


def rodar_ocr_com_tempo(
    img_bgr: np.ndarray, lang: str = "pt"
) -> tuple[list[Linha], dict[str, float]]:
    """Envia uma imagem à API OCR e devolve o formato interno do pipeline."""
    del lang  # O modelo é multilíngue e detecta o idioma automaticamente.
    chave = os.getenv("MISTRAL_API_KEY", "").strip()
    if not chave:
        raise RuntimeError("MISTRAL_API_KEY não configurada")
    ok, codificada = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 94])
    if not ok:
        raise RuntimeError("Não foi possível preparar a imagem para o OCR da Mistral")

    inicio = time.perf_counter()
    payload = {
        "model": os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest"),
        "document": {
            "type": "image_url",
            "image_url": "data:image/jpeg;base64," + base64.b64encode(codificada.tobytes()).decode("ascii"),
        },
        "include_blocks": True,
        "confidence_scores_granularity": "page",
        "include_image_base64": False,
    }
    url_base = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai").rstrip("/")
    with httpx.Client(timeout=float(os.getenv("MISTRAL_OCR_TIMEOUT", "90"))) as cliente:
        resposta = cliente.post(
            f"{url_base}/v1/ocr",
            headers={"Authorization": f"Bearer {chave}"},
            json=payload,
        )
    resposta.raise_for_status()
    inferencia = time.perf_counter() - inicio
    linhas = _linhas_da_resposta(resposta.json())
    total = time.perf_counter() - inicio
    log.info("Mistral OCR concluído em %.2fs (%d linhas).", total, len(linhas))
    return linhas, {"fila_s": 0.0, "inferencia_s": inferencia,
                    "pos_processamento_s": total - inferencia, "total_s": total}
