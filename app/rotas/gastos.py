"""Consumo e saldo das APIs pagas (OpenRouter, DeepSeek, OpenAI, Mistral)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .. import auth, custos_api

roteador = APIRouter()


class SaldoInformado(BaseModel):
    #: Texto, e não número: "25,50" digitado no Brasil chega intacto e o erro de
    #: formato volta em português, em vez do 422 do Pydantic.
    valor: str


@roteador.get("/api/observabilidade/custos-api")
async def custos_api_tempo_real(horas: int = Query(default=24, ge=1, le=720)) -> dict[str, Any]:
    """Consumo e falhas de APIs no período, sem dados de cliente ou prompts."""
    return await run_in_threadpool(lambda: custos_api.resumo(horas=horas))


@roteador.get("/api/gastos-api")
async def painel_gastos_api(_usuario: auth.Usuario = Depends(auth.exigir_modulo("gastos_api"))):
    """Gasto e saldo restante de cada API, para saber quando recarregar."""
    return await run_in_threadpool(custos_api.painel)


@roteador.post("/api/gastos-api/{fornecedor}/saldo")
async def informar_saldo_da_api(
    fornecedor: str,
    corpo: SaldoInformado,
    usuario: auth.Usuario = Depends(auth.exigir_modulo("gastos_api")),
) -> dict[str, Any]:
    """Crédito que o escritório vê hoje na conta de uma API que não informa o saldo."""
    try:
        return await run_in_threadpool(lambda: custos_api.informar_saldo(fornecedor, corpo.valor, por=usuario.nome))
    except ValueError as erro:
        raise HTTPException(400, str(erro)) from erro


@roteador.get("/api/gastos-api/uso")
async def uso_das_apis(
    dias: int = Query(default=30, ge=7, le=90),
    _usuario: auth.Usuario = Depends(auth.exigir_modulo("gastos_api")),
):
    """Uso por dia, por hora e por parte do sistema, com alerta quando hoje foge da média."""
    return await run_in_threadpool(lambda: custos_api.uso(dias=dias))
