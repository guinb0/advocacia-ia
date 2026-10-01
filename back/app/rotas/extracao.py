"""Extração de documento avulso (OCR) e consulta de jobs."""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .. import jobs
from ..tasks.ocr import processar_documento
from .comum import (
    BASE,
    _ler_upload,
    _processar,
    log,
)

roteador = APIRouter()


@roteador.post("/api/extrair")
async def extrair(
    arquivo: UploadFile = File(...),
    idioma: str = Form("pt"),
    tipo: str | None = Form(None),
):
    conteudo = await _ler_upload(arquivo)
    tipo_forcado = tipo if tipo and tipo not in ("auto", "", "None") else None
    resultado = await _processar(
        conteudo, arquivo.filename or "sem-nome", idioma, tipo_forcado
    )
    return JSONResponse(resultado)


@roteador.post("/api/extrair/jobs", status_code=202)
async def enfileirar_extracao(
    arquivo: UploadFile = File(...),
    idioma: str = Form("pt"),
    tipo: str | None = Form(None),
):
    """Libera a conexão HTTP e executa o OCR no worker da fila GPU background."""
    conteudo = await _ler_upload(arquivo)
    tipo_forcado = tipo if tipo and tipo not in ("auto", "", "None") else None
    pasta = BASE / "tmp" / "jobs"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{uuid.uuid4().hex}.upload"
    caminho.write_bytes(conteudo)
    try:
        await run_in_threadpool(jobs.inicializar)
        job_id = await run_in_threadpool(jobs.criar, "OCR", arquivo=str(caminho))
        tarefa = processar_documento.apply_async(
            args=(
                job_id,
                str(caminho),
                arquivo.filename or "sem-nome",
                idioma,
                tipo_forcado,
            ),
            queue="gpu_background",
            priority=7,
        )
        await run_in_threadpool(jobs.vincular_tarefa, job_id, tarefa.id)
        return {
            "job_id": job_id,
            "task_id": tarefa.id,
            "status": "QUEUED",
            "progresso": 0,
        }
    except Exception as exc:
        caminho.unlink(missing_ok=True)
        log.exception("Falha ao enfileirar OCR")
        raise HTTPException(503, f"Fila de processamento indisponível: {exc}") from exc


@roteador.get("/api/jobs/{job_id}")
async def consultar_job(job_id: str):
    try:
        uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(400, "Identificador de job inválido") from exc
    registro = await run_in_threadpool(jobs.obter, job_id)
    if registro is None:
        raise HTTPException(404, "Job não encontrado")
    return registro
