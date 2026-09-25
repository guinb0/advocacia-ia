"""Funções de imagem compartilhadas pela skill organizar-documentos.

Nada aqui altera o conteúdo do documento: só giro, corte de bordas,
endireitamento e ajuste de contraste. Carimbos, marcas d'água, anotações e
rasuras são preservados por construção.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageOps

# --------------------------------------------------------------------------
# Constantes
# --------------------------------------------------------------------------

DPI_PADRAO = 200
A4_PX = (1654, 2339)  # A4 a 200 dpi
INCLINACAO_MAX = 10.0  # graus; acima disso é página torta, não é skew de scanner
LIMIAR_BRANCO = 0.995  # proporção de pixels claros para considerar página em branco
LIMIAR_NITIDEZ = 60.0  # variância do laplaciano abaixo disso = possível borrão
LADO_MINIMO_OK = 1000  # px no menor lado; abaixo disso, resolução baixa
USAR_OSD = True  # detecção de orientação; desligue em lotes grandes (é o passo mais lento)


# --------------------------------------------------------------------------
# Carregamento e identidade
# --------------------------------------------------------------------------

def carregar(caminho) -> Image.Image:
    """Abre a imagem, corrige a rotação EXIF e devolve em RGB."""
    img = Image.open(caminho)
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def _cinza(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)


def hash_conteudo(img: Image.Image) -> str:
    """Hash do conteúdo visual, insensível a tamanho e compressão.

    Duas fotos da mesma página, tiradas duas vezes, batem aqui. Frente e verso
    do mesmo cartão, não.
    """
    g = cv2.resize(_cinza(img), (64, 64), interpolation=cv2.INTER_AREA)
    g = cv2.normalize(g, None, 0, 255, cv2.NORM_MINMAX)
    return hashlib.md5(g.astype(np.uint8).tobytes()).hexdigest()


def dhash(img: Image.Image) -> int:
    """Hash perceptual para duplicidade aproximada (mesma página reescaneada)."""
    g = cv2.resize(_cinza(img), (9, 8), interpolation=cv2.INTER_AREA)
    bits = g[:, 1:] > g[:, :-1]
    valor = 0
    for bit in bits.flatten():
        valor = (valor << 1) | int(bit)
    return valor


def distancia_hash(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# --------------------------------------------------------------------------
# Medição / diagnóstico
# --------------------------------------------------------------------------

def detectar_giro(img: Image.Image):
    """Giro sugerido pelo Tesseract OSD, em graus horários (0/90/180/270).

    Devolve (graus, confianca) ou (None, 0.0) quando não há texto suficiente.
    O resultado é PISTA, não veredito: página com pouco texto engana o OSD.
    """
    if not USAR_OSD:
        return None, 0.0
    try:
        import pytesseract

        dados = pytesseract.image_to_osd(
            np.array(img), config="--psm 0", output_type=pytesseract.Output.DICT
        )
        # O OSD devolve o giro em sentido ANTI-horário; a skill trabalha em
        # sentido horário, então convertemos aqui.
        rotate = int(dados.get("rotate", 0)) % 360
        return (360 - rotate) % 360, float(dados.get("orientation_conf", 0))
    except Exception:
        return None, 0.0


def medir_inclinacao(img: Image.Image) -> float:
    """Inclinação em graus (positivo = horário). Zero quando não dá para medir."""
    g = _cinza(img)
    g = cv2.bitwise_not(g)
    _, bin_ = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    coords = cv2.findNonZero(bin_)
    if coords is None or len(coords) < 50:
        return 0.0
    angulo = cv2.minAreaRect(coords)[-1]
    if angulo < -45:
        angulo += 90
    elif angulo > 45:
        angulo -= 90
    return round(float(angulo), 2)


def medir(img: Image.Image) -> dict:
    """Diagnóstico da página. Todos os campos são pistas para conferência visual."""
    g = _cinza(img)
    largura, altura = img.size
    nitidez = float(cv2.Laplacian(g, cv2.CV_64F).var())
    brilho = float(g.mean())
    contraste = float(g.std())
    claros = float((g > 235).mean())
    inclinacao = medir_inclinacao(img)
    giro, conf = detectar_giro(img)

    alertas = []
    if claros >= LIMIAR_BRANCO:
        alertas.append("possível página em branco")
    if nitidez < LIMIAR_NITIDEZ:
        alertas.append("possível borrão / foco ruim")
    if brilho < 70:
        alertas.append("muito escura")
    if brilho > 248 and contraste < 35:
        alertas.append("estourada / lavada")
    if contraste < 18:
        alertas.append("contraste baixo")
    if min(largura, altura) < LADO_MINIMO_OK:
        alertas.append("resolução baixa")
    if giro:
        alertas.append(f"OSD sugere girar {giro}° (conf. {conf:.1f})")
    if abs(inclinacao) > 1.0:
        alertas.append(f"torta ~{inclinacao}°")
    if altura < largura:
        alertas.append("página deitada (paisagem)")

    return {
        "largura": largura,
        "altura": altura,
        "nitidez": round(nitidez, 1),
        "brilho": round(brilho, 1),
        "contraste": round(contraste, 1),
        "branco": claros >= LIMIAR_BRANCO,
        "inclinacao": inclinacao,
        "giro_osd": giro,
        "conf_osd": round(conf, 1),
        "alertas": alertas,
    }


# --------------------------------------------------------------------------
# Tratamento
# --------------------------------------------------------------------------

def girar(img: Image.Image, graus: int) -> Image.Image:
    graus = int(graus) % 360
    if graus == 0:
        return img
    if graus not in (90, 180, 270):
        raise ValueError("girar aceita apenas 0, 90, 180 ou 270 (horário)")
    # PIL gira no anti-horário; convertemos para horário
    return img.rotate(-graus, expand=True)


def remover_moldura(img: Image.Image) -> Image.Image:
    """Corta a moldura escura do scanner, se houver. Conservador por padrão."""
    g = _cinza(img)
    mascara = (g > 45).astype(np.uint8)
    coords = cv2.findNonZero(mascara)
    if coords is None:
        return img
    x, y, w, h = cv2.boundingRect(coords)
    area_original = img.size[0] * img.size[1]
    if w * h < 0.30 * area_original:  # corte agressivo demais: provavelmente erro
        return img
    if w * h > 0.995 * area_original:  # não há moldura relevante
        return img
    return img.crop((x, y, x + w, y + h))


def endireitar(img: Image.Image, limite: float = INCLINACAO_MAX) -> Image.Image:
    angulo = medir_inclinacao(img)
    if abs(angulo) < 0.3 or abs(angulo) > limite:
        return img
    arr = np.array(img)
    h, w = arr.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angulo, 1.0)
    girada = cv2.warpAffine(
        arr, m, (w, h), flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return Image.fromarray(girada)


def _regiao_papel(img: Image.Image):
    """Tenta isolar a folha (região clara e grande) numa foto com fundo.

    Devolve (x0, y0, x1, y1) ou None quando não encontra uma folha plausível.
    Fotos de celular quase sempre trazem cama, mesa ou papéis vizinhos: sem
    isso, o documento entra minúsculo dentro do A4.
    """
    g = _cinza(img)
    g = cv2.GaussianBlur(g, (7, 7), 0)
    _, papel = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    papel = cv2.morphologyEx(papel, cv2.MORPH_CLOSE, np.ones((35, 35), np.uint8))
    papel = cv2.morphologyEx(papel, cv2.MORPH_OPEN, np.ones((25, 25), np.uint8))
    contornos, _ = cv2.findContours(papel, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return None
    W, H = img.size
    maior = max(contornos, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(maior)
    proporcao = (w * h) / float(W * H)
    if not (0.18 <= proporcao <= 0.97):
        return None
    if min(w, h) < 0.25 * min(W, H):  # faixa fina: não é a folha
        return None

    # TRAVA DE SEGURANÇA: a caixa só vale se contiver praticamente toda a
    # tinta da imagem. Sem isso, o recorte ampute o rodapé ou a assinatura.
    escuro = cv2.GaussianBlur(g, (5, 5), 0)
    _, tinta = cv2.threshold(escuro, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    total = int((tinta > 0).sum())
    if total == 0:
        return None
    dentro = int((tinta[y:y + h, x:x + w] > 0).sum())
    if dentro / total < 0.985:
        return None

    return x, y, x + w, y + h


def aparar(img: Image.Image, modo: str = "auto") -> Image.Image:
    """Apara as margens.

    auto    – isola a folha na foto e recorta na área de conteúdo, com folga
    bordas  – recorta só o excesso de fundo, preservando a margem branca
    nenhum  – não mexe
    """
    if modo == "nenhum":
        return img
    W, H = img.size

    # 1) isola a folha, quando a foto tem fundo visível
    caixa_papel = _regiao_papel(img)
    if caixa_papel:
        folga_papel = int(0.010 * max(W, H))
        x0, y0, x1, y1 = caixa_papel
        img = img.crop((
            max(0, x0 - folga_papel), max(0, y0 - folga_papel),
            min(W, x1 + folga_papel), min(H, y1 + folga_papel),
        ))
        if modo == "bordas":
            return img
        W, H = img.size

    # 2) aparo fino na área de conteúdo
    g = _cinza(img)
    borrada = cv2.GaussianBlur(g, (9, 9), 0)
    _, bin_ = cv2.threshold(borrada, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    bin_ = cv2.morphologyEx(bin_, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    coords = cv2.findNonZero(bin_)
    if coords is None:
        return img
    x, y, w, h = cv2.boundingRect(coords)
    if w * h < 0.15 * W * H:  # bounding box implausível: não arrisca amputar
        return img
    folga = int(0.030 * max(W, H)) if modo == "auto" else int(0.075 * max(W, H))
    x0 = max(0, x - folga)
    y0 = max(0, y - folga)
    x1 = min(W, x + w + folga)
    y1 = min(H, y + h + folga)
    return img.crop((x0, y0, x1, y1))


def realcar(img: Image.Image, nivel: str = "suave") -> Image.Image:
    """Ajuste de contraste. Nunca binariza: apagar carimbo/marca d'água é vedado."""
    if nivel in (None, "nenhum"):
        return img
    if nivel == "suave":
        img = ImageEnhance.Contrast(img).enhance(1.20)
        return ImageEnhance.Brightness(img).enhance(1.03)
    if nivel == "forte":
        arr = np.array(img.convert("L"))
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        arr = clahe.apply(arr)
        out = Image.fromarray(arr).convert("RGB")
        return ImageEnhance.Contrast(out).enhance(1.10)
    raise ValueError("realce deve ser nenhum, suave ou forte")


