"""Telemetria enxuta de chamadas pagas, sem registrar conteúdo ou credenciais."""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("custos-api")


def registrar(fornecedor: str, modelo: str, operacao: str, resposta: Any) -> None:
    """Registra tokens retornados pelo provedor; OCR sem uso explícito fica em zero."""
    try:
        uso = resposta.json().get("usage") or {}
    except Exception:
        uso = {}
    entrada = uso.get("prompt_tokens", uso.get("input_tokens", 0)) or 0
    saida = uso.get("completion_tokens", uso.get("output_tokens", 0)) or 0
    total = uso.get("total_tokens", 0) or 0
    log.info(
        "api_usage fornecedor=%s modelo=%s operacao=%s input_tokens=%s output_tokens=%s total_tokens=%s",
        fornecedor, modelo, operacao, entrada, saida, total,
    )
