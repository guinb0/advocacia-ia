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


def mesclar_em_pdf(
    origens: list[tuple[Path, str]], destino: Path, *, limite_paginas: int
) -> int:
    """Junta vários arquivos (PDF ou imagem) num único PDF, na ordem dada.

    Cada imagem passa por `converter_para_pdf` antes — a mesma conversão do
    botão "baixar como PDF" de uma entrega —, e o PDF resultante (ou o original,
    se já for PDF) tem suas páginas importadas para um documento novo. Ao final
    sobra um único arquivo, na ordem em que os originais foram passados.

    O pdfium não é thread-safe: cada chamada à biblioteca aqui passa pelo MESMO
    lock que protege a rasterização do OCR (`app.pdf.PDFIUM_LOCK`), senão duas
    exportações ao mesmo tempo corrompem uma a outra.

    Devolve o total de páginas do PDF final. `ErroConversaoPdf` se algum
    arquivo não puder entrar (tipo não suportado, ou a própria conversão
    falhar), ou se a soma de páginas passar do limite — um PDF de centenas de
    páginas não é o caso de uso desta função.
    """
    import pypdfium2 as pdfium

    from . import pdf as pdf_mod

    destino.parent.mkdir(parents=True, exist_ok=True)
    temporarios: list[Path] = []
    combinado = pdfium.PdfDocument.new()
    try:
        total_paginas = 0
        for indice, (origem, nome_original) in enumerate(origens):
            ext = origem.suffix.lower()
            if ext == ".pdf":
                caminho_pdf = origem
            elif ext in EXTENSOES_IMAGEM:
                tmp = destino.with_name(f"{destino.stem}-parte-{indice}.pdf")
                converter_para_pdf(origem, nome_original, tmp)
                temporarios.append(tmp)
                caminho_pdf = tmp
            else:
                raise ErroConversaoPdf(
                    f"'{nome_original}' não pode entrar no PDF combinado — hoje "
                    "só PDF e imagem são aceitos nesse formato."
                )

            with pdf_mod.PDFIUM_LOCK:
                with pdfium.PdfDocument(str(caminho_pdf)) as parte:
                    n = len(parte)
                    if n == 0:
                        continue
                    if total_paginas + n > limite_paginas:
                        raise ErroConversaoPdf(
                            f"A seleção passa de {limite_paginas} páginas combinadas. "
                            "Baixe em partes menores."
                        )
                    combinado.import_pages(parte)
                    total_paginas += n

        if total_paginas == 0:
            raise ErroConversaoPdf("Nenhum arquivo pôde ser combinado em PDF.")

        with pdf_mod.PDFIUM_LOCK:
            combinado.save(str(destino))
    finally:
        combinado.close()
        for tmp in temporarios:
            tmp.unlink(missing_ok=True)

    return total_paginas


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
