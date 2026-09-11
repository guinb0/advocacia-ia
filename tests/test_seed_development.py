"""Safety checks for the local development seeder.

    .venv\Scripts\python.exe -m tests.test_seed_development
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import seed_development  # noqa: E402
from app.tasks import agente as agent_tasks  # noqa: E402
from app.tasks.agente import DEVELOPMENT_CASE_PREFIX, enviar_entrega_ao_agente  # noqa: E402

failures = 0


def check(condition: bool, description: str) -> None:
    global failures
    if condition:
        print(f"  PASS  {description}")
    else:
        failures += 1
        print(f"  FAIL  {description}")


def validate(host: str, port: str, test_data: str) -> str:
    names = ("SQLSERVER_HOST", "SQLSERVER_PORT", "PERMITIR_DADOS_TESTE")
    previous = {name: os.environ.get(name) for name in names}
    os.environ.update(
        {
            "SQLSERVER_HOST": host,
            "SQLSERVER_PORT": port,
            "PERMITIR_DADOS_TESTE": test_data,
        }
    )
    try:
        seed_development._require_local_environment()
    except RuntimeError as error:
        return str(error)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    return ""


def main() -> int:
    print("== development seeder safety ==")
    check(
        not validate("127.0.0.1", "14333", "true"),
        "accepts the explicitly enabled local SQL Server",
    )
    check(
        bool(validate("10.200.1.1", "14333", "true")),
        "rejects a non-local SQL Server host",
    )
    check(
        bool(validate("127.0.0.1", "1433", "true")),
        "rejects a port other than the local development port",
    )
    check(
        bool(validate("127.0.0.1", "14333", "false")),
        "requires explicit permission for synthetic data",
    )
    check(
        DEVELOPMENT_CASE_PREFIX == seed_development.CASE_PREFIX
        and enviar_entrega_ao_agente.run("dev-seed-check", "delivery") is False,
        "excludes synthetic deliveries from the agent queue before any agent request",
    )
    original_get_case = agent_tasks.armazenamento.obter_caso
    agent_tasks.armazenamento.obter_caso = lambda case_id: None
    try:
        check(
            enviar_entrega_ao_agente.run("removed-case", "delivery") is False,
            "discards queued deliveries when their case was removed",
        )
    finally:
        agent_tasks.armazenamento.obter_caso = original_get_case
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
