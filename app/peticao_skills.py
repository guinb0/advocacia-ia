"""Skill/prompt configurável por categoria de petição, no PostgreSQL do pgvector.

Fica no mesmo banco do RAG e não no SQL Server do Acervo porque é o Postgres quem
tem a extensão `pgvector` — tudo que é insumo para a IA jurídica mora lá, para o
dia em que esta configuração precisar ser buscada por similaridade ou cruzada com
os embeddings de estilo. Mesmo padrão de `app/jobs.py`: conexão própria,
`inicializar()` idempotente chamada antes de cada uso, sem depender de migração
manual em produção.

Chave é a `categoria` de `app/categorias.py` (as ações que o escritório atende —
acidente do trabalho, doença ocupacional etc.). Sem linha para uma categoria, ela
segue com o prompt padrão de `app/peticao_local.py` — não é preciso cadastrar as
cinco para o sistema continuar funcionando.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

log = logging.getLogger("peticao_skills")


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
        raise RuntimeError("Defina DATABASE_URL para persistir a skill de petição.")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _conectar(**kwargs: Any):
    return psycopg.connect(_url(), connect_timeout=10, **kwargs)


def inicializar() -> None:
    with _conectar() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS peticao_skills (
                categoria      varchar(80) PRIMARY KEY,
                instrucoes     text NOT NULL DEFAULT '',
                atualizado_por varchar(200) NOT NULL DEFAULT '',
                criado_em      timestamptz NOT NULL DEFAULT now(),
                atualizado_em  timestamptz NOT NULL DEFAULT now()
            )
        """)


def salvar(categoria: str, *, instrucoes: str, atualizado_por: str = "") -> dict[str, Any]:
    """Grava (ou regrava) a skill daquela categoria. Idempotente pela categoria."""
    with _conectar() as con:
        con.execute(
            """
            INSERT INTO peticao_skills (categoria, instrucoes, atualizado_por)
                 VALUES (%s, %s, %s)
            ON CONFLICT (categoria) DO UPDATE
                SET instrucoes = EXCLUDED.instrucoes,
                    atualizado_por = EXCLUDED.atualizado_por,
                    atualizado_em = now()
            """,
            (categoria, instrucoes, atualizado_por),
        )
    return obter(categoria) or {}


def obter(categoria: str) -> dict[str, Any] | None:
    with _conectar(row_factory=dict_row) as con:
        linha = con.execute(
            "SELECT categoria, instrucoes, atualizado_por, criado_em, atualizado_em"
            "  FROM peticao_skills WHERE categoria = %s",
            (categoria,),
        ).fetchone()
    if linha:
        linha["criado_em"] = str(linha["criado_em"])
        linha["atualizado_em"] = str(linha["atualizado_em"])
    return linha


def listar() -> list[dict[str, Any]]:
    with _conectar(row_factory=dict_row) as con:
        linhas = con.execute(
            "SELECT categoria, instrucoes, atualizado_por, criado_em, atualizado_em"
            "  FROM peticao_skills ORDER BY categoria"
        ).fetchall()
    for linha in linhas:
        linha["criado_em"] = str(linha["criado_em"])
        linha["atualizado_em"] = str(linha["atualizado_em"])
    return linhas


#: Chave da orientação que vale para TODA peça, independente da ação.
#:
#: O escritório pediu para parar de configurar por ação: o que ele ensina sobre
#: como redigir vale para a peça inteira, e dividir por categoria fazia a mesma
#: instrução ser reescrita cinco vezes. Guardada na MESMA tabela, como uma linha
#: reservada, porque o formato é idêntico — muda só o escopo de quem a lê.
#:
#: O prefixo `__` mantém a chave fora do espaço dos códigos reais de categoria
#: (`acidente_trabalho_correios` e afins), então nenhuma ação futura colide com
#: ela por acidente.
CATEGORIA_GERAL = "__geral__"


def instrucoes_gerais() -> str:
    """A orientação única do escritório, válida para qualquer peça.

    Mesma tolerância a falha de `instrucoes_da_categoria`: instrução é insumo
    opcional, e o pgvector fora do ar não pode impedir a petição de sair.
    """
    return instrucoes_da_categoria(CATEGORIA_GERAL)


def instrucoes_da_categoria(categoria: str) -> str:
    """Só o texto, para quem monta o prompt — vazio quando não há skill cadastrada.

    Não propaga erro de conexão: uma oscilação do pgvector não pode derrubar a
    geração da petição por causa de uma instrução opcional. Sem ela, a IA usa o
    prompt padrão, que é exatamente o comportamento de antes desta configuração
    existir.
    """
    if not categoria:
        return ""
    try:
        registro = obter(categoria)
    except Exception:
        # Silêncio total aqui custou tempo de diagnóstico: com o pgvector fora do
        # ar (ou a tabela ainda não criada) a petição saía SEM a instrução do
        # escritório e nada dizia isso em lugar nenhum — o sintoma era "a IA
        # ignorou a skill", indistinguível de skill mal escrita. O registro não
        # muda o comportamento, só deixa rastro de que a instrução não foi lida.
        log.warning(
            "skill da categoria %r não pôde ser lida; a petição será gerada com o "
            "prompt padrão",
            categoria,
            exc_info=True,
        )
        return ""
    return (registro or {}).get("instrucoes", "") or ""