def para_pagina(img: Image.Image, tamanho=A4_PX) -> Image.Image:
    """Encaixa a página em folha A4 branca, sem cortar e sem distorcer."""
    largura, altura = tamanho
    if img.size[0] > img.size[1]:  # conteúdo em paisagem: usa folha deitada
        largura, altura = altura, largura
    copia = img.copy()
    copia.thumbnail((largura, altura), Image.LANCZOS)
    folha = Image.new("RGB", (largura, altura), "white")
    folha.paste(copia, ((largura - copia.size[0]) // 2, (altura - copia.size[1]) // 2))
    return folha


def tratar(img: Image.Image, opcoes: dict) -> Image.Image:
    """Pipeline oficial: giro → moldura → endireitar → aparo → realce → A4."""
    img = girar(img, opcoes.get("girar", 0))
    img = remover_moldura(img)
    if opcoes.get("endireitar", True):
        img = endireitar(img)
    img = aparar(img, opcoes.get("corte", "auto"))
    img = realcar(img, opcoes.get("realce", "suave"))
    if opcoes.get("pagina", "A4") != "nenhum":
        img = para_pagina(img)
    return img


# --------------------------------------------------------------------------
# Nomes
# --------------------------------------------------------------------------

SIGLAS = {
    "rg", "cpf", "cnis", "ctps", "pis", "pasep", "nit", "cat", "ppp",
    "ltcat", "pcmso", "asos", "bo", "inss", "nb", "der", "dib", "dcb",
    "dii", "b91", "b31", "trf", "jef", "cnh", "cin", "cadunico", "epi",
}


def normalizar_nome(nome: str) -> str:
    """'comprovante de residência' -> 'Comprovante De Residência'.

    Preserva acentos, datas (2024-03-11) e a palavra "(duplicado)". Cada
    palavra recebe a primeira letra maiúscula e o restante minúsculo (Title
    Case) — é o padrão de entrega da pasta — exceto siglas conhecidas
    (RG, CPF, CNIS, PPP, INSS etc.), que ficam sempre em caixa alta total.
    """
    nome = nome.strip()
    nome = re.sub(r"[^\w\sÀ-ÿ().-]", "", nome, flags=re.UNICODE)
    nome = re.sub(r"\s+", " ", nome).strip() or "Documento"

    def capitaliza_palavra(palavra: str) -> str:
        if not palavra:
            return palavra
        nucleo = palavra.strip("()")
        prefixo = palavra[: len(palavra) - len(palavra.lstrip("("))]
        sufixo = palavra[len(palavra.rstrip(")")):]
        if nucleo.lower() in SIGLAS:
            return prefixo + nucleo.upper() + sufixo
        if re.fullmatch(r"[\d.\-]+", nucleo):
            return palavra
        return prefixo + nucleo[0].upper() + nucleo[1:].lower() + sufixo

    partes = nome.split(" ")
    partes = [capitaliza_palavra(p) for p in partes]
    return " ".join(partes)
