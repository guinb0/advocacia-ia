"""Celery central: filas isoladas, entrega tardia e agendamentos periódicos."""

from __future__ import annotations

import os

from celery import Celery

BROKER = os.getenv("CELERY_BROKER_URL", "redis://localhost:6380/0")
BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6380/1")

celery_app = Celery(
    "advocacia",
    broker=BROKER,
    backend=BACKEND,
    include=(
        "app.tasks.ocr",
        "app.tasks.agente",
        "app.tasks.documentos",
        "app.tasks.ia",
        "app.tasks.manutencao",
    ),
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="America/Sao_Paulo",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_send_sent_event=True,
    worker_send_task_events=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=1500,
    task_time_limit=1800,
    result_expires=86_400,
    broker_transport_options={
        "visibility_timeout": 21_600,
        "priority_steps": list(range(10)),
        "queue_order_strategy": "priority",
    },
    task_default_queue="default",
    task_routes={
        "app.tasks.ocr.*": {"queue": "gpu_background"},
        "app.tasks.agente.*": {"queue": "default"},
        "app.tasks.transcricao.*": {"queue": "gpu_realtime"},
        "app.tasks.ia.*": {"queue": "ai"},
        "app.tasks.documentos.*": {"queue": "documents"},
        "app.tasks.manutencao.*": {"queue": "low"},
    },
    beat_schedule={
        "limpar-temporarios": {
            "task": "app.tasks.manutencao.limpar_temporarios",
            "schedule": 3600.0,
        },
        "recuperar-jobs-abandonados": {
            "task": "app.tasks.manutencao.recuperar_jobs_abandonados",
            "schedule": 900.0,
        },
        "reenfileirar-entregas-ao-agente": {
            "task": "app.tasks.agente.reenfileirar_pendentes",
            "schedule": 600.0,
        },
    },
)

if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
    from opentelemetry.instrumentation.celery import CeleryInstrumentor
    CeleryInstrumentor().instrument()
