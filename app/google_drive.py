from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import auth, cripto
from .banco import PREFIXO, SCHEMA, conectar

log = logging.getLogger("google_drive")

roteador = APIRouter(prefix="/api/drive", tags=["google-drive"])

_TABELA = f"{SCHEMA}.{PREFIXO}config_google_drive"
URL_PORTAL = os.getenv("URL_PORTAL", "http://localhost:3000").rstrip("/")
ESCOPOS = "https://www.googleapis.com/auth/drive.file openid email"
NOME_PASTA = "Acervo — Gravações de entrevistas"
BLOCO_UPLOAD = 8 * 1024 * 1024

ESQUEMA = f"""
IF OBJECT_ID('{_TABELA}') IS NULL
CREATE TABLE {_TABELA} (
    id                     int           NOT NULL CONSTRAINT pk_acervo_config_google_drive PRIMARY KEY,
    client_id              nvarchar(300) NULL,
    client_secret_cifrado  nvarchar(max) NULL,
    refresh_token_cifrado  nvarchar(max) NULL,
    conta_email            nvarchar(200) NULL,
    pasta_id               nvarchar(200) NULL,
    conectado_em           varchar(40)   NULL,
    atualizado_em          varchar(40)   NOT NULL
)
"""

_token_cache: dict[str, Any] = {"valor": "", "expira": 0.0}


class Credenciais(BaseModel):
    client_id: str
    client_secret: str


def inicializar() -> None:
    with conectar() as con:
        con.execute(ESQUEMA)
        con.commit()


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _linha() -> Any:
    with conectar() as con:
        return con.execute(f"SELECT * FROM {_TABELA} WHERE id = 1").fetchone()


def _salvar(**campos: Any) -> None:
    campos["atualizado_em"] = _agora()
    with conectar() as con:
        existe = con.execute(f"SELECT 1 FROM {_TABELA} WHERE id = 1").fetchone()
        if existe:
            atribuicoes = ", ".join(f"{coluna} = ?" for coluna in campos)
            con.execute(f"UPDATE {_TABELA} SET {atribuicoes} WHERE id = 1", tuple(campos.values()))
        else:
            colunas = ", ".join(["id", *campos])
            marcas = ", ".join("?" for _ in range(len(campos) + 1))
            con.execute(f"INSERT INTO {_TABELA} ({colunas}) VALUES ({marcas})", (1, *campos.values()))
        con.commit()


def _credenciais() -> tuple[str, str]:
    cid = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    segredo = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if cid and segredo:
        return cid, segredo
    linha = _linha()
    if linha and linha["client_id"] and linha["client_secret_cifrado"]:
        return str(linha["client_id"]), cripto.decifrar(str(linha["client_secret_cifrado"]))
    return "", ""


def _redirect_uri() -> str:
    return f"{URL_PORTAL}/api/drive/callback"


def _segredo_estado() -> str:
    segredo = os.getenv("JWT_SECRET", "").strip() or os.getenv("PORTAL_SEGREDO", "").strip()
    if not segredo:
        raise HTTPException(503, "Defina JWT_SECRET no servidor antes de conectar o Google Drive.")
    return segredo


def conectado() -> bool:
    linha = _linha()
    return bool(linha and linha["refresh_token_cifrado"])


def _status() -> dict[str, Any]:
    linha = _linha()
    cid, _ = _credenciais()
    pasta = str(linha["pasta_id"] or "") if linha else ""
    return {
        "configurado": bool(cid),
        "credenciais_do_ambiente": bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()),
        "conectado": bool(linha and linha["refresh_token_cifrado"]),
        "conta": str(linha["conta_email"] or "") if linha else "",
        "pasta_url": f"https://drive.google.com/drive/folders/{pasta}" if pasta else "",
        "redirect_uri": _redirect_uri(),
    }


