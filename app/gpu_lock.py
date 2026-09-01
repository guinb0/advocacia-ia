"""Exclusão mútua da GPU entre processos e filas diferentes."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from redis import Redis


@contextmanager
def gpu_exclusiva(*, timeout: int = 1800, espera: int = 1800) -> Iterator[None]:
    cliente = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6380/0"))
    lock = cliente.lock("gpu:0", timeout=timeout, blocking_timeout=espera)
    adquirido = lock.acquire(blocking=True)
    if not adquirido:
        raise TimeoutError("GPU ocupada além do limite de espera")
    try:
        yield
    finally:
        if lock.owned():
            lock.release()
