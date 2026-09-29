"""Entrada do serviço OCR sobre a fila SQL.

Mantemos a função OCR existente como handler para preservar toda a regra de
triagem; apenas o transporte deixa de ser Celery/Redis.
"""
from __future__ import annotations

import os

from .tasks.ocr import processar_entrega
from .worker_sql import iniciar, registrar


def _ler_entrega(**argumentos: object) -> object:
    # Flag lida pela task: falhas temporárias NÃO gravam `entregas` em `erro`
    # — o worker SQL decide retry vs falha definitiva via `fila_sql.falhar`.
    os.environ["OCR_FILA_SQL_HANDLER"] = "1"
    try:
        # `.run` executa o corpo da task ligada sem publicar no broker Celery.
        return processar_entrega.run(**argumentos)
    finally:
        os.environ.pop("OCR_FILA_SQL_HANDLER", None)


registrar("ocr_entrega", _ler_entrega)

if __name__ == "__main__":
    iniciar()
