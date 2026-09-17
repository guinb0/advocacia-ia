"""Mostra o progresso da ingestão do acervo de peças."""
from __future__ import annotations

import os

import psycopg

from app import ambiente


def main() -> None:
    ambiente.carregar()
    with psycopg.connect(os.environ["DATABASE_URL"]) as banco:
        linhas = banco.execute(
            """SELECT p.categoria, count(DISTINCT p.id) AS pecas, count(c.id) AS trechos
               FROM pecas_conteudo p
               LEFT JOIN pecas_conteudo_chunks c ON c.peca_id = p.id
               WHERE p.categoria IN ('pecas_simples', 'pecas_complexas')
               GROUP BY p.categoria ORDER BY p.categoria"""
        ).fetchall()
    for categoria, pecas, trechos in linhas:
        print(f"{categoria}: {pecas} peça(s), {trechos} trecho(s)")
    with psycopg.connect(os.environ["DATABASE_URL"]) as banco:
        corrompidas = banco.execute(
            """SELECT count(*) FROM pecas_conteudo
               WHERE categoria IN ('pecas_simples', 'pecas_complexas')
                 AND texto_integral LIKE %s""",
            ("%\ufffd%",),
        ).fetchone()[0]
    print(f"peças com caractere de substituição: {corrompidas}")


if __name__ == "__main__":
    main()
