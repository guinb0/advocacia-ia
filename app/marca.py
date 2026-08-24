"""O símbolo do escritório no cabeçalho do relatório.

Por que gerado, e não um arquivo de arte: o escritório é LARA & MELO ADVOGADOS
ASSOCIADOS (está na saudação do roteiro), e não havia logotipo no repositório.
Um emblema tipográfico — monograma e razão social numa serifada editorial —
resolve o cabeçalho hoje e fica nítido em qualquer zoom, porque é texto
rasterizado em alta resolução, não um JPG de baixa.

Quando o escritório tiver o logotipo de verdade, é só apontar `RELATORIO_LOGO`
para o PNG/JPG dele: esta função devolve esse arquivo em vez de desenhar. A
proporção é preservada no relatório, então qualquer arte serve.

A paleta é a mesma da direção visual do sistema (`--tinta`, creme, o dourado
fechado dos rótulos): marinho e creme, sóbrio, dois tons.
"""

from __future__ import annotations

import io
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

# Paleta — casa com o GUIA-LAYOUT (tinta #14202e; dourado fechado dos rótulos).
MARINHO = (20, 32, 46)
CREME = (245, 241, 232)
DOURADO = (154, 123, 63)

#: Renderiza em 3× e o Word reduz: é o que mantém a serifada sem serrilhado.
ESCALA = 3


def _fonte(nomes: list[str], tamanho: int) -> ImageFont.FreeTypeFont:
    """Primeira serifada do sistema que existir; Georgia é a preferida."""
    for nome in nomes:
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{nome}", tamanho)
        except OSError:
            continue
    return ImageFont.load_default()


def _texto_espacado(
    draw: ImageDraw.ImageDraw,
    centro_x: int,
    y: int,
    texto: str,
    fonte: ImageFont.FreeTypeFont,
    cor: tuple[int, int, int],
    tracking: int,
) -> None:
    """Desenha o texto com espaçamento entre letras, centralizado em `centro_x`.

    O PIL não tem letter-spacing; a linha `ADVOGADOS ASSOCIADOS` precisa dele
    para ler como assinatura, e não como palavra. Some as larguras, acha o
    ponto de partida e vai posicionando letra a letra.
    """
    larguras = [draw.textlength(c, font=fonte) for c in texto]
    total = sum(larguras) + tracking * (len(texto) - 1)
    x = centro_x - total / 2
    for caractere, largura in zip(texto, larguras):
        draw.text((x, y), caractere, font=fonte, fill=cor)
        x += largura + tracking


@lru_cache(maxsize=1)
def emblema_png() -> bytes:
    """PNG do cabeçalho do escritório. Cacheado: o desenho não muda entre casos.

    Se `RELATORIO_LOGO` apontar para um arquivo, ele é usado como está — é o
    gancho para o logotipo real do escritório.
    """
    externo = os.getenv("RELATORIO_LOGO", "").strip()
    if externo and os.path.isfile(externo):
        with open(externo, "rb") as arquivo:
            return arquivo.read()

    s = ESCALA
    largura = 1180 * s
    altura = 400 * s
    img = Image.new("RGBA", (largura, altura), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    centro = largura // 2

    serif_bold = _fonte(["georgiab.ttf", "timesbd.ttf", "palab.ttf"], 62 * s)
    serif = _fonte(["georgia.ttf", "times.ttf", "pala.ttf"], 25 * s)
    mono = _fonte(["georgiab.ttf", "timesbd.ttf", "palab.ttf"], 50 * s)

    # Monograma: quadrado marinho com fio dourado por dentro e "L&M" em creme.
    lado = 150 * s
    x0 = centro - lado // 2
    y0 = 20 * s
    draw.rounded_rectangle(
        [x0, y0, x0 + lado, y0 + lado], radius=10 * s, fill=MARINHO
    )
    inset = 12 * s
    draw.rounded_rectangle(
        [x0 + inset, y0 + inset, x0 + lado - inset, y0 + lado - inset],
        radius=6 * s,
        outline=DOURADO,
        width=2 * s,
    )
    caixa = draw.textbbox((0, 0), "L&M", font=mono)
    lm_w, lm_h = caixa[2] - caixa[0], caixa[3] - caixa[1]
    draw.text(
        (centro - lm_w / 2 - caixa[0], y0 + lado / 2 - lm_h / 2 - caixa[1]),
        "L&M",
        font=mono,
        fill=CREME,
    )

    # Razão social e a assinatura espaçada abaixo dela.
    nome = "LARA & MELO"
    nome_w = draw.textlength(nome, font=serif_bold)
    y_nome = y0 + lado + 26 * s
    draw.text((centro - nome_w / 2, y_nome), nome, font=serif_bold, fill=MARINHO)

    y_assinatura = y_nome + 78 * s
    _texto_espacado(
        draw, centro, y_assinatura, "ADVOGADOS ASSOCIADOS", serif, MARINHO, 10 * s
    )

    # Fio dourado sob a assinatura — fecha o emblema sem pesar.
    regua = int(largura * 0.42)
    y_regua = y_assinatura + 44 * s
    draw.line(
        [centro - regua // 2, y_regua, centro + regua // 2, y_regua],
        fill=DOURADO,
        width=2 * s,
    )

    # Corta o excesso transparente embaixo, para o emblema não trazer margem.
    recorte = img.getbbox()
    if recorte:
        img = img.crop((0, 0, largura, recorte[3] + 8 * s))

    saida = io.BytesIO()
    img.save(saida, format="PNG")
    return saida.getvalue()


def dimensao_emblema() -> tuple[int, int]:
    """(largura, altura) em px do PNG — para calcular a proporção no .docx."""
    with Image.open(io.BytesIO(emblema_png())) as img:
        return img.size


if __name__ == "__main__":  # prévia: python -m app.marca
    destino = os.path.join(os.path.dirname(__file__), "..", "tmp", "emblema.png")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "wb") as arquivo:
        arquivo.write(emblema_png())
    print("emblema em", os.path.abspath(destino), dimensao_emblema())
