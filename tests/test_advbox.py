import asyncio
import os

import httpx
import pytest
from fastapi import HTTPException

from app import advbox


def executar(coro):
    return asyncio.run(coro)


def test_desligada_sem_token(monkeypatch):
    monkeypatch.setenv("ADVBOX_API_TOKEN", "")
    with pytest.raises(HTTPException) as erro:
        executar(advbox._get("/lawsuits"))
    assert erro.value.status_code == 503


def test_consulta_usa_bearer_e_get(monkeypatch):
    monkeypatch.setenv("ADVBOX_API_TOKEN", "segredo-teste")
    monkeypatch.setenv("ADVBOX_BASE_URL", "https://app.advbox.com.br/api/v1")

    def responder(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer segredo-teste"
        assert request.url.path == "/api/v1/lawsuits"
        assert request.url.params["limit"] == "10"
        return httpx.Response(200, json={"data": [], "totalCount": 0})

    async def consultar():
        async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http:
            return await advbox._get("/lawsuits", params={"limit": 10}, http=http)

    assert executar(consultar())["totalCount"] == 0


def test_nao_segue_redirect_para_login(monkeypatch):
    monkeypatch.setenv("ADVBOX_API_TOKEN", "invalido")

    async def consultar():
        transporte = httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"Location": "/login"})
        )
        async with httpx.AsyncClient(transport=transporte) as http:
            return await advbox._get("/customers", http=http)

    with pytest.raises(HTTPException) as erro:
        executar(consultar())
    assert erro.value.status_code == 502
