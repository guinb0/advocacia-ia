"""Paginação da listagem de casos sem carregar a carteira inteira."""

from __future__ import annotations

from typing import Any

from app import armazenamento


class ResultadoFalso:
    def __init__(self, *, uma: Any = None, todas: list[Any] | None = None) -> None:
        self._uma = uma
        self._todas = todas or []

    def fetchone(self) -> Any:
        return self._uma

    def fetchall(self) -> list[Any]:
        return self._todas


class ConexaoFalsa:
    def __init__(self) -> None:
        self.consultas: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> "ConexaoFalsa":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> ResultadoFalso:
        self.consultas.append((sql, params))
        if "COUNT(*) FROM casos" in sql:
            return ResultadoFalso(uma=(19,))
        return ResultadoFalso(
            todas=[
                {
                    "id": "caso-9",
                    "cliente": "Cliente 9",
                    "atualizado_em": "2026-08-09T12:00:00+00:00",
                    "portal_senha_hash": "não pode sair",
                    "portal_sal": "não pode sair",
                    "portal_token": "token",
                    "total_entregas": 2,
                }
            ]
        )


def test_storage_busca_somente_o_recorte(monkeypatch: Any) -> None:
    conexao = ConexaoFalsa()
    monkeypatch.setattr(armazenamento, "conectar", lambda: conexao)

    casos, total = armazenamento.listar_casos_paginados(limite=8, deslocamento=8)

    assert total == 19
    assert [caso["id"] for caso in casos] == ["caso-9"]
    assert casos[0]["portal_ativo"] is True
    assert "portal_senha_hash" not in casos[0]
    assert conexao.consultas[1][1] == (8, 8)
    assert "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY" in conexao.consultas[1][0]


def test_storage_recusa_recorte_invalido() -> None:
    try:
        armazenamento.listar_casos_paginados(limite=0, deslocamento=0)
    except ValueError as exc:
        assert str(exc) == "O limite deve ser maior que zero."
    else:
        raise AssertionError("limite zero deveria ser recusado")
