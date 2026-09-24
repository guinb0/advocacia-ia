"""Leitura consistente da saúde da fila OCR, sem conteúdo de documentos."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .banco import conectar
from .celery_app import celery_app


def _classificar(dados: dict[str, Any]) -> str:
    waiting = dados["waiting"] or 0
    if dados.get("broker_error"):
        return "DEGRADED"
    if dados["active"] and (dados["oldest_processing_seconds"] or 0) > 780:
        return "POSSIBLE_HUNG_TASK"
    if waiting and not dados["healthy_workers"]:
        return "NO_CONSUMERS"
    if waiting and not dados["queue_progressing"] and (dados["oldest_waiting_seconds"] or 0) >= 300:
        return "STALLED"
    if waiting:
        return "DEGRADED"
    return "HEALTHY"


def snapshot() -> dict[str, Any]:
    agora = datetime.now(timezone.utc)
    limite_5m = (agora - timedelta(minutes=5)).isoformat(timespec="seconds")
    dados: dict[str, Any] = {
        "queue": "gpu_background", "waiting": None, "waiting_redis": None,
        "waiting_sql": 0, "active": 0,
        "healthy_workers": 0, "oldest_waiting_seconds": None,
        "oldest_processing_seconds": None, "last_completed_at": None,
        "completed_last_5m": 0, "failed_last_5m": 0, "queue_progressing": None,
        "state": "UNKNOWN",
    }
    try:
        from redis import Redis
        redis = Redis.from_url(celery_app.conf.broker_url, socket_connect_timeout=2, socket_timeout=2)
        dados["waiting_redis"] = redis.llen("gpu_background")
        workers = []
        for chave in redis.scan_iter("ocr:worker:*:heartbeat"):
            bruto = redis.get(chave)
            if bruto:
                try:
                    workers.append(json.loads(bruto))
                except (TypeError, json.JSONDecodeError):
                    pass
        dados["healthy_workers"] = len(workers)
        dados["workers"] = workers
    except Exception as exc:  # fronteira com broker
        dados["broker_error"] = type(exc).__name__
        dados["workers"] = []

    try:
        ativas = celery_app.control.inspect(timeout=3).active() or {}
        dados["active"] = sum(
            1 for tarefas in ativas.values() for t in tarefas
            if t.get("name") == "app.tasks.ocr.processar_entrega"
        )
    except Exception as exc:
        dados["inspect_error"] = type(exc).__name__

    with conectar(timeout=5) as con:
        linha = con.execute("""
            SELECT
              SUM(CASE WHEN status_proc = 'na_fila' THEN 1 ELSE 0 END) AS waiting_sql,
              MIN(CASE WHEN status_proc = 'na_fila' THEN COALESCE(ocr_enfileirado_em, criado_em) END) AS oldest_waiting,
              MIN(CASE WHEN status_proc = 'processando' THEN COALESCE(ocr_iniciado_em, criado_em) END) AS oldest_processing,
              MAX(CASE WHEN status_proc = 'pronto' THEN ocr_finalizado_em END) AS last_completed,
              SUM(CASE WHEN status_proc = 'pronto' AND ocr_finalizado_em >= ? THEN 1 ELSE 0 END) AS completed_5m,
              SUM(CASE WHEN status_proc = 'erro' AND ocr_finalizado_em >= ? THEN 1 ELSE 0 END) AS failed_5m
            FROM entregas
        """, (limite_5m, limite_5m)).fetchone()
    dados["waiting_sql"] = int(linha["waiting_sql"] or 0)
    # O banco é a cópia durável: em queda do broker, mensagens podem estar no
    # unacked mas a entrega ainda será `na_fila`. O maior dos dois evita chamar
    # a fila de vazia só porque um dos lados está atrasado.
    if dados["waiting_redis"] is None:
        dados["waiting"] = dados["waiting_sql"]
    else:
        dados["waiting"] = max(dados["waiting_redis"], dados["waiting_sql"])
    dados["last_completed_at"] = linha["last_completed"]
    dados["completed_last_5m"] = int(linha["completed_5m"] or 0)
    dados["failed_last_5m"] = int(linha["failed_5m"] or 0)
    for coluna, destino in (("oldest_waiting", "oldest_waiting_seconds"), ("oldest_processing", "oldest_processing_seconds")):
        valor = linha[coluna]
        if valor:
            try:
                instante = datetime.fromisoformat(str(valor)).astimezone(timezone.utc)
                dados[destino] = max(0, int((agora - instante).total_seconds()))
            except ValueError:
                pass

    waiting = dados["waiting"] or 0
    progresso = waiting == 0 or dados["completed_last_5m"] > 0
    dados["queue_progressing"] = progresso
    dados["state"] = _classificar(dados)
    return dados
