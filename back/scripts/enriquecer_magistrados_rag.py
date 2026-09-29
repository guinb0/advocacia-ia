"""Inclui magistrados dos documentos TRT8 nos metadados já ingeridos, sem re-embedding."""

from __future__ import annotations

import json
import os
from collections import defaultdict

import psycopg

from app.rag import carregar_env
from scripts.ingerir_jurimetria import magistrados_do_payload


def enriquecer() -> dict[str, int]:
    carregar_env()
    origem_url = os.getenv(
        "JURIMETRIA_DATABASE_URL", "postgresql://juri:juri@localhost:5433/juri"
    )
    por_processo: dict[str, set[str]] = defaultdict(set)
    with psycopg.connect(origem_url, connect_timeout=10) as origem:
        with origem.cursor(name="magistrados_rag") as cursor:
            cursor.execute(
                "SELECT numero_processo, payload_detalhe FROM documento_raw "
                "WHERE payload_detalhe IS NOT NULL"
            )
            for numero, payload in cursor:
                por_processo[numero].update(magistrados_do_payload(payload))

    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=10) as destino:
        destino.execute(
            "CREATE TEMP TABLE tmp_magistrados "
            "(numero_processo text PRIMARY KEY, nomes jsonb) ON COMMIT DROP"
        )
        parametros = [
            (numero, json.dumps(sorted(nomes), ensure_ascii=False))
            for numero, nomes in por_processo.items()
            if nomes
        ]
        with destino.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO tmp_magistrados VALUES (%s, %s::jsonb)", parametros
            )
        resultado = destino.execute(
            """UPDATE knowledge_chunks k
                  SET metadados=jsonb_set(k.metadados, '{magistrados}', t.nomes, true)
                 FROM tmp_magistrados t
                WHERE k.metadados->>'numero_processo'=t.numero_processo"""
        )
        atualizados = resultado.rowcount
        destino.commit()
    return {"processos_com_magistrado": sum(bool(n) for n in por_processo.values()),
            "chunks_atualizados": atualizados}


if __name__ == "__main__":
    print(enriquecer())
