"""Fila durável no SQL Server, sem broker Redis/Celery.

O SQL é a fonte de verdade: reservar um job usa locks de linha e evita que duas
réplicas o executem; lease/heartbeat permite recuperar trabalho abandonado.
"""
from __future__ import annotations

import json
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .banco import conectar

LEASE_S = int(os.getenv("FILA_SQL_LEASE_S", "120"))
WORKER_TTL_S = int(os.getenv("FILA_SQL_WORKER_TTL_S", "30"))
STALL_S = int(os.getenv("FILA_SQL_STALL_S", "600"))


def _agora() -> datetime:
    return datetime.now(timezone.utc)


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
            "SELECT COUNT(*) AS quantidade FROM fila_jobs WHERE status='RUNNING' AND heartbeat_em < ?",
            (limite,),
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
    if ativos == 0:
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
                return str(existente["id"])
        con.execute(
            "INSERT INTO fila_jobs (id, tipo, argumentos_json, chave, status, prioridade, tentativas_max, criado_em, atualizado_em) VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)",
            (job_id, tipo, json.dumps(argumentos, ensure_ascii=False), chave or None, prioridade, tentativas_max, agora, agora),
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
    """Reserva exatamente um job com lock de atualização, sem corrida entre pods."""
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
    return {**dict(linha), "argumentos": json.loads(linha["argumentos_json"] or "{}"), "worker_id": worker_id}


def concluir(job_id: str) -> None:
    agora = _agora().isoformat(timespec="seconds")
    with conectar() as con:
        con.execute("UPDATE fila_jobs SET status='COMPLETED', finalizado_em=?, lease_ate=NULL, atualizado_em=? WHERE id=? AND status='RUNNING'", (agora, agora, job_id))


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


def falhar(job: dict[str, Any], erro: Exception) -> None:
    agora = _agora()
    tentativas = int(job.get("tentativas") or 1)
    maximo = int(job.get("tentativas_max") or 3)
    status = "FAILED" if tentativas >= maximo else "PENDING"
    disponivel = None if status == "FAILED" else (agora + timedelta(seconds=min(300, 2 ** tentativas))).isoformat(timespec="seconds")
    with conectar() as con:
        con.execute("UPDATE fila_jobs SET status=?, erro=?, disponivel_em=?, lease_ate=NULL, atualizado_em=? WHERE id=?", (status, str(erro)[:2000], disponivel, agora.isoformat(timespec="seconds"), job["id"]))


def recuperar_orfaos() -> int:
    agora = _agora().isoformat(timespec="seconds")
    with conectar() as con:
        cursor = con.execute(
            "UPDATE fila_jobs SET status='PENDING', worker_id=NULL, heartbeat_em=NULL, "
            "lease_ate=NULL, disponivel_em=?, atualizado_em=? "
            "WHERE status='RUNNING' AND lease_ate < ?",
            (agora, agora, agora),
        )
    return int(cursor.rowcount or 0)
