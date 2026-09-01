"""Consistencia do vinculo relacional entre usuarios e perfis.

    .venv\Scripts\python.exe -m tests.test_usuarios_perfis
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.modules.setdefault("pyodbc", types.SimpleNamespace())

from fastapi import HTTPException  # noqa: E402

from app import perfis, usuarios  # noqa: E402


class ConexaoFalsa:
    pass


falhas = 0


def checar(condicao: bool, descricao: str, detalhe: str = "") -> None:
    global falhas
    if condicao:
        print(f"  PASS  {descricao}")
    else:
        falhas += 1
        print(f"  FALHA {descricao}" + (f"\n          {detalhe}" if detalhe else ""))


def main() -> int:
    con = ConexaoFalsa()
    original_nome = perfis.perfil_nome_de_id
    original_id = perfis.perfil_id_de
    try:
        perfis.perfil_nome_de_id = lambda perfil_id, **_: (
            "advogado" if perfil_id == 1 else None
        )
        perfis.perfil_id_de = lambda nome, **_: 1 if nome == "advogado" else None

        checar(
            usuarios._resolver_perfil_usuario(con, 1, None) == (1, "advogado"),
            "perfil_id valido e a fonte principal",
        )
        checar(
            usuarios._resolver_perfil_usuario(con, None, " advogado ") == (1, "advogado"),
            "nome legado continua compativel e resolve para id",
        )

        try:
            usuarios._resolver_perfil_usuario(con, 1, "secretario")
        except HTTPException as erro:
            checar(erro.status_code == 400, "id e nome divergentes sao recusados")
        else:
            checar(False, "id e nome divergentes sao recusados")

        try:
            usuarios._resolver_perfil_usuario(con, 99, None)
        except HTTPException as erro:
            checar(erro.status_code == 400, "id inexistente ou inativo e recusado")
        else:
            checar(False, "id inexistente ou inativo e recusado")

        pedido_atual = usuarios.NovoUsuario(
            nome="Pessoa Teste",
            email="pessoa@example.com",
            perfilId=1,
            senha="12345678",
        )
        pedido_legado = usuarios.NovoUsuario(
            nome="Pessoa Antiga",
            email="antiga@example.com",
            perfil="advogado",
            senha="12345678",
        )
        checar(pedido_atual.perfil_id == 1, "API aceita perfilId do frontend atual")
        checar(pedido_legado.perfil == "advogado", "API preserva contrato textual antigo")
    finally:
        perfis.perfil_nome_de_id = original_nome
        perfis.perfil_id_de = original_id

    return falhas


if __name__ == "__main__":
    raise SystemExit(main())
