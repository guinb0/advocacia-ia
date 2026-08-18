from __future__ import annotations

from .. import jobs, pipeline
from ..celery_app import celery_app
from pathlib import Path
import time


@celery_app.task(name="app.tasks.manutencao.limpar_temporarios")
def limpar_temporarios() -> int:
    removidos = pipeline.limpar_temporarios()
    pasta_jobs = pipeline.TMP_DIR / "jobs"
    limite = time.time() - 24 * 3600
    for caminho in pasta_jobs.glob("*.upload") if pasta_jobs.exists() else ():
        try:
            if caminho.stat().st_mtime < limite:
                caminho.unlink()
                removidos += 1
        except OSError:
            pass
    return removidos


@celery_app.task(name="app.tasks.manutencao.recuperar_jobs_abandonados")
def recuperar_jobs_abandonados() -> int:
    return jobs.recuperar_abandonados()
