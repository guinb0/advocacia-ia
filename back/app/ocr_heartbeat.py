"""Heartbeat do processo mestre de cada worker OCR.

Roda em thread própria do mestre Celery; uma task ou subprocesso OCR bloqueado
não interrompe a renovação do TTL.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone

from .celery_app import celery_app

INTERVALO_S = 15
TTL_S = 60
_iniciado = False
_trava = threading.Lock()


def iniciar(hostname: str) -> None:
    global _iniciado
    if not hostname.startswith("ocr@"):
        return
    with _trava:
        if _iniciado:
            return
        _iniciado = True
    worker_id = f"ocr-worker-{hostname.removeprefix('ocr@')}-{os.getpid()}"

    def publicar() -> None:
        from redis import Redis
        while True:
            try:
                redis = Redis.from_url(
                    celery_app.conf.broker_url, socket_connect_timeout=2, socket_timeout=2
                )
                chave = f"ocr:worker:{worker_id}:heartbeat"
                while True:
                    corpo = json.dumps({
                        "worker_id": worker_id, "hostname": hostname, "pid": os.getpid(),
                        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "status": "ready",
                    })
                    redis.set(chave, corpo, ex=TTL_S)
                    time.sleep(INTERVALO_S)
            except Exception:
                # O worker continua tentando reconectar; a expiração do TTL é o
                # sinal externo de indisponibilidade e não revela credenciais.
                time.sleep(INTERVALO_S)

    threading.Thread(target=publicar, name="ocr-heartbeat", daemon=True).start()
