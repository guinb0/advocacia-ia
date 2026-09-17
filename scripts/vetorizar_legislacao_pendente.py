"""Gera embeddings somente para fontes de legislação já importadas.

Uso: python -m scripts.vetorizar_legislacao_pendente
"""
from __future__ import annotations

import os

import psycopg

from app.rag import carregar_env, gerar_embeddings, vetor_literal


def main() -> None:
    carregar_env()
    total = 0
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conexao:
        while True:
            linhas = conexao.execute(
                """SELECT k.id,k.texto FROM knowledge_chunks k JOIN fontes f ON f.id=k.fonte_id
                   WHERE f.tipo='lei' AND k.embedding IS NULL ORDER BY k.id LIMIT 32"""
            ).fetchall()
            if not linhas:
                break
            vetores = gerar_embeddings([texto for _, texto in linhas], timeout=180)
            with conexao.transaction():
                with conexao.cursor() as cur:
                    cur.executemany(
                        "UPDATE knowledge_chunks SET embedding=%s::vector WHERE id=%s",
                        [(vetor_literal(vetor), chunk_id) for (chunk_id, _), vetor in zip(linhas, vetores)],
                    )
            total += len(linhas)
            print(f"Vetorizados: {total}", flush=True)
    print(f"Concluído: {total} chunks de legislação.")


if __name__ == "__main__":
    main()
