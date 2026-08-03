"""Conversão segura de PDFs para imagem antes do OCR."""

from __future__ import annotations

import threading

import cv2
import numpy as np

# PDFium não é thread-safe. A API processa uploads em threads para não bloquear o
# event loop, então todas as renderizações passam por este único lock.
_PDFIUM_LOCK = threading.Lock()

MAX_PAGINAS_PDF = 10
MAX_PIXELS_RENDERIZADOS = 24_000_000
ESCALA_RENDERIZACAO = 2.0  # 144 DPI: legível para OCR sem inflar excessivamente a memória.
ESPACO_ENTRE_PAGINAS = 24


def pdf_para_imagem(conteudo: bytes) -> np.ndarray:
    """Rasteriza um PDF inteiro em uma imagem BGR, preservando a ordem das páginas."""
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - protegido por requirements.txt
        raise ValueError("O suporte a PDF não está instalado no servidor.") from exc

    try:
        with _PDFIUM_LOCK:
            with pdfium.PdfDocument(conteudo) as documento:
                total_paginas = len(documento)
                if total_paginas == 0:
                    raise ValueError("O PDF não contém páginas.")
                if total_paginas > MAX_PAGINAS_PDF:
                    raise ValueError(
                        f"PDF com {total_paginas} páginas. O limite é de {MAX_PAGINAS_PDF} páginas por envio."
                    )

                pixels_estimados = sum(
                    int(largura * ESCALA_RENDERIZACAO) * int(altura * ESCALA_RENDERIZACAO)
                    for largura, altura in (documento.get_page_size(i) for i in range(total_paginas))
                )
                if pixels_estimados > MAX_PIXELS_RENDERIZADOS:
                    raise ValueError(
                        "O PDF é grande demais para conversão segura. Reduza a resolução ou divida o arquivo."
                    )

                paginas: list[np.ndarray] = []
                for indice in range(total_paginas):
                    pagina = documento[indice]
                    bitmap = None
                    try:
                        bitmap = pagina.render(scale=ESCALA_RENDERIZACAO)
                        raster = bitmap.to_numpy()
                        if raster.ndim == 2:
                            imagem = cv2.cvtColor(raster, cv2.COLOR_GRAY2BGR)
                        elif raster.ndim == 3 and raster.shape[2] >= 3:
                            # O padrão do PDFium é BGR; o quarto canal, quando existe,
                            # é alpha ou preenchimento e não é necessário ao OpenCV.
                            imagem = raster[:, :, :3].copy()
                        else:
                            raise ValueError(f"Não foi possível converter a página {indice + 1} do PDF.")
                        paginas.append(imagem)
                    finally:
                        if bitmap is not None:
                            bitmap.close()
                        pagina.close()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("PDF inválido, protegido por senha ou corrompido.") from exc

    largura = max(imagem.shape[1] for imagem in paginas)
    altura = sum(imagem.shape[0] for imagem in paginas) + ESPACO_ENTRE_PAGINAS * (len(paginas) - 1)
    imagem_final = np.full((altura, largura, 3), 255, dtype=np.uint8)

    y = 0
    for imagem in paginas:
        x = (largura - imagem.shape[1]) // 2
        h, w = imagem.shape[:2]
        imagem_final[y : y + h, x : x + w] = imagem
        y += h + ESPACO_ENTRE_PAGINAS
    return imagem_final
