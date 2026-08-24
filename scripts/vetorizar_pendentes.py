"""Preenche embeddings NULL em lotes retomáveis de 32 chunks.

TODA OPERAÇÃO PRECISA DE PRAZO, NÃO SÓ A CONEXÃO

Medido em 13/08/2026: uma execução iniciada às 13:46:53 seguia viva 25 minutos
depois com 1,1s de CPU, log de zero byte e a contagem parada — com a conexão
`Established` desde 13:46:54. Ela conectou e ficou pendurada esperando uma
resposta que nunca veio.

O `connect_timeout` cobre só o aperto de mão. Depois dele, uma leitura que não
retorna bloqueia para sempre: o servidor é remoto e compartilhado, e uma conexão
pode morrer sem que o outro lado saiba. Daí os `keepalives` (o sistema derruba a
conexão morta em ~1 min) e o `statement_timeout` (o servidor aborta a consulta
que se arrasta). Sem os dois, o `while` de retentativa lá embaixo nunca roda —
a exceção que o dispararia jamais é levantada.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

import psycopg

from app.rag import carregar_env, gerar_embeddings, vetor_literal

#: Prazos DEPOIS da conexão aberta. `keepalives_count` é ignorado no Windows;
#: idle e interval não são, e são eles que detectam a conexão morta.
CONEXAO = {
    "connect_timeout": 10,
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
    # Generoso: um lote de 64 vetores grava em segundos. Serve para o caso
    # patológico, não para o normal.
    "options": "-c statement_timeout=180000",
}


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def vetorizar(
    *, lote: int = 32, limite: int | None = None, progresso: dict[str, int] | None = None
) -> dict[str, int]:
    """`progresso` recebe o que já foi gravado, mesmo se a conexão cair no meio.

    Sem isso, quem chama não distingue "caiu sem fazer nada" de "gravou 640
    chunks e então caiu" — e as duas coisas não merecem a mesma reação.
    """
    carregar_env()
    feitos = 0
    chamadas = 0
    if progresso is not None:
        progresso["chunks"] = 0

    # A chamada externa de embeddings pode demorar. Em autocommit, o SELECT não
    # deixa uma transação ociosa aberta enquanto aguardamos a API, evitando o
    # idle_in_transaction_session_timeout do PostgreSQL remoto — que neste
    # servidor está em 30s (medido em 13/08).
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, **CONEXAO) as conexao:
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
            ids = [chunk_id for chunk_id, _ in linhas]
            embeddings = [vetor_literal(vetor) for vetor in vetores]
            # Uma única transação por lote. Antes eram N commits remotos (um por
            # vetor), o que amplificava brutalmente a latência e as quedas de rede.
            with conexao.transaction():
                conexao.execute(
                    """UPDATE knowledge_chunks AS k
                          SET embedding = lote.embedding::vector
                         FROM (
                               SELECT unnest(%s::bigint[]) AS id,
                                      unnest(%s::text[]) AS embedding
                              ) AS lote
                        WHERE k.id = lote.id""",
                    (ids, embeddings),
                )
            feitos += len(linhas)
            chamadas += 1
            if progresso is not None:
                progresso["chunks"] = feitos
            # Com data e hora: é o que separa "está trabalhando devagar" de
            # "está pendurado desde as 13h46" quando se lê o log depois.
            print(f"[{_agora()}] chunks={feitos} lotes={chamadas}", flush=True)
    return {"chunks": feitos, "lotes": chamadas}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lote", type=int, default=64)
    parser.add_argument("--limite", type=int)
    #: Finito de propósito. Antes era `while True`, e o processo NUNCA saía —
    #: o que anulava as 30 retentativas do `sincronizar-rag.ps1`, que só agem
    #: quando o Python termina com código diferente de zero. Duas camadas de
    #: retentativa, e a de dentro impedindo a de fora de existir.
    #:
    #: O orçamento conta apenas falhas SEGUIDAS E ESTÉREIS: ver abaixo.
    parser.add_argument("--tentativas", type=int, default=5)
    args = parser.parse_args()

    total = 0
    restantes = args.tentativas

    while restantes > 0:
        progresso: dict[str, int] = {"chunks": 0}
        try:
            resultado = vetorizar(lote=args.lote, limite=args.limite, progresso=progresso)
            total += resultado["chunks"]
            print(f"[{_agora()}] concluído: {total} chunks no total.", flush=True)
            return 0
        except Exception as exc:
            total += progresso["chunks"]
            # Uma queda DEPOIS de gravar lotes não é a mesma coisa que uma queda
            # sem gravar nada. Nesta rede, a conexão cai a cada poucos lotes; se
            # cada queda consumisse uma tentativa, o processo desistiria com
            # milhares de chunks ainda pendentes tendo funcionado o tempo todo.
            # O orçamento existe para o caso de o banco estar realmente fora, e
            # por isso só falha ESTÉRIL o consome.
            if progresso["chunks"]:
                restantes = args.tentativas
                print(
                    f"[{_agora()}] Queda depois de {progresso['chunks']} chunks "
                    f"({type(exc).__name__}); {total} no total, orçamento renovado.",
                    flush=True,
                )
            else:
                restantes -= 1
                print(
                    f"[{_agora()}] Falha sem progresso ({type(exc).__name__}: "
                    f"{str(exc)[:120]}); restam {restantes} tentativa(s).",
                    flush=True,
                )
            if restantes > 0:
                time.sleep(10)

    print(
        f"[{_agora()}] Desistindo depois de {args.tentativas} falhas seguidas "
        f"sem progresso. {total} chunks gravados nesta execução.",
        flush=True,
    )
    # Código diferente de zero: é assim que o sincronizar-rag.ps1 sabe que
    # precisa esperar 60s e tentar de novo, com o banco possivelmente melhor.
    return 1


if __name__ == "__main__":
    sys.exit(main())
