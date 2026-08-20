"""Análise de legibilidade da foto do documento.

Métricas puramente de imagem (antes do OCR) + métricas derivadas do OCR.
Cada métrica vira um score 0-100 e um veredito textual em português.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os

import cv2
import numpy as np

# Limiares calibrados para fotos de documento tiradas por celular.
MIN_LADO_MENOR = 600          # px — abaixo disso o texto pequeno se perde
BOM_LADO_MENOR = 1000
BLUR_RUIM = 60.0              # variância do Laplaciano
BLUR_BOM = 250.0
BRILHO_MIN = 55
# Papel branco eleva a média legitimamente (um scan de página passa de 230), então o
# teto é folgado: quem detecta superexposição de verdade é a métrica de reflexo.
BRILHO_MAX = 240
CONTRASTE_RUIM = 25.0         # desvio padrão da luminância
CONTRASTE_BOM = 55.0
GLARE_MAX_PCT = 8.0           # % de pixels estourados (reflexo do flash)


@dataclass
class Metrica:
    nome: str
    valor: float
    score: int
    ok: bool
    mensagem: str


@dataclass
class Qualidade:
    score: int
    legivel: bool
    metricas: list[Metrica] = field(default_factory=list)
    problemas: list[str] = field(default_factory=list)
    sugestoes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score_legibilidade": self.score,
            "legivel": self.legivel,
            "metricas": [
                {
                    "nome": m.nome,
                    "valor": round(m.valor, 2),
                    "score": m.score,
                    "ok": m.ok,
                    "mensagem": m.mensagem,
                }
                for m in self.metricas
            ],
            "problemas": self.problemas,
            "sugestoes": self.sugestoes,
        }


def _interp_score(valor: float, ruim: float, bom: float) -> int:
    """Mapeia linearmente [ruim, bom] -> [0, 100], saturando nas pontas."""
    if bom == ruim:
        return 100
    pct = (valor - ruim) / (bom - ruim)
    return int(max(0.0, min(1.0, pct)) * 100)


def analisar_imagem(img_bgr: np.ndarray) -> tuple[list[Metrica], list[str], list[str]]:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    lado_menor = min(h, w)

    metricas: list[Metrica] = []
    problemas: list[str] = []
    sugestoes: list[str] = []

    # --- resolução ---------------------------------------------------------
    score_res = _interp_score(lado_menor, MIN_LADO_MENOR * 0.5, BOM_LADO_MENOR)
    ok_res = lado_menor >= MIN_LADO_MENOR
    metricas.append(
        Metrica(
            "resolucao",
            float(lado_menor),
            score_res,
            ok_res,
            f"{w}x{h}px (menor lado: {lado_menor}px)",
        )
    )
    if not ok_res:
        problemas.append(f"Resolução baixa: menor lado tem {lado_menor}px (mínimo {MIN_LADO_MENOR}px).")
        sugestoes.append("Aproxime a câmera do documento ou envie a foto em resolução original.")

    # --- nitidez (foco) ----------------------------------------------------
    # Normaliza para 1000px antes de medir, senão a variância escala com o tamanho.
    escala = 1000.0 / max(lado_menor, 1)
    gray_norm = cv2.resize(gray, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA) if escala < 1 else gray
    blur = float(cv2.Laplacian(gray_norm, cv2.CV_64F).var())
    score_blur = _interp_score(blur, BLUR_RUIM * 0.4, BLUR_BOM)
    ok_blur = blur >= BLUR_RUIM
    metricas.append(Metrica("nitidez", blur, score_blur, ok_blur, f"variância do Laplaciano: {blur:.0f}"))
    if not ok_blur:
        problemas.append(f"Imagem desfocada ou tremida (nitidez {blur:.0f}, mínimo {BLUR_RUIM:.0f}).")
        sugestoes.append("Apoie o celular, toque na tela para focar e tire a foto novamente.")

    # --- brilho ------------------------------------------------------------
    brilho = float(gray.mean())
    if brilho < BRILHO_MIN:
        score_bri = _interp_score(brilho, 0, BRILHO_MIN)
        msg = f"escuro demais (média {brilho:.0f})"
        ok_bri = False
    elif brilho > BRILHO_MAX:
        score_bri = _interp_score(255 - brilho, 0, 255 - BRILHO_MAX)
        msg = f"claro demais (média {brilho:.0f})"
        ok_bri = False
    else:
        score_bri = 100
        msg = f"adequado (média {brilho:.0f})"
        ok_bri = True
    metricas.append(Metrica("brilho", brilho, score_bri, ok_bri, msg))
    if not ok_bri:
        problemas.append(f"Iluminação inadequada — {msg}.")
        sugestoes.append("Fotografe em ambiente bem iluminado, sem sombra sobre o documento.")

    # --- contraste ---------------------------------------------------------
    contraste = float(gray.std())
    score_con = _interp_score(contraste, CONTRASTE_RUIM * 0.5, CONTRASTE_BOM)
    ok_con = contraste >= CONTRASTE_RUIM
    metricas.append(Metrica("contraste", contraste, score_con, ok_con, f"desvio padrão: {contraste:.0f}"))
    if not ok_con:
        problemas.append(f"Contraste baixo ({contraste:.0f}) — o texto se confunde com o fundo.")
        sugestoes.append("Coloque o documento sobre uma superfície de cor contrastante.")

    # --- reflexo / estouro de luz -----------------------------------------
    glare_pct = float((gray >= 250).sum()) / gray.size * 100.0
    score_gla = 100 - _interp_score(glare_pct, 0, GLARE_MAX_PCT * 2)
    ok_gla = glare_pct <= GLARE_MAX_PCT
    metricas.append(Metrica("reflexo", glare_pct, score_gla, ok_gla, f"{glare_pct:.1f}% de pixels estourados"))
    if not ok_gla:
        problemas.append(f"Reflexo/brilho excessivo cobrindo {glare_pct:.1f}% da imagem.")
        sugestoes.append("Desligue o flash e evite luz direta sobre o plástico do documento.")

    return metricas, problemas, sugestoes


def avaliar(
    img_bgr: np.ndarray,
    confianca_ocr: float | None = None,
    qtd_blocos: int = 0,
    qtd_caracteres: int = 0,
) -> Qualidade:
    """Combina métricas de imagem com o resultado do OCR num score único."""
    metricas, problemas, sugestoes = analisar_imagem(img_bgr)

    # --- confiança média do OCR -------------------------------------------
    if confianca_ocr is not None:
        pct = confianca_ocr * 100
        score_conf = _interp_score(pct, 40, 92)
        ok_conf = pct >= 70
        metricas.append(
            Metrica("confianca_ocr", pct, score_conf, ok_conf, f"confiança média do OCR: {pct:.1f}%")
        )
        if not ok_conf:
            problemas.append(f"O OCR reconheceu o texto com baixa confiança ({pct:.1f}%).")
    else:
        score_conf = 0

    # --- densidade de texto ------------------------------------------------
    ok_texto = qtd_caracteres >= 40 and qtd_blocos >= 4
    score_texto = _interp_score(qtd_caracteres, 0, 200)
    metricas.append(
        Metrica(
            "texto_detectado",
            float(qtd_caracteres),
            score_texto,
            ok_texto,
            f"{qtd_blocos} blocos, {qtd_caracteres} caracteres",
        )
    )
    if not ok_texto:
        problemas.append(
            f"Pouco texto detectado ({qtd_caracteres} caracteres em {qtd_blocos} blocos) — "
            "a imagem pode não ser um documento ou está ilegível."
        )
        sugestoes.append("Enquadre o documento inteiro, preenchendo a maior parte do quadro.")

    # Peso maior para o que de fato determina a leitura: nitidez e OCR.
    pesos = {
        "resolucao": 1.0,
        "nitidez": 2.0,
        "brilho": 1.0,
        "contraste": 1.0,
        "reflexo": 0.5,
        "confianca_ocr": 2.5,
        "texto_detectado": 2.0,
    }
    soma = sum(m.score * pesos.get(m.nome, 1.0) for m in metricas)
    total = sum(pesos.get(m.nome, 1.0) for m in metricas)
    score = int(round(soma / total)) if total else 0

    legivel = score >= 55 and ok_texto and (confianca_ocr is None or confianca_ocr >= 0.60)

    if not sugestoes and score < 80:
        sugestoes.append("A leitura funcionou, mas uma foto mais nítida e bem iluminada aumenta a precisão.")

    return Qualidade(score=score, legivel=legivel, metricas=metricas, problemas=problemas, sugestoes=sugestoes)


# ------------------------------------------------------- pré-processamento


def _ordenar_vertices(pontos: np.ndarray) -> np.ndarray:
    pontos = pontos.reshape(4, 2).astype(np.float32)
    soma = pontos.sum(axis=1)
    diferenca = np.diff(pontos, axis=1).reshape(-1)
    return np.array([
        pontos[np.argmin(soma)], pontos[np.argmin(diferenca)],
        pontos[np.argmax(soma)], pontos[np.argmax(diferenca)],
    ], dtype=np.float32)


def recortar_documento(img_bgr: np.ndarray) -> tuple[np.ndarray, bool]:
    """Recorta por perspectiva somente quando há um quadrilátero inequívoco."""
    h, w = img_bgr.shape[:2]
    if min(h, w) < 500:
        return img_bgr, False
    escala = min(1.0, 1000.0 / max(h, w))
    pequena = cv2.resize(img_bgr, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
    cinza = cv2.cvtColor(pequena, cv2.COLOR_BGR2GRAY)
    cinza = cv2.GaussianBlur(cinza, (5, 5), 0)
    bordas = cv2.Canny(cinza, 45, 135)
    bordas = cv2.morphologyEx(bordas, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2)
    area_imagem = pequena.shape[0] * pequena.shape[1]
    contornos, _ = cv2.findContours(bordas, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contorno in sorted(contornos, key=cv2.contourArea, reverse=True)[:8]:
        area = cv2.contourArea(contorno)
        proporcao = area / area_imagem
        if not 0.35 <= proporcao <= 0.97:
            continue
        aproximado = cv2.approxPolyDP(contorno, 0.02 * cv2.arcLength(contorno, True), True)
        if len(aproximado) != 4 or not cv2.isContourConvex(aproximado):
            continue
        pontos = _ordenar_vertices(aproximado / escala)
        tl, tr, br, bl = pontos
        largura = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
        altura = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
        if largura < 500 or altura < 300:
            continue
        destino = np.array([[0, 0], [largura - 1, 0], [largura - 1, altura - 1], [0, altura - 1]], dtype=np.float32)
        matriz = cv2.getPerspectiveTransform(pontos, destino)
        return cv2.warpPerspective(img_bgr, matriz, (largura, altura)), True
    return img_bgr, False


def preparar_para_ocr(img_bgr: np.ndarray, lado_maximo: int = 2000) -> np.ndarray:
    """Prepara foto de celular com OpenCV sem criar uma segunda passada de OCR.

    O tratamento é adaptativo: ilumina foto escura, contém fundo estourado,
    reforça contraste local e aplica máscara de nitidez apenas quando a imagem
    está realmente suave. Documento já bom recebe intervenção pequena, evitando
    halos que confundem ``O/0`` e ``I/1``.
    """
    if img_bgr is None or img_bgr.size == 0:
        raise ValueError("Imagem vazia para pré-processamento.")
    if img_bgr.dtype != np.uint8:
        img_bgr = np.clip(img_bgr, 0, 255).astype(np.uint8)

    # Opt-in: fotos sem margem podem ter bordas internas parecidas com o papel.
    # O benchmark deve validar o acervo real antes de habilitar globalmente.
    if os.getenv("OCR_CROPS_DOCUMENTO", "0").strip().lower() not in {"0", "false"}:
        img_bgr, _ = recortar_documento(img_bgr)

    h, w = img_bgr.shape[:2]
    maior = max(h, w)
    if maior > lado_maximo:
        escala = lado_maximo / maior
        img_bgr = cv2.resize(img_bgr, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)

    # Gamma corrige iluminação global preservando as cores e as bordas. CLAHE
    # sozinho melhora o contraste local, mas não recupera uma foto inteira
    # subexposta ou um papel lavado pelo flash.
    luminancia = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    media = float(luminancia.mean())
    gamma = 0.72 if media < 85 else 0.86 if media < 120 else 1.18 if media > 220 else 1.0
    if gamma != 1.0:
        tabela = np.array([((i / 255.0) ** gamma) * 255 for i in range(256)], dtype=np.uint8)
        img_bgr = cv2.LUT(img_bgr, tabela)

    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    contraste = float(l.std())
    clip = 2.6 if contraste < 32 else 2.0 if contraste < 50 else 1.35
    l = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8)).apply(l)
    preparada = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)

    # Unsharp mask moderada somente em imagem suave. Acima do limiar, reforçar
    # criaria borda dupla em letras que já estão nítidas.
    nitidez = float(cv2.Laplacian(cv2.cvtColor(preparada, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
    if nitidez < 140:
        suave = cv2.GaussianBlur(preparada, (0, 0), 1.0)
        preparada = cv2.addWeighted(preparada, 1.35, suave, -0.35, 0)
    return preparada
