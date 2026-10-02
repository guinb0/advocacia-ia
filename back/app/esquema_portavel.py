"""Tabelas descritas uma vez e criadas em SQL Server (produção) ou SQLite (testes).

Os módulos do atendimento (agenda, alertas, modelos de WhatsApp, análise) guardam
estado que precisa ser testado de ponta a ponta — transição concorrente, chave
única de alerta, lembrete que não pode sair duas vezes. Testar isso com dublê de
função provaria pouco; testar no SQL Server de produção é proibido. A saída é a
mesma descrição de tabela gerar o DDL dos dois dialetos, e o SQL das consultas
ficar no subconjunto comum (`?`, `UPDATE ... WHERE` + `rowcount`, sem `TOP` nem
`OUTPUT`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Tipo lógico → (SQL Server, SQLite). Tipo fora da tabela passa cru para o SQL Server.
TIPOS: dict[str, tuple[str, str]] = {
    "id": ("varchar(64)", "TEXT"),
    "chave": ("varchar(220)", "TEXT"),
    "codigo": ("varchar(60)", "TEXT"),
    "data": ("varchar(40)", "TEXT"),
    "curto": ("nvarchar(200)", "TEXT"),
    "texto": ("nvarchar(1000)", "TEXT"),
    "longo": ("nvarchar(max)", "TEXT"),
    "inteiro": ("int", "INTEGER"),
}


@dataclass(frozen=True)
class Coluna:
    nome: str
    tipo: str
    nula: bool = True
    padrao: Any = None


@dataclass(frozen=True)
class Tabela:
    nome: str
    colunas: tuple[Coluna, ...]
    chave_primaria: tuple[str, ...]
    unicos: tuple[tuple[str, tuple[str, ...]], ...] = field(default_factory=tuple)
    indices: tuple[tuple[str, tuple[str, ...]], ...] = field(default_factory=tuple)

    @property
    def curto(self) -> str:
        return self.nome.split(".")[-1]


def _tipo(coluna: Coluna, dialeto: str) -> str:
    par = TIPOS.get(coluna.tipo)
    if par is None:
        return coluna.tipo if dialeto == "sqlserver" else "TEXT"
    return par[0] if dialeto == "sqlserver" else par[1]


def _literal(valor: Any) -> str:
    if isinstance(valor, bool):
        return str(int(valor))
    if isinstance(valor, (int, float)):
        return str(valor)
    texto = str(valor).replace("'", "''")
    return f"'{texto}'"


def ddl_sqlserver(tabela: Tabela) -> list[str]:
    linhas = []
    for c in tabela.colunas:
        parte = f"    {c.nome} {_tipo(c, 'sqlserver')} {'NULL' if c.nula else 'NOT NULL'}"
        if c.padrao is not None:
            parte += f" CONSTRAINT df_{tabela.curto}_{c.nome} DEFAULT {_literal(c.padrao)}"
        linhas.append(parte)
    linhas.append(
        f"    CONSTRAINT pk_{tabela.curto} PRIMARY KEY ({', '.join(tabela.chave_primaria)})"
    )
    comandos = [
        f"IF OBJECT_ID('{tabela.nome}') IS NULL CREATE TABLE {tabela.nome} (\n"
        + ",\n".join(linhas)
        + "\n)"
    ]
    for c in tabela.colunas:
        definicao = f"{_tipo(c, 'sqlserver')} {'NULL' if c.nula else 'NOT NULL'}"
        if c.padrao is not None:
            definicao += f" CONSTRAINT df_{tabela.curto}_{c.nome} DEFAULT {_literal(c.padrao)}"
        elif not c.nula:
            # Coluna obrigatória sem padrão não pode nascer numa tabela com linhas.
            continue
        comandos.append(
            f"IF COL_LENGTH('{tabela.nome}', '{c.nome}') IS NULL "
            f"ALTER TABLE {tabela.nome} ADD {c.nome} {definicao}"
        )
    for nome, colunas in tabela.unicos:
        comandos.append(
            f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = '{nome}') "
            f"CREATE UNIQUE INDEX {nome} ON {tabela.nome} ({', '.join(colunas)})"
        )
    for nome, colunas in tabela.indices:
        comandos.append(
            f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = '{nome}') "
            f"CREATE INDEX {nome} ON {tabela.nome} ({', '.join(colunas)})"
        )
    return comandos


def ddl_sqlite(tabela: Tabela) -> list[str]:
    linhas = []
    for c in tabela.colunas:
        parte = f"{c.nome} {_tipo(c, 'sqlite')} {'NULL' if c.nula else 'NOT NULL'}"
        if c.padrao is not None:
            parte += f" DEFAULT {_literal(c.padrao)}"
        linhas.append(parte)
    linhas.append(f"PRIMARY KEY ({', '.join(tabela.chave_primaria)})")
    comandos = [f"CREATE TABLE IF NOT EXISTS {tabela.nome} ({', '.join(linhas)})"]
    esquema, _, curto = tabela.nome.rpartition(".")
    prefixo = f"{esquema}." if esquema else ""
    for nome, colunas in tabela.unicos:
        comandos.append(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {prefixo}{nome} ON {curto} ({', '.join(colunas)})"
        )
    for nome, colunas in tabela.indices:
        comandos.append(
            f"CREATE INDEX IF NOT EXISTS {prefixo}{nome} ON {curto} ({', '.join(colunas)})"
        )
    return comandos


def criar(con: Any, tabelas: tuple[Tabela, ...] | list[Tabela], dialeto: str = "sqlserver") -> None:
    """Cria (ou completa) as tabelas. Idempotente nos dois dialetos."""
    gerar = ddl_sqlserver if dialeto == "sqlserver" else ddl_sqlite
    for tabela in tabelas:
        for comando in gerar(tabela):
            con.execute(comando)
