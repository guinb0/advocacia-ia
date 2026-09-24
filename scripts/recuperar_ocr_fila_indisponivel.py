#!/usr/bin/env python3
"""Reenfileira entregas que falharam com a mensagem antiga de 'fila indisponível'.

Uso (na API/worker, com SQLSERVER_* no ambiente):

    PYTHONPATH=. python -m scripts.recuperar_ocr_fila_indisponivel --dry-run
    PYTHONPATH=. python -m scripts.recuperar_ocr_fila_indisponivel

Só toca entregas com status_proc='erro' cuja mensagem contém 'Fila de OCR'
ou 'Não foi possível enfileirar'. O arquivo precisa existir em disco ou em
`entregas.conteudo`.
"""
from __future__ import annotations

import argparse
import logging
import uuid

from app import armazenamento, fila_sql
from app.banco import conectar

log = logging.getLogger("recuperar-ocr")


def _candidatas(limite: int) -> list[dict]:
    with conectar() as con:
        linhas = con.execute(
            """
            SELECT TOP (?) e.id, e.caso_id, e.item_codigo, e.arquivo,
                   e.itens_atendidos, e.erro_proc, c.categoria
              FROM entregas e
              JOIN casos c ON c.id = e.caso_id
             WHERE e.status_proc = 'erro'
               AND (
                    e.erro_proc LIKE ?
                 OR e.erro_proc LIKE ?
                 OR e.erro_proc LIKE ?
                 OR e.erro_proc LIKE ?
               )
             ORDER BY e.criado_em DESC
            """,
            (
                limite,
                "%Fila de OCR%",
                "%Fila de leitura%",
                "%Não foi possível enfileirar%",
                "%daemonic processes%",
            ),
        ).fetchall()
    return [dict(l) for l in linhas]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limite", type=int, default=200)
    args = parser.parse_args()

    candidatas = _candidatas(args.limite)
    log.info("%d entrega(s) candidata(s)", len(candidatas))
    reenfileiradas = 0
    for entrega in candidatas:
        caminho = armazenamento.caminho_duravel_da_entrega(entrega["id"])
        if caminho is None:
            log.warning("sem arquivo: %s (%s)", entrega["id"], entrega["arquivo"])
            continue
        import json

        itens = json.loads(entrega["itens_atendidos"] or "[]")
        args_ocr = (
            entrega["id"],
            entrega["caso_id"],
            str(caminho),
            entrega["arquivo"],
            entrega["item_codigo"],
            entrega["categoria"],
            "pt",
            len(itens) > 1,
        )
        if args.dry_run:
            log.info("dry-run %s %s", entrega["id"], entrega["arquivo"])
            continue
        task_id = str(uuid.uuid4())
        armazenamento.marcar_entrega_enfileirada(entrega["id"], task_id)
        fila_sql.enfileirar_ocr(args_ocr, job_id=task_id)
        reenfileiradas += 1
        log.info("reenfileirada %s -> job %s", entrega["id"], task_id)

    log.info("reenfileiradas=%d dry_run=%s", reenfileiradas, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
