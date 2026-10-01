"""Consulta manual do plano e da matriz de providers, sem disparar coleta oculta."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .pesquisa_jurisprudencial import planejar, providers_padrao
from .pesquisa_jurisprudencial import PrecedenteEstruturado
from .precedentes_verificados import salvar

roteador = APIRouter(prefix="/api/jurisprudencia", tags=["jurisprudência"])


class PedidoPlano(BaseModel):
    uf: str = ""
    contexto: str = Field(default="", max_length=12000)
    plano: dict[str, Any] = Field(default_factory=dict)


class PedidoConfirmacao(BaseModel):
    precedente: dict[str, Any]
    texto_original: str = Field(min_length=1)
    organization_id: str = ""
    gerar_embedding: bool = False


@roteador.get("/providers")
def providers() -> list[dict[str, Any]]:
    """O que a interface pode oferecer e por que um provider não roda sozinho."""
    return [vars(p.capacidade()) for _, p in sorted(providers_padrao().items())]


@roteador.post("/plano")
def plano(pedido: PedidoPlano) -> dict[str, Any]:
    """Prévia auditável das consultas; execução externa só entra com provider homologado."""
    return planejar(pedido.plano, pedido.contexto, uf=pedido.uf).como_dict()


@roteador.post("/precedentes/verificados", status_code=201)
def confirmar_precedente(pedido: PedidoConfirmacao) -> dict[str, int]:
    """Entrada manual após conferência da decisão oficial; não aceita snippet."""
    precedente = PrecedenteEstruturado(**pedido.precedente)
    return {"fonte_id": salvar(precedente, texto_original=pedido.texto_original,
                                organization_id=pedido.organization_id,
                                gerar_embedding=pedido.gerar_embedding)}
