from __future__ import annotations

from datetime import datetime, timezone
from contextlib import nullcontext
import os
from pathlib import Path

from .. import jobs, pipeline
from ..celery_app import celery_app
from ..gpu_lock import gpu_exclusiva


@celery_app.task(
    bind=True,
    name="app.tasks.ocr.processar_documento",
    autoretry_for=(OSError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def processar_documento(self, job_id: str, caminho: str, nome: str, idioma: str, tipo: str | None):
    inicio = datetime.now(timezone.utc)
    jobs.atualizar(job_id, status="STARTED", progresso=5, iniciado_em=inicio)
    try:
        jobs.atualizar(job_id, status="PROCESSING", progresso=15)
        conteudo = Path(caminho).read_bytes()
        # O Paddle atual é CPU por decisão medida. Ao ativar a wheel CUDA, esta
        # mesma tarefa passa a disputar a trava interprocesso com o Whisper.
        trava = gpu_exclusiva() if os.getenv("OCR_USA_GPU", "0") == "1" else nullcontext()
        with trava:
            jobs.atualizar(job_id, progresso=30)
            resultado = pipeline.processar(conteudo, nome, idioma, tipo)
        jobs.atualizar(
            job_id,
            status="COMPLETED",
            progresso=100,
            resultado=resultado,
            finalizado_em=datetime.now(timezone.utc),
        )
        Path(caminho).unlink(missing_ok=True)
        return resultado
    except Exception as exc:
        # Se houver retry, a próxima execução volta o estado para STARTED.
        jobs.atualizar(job_id, status="FAILED", erro=str(exc), finalizado_em=datetime.now(timezone.utc))
        raise
