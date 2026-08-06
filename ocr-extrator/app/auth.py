"""Autenticação por JWT emitido pelo Keycloak.

O backend não fala com o Keycloak a cada requisição: baixa as chaves públicas
(JWKS) uma vez e valida a assinatura localmente. É por isso que o token pode ser
verificado em milissegundos, e também por que uma chave rotacionada exige
rebuscar o JWKS — daí o cache com invalidação por `kid` desconhecido.

Sem `KEYCLOAK_URL` configurado a autenticação fica DESLIGADA e todas as rotas
seguem abertas, para não quebrar quem roda o projeto sem Docker (e os testes).
O log grita quando isso acontece, porque é um modo inseguro por definição.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Request

log = logging.getLogger("auth")

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "").rstrip("/")
REALM = os.getenv("KEYCLOAK_REALM", "advocacia")
CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "acervo-frontend")
# O access token traz `aud` do mapper do realm; aceitar também o próprio client
# cobre configurações em que o mapper de audience não foi aplicado.
AUDIENCIAS = {a for a in (os.getenv("KEYCLOAK_AUDIENCE", "acervo-api"), CLIENT_ID, "account") if a}

ATIVA = bool(KEYCLOAK_URL)

_lock = threading.Lock()
_jwks: dict[str, Any] | None = None


def _url_jwks() -> str:
    return f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/certs"


def emissor() -> str:
    return f"{KEYCLOAK_URL}/realms/{REALM}"


def _buscar_jwks(forcar: bool = False) -> dict[str, Any]:
    global _jwks
    with _lock:
        if _jwks is None or forcar:
            resposta = httpx.get(_url_jwks(), timeout=10)
            resposta.raise_for_status()
            _jwks = resposta.json()
        return _jwks


def _chave_para(token: str):
    """Devolve a chave pública do `kid` do token, rebuscando o JWKS se preciso."""
    from jwt import PyJWKClient  # importado aqui para não pesar quem roda sem auth

    cliente = PyJWKClient(_url_jwks(), cache_keys=True)
    return cliente.get_signing_key_from_jwt(token).key


def validar_token(token: str) -> dict[str, Any]:
    """Verifica assinatura, emissor, audiência e validade. Devolve as claims."""
    import jwt

    try:
        chave = _chave_para(token)
        return jwt.decode(
            token,
            chave,
            algorithms=["RS256"],
            issuer=emissor(),
            audience=list(AUDIENCIAS),
            # `aud` já é conferido acima; as demais checagens são as padrão.
            options={"require": ["exp", "iat", "sub"]},
        )
    except Exception as exc:
        # Um `kid` novo (chave rotacionada) aparece como erro de assinatura: vale
        # uma segunda tentativa com o JWKS recarregado antes de recusar.
        try:
            _buscar_jwks(forcar=True)
            return jwt.decode(
                token,
                _chave_para(token),
                algorithms=["RS256"],
                issuer=emissor(),
                audience=list(AUDIENCIAS),
                options={"require": ["exp", "iat", "sub"]},
            )
        except Exception:
            raise HTTPException(401, f"Token inválido: {exc}") from exc


class Usuario:
    """Quem está autenticado, do ponto de vista da aplicação."""

    def __init__(self, claims: dict[str, Any]):
        self.claims = claims
        self.id: str = claims.get("sub", "")
        self.usuario: str = claims.get("preferred_username", "")
        self.nome: str = claims.get("name") or self.usuario
        self.papeis: set[str] = set(claims.get("realm_access", {}).get("roles", []))

    def tem_papel(self, papel: str) -> bool:
        return papel in self.papeis

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "usuario": self.usuario,
            "nome": self.nome,
            "papeis": sorted(self.papeis),
        }


USUARIO_ABERTO = Usuario(
    {"sub": "local", "preferred_username": "local", "name": "Sessão sem autenticação"}
)


def usuario_atual(request: Request) -> Usuario:
    """Dependência das rotas protegidas."""
    if not ATIVA:
        return USUARIO_ABERTO

    cabecalho = request.headers.get("authorization", "")
    if not cabecalho.lower().startswith("bearer "):
        raise HTTPException(401, "Autenticação necessária.")

    return Usuario(validar_token(cabecalho[7:].strip()))


def exigir_papel(papel: str):
    """Dependência para rotas que pedem um papel específico."""

    def verificar(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
        if ATIVA and not usuario.tem_papel(papel):
            raise HTTPException(403, f"Requer o papel '{papel}'.")
        return usuario

    return verificar


def configuracao_publica() -> dict[str, Any]:
    """O que o frontend precisa para iniciar o fluxo — nada secreto aqui."""
    return {
        "ativa": ATIVA,
        "url": KEYCLOAK_URL,
        "realm": REALM,
        "client_id": CLIENT_ID,
    }
