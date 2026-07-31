"""Wrapper do PaddleOCR: carrega o modelo uma vez e devolve linhas normalizadas."""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .extractors import Linha

log = logging.getLogger("ocr")

# Silencia o log verboso do PaddleX/Paddle durante a inferência.
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("FLAGS_call_stack_level", "0")

_lock = threading.Lock()
_engine = None
_lang_carregado: str | None = None

# O predictor nativo do Paddle tem afinidade de thread: usá-lo a partir de threads
# diferentes estoura "RuntimeError: Unknown exception" mesmo quando as chamadas são
# serializadas por lock. Por isso toda a inferência acontece nesta única thread, que
# constrói o modelo e é dona dele pelo resto da vida do processo. Como efeito colateral
# os uploads simultâneos entram numa fila, que é o comportamento desejado num servidor
# de CPU: rodar dois OCRs ao mesmo tempo só faria os dois ficarem mais lentos.
_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="paddle-ocr")


def _construir(lang: str):
    from paddleocr import PaddleOCR

    return PaddleOCR(
        lang=lang,
        # Endireita a página inteira antes de detectar. Sem isso uma foto deitada
        # até é lida, mas as caixas saem transpostas e a associação rótulo->valor
        # (que é geométrica) troca os campos de lugar.
        use_doc_orientation_classify=True,
        use_doc_unwarping=False,   # correção de páginas onduladas: pesada e rara aqui
        use_textline_orientation=True,
    )


def get_engine(lang: str = "pt"):
    """Carrega o PaddleOCR sob demanda (o download dos modelos ocorre na 1ª chamada)."""
    global _engine, _lang_carregado
    with _lock:
        if _engine is not None and _lang_carregado == lang:
            return _engine

        for tentativa in (lang, "latin", "en"):
            try:
                log.info("Carregando PaddleOCR (lang=%s)...", tentativa)
                _engine = _construir(tentativa)
                _lang_carregado = lang
                log.info("PaddleOCR pronto (lang=%s).", tentativa)
                return _engine
            except Exception as exc:  # modelo indisponível para o idioma
                log.warning("Falha ao carregar lang=%s: %s", tentativa, exc)

        raise RuntimeError("Não foi possível inicializar o PaddleOCR.")


def _poligono_para_metrica(poly) -> tuple[float, float, float, float]:
    """Devolve (y_central, x_esquerda, largura, altura) de um polígono de 4 pontos."""
    pts = np.asarray(poly, dtype=float).reshape(-1, 2)
    ys, xs = pts[:, 1], pts[:, 0]
    return float(ys.mean()), float(xs.min()), float(xs.max() - xs.min()), float(ys.max() - ys.min())


def _agrupar_em_linhas(itens: list[Linha]) -> list[Linha]:
    """Junta caixas na mesma altura, mas mantém colunas separadas.

    Documentos de identidade são diagramados em colunas ("FILIAÇÃO" à esquerda,
    "CAT. HAB." à direita, na mesma altura). Juntar tudo numa linha só contamina
    a extração, então um espaço horizontal grande vira uma quebra.
    """
    if not itens:
        return []

    alturas = [i.altura for i in itens if i.altura > 0]
    altura_tipica = float(np.median(alturas)) if alturas else 16.0
    tolerancia_y = altura_tipica * 0.6
    limite_gap = max(altura_tipica * 2.0, 30.0)

    itens = sorted(itens, key=lambda i: (i.y, i.x))
    faixas: list[list[Linha]] = [[itens[0]]]
    for item in itens[1:]:
        if abs(item.y - faixas[-1][-1].y) <= tolerancia_y:
            faixas[-1].append(item)
        else:
            faixas.append([item])

    linhas: list[Linha] = []
    for faixa in faixas:
        faixa.sort(key=lambda i: i.x)

        colunas: list[list[Linha]] = [[faixa[0]]]
        for anterior, item in zip(faixa, faixa[1:]):
            fim_anterior = anterior.x + anterior.largura
            if item.x - fim_anterior > limite_gap:
                colunas.append([item])
            else:
                colunas[-1].append(item)

        for coluna in colunas:
            texto = " ".join(c.texto for c in coluna).strip()
            if not texto:
                continue
            linhas.append(
                Linha(
                    texto=texto,
                    confianca=float(np.mean([c.confianca for c in coluna])),
                    y=float(np.mean([c.y for c in coluna])),
                    x=min(c.x for c in coluna),
                    largura=sum(c.largura for c in coluna),
                    altura=float(np.max([c.altura for c in coluna])),
                )
            )

    linhas.sort(key=lambda l: (l.y, l.x))
    return linhas


def _extrair_resultado(res) -> list[Linha]:
    """Normaliza a saída do PaddleOCR 3.x (dict) e 2.x (listas aninhadas)."""
    itens: list[Linha] = []

    # --- API 3.x: objeto tipo dict com rec_texts / rec_scores / rec_polys ---
    dados = None
    if isinstance(res, dict):
        dados = res
    elif hasattr(res, "json") and isinstance(getattr(res, "json", None), dict):
        dados = res.json.get("res", res.json)
    elif hasattr(res, "__getitem__"):
        try:
            _ = res["rec_texts"]
            dados = res
        except Exception:
            dados = None

    if dados is not None:
        try:
            textos = list(dados["rec_texts"])
            scores = list(dados.get("rec_scores") or [1.0] * len(textos))
            polys = dados.get("rec_polys")
            if polys is None:
                polys = dados.get("dt_polys")
            polys = list(polys) if polys is not None else [None] * len(textos)

            for texto, score, poly in zip(textos, scores, polys):
                if not (texto or "").strip():
                    continue
                y, x, larg, alt = _poligono_para_metrica(poly) if poly is not None else (0.0, 0.0, 0.0, 0.0)
                itens.append(
                    Linha(texto=str(texto).strip(), confianca=float(score), y=y, x=x, largura=larg, altura=alt)
                )
            return itens
        except Exception as exc:
            log.debug("Saída 3.x não reconhecida (%s); tentando formato 2.x.", exc)

    # --- API 2.x: [[box, (texto, score)], ...] ------------------------------
    try:
        for item in res:
            if not item:
                continue
            box, (texto, score) = item[0], item[1]
            if not (texto or "").strip():
                continue
            y, x, larg, alt = _poligono_para_metrica(box)
            itens.append(
                Linha(texto=str(texto).strip(), confianca=float(score), y=y, x=x, largura=larg, altura=alt)
            )
    except Exception as exc:
        log.debug("Saída também não é 2.x (%s) — provavelmente não há texto na imagem.", exc)

    return itens


def _inferir(img_bgr: np.ndarray, lang: str):
    """Só é chamada de dentro da thread dedicada — ver `_worker`."""
    engine = get_engine(lang)
    if hasattr(engine, "predict"):
        return engine.predict(input=img_bgr)
    return engine.ocr(img_bgr, cls=True)  # PaddleOCR 2.x


def rodar_ocr(img_bgr: np.ndarray, lang: str = "pt") -> list[Linha]:
    """Executa o OCR e devolve as linhas ordenadas de cima para baixo."""
    saida = _worker.submit(_inferir, img_bgr, lang).result()

    itens: list[Linha] = []
    for res in (saida or []):
        itens.extend(_extrair_resultado(res))

    return _agrupar_em_linhas(itens)
