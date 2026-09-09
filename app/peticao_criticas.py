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
) -> dict[str, Any]:
    """Grava uma crítica. Cada revisão gera uma linha nova — nunca sobrescreve."""
    id_critica = str(uuid.uuid4())
    with _conectar(row_factory=dict_row) as con:
        linha = con.execute(
            """
            INSERT INTO peticao_criticas
                   (id, caso_id, categoria, versao_origem, versao_resultado, prompt, usuario)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, caso_id, categoria, versao_origem, versao_resultado,
                      prompt, usuario, criado_em
            """,
            (id_critica, caso_id, categoria, versao_origem, versao_resultado, prompt, usuario),
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
                   prompt, usuario, criado_em
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


def ultimas_da_categoria(categoria: str, *, limite: int = 5) -> list[str]:
    """Os textos das críticas mais recentes desta categoria, para retroalimentar
    a próxima geração — a mais antiga primeiro, na ordem em que o escritório as fez.

    Só o texto, não o registro inteiro: quem monta o prompt não precisa de mais
    que isso, e devolver menos é devolver menos para dar errado quando o
    formato do registro mudar.
    """
    if not categoria:
        return []
    with _conectar(row_factory=dict_row) as con:
        linhas = con.execute(
            """
            SELECT prompt FROM peticao_criticas
             WHERE categoria = %s
             ORDER BY criado_em DESC
             LIMIT %s
            """,
            (categoria, limite),
        ).fetchall()
    return [str(linha["prompt"]) for linha in reversed(linhas)]
