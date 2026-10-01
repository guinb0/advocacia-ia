"""Edicao de contas: so o secretario, e o que o servidor aceita ou recusa.

    .venv\\Scripts\\python.exe -m tests.test_usuarios_edicao

A guarda e conferida na ROTA (dependencia declarada), pelo mesmo motivo de
`test_perfis_acesso.py`: com a autenticacao desligada, que e como o projeto roda
em desenvolvimento, uma chamada HTTP passaria mesmo com a rota aberta.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.modules.setdefault("pyodbc", types.SimpleNamespace())

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app import usuarios  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str, detalhe: str = "") -> None:
    global falhas
    if condicao:
        print(f"  PASS  {descricao}")
    else:
        falhas += 1
        print(f"  FALHA {descricao}" + (f"\n          {detalhe}" if detalhe else ""))


def _exigencias(dependente, fabrica: str) -> set[str]:
    """Os valores que `auth.<fabrica>` guardou no closure das dependencias da rota."""
    achados: set[str] = set()
    for sub in dependente.dependencies:
        chamada = sub.call
        if getattr(chamada, "__qualname__", "").startswith(fabrica):
            for celula in chamada.__closure__ or ():
                if isinstance(celula.cell_contents, str):
                    achados.add(celula.cell_contents)
        achados |= _exigencias(sub, fabrica)
    return achados


def main() -> int:
    # ------------------------------------------------------------ guardas
    rotas = {}
    for rota in usuarios.roteador.routes:
        for metodo in getattr(rota, "methods", ()):
            rotas[(metodo, rota.path)] = rota

    editar = rotas.get(("PUT", "/api/usuarios/{codigo}"))
    checar(editar is not None, "PUT /api/usuarios/{codigo} existe")
    if editar is not None:
        checar(
            "secretario" in _exigencias(editar.dependant, "exigir_papel"),
            "editar conta exige o PAPEL secretario",
            str(_exigencias(editar.dependant, "exigir_papel")),
        )
        checar(
            not _exigencias(editar.dependant, "exigir_modulo"),
            "editar conta NAO se libera por modulo (a matriz nao concede este poder)",
            str(_exigencias(editar.dependant, "exigir_modulo")),
        )

    desativar = rotas.get(("DELETE", "/api/usuarios/{codigo}"))
    checar(
        desativar is not None
        and "secretario" in _exigencias(desativar.dependant, "exigir_papel"),
        "desativar conta tambem exige o papel secretario",
    )

    criar = rotas.get(("POST", "/api/usuarios"))
    checar(
        criar is not None and "usuarios" in _exigencias(criar.dependant, "exigir_modulo"),
        "cadastrar conta continua com o modulo usuarios (advogado cadastra na hora)",
    )

    # ------------------------------------------------------------ telefone
    checar(usuarios._normalizar_telefone("") is None, "telefone vazio vira None")
    checar(
        usuarios._normalizar_telefone("(61) 99999-0000") == "61999990000",
        "telefone com mascara guarda so os digitos",
        str(usuarios._normalizar_telefone("(61) 99999-0000")),
    )
    checar(
        usuarios._normalizar_telefone("+55 61 3333-4444") == "556133334444",
        "telefone com +55 e aceito",
    )
    try:
        usuarios._normalizar_telefone("12345")
    except HTTPException as erro:
        checar(erro.status_code == 400, "telefone curto demais e recusado com 400")
    else:
        checar(False, "telefone curto demais e recusado com 400")

    checar(
        "ADD telefone varchar(13) NULL" in usuarios.ESQUEMA,
        "a coluna telefone e criada na inicializacao",
    )

    # ------------------------------------------------------------ corpo
    pedido = usuarios.EdicaoUsuario(
        nome="Mariana Alves",
        email="mariana@escritorio.adv.br",
        telefone="(61) 99999-0000",
        perfilId=4,
        ativo=True,
        senha="",
        redefinirSenha=True,
    )
    checar(pedido.perfil_id == 4, "aceita perfilId, o nome que a tela envia")
    checar(pedido.redefinir_senha is True, "aceita redefinirSenha, o nome que a tela envia")

    try:
        usuarios.EdicaoUsuario(nome="Mariana", email="sem-arroba", perfilId=4)
    except ValidationError:
        checar(True, "e-mail sem formato de e-mail e recusado")
    else:
        checar(False, "e-mail sem formato de e-mail e recusado")

    try:
        usuarios.EdicaoUsuario(
            nome="Mariana", email="m@x.com.br", perfilId=4, senha_md5="abc"
        )
    except ValidationError:
        checar(True, "campo desconhecido (ex.: senha_md5) e recusado, nao gravado")
    else:
        checar(False, "campo desconhecido (ex.: senha_md5) e recusado, nao gravado")

    try:
        usuarios.EdicaoUsuario(nome="Mariana", email="m@x.com.br")
    except ValidationError:
        checar(True, "perfil e obrigatorio na edicao")
    else:
        checar(False, "perfil e obrigatorio na edicao")

    return falhas


if __name__ == "__main__":
    raise SystemExit(main())
