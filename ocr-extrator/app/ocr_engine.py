"""Wrapper do PaddleOCR: carrega o modelo uma vez e devolve linhas normalizadas."""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .extractors import Linha

log = logging.getLogger("ocr")

# Silencia o log verboso do PaddleX/Paddle durante a inferência.
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("FLAGS_call_stack_level", "0")


def _inteiro_env(nome: str, padrao: int, minimo: int = 1) -> int:
    try:
        return max(minimo, int(os.getenv(nome, "").strip() or padrao))
    except ValueError:
        log.warning("%s inválido; usando %s.", nome, padrao)
        return padrao


_DET_LADO_MAXIMO = os.getenv("OCR_DET_LADO_MAXIMO", "").strip()

# ------------------------------------------------------------------ dispositivo
#
# A placa é de 6.141 MiB e o Whisper já mora nela com 4.230. O que sobra para o
# OCR é ~1,7 GB, e o teto abaixo é o que impede o Paddle de tentar passar disso:
# sem ele o alocador cresce até ~2,5 GB no detector `server` e derruba a GPU
# inteira — a entrevista ao vivo junto. Medido; ver `docs/SISTEMA.md`.
#
# Precisa ser definido ANTES do primeiro `import paddle`, que só acontece dentro
# de `_construir`. Por isso está no topo do módulo, e não perto do uso.
LIMITE_VRAM_MB = os.getenv("OCR_LIMITE_VRAM_MB", "1200")
os.environ.setdefault("FLAGS_gpu_memory_limit_mb", LIMITE_VRAM_MB)

#: **CPU por medição, não por omissão.** Em GPU o OCR fica 17x mais rápido
#: (0,25s contra 4,2s) e cabe na VRAM que sobra do Whisper — mas o caminho CUDA
#: devolve caixas com geometria diferente e a extração de campos quebra:
#: `tests/test_pipeline.py` vai de 2 para 9 falhas, com o nome do titular da CNH
#: saindo como o do pai. Enquanto `_agrupar_em_linhas` não for reajustado para
#: essa saída, `gpu` aqui é experimento — e exige a wheel `paddlepaddle-gpu`.
DISPOSITIVO = os.getenv("OCR_DISPOSITIVO", "cpu").strip().lower()

#: Só faz sentido em GPU, onde o detector `server` não cabe (2.490 MiB de pico
#: contra 916 do `mobile`). Em CPU o padrão do PaddleOCR é mantido.
DETECTOR = os.getenv("OCR_DETECTOR") or ("PP-OCRv5_mobile_det" if DISPOSITIVO == "gpu" else "")

_lock = threading.Lock()
_engine = None
_lang_carregado: str | None = None
#: Vira True quando a GPU falha e o motor é reconstruído em CPU. A partir daí
#: nem se tenta de novo: se não coube uma vez, não vai caber na seguinte.
_caiu_para_cpu = False

# O predictor nativo do Paddle tem afinidade de thread: usá-lo a partir de threads
# diferentes estoura "RuntimeError: Unknown exception" mesmo quando as chamadas são
# serializadas por lock. Por isso toda a inferência acontece nesta única thread, que
# constrói o modelo e é dona dele pelo resto da vida do processo. Como efeito colateral
# os uploads simultâneos entram numa fila, que é o comportamento desejado num servidor
# de CPU: rodar dois OCRs ao mesmo tempo só faria os dois ficarem mais lentos.
_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="paddle-ocr")


def _construir(lang: str, dispositivo: str):
    from paddleocr import PaddleOCR

    extra = {}
    if dispositivo == "gpu" and DETECTOR:
        extra["text_detection_model_name"] = DETECTOR
    # Reduzir a imagem foi descartado nas medições dos documentos reais porque
    # piorava a detecção e acionava até três rotações extras. Só habilita quando
    # alguém define explicitamente a variável para um novo benchmark.
    if _DET_LADO_MAXIMO:
        extra["text_det_limit_type"] = "max"
        extra["text_det_limit_side_len"] = _inteiro_env(
            "OCR_DET_LADO_MAXIMO", 1280, minimo=320
        )

    return PaddleOCR(
        lang=lang,
        # Endireita a página inteira antes de detectar. Sem isso uma foto deitada
        # até é lida, mas as caixas saem transpostas e a associação rótulo->valor
        # (que é geométrica) troca os campos de lugar.
        use_doc_orientation_classify=True,
        use_doc_unwarping=False,   # correção de páginas onduladas: pesada e rara aqui
        use_textline_orientation=True,
        device=dispositivo,
        **extra,
    )


