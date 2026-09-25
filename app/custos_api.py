"""Telemetria de chamadas pagas, sem registrar conteúdo ou credenciais."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .banco import conectar

log = logging.getLogger("custos-api")


def _numero(valor: Any) -> int:
    try:
        return max(0, int(valor or 0))
    except (TypeError, ValueError):
        return 0


def _custo_usd(uso: dict[str, Any]) -> Decimal | None:
    """Extrai o custo efetivo quando o provedor o informa na resposta."""
    valor = uso.get("cost")
    if valor is None:
        return None
    try:
        custo = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return custo if custo >= 0 else None


def registrar(fornecedor: str, modelo: str, operacao: str, resposta: Any, *, latencia_ms: int | None = None) -> None:
    """Persiste consumo sem deixar uma falha de telemetria afetar a chamada paga."""
    try:
        uso = resposta.json().get("usage") or {}
    except Exception:
        uso = {}
    entrada = _numero(uso.get("prompt_tokens", uso.get("input_tokens", 0)))
    saida = _numero(uso.get("completion_tokens", uso.get("output_tokens", 0)))
    total = _numero(uso.get("total_tokens")) or entrada + saida
    custo = _custo_usd(uso)
    log.info(
        "api_usage fornecedor=%s modelo=%s operacao=%s input_tokens=%s output_tokens=%s total_tokens=%s custo_usd=%s",
        fornecedor, modelo, operacao, entrada, saida, total, custo,
    )
    try:
        with conectar(timeout=3) as con:
            con.execute(
                "INSERT INTO custos_api "
                "(id, criado_em, fornecedor, modelo, operacao, input_tokens, output_tokens, "
                "total_tokens, custo_usd, custo_estimado, status, erro, latencia_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    str(fornecedor)[:64], str(modelo)[:200], str(operacao)[:100],
                    entrada, saida, total, custo, 0, "SUCCESS", None, latencia_ms,
                ),
            )
    except Exception:
        # Observabilidade não pode parar OCR, triagem ou criação de caso.
        log.warning("Não foi possível persistir a telemetria de custo.", exc_info=True)


def registrar_falha(fornecedor: str, modelo: str, operacao: str, erro: Exception | str, *, latencia_ms: int | None = None) -> None:
    """Registra recusa, timeout ou erro de rede sem conteúdo da requisição."""
    try:
        with conectar(timeout=3) as con:
            con.execute(
                "INSERT INTO custos_api (id, criado_em, fornecedor, modelo, operacao, input_tokens, output_tokens, total_tokens, custo_usd, custo_estimado, status, erro, latencia_ms) VALUES (?, ?, ?, ?, ?, 0, 0, 0, NULL, 0, 'ERROR', ?, ?)",
                (str(uuid.uuid4()), datetime.now(timezone.utc).isoformat(timespec="seconds"), str(fornecedor)[:64], str(modelo)[:200], str(operacao)[:100], str(erro)[:800], latencia_ms),
            )
    except Exception:
        log.warning("Não foi possível persistir falha de API.", exc_info=True)


def resumo(*, horas: int = 24) -> dict[str, Any]:
    """Agregação para painel, sem prompt, documento ou credencial."""
    horas = max(1, min(int(horas), 24 * 30))
    with conectar(timeout=5) as con:
        totais = con.execute("SELECT COUNT(*) AS chamadas, SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, SUM(total_tokens) AS total_tokens, SUM(COALESCE(custo_usd,0)) AS custo_usd, SUM(CASE WHEN status='ERROR' THEN 1 ELSE 0 END) AS erros FROM custos_api WHERE criado_em >= DATEADD(hour, ?, SYSUTCDATETIME())", (-horas,)).fetchone() or {}
        por_modelo = con.execute("SELECT fornecedor, modelo, operacao, status, COUNT(*) AS chamadas, SUM(total_tokens) AS total_tokens, SUM(COALESCE(custo_usd,0)) AS custo_usd, AVG(CAST(latencia_ms AS float)) AS latencia_ms FROM custos_api WHERE criado_em >= DATEADD(hour, ?, SYSUTCDATETIME()) GROUP BY fornecedor, modelo, operacao, status ORDER BY chamadas DESC", (-horas,)).fetchall()
    return {"horas": horas, "totais": dict(totais), "por_modelo": [dict(x) for x in por_modelo]}
