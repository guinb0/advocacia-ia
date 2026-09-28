"""Consumo e saldo das APIs pagas (OpenRouter, DeepSeek, Mistral)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from .. import auth, custos_api

roteador = APIRouter()


@roteador.get("/api/observabilidade/custos-api")
async def custos_api_tempo_real(horas: int = Query(default=24, ge=1, le=720)) -> dict[str, Any]:
    """Consumo e falhas de APIs no período, sem dados de cliente ou prompts."""
    return await run_in_threadpool(lambda: custos_api.resumo(horas=horas))


@roteador.get("/api/gastos-api")
async def painel_gastos_api(_usuario: auth.Usuario = Depends(auth.exigir_modulo("gastos_api"))):
    """Gasto e saldo restante de cada API, para saber quando recarregar."""
    return await run_in_threadpool(custos_api.painel)
