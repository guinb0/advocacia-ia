"""Fila durável no SQL Server, sem broker Redis/Celery.

O SQL é a fonte de verdade: reservar um job usa locks de linha e evita que duas
réplicas o executem; lease/heartbeat permite recuperar trabalho abandonado.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .banco import conectar

log = logging.getLogger(__name__)

# OCR pode levar vários minutos (subprocesso + provedor). Lease curto devolvia o
# job a outro worker no meio da leitura — produção usa 720s.
LEASE_S = int(os.getenv("FILA_SQL_LEASE_S", "720"))
WORKER_TTL_S = int(os.getenv("FILA_SQL_WORKER_TTL_S", "30"))
STALL_S = int(os.getenv("FILA_SQL_STALL_S", "600"))


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _evento(evento: str, **campos: Any) -> None:
    """Log estruturado rastreável: UPLOAD → OCR_QUEUED → … → CLASSIFICATION_*."""
    partes = " ".join(f"{chave}={valor!r}" for chave, valor in campos.items() if valor is not None)
    log.info("event=%s %s", evento, partes)


def heartbeat_worker(worker_id: str, fila: str = "ocr") -> None:
    agora = _agora().isoformat(timespec="seconds")
    with conectar() as con:
        cursor = con.execute(
            "UPDATE fila_workers SET estado='READY', heartbeat_em=?, atualizado_em=? WHERE worker_id=?",
            (agora, agora, worker_id),
        )
        if cursor.rowcount:
            return
        con.execute(
            "INSERT INTO fila_workers (worker_id, fila, estado, iniciado_em, heartbeat_em, atualizado_em) VALUES (?, ?, 'READY', ?, ?, ?)",
            (worker_id, fila, agora, agora, agora),
        )


def snapshot(fila: str = "ocr", esperados: int = 3) -> dict[str, Any]:
    """Saúde baseada em SQL: fila, lease/progresso e consumers com heartbeat."""
    agora = _agora()
    limite = (agora - timedelta(seconds=WORKER_TTL_S)).isoformat(timespec="seconds")
    limite_stall = (agora - timedelta(seconds=STALL_S)).isoformat(timespec="seconds")
    with conectar() as con:
        linhas = con.execute(
            "SELECT status, COUNT(*) AS quantidade, MIN(criado_em) AS mais_antigo "
            "FROM fila_jobs GROUP BY status"
        ).fetchall()
        workers = con.execute(
            "SELECT worker_id, estado, heartbeat_em FROM fila_workers WHERE fila=? AND heartbeat_em >= ?",
            (fila, limite),
        ).fetchall()
        presos = con.execute(
            "SELECT COUNT(*) AS quantidade FROM fila_jobs WHERE status='RUNNING' AND lease_ate < ?",
            (agora.isoformat(timespec="seconds"),),
        ).fetchone()
        pendentes_antigos = con.execute(
            "SELECT COUNT(*) AS quantidade FROM fila_jobs WHERE status='PENDING' AND criado_em < ?",
            (limite_stall,),
        ).fetchone()
    contagens = {str(l["status"]): int(l["quantidade"]) for l in linhas}
    pendentes = contagens.get("PENDING", 0)
    ativos = len(workers)
    possivel_preso = int(presos["quantidade"] or 0)
    esperando_demais = int(pendentes_antigos["quantidade"] or 0)
    if ativos == 0 and pendentes:
        classificacao = "NO_CONSUMERS"
    elif possivel_preso:
        classificacao = "POSSIBLE_HUNG_TASK"
    elif esperando_demais:
        classificacao = "STALLED"
    elif pendentes and ativos < esperados:
        classificacao = "DEGRADED"
    elif pendentes:
        classificacao = "DEGRADED"
    else:
        classificacao = "HEALTHY"
    return {
        "classificacao": classificacao,
        "jobs": contagens,
        "consumidores_ativos": ativos,
        "consumidores_esperados": esperados,
        "possiveis_presos": possivel_preso,
        "pendentes_alem_do_limite": esperando_demais,
        "workers": [dict(w) for w in workers],
    }


def enfileirar(
    tipo: str,
    argumentos: dict[str, Any],
    *,
    chave: str = "",
    tentativas_max: int = 3,
    prioridade: int = 0,
    job_id: str | None = None,
) -> str:
    """Inclui trabalho idempotente; a mesma chave ativa não duplica execução."""
    job_id = job_id or str(uuid.uuid4())
    agora = _agora().isoformat(timespec="seconds")
    with conectar() as con:
        if chave:
            existente = con.execute(
                "SELECT id FROM fila_jobs WITH (UPDLOCK, HOLDLOCK) "
                "WHERE chave = ? AND status IN ('PENDING','RUNNING')", (chave,)
            ).fetchone()
            if existente:
                _evento(
                    "OCR_QUEUED_DEDUP",
                    job_id=existente["id"],
                    chave=chave,
                    document_id=argumentos.get("entrega_id"),
                )
                return str(existente["id"])
        con.execute(
            "INSERT INTO fila_jobs (id, tipo, argumentos_json, chave, status, prioridade, tentativas_max, criado_em, atualizado_em) VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)",
            (job_id, tipo, json.dumps(argumentos, ensure_ascii=False), chave or None, prioridade, tentativas_max, agora, agora),
        )
    _evento(
        "OCR_QUEUED",
        job_id=job_id,
        document_id=argumentos.get("entrega_id"),
        tipo=tipo,
        chave=chave or None,
        prioridade=prioridade,
        status="PENDING",
    )
    return job_id


def enfileirar_ocr(args: tuple[Any, ...], *, job_id: str | None = None) -> str:
    """Publica a leitura OCR com a entrega como chave idempotente."""
    campos = (
        "entrega_id", "caso_id", "caminho", "nome", "item_codigo",
        "categoria_codigo", "idioma", "usar_para_rg_e_cpf",
    )
    if len(args) != len(campos):
        raise ValueError("argumentos inválidos para job OCR")
    argumentos = dict(zip(campos, args, strict=True))
    return enfileirar(
        "ocr_entrega", argumentos, chave=f"ocr:{argumentos['entrega_id']}",
        tentativas_max=3, prioridade=7, job_id=job_id,
    )


def reservar(worker_id: str | None = None) -> dict[str, Any] | None:
    """Reserva exatamente um job com lock de atualização, sem corrida entre pods.

    Equivalente SQL Server a `FOR UPDATE SKIP LOCKED`: UPDLOCK + READPAST.
    A transação fecha ao sair de `conectar()` — o OCR pesado roda fora dela.
    """
    worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    agora = _agora()
    lease = (agora + timedelta(seconds=LEASE_S)).isoformat(timespec="seconds")
    with conectar() as con:
        linha = con.execute("""
            ;WITH proximo AS (
                SELECT TOP 1 * FROM fila_jobs WITH (UPDLOCK, READPAST, ROWLOCK)
                WHERE status = 'PENDING' AND (disponivel_em IS NULL OR disponivel_em <= ?)
                ORDER BY prioridade DESC, criado_em ASC
            )
            UPDATE proximo SET status='RUNNING', worker_id=?, iniciado_em=COALESCE(iniciado_em, ?),
                heartbeat_em=?, lease_ate=?, tentativas=tentativas+1, atualizado_em=?
            OUTPUT inserted.id, inserted.tipo, inserted.argumentos_json, inserted.chave,
                   inserted.tentativas, inserted.tentativas_max;
        """, (agora.isoformat(timespec="seconds"), worker_id, agora.isoformat(timespec="seconds"), agora.isoformat(timespec="seconds"), lease, agora.isoformat(timespec="seconds"))).fetchone()
    if not linha:
        return None
    job = {**dict(linha), "argumentos": json.loads(linha["argumentos_json"] or "{}"), "worker_id": worker_id}
    _evento(
        "OCR_CLAIMED",
        job_id=job["id"],
        document_id=job["argumentos"].get("entrega_id"),
        worker_id=worker_id,
        attempt=job.get("tentativas"),
        status="RUNNING",
    )
    return job


def concluir(job_id: str, *, document_id: str | None = None, processing_time: float | None = None) -> None:
    agora = _agora().isoformat(timespec="seconds")
    with conectar() as con:
        con.execute(
            "UPDATE fila_jobs SET status='COMPLETED', finalizado_em=?, lease_ate=NULL, atualizado_em=? "
            "WHERE id=? AND status='RUNNING'",
            (agora, agora, job_id),
        )
    _evento(
        "OCR_COMPLETED",
        job_id=job_id,
        document_id=document_id,
        status="COMPLETED",
        processing_time=None if processing_time is None else round(processing_time, 3),
    )


def renovar_lease(job_id: str, worker_id: str) -> bool:
    """Registra progresso do consumidor e estende a reserva sem roubar jobs."""
    agora = _agora()
    lease = (agora + timedelta(seconds=LEASE_S)).isoformat(timespec="seconds")
    with conectar() as con:
        cursor = con.execute(
            "UPDATE fila_jobs SET heartbeat_em=?, lease_ate=?, atualizado_em=? "
            "WHERE id=? AND status='RUNNING' AND worker_id=?",
            (agora.isoformat(timespec="seconds"), lease, agora.isoformat(timespec="seconds"), job_id, worker_id),
        )
    return bool(cursor.rowcount)


def falhar(job: dict[str, Any], erro: Exception) -> str:
    """Marca falha temporária (PENDING + backoff) ou definitiva (FAILED).

    Devolve o novo status para o worker sincronizar a entrega.
    """
    agora = _agora()
    tentativas = int(job.get("tentativas") or 1)
    maximo = int(job.get("tentativas_max") or 3)
    status = "FAILED" if tentativas >= maximo else "PENDING"
    disponivel = None if status == "FAILED" else (agora + timedelta(seconds=min(300, 2 ** tentativas))).isoformat(timespec="seconds")
    mensagem = str(erro)[:2000]
    with conectar() as con:
        con.execute(
            "UPDATE fila_jobs SET status=?, erro=?, disponivel_em=?, lease_ate=NULL, atualizado_em=? WHERE id=?",
            (status, mensagem, disponivel, agora.isoformat(timespec="seconds"), job["id"]),
        )
    document_id = (job.get("argumentos") or {}).get("entrega_id")
    _evento(
        "OCR_FAILED" if status == "FAILED" else "OCR_RETRY_SCHEDULED",
        job_id=job["id"],
        document_id=document_id,
        worker_id=job.get("worker_id"),
        attempt=tentativas,
        status=status,
        erro=mensagem[:300],
        available_at=disponivel,
    )
    return status


def recuperar_orfaos() -> int:
    """Devolve a PENDING jobs cujo lease expirou (worker morto no meio do OCR)."""
    agora = _agora().isoformat(timespec="seconds")
    with conectar() as con:
        orfaos = con.execute(
            "SELECT id, argumentos_json, worker_id, tentativas FROM fila_jobs "
            "WHERE status='RUNNING' AND lease_ate < ?",
            (agora,),
        ).fetchall()
        if not orfaos:
            return 0
        cursor = con.execute(
            "UPDATE fila_jobs SET status='PENDING', worker_id=NULL, heartbeat_em=NULL, "
            "lease_ate=NULL, disponivel_em=?, atualizado_em=? "
            "WHERE status='RUNNING' AND lease_ate < ?",
            (agora, agora, agora),
        )
    for linha in orfaos:
        args = json.loads(linha["argumentos_json"] or "{}")
        _evento(
            "OCR_ORPHAN_RECOVERED",
            job_id=linha["id"],
            document_id=args.get("entrega_id"),
            worker_id=linha["worker_id"],
            attempt=linha["tentativas"],
            status="PENDING",
        )
    return int(cursor.rowcount or 0)


def job_ativo_para_entrega(entrega_id: str) -> str | None:
    """Id do job PENDING/RUNNING da entrega, se houver (idempotência)."""
    chave = f"ocr:{entrega_id}"
    with conectar() as con:
        linha = con.execute(
            "SELECT id FROM fila_jobs WHERE chave=? AND status IN ('PENDING','RUNNING')",
            (chave,),
        ).fetchone()
    return str(linha["id"]) if linha else None
