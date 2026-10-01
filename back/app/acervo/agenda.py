"""Quando o Acervo se verifica sozinho. A fonte da verdade é o `beat_schedule` do Celery, não uma conta à parte."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

TAREFA = "app.tasks.acervo.sincronizar_acervo"
ENTRADA = "acervo-sincronizar"


def ativa() -> bool:
    """Desligada por padrão: só sincroniza com `ACERVO_SINCRONIZACAO_ATIVA=1` (escreve no pgvector)."""
    return os.getenv("ACERVO_SINCRONIZACAO_ATIVA", "0").strip().lower() in {"1", "true", "sim", "yes"}


def _agendamento() -> Any | None:
    from ..celery_app import celery_app
    entrada = (celery_app.conf.beat_schedule or {}).get(ENTRADA)
    return entrada.get("schedule") if entrada else None


def proxima_execucao(agora: datetime | None = None, *, agendamento: Any | None = None) -> datetime | None:
    """Próximo disparo do beat depois de `agora`; None quando a sincronização automática está desligada."""
    if not ativa():
        return None
    agendamento = agendamento if agendamento is not None else _agendamento()
    if agendamento is None:
        return None
    agora = agora or datetime.now(UTC)
    if hasattr(agendamento, "remaining_estimate"):
        restante = agendamento.remaining_estimate(agora)
        return (agora + restante).astimezone(UTC)
    from datetime import timedelta
    return agora + timedelta(seconds=float(agendamento))


def descricao(agendamento: Any | None = None) -> str:
    agendamento = agendamento if agendamento is not None else _agendamento()
    if agendamento is None:
        return "não agendada"
    horas = getattr(agendamento, "_orig_hour", None)
    minutos = getattr(agendamento, "_orig_minute", None)
    if horas is not None and minutos is not None:
        return f"diariamente às {int(str(horas)):02d}:{int(str(minutos)):02d} (America/Sao_Paulo)"
    return str(agendamento)
