"""`/api/chat` — a porta única de quem pergunta.

Todas as rotas filtram pelo `sub` do token: o histórico é de quem perguntou. Sessão de
outra pessoa responde `404`, e não `403` — dizer "existe, mas não é sua" já entrega que
ela existe.

As rotas são síncronas (`def`, não `async def`) de propósito: o FastAPI as roda no
threadpool, e o que acontece dentro delas é justamente o que não pode bloquear o laço de
eventos — consulta ao SQL Server, chamada ao agente, pesquisa na web.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status

from .. import armazenamento, auth, pesquisa_web
from ..agente import analista
from ..agente.config import config as config_do_agente
from . import destinos, documentos as documentos_lib, sessoes

roteador = APIRouter(prefix="/api/chat", tags=["chat"])

_SEM_SESSAO = "Conversa não encontrada."


@roteador.get("/estado")
def estado() -> dict[str, Any]:
    """O que o chat consegue fazer AGORA, para a tela não prometer o que não há.

    Os três destinos que dependem de serviço externo dizem se estão de pé. A tela usa
    isso para explicar antes da pergunta — "a pesquisa na web está desligada" dito no
    campo vale mais do que dito depois de trinta segundos de espera.
    """
    return {
        "web": pesquisa_web.configurada(),
        "analista": analista.ligado(),
        "agente": config_do_agente().ligado,
        "teto": sessoes.TETO,
        "modos": list(destinos.MODOS),
    }


@roteador.get("/sessoes")
def listar_sessoes(
    usuario: auth.Usuario = Depends(auth.usuario_atual),
) -> dict[str, Any]:
    """As sessões de quem entrou, da mais recente para a mais antiga (no máximo oito)."""
    return sessoes.listar(usuario.id)


@roteador.post("/sessoes", status_code=status.HTTP_201_CREATED)
def abrir_sessao(usuario: auth.Usuario = Depends(auth.usuario_atual)) -> dict[str, Any]:
    """Uma sessão vazia — ou a que já estava vazia, se houver.

    `apagadas` diz o que a poda levou para caber no teto. A tela precisa saber: uma barra
    lateral que encolhe sozinha, sem explicação, parece defeito.
    """
    return sessoes.abrir(usuario.id)


@roteador.get("/sessoes/{sessao_id}")
def detalhar_sessao(
    sessao_id: str, usuario: auth.Usuario = Depends(auth.usuario_atual)
) -> dict[str, Any]:
    sessao = sessoes.detalhar(sessao_id, usuario.id)
    if sessao is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _SEM_SESSAO)
    return sessao


@roteador.post("/sessoes/{sessao_id}/mensagens")
def perguntar(
    sessao_id: str,
    mensagem: str = Body(..., embed=True, min_length=1, max_length=10_000),
    modo: str = Body("AUTO", embed=True),
    caso_id: str | None = Body(None, embed=True),
    usuario: auth.Usuario = Depends(auth.usuario_atual),
) -> dict[str, Any]:
    """A pergunta. Quem decide o destino é o servidor — a tela não adivinha.

    `modo` é o pedido explícito ("Pesquisar na web"); `caso_id` é a ORDEM de quem clicou
    num caso da lista de desambiguação, e não o caso da sessão.
    """
    resposta = sessoes.responder(
        sessao_id, mensagem, usuario.id, modo=modo, caso_escolhido=caso_id
    )
    if resposta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _SEM_SESSAO)
    return resposta


@roteador.patch("/sessoes/{sessao_id}/caso")
def fixar_caso(
    sessao_id: str,
    caso_id: str | None = Body(None, embed=True),
    usuario: auth.Usuario = Depends(auth.usuario_atual),
) -> dict[str, Any]:
    """Cola a sessão a um caso, ou a solta (`null`) para voltar a falar do escritório.

    Trocar de caso zera o `conversa_ref`: o fio do agente pertence ao caso que saiu, e
    reaproveitá-lo pediria uma resposta sobre um caso com o histórico de outro.
    """
    sessao = sessoes.detalhar(sessao_id, usuario.id)
    if sessao is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _SEM_SESSAO)

    if caso_id is None:
        armazenamento.atualizar_sessao_de_chat(sessao_id, resumo="", soltar_caso=True)
        return sessoes.detalhar(sessao_id, usuario.id) or sessao

    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Caso não encontrado.")
    if sessao["caso_id"] != caso_id:
        armazenamento.atualizar_sessao_de_chat(sessao_id, soltar_caso=True)
    armazenamento.atualizar_sessao_de_chat(
        sessao_id, caso_id=caso_id, resumo=str(caso.get("cliente") or "")
    )
    return sessoes.detalhar(sessao_id, usuario.id) or sessao


@roteador.delete("/sessoes/{sessao_id}", status_code=status.HTTP_204_NO_CONTENT)
def apagar_sessao(
    sessao_id: str, usuario: auth.Usuario = Depends(auth.usuario_atual)
) -> None:
    if not sessoes.apagar(sessao_id, usuario.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, _SEM_SESSAO)


@roteador.get("/casos/{caso_id}/documentos")
def documentos_do_caso(
    caso_id: str, _: auth.Usuario = Depends(auth.usuario_atual)
) -> dict[str, Any]:
    """O material do caso, para o botão "Ver aqui" da conversa.

    A mesma leitura que a resposta já usou (`chat.documentos`), servida à parte para o
    atalho que o advogado abre depois — inclusive numa sessão reaberta amanhã, quando a
    mensagem gravada já não reflete o que entrou no caso desde então.
    """
    painel = documentos_lib.montar(caso_id)
    if painel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Caso não encontrado.")
    return painel
