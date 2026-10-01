"""Fila e métricas de revisão de petições."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, peticao_local, revisao

roteador = APIRouter()


# --------------------------------------------------------- REVISÃO DE PETIÇÕES
# Perfil Revisor: fila de petições a revisar, aprovação e métricas de atividade.
PodeRevisar = Depends(auth.exigir_modulo("revisao"))


def _quem_revisa(usuario: auth.Usuario) -> str:
    return usuario.usuario or getattr(usuario, "nome", "") or usuario.id or "revisor"


class PedidoConclusaoRevisao(BaseModel):
    #: "aprovada" (segue para assinatura) ou "ajustes" (volta ao redator).
    resultado: str


@roteador.get("/api/revisao/fila")
def revisao_fila(_usuario: auth.Usuario = PodeRevisar):
    """As petições que precisam de revisão, da mais antiga para a mais nova."""
    return {"pendentes": revisao.fila_pendentes()}


@roteador.post("/api/revisao/{caso_id}/iniciar", status_code=201)
def revisao_iniciar(caso_id: str, usuario: auth.Usuario = PodeRevisar):
    """Marca o início da revisão desta petição por este revisor (idempotente)."""
    if not peticao_local.existe(caso_id):
        raise HTTPException(404, "Não há petição para revisar neste caso.")
    return revisao.iniciar(caso_id, _quem_revisa(usuario), usuario.id)


@roteador.post("/api/revisao/{caso_id}/concluir")
def revisao_concluir(
    caso_id: str, pedido: PedidoConclusaoRevisao, usuario: auth.Usuario = PodeRevisar
):
    """Aprova a petição ou a devolve para ajustes, fechando a contagem do tempo."""
    if not peticao_local.existe(caso_id):
        raise HTTPException(404, "Não há petição para revisar neste caso.")
    try:
        return revisao.concluir(caso_id, _quem_revisa(usuario), pedido.resultado.strip(), usuario.id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@roteador.get("/api/revisao/metricas")
def revisao_metricas(minhas: bool = False, usuario: auth.Usuario = PodeRevisar):
    """Métricas de revisão. `minhas=true` recorta para o próprio revisor."""
    # O id vai junto: o recorte "minhas" é por identidade, não por nome de
    # exibição (ver `revisao.metricas`).
    if not minhas:
        return revisao.metricas()
    return revisao.metricas(_quem_revisa(usuario), usuario.id)
