"""Captcha e segundo fator na porta de entrada.

    .venv\\Scripts\\python.exe -m tests.test_login_dois_fatores

O banco é substituído por um dicionário que entende as SEIS consultas que
`app/dois_fatores.py` emite. Não é um SQL Server de mentira e não tenta ser: o
que está sob teste é a regra (o código morre por prazo, por tentativa e por
reenvio; o hash não é reversível; a sessão só nasce no segundo passo), e ligar
isso a um banco real trocaria um teste que roda em qualquer máquina por um que
depende de VPN.
"""

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.modules.setdefault("pyodbc", types.SimpleNamespace())

from contextlib import contextmanager  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from app import auth, captcha, correio, dois_fatores, usuarios  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str, detalhe: str = "") -> None:
    global falhas
    if condicao:
        print(f"  PASS  {descricao}")
    else:
        falhas += 1
        print(f"  FALHA {descricao}" + (f"\n          {detalhe}" if detalhe else ""))


def esperar_http(codigo: int, descricao: str, funcao, *args, **kwargs) -> None:
    """Roda `funcao` esperando um HTTPException com este status."""
    try:
        funcao(*args, **kwargs)
    except HTTPException as erro:
        checar(erro.status_code == codigo, descricao, f"veio {erro.status_code}: {erro.detail}")
    except Exception as erro:  # noqa: BLE001
        checar(False, descricao, f"exceção inesperada: {erro!r}")
    else:
        checar(False, descricao, "não levantou nada")


# --------------------------------------------------------------- banco falso


class BancoFalso:
    """As linhas da tabela de desafios, em memória."""

    def __init__(self) -> None:
        self.linhas: dict[str, dict] = {}

    def execute(self, sql: str, params=()):
        texto = " ".join(sql.split())

        if texto.startswith("IF ") or texto.startswith("CREATE "):
            return self  # DDL: o dicionário já existe

        if "INSERT INTO" in texto:
            (id_, email, hash_, criado, enviado, expira) = params
            self.linhas[id_] = {
                "id": id_,
                "email": email,
                "codigo_hash": hash_,
                "criado_em": criado,
                "enviado_em": enviado,
                "expira_em": expira,
                "tentativas": 0,
                "envios": 1,
                "consumido": 0,
            }
            return self

        if "DELETE" in texto and "WHERE id = ?" in texto:
            self.linhas.pop(params[0], None)
            return self

        if "DELETE" in texto and "WHERE email = ?" in texto:
            for chave in [k for k, v in self.linhas.items() if v["email"] == params[0]]:
                del self.linhas[chave]
            return self

        if "DELETE" in texto and "expira_em <" in texto:
            corte = params[0]
            for chave in [
                k
                for k, v in self.linhas.items()
                if v["expira_em"] < corte or v["consumido"] == 1
            ]:
                del self.linhas[chave]
            return self

        if "SET tentativas = tentativas + 1" in texto:
            self.linhas[params[0]]["tentativas"] += 1
            return self

        if "SET codigo_hash" in texto:
            hash_, enviado, expira, id_ = params
            linha = self.linhas[id_]
            linha.update(codigo_hash=hash_, enviado_em=enviado, expira_em=expira)
            linha["envios"] += 1
            return self

        if texto.startswith("SELECT"):
            self._encontrada = next(
                (
                    dict(v)
                    for v in self.linhas.values()
                    if v["id"] == params[0] and v["consumido"] == 0
                ),
                None,
            )
            return self

        raise AssertionError(f"consulta não prevista no banco falso: {texto}")

    def fetchone(self):
        return getattr(self, "_encontrada", None)


BANCO = BancoFalso()
ENVIADOS: list[dict] = []


@contextmanager
def conectar_falso():
    yield BANCO


def enviar_falso(*, para, assunto, texto, html=""):
    """Guarda a mensagem e extrai o código do corpo em texto."""
    codigo = "".join(c for c in texto.split("é: ")[1][:6] if c.isdigit())
    ENVIADOS.append({"para": para, "assunto": assunto, "codigo": codigo})


# ------------------------------------------------------------------ cenários


def cenario_mascara() -> None:
    print("\n[máscara do e-mail]")
    checar(
        dois_fatores.mascarar("fulano@escritorio.com") == "fu****@escritorio.com",
        "mostra só os dois primeiros caracteres",
        dois_fatores.mascarar("fulano@escritorio.com"),
    )
    checar(
        "@" in dois_fatores.mascarar("ana@x.com") and "ana" not in dois_fatores.mascarar("ana@x.com"),
        "e-mail curto também é mascarado",
        dois_fatores.mascarar("ana@x.com"),
    )
    checar(dois_fatores.mascarar("") == "seu e-mail", "valor vazio não vira máscara quebrada")


