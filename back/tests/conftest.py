"""Banco SQLite em memória para os testes do fluxo de atendimento.

As consultas de `atendimentos`, `alertas`, `analise_acoes`, `pos_entrevista`,
`whatsapp_modelos`, `automacoes_whatsapp` e `documentacao` ficam no subconjunto
de SQL comum ao SQL Server e ao SQLite (ver `app/esquema_portavel.py`). Aqui a
mesma descrição de tabela vira DDL de SQLite num banco que morre com o teste —
nada encosta no SQL Server.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

import pytest

_DDL_LEGADO = (
    """CREATE TABLE IF NOT EXISTS dbo.acervo_automacoes_whatsapp (
        chave TEXT PRIMARY KEY, tipo TEXT NOT NULL, caso_id TEXT, destino TEXT NOT NULL,
        status TEXT NOT NULL, tentativas INTEGER NOT NULL DEFAULT 1, ultimo_erro TEXT,
        enviado_em TEXT, criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL,
        status_entrega TEXT, mensagem_id TEXT, atendimento_id TEXT, texto_resumo TEXT,
        entregue_em TEXT, lido_em TEXT)""",
    """CREATE TABLE IF NOT EXISTS dbo.acervo_atendimentos_documentacao (
        entrevista_id TEXT PRIMARY KEY, caso_id TEXT, cliente TEXT NOT NULL DEFAULT '',
        sala TEXT, status TEXT NOT NULL DEFAULT 'entrevista', entrevistador_id TEXT NOT NULL,
        entrevistador_nome TEXT NOT NULL, documentador_id TEXT, documentador_nome TEXT,
        iniciado_em TEXT NOT NULL, solicitado_em TEXT, assumido_em TEXT, atualizado_em TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS dbo.acervo_documentadores_online (
        usuario_id TEXT PRIMARY KEY, nome TEXT NOT NULL, atualizado_em TEXT NOT NULL)""",
)


class _ConexaoSqlite:
    def __init__(self, bruta: sqlite3.Connection) -> None:
        self._bruta = bruta

    def execute(self, sql: str, params: Any = ()) -> Any:
        from app import banco

        cursor = self._bruta.cursor()
        cursor.execute(banco._qualificar(sql), tuple(params))
        return banco._Resultado(cursor)


@pytest.fixture
def banco_sqlite(monkeypatch: pytest.MonkeyPatch) -> Iterator[sqlite3.Connection]:
    from app import (
        alertas, analise_acoes, atendimentos, automacoes_whatsapp, banco, criterios_caso,
        documentacao, esquema_portavel, whatsapp_modelos,
    )

    bruta = sqlite3.connect(":memory:", check_same_thread=False)
    bruta.execute("ATTACH DATABASE ':memory:' AS dbo")
    conexao = _ConexaoSqlite(bruta)

    @contextmanager
    def conectar(timeout: int = 15) -> Iterator[_ConexaoSqlite]:
        try:
            yield conexao
            bruta.commit()
        except Exception:
            bruta.rollback()
            raise

    monkeypatch.setattr(banco, "conectar", conectar)
    monkeypatch.setattr(automacoes_whatsapp, "conectar", conectar)
    monkeypatch.setattr(documentacao, "conectar", conectar)

    def criar_sqlite(con: Any, tabelas: Any, dialeto: str = "sqlite") -> None:
        esquema_portavel.criar(con, tabelas, "sqlite")

    for modulo in (atendimentos, alertas, analise_acoes, criterios_caso, whatsapp_modelos):
        monkeypatch.setattr(modulo, "criar_tabelas", criar_sqlite)
        modulo.inicializar()
    for comando in _DDL_LEGADO:
        bruta.execute(comando)
    bruta.commit()

    monkeypatch.setattr(alertas, "_ultima_varredura", 0.0)
    monkeypatch.setattr(documentacao, "_ultima_expiracao", 0.0)
    whatsapp_modelos._cache.clear()
    yield bruta
    bruta.close()


class WhatsappFalso:
    """A Evolution simulada: guarda o que seria enviado e devolve um id de mensagem."""

    def __init__(self) -> None:
        self.enviadas: list[tuple[str, str]] = []
        self.sem_whatsapp: set[str] = set()
        self.falhar = False

    def instalar(self, monkeypatch: pytest.MonkeyPatch) -> "WhatsappFalso":
        from app import whatsapp

        monkeypatch.setattr(whatsapp, "configurado", lambda: True)
        monkeypatch.setattr(whatsapp, "numero_tem_whatsapp_sync", lambda numero: numero not in self.sem_whatsapp)
        monkeypatch.setattr(whatsapp, "_enviar_texto_sync", self._enviar)
        return self

    def _enviar(self, numero: str, texto: str) -> dict[str, Any]:
        if self.falhar:
            raise RuntimeError("Evolution fora do ar")
        self.enviadas.append((numero, texto))
        return {"key": {"id": f"MSG{len(self.enviadas)}"}}


@pytest.fixture
def whatsapp_falso(monkeypatch: pytest.MonkeyPatch) -> WhatsappFalso:
    return WhatsappFalso().instalar(monkeypatch)


class CatalogoFalso:
    """`tipos_caso` em memória: o real usa DDL de SQL Server e o histórico."""

    def __init__(self) -> None:
        self.criados: dict[str, dict[str, Any]] = {}

    def _categoria(self, registro: dict[str, Any]) -> Any:
        from app import categorias

        return categorias.Categoria(
            codigo=registro["codigo"], nome=registro["nome"], descricao=registro["descricao"],
            itens=tuple(
                categorias.ItemChecklist(f"item{n}", n, i["nome"], bool(i["obrigatorio"]))
                for n, i in enumerate(registro["itens"], start=1)
            ),
        )

    def listar(self, incluir_inativos: bool = False) -> list[dict[str, Any]]:
        from app import categorias

        fixos = [
            {"codigo": c.codigo, "nome": c.nome, "descricao": c.descricao, "quando_usar": "",
             "sistema": True, "ativo": True, "itens": []}
            for c in categorias.CATEGORIAS.values()
        ]
        return fixos + list(self.criados.values())

    def criar(self, *, nome: str, usuario: str, descricao: str = "", quando_usar: str = "",
              itens: Any = (), **_: Any) -> dict[str, Any]:
        codigo = "ia_" + "".join(c for c in nome.lower() if c.isalnum())[:30]
        registro = {"codigo": codigo, "nome": nome, "descricao": descricao, "quando_usar": quando_usar,
                    "sistema": False, "ativo": True, "itens": list(itens), "criado_por": usuario}
        self.criados[codigo] = registro
        return registro

    def instalar(self, monkeypatch: pytest.MonkeyPatch) -> "CatalogoFalso":
        from app import categorias, tipos_caso

        monkeypatch.setattr(tipos_caso, "listar", self.listar)
        monkeypatch.setattr(tipos_caso, "criar", self.criar)
        monkeypatch.setattr(categorias, "_do_escritorio",
                            lambda: {c: self._categoria(r) for c, r in self.criados.items()})
        monkeypatch.setattr(categorias, "_desligadas", lambda: set())
        monkeypatch.setattr(categorias, "_com_itens_do_glossario", lambda categoria: categoria)
        return self


@pytest.fixture
def catalogo_falso(monkeypatch: pytest.MonkeyPatch) -> CatalogoFalso:
    return CatalogoFalso().instalar(monkeypatch)
