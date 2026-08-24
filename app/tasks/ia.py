from __future__ import annotations

from ..celery_app import celery_app
from .. import jobs
from datetime import datetime, timezone


@celery_app.task(bind=True, name="app.tasks.ia.analisar", autoretry_for=(TimeoutError,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def analisar(self, operacao: str, argumentos: dict):
    """Fila reservada a inferências não realtime; evita misturá-las ao OCR."""
    if operacao == "estrategia":
        from ..rag import sugerir_acoes
        return sugerir_acoes(**argumentos)
    raise ValueError(f"Operação de IA não permitida: {operacao}")


@celery_app.task(bind=True, name="app.tasks.ia.gerar_estrategia", autoretry_for=(TimeoutError,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def gerar_estrategia(self, job_id: str, relato: str, limite: int = 8):
    jobs.atualizar(job_id, status="STARTED", progresso=10, iniciado_em=datetime.now(timezone.utc))
    try:
        from ..rag import sugerir_acoes
        jobs.atualizar(job_id, status="PROCESSING", progresso=35)
        resultado = sugerir_acoes(relato, limite=limite)
        jobs.atualizar(job_id, status="COMPLETED", progresso=100, resultado=resultado, finalizado_em=datetime.now(timezone.utc))
        return resultado
    except Exception as exc:
        jobs.atualizar(job_id, status="FAILED", erro=str(exc), finalizado_em=datetime.now(timezone.utc))
        raise