def _pedir_token(dados: dict[str, str]) -> dict[str, Any]:
    resposta = httpx.post("https://oauth2.googleapis.com/token", data=dados, timeout=30)
    if resposta.status_code != 200:
        raise HTTPException(502, f"O Google recusou o acesso: {resposta.text[:300]}")
    return resposta.json()


def _token_acesso() -> str:
    if _token_cache["valor"] and time.time() < float(_token_cache["expira"]):
        return str(_token_cache["valor"])
    linha = _linha()
    if not linha or not linha["refresh_token_cifrado"]:
        raise HTTPException(409, "O Google Drive não está conectado.")
    cid, segredo = _credenciais()
    dados = _pedir_token(
        {
            "client_id": cid,
            "client_secret": segredo,
            "refresh_token": cripto.decifrar(str(linha["refresh_token_cifrado"])),
            "grant_type": "refresh_token",
        }
    )
    _token_cache["valor"] = str(dados["access_token"])
    _token_cache["expira"] = time.time() + int(dados.get("expires_in", 3600)) - 120
    return str(dados["access_token"])


def _criar_pasta(token: str) -> str:
    resposta = httpx.post(
        "https://www.googleapis.com/drive/v3/files",
        params={"fields": "id"},
        headers={"Authorization": f"Bearer {token}"},
        json={"name": NOME_PASTA, "mimeType": "application/vnd.google-apps.folder"},
        timeout=30,
    )
    if resposta.status_code not in (200, 201):
        raise HTTPException(502, f"Não foi possível criar a pasta no Google Drive: {resposta.text[:300]}")
    return str(resposta.json()["id"])


def _pagina(titulo: str, texto: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'><title>Google Drive</title>"
        "<body style='font-family:system-ui;max-width:520px;margin:48px auto;padding:0 16px'>"
        f"<h2>{escape(titulo)}</h2><p>{escape(texto)}</p>"
        "<p>Pode fechar esta aba e voltar ao sistema.</p>"
        "<script>setTimeout(function(){window.close()},2500)</script></body>"
    )


def _enviar(arquivo: UploadFile, nome: str) -> dict[str, str]:
    token = _token_acesso()
    linha = _linha()
    pasta = str(linha["pasta_id"] or "") if linha else ""
    tipo = arquivo.content_type or "application/octet-stream"
    arquivo.file.seek(0, 2)
    tamanho = arquivo.file.tell()
    for tentativa in range(2):
        if not pasta:
            pasta = _criar_pasta(token)
            _salvar(pasta_id=pasta)
        inicio = httpx.post(
            "https://www.googleapis.com/upload/drive/v3/files",
            params={"uploadType": "resumable", "fields": "id,webViewLink"},
            headers={
                "Authorization": f"Bearer {token}",
                "X-Upload-Content-Type": tipo,
                "X-Upload-Content-Length": str(tamanho),
            },
            json={"name": nome, "parents": [pasta]},
            timeout=30,
        )
        if inicio.status_code == 404 and tentativa == 0:
            pasta = ""
            continue
        if inicio.status_code != 200 or "Location" not in inicio.headers:
            raise HTTPException(502, f"O Google Drive recusou o envio: {inicio.text[:300]}")
        arquivo.file.seek(0)

        def blocos():
            while True:
                bloco = arquivo.file.read(BLOCO_UPLOAD)
                if not bloco:
                    break
                yield bloco

        final = httpx.put(
            inicio.headers["Location"],
            content=blocos(),
            headers={"Content-Length": str(tamanho), "Content-Type": tipo},
            timeout=httpx.Timeout(60, read=1800, write=1800),
        )
        if final.status_code not in (200, 201):
            raise HTTPException(502, f"O envio ao Google Drive não terminou: {final.text[:300]}")
        dados = final.json()
        return {"id": str(dados.get("id", "")), "link": str(dados.get("webViewLink", ""))}
    raise HTTPException(502, "Não foi possível encontrar a pasta do Google Drive.")


@roteador.get("/status", dependencies=[Depends(auth.usuario_atual)])
async def status() -> dict[str, Any]:
    return await run_in_threadpool(_status)


