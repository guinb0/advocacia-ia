"""Quando o Acervo se verifica sozinho. A fonte da verdade é o `beat_schedule` do Celery, não uma conta à parte."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

TAREFA = "app.tasks.acervo.sincronizar_acervo"
ENTRADA = "acervo-sincronizar"

#: Uma ronda concluída vale por este prazo; passado ele, a garantia sincroniza de novo (a semanal falhou ou não rodou).
PRAZO_DA_RONDA = timedelta(days=8)
#: Sincronização que falhou é tentada de novo depois deste intervalo — não a cada meia hora.
ESPERA_APOS_ERRO = timedelta(hours=6)
#: Acima disto, um EM_ANDAMENTO é processo que morreu no meio (o limite duro da tarefa é 30 min).
ANDAMENTO_ABANDONADO = timedelta(hours=2)

_DIAS = {"0": "domingo", "sun": "domingo", "1": "segunda-feira", "mon": "segunda-feira", "2": "terça-feira", "tue": "terça-feira",
         "3": "quarta-feira", "wed": "quarta-feira", "4": "quinta-feira", "thu": "quinta-feira", "5": "sexta-feira",
         "fri": "sexta-feira", "6": "sábado", "sat": "sábado"}


def ativa() -> bool:
    """Desligada por padrão: só sincroniza com `ACERVO_SINCRONIZACAO_ATIVA=1` (escreve no pgvector)."""
    return os.getenv("ACERVO_SINCRONIZACAO_ATIVA", "0").strip().lower() in {"1", "true", "sim", "yes"}


def documentos_agendados(manifesto: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None) -> list[str]:
    """Normas da ronda automática: `ACERVO_DOCUMENTOS_AGENDADOS` (ids separados por vírgula ou `todos`); padrão, a CLT."""
    if manifesto is None:
        from .sincronizacao import manifesto as carregar
        manifesto = carregar()
    legislacao = [i["id"] for i in manifesto if i.get("categoria", "legislacao") == "legislacao"]
    pedido = os.getenv("ACERVO_DOCUMENTOS_AGENDADOS", "clt-1943").strip().lower()
    if pedido in {"todos", "todas", "*"}:
        return legislacao
    ids = [x.strip() for x in pedido.split(",") if x.strip()]
    return [i for i in legislacao if i in ids]


def documentos_atrasados(armazenamento: Any, ids: list[str], agora: datetime | None = None) -> list[str]:
    """Das normas agendadas, as que precisam sincronizar agora: nunca sincronizadas, ronda vencida ou erro antigo."""
    agora = agora or datetime.now(UTC)
    saida = []
    for doc in ids:
        ultima = next(iter(armazenamento.sincronizacoes(document_id=doc, limite=1)), None)
        if not ultima:
            saida.append(doc)
            continue
        inicio = ultima.get("iniciada_em")
        if not isinstance(inicio, datetime):
            saida.append(doc)
            continue
        if inicio.tzinfo is None:
            inicio = inicio.replace(tzinfo=UTC)
        decorrido = agora - inicio
        status = str(ultima.get("status") or "")
        if status == "EM_ANDAMENTO":
            atrasada = decorrido > ANDAMENTO_ABANDONADO
        elif status == "ERRO":
            atrasada = decorrido > ESPERA_APOS_ERRO
        else:
            atrasada = decorrido > PRAZO_DA_RONDA
        if atrasada:
            saida.append(doc)
    return saida


def sincronizada_agora_pouco(armazenamento: Any, document_id: str, agora: datetime | None = None) -> bool:
    """Já há ronda em andamento ou concluída há menos de 2 h: a cópia duplicada na fila não roda de novo."""
    ultima = next(iter(armazenamento.sincronizacoes(document_id=document_id, limite=1)), None)
    inicio = (ultima or {}).get("iniciada_em")
    if not isinstance(inicio, datetime) or str(ultima.get("status") or "") == "ERRO":
        return False
    if inicio.tzinfo is None:
        inicio = inicio.replace(tzinfo=UTC)
    return (agora or datetime.now(UTC)) - inicio < ANDAMENTO_ABANDONADO


def _agendamento() -> Any | None:
    from ..celery_app import celery_app
    entrada = (celery_app.conf.beat_schedule or {}).get(ENTRADA)
    return entrada.get("schedule") if entrada else None


def proxima_execucao(agora: datetime | None = None, *, agendamento: Any | None = None) -> datetime | None:
    """Próximo disparo do beat depois de `agora`; None quando a sincronização automática está desligada."""
    if not ativa():
        return None
    agendamento = agendamento if agendamento is not None else _agendamento()
    if agendamento is None:
        return None
    agora = agora or datetime.now(UTC)
    if hasattr(agendamento, "remaining_estimate"):
        restante = agendamento.remaining_estimate(agora)
        return (agora + restante).astimezone(UTC)
    return agora + timedelta(seconds=float(agendamento))


def descricao(agendamento: Any | None = None) -> str:
    agendamento = agendamento if agendamento is not None else _agendamento()
    if agendamento is None:
        return "não agendada"
    horas = getattr(agendamento, "_orig_hour", None)
    minutos = getattr(agendamento, "_orig_minute", None)
    if horas is not None and minutos is not None:
        hora = f"{int(str(horas)):02d}:{int(str(minutos)):02d} (America/Sao_Paulo)"
        dia = str(getattr(agendamento, "_orig_day_of_week", "*")).strip().lower()
        if dia in ("*", ""):
            return f"diariamente às {hora}"
        return f"semanalmente ({_DIAS.get(dia, dia)}) às {hora}"
    return str(agendamento)
