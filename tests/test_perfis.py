"""Permissoes por perfil.

    .venv\\Scripts\\python.exe -m tests.test_perfis
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.modules.setdefault("pyodbc", types.SimpleNamespace())

from app import perfis  # noqa: E402


class Resultado:
    def __init__(self, linhas):
        self.linhas = linhas

    def fetchall(self):
        return self.linhas

    def fetchone(self):
        return self.linhas[0] if self.linhas else None


class ConexaoFalsa:
    def __init__(self):
        self.perfis = {"advogado": 1}
        self.modulos = {"usuarios": 10, "casos": 20, "agente": 30}
        self.permissoes = {(1, 10): {"id": 99, "hasPermissao": "n"}}
        self.inseridos = []
        self.atualizados = []
        self.modulos_inseridos = []
        self.modulos_atualizados = []
        self.perfis_atualizados = []

    def execute(self, sql, params=()):
        if "SELECT nome FROM dbo.acervo_tb_perfis WHERE ativo = 1 AND nome <> 'cliente'" in sql:
            return Resultado([{"nome": "advogado"}])
        if "SELECT codigo, rotulo, descricao, sistema, criado_em" in sql:
            return Resultado(
                [
                    {
                        "codigo": "advogado",
                        "rotulo": "Advogado",
                        "descricao": "Perfil existente",
                        "sistema": 1,
                        "criado_em": "2026-01-01T00:00:00+00:00",
                    }
                ]
            )
        if "SELECT perfil_codigo, modulo" in sql:
            return Resultado(
                [
                    {"perfil_codigo": "advogado", "modulo": "usuarios"},
                    {"perfil_codigo": "advogado", "modulo": "casos"},
                ]
            )
        if "FROM dbo.acervo_tb_perfis" in sql and "WHERE nome = ?" in sql:
            perfil = self.perfis.get(params[0])
            return Resultado([{"id": perfil}] if perfil else [])
        if "FROM dbo.acervo_tb_modulos_web" in sql and "WHERE nome_modulo = ?" in sql:
            modulo = self.modulos.get(params[0])
            return Resultado([{"id": modulo}] if modulo else [])
        if "FROM dbo.acervo_tb_permissoes" in sql and "WHERE perfil = ? AND modulo = ?" in sql:
            permissao = self.permissoes.get((params[0], params[1]))
            return Resultado([permissao] if permissao else [])
        if sql.strip().startswith("UPDATE dbo.acervo_tb_permissoes"):
            self.atualizados.append(params)
            return Resultado([])
        if sql.strip().startswith("INSERT INTO dbo.acervo_tb_permissoes"):
            self.inseridos.append(params)
            return Resultado([])
        if sql.strip().startswith("UPDATE dbo.acervo_tb_modulos_web"):
            self.modulos_atualizados.append(params)
            return Resultado([])
        if sql.strip().startswith("INSERT INTO dbo.acervo_tb_modulos_web"):
            self.modulos_inseridos.append(params)
            return Resultado([])
        if sql.strip().startswith("UPDATE dbo.acervo_tb_perfis"):
            self.perfis_atualizados.append((sql, params))
            return Resultado([])
        return Resultado([])


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
    perfis._migrar_acessos_legados(con)

    checar(
        con.atualizados == [],
        "migracao legada nao sobrescreve permissao nova ja existente",
        str(con.atualizados),
    )
    checar(
        con.inseridos == [(20, 1, "s")],
        "migracao legada so cria a permissao que ainda nao existia",
        str(con.inseridos),
    )

    con_catalogo = ConexaoFalsa()
    perfis._sincronizar_modulos(con_catalogo)
    checar(
        con_catalogo.modulos_atualizados == [],
        "sincronizacao de modulos nao reativa nem sobrescreve modulo existente",
        str(con_catalogo.modulos_atualizados),
    )

    perfis._sincronizar_perfis(con_catalogo, "2026-01-01T00:00:00+00:00")
    checar(
        all("ativo = 1" not in sql for sql, _ in con_catalogo.perfis_atualizados),
        "sincronizacao de perfis nao reativa perfil novo existente",
        str(con_catalogo.perfis_atualizados),
    )

    con_agente = ConexaoFalsa()
    perfis._liberar_agente_para_perfis_internos(con_agente)
    checar(
        (30, 1, "s") in con_agente.inseridos,
        "agente juridico e liberado para perfil interno existente",
        str(con_agente.inseridos),
    )
    return falhas


if __name__ == "__main__":
    raise SystemExit(main())
