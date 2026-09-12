"""Rastro das alterações relevantes: quem mudou o quê, quando, e como estava antes.

O QUE ENTRA AQUI

Mudança que alguém vai precisar explicar depois: um tipo do glossário renomeado ou
desativado, um documento reclassificado ou devolvido à triagem, um arquivo repetido
aceito com confirmação, um documento removido. Não é log de aplicação — é a resposta
para "por que este documento está neste item, e quem decidiu".

POR QUE UMA TABELA SÓ

Glossário e documentos respondem à mesma pergunta (quem, quando, antes, depois). Duas
tabelas com a mesma forma seriam duas consultas para montar a mesma tela, e o próximo
cadastro auditável teria de escolher em qual das duas cair. `entidade` + `entidade_id`
dizem de quem é cada linha.

POR QUE SEM CHAVE ESTRANGEIRA

O rastro precisa sobreviver ao que ele descreve. O documento removido é justamente o
caso em que alguém pergunta "quem apagou e o que era" — com FK em cascata, apagar a
entrega apagaria a prova de que ela existiu.

POR QUE NA MESMA TRANSAÇÃO DA ALTERAÇÃO

`registrar` usa `conectar()`, que dentro de `banco.sessao()` reaproveita a transação de
quem chamou. Quem altera abre a sessão, altera e registra: ou ficam os dois, ou nenhum.
Alteração sem rastro é exatamente o que este módulo existe para impedir.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .banco import PREFIXO, SCHEMA, conectar

__all__ = [
    "ENTIDADE_ENTREGA",
    "ENTIDADE_TIPO_DOCUMENTO",
    "houve",
    "inicializar",
    "listar",
    "registrar",
]

ENTIDADE_TIPO_DOCUMENTO = "tipo_documento"
ENTIDADE_ENTREGA = "entrega"

_TABELA = f"{SCHEMA}.{PREFIXO}historico_alteracoes"

ESQUEMA = f"""
IF OBJECT_ID('{_TABELA}') IS NULL
CREATE TABLE {_TABELA} (
    id          varchar(64)   NOT NULL CONSTRAINT pk_acervo_historico_alteracoes PRIMARY KEY,
    entidade    varchar(40)   NOT NULL,
    entidade_id varchar(80)   NOT NULL,
    caso_id     varchar(64)   NULL,
    acao        varchar(40)   NOT NULL,
    antes       nvarchar(max) NULL,
    depois      nvarchar(max) NULL,
    motivo      nvarchar(600) NOT NULL CONSTRAINT df_acervo_hist_alt_motivo DEFAULT N'',
    usuario     nvarchar(200) NOT NULL,
    criado_em   varchar(40)   NOT NULL
);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'idx_acervo_hist_alt_entidade')
CREATE INDEX idx_acervo_hist_alt_entidade ON {_TABELA} (entidade, entidade_id, criado_em)
"""


def _agora() -> str:
    # Microssegundos, e não segundos como no resto do Acervo: criar um tipo e
    # corrigi-lo logo em seguida cai no mesmo segundo, e o histórico precisa
    # mostrar os dois na ordem em que aconteceram.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _como_json(valor: Any) -> str | None:
    return None if valor is None else json.dumps(valor, ensure_ascii=False, default=str)


def _de_json(bruto: Any) -> Any:
    if not bruto:
        return None
    try:
        return json.loads(bruto)
    except (TypeError, ValueError):
        return None


def inicializar() -> None:
    """Cria a tabela e o índice, se ainda não existirem. Idempotente."""
    with conectar() as con:
        for lote in ESQUEMA.split(";\n"):
            if lote.strip():
                con.execute(lote)


def registrar(
    entidade: str,
    entidade_id: str,
    acao: str,
    *,
    usuario: str,
    antes: Any = None,
    depois: Any = None,
    caso_id: str | None = None,
    motivo: str = "",
) -> dict[str, Any]:
    """Grava um evento. Chame dentro da `banco.sessao()` da própria alteração."""
    evento = {
        "id": str(uuid.uuid4()),
        "entidade": entidade,
        "entidade_id": str(entidade_id),
        "caso_id": caso_id,
        "acao": acao,
        "antes": antes,
        "depois": depois,
        "motivo": " ".join(str(motivo or "").split())[:600],
        "usuario": (str(usuario or "").strip() or "escritório")[:200],
        "criado_em": _agora(),
    }
    with conectar() as con:
        con.execute(
            f"""
            INSERT INTO {_TABELA}
                (id, entidade, entidade_id, caso_id, acao, antes, depois, motivo, usuario, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evento["id"],
                evento["entidade"],
                evento["entidade_id"],
                evento["caso_id"],
                evento["acao"],
                _como_json(antes),
                _como_json(depois),
                evento["motivo"],
                evento["usuario"],
                evento["criado_em"],
            ),
        )
    return evento


def listar(entidade: str, entidade_id: str, limite: int = 100) -> list[dict[str, Any]]:
    """Eventos de um registro, do mais recente para o mais antigo."""
    with conectar() as con:
        linhas = con.execute(
            f"""
            SELECT TOP (?) id, entidade, entidade_id, caso_id, acao, antes, depois,
                   motivo, usuario, criado_em
              FROM {_TABELA}
             WHERE entidade = ? AND entidade_id = ?
             ORDER BY criado_em DESC
            """,
            (int(limite), entidade, str(entidade_id)),
        ).fetchall()
    return [
        {
            "id": linha["id"],
            "entidade": linha["entidade"],
            "entidade_id": linha["entidade_id"],
            "caso_id": linha["caso_id"],
            "acao": linha["acao"],
            "antes": _de_json(linha["antes"]),
            "depois": _de_json(linha["depois"]),
            "motivo": linha["motivo"] or "",
            "usuario": linha["usuario"],
            "criado_em": linha["criado_em"],
        }
        for linha in linhas
    ]


def houve(entidade: str, entidade_id: str, acao: str) -> bool:
    """Este registro já teve um evento desta ação?"""
    with conectar() as con:
        linha = con.execute(
            f"SELECT TOP 1 1 AS achou FROM {_TABELA}"
            " WHERE entidade = ? AND entidade_id = ? AND acao = ?",
            (entidade, str(entidade_id), acao),
        ).fetchone()
    return linha is not None
