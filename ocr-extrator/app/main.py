"""API do extrator de documentos (FastAPI + PaddleOCR)."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from . import categorias, pipeline
from .extractors import ROTULOS_TIPO

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")

BASE = Path(__file__).resolve().parent.parent
STATIC = BASE / "static"

MAX_BYTES = 20 * 1024 * 1024
EXTENSOES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}

app = FastAPI(title="Extrator de Documentos — PaddleOCR", version="1.0.0")

# O frontend Next (:3100) chama esta API direto do navegador, então precisa de CORS.
# `*` é aceitável aqui porque o servidor escuta só em 127.0.0.1 e não usa cookies nem
# sessão — não há credencial que uma página de terceiros pudesse reaproveitar. Se um dia
# isto for exposto na rede, troque por uma lista explícita de origens.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/tipos")
def tipos():
    return {"tipos": [{"codigo": k, "descricao": v} for k, v in ROTULOS_TIPO.items()]}


@app.get("/api/categorias")
def listar_categorias():
    """Categorias de processo, cada uma com seu checklist de documentos."""
    return {"categorias": [c.to_dict() for c in categorias.listar()]}


@app.get("/api/categorias/{codigo}")
def obter_categoria(codigo: str):
    categoria = categorias.obter(codigo)
    if categoria is None:
        raise HTTPException(404, f"Categoria '{codigo}' não encontrada.")
    return categoria.to_dict()


@app.get("/api/saude")
def saude():
    from . import ocr_engine  # lê o atributo do módulo, não uma cópia do valor

    return {"status": "ok", "modelo_carregado": ocr_engine._engine is not None}


@app.post("/api/aquecer")
def aquecer():
    """Baixa e carrega os modelos do PaddleOCR antes do primeiro upload."""
    import numpy as np

    from .ocr_engine import rodar_ocr

    branco = np.full((80, 400, 3), 255, dtype=np.uint8)
    try:
        rodar_ocr(branco)
        return {"status": "pronto"}
    except Exception as exc:
        log.exception("Falha ao aquecer o modelo")
        raise HTTPException(status_code=500, detail=f"Falha ao carregar o modelo: {exc}") from exc


@app.post("/api/extrair")
async def extrair(
    arquivo: UploadFile = File(...),
    idioma: str = Form("pt"),
    tipo: str | None = Form(None),
):
    ext = Path(arquivo.filename or "").suffix.lower()
    if ext and ext not in EXTENSOES:
        raise HTTPException(400, f"Extensão '{ext}' não suportada. Use: {', '.join(sorted(EXTENSOES))}")

    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")
    if len(conteudo) > MAX_BYTES:
        raise HTTPException(413, f"Arquivo maior que {MAX_BYTES // (1024 * 1024)}MB.")

    tipo_forcado = tipo if tipo and tipo not in ("auto", "", "None") else None

    try:
        # O OCR leva segundos e é puro CPU: fora do event loop, senão o servidor
        # para de responder (inclusive ao /api/saude) enquanto processa.
        resultado = await run_in_threadpool(
            pipeline.processar, conteudo, arquivo.filename or "sem-nome", idioma, tipo_forcado
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        log.exception("Erro ao processar %s", arquivo.filename)
        raise HTTPException(500, f"Erro ao processar a imagem: {exc}") from exc

    return JSONResponse(resultado)


@app.get("/api/temp/{nome}")
def baixar_temp(nome: str):
    """Serve o JSON/XML temporário gerado para um documento."""
    if not nome.endswith((".json", ".xml")) or "/" in nome or "\\" in nome or ".." in nome:
        raise HTTPException(400, "Nome de arquivo inválido.")

    caminho = (pipeline.TMP_DIR / nome).resolve()
    if pipeline.TMP_DIR.resolve() not in caminho.parents or not caminho.is_file():
        raise HTTPException(404, "Arquivo temporário não encontrado ou já expirado.")

    media = "application/json" if nome.endswith(".json") else "application/xml"
    return FileResponse(caminho, media_type=media, filename=nome)


@app.delete("/api/temp")
def limpar():
    return {"removidos": pipeline.limpar_temporarios()}