def cenario_ciclo_feliz() -> None:
    print("\n[código correto abre a sessão]")
    BANCO.linhas.clear()
    ENVIADOS.clear()

    aberto = dois_fatores.abrir_desafio(email="ana@escritorio.com", nome="Ana Souza")
    checar(len(ENVIADOS) == 1, "um e-mail saiu")
    checar(aberto["email"] == dois_fatores.mascarar("ana@escritorio.com"), "devolve o e-mail mascarado")
    checar("codigo" not in aberto, "o código NÃO volta na resposta da API")

    guardado = next(iter(BANCO.linhas.values()))
    codigo = ENVIADOS[0]["codigo"]
    checar(len(codigo) == 6 and codigo.isdigit(), "código de 6 dígitos", codigo)
    checar(codigo not in guardado["codigo_hash"], "o banco guarda o hash, não o código")
    checar(len(guardado["codigo_hash"]) == 64, "hash SHA-256 completo")

    email = dois_fatores.conferir(aberto["desafio"], codigo)
    checar(email == "ana@escritorio.com", "confere e devolve a conta")
    checar(not BANCO.linhas, "o desafio é consumido no primeiro uso")

    esperar_http(
        400,
        "o mesmo código não entra duas vezes",
        dois_fatores.conferir,
        aberto["desafio"],
        codigo,
    )


def cenario_codigo_errado() -> None:
    print("\n[código errado]")
    BANCO.linhas.clear()
    ENVIADOS.clear()
    aberto = dois_fatores.abrir_desafio(email="ana@escritorio.com", nome="Ana")
    certo = ENVIADOS[0]["codigo"]
    errado = "000000" if certo != "000000" else "111111"

    esperar_http(401, "código errado é recusado", dois_fatores.conferir, aberto["desafio"], errado)
    checar(
        next(iter(BANCO.linhas.values()))["tentativas"] == 1,
        "a tentativa errada é contada",
    )

    for _ in range(dois_fatores.TENTATIVAS_MAXIMAS - 1):
        try:
            dois_fatores.conferir(aberto["desafio"], errado)
        except HTTPException:
            pass

    esperar_http(
        429,
        "estoura o limite de tentativas e o desafio morre",
        dois_fatores.conferir,
        aberto["desafio"],
        certo,
    )
    checar(not BANCO.linhas, "o desafio queimado é apagado")


def cenario_expiracao() -> None:
    print("\n[expiração]")
    BANCO.linhas.clear()
    ENVIADOS.clear()
    aberto = dois_fatores.abrir_desafio(email="ana@escritorio.com", nome="Ana")
    codigo = ENVIADOS[0]["codigo"]

    vencido = datetime.now(timezone.utc) - timedelta(seconds=1)
    next(iter(BANCO.linhas.values()))["expira_em"] = vencido.isoformat(timespec="seconds")

    esperar_http(
        400, "código vencido é recusado", dois_fatores.conferir, aberto["desafio"], codigo
    )
    checar(not BANCO.linhas, "a linha vencida é varrida")


def cenario_reenvio() -> None:
    print("\n[reenvio]")
    BANCO.linhas.clear()
    ENVIADOS.clear()
    original = usuarios.por_email
    usuarios.por_email = lambda email: {"nome": "Ana", "email": email, "ativo": True}
    try:
        aberto = dois_fatores.abrir_desafio(email="ana@escritorio.com", nome="Ana")
        primeiro = ENVIADOS[0]["codigo"]

        esperar_http(
            429, "reenvio antes da espera é recusado", dois_fatores.reenviar, aberto["desafio"]
        )

        # Finge que o último envio foi há tempo suficiente.
        linha = next(iter(BANCO.linhas.values()))
        atras = datetime.now(timezone.utc) - timedelta(seconds=dois_fatores.ESPERA_REENVIO_S + 1)
        linha["enviado_em"] = atras.isoformat(timespec="seconds")

        dois_fatores.reenviar(aberto["desafio"])
        segundo = ENVIADOS[-1]["codigo"]
        checar(len(ENVIADOS) == 2, "o reenvio manda outro e-mail")
        checar(
            next(iter(BANCO.linhas.values()))["envios"] == 2, "o contador de envios sobe"
        )

        if primeiro != segundo:
            esperar_http(
                401,
                "o código antigo deixa de valer depois do reenvio",
                dois_fatores.conferir,
                aberto["desafio"],
                primeiro,
            )
        checar(
            dois_fatores.conferir(aberto["desafio"], segundo) == "ana@escritorio.com",
            "o código novo vale",
        )
    finally:
        usuarios.por_email = original


