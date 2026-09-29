"""Integração com o Tactiq (reuniões e transcrições)."""

from __future__ import annotations

from urllib.parse import quote

import httpx
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)
from fastapi.responses import RedirectResponse

from .. import auth, tactiq
from .comum import URL_PORTAL, log

roteador = APIRouter()


@roteador.get("/api/tactiq/status")
def tactiq_status(verificar: bool = False, usuario: auth.Usuario = Depends(auth.usuario_atual)):
    """Estado seguro: nunca devolve token ao navegador. `verificar` testa o token no Tactiq."""
    return tactiq.status(usuario.id, verificar)


@roteador.get("/api/tactiq/ferramentas")
def tactiq_ferramentas(usuario: auth.Usuario = Depends(auth.usuario_atual)):
    """Diagnóstico do MCP remoto; não expõe token nem conteúdo de reunião."""
    try:
        return {"ferramentas": tactiq.ferramentas(usuario.id)}
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, f"Não foi possível consultar o MCP do Tactiq: {exc}") from exc


@roteador.get("/api/tactiq/reunioes")
def tactiq_reunioes(usuario: auth.Usuario = Depends(auth.usuario_atual)):
    """Lista as reuniões que o advogado já pode ler no Tactiq."""
    try:
        return {"reunioes": tactiq.listar_reunioes(usuario.id)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Não foi possível carregar as reuniões do Tactiq agora.") from exc


@roteador.get("/api/tactiq/reunioes/{reuniao_id}/transcricao")
def tactiq_transcricao(reuniao_id: str, usuario: auth.Usuario = Depends(auth.usuario_atual)):
    """Lê a transcrição selecionada sem expor o token Tactiq ao navegador."""
    try:
        return tactiq.transcricao(usuario.id, reuniao_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Não foi possível carregar a transcrição do Tactiq agora.") from exc


def _callback_tactiq(request: Request) -> str:
    """URL pública do OAuth; nunca o host interno api:8100 atrás do proxy."""
    # Em produção URL_PORTAL é o domínio HTTPS que o advogado abriu. Usar
    # request.base_url ali registrava http://api:8100 no Tactiq, endereço que
    # não existe fora da rede Docker e faz o registro dinâmico ser recusado.
    if URL_PORTAL.startswith("https://"):
        return f"{URL_PORTAL}/api/tactiq/callback"
    return f"{str(request.base_url).rstrip('/')}/api/tactiq/callback"


@roteador.post("/api/tactiq/conectar")
def tactiq_conectar(request: Request, usuario: auth.Usuario = Depends(auth.usuario_atual)):
    try:
        return {"url": tactiq.iniciar(usuario.id, _callback_tactiq(request))}
    except httpx.HTTPStatusError as exc:
        log.warning("Tactiq recusou o registro OAuth: %s", exc.response.status_code)
        raise HTTPException(502, "O Tactiq recusou temporariamente a conexão. Tente novamente em alguns minutos.") from exc
    except httpx.RequestError as exc:
        log.warning("Tactiq indisponível: %s", exc)
        raise HTTPException(503, "Não foi possível alcançar o Tactiq agora. Tente novamente em instantes.") from exc
    except Exception as exc:
        log.exception("Falha ao iniciar OAuth Tactiq")
        raise HTTPException(503, f"Não foi possível preparar a conexão Tactiq: {exc}") from exc


@roteador.get("/api/tactiq/callback")
def tactiq_callback(
    request: Request, code: str = "", state: str = "", error: str = "", error_description: str = ""
):
    # O provedor volta pelo navegador, portanto a pessoa precisa cair novamente
    # DENTRO do escritório — e não na raiz, que é o login. O retorno anterior
    # para `/?tactiq=conectado` criava a aparência de que a conexão se perdeu.
    destino = f"{URL_PORTAL}/home?configuracao=configuracaoAssinatura&tactiq="
    if error:
        detalhe = (error_description or error)[:180]
        return RedirectResponse(f"{destino}cancelado&detalhe={quote(detalhe)}", status_code=303)
    if not code or not state:
        return RedirectResponse(f"{destino}erro", status_code=303)
    try:
        tactiq.concluir(state, code, _callback_tactiq(request))
    except Exception as exc:
        log.warning("Falha ao concluir OAuth Tactiq: %s", exc)
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"{destino}conectado", status_code=303)
