"""Categorias de caso."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import categorias

roteador = APIRouter()


@roteador.get("/api/categorias")
def listar_categorias():
    """Categorias de processo, cada uma com seu checklist de documentos."""
    return {"categorias": [c.to_dict() for c in categorias.listar()]}


@roteador.get("/api/categorias/{codigo}")
def obter_categoria(codigo: str):
    categoria = categorias.obter(codigo)
    if categoria is None:
        raise HTTPException(404, f"Categoria '{codigo}' não encontrada.")
    return categoria.to_dict()
