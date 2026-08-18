"""Registro durável dos jobs no PostgreSQL usado pelo RAG/pgvector."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


def _url() -> str:
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            texto = linha.strip()
            if texto and not texto.startswith("#") and "=" in texto:
                chave, valor = texto.split("=", 1)
                os.environ.setdefault(chave.strip(), valor.strip())
    url = os.getenv("JOBS_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("Defina JOBS_DATABASE_URL ou DATABASE_URL para persistir jobs.")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _conectar(**kwargs):
    return psycopg.connect(_url(), connect_timeout=10, **kwargs)


def inicializar() -> None:
    with _conectar() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id uuid PRIMARY KEY,
                celery_task_id varchar(255),
                caso_id varchar(64),
                tipo varchar(50) NOT NULL,
                status varchar(30) NOT NULL,
                progresso integer NOT NULL DEFAULT 0 CHECK (progresso BETWEEN 0 AND 100),
                erro text,
                resultado jsonb,
                arquivo_temporario text,
                criado_em timestamptz NOT NULL DEFAULT now(),
                iniciado_em timestamptz,
                finalizado_em timestamptz,
                atualizado_em timestamptz NOT NULL DEFAULT now()
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS ix_jobs_status_criado ON jobs(status, criado_em)")


def criar(tipo: str, *, caso_id: str | None = None, arquivo: str | None = None) -> str:
    job_id = str(uuid.uuid4())
    with _conectar() as con:
        con.execute(
            "INSERT INTO jobs(id,tipo,status,caso_id,arquivo_temporario) VALUES (%s,%s,'QUEUED',%s,%s)",
            (job_id, tipo, caso_id, arquivo),
        )
    return job_id


def vincular_tarefa(job_id: str, task_id: str) -> None:
    atualizar(job_id, celery_task_id=task_id)


def atualizar(job_id: str, **campos: Any) -> None:
    permitidos = {"celery_task_id", "status", "progresso", "erro", "resultado", "iniciado_em", "finalizado_em"}
    dados = {k: v for k, v in campos.items() if k in permitidos}
    if not dados:
        return
    if "resultado" in dados:
        dados["resultado"] = json.dumps(dados["resultado"], ensure_ascii=False)
    atribuicoes = ", ".join(f"{k} = %s" + ("::jsonb" if k == "resultado" else "") for k in dados)
    with _conectar() as con:
        con.execute(
            f"UPDATE jobs SET {atribuicoes}, atualizado_em=now() WHERE id=%s",
            (*dados.values(), job_id),
        )


def obter(job_id: str) -> dict[str, Any] | None:
    with _conectar(row_factory=dict_row) as con:
        linha = con.execute(
            "SELECT id,celery_task_id,caso_id,tipo,status,progresso,erro,resultado,criado_em,iniciado_em,finalizado_em FROM jobs WHERE id=%s",
            (job_id,),
        ).fetchone()
    if linha:
        for chave in ("id", "criado_em", "iniciado_em", "finalizado_em"):
            if linha.get(chave) is not None:
                linha[chave] = str(linha[chave])
    return linha


def recuperar_abandonados(minutos: int = 30) -> int:
    limite = datetime.now(timezone.utc) - timedelta(minutes=minutos)
    with _conectar() as con:
        cursor = con.execute(
            """UPDATE jobs SET status='FAILED', erro='Worker interrompido ou tempo limite excedido',
                      finalizado_em=now(), atualizado_em=now()
                 WHERE status IN ('STARTED','PROCESSING') AND atualizado_em < %s""",
            (limite,),
        )
        return cursor.rowcount
