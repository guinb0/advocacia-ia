"""Autenticação por JWT próprio, no padrão usado nos projetos da Level.

POR QUE SAIU O KEYCLOAK

O Keycloak resolvia identidade de um jeito grande demais para o tamanho deste
sistema: subir um servidor de identidade, manter um realm, um banco só dele e um
console separado — para um escritório com um punhado de contas. Cada ambiente
novo pedia realm importado à mão, e o `-SemAuth` existia justamente porque ligar
o Keycloak em máquina de desenvolvimento dava trabalho. Os demais projetos da
Level (SIDAF/DFLegal) já emitem o token aqui mesmo, e é esse desenho que este
módulo passa a seguir.

O QUE MUDA NA PRÁTICA

- **A chave é simétrica (HS256).** Antes o token vinha assinado com RS256 por
  outro processo e este backend baixava o JWKS para conferir. Agora quem assina e
  quem confere é o mesmo serviço, então uma chave só (`JWT_SECRET`) basta — e
  some a viagem de rede que o JWKS custava no primeiro acesso;
- **O token viaja em cookie `HttpOnly`.** É o padrão do DFLegal e é mais seguro
  que o `Authorization` que usávamos: JavaScript não lê cookie `HttpOnly`, então
  um XSS não consegue carregar a sessão embora. O header continua aceito como
  segunda porta — ver `token_da_requisicao`;
- **O perfil vem dentro do token.** Não há mais `realm_access.roles`: o claim é
  `perfil`, uma string, como no DFLegal. `Usuario.papeis` continua existindo
  porque a matriz de acesso (`app/perfis.py`) raciocina em lista, e quem tem um
  perfil só é o caso comum, não o único possível.

Sem `JWT_SECRET` configurado a autenticação fica DESLIGADA e todas as rotas
seguem abertas, para não quebrar quem roda o projeto sem Docker (e os testes).
O log grita quando isso acontece, porque é um modo inseguro por definição.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, Request, Response

log = logging.getLogger("auth")

#: A chave que assina e confere. Simétrica: não há segunda parte para publicar.
#:
#: Fica vazia por padrão de propósito. Um valor embutido aqui viraria o segredo
#: de produção de quem esquecesse de trocar — e o modo aberto, que é o que
#: acontece sem ela, pelo menos GRITA no log em vez de fingir estar protegido.
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
JWT_ALGORITMO = "HS256"
JWT_EMISSOR = os.getenv("JWT_ISSUER", "https://acervo.level33.com.br/").strip()
JWT_AUDIENCIA = os.getenv("JWT_AUDIENCE", JWT_EMISSOR).strip()

#: 24 horas, como no DFLegal. É o expediente inteiro mais folga: uma entrevista
#: de quarenta perguntas não pode esbarrar em token vencendo no meio, que foi
#: exatamente o problema que a renovação do Keycloak existia para remendar.
JWT_HORAS = float(os.getenv("JWT_HORAS", "24") or 24)

#: O nome do cookie é o mesmo do DFLegal — quem depura um dos dois sistemas
#: procura por `JwtToken` no navegador e acha.
COOKIE = os.getenv("JWT_COOKIE", "JwtToken").strip() or "JwtToken"

#: Domínio do cookie. Vazio = o host que respondeu, que é o certo em
#: desenvolvimento (`localhost`) e em qualquer implantação de host único.
#: Preencher só quando front e API moram em subdomínios irmãos, como no DFLegal
#: (`level33.com.br` cobrindo os dois).
COOKIE_DOMINIO = os.getenv("JWT_COOKIE_DOMAIN", "").strip()

#: `Secure` exige HTTPS, e em desenvolvimento não há. Ligado por padrão mesmo
#: assim: errar para o lado de exigir HTTPS é recuperável (o cookie não gruda e
#: alguém investiga); errar para o outro manda o token em claro sem ninguém ver.
#: O `.env` de desenvolvimento desliga.
COOKIE_SEGURO = os.getenv("JWT_COOKIE_SECURE", "1").strip() != "0"

#: `lax` é o que funciona com front e API no MESMO site — que é o nosso caso em
#: desenvolvimento (`localhost:3000` conversando com `localhost:8100`: porta não
#: separa "site", só o host separa). `none` só funciona junto de `Secure`, e é o
#: que o DFLegal usa por estar em domínios diferentes sob HTTPS.
COOKIE_SAMESITE = (os.getenv("JWT_COOKIE_SAMESITE", "lax").strip() or "lax").lower()

AUTH_DESATIVADA = os.getenv("AUTH_DESATIVADA", "0").strip() == "1"

ATIVA = bool(JWT_SECRET) and not AUTH_DESATIVADA

#: MD5 de "123456" — a senha que toda conta nova recebe quando ninguém informa
#: uma. O mesmo valor do DFLegal, de propósito: é ele que faz o claim
#: `senhaPadrao` significar a mesma coisa nos dois sistemas, e é o que a tela usa
#: para exigir a troca antes de deixar o usuário seguir.
SENHA_PADRAO_MD5 = "e10adc3949ba59abbe56e057f20f883e"


if not ATIVA:
    log.warning(
        "AUTENTICAÇÃO DESLIGADA: sem JWT_SECRET (ou com AUTH_DESATIVADA=1) toda "
        "rota fica aberta. Não suba assim em produção."
    )


def _agora() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ emissão


def gerar_token(
    *,
    codigo: str,
    nome: str,
    email: str,
    perfil: str,
    senha_padrao: bool = False,
    extras: dict[str, Any] | None = None,
) -> str:
    """Assina o token de sessão. Os claims são os mesmos do DFLegal.

    Nomes em inglês/camelCase aqui e não em português como no resto do projeto:
    são claims de um contrato que atravessa sistemas, e o `middleware.ts` do
    frontend e o backend .NET do SIDAF leem exatamente estes nomes. Renomear para
    `perfil_codigo` deixaria o token bonito e incompatível.
    """
    import jwt

    if not JWT_SECRET:
        raise HTTPException(
            503,
            "Login indisponível: falta JWT_SECRET no .env. Sem ele o servidor não "
            "tem como assinar a sessão.",
        )

    emitido = _agora()
    claims: dict[str, Any] = {
        "sub": str(codigo),
        "codigo": str(codigo),
        "nome": nome,
        "email": email,
        "perfil": perfil,
        "senhaPadrao": "true" if senha_padrao else "false",
        "loginTimeStamp": emitido.isoformat(timespec="seconds"),
        "iss": JWT_EMISSOR,
        "aud": JWT_AUDIENCIA,
        "iat": emitido,
        "exp": emitido + timedelta(hours=JWT_HORAS),
    }
    if extras:
        claims.update(extras)
    return str(jwt.encode(claims, JWT_SECRET, algorithm=JWT_ALGORITMO))


def definir_cookie(resposta: Response, token: str) -> None:
    """Gruda o token na resposta como cookie `HttpOnly`.

    `max_age` acompanha a validade do token em vez de ser um número próprio: um
    cookie que sobrevive ao token faz o navegador mandar credencial morta e a
    tela receber 401 sem entender por quê.
    """
    resposta.set_cookie(
        COOKIE,
        token,
        max_age=int(JWT_HORAS * 3600),
        httponly=True,
        secure=COOKIE_SEGURO,
        samesite=COOKIE_SAMESITE,  # type: ignore[arg-type]
        path="/",
        domain=COOKIE_DOMINIO or None,
    )


def limpar_cookie(resposta: Response) -> None:
    """Apaga o cookie de sessão.

    Os atributos precisam bater com os do `definir_cookie` — `path` e `domain`
    fazem parte da identidade do cookie, e apagar com atributos diferentes cria
    um segundo cookie vazio ao lado do que continua valendo.
    """
    resposta.delete_cookie(
        COOKIE,
        path="/",
        domain=COOKIE_DOMINIO or None,
        httponly=True,
        secure=COOKIE_SEGURO,
        samesite=COOKIE_SAMESITE,  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------ leitura


def token_da_requisicao(request: Request) -> str:
    """O token, venha ele do cookie ou do header. Vazio quando não veio nenhum.

    O cookie vem primeiro porque é o caminho do navegador, que é a maioria do
    tráfego. O `Authorization` continua aceito por dois motivos concretos: o
    `curl` de depuração e o `scripts/` que fala com a API sem sessão de
    navegador — nenhum dos dois tem cookie jar, e obrigá-los a ter só para
    conferir uma rota seria atrito sem ganho de segurança.
    """
    do_cookie = request.cookies.get(COOKIE, "")
    if do_cookie:
        return do_cookie

    cabecalho = request.headers.get("authorization", "")
    if cabecalho.lower().startswith("bearer "):
        return cabecalho[7:].strip()
    return ""


def validar_token(token: str) -> dict[str, Any]:
    """Verifica assinatura, emissor, audiência e validade. Devolve as claims."""
    import jwt

    try:
        return jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITMO],
            issuer=JWT_EMISSOR,
            audience=JWT_AUDIENCIA,
            options={"require": ["exp", "iat", "sub"]},
        )
    except Exception as exc:
        # A mensagem do PyJWT ("Signature has expired", "Invalid audience") vai
        # junto de propósito: sem ela, "Token inválido" manda o suporte adivinhar
        # entre chave trocada, relógio errado e sessão vencida.
        raise HTTPException(401, f"Token inválido: {exc}") from exc


class Usuario:
    """Quem está autenticado, do ponto de vista da aplicação."""

    def __init__(self, claims: dict[str, Any]):
        self.claims = claims
        self.id: str = str(claims.get("codigo") or claims.get("sub") or "")
        # O e-mail é o nome de usuário deste sistema (ver `app/usuarios.py`), e
        # não há mais `preferred_username` porque não há mais Keycloak.
        self.usuario: str = claims.get("email", "")
        self.nome: str = claims.get("nome") or self.usuario
        self.email: str = claims.get("email", "")
        self.senha_padrao: bool = str(claims.get("senhaPadrao", "")).lower() == "true"

        # `perfil` (string) é o formato do token; `perfis` (lista) fica aceito
        # para o dia em que alguém acumular dois. A matriz de acesso raciocina em
        # lista dos dois jeitos, então nada a jusante precisa saber a diferença.
        crus = claims.get("perfis") or claims.get("perfil") or []
        if isinstance(crus, str):
            crus = [crus] if crus else []
        self.papeis: set[str] = {str(p) for p in crus if p}

    def tem_papel(self, papel: str) -> bool:
        return papel in self.papeis

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "usuario": self.usuario,
            "nome": self.nome,
            "email": self.email,
            "papeis": sorted(self.papeis),
            "senhaPadrao": self.senha_padrao,
        }


USUARIO_ABERTO = Usuario(
    {"sub": "local", "codigo": "local", "email": "local", "nome": "Sessão sem autenticação"}
)


def usuario_atual(request: Request) -> Usuario:
    """Dependência das rotas protegidas."""
    if not ATIVA:
        return USUARIO_ABERTO

    token = token_da_requisicao(request)
    if not token:
        raise HTTPException(401, "Autenticação necessária.")

    return Usuario(validar_token(token))


# ------------------------------------------------------------- autorização


def exigir_papel(papel: str):
    """Dependência para rotas que pedem um papel específico."""

    def verificar(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
        if ATIVA and papel not in _papeis_atuais(usuario):
            raise HTTPException(403, f"Requer o papel '{papel}'.")
        return usuario

    return verificar


def exigir_qualquer_papel(*papeis: str):
    """Dependência para rotas que aceitam MAIS DE UM papel.

    Existe porque administrar conta tem dois donos legítimos: o advogado que
    cadastra o colega na hora e o secretário, cuja função é essa. Com só o
    `exigir_papel` seria preciso escolher um e deixar o outro de fora, ou repetir
    a checagem dentro de cada rota — que é onde ela é esquecida.
    """

    def verificar(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
        atuais = _papeis_atuais(usuario) if ATIVA else usuario.papeis
        if ATIVA and not any(p in atuais for p in papeis):
            raise HTTPException(403, f"Requer um destes papéis: {', '.join(papeis)}.")
        return usuario

    return verificar


def exigir_modulo(modulo: str):
    """Dependência para rotas guardadas por MÓDULO, e não por papel.

    A diferença importa. `exigir_papel("secretario")` amarra a rota a um nome de
    perfil: criar o perfil "analista" — que precisa ver as entrevistas da equipe
    sem conduzir nenhuma — exigiria caçar cada rota e acrescentar o nome novo na
    lista. Era assim que a lista de perfis acabava fechada.

    Aqui a rota declara o módulo a que pertence e para de opinar sobre quem
    entra. Quem decide é a matriz perfil × módulo (`app/perfis.py`), que o
    escritório edita na tela — perfil novo nasce sabendo o que alcança, sem tocar
    em código.

    Com a autenticação desligada isto libera, como todo o resto: não há perfil no
    token para consultar, e travar tudo deixaria o modo de depuração inútil.
    """

    def verificar(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
        if not ATIVA:
            return usuario
        from . import perfis

        if not perfis.pode(list(_papeis_atuais(usuario)), modulo):
            rotulo = next(
                (m["rotulo"] for m in perfis.MODULOS if m["codigo"] == modulo), modulo
            )
            raise HTTPException(403, f"Seu perfil não tem acesso a {rotulo}.")
        return usuario

    return verificar


def _papeis_atuais(usuario: Usuario) -> tuple[str, ...]:
    """Le o perfil atual no banco; o token prova identidade, nao permissao."""
    from . import usuarios

    return usuarios.papeis_ativos_de_email(usuario.email)


def configuracao_publica() -> dict[str, Any]:
    """O que o frontend precisa saber sobre a sessão — nada secreto aqui.

    Ficou bem menor que na época do Keycloak: não há mais URL de servidor de
    identidade, realm nem client_id para o navegador descobrir. Sobrou o que a
    tela realmente decide com base nisto — mostrar ou não o login.
    """
    return {
        "ativa": ATIVA,
        "cookie": COOKIE,
        "expira_em_horas": JWT_HORAS,
    }
