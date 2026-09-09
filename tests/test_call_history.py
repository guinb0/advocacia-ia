"""Call history persisted by case.

    .venv\Scripts\python.exe -m tests.test_call_history
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

from app import armazenamento, banco


class Result:
    def __init__(self, rows: list[dict[str, str]] | None = None):
        self.rows = rows or []

    def fetchall(self) -> list[dict[str, str]]:
        return self.rows


class FakeConnection:
    def __init__(self) -> None:
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.rows = [
            {
                "id": "call-2",
                "caso_id": "case-1",
                "atendente_id": "attendant-2",
                "atendente_nome": "Bruna Lima",
                "realizada_em": "2026-09-09T11:00:00+00:00",
                "criado_em": "2026-09-09T11:00:00+00:00",
            },
            {
                "id": "call-1",
                "caso_id": "case-1",
                "atendente_id": "attendant-1",
                "atendente_nome": "Ana Souza",
                "realizada_em": "2026-09-09T10:00:00+00:00",
                "criado_em": "2026-09-09T10:00:00+00:00",
            },
        ]

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> Result:
        self.commands.append((sql, params))
        if sql.startswith("SELECT"):
            return Result(self.rows if params == ("case-1",) else [])
        return Result()


def check(condition: bool, description: str) -> int:
    print(f"  {'PASS' if condition else '>> FAILURE'} {description}")
    return 0 if condition else 1


def main() -> int:
    connection = FakeConnection()

    @contextmanager
    def fake_connect():
        yield connection

    with (
        patch.object(armazenamento, "conectar", fake_connect),
        patch.object(armazenamento.uuid, "uuid4", return_value="call-3"),
        patch.object(armazenamento, "agora", return_value="2026-09-09T12:00:00+00:00"),
    ):
        record = armazenamento.register_call("case-1", " attendant-3 ", " Carlos Silva ")
        history = armazenamento.list_calls("case-1")
        other_case_history = armazenamento.list_calls("case-2")

    failures = 0
    failures += check(record["atendente_id"] == "attendant-3", "stores the attendant identifier")
    failures += check(record["atendente_nome"] == "Carlos Silva", "stores the attendant name")
    failures += check(record["realizada_em"] == "2026-09-09T12:00:00+00:00", "stores date and time")
    failures += check(len(history) == 2, "returns all calls for the case")
    failures += check(
        [call["atendente_nome"] for call in history] == ["Bruna Lima", "Ana Souza"],
        "preserves prior records in history order",
    )
    failures += check(other_case_history == [], "does not mix another case history")
    failures += check(
        any("INSERT INTO ligacoes" in sql for sql, _ in connection.commands),
        "inserts a new row without updating existing records",
    )
    failures += check(
        banco._qualificar("SELECT * FROM ligacoes") == "SELECT * FROM dbo.acervo_ligacoes",
        "qualifies the new table for SQL Server",
    )
    print("ALL TESTS PASSED" if not failures else f"{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
