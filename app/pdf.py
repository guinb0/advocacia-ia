"""Conversão segura de PDFs para imagem antes do OCR."""

from __future__ import annotations

import os
import threading

import cv2
import numpy as np

# PDFium não é thread-safe. A API processa uploads em threads para não bloquear o
# event loop, então todas as renderizações passam por este único lock. Público
# (sem `_`) porque `conversao_pdf.mesclar_em_pdf` também chama a biblioteca e
# precisa do MESMO lock — dois pdfium ao mesmo tempo em threads diferentes é o
# que ele não tolera, não importa a operação.
PDFIUM_LOCK = threading.Lock()

# Quantas páginas um único PDF pode trazer, e quantos pixels a rasterização toda
# pode ocupar. Os dois andam JUNTOS, e é por isso que estão lado a lado.
#
# A CONTA, porque mexer num sem o outro não aumenta nada de verdade:
#
#   uma A4 a 180 DPI (escala 2,5) ≈ 1487 × 2105 ≈ 3,13M pixels
#   20 páginas ≈ 63M pixels ≈ 188 MB na imagem final (3 bytes por pixel)
#
# Com o teto antigo de 24M, um PDF de 20 páginas até era aceito — mas
# `_escala_efetiva` derrubava a escala para ~1,0 (≈72 DPI) para caber, e é
# exatamente aí que o OCR passa a errar dígito de CPF e código de CID. Subir o
# número de páginas sem subir o teto de pixels troca "recusa o arquivo" por
# "lê o arquivo errado", que é pior: o erro deixa de aparecer.
#
# CUSTO REAL, declarado: o laço acumula as páginas numa lista ANTES de montar a
# imagem final, então o pico é ~2× o tamanho dela (~376 MB em 20 páginas).
# `PDFIUM_LOCK` serializa as conversões, então é um pico por vez — mas ele
# divide a memória do processo com o resto da API.
#
# Ambos por variável de ambiente, como os outros tetos do projeto
# (`MAX_PAGINAS_PDF_SELECAO`, `OCR_PDF_ESCALA`): o documento que hoje não cabe é
# ajustável em produção sem novo deploy.
MAX_PAGINAS_PDF = int(os.getenv("MAX_PAGINAS_PDF", "20"))
MAX_PIXELS_RENDERIZADOS = int(os.getenv("OCR_PDF_MAX_PIXELS", str(64_000_000)))
# Escala-ALVO da rasterização. 2.5 ≈ 180 DPI: o dígito do CPF e o código do CID
# saem mais nítidos que a 144 DPI de antes, e é aí que o OCR ganha precisão. Não
# é garantia: quando o PDF é grande, `_escala_efetiva` reduz este alvo para caber
# no teto de pixels — melhor rasterizar num DPI menor do que recusar o arquivo.
ESCALA_RENDERIZACAO = float(os.getenv("OCR_PDF_ESCALA", "2.5"))
ESPACO_ENTRE_PAGINAS = 24


def _escala_efetiva(tamanhos: list[tuple[float, float]]) -> float:
    """Maior escala ≤ alvo que ainda cabe no teto de pixels do conjunto.

    Documento de uma ou duas páginas usa o alvo inteiro; só um PDF de muitas
    páginas é reduzido, e ainda assim para o maior DPI que respeita a memória —
    em vez do erro "grande demais" que devolvia o arquivo sem ler.
    """
    base_pixels = sum(largura * altura for largura, altura in tamanhos)
    if base_pixels <= 0:
        return ESCALA_RENDERIZACAO
    # pixels(escala) = base_pixels * escala² ≤ teto  →  escala ≤ sqrt(teto/base)
    teto_escala = (MAX_PIXELS_RENDERIZADOS / base_pixels) ** 0.5
    return min(ESCALA_RENDERIZACAO, teto_escala)


def pdf_para_imagem(conteudo: bytes) -> np.ndarray:
    """Rasteriza um PDF inteiro em uma imagem BGR, preservando a ordem das páginas."""
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - protegido por requirements.txt
        raise ValueError("O suporte a PDF não está instalado no servidor.") from exc

    try:
        with PDFIUM_LOCK:
            with pdfium.PdfDocument(conteudo) as documento:
                total_paginas = len(documento)
                if total_paginas == 0:
                    raise ValueError("O PDF não contém páginas.")
                if total_paginas > MAX_PAGINAS_PDF:
                    raise ValueError(
                        f"PDF com {total_paginas} páginas. O limite é de {MAX_PAGINAS_PDF} páginas por envio."
                    )

                tamanhos = [documento.get_page_size(i) for i in range(total_paginas)]
                escala = _escala_efetiva(tamanhos)

                paginas: list[np.ndarray] = []
                for indice in range(total_paginas):
                    pagina = documento[indice]
                    bitmap = None
                    try:
                        bitmap = pagina.render(scale=escala)
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
