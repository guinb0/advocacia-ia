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

# Teto de PÁGINAS: acima disso o arquivo é recusado antes de gastar tempo
# rasterizando. O teto de PIXELS abaixo continua sendo quem protege a memória
# dentro desse limite — `_escala_efetiva` derruba o DPI para o documento
# inteiro caber nele, em vez de recusar o arquivo. Rasterizar num DPI menor é
# pior para o OCR (mais chance de errar dígito de CPF ou código de CID) mas
# ainda lê algo; recusar não lê nada.
MAX_PAGINAS = int(os.getenv("OCR_PDF_MAX_PAGINAS", "350"))
#
# A CONTA, para dimensionar o teto de pixels:
#
#   uma A4 a 180 DPI (escala 2,5) ≈ 1487 × 2105 ≈ 3,13M pixels
#   20 páginas nesse DPI ≈ 63M pixels ≈ 188 MB na imagem final (3 bytes/pixel)
#
# CUSTO REAL, declarado: o laço acumula as páginas numa lista ANTES de montar a
# imagem final, então o pico é ~2× o tamanho dela. `PDFIUM_LOCK` serializa as
# conversões, então é um pico por vez — mas ele divide a memória do processo
# com o resto da API. Um documento de centenas de páginas ainda cabe no teto de
# pixels (a escala só cai), então o pico de memória não cresce com a página —
# cresce só se o teto de pixels for aumentado.
#
# Por variável de ambiente, como os outros tetos do projeto (`OCR_PDF_ESCALA`):
# ajustável em produção sem novo deploy.
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
    return empilhar_paginas(pdf_para_paginas(conteudo))


def pdf_para_paginas(conteudo: bytes) -> list[np.ndarray]:
    """Cada página do PDF como uma imagem BGR própria, na ordem do documento.

    O OCR precisa delas SEPARADAS: `quality.preparar_para_ocr` reduz a imagem
    para caber em 2000 px no lado maior, e na pilha única de um PDF de dez
    páginas isso deixava cada página com ~200 px de altura — ilegível, e o texto
    simplesmente não saía.
    """
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
                if total_paginas > MAX_PAGINAS:
                    raise ValueError(
                        f"O PDF tem {total_paginas} páginas; o limite é {MAX_PAGINAS}."
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
    return paginas


def empilhar_paginas(paginas: list[np.ndarray]) -> np.ndarray:
    """Junta as páginas numa imagem só, uma embaixo da outra, centralizadas."""
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


#: Média de caracteres por página abaixo da qual o "texto nativo" é
#: watermark/rodapé, não o corpo do documento — a página real ainda é uma
#: digitalização embutida, e rasterizar+OCR continua sendo o caminho certo.
#: Um PDF do portal do INSS ou da Justiça tem centenas de caracteres por
#: página; um PDF escaneado com OCR já embutido pelo scanner às vezes carrega
#: metadado esparso que não chega perto disso.
MIN_CARACTERES_POR_PAGINA_NATIVA = int(os.getenv("PDF_MIN_CARACTERES_POR_PAGINA", "60"))


def extrair_texto_nativo(conteudo: bytes) -> str:
    """O texto JÁ DIGITAL de um PDF, ou string vazia se ele não tiver (ou for pouco).

    PDF gerado por sistema (protocolo do INSS, petição, portal da Justiça) já
    tem o texto gravado — rasterizar a página inteira e mandar para o OCR
    joga fora essa fidelidade e ainda arrisca errar dígito de número de
    processo ou CID que já estava perfeito no arquivo. Aqui não há CUSTO de
    render nem chamada de API: é leitura direta do PDF, e o teto de páginas
    de `pdf_para_imagem` não se aplica — não existe pixel a limitar.

    Vazio (string vazia) é o sinal para `tasks/ocr.py` cair no caminho de
    sempre (rasterizar + OCR): PDF sem camada de texto (foto virou PDF) ou
    com só metadado esparso continua precisando de OCR de verdade.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return ""

    try:
        with PDFIUM_LOCK:
            with pdfium.PdfDocument(conteudo) as documento:
                textos = []
                for pagina in documento:
                    pagina_texto = pagina.get_textpage()
                    try:
                        textos.append(pagina_texto.get_text_range().strip())
                    finally:
                        pagina_texto.close()
                        pagina.close()
    except Exception:
        return ""

    if not textos:
        return ""
    total_chars = sum(len(t) for t in textos)
    if total_chars < MIN_CARACTERES_POR_PAGINA_NATIVA * len(textos):
        return ""
    # Duas quebras entre páginas: o mesmo critério de `mistral_ocr.markdown_do_pdf`
    # — o que lê depois precisa saber onde uma página termina e a outra começa.
    return "\n\n".join(t for t in textos if t)