def _e_falta_de_memoria(exc: BaseException) -> bool:
    """O Paddle sinaliza VRAM cheia por texto, não por tipo de exceção."""
    texto = f"{type(exc).__name__} {exc}".lower()
    return any(m in texto for m in ("resourceexhausted", "out of memory", "memoryerror"))


def get_engine(lang: str = "pt"):
    """Carrega o PaddleOCR sob demanda (o download dos modelos ocorre na 1ª chamada).

    Tenta a GPU primeiro e cai para CPU se ela não responder — mesma política do
    Whisper em `app/transcricao.py`. A diferença de velocidade é grande (0,25s
    contra ~4s por documento), mas um upload que falha é pior que um lento.
    """
    global _engine, _lang_carregado, _caiu_para_cpu
    with _lock:
        if _engine is not None and _lang_carregado == lang:
            return _engine

        alvo = "cpu" if _caiu_para_cpu else DISPOSITIVO
        for dispositivo in (alvo, "cpu"):
            for tentativa in (lang, "latin", "en"):
                try:
                    log.info("Carregando PaddleOCR (lang=%s, device=%s)...", tentativa, dispositivo)
                    _engine = _construir(tentativa, dispositivo)
                    _lang_carregado = lang
                    log.info("PaddleOCR pronto (lang=%s, device=%s%s).", tentativa, dispositivo,
                             f", det={DETECTOR}" if dispositivo == "gpu" and DETECTOR else "")
                    return _engine
                except Exception as exc:  # modelo indisponível para o idioma, ou GPU cheia
                    log.warning("Falha ao carregar lang=%s device=%s: %s",
                                tentativa, dispositivo, str(exc)[:160])

            if dispositivo != "cpu":
                log.warning("GPU indisponível para o OCR; caindo para CPU.")
                _caiu_para_cpu = True

        raise RuntimeError("Não foi possível inicializar o PaddleOCR.")


def modelo_carregado() -> bool:
    return _engine is not None


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


def _predizer(engine, img_bgr: np.ndarray):
    if hasattr(engine, "predict"):
        return engine.predict(input=img_bgr)
    return engine.ocr(img_bgr, cls=True)  # PaddleOCR 2.x


def _inferir(img_bgr: np.ndarray, lang: str):
    """Só é chamada de dentro da thread dedicada — ver `_worker`."""
    global _engine, _caiu_para_cpu

    engine = get_engine(lang)
    try:
        return _predizer(engine, img_bgr)
    except Exception as exc:
        # A GPU pode caber no boot e faltar depois: quem cresce é o Whisper, e o
        # documento grande é que estoura. Cair para CPU aqui custa segundos; não
        # cair custa o documento.
        if not _e_falta_de_memoria(exc) or _caiu_para_cpu:
            raise
        log.warning("VRAM insuficiente durante o OCR (%s); refazendo em CPU.", str(exc)[:160])
        with _lock:
            _caiu_para_cpu = True
            _engine = None
        return _predizer(get_engine(lang), img_bgr)


def _inferir_medido(img_bgr: np.ndarray, lang: str, enviado_em: float):
    inicio = time.perf_counter()
    saida = _inferir(img_bgr, lang)
    fim = time.perf_counter()
    return saida, {
        "fila_s": inicio - enviado_em,
        "inferencia_s": fim - inicio,
        "total_s": fim - enviado_em,
    }


def rodar_ocr_com_tempo(img_bgr: np.ndarray, lang: str = "pt") -> tuple[list[Linha], dict[str, float]]:
    """Executa o OCR e devolve linhas + tempos da fila/inferência."""
    enviado_em = time.perf_counter()
    saida, tempos = _worker.submit(_inferir_medido, img_bgr, lang, enviado_em).result()

    inicio_pos = time.perf_counter()
    itens: list[Linha] = []
    for res in (saida or []):
        itens.extend(_extrair_resultado(res))

    linhas = _agrupar_em_linhas(itens)
    tempos["pos_processamento_s"] = time.perf_counter() - inicio_pos
    tempos["total_s"] = time.perf_counter() - enviado_em

    h, w = img_bgr.shape[:2]
    log.info(
        "ocr %dx%d: fila=%.2fs inferencia=%.2fs pos=%.3fs blocos=%d device=%s",
        w,
        h,
        tempos["fila_s"],
        tempos["inferencia_s"],
        tempos["pos_processamento_s"],
        len(linhas),
        "cpu" if _caiu_para_cpu else DISPOSITIVO,
    )
    return linhas, tempos


def rodar_ocr(img_bgr: np.ndarray, lang: str = "pt") -> list[Linha]:
    """Executa o OCR e devolve as linhas ordenadas de cima para baixo."""
    linhas, _ = rodar_ocr_com_tempo(img_bgr, lang)
    return linhas
