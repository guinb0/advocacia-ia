import asyncio

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import usuarios


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "scheme": "https",
        "path": "/api/user/authenticate",
        "headers": [],
        "client": ("203.0.113.10", 4321),
        "server": ("app.forenseflow.com.br", 443),
    })


class _ClienteSiteverify:
    def __init__(self, resultado):
        self.resultado = resultado
        self.payload = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url, json):
        self.payload = json
        return httpx.Response(200, json=self.resultado, request=httpx.Request("POST", url))


def _configurar(monkeypatch):
    monkeypatch.setenv("NEXT_PUBLIC_TURNSTILE_SITE_KEY", "site-publica")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "segredo")
    monkeypatch.setenv("TURNSTILE_HOSTNAMES", "app.forenseflow.com.br")


def test_turnstile_valida_token_acao_hostname_e_ip(monkeypatch):
    _configurar(monkeypatch)
    cliente = _ClienteSiteverify({
        "success": True,
        "action": "login",
        "hostname": "app.forenseflow.com.br",
    })
    monkeypatch.setattr(usuarios.httpx, "AsyncClient", lambda **_kwargs: cliente)

    asyncio.run(usuarios._validar_turnstile("token-valido", _request()))

    assert cliente.payload["response"] == "token-valido"
    assert cliente.payload["remoteip"] == "203.0.113.10"
    assert cliente.payload["secret"] == "segredo"


@pytest.mark.parametrize("resultado", [
    {"success": False, "action": "login", "hostname": "app.forenseflow.com.br"},
    {"success": True, "action": "cadastro", "hostname": "app.forenseflow.com.br"},
    {"success": True, "action": "login", "hostname": "outro.example"},
])
def test_turnstile_recusa_prova_invalida(monkeypatch, resultado):
    _configurar(monkeypatch)
    monkeypatch.setattr(
        usuarios.httpx, "AsyncClient", lambda **_kwargs: _ClienteSiteverify(resultado)
    )

    with pytest.raises(HTTPException) as erro:
        asyncio.run(usuarios._validar_turnstile("token", _request()))

    assert erro.value.status_code == 400


def test_turnstile_nao_bloqueia_login_com_configuracao_incompleta(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "segredo")
    monkeypatch.delenv("NEXT_PUBLIC_TURNSTILE_SITE_KEY", raising=False)

    asyncio.run(usuarios._validar_turnstile("", _request()))
