"""Cliente leve do Document AI/OCR da Mistral, sem depender do SDK."""

from __future__ import annotations

import base64
import logging
import os
import time

import cv2
import httpx
import numpy as np

from . import ambiente
from .extractors import Linha

# Pelo mesmo motivo do `transcricao_openrouter`: este módulo lê `MISTRAL_API_KEY`
# do ambiente, e nem todo processo que o importa passou pelo `iniciar.ps1` — um
# worker subido à mão, ou um script. Sem a chave, `configurada()` diz que não há
# OCR e quem chama cai no caminho de reserva; o defeito aparece como documento
# ilegível, não como configuração faltando. Ver o cabeçalho de `app/ambiente.py`.
ambiente.carregar()

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


def markdown_do_pdf(conteudo: bytes, tempo_limite: float | None = None) -> str:
    """O PDF INTEIRO pela API de OCR, em markdown, uma página após a outra.

    POR QUE NÃO PASSA PELO `pdf.pdf_para_imagem`

    O caminho de documento do checklist rasteriza o PDF numa imagem só e manda
    como `image_url`. Isso serve a um RG ou a um contracheque — uma página, dois
    campos. Para um roteiro de entrevista não serve, por dois motivos:

    - `pdf.MAX_PAGINAS_PDF` recusa acima de 10 páginas, e roteiro de escritório
      passa disso. Um documento de 20 páginas nem chegaria ao OCR;
    - a imagem única perde a divisão em páginas, e o `_linhas_da_resposta`
      ainda achata os títulos (`lstrip("#")`) para caber no formato de linha do
      pipeline.

    Aqui o PDF vai como `document_url`, que é o que a API espera para documento:
    ela mesma pagina, e devolve markdown por página. O markdown é o ponto —
    título continua título e lista continua lista, e é dessa estrutura que o
    modelo tira onde um bloco do roteiro termina e o próximo começa.
    """
    chave = os.getenv("MISTRAL_API_KEY", "").strip()
    if not chave:
        raise RuntimeError("MISTRAL_API_KEY não configurada")

    dados = base64.b64encode(conteudo).decode("ascii")
    url_base = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai").rstrip("/")
    espera = tempo_limite or float(os.getenv("MISTRAL_OCR_TIMEOUT_DOC", "300"))

    inicio = time.perf_counter()
    with httpx.Client(timeout=espera) as cliente:
        resposta = cliente.post(
            f"{url_base}/v1/ocr",
            headers={"Authorization": f"Bearer {chave}"},
            json={
                "model": os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest"),
                "document": {
                    "type": "document_url",
                    "document_url": "data:application/pdf;base64," + dados,
                },
                "include_image_base64": False,
            },
        )
    resposta.raise_for_status()

    paginas = resposta.json().get("pages") or []
    textos = [str(p.get("markdown") or "").strip() for p in paginas]
    log.info(
        "Mistral OCR leu %d página(s) em %.1fs.", len(paginas), time.perf_counter() - inicio
    )
    # Duas quebras entre páginas: o modelo que monta o roteiro lê isso como
    # separação de seção, e não como uma frase que continua na linha de baixo.
    return "\n\n".join(t for t in textos if t)
