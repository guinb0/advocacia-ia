"""Portal do cliente: acesso pela senha do caso e envio de documentos."""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)

from .. import armazenamento, casos, portal
from .registro_documentos import _registrar_documento, _registrar_lote

roteador = APIRouter()


# ------------------------------------------------------ portal do cliente
#
# Estas rotas são públicas (não passam pelo Keycloak): quem as protege é a senha
# do caso. Cada uma confere a sessão do portal por conta própria — não há
# dependência global que faça isso por elas.


def _caso_do_portal(token: str, request: Request) -> dict[str, Any]:
    """Resolve o caso pelo token E exige uma sessão válida deste caso."""
    caso = armazenamento.obter_caso_por_token(token)
    if caso is None:
        # Mesma resposta de sessão inválida: não confirmamos se o link existe.
        raise HTTPException(404, "Link inválido ou expirado.")

    cabecalho = request.headers.get("authorization", "")
    sessao = cabecalho[7:].strip() if cabecalho.lower().startswith("bearer ") else ""
    if not portal.validar_sessao(sessao, token):
        raise HTTPException(401, "Informe a senha para acessar seus documentos.")
    return caso


@roteador.post("/api/portal/{token}/entrar")
def portal_entrar(token: str, senha: str = Form(...)):
    espera = portal.bloqueado(token)
    if espera > 0:
        raise HTTPException(
            429,
            f"Muitas tentativas. Tente novamente em {espera // 60 + 1} minuto(s) "
            "ou peça uma senha nova ao escritório.",
        )

    caso = armazenamento.obter_caso_por_token(token)
    # Link inexistente e senha errada devolvem a mesma coisa, para o link não
    # virar um oráculo que diz quais casos existem.
    if caso is None or not caso.get("portal_senha_hash"):
        portal.registrar_falha(token)
        raise HTTPException(401, "Link ou senha incorretos.")

    if not portal.conferir_senha(senha, caso["portal_senha_hash"], caso["portal_sal"]):
        portal.registrar_falha(token)
        raise HTTPException(401, "Link ou senha incorretos.")

    portal.limpar_tentativas(token)
    return {**portal.criar_sessao(token), "cliente": caso["cliente"]}


@roteador.get("/api/portal/{token}/situacao")
def portal_situacao(token: str, request: Request):
    """O checklist na visão do cliente: o que chegou e o que falta."""
    caso = _caso_do_portal(token, request)
    situacao = casos.montar_situacao(caso["id"])
    if situacao is None:
        raise HTTPException(404, "Caso não encontrado.")
    return casos.visao_do_cliente(situacao)


@roteador.post("/api/portal/{token}/documentos", status_code=201)
async def portal_enviar(
    token: str,
    request: Request,
    arquivo: UploadFile = File(...),
    item: str = Form(""),
):
    """Upload feito pelo cliente. Mesmo caminho do advogado, resposta enxuta.

    O item deixou de ser obrigatório: o cliente pode mandar o documento pela
    linha do checklist (e aí ele é um palpite) ou sem linha nenhuma.
    """
    caso = _caso_do_portal(token, request)
    await _registrar_documento(caso, item, arquivo, "pt", False)

    situacao = casos.montar_situacao(caso["id"])
    return casos.visao_do_cliente(situacao) if situacao else {}


@roteador.post("/api/portal/{token}/documentos/lote", status_code=201)
async def portal_enviar_lote(
    token: str,
    request: Request,
    arquivos: list[UploadFile] = File(...),
):
    """Envio em massa pelo cliente: manda tudo, o sistema separa.

    É o caminho que tira do cliente a tarefa de saber o que é cada papel — ele
    fotografa a pilha inteira e cada arquivo acha o próprio item do checklist.
    """
    caso = _caso_do_portal(token, request)
    resultado = await _registrar_lote(caso, arquivos, "pt")

    situacao = casos.montar_situacao(caso["id"])
    return {
        **resultado,
        "situacao": casos.visao_do_cliente(situacao) if situacao else {},
    }
