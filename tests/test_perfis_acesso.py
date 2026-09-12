"""Quem NAO administra nao mexe em perfil.

O teste olha a rota, e nao a resposta: a barreira aqui e uma dependencia
declarada (`auth.exigir_modulo("usuarios")`), e o jeito de ela sumir sem ninguem
ver e alguem editar a assinatura da funcao e deixar a rota aberta. Uma chamada de
integracao passaria mesmo assim quando a autenticacao estivesse desligada - que e
como o projeto roda em desenvolvimento -, entao ela nao serve de guarda.

    .venv\\Scripts\\python.exe -m tests.test_perfis_acesso
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.modules.setdefault("pyodbc", types.SimpleNamespace())

from app import usuarios  # noqa: E402

#: Toda rota de perfil e o modulo que ela deve exigir. Rota de leitura publica
#: (`GET /api/usuarios/perfis`, o vocabulario do seletor) fica fora de proposito:
#: ela nao expoe o desenho de acesso, so os nomes que o cadastro oferece.
ESPERADO = {
    ("GET", "/api/usuarios/modulos"): "usuarios",
    ("GET", "/api/usuarios/perfis/matriz"): "usuarios",
    ("GET", "/api/usuarios/perfis/historico"): "usuarios",
    ("PUT", "/api/usuarios/perfis/{codigo}"): "usuarios",
    ("DELETE", "/api/usuarios/perfis/{codigo}"): "usuarios",
}

falhas = 0


def checar(condicao: bool, descricao: str, detalhe: str = "") -> None:
    global falhas
    if condicao:
        print(f"  PASS  {descricao}")
    else:
        falhas += 1
        print(f"  FALHA {descricao}" + (f"\n          {detalhe}" if detalhe else ""))


def _modulos_exigidos(dependente) -> set[str]:
    """Os modulos que esta rota exige, lidos das dependencias declaradas.

    `exigir_modulo` devolve uma funcao interna que guarda o nome do modulo no
    proprio closure; e de la que ele sai. Ler o nome da funcao nao bastaria:
    `exigir_papel` e `exigir_modulo` produzem funcoes com o mesmo nome interno.
    """
    achados: set[str] = set()
    for sub in dependente.dependencies:
        chamada = sub.call
        if getattr(chamada, "__qualname__", "").startswith("exigir_modulo"):
            for celula in chamada.__closure__ or ():
                valor = celula.cell_contents
                if isinstance(valor, str):
                    achados.add(valor)
        achados |= _modulos_exigidos(sub)
    return achados


def main() -> int:
    rotas = {}
    for rota in usuarios.roteador.routes:
        for metodo in getattr(rota, "methods", ()):
            rotas[(metodo, rota.path)] = rota

    for (metodo, caminho), modulo in ESPERADO.items():
        rota = rotas.get((metodo, caminho))
        if rota is None:
            checar(False, f"{metodo} {caminho} existe", str(sorted(rotas)))
            continue
        exigidos = _modulos_exigidos(rota.dependant)
        checar(
            modulo in exigidos,
            f"{metodo} {caminho} exige o modulo '{modulo}'",
            f"exigencias encontradas: {sorted(exigidos) or 'NENHUMA — rota aberta'}",
        )

    # O vocabulario continua sem token: e ele que alimenta o seletor do cadastro,
    # e fecha-lo quebraria a tela de usuarios sem proteger nada que ja nao esteja
    # protegido (ele nao diz o que cada perfil alcanca).
    publica = rotas.get(("GET", "/api/usuarios/perfis"))
    checar(publica is not None, "GET /api/usuarios/perfis existe")
    if publica is not None:
        checar(
            _modulos_exigidos(publica.dependant) == set(),
            "vocabulario de perfis segue sem exigencia de modulo",
            str(sorted(_modulos_exigidos(publica.dependant))),
        )

    return falhas


if __name__ == "__main__":
    raise SystemExit(main())