def cenario_rotas() -> None:
    print("\n[as duas etapas do login]")
    BANCO.linhas.clear()
    ENVIADOS.clear()

    interno = {
        "codigo": "7",
        "nome": "Ana Souza",
        "email": "ana@escritorio.com",
        "senha_md5": usuarios._md5("segredo123"),
        "perfil": "advogado",
        "perfil_id": 1,
        "perfil_ativo": True,
        "ativo": True,
    }
    cliente = {**interno, "codigo": "9", "email": "cli@ex.com", "perfil": "cliente"}
    contas = {interno["email"]: interno, cliente["email"]: cliente}

    class RespostaFalsa:
        def __init__(self) -> None:
            self.cookies: list[str] = []

        def set_cookie(self, nome, *_a, **_k):
            self.cookies.append(nome)

    class PedidoFalso:
        headers: dict = {}
        client = None

    originais = (usuarios._por_email, usuarios._sessao_da_pessoa, auth.gerar_token)
    usuarios._por_email = lambda email: contas.get(email.lower())
    usuarios._sessao_da_pessoa = lambda p: {"codigo": p["codigo"], "nome": p["nome"]}
    auth.gerar_token = lambda **_: "token-de-teste"
    try:
        # --- perfil interno: para no segundo fator, SEM cookie
        resposta = RespostaFalsa()
        corpo = usuarios.autenticar(
            usuarios.PedidoLogin(email="ana@escritorio.com", senha="segredo123"),
            PedidoFalso(),
            resposta,
        )
        checar(corpo["data"]["etapa"] == "dois_fatores", "perfil interno cai no segundo fator")
        checar(not resposta.cookies, "NENHUM cookie é gravado só com a senha")
        checar(len(ENVIADOS) == 1, "o código foi enviado")

        desafio = corpo["data"]["desafio"]
        codigo = ENVIADOS[0]["codigo"]

        # --- código errado não abre sessão
        resposta_errada = RespostaFalsa()
        esperar_http(
            401,
            "código errado não abre sessão",
            usuarios.confirmar_codigo,
            usuarios.PedidoCodigo(desafio=desafio, codigo="000000" if codigo != "000000" else "111111"),
            resposta_errada,
        )
        checar(not resposta_errada.cookies, "e não grava cookie")

        # --- código certo abre
        resposta2 = RespostaFalsa()
        final = usuarios.confirmar_codigo(
            usuarios.PedidoCodigo(desafio=desafio, codigo=codigo), resposta2
        )
        checar(final["data"]["etapa"] == "sessao", "o código certo abre a sessão")
        checar(resposta2.cookies == [auth.COOKIE], "o cookie nasce no SEGUNDO passo")

        # --- cliente é isento e entra direto
        BANCO.linhas.clear()
        ENVIADOS.clear()
        resposta3 = RespostaFalsa()
        corpo_cliente = usuarios.autenticar(
            usuarios.PedidoLogin(email="cli@ex.com", senha="segredo123"),
            PedidoFalso(),
            resposta3,
        )
        checar(corpo_cliente["data"]["etapa"] == "sessao", "cliente entra sem segundo fator")
        checar(not ENVIADOS, "e nenhum e-mail é mandado para ele")

        # --- senha errada não chega a mandar e-mail
        ENVIADOS.clear()
        esperar_http(
            401,
            "senha errada é recusada",
            usuarios.autenticar,
            usuarios.PedidoLogin(email="ana@escritorio.com", senha="outra"),
            PedidoFalso(),
            RespostaFalsa(),
        )
        checar(not ENVIADOS, "senha errada NÃO dispara e-mail (a rota não vira spammer)")
    finally:
        usuarios._por_email, usuarios._sessao_da_pessoa, auth.gerar_token = originais


def cenario_captcha() -> None:
    print("\n[captcha]")
    original = captcha.ATIVO
    try:
        captcha.ATIVO = False
        captcha.verificar("", "1.2.3.4")
        checar(True, "desligado, passa direto (desenvolvimento sem conta na Cloudflare)")

        captcha.ATIVO = True
        esperar_http(400, "ligado, token vazio é recusado", captcha.verificar, "", "1.2.3.4")
    finally:
        captcha.ATIVO = original


def main() -> int:
    # O segundo fator só é exigido com a autenticação ligada; o teste roda com o
    # `.env` de qualquer máquina, então os interruptores são forçados aqui.
    auth.ATIVA = True
    dois_fatores.ATIVO = True
    # O captcha tambem: com TURNSTILE_SECRET_KEY preenchida no .env da maquina,
    # `autenticar` passaria a exigir um token da Cloudflare que nenhum teste tem
    # como produzir — e a suite passaria ou falharia conforme o .env de quem a
    # roda. `cenario_captcha` liga e desliga por conta propria.
    captcha.ATIVO = False
    dois_fatores.conectar = conectar_falso
    correio.ATIVO = True
    correio.enviar = enviar_falso

    cenario_mascara()
    cenario_ciclo_feliz()
    cenario_codigo_errado()
    cenario_expiracao()
    cenario_reenvio()
    cenario_rotas()
    cenario_captcha()

    print()
    if falhas:
        print(f"{falhas} FALHA(S)")
        return 1
    print("Tudo certo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
