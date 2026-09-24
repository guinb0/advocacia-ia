"""Estado humano sobre um fato do case brief — confirmado, corrigido ou rejeitado.

POR QUE ISTO EXISTE

Sem isto, um insight da tela de revisão era só um card: a IA mostrava "Comprovante
de residência em nome de Maria", o advogado lia, e na próxima geração — ou na
próxima vez que alguém abrisse o caso — a mesma pergunta aparecia de novo, porque
nada do que foi respondido tinha para onde ir. `case_brief.montar` reconstrói o
brief do zero a cada chamada, a partir da leitura crua dos documentos
(`analise_documentos`), então sem uma camada própria de estado a resposta do
advogado nunca sobrevivia à releitura.

Esta tabela é essa camada: por `(caso_id, fato_id)`, guarda o ÚLTIMO estado —
não um log de tudo que já aconteceu (isso é `historico_alteracoes`, para quem
precisar de auditoria completa depois). `fato_id` é o id que `case_brief.montar`
já atribui (`fato-1`, `evento-1`, ...) — estável enquanto a mesma leitura de
documentos gerar a mesma lista na mesma ordem; se a leitura mudar (documento
novo, reanálise), ids somem e aparecem, e o estado antigo de um id que não
existe mais simplesmente não é aplicado a nada. Não é o ideal, mas é o mesmo
custo que qualquer id posicional paga, e recriar isso com um id semântico
estável exigiria mudar `analise_documentos` para também versionar achados —
fora do escopo desta camada.

PRIORIDADE DA CORREÇÃO HUMANA

`case_brief.montar` aplica os estados por cima da leitura crua: um fato
`CORRECTED` aparece com o valor corrigido, não o do OCR; um `REJECTED` sai da
lista que alimenta a geração. Ver `case_brief.montar` para onde isso acontece.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

#: Vocabulário fechado do estado de um insight.
ESTADOS = {"DETECTED", "CONFIRMED", "CORRECTED", "REJECTED", "NEEDS_CONFIRMATION"}


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
        raise RuntimeError("Defina DATABASE_URL para persistir estado do case brief.")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _conectar(**kwargs: Any):
    return psycopg.connect(_url(), connect_timeout=10, **kwargs)


def inicializar() -> None:
    with _conectar() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS case_brief_estados (
                id              uuid PRIMARY KEY,
                caso_id         varchar(64) NOT NULL,
                fato_id         varchar(80) NOT NULL,
                estado          varchar(24) NOT NULL,
                valor_original  text NOT NULL DEFAULT '',
                valor_corrigido text NOT NULL DEFAULT '',
                observacao      text NOT NULL DEFAULT '',
                usuario         varchar(200) NOT NULL DEFAULT '',
                criado_em       timestamptz NOT NULL DEFAULT now(),
                atualizado_em   timestamptz NOT NULL DEFAULT now(),
                UNIQUE (caso_id, fato_id)
            )
        """)
        con.execute(
            "CREATE INDEX IF NOT EXISTS ix_case_brief_estados_caso"
            "    ON case_brief_estados (caso_id)"
        )


def definir_estado(
    caso_id: str,
    fato_id: str,
    estado: str,
    *,
    valor_original: str = "",
    valor_corrigido: str = "",
    observacao: str = "",
    usuario: str = "",
) -> dict[str, Any]:
    """Grava (ou substitui) o estado humano deste fato — upsert por `(caso_id, fato_id)`.

    Substituir e não acumular é deliberado: o que importa para a próxima
    geração é a última palavra do advogado, não a sequência de idas e vindas.
    """
    estado = estado.strip().upper()
    if estado not in ESTADOS:
        raise ValueError(f"Estado inválido: {estado!r}. Use um de {sorted(ESTADOS)}.")
    if not caso_id.strip() or not fato_id.strip():
        raise ValueError("caso_id e fato_id são obrigatórios.")

    agora = datetime.now(timezone.utc)
    with _conectar(row_factory=dict_row) as con:
        linha = con.execute(
            """
            INSERT INTO case_brief_estados
                (id, caso_id, fato_id, estado, valor_original, valor_corrigido,
                 observacao, usuario, criado_em, atualizado_em)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (caso_id, fato_id) DO UPDATE SET
                estado = EXCLUDED.estado,
                valor_original = CASE WHEN EXCLUDED.valor_original <> ''
                                       THEN EXCLUDED.valor_original
                                       ELSE case_brief_estados.valor_original END,
                valor_corrigido = EXCLUDED.valor_corrigido,
                observacao = EXCLUDED.observacao,
                usuario = EXCLUDED.usuario,
                atualizado_em = EXCLUDED.atualizado_em
            RETURNING *
            """,
            (
                str(uuid.uuid4()), caso_id, fato_id, estado, valor_original,
                valor_corrigido, observacao, usuario, agora, agora,
            ),
        ).fetchone()
    return dict(linha)


def estados_do_caso(caso_id: str) -> dict[str, dict[str, Any]]:
    """Todos os estados já registrados neste caso, por `fato_id`."""
    with _conectar(row_factory=dict_row) as con:
        linhas = con.execute(
            "SELECT * FROM case_brief_estados WHERE caso_id = %s", (caso_id,)
        ).fetchall()
    return {str(linha["fato_id"]): dict(linha) for linha in linhas}
