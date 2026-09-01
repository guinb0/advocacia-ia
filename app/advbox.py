"""Consultas somente leitura na API oficial da ADVBOX."""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

BASE_PADRAO = "https://app.advbox.com.br/api/v1"
TIMEOUT = 20.0

roteador = APIRouter(prefix="/api/advbox", tags=["advbox"])


def _env(nome: str, padrao: str = "") -> str:
    return (os.getenv(nome, padrao) or "").strip()


def ativa() -> bool:
    return bool(_env("ADVBOX_API_TOKEN"))


async def _get(
    caminho: str,
    *,
    params: dict[str, Any] | None = None,
    http: httpx.AsyncClient | None = None,
) -> Any:
    token = _env("ADVBOX_API_TOKEN")
    if not token:
        raise HTTPException(
            503,
            "Integração ADVBOX desligada: gere o API Token na ADVBOX e configure "
            "ADVBOX_API_TOKEN no .env.",
        )
    base = _env("ADVBOX_BASE_URL", BASE_PADRAO).rstrip("/")

    async def executar(cliente: httpx.AsyncClient) -> httpx.Response:
        return await cliente.get(
            base + caminho,
            params={k: v for k, v in (params or {}).items() if v is not None},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )

    try:
        if http is None:
            async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as cliente:
                resposta = await executar(cliente)
        else:
            resposta = await executar(http)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "A ADVBOX não respondeu. Tente novamente.") from exc

    if resposta.status_code in (301, 302, 401, 403):
        raise HTTPException(502, "A ADVBOX recusou o API Token configurado.")
    if resposta.status_code == 404:
        raise HTTPException(404, "Registro não encontrado na ADVBOX.")
    if resposta.status_code == 429:
        raise HTTPException(503, "Limite temporário de consultas da ADVBOX atingido.")
    if resposta.status_code == 204:
        return {"data": []}
    if resposta.is_error:
        raise HTTPException(502, f"A ADVBOX devolveu erro HTTP {resposta.status_code}.")
    try:
        return resposta.json()
    except ValueError as exc:
        raise HTTPException(502, "A ADVBOX devolveu uma resposta inválida.") from exc


@roteador.get("/config")
async def configuracao() -> dict[str, Any]:
    return {"ativa": ativa(), "somente_leitura": True}


@roteador.get("/clientes")
async def clientes(
    nome: str | None = None,
    email: str | None = None,
    identificacao: str | None = None,
    telefone: str | None = None,
    limite: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> Any:
    return await _get("/customers", params={
        "name": nome, "email": email, "identification": identificacao,
        "phone": telefone, "limit": limite, "offset": offset,
    })


@roteador.get("/clientes/{cliente_id}")
async def cliente(cliente_id: int) -> Any:
    return await _get(f"/customers/{cliente_id}")


@roteador.get("/processos")
async def processos(
    nome: str | None = None,
    numero_processo: str | None = None,
    cliente_id: int | None = None,
    responsavel: str | None = None,
    fase: str | None = None,
    limite: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Any:
    return await _get("/lawsuits", params={
        "name": nome, "process_number": numero_processo, "customer_id": cliente_id,
        "responsible": responsavel, "stage": fase, "limit": limite, "offset": offset,
    })


@roteador.get("/processos/{processo_id}")
async def processo(processo_id: int) -> Any:
    return await _get(f"/lawsuits/{processo_id}")


@roteador.get("/processos/{processo_id}/historico")
async def historico(
    processo_id: int,
    situacao: str = Query("all", pattern="^(all|pending|completed)$"),
) -> Any:
    return await _get(f"/history/{processo_id}", params={"status": situacao})


@roteador.get("/processos/{processo_id}/movimentacoes")
async def movimentacoes(
    processo_id: int,
    origem: str | None = Query(None, pattern="^(TRIBUNAL|MANUAL)$"),
) -> Any:
    return await _get(f"/movements/{processo_id}", params={"origin": origem})


@roteador.get("/configuracoes")
async def configuracoes_advbox() -> Any:
    return await _get("/settings")
