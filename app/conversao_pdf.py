"""Conversão de entregas para PDF, sob demanda.

O original continua sendo a fonte da verdade. PDF volta intacto; imagem vira
uma ou mais páginas PDF sem passar novamente por OCR ou IA.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageSequence, UnidentifiedImageError


class ErroConversaoPdf(ValueError):
    """Arquivo que o conversor atual não consegue representar como PDF."""


@dataclass(frozen=True)
class PdfConvertido:
    caminho: Path
    temporario: bool
    nome_download: str


EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}

# 2400 px preserva texto pequeno para leitura e impressão, mas evita colocar no
# PDF os 12–48 megapixels inteiros de uma foto de celular.
MAX_LADO_PDF = 2400
QUALIDADE_JPEG_PDF = 82


def nome_pdf(nome_original: str, padrao: str = "documento") -> str:
    base = Path(nome_original or padrao).stem or padrao
    limpo = re.sub(r'[\\/:*?"<>|]+', "-", base).strip(" .") or padrao
    return f"{limpo}.pdf"


def converter_para_pdf(origem: Path, nome_original: str, destino: Path) -> PdfConvertido:
    ext = origem.suffix.lower()
    download = nome_pdf(nome_original)
    if ext == ".pdf":
        return PdfConvertido(origem, False, download)
    if ext not in EXTENSOES_IMAGEM:
        raise ErroConversaoPdf(
            "Este tipo de arquivo ainda não pode ser convertido para PDF. "
            "Hoje o sistema converte imagens e preserva PDFs originais."
        )

    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(origem) as imagem:
            paginas = [_preparar_pagina(frame) for frame in ImageSequence.Iterator(imagem)]
            if not paginas:
                raise ErroConversaoPdf("A imagem não contém páginas.")
            paginas[0].save(
                destino,
                format="PDF",
                save_all=len(paginas) > 1,
                append_images=paginas[1:],
                resolution=150,
                quality=QUALIDADE_JPEG_PDF,
                optimize=True,
            )
    except UnidentifiedImageError as exc:
        raise ErroConversaoPdf("Arquivo de imagem inválido ou corrompido.") from exc
    except OSError as exc:
        raise ErroConversaoPdf("Não foi possível converter a imagem para PDF.") from exc
    finally:
        for pagina in locals().get("paginas", []):
            pagina.close()
    return PdfConvertido(destino, True, download)


def _preparar_pagina(imagem: Image.Image) -> Image.Image:
    pagina = imagem.copy()
    if pagina.mode in {"RGBA", "LA", "P"}:
        fundo = Image.new("RGB", pagina.size, "white")
        if pagina.mode == "P":
            pagina = pagina.convert("RGBA")
        alpha = pagina.getchannel("A") if "A" in pagina.getbands() else None
        fundo.paste(pagina.convert("RGB"), mask=alpha)
        pagina.close()
        pagina = fundo
    if pagina.mode != "RGB":
        convertida = pagina.convert("RGB")
        pagina.close()
        pagina = convertida
    if max(pagina.size) > MAX_LADO_PDF:
        pagina.thumbnail((MAX_LADO_PDF, MAX_LADO_PDF), Image.Resampling.LANCZOS)
    return pagina
