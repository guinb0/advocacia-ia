"""Críticas/prompts de revisão de petição, no PostgreSQL do pgvector.

Issue "[Petição - IA] Permitir alteração da petição por prompt com
rastreabilidade". Mesmo raciocínio de `app/peticao_skills.py`: a crítica é
insumo de IA — ela não só documenta o que aconteceu numa petição (isso está em
`peticao_versoes`, no SQL Server, junto do resto do estado do caso), como
também **retroalimenta as próximas gerações da mesma categoria** (decisão do
escritório: a retroalimentação é automática, não depende de promover nada à
mão — ver `peticao_local._com_skill_do_escritorio`). Por ser o insumo que
ensina a IA, mora no Postgres.

Cada linha é uma crítica: quem pediu, quando, em cima de qual versão, e o que
a revisão virou. `listar_por_caso` cobre a rastreabilidade por caso que a
issue pede; `ultimas_da_categoria` é o que alimenta a retroalimentação
automática entre casos.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


def _url() -> str:
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            texto = linha.strip()
            if texto and not texto.startswith("#") and "=" in texto:
                chave, valor = texto.split("=", 1)
                os.environ.setdefault(chave.strip(), valor.strip())
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("Defina DATABASE_URL para persistir críticas de petição.")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _conectar(**kwargs: Any):
    return psycopg.connect(_url(), connect_timeout=10, **kwargs)


def inicializar() -> None:
    with _conectar() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS peticao_criticas (
                id              uuid PRIMARY KEY,
                caso_id         varchar(64) NOT NULL,
                categoria       varchar(80) NOT NULL,
                versao_origem   integer NOT NULL,
                versao_resultado integer NOT NULL,
                prompt          text NOT NULL,
                usuario         varchar(200) NOT NULL DEFAULT '',
                criado_em       timestamptz NOT NULL DEFAULT now()
            )
        """)
        # Coluna acrescentada depois: uma crítica pode valer só para o caso em
        # que foi feita ("troque o nome do cliente"), e essa NÃO pode instruir
        # as próximas petições da categoria. `IF NOT EXISTS` porque o banco em
        # produção já tem a tabela sem ela; o default `true` preserva o que já
        # estava gravado como generalizável, que era o comportamento único.
        con.execute(
            "ALTER TABLE peticao_criticas "
            "  ADD COLUMN IF NOT EXISTS generaliza boolean NOT NULL DEFAULT true"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS ix_peticao_criticas_caso"
            "    ON peticao_criticas (caso_id, criado_em)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS ix_peticao_criticas_categoria"
            "    ON peticao_criticas (categoria, criado_em)"
        )


def registrar(
    *,
    caso_id: str,
    categoria: str,
    versao_origem: int,
    versao_resultado: int,
    prompt: str,
    usuario: str,
    generaliza: bool = True,
) -> dict[str, Any]:
    """Grava uma crítica. Cada revisão gera uma linha nova — nunca sobrescreve.

    `generaliza=False` marca a crítica como "só deste caso": ela continua na
    rastreabilidade (`listar_por_caso`) e some da retroalimentação
    (`ultimas_da_categoria`). É o que separa uma lição do escritório — "sempre
    separe dano moral do material" — de um ajuste pontual — "troque o nome do
    cliente" —, que instruindo as próximas petições faria estrago.
    """
    id_critica = str(uuid.uuid4())
    with _conectar(row_factory=dict_row) as con:
        linha = con.execute(
            """
            INSERT INTO peticao_criticas
                   (id, caso_id, categoria, versao_origem, versao_resultado, prompt,
                    usuario, generaliza)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, caso_id, categoria, versao_origem, versao_resultado,
                      prompt, usuario, generaliza, criado_em
            """,
            (id_critica, caso_id, categoria, versao_origem, versao_resultado, prompt,
             usuario, generaliza),
        ).fetchone()
    assert linha is not None
    linha["id"] = str(linha["id"])
    linha["criado_em"] = str(linha["criado_em"])
    return linha


def listar_por_caso(caso_id: str) -> list[dict[str, Any]]:
    """Histórico completo de críticas deste caso — rastreabilidade por versão."""
    with _conectar(row_factory=dict_row) as con:
        linhas = con.execute(
            """
            SELECT id, caso_id, categoria, versao_origem, versao_resultado,
                   prompt, usuario, generaliza, criado_em
              FROM peticao_criticas
             WHERE caso_id = %s
             ORDER BY criado_em
            """,
            (caso_id,),
        ).fetchall()
    for linha in linhas:
        linha["id"] = str(linha["id"])
        linha["criado_em"] = str(linha["criado_em"])
    return linhas


def _chave(texto: str) -> str:
    """Duas críticas "iguais" para efeito de repetição.

    O advogado reescreve a mesma lição com outras palavras e outra pontuação —
    "separe dano moral do material" e "Separe o dano moral do material!" são a
    mesma instrução ocupando duas vagas do prompt. Normalizar caixa, pontuação e
    espaço resolve a maioria dos casos reais sem inventar semelhança semântica,
    que erraria em silêncio e juntaria lições diferentes.
    """
    limpo = "".join(c if c.isalnum() or c.isspace() else " " for c in texto.lower())
    return " ".join(limpo.split())


def _licoes(prompts_recentes_primeiro: list[str], limite: int) -> list[str]:
    """Da lista crua (mais recente primeiro) para as lições do prompt (mais antiga
    primeiro), sem repetição e dentro do teto.

    Separada da consulta de propósito: é a regra que decide o que a IA aprende, e
    regra se testa sem precisar de banco de pé.
    """
    vistas: set[str] = set()
    recentes_primeiro: list[str] = []
    for texto in prompts_recentes_primeiro:
        limpo = texto.strip()
        chave = _chave(limpo)
        if not chave or chave in vistas:
            continue
        vistas.add(chave)
        recentes_primeiro.append(limpo)
        if len(recentes_primeiro) >= limite:
            break
    return list(reversed(recentes_primeiro))


def ultimas_da_categoria(categoria: str, *, limite: int = 20) -> list[str]:
    """As críticas que instruem a próxima geração desta categoria.

    Da mais antiga para a mais recente, na ordem em que o escritório as fez.

    Três filtros, e cada um existe por um motivo medido:

    - **`generaliza`**: a crítica marcada como "só deste caso" fica fora. Sem
      isso, um "troque o nome do cliente" passava a instruir todas as petições
      da categoria.
    - **Repetidas**: a mesma lição dita cinco vezes ocupava cinco vagas e
      afogava as outras. Fica a redação MAIS RECENTE de cada lição — é a que o
      escritório escreveu por último, e o lugar dela na ordem é o da última vez
      em que foi cobrada.
    - **`limite`**: teto de contexto. Era 5, o que fazia a IA esquecer a
      primeira lição assim que chegava a sexta — o escritório corrigia de novo
      algo já ensinado. 20 cabe no prompt e cobre o que uma categoria acumula
      em meses de uso.

    A consulta pede mais linhas que o limite justamente porque a deduplicação
    acontece depois: sem essa folga, dez repetições da mesma frase devolveriam
    uma lição só e as outras dezenove ficariam de fora.
    """
    if not categoria:
        return []
    with _conectar(row_factory=dict_row) as con:
        linhas = con.execute(
            """
            SELECT prompt FROM peticao_criticas
             WHERE categoria = %s AND generaliza
             ORDER BY criado_em DESC
             LIMIT %s
            """,
            (categoria, max(limite * 5, limite)),
        ).fetchall()

    return _licoes([str(l["prompt"]) for l in linhas], limite)
