"""Gestao de perfis: o que a trilha registra e o que ela se recusa a registrar.

    .venv\\Scripts\\python.exe -m tests.test_perfis_gestao
"""

import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.modules.setdefault("pyodbc", types.SimpleNamespace())

from app import perfis, usuarios  # noqa: E402


class Resultado:
    def __init__(self, linhas):
        self.linhas = linhas

    def fetchall(self):
        return self.linhas

    def fetchone(self):
        return self.linhas[0] if self.linhas else None


class ConexaoFalsa:
    """Responde o mínimo que `_estado_de` e `_registrar` perguntam."""

    def __init__(self, perfil=None, modulos=()):
        self.perfil = perfil
        self.modulos = list(modulos)
        self.registros = []
        self.contagem = 4

    def execute(self, sql, params=()):
        if "SELECT rotulo, descricao FROM" in sql:
            return Resultado([self.perfil] if self.perfil else [])
        if "AS modulo" in sql and "hasPermissao = 's'" in sql:
            return Resultado([{"modulo": m} for m in self.modulos])
        if sql.strip().startswith("INSERT INTO dbo.acervo_perfil_alteracoes"):
            self.registros.append(params)
            return Resultado([])
        if "COUNT(*) AS n" in sql:
            return Resultado([{"n": self.contagem}])
        if "FROM dbo.acervo_tb_perfis" in sql and "WHERE nome = ?" in sql:
            return Resultado([{"id": 1}])
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
    # ------------------------------------------------ leitura do estado atual
    con = ConexaoFalsa(
        perfil={"rotulo": "Analista", "descricao": "Acompanha a equipe."},
        modulos=("supervisao", "casos"),
    )
    estado = perfis._estado_de(con, "analista")
    checar(
        estado == {
            "rotulo": "Analista",
            "descricao": "Acompanha a equipe.",
            "modulos": ["casos", "supervisao"],
        },
        "estado atual traz rotulo, descricao e modulos ordenados",
        str(estado),
    )
    checar(
        perfis._estado_de(ConexaoFalsa(), "inexistente") is None,
        "perfil que nao existe nao tem estado anterior",
    )

    # ------------------------------------------------ resumo da mudanca
    base = {"rotulo": "Analista", "descricao": "d", "modulos": ["casos"]}
    checar(
        perfis._resumo_da_mudanca(base, dict(base)) == "",
        "salvar sem mexer em nada nao vira alteracao",
        perfis._resumo_da_mudanca(base, dict(base)),
    )
    checar(
        perfis._resumo_da_mudanca(None, base) == "perfil criado com casos",
        "criacao e descrita como criacao",
        perfis._resumo_da_mudanca(None, base),
    )
    concedeu = perfis._resumo_da_mudanca(base, {**base, "modulos": ["casos", "revisao"]})
    checar(
        concedeu == "módulos concedidos: revisao",
        "modulo concedido aparece no resumo",
        concedeu,
    )
    retirou = perfis._resumo_da_mudanca(base, {**base, "modulos": []})
    checar(
        retirou == "módulos retirados: casos",
        "modulo retirado aparece no resumo",
        retirou,
    )
    renomeou = perfis._resumo_da_mudanca(base, {**base, "rotulo": "Analista sênior"})
    checar(
        "rótulo" in renomeou and "Analista sênior" in renomeou,
        "rotulo alterado aparece no resumo",
        renomeou,
    )
    checar(
        perfis._resumo_da_mudanca(base, {**base, "descricao": "outra"}) == "descrição alterada",
        "descricao alterada aparece no resumo",
    )

    # ------------------------------------------------ gravacao da trilha
    vazia = ConexaoFalsa()
    checar(
        perfis._registrar(vazia, "analista", "atualizado", base, base, "", "eu@x", "2026-01-01")
        is None
        and vazia.registros == [],
        "resumo vazio nao grava linha na trilha",
        str(vazia.registros),
    )

    com_registro = ConexaoFalsa()
    devolvido = perfis._registrar(
        com_registro,
        "analista",
        "atualizado",
        base,
        {**base, "modulos": []},
        "módulos retirados: casos",
        "gestor@escritorio.adv.br",
        "2026-01-01T00:00:00+00:00",
    )
    checar(len(com_registro.registros) == 1, "alteracao real grava uma linha")
    gravado = com_registro.registros[0] if com_registro.registros else ()
    checar(
        gravado[:4]
        == (
            "analista",
            "atualizado",
            "gestor@escritorio.adv.br",
            "módulos retirados: casos",
        ),
        "perfil, acao, autor e resumo vao para a trilha",
        str(gravado[:4]),
    )
    checar(
        json.loads(gravado[4])["modulos"] == ["casos"] and json.loads(gravado[5])["modulos"] == [],
        "estado anterior e novo ficam gravados como JSON",
        str(gravado[4:6]),
    )
    checar(
        devolvido is not None and devolvido["autor"] == "gestor@escritorio.adv.br",
        "o registro devolvido identifica quem alterou",
    )

    sem_autor = ConexaoFalsa()
    perfis._registrar(sem_autor, "analista", "criado", None, base, "perfil criado", "", "2026-01-01")
    checar(
        sem_autor.registros[0][2] == "desconhecido",
        "alteracao sem sessao grava autor 'desconhecido', nao vazio",
        str(sem_autor.registros[0][2]),
    )

    # ------------------------------------------------ impacto medido
    checar(
        perfis._quantos_usam(ConexaoFalsa(), "analista") == 4,
        "impacto conta as contas ligadas ao perfil",
    )

    # ------------------------------------------------ autor da rota
    checar(
        usuarios._autor(usuarios.auth.USUARIO_ABERTO) == "sessão sem autenticação",
        "com a autenticacao desligada a trilha diz isso, em vez de inventar nome",
        usuarios._autor(usuarios.auth.USUARIO_ABERTO),
    )

    return falhas


if __name__ == "__main__":
    raise SystemExit(main())
