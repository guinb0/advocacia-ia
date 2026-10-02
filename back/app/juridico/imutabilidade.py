"""Invariantes do PETITION_PLAN final.

O plano é a fronteira entre decisão jurídica e redação.  Depois de finalizado,
qualquer divergência nos objetos jurídicos é falha de pipeline, não oportunidade
para um revisor de texto "consertar" o documento.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


_CAMPOS_IMUTAVEIS = (
    "petition_date", "fatos", "teses", "pedidos", "valor_da_causa_calculado",
    "case_facts", "authorities", "calculations", "tabelas",
)


class MutacaoDoPlano(RuntimeError):
    """Uma etapa posterior tentou mudar a decisão jurídica final."""


def _normalizar(valor: Any) -> Any:
    if isinstance(valor, dict):
        return {str(k): _normalizar(v) for k, v in sorted(valor.items(), key=lambda x: str(x[0]))
                if not str(k).startswith("_")}
    if isinstance(valor, list):
        return [_normalizar(v) for v in valor]
    if isinstance(valor, tuple):
        return [_normalizar(v) for v in valor]
    return valor


def congelar(plano: dict[str, Any]) -> dict[str, Any]:
    """Snapshot serializável somente da superfície jurídica autorizada."""
    return {campo: _normalizar(copy.deepcopy(plano.get(campo))) for campo in _CAMPOS_IMUTAVEIS}


def impressao(plano: dict[str, Any]) -> str:
    bruto = json.dumps(congelar(plano), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def verificar(snapshot: dict[str, Any], plano: dict[str, Any], *, etapa: str) -> None:
    atual = congelar(plano)
    if atual == snapshot:
        return
    alterados = [campo for campo in _CAMPOS_IMUTAVEIS if snapshot.get(campo) != atual.get(campo)]
    raise MutacaoDoPlano(
        f"PETITION_PLAN_FINALIZED foi alterado após sua finalização ({etapa}): " + ", ".join(alterados)
    )


def validar(plano: dict[str, Any]) -> list[str]:
    """Valida as invariantes estruturais sem LLM."""
    erros: list[str] = []
    pedidos = plano.get("pedidos") or []
    vistos: set[str] = set()
    for pedido in pedidos:
        if not isinstance(pedido, dict):
            erros.append("pedido inválido fora do esquema estruturado")
            continue
        pid = str(pedido.get("request_id") or pedido.get("id") or "")
        if not pid or pid in vistos:
            erros.append(f"request_id ausente ou duplicado: {pid or '<vazio>'}")
        vistos.add(pid)
        if not pedido.get("factual_support") and not pedido.get("de_praxe"):
            erros.append(f"{pid}: pedido sem factual_support")
        if not pedido.get("authority_ids") and not pedido.get("de_praxe"):
            erros.append(f"{pid}: pedido sem authority_ids")
        monetario = pedido.get("value") not in (None, "") or pedido.get("valor") not in (None, "")
        if monetario and not pedido.get("calculation_id"):
            erros.append(f"{pid}: pedido monetário sem calculation_id")
    valor = (plano.get("valor_da_causa_calculado") or {}).get("valor")
    if valor is not None:
        try:
            from .calculos import valor_da_causa
            calculado = valor_da_causa(pedidos).get("valor")
            if calculado != valor:
                erros.append("valor_da_causa_calculado diverge da soma canônica dos pedidos")
        except Exception as erro:  # pragma: no cover - transformado em diagnóstico do pipeline
            erros.append(f"não foi possível validar valor da causa: {type(erro).__name__}")
    return erros
