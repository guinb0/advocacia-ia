"""Consumidor reciclável da fila SQL.

Ele não depende do Redis: cada processo reserva uma linha, mantém o lease vivo
enquanto executa e devolve ao banco qualquer reserva abandonada por outro processo.
Os handlers são registrados explicitamente pelo serviço que os possui.
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

from . import fila_sql

log = logging.getLogger(__name__)
Handler = Callable[..., Any]
_handlers: dict[str, Handler] = {}
_parar = threading.Event()


def registrar(tipo: str, handler: Handler) -> None:
    if not tipo:
        raise ValueError("tipo de job é obrigatório")
    _handlers[tipo] = handler


def _worker_id() -> str:
    return os.getenv("FILA_SQL_WORKER_ID") or f"{socket.gethostname()}:{os.getpid()}"


def _manter_lease(job_id: str, worker_id: str, parar: threading.Event) -> None:
    intervalo = max(5, fila_sql.LEASE_S // 3)
    while not parar.wait(intervalo):
        try:
            if not fila_sql.renovar_lease(job_id, worker_id):
                log.error("job %s perdeu a reserva; execução será encerrada ao terminar", job_id)
                return
        except Exception:
            log.exception("não foi possível renovar lease do job %s", job_id)


def executar_uma_vez(worker_id: str | None = None) -> bool:
    """Executa no máximo um job. Útil para testes e para o loop do processo."""
    worker_id = worker_id or _worker_id()
    job = fila_sql.reservar(worker_id)
    if job is None:
        return False

    handler = _handlers.get(str(job["tipo"]))
    if handler is None:
        fila_sql.falhar(job, RuntimeError(f"tipo de job desconhecido: {job['tipo']}"))
        log.error("job %s rejeitado: tipo %s sem handler", job["id"], job["tipo"])
        return True

    parar_lease = threading.Event()
    heartbeat = threading.Thread(
        target=_manter_lease, args=(str(job["id"]), worker_id, parar_lease), daemon=True
    )
    heartbeat.start()
    try:
        handler(**job["argumentos"])
    except Exception as exc:
        log.exception("job SQL %s (%s) falhou", job["id"], job["tipo"])
        fila_sql.falhar(job, exc)
    else:
        fila_sql.concluir(str(job["id"]))
    finally:
        parar_lease.set()
        heartbeat.join(timeout=2)
    return True


def executar(poll_s: float = 1.0) -> None:
    """Loop do processo. A recuperação é idempotente e não apaga trabalho."""
    worker_id = _worker_id()
    max_jobs = int(os.getenv("FILA_SQL_MAX_JOBS", "0"))
    executados = 0
    proximo_heartbeat = 0.0
    proxima_recuperacao = 0.0
    log.info("worker SQL pronto: %s", worker_id)
    while not _parar.is_set():
        try:
            monotonic = time.monotonic()
            if monotonic >= proximo_heartbeat:
                fila_sql.heartbeat_worker(worker_id)
                proximo_heartbeat = monotonic + 5
            if monotonic >= proxima_recuperacao:
                fila_sql.recuperar_orfaos()
                proxima_recuperacao = monotonic + 30
            if executar_uma_vez(worker_id):
                executados += 1
                if max_jobs and executados >= max_jobs:
                    log.info("worker SQL reciclado após %d jobs", executados)
                    return
            else:
                _parar.wait(poll_s)
        except Exception:
            log.exception("loop da fila SQL falhou; nova tentativa em %.1fs", poll_s)
            _parar.wait(poll_s)


def _encerrar(_signal: int, _frame: Any) -> None:
    _parar.set()


def iniciar() -> None:
    signal.signal(signal.SIGTERM, _encerrar)
    signal.signal(signal.SIGINT, _encerrar)
    executar(float(os.getenv("FILA_SQL_POLL_S", "1")))


if __name__ == "__main__":
    iniciar()
