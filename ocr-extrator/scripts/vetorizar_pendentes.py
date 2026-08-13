"""Preenche embeddings NULL em lotes retomáveis de 32 chunks."""

from __future__ import annotations

import argparse
import os
import time

import psycopg

from app.rag import carregar_env, gerar_embeddings, vetor_literal


def vetorizar(*, lote: int = 32, limite: int | None = None) -> dict[str, int]:
    carregar_env()
    feitos = 0
    chamadas = 0
    # A chamada externa de embeddings pode demorar. Em autocommit, o SELECT não
    # deixa uma transação ociosa aberta enquanto aguardamos a API, evitando o
    # idle_in_transaction_session_timeout do PostgreSQL remoto.
    with psycopg.connect(
        os.environ["DATABASE_URL"], connect_timeout=10, autocommit=True
    ) as conexao:
        while limite is None or feitos < limite:
            tamanho = min(lote, limite - feitos) if limite is not None else lote
            linhas = conexao.execute(
                """SELECT k.id, k.texto FROM knowledge_chunks k
                   JOIN fontes f ON f.id=k.fonte_id
                  WHERE k.embedding IS NULL AND f.tipo='jurisprudencia'
                  ORDER BY k.id LIMIT %s""",
                (tamanho,),
            ).fetchall()
            if not linhas:
                break
            vetores = gerar_embeddings([linha[1] for linha in linhas])
            for (chunk_id, _), vetor in zip(linhas, vetores, strict=True):
                conexao.execute(
                    "UPDATE knowledge_chunks SET embedding=%s::vector WHERE id=%s",
                    (vetor_literal(vetor), chunk_id),
                )
            feitos += len(linhas)
            chamadas += 1
            print(f"\rchunks={feitos} lotes={chamadas}", end="", flush=True)
    print()
    return {"chunks": feitos, "lotes": chamadas}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lote", type=int, default=32)
    parser.add_argument("--limite", type=int)
    args = parser.parse_args()
    tentativa = 0
    while True:
        try:
            print(vetorizar(lote=args.lote, limite=args.limite))
            return
        except Exception as exc:
            tentativa += 1
            print(
                f"\nFalha transitória ({type(exc).__name__}); "
                f"retentativa {tentativa} em 60s.",
                flush=True,
            )
            time.sleep(60)


if __name__ == "__main__":
    main()
