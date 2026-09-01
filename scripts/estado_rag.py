"""Diz em que pé está o banco vetorial — e, quando não está, por quê.

Existe porque "o RAG não respondeu" tem causas muito diferentes, e a mensagem de
erro do psycopg é a mesma para quase todas: a rede não alcança o servidor, o
servidor está de pé mas o banco recusa a senha, o banco responde mas a tabela
está vazia, ou está cheia de texto sem embedding — que é o estado real desde que
a vetorização foi pausada. Cada uma pede uma ação diferente, e nenhuma delas é
"mexer no código".

O uso comum é conferir se a conferência da entrevista (`app/analise_resposta.py`)
vai conseguir citar processos ou vai sair marcada como "sem precedentes".

    .venv\\Scripts\\python.exe -m scripts.estado_rag
    .venv\\Scripts\\python.exe -m scripts.estado_rag --busca "acidente com o dedo na máquina"

O `--busca` é o único que gasta: ele gera um embedding de verdade (uma chamada ao
OpenRouter) para provar o caminho inteiro, do texto ao processo recuperado. Sem
ele, nada sai da máquina além da consulta ao Postgres.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

from app import rag

#: Curto de propósito: isto é diagnóstico. Um banco que leva mais de 8s para
#: aceitar conexão já é a resposta que se veio procurar.
TEMPO_CONEXAO_S = 8


def _linha(rotulo: str, valor: object) -> None:
    print(f"  {rotulo:.<34} {valor}")


def _alcance(url: str) -> bool:
    """Separa 'a rede não chega lá' de 'o banco recusou'.

    É a distinção que mais economiza tempo: sem ela, VPN caída e senha trocada
    produzem a mesma mensagem, e se perde meia hora no arquivo errado.
    """
    partes = urlparse(url)
    host, porta = partes.hostname or "", partes.port or 5432
    print("\nREDE")
    _linha("servidor", f"{host}:{porta}")
    inicio = time.monotonic()
    try:
        with socket.create_connection((host, porta), timeout=TEMPO_CONEXAO_S):
            _linha("porta TCP", f"alcançável em {time.monotonic() - inicio:.2f}s")
            return True
    except OSError as exc:
        _linha("porta TCP", f"INALCANÇÁVEL — {exc}")
        print(
            "\n  A rede não chega ao servidor. Não é senha nem schema:\n"
            "  confira a VPN e se o host responde de outra máquina.\n"
            "  A conferência da entrevista segue funcionando, marcada\n"
            "  como 'sem precedentes'."
        )
        return False


CONSULTAS = {
    "extensoes": "SELECT extname, extversion FROM pg_extension ORDER BY extname",
    "dimensao": """
        SELECT c.relname AS tabela, a.attname AS coluna,
               format_type(a.atttypid, a.atttypmod) AS tipo
          FROM pg_attribute a
          JOIN pg_class c ON c.oid = a.attrelid
         WHERE a.atttypid = 'vector'::regtype AND NOT a.attisdropped
         ORDER BY 1, 2
    """,
    "totais": """
        SELECT count(*) AS chunks,
               count(embedding) AS com_embedding,
               count(*) - count(embedding) AS pendentes
          FROM knowledge_chunks
    """,
    "por_tipo": """
        SELECT f.tipo,
               count(*) AS chunks,
               count(k.embedding) AS com_embedding
          FROM knowledge_chunks k
          JOIN fontes f ON f.id = k.fonte_id
         GROUP BY f.tipo
         ORDER BY chunks DESC
    """,
    "por_origem": """
        SELECT coalesce(k.metadados->>'origem', '(sem origem)') AS origem,
               count(*) AS chunks,
               count(k.embedding) AS com_embedding
          FROM knowledge_chunks k
         GROUP BY 1
         ORDER BY chunks DESC
    """,
    "processos": """
        SELECT count(DISTINCT metadados->>'numero_processo') AS processos
          FROM knowledge_chunks
         WHERE metadados->>'numero_processo' IS NOT NULL
    """,
}


def _pct(parte: int, todo: int) -> str:
    return f"{parte * 100 / todo:.2f}%" if todo else "—"


def _diagnostico(conexao: psycopg.Connection) -> int:
    print("\nESTRUTURA")
    extensoes = conexao.execute(CONSULTAS["extensoes"]).fetchall()
    nomes = {e["extname"] for e in extensoes}
    _linha("extensões", ", ".join(f"{e['extname']} {e['extversion']}" for e in extensoes))
    if "vector" not in nomes:
        print("  FALTA a extensão `vector`. Aplique sql/001_criar_banco_vetorial.sql.")
        return 1

    for coluna in conexao.execute(CONSULTAS["dimensao"]).fetchall():
        _linha(f"{coluna['tabela']}.{coluna['coluna']}", coluna["tipo"])
    # A dimensão precisa bater com EMBEDDINGS_DIMENSIONS: divergindo, a busca não
    # dá erro de conexão — ela dá erro no operador, e a mensagem não diz isso.
    esperada = os.getenv("EMBEDDINGS_DIMENSIONS", "1536")
    _linha("EMBEDDINGS_DIMENSIONS no .env", esperada)

    print("\nVETORIZAÇÃO")
    t = conexao.execute(CONSULTAS["totais"]).fetchone()
    fontes = conexao.execute("SELECT count(*) AS n FROM fontes").fetchone()["n"]
    processos = conexao.execute(CONSULTAS["processos"]).fetchone()["processos"]
    _linha("fontes", fontes)
    _linha("processos distintos", processos)
    _linha("chunks", t["chunks"])
    _linha("com embedding", f"{t['com_embedding']}  ({_pct(t['com_embedding'], t['chunks'])})")
    _linha("pendentes", t["pendentes"])

    if t["chunks"]:
        print("\n  por tipo de fonte")
        for l in conexao.execute(CONSULTAS["por_tipo"]).fetchall():
            print(
                f"    {str(l['tipo']):<22} {l['chunks']:>7} chunks   "
                f"{l['com_embedding']:>7} vetorizados ({_pct(l['com_embedding'], l['chunks'])})"
            )
        print("\n  por origem")
        for l in conexao.execute(CONSULTAS["por_origem"]).fetchall():
            print(
                f"    {str(l['origem']):<22} {l['chunks']:>7} chunks   "
                f"{l['com_embedding']:>7} vetorizados ({_pct(l['com_embedding'], l['chunks'])})"
            )

    # O que a conferência da entrevista realmente usa: jurisprudência COM vetor.
    # Zero aqui e o painel sai "sem precedentes" mesmo com o banco de pé.
    usaveis = conexao.execute(
        """
        SELECT count(*) AS n FROM knowledge_chunks k JOIN fontes f ON f.id = k.fonte_id
         WHERE k.embedding IS NOT NULL AND f.tipo = 'jurisprudencia'
        """
    ).fetchone()["n"]
    print("\nO QUE A ENTREVISTA CONSEGUE CITAR")
    _linha("jurisprudência vetorizada", usaveis)
    if usaveis:
        print("\n  A conferência da entrevista vai citar processos.")
    else:
        print(
            "\n  Sem jurisprudência vetorizada: a conferência sai marcada\n"
            "  'sem precedentes'. Retome a vetorização:\n"
            "    Enable-ScheduledTask -TaskName 'AdvocaciaIA-SincronizarRAG'\n"
            "    Start-ScheduledTask  -TaskName 'AdvocaciaIA-SincronizarRAG'"
        )
    return 0


def _busca(texto: str) -> int:
    """Prova o caminho inteiro: texto → embedding → HNSW → processo."""
    print("\nBUSCA DE PONTA A PONTA")
    _linha("consulta", texto[:60])
    inicio = time.monotonic()
    try:
        achados = rag.buscar_similares(texto, limite=5)
    except Exception as exc:
        _linha("resultado", f"FALHOU — {type(exc).__name__}: {exc}")
        return 1
    _linha("tempo", f"{time.monotonic() - inicio:.2f}s")
    if not achados:
        _linha("resultado", "nenhum trecho — há texto no banco, mas sem embedding")
        return 1
    for t in achados:
        ref = t.referencia()
        print(
            f"    {ref['similaridade']:.3f}  {ref['processo'] or '—'}  "
            f"{ref['resultado'] or '—'}  {(ref['vara'] or '')[:40]}"
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Estado do banco vetorial (pgvector).")
    ap.add_argument(
        "--busca",
        metavar="TEXTO",
        help="prova a recuperação de ponta a ponta (gasta uma chamada de embeddings)",
    )
    args = ap.parse_args()

    rag.carregar_env()
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL não configurada no .env.")
        return 1

    if not _alcance(url):
        return 1

    print("\nCONEXÃO")
    try:
        with psycopg.connect(
            url, connect_timeout=TEMPO_CONEXAO_S, row_factory=dict_row
        ) as conexao:
            _linha("autenticação", "ok")
            _linha("versão", conexao.execute("SELECT version()").fetchone()["version"][:60])
            codigo = _diagnostico(conexao)
    except psycopg.OperationalError as exc:
        # A porta abriu e mesmo assim falhou: é senha, base inexistente ou
        # pg_hba — nada que se resolva olhando a rede.
        _linha("autenticação", f"RECUSADA — {str(exc).strip()[:140]}")
        print("\n  A porta abre mas o banco recusou. Confira PGVECTOR_* / DATABASE_URL no .env.")
        return 1

    if args.busca:
        codigo |= _busca(args.busca)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