@roteador.post("/credenciais", dependencies=[Depends(auth.exigir_modulo("usuarios"))])
async def salvar_credenciais(dados: Credenciais) -> dict[str, Any]:
    cid = dados.client_id.strip()
    segredo = dados.client_secret.strip()
    if not cid or not segredo:
        raise HTTPException(422, "Informe o Client ID e o Client Secret.")
    await run_in_threadpool(
        _salvar, client_id=cid, client_secret_cifrado=cripto.cifrar(segredo)
    )
    return await run_in_threadpool(_status)


@roteador.get("/conectar", dependencies=[Depends(auth.exigir_modulo("usuarios"))])
async def conectar_drive() -> dict[str, str]:
    cid, _ = await run_in_threadpool(_credenciais)
    if not cid:
        raise HTTPException(409, "Cadastre o Client ID e o Client Secret do Google antes de conectar.")
    estado = jwt.encode(
        {"proposito": "google-drive", "exp": datetime.now(timezone.utc) + timedelta(minutes=15)},
        _segredo_estado(),
        algorithm="HS256",
    )
    parametros = {
        "client_id": cid,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": ESCOPOS,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": estado,
    }
    return {"url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(parametros)}


@roteador.get("/callback")
def callback(code: str = "", state: str = "", error: str = "") -> HTMLResponse:
    if error:
        return _pagina("Conexão cancelada", "O Google Drive não foi conectado.")
    try:
        jwt.decode(state, _segredo_estado(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return _pagina("Link expirado", "Volte ao sistema e clique em “Conectar Google Drive” de novo.")
    cid, segredo = _credenciais()
    tokens = _pedir_token(
        {
            "code": code,
            "client_id": cid,
            "client_secret": segredo,
            "redirect_uri": _redirect_uri(),
            "grant_type": "authorization_code",
        }
    )
    refresh = tokens.get("refresh_token")
    if not refresh:
        return _pagina(
            "Autorização incompleta",
            "O Google não devolveu acesso permanente. Remova o acesso do Acervo na sua conta Google e conecte de novo.",
        )
    _token_cache["valor"] = str(tokens.get("access_token", ""))
    _token_cache["expira"] = time.time() + int(tokens.get("expires_in", 3600)) - 120
    email = ""
    if tokens.get("id_token"):
        email = str(jwt.decode(tokens["id_token"], options={"verify_signature": False}).get("email", ""))
    pasta = _criar_pasta(str(tokens["access_token"]))
    _salvar(
        refresh_token_cifrado=cripto.cifrar(str(refresh)),
        conta_email=email,
        pasta_id=pasta,
        conectado_em=_agora(),
    )
    return _pagina("Google Drive conectado", f"As gravações vão para a pasta “{NOME_PASTA}” de {email or 'sua conta'}.")


@roteador.post("/desconectar", dependencies=[Depends(auth.exigir_modulo("usuarios"))])
async def desconectar() -> dict[str, Any]:
    linha = await run_in_threadpool(_linha)
    if linha and linha["refresh_token_cifrado"]:
        try:
            httpx.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": cripto.decifrar(str(linha["refresh_token_cifrado"]))},
                timeout=15,
            )
        except Exception:  # noqa: BLE001
            log.warning("Falha ao revogar o acesso ao Google Drive", exc_info=True)
    _token_cache.update(valor="", expira=0.0)
    await run_in_threadpool(
        _salvar, refresh_token_cifrado=None, conta_email=None, pasta_id=None, conectado_em=None
    )
    return await run_in_threadpool(_status)


@roteador.post("/gravacoes", dependencies=[Depends(auth.usuario_atual)])
async def enviar_gravacao(arquivo: UploadFile = File(...), nome: str = Form("")) -> dict[str, str]:
    return await run_in_threadpool(_enviar, arquivo, (nome or arquivo.filename or "gravacao.webm").strip())
