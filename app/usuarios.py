"""Contas do escritório: cadastro, login e sessão.

POR QUE AGORA É UMA TABELA DAQUI, E NÃO O KEYCLOAK

O cabeçalho antigo defendia o contrário — "a identidade já mora lá" — e o
argumento era bom enquanto o Keycloak fosse mesmo a fonte da verdade. Ele saiu
(ver `app/auth.py`), e com ele saiu a segunda verdade: quem emite o token e quem
guarda a conta passam a ser o mesmo serviço, então não há duas listas de gente
para divergir. É também o desenho dos outros projetos da Level, onde a conta vive
na tabela do próprio sistema e o backend assina o JWT.

O que se perde é honesto de registrar: não há mais console de administração, nem
federação com outro provedor, nem fluxo de "esqueci a senha" por e-mail. Nada
disso estava em uso.

POR QUE TÃO POUCOS CAMPOS

Conta se cria no meio do atendimento, com o cliente esperando. Nome, e-mail,
perfil e senha bastam para entrar; o resto (CPF, endereço, telefone) o cadastro
do CASO já coleta, e pedir duas vezes é a forma mais rápida de ninguém preencher
nenhuma das duas.

O e-mail é o nome de usuário. Ter os dois separados obrigaria a inventar um
apelido na hora, que é justamente a decisão que trava quem está cadastrando.

SOBRE O MD5 DA SENHA

É o formato do DFLegal, adotado aqui para as duas bases falarem a mesma língua:
o frontend manda `Md5.hashStr(senha)` e o servidor compara. Fique registrado o
que isso custa — MD5 sem sal é quebrável por tabela pronta, então um vazamento da
tabela `acervo_usuarios` entrega as senhas junto. A senha nunca trafega em claro
(o navegador já manda o hash), mas isso protege o trânsito, não o banco. Trocar
por bcrypt depois é uma coluna nova e uma rotina de re-hash no login.

OS PERFIS

`advogado` conduz entrevista, gera documento e cadastra gente. `secretario`
gerencia as contas e acompanha as entrevistas de toda a equipe (ver
`app/supervisao.py`). `cliente` só acompanha o próprio caso e envia documento.

Cadastrar exige `advogado` ou `secretario` — nunca `cliente`, que criaria acesso
ao acervo do escritório.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from . import auth
from . import perfis as perfis_lib
from .auth import exigir_qualquer_papel
from .banco import PREFIXO, SCHEMA, conectar

log = logging.getLogger("usuarios")

roteador = APIRouter(prefix="/api/usuarios", tags=["usuarios"])

#: A sessão fica num router próprio, com o mesmo endereço do DFLegal
#: (`/api/user/authenticate`). Endereço igual é o que permite copiar o
#: `auth.service.ts` de um projeto para o outro sem reescrever nada — e separar
#: de `/api/usuarios` mantém "entrar no sistema" longe de "administrar contas",
#: que são coisas de públicos diferentes.
roteador_sessao = APIRouter(prefix="/api/user", tags=["sessao"])

#: Os perfis que o escritório JÁ USAVA quando eles eram cravados aqui.
#:
#: Deixaram de ser a fonte da verdade: quem responde "que perfis existem" agora é
#: `app/perfis.py`, contra a tabela. Isto fica como semente de leitura para o
#: código antigo que ainda importa `PERFIS`/`CODIGOS`, e some quando o último
#: deles sair.
PERFIS: tuple[dict[str, str], ...] = (
    {
        "codigo": "advogado",
        "rotulo": "Advogado",
        "descricao": "Conduz entrevistas, gera documentos e cadastra usuários.",
    },
    {
        "codigo": "secretario",
        "rotulo": "Secretário",
        "descricao": "Gerencia os usuários e acompanha as entrevistas de toda a equipe.",
    },
    {
        "codigo": "cliente",
        "rotulo": "Cliente",
        "descricao": "Acompanha o próprio caso e envia documentos.",
    },
    {
        "codigo": "documentacao",
        "rotulo": "Documentação",
        "descricao": "Assume chamadas e coleta dados e documentos do cliente.",
    },
)
CODIGOS = tuple(p["codigo"] for p in PERFIS)

#: Quem administra contas. São dois porque o escritório tem dois caminhos reais:
#: o advogado que cadastra o colega na hora, e o secretário, cuja função É essa.
#: Cliente nunca — um cliente que criasse contas criaria acesso ao acervo.
PODEM_GERIR = ("advogado", "secretario")

PodeGerir = Depends(exigir_qualquer_papel(*PODEM_GERIR))

_TABELA = f"{SCHEMA}.{PREFIXO}usuarios"

ESQUEMA = f"""
IF OBJECT_ID('{_TABELA}') IS NULL
CREATE TABLE {_TABELA} (
    codigo     int           IDENTITY(1,1) NOT NULL CONSTRAINT pk_acervo_usuarios PRIMARY KEY,
    nome       nvarchar(120) NOT NULL,
    email      nvarchar(160) NOT NULL CONSTRAINT uq_acervo_usuarios_email UNIQUE,
    senha_md5  char(32)      NOT NULL,
    perfil     varchar(60)   NOT NULL,
    ativo      bit           NOT NULL CONSTRAINT df_acervo_usuarios_ativo DEFAULT 1,
    criado_em  varchar(40)   NOT NULL
);
"""


def _md5(texto: str) -> str:
    return hashlib.md5(texto.encode("utf-8")).hexdigest()


def _parece_md5(valor: str) -> bool:
    """32 caracteres hexadecimais.

    Serve para o servidor aceitar tanto o hash que o navegador manda quanto uma
    senha digitada em `curl` durante depuração, sem gravar senha em claro por
    engano no banco. Uma senha que POR ACASO tenha 32 dígitos hexadecimais seria
    tratada como hash — é um caso que não acontece com senha escolhida por gente,
    e o preço de errar é a pessoa não conseguir entrar, não uma brecha.
    """
    valor = valor.strip()
    return len(valor) == 32 and all(c in "0123456789abcdefABCDEF" for c in valor)


def _hash_de(senha: str) -> str:
    return senha.strip().lower() if _parece_md5(senha) else _md5(senha)


def _decodificar(valor: str) -> str:
    """Desfaz o base64 que o frontend aplica no identificador do login.

    O DFLegal manda `btoa(cpf)`; aqui é o e-mail. Não é segurança — base64 não
    esconde nada de quem olha a requisição — é o formato do contrato, e recusar
    silenciosamente o que não for base64 quebraria quem chama a rota de `curl`.
    Por isso o valor que não decodifica volta como veio.
    """
    bruto = valor.strip()
    if not bruto:
        return ""
    try:
        decodificado = base64.b64decode(bruto, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return bruto
    # Base64 válido que não vira e-mail é, quase sempre, um e-mail que por acaso
    # passou pelo decodificador (`teste@x.com` não passa, mas cadeias curtas
    # passam). Ficar com o texto que TEM cara de e-mail evita esse tropeço.
    return decodificado if "@" in decodificado else bruto


def _env(nome: str, padrao: str = "") -> str:
    return (os.getenv(nome, padrao) or "").strip()


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def inicializar() -> None:
    """Cria a tabela e garante a primeira conta. Idempotente.

    A conta semente existe porque um sistema com autenticação ligada e tabela
    vazia não tem por onde entrar: não há console de administração para socorrer,
    e a única saída seria escrever no banco à mão. Ela nasce com o perfil
    `advogado`, que é quem cadastra os demais.
    """
    with conectar() as con:
        for lote in ESQUEMA.split(";\n"):
            if lote.strip():
                con.execute(lote)

        email = (_env("ACERVO_ADMIN_EMAIL") or "admin@acervo.local").lower()
        ja_tem = con.execute(f"SELECT TOP 1 codigo FROM {_TABELA}").fetchone()
        if ja_tem:
            return

        senha = _env("ACERVO_ADMIN_SENHA")
        # Sem senha no `.env`, a conta nasce com a senha padrão e o token sai com
        # `senhaPadrao: true` — a tela obriga a trocar antes de seguir. É melhor
        # que gerar uma senha aleatória que ninguém vê passar no log.
        hash_senha = _hash_de(senha) if senha else auth.SENHA_PADRAO_MD5
        con.execute(
            f"INSERT INTO {_TABELA} (nome, email, senha_md5, perfil, ativo, criado_em)"
            " VALUES (?, ?, ?, 'advogado', 1, ?)",
            ("Administrador", email, hash_senha, _agora()),
        )
        log.warning(
            "Nenhum usuário cadastrado: criada a conta inicial %s%s",
            email,
            "" if senha else " com a SENHA PADRÃO (123456) — troque no primeiro acesso",
        )


def _por_email(email: str) -> dict[str, Any] | None:
    with conectar() as con:
        linha = con.execute(
            f"SELECT codigo, nome, email, senha_md5, perfil, ativo FROM {_TABELA}"
            " WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()
    if linha is None:
        return None
    return {
        "codigo": str(linha["codigo"]),
        "nome": linha["nome"],
        "email": linha["email"],
        "senha_md5": (linha["senha_md5"] or "").strip().lower(),
        "perfil": linha["perfil"],
        "ativo": bool(linha["ativo"]),
    }


# ------------------------------------------------------------------- sessão


class PedidoLogin(BaseModel):
    """O corpo do login, no formato do DFLegal.

    `TipoLogin` existe lá para escolher entre CPF e matrícula. Aqui só há e-mail,
    e o campo fica com valor único em vez de sumir: é o que permite o dia em que
    o escritório quiser entrar por OAB sem mudar o contrato outra vez.
    """

    model_config = ConfigDict(extra="ignore")

    email: str = ""
    senha: str
    TipoLogin: str = "email"


@roteador_sessao.post("/authenticate")
def autenticar(pedido: PedidoLogin, resposta: Response) -> dict[str, Any]:
    """Confere a credencial, assina o token e o grava no cookie `HttpOnly`.

    A resposta vem no envelope `{flag, message, data}` do DFLegal, e o `data`
    repete os dados de sessão que o token já carrega. Não é redundância à toa: o
    cookie é `HttpOnly`, então o JavaScript NÃO consegue ler o token para
    descobrir quem entrou — sem este corpo a tela não teria como saber o nome de
    quem acabou de logar.

    O token NÃO vai no corpo. Devolvê-lo ali desfaria toda a proteção do
    `HttpOnly`: bastaria um XSS ler a resposta do login.
    """
    email = _decodificar(pedido.email).strip().lower()
    if not email or not pedido.senha:
        raise HTTPException(400, "Informe e-mail e senha.")

    pessoa = _por_email(email)
    informado = _hash_de(pedido.senha)

    # Uma resposta só para "não existe" e para "senha errada", de propósito:
    # respostas diferentes contam a quem tenta quais e-mails têm conta aqui.
    if pessoa is None or pessoa["senha_md5"] != informado:
        log.warning("login recusado para %s", email)
        raise HTTPException(401, "E-mail ou senha incorretos.")
    if not pessoa["ativo"]:
        raise HTTPException(403, "Esta conta está desativada. Procure quem administra.")

    senha_padrao = pessoa["senha_md5"] == auth.SENHA_PADRAO_MD5
    token = auth.gerar_token(
        codigo=pessoa["codigo"],
        nome=pessoa["nome"],
        email=pessoa["email"],
        perfil=pessoa["perfil"],
        senha_padrao=senha_padrao,
    )
    auth.definir_cookie(resposta, token)
    log.info("login: %s (%s)", email, pessoa["perfil"])

    return {
        "flag": True,
        "message": "Autenticado.",
        "data": {
            "codigo": pessoa["codigo"],
            "nome": pessoa["nome"],
            "email": pessoa["email"],
            "perfil": pessoa["perfil"],
            "senhaPadrao": senha_padrao,
            # Os módulos que este perfil alcança vão junto para a tela montar o
            # menu sem uma segunda ida ao servidor — e para o menu não oferecer
            # botão que a rota vai recusar depois.
            "modulos": sorted(perfis_lib.modulos_de([pessoa["perfil"]])),
        },
    }


@roteador_sessao.post("/logout")
def sair(resposta: Response) -> dict[str, Any]:
    """Apaga o cookie. Sem token para revogar: ele morre no `exp`.

    Não há lista de tokens revogados, e é uma escolha, não um esquecimento —
    manter uma exigiria consultar o banco a cada requisição, que é justamente o
    custo que o JWT existe para evitar. O risco que sobra é um token roubado
    valer até o vencimento; o que o encurta é `JWT_HORAS`, não esta rota.
    """
    auth.limpar_cookie(resposta)
    return {"flag": True, "message": "disconnect"}


@roteador_sessao.get("/my-account")
def minha_conta(request: Request) -> dict[str, Any]:
    """Quem está logado, lido do BANCO e não do token.

    A diferença aparece quando alguém tem o perfil trocado no meio do expediente:
    o token na mão daquela pessoa continua dizendo o perfil antigo por até 24h.
    Esta rota é o caminho da tela para se atualizar sem obrigar a sair e entrar.
    """
    usuario = auth.usuario_atual(request)
    if not auth.ATIVA:
        return {"flag": True, "data": usuario.to_dict()}

    pessoa = _por_email(usuario.email)
    if pessoa is None:
        # A conta sumiu depois do token emitido. Não é 404: do ponto de vista de
        # quem chama, a sessão é que deixou de valer.
        raise HTTPException(401, "Sua conta não existe mais. Entre novamente.")
    return {
        "flag": True,
        "data": {
            "codigo": pessoa["codigo"],
            "nome": pessoa["nome"],
            "email": pessoa["email"],
            "perfil": pessoa["perfil"],
            "ativo": pessoa["ativo"],
            "senhaPadrao": pessoa["senha_md5"] == auth.SENHA_PADRAO_MD5,
            "modulos": sorted(perfis_lib.modulos_de([pessoa["perfil"]])),
        },
    }


class PedidoTrocaSenha(BaseModel):
    model_config = ConfigDict(extra="ignore")

    #: O hash MD5 vindo da tela, ou a senha em claro de um `curl`. `_hash_de`
    #: resolve os dois; o mínimo de 6 cobre a senha em claro sem barrar o hash.
    senha: Annotated[str, Field(min_length=6, max_length=128)]


@roteador_sessao.put("/change-password")
def trocar_senha(pedido: PedidoTrocaSenha, request: Request, resposta: Response) -> dict[str, Any]:
    """Troca a própria senha. Só a própria — não há `codigo` no corpo de propósito.

    O DFLegal aceita o `codigo` de quem terá a senha trocada, e isso deixa a rota
    valer como redefinição de senha alheia se alguém esquecer de conferir quem
    chamou. Aqui a conta alvo sai do token, e mais nada.

    O token é reemitido porque o claim `senhaPadrao` acabou de mudar: sem isso a
    tela continuaria exigindo a troca que a pessoa acabou de fazer.
    """
    usuario = auth.usuario_atual(request)
    if not auth.ATIVA:
        raise HTTPException(400, "A autenticação está desligada; não há senha a trocar.")

    novo = _hash_de(pedido.senha)
    if novo == auth.SENHA_PADRAO_MD5:
        raise HTTPException(400, "Escolha uma senha diferente da padrão.")

    with conectar() as con:
        alteradas = con.execute(
            f"UPDATE {_TABELA} SET senha_md5 = ? WHERE email = ?",
            (novo, usuario.email.lower()),
        ).rowcount
    if not alteradas:
        raise HTTPException(401, "Sua conta não existe mais. Entre novamente.")

    pessoa = _por_email(usuario.email)
    assert pessoa is not None  # acabou de ser atualizada
    auth.definir_cookie(
        resposta,
        auth.gerar_token(
            codigo=pessoa["codigo"],
            nome=pessoa["nome"],
            email=pessoa["email"],
            perfil=pessoa["perfil"],
            senha_padrao=False,
        ),
    )
    log.info("senha trocada: %s", usuario.email)
    return {"flag": True, "message": "Senha alterada."}


# ------------------------------------------------------------------ perfis


class PedidoPerfil(BaseModel):
    """Um perfil e os módulos que ele alcança."""

    model_config = ConfigDict(extra="forbid")

    codigo: Annotated[str, Field(min_length=2, max_length=60, pattern=r"^[a-z][a-z0-9_]*$")]
    """Minúsculas, sem espaço: o código vai no claim `perfil` do token e é
    comparado como texto exato — acento e espaço só criam jeito de errar."""

    rotulo: Annotated[str, Field(min_length=2, max_length=120)]
    descricao: Annotated[str, Field(max_length=400)] = ""
    modulos: list[str] = Field(default_factory=list)


@roteador.get("/modulos", dependencies=[PodeGerir])
def catalogo_de_modulos() -> dict[str, Any]:
    """Os módulos que um perfil pode alcançar, para a tela montar a matriz.

    Vem do servidor e não do frontend de propósito: são os mesmos códigos que as
    rotas usam em `auth.exigir_modulo`. Uma lista digitada na tela divergiria em
    silêncio, e a caixa marcada não corresponderia a acesso nenhum.
    """
    return {"modulos": list(perfis_lib.MODULOS)}


@roteador.get("/perfis/matriz", dependencies=[PodeGerir])
def matriz_de_perfis() -> dict[str, Any]:
    """Os perfis COM os módulos de cada um, para a tela de gerenciamento.

    Separada de `GET /perfis` porque as duas respondem a perguntas diferentes,
    para públicos diferentes. Aquela é vocabulário — "que perfis existem?" — e
    responde sem token porque alimenta o seletor do cadastro. Esta diz o que cada
    perfil ALCANÇA, que é desenho de acesso do escritório e só interessa a quem
    administra. Juntar as duas obrigaria a proteger o vocabulário ou a expor a
    matriz; nenhuma das duas serve.
    """
    return {"perfis": perfis_lib.listar(), "modulos": list(perfis_lib.MODULOS)}


@roteador.put("/perfis/{codigo}", dependencies=[PodeGerir])
def salvar_perfil(codigo: str, pedido: PedidoPerfil) -> dict[str, Any]:
    """Cria ou atualiza um perfil e a matriz de módulos dele.

    O corpo traz o estado COMPLETO das caixas: a matriz é substituída inteira, em
    vez de comparada item a item — comparar só criaria caminho para a tela e o
    banco discordarem sobre o que está marcado.
    """
    if codigo != pedido.codigo:
        raise HTTPException(400, "O código do endereço e o do corpo precisam ser iguais.")
    try:
        return perfis_lib.salvar(
            pedido.codigo, pedido.rotulo, pedido.descricao, pedido.modulos
        )
    except ValueError as erro:
        raise HTTPException(400, str(erro)) from erro


@roteador.delete("/perfis/{codigo}", dependencies=[PodeGerir])
def remover_perfil(codigo: str) -> dict[str, str]:
    """Apaga um perfil. Os de sistema recusam — ver `perfis.SEMENTE`.

    Recusa também enquanto houver gente usando: apagar o perfil de alguém deixaria
    a conta sem nada que a matriz reconheça, e o sintoma seria uma pessoa que
    entra e não enxerga tela nenhuma, sem mensagem que explique.
    """
    with conectar() as con:
        em_uso = con.execute(
            f"SELECT COUNT(*) AS n FROM {_TABELA} WHERE perfil = ?", (codigo,)
        ).fetchone()
    if em_uso and int(em_uso["n"]):
        raise HTTPException(
            400,
            f"{em_uso['n']} usuário(s) ainda usam este perfil. Mova essas contas antes.",
        )
    try:
        perfis_lib.remover(codigo)
    except ValueError as erro:
        raise HTTPException(400, str(erro)) from erro
    return {"codigo": codigo, "situacao": "removido"}


@roteador.get("/perfis")
def listar_perfis() -> dict[str, Any]:
    """Os perfis que a tela oferece. Sem token: é vocabulário, não dado de ninguém.

    Lê do banco em vez de uma lista cravada: é o que faz um perfil criado na tela
    aparecer no seletor do cadastro sem alguém editar código. Os módulos de cada
    perfil NÃO vêm aqui — quem pergunta isto está montando um seletor, e o
    desenho de acesso do escritório não precisa sair sem token para isso.

    Se o banco não responder, devolve a semente. Um seletor vazio impediria
    cadastrar qualquer pessoa, e os três perfis de sistema são justamente os que
    sempre existem.
    """
    try:
        cadastrados = perfis_lib.listar()
    except Exception:
        log.exception("Perfis não puderam ser lidos; usando a semente")
        return {"perfis": list(PERFIS)}
    return {
        "perfis": [
            {"codigo": p["codigo"], "rotulo": p["rotulo"], "descricao": p["descricao"]}
            for p in cadastrados
        ]
        or list(PERFIS)
    }


# ---------------------------------------------------------------- cadastro


class NovoUsuario(BaseModel):
    """O mínimo para alguém entrar. Ver o cabeçalho para o porquê de ser tão pouco."""

    model_config = ConfigDict(extra="forbid")

    nome: Annotated[str, Field(min_length=3, max_length=120)]
    #: Padrão simples de propósito, em vez do `EmailStr` do pydantic: ele exige o
    #: pacote `email-validator`, e uma dependência nova no requirements obrigaria
    #: todo mundo do time a reinstalar o ambiente por causa de um campo. Aqui o
    #: e-mail serve de nome de usuário — o que importa é ter formato de e-mail e
    #: ser único, não passar pelo RFC inteiro.
    email: Annotated[
        str, Field(min_length=5, max_length=160, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
    ]
    #: Sem `pattern` fechado nos três perfis antigos: a lista mora no banco desde
    #: `app/perfis.py`, e cravá-la aqui faria um perfil criado na tela ser
    #: recusado no cadastro pela validação do corpo. A conferência é abaixo,
    #: contra os perfis que existem de verdade.
    perfil: Annotated[str, Field(min_length=2, max_length=60)]
    #: 8 é o mínimo que não é teatro. Vazio deixa a conta com a senha padrão, e o
    #: token sai marcado para a tela exigir a troca no primeiro acesso.
    senha: Annotated[str, Field(max_length=128)] = ""


@roteador.get("", dependencies=[PodeGerir])
def listar_usuarios() -> dict[str, Any]:
    """Quem já existe, com o perfil de cada um.

    A forma da resposta é a mesma da época do Keycloak — `usuario`, `perfis` no
    plural — porque `components/Usuarios.tsx` a consome assim, e trocar os nomes
    aqui só renomearia o mesmo dado em dois lugares.
    """
    with conectar() as con:
        linhas = con.execute(
            f"SELECT codigo, nome, email, perfil, ativo FROM {_TABELA} ORDER BY nome"
        ).fetchall()

    itens = [
        {
            "id": str(linha["codigo"]),
            "usuario": linha["email"],
            "nome": linha["nome"],
            "email": linha["email"],
            "ativo": bool(linha["ativo"]),
            "perfis": [linha["perfil"]],
        }
        for linha in linhas
    ]
    return {"itens": itens, "total": len(itens)}


@roteador.post("", status_code=201, dependencies=[PodeGerir])
def criar_usuario(pedido: NovoUsuario) -> dict[str, Any]:
    """Cria a conta e já deixa entrar — sem etapa de ativação.

    Não há e-mail de confirmação porque não há servidor de e-mail configurado, e
    exigir verificação deixaria toda conta nova barrada num e-mail que nunca
    chega. Quem cadastra está na frente da pessoa e entrega a senha na hora.
    """
    email = pedido.email.strip().lower()

    disponiveis = {p["codigo"] for p in perfis_lib.listar()} or set(CODIGOS)
    if pedido.perfil not in disponiveis:
        raise HTTPException(400, f"Perfil desconhecido: {pedido.perfil}.")

    senha = pedido.senha.strip()
    if senha and not _parece_md5(senha) and len(senha) < 8:
        raise HTTPException(400, "A senha precisa de pelo menos 8 caracteres.")
    hash_senha = _hash_de(senha) if senha else auth.SENHA_PADRAO_MD5

    with conectar() as con:
        existe = con.execute(
            f"SELECT 1 FROM {_TABELA} WHERE email = ?", (email,)
        ).fetchone()
        if existe:
            raise HTTPException(409, f"Já existe usuário com o e-mail {email}.")
        con.execute(
            f"INSERT INTO {_TABELA} (nome, email, senha_md5, perfil, ativo, criado_em)"
            " VALUES (?, ?, ?, ?, 1, ?)",
            (pedido.nome.strip(), email, hash_senha, pedido.perfil, _agora()),
        )
        criado = con.execute(
            f"SELECT codigo FROM {_TABELA} WHERE email = ?", (email,)
        ).fetchone()

    log.info("usuario criado: %s (%s)", email, pedido.perfil)
    return {
        "id": str(criado["codigo"]),
        "usuario": email,
        "nome": pedido.nome.strip(),
        "email": email,
        "perfil": pedido.perfil,
        "perfis": [pedido.perfil],
        "ativo": True,
        "senhaPadrao": hash_senha == auth.SENHA_PADRAO_MD5,
    }


@roteador.delete("/{codigo}", dependencies=[PodeGerir])
def desativar_usuario(codigo: int, request: Request) -> dict[str, Any]:
    """Desativa a conta em vez de apagá-la.

    Apagar quebraria a autoria já gravada: entrevistas, casos e auditoria apontam
    para quem os conduziu, e um registro órfão é pior que um nome inativo na
    lista. Desativado não entra — `autenticar` recusa antes de assinar token.
    """
    usuario = auth.usuario_atual(request)
    if auth.ATIVA and str(codigo) == usuario.id:
        # Quem se desativa perde o acesso e, sendo o único administrador, tranca
        # o sistema para todo mundo.
        raise HTTPException(400, "Você não pode desativar a própria conta.")

    with conectar() as con:
        alteradas = con.execute(
            f"UPDATE {_TABELA} SET ativo = 0 WHERE codigo = ?", (codigo,)
        ).rowcount
    if not alteradas:
        raise HTTPException(404, "Usuário não encontrado.")
    return {"id": str(codigo), "situacao": "desativado"}
