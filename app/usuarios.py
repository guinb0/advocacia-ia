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

O telefone entrou depois, OPCIONAL, pelo mesmo motivo: é o dado que o secretário
precisa para achar a pessoa, e obrigatório ele travaria o cadastro feito na hora.

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

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from . import auth, captcha, dois_fatores
from . import perfis as perfis_lib
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

# O nome dos perfis acima permanece para clientes antigos, mas a autorizacao
# atual vem da matriz relacional. Assim um perfil novo com o modulo `usuarios`
# funciona sem alteracao de codigo.
PodeGerir = Depends(auth.exigir_modulo("usuarios"))

#: Mexer na conta de alguém — e-mail, senha, perfil, situação — é mais que
#: cadastrar: é poder entrar como aquela pessoa. Fica com o papel `secretario` e
#: com mais ninguém, por decisão do escritório.
#:
#: Amarrado ao PAPEL, e não a um módulo, de propósito. Módulo se concede pela
#: matriz de perfis, e quem administra a matriz inclui o advogado (ele tem
#: `usuarios`): com um módulo aqui, bastaria um clique para ele se dar o poder de
#: trocar a senha de qualquer colega. O papel não se concede pela tela.
PodeEditarContas = Depends(auth.exigir_papel("secretario"))


def _autor(usuario: auth.Usuario) -> str:
    """Como a pessoa aparece na trilha de alterações.

    O e-mail vem primeiro por ser o login — é ele que identifica a conta sem
    ambiguidade quando dois colegas têm o mesmo primeiro nome. Com a
    autenticação desligada não há ninguém a nomear, e a trilha diz isso em vez
    de atribuir a alteração a um usuário que não existe.
    """
    if not auth.ATIVA:
        return "sessão sem autenticação"
    return usuario.email or usuario.nome or "desconhecido"


_TABELA = f"{SCHEMA}.{PREFIXO}usuarios"
_TABELA_PERFIS_NOVA = f"{SCHEMA}.{PREFIXO}tb_perfis"

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

IF COL_LENGTH('{_TABELA}', 'perfil_id') IS NULL
ALTER TABLE {_TABELA} ADD perfil_id int NULL;

IF COL_LENGTH('{_TABELA}', 'telefone') IS NULL
ALTER TABLE {_TABELA} ADD telefone varchar(13) NULL;

IF OBJECT_ID('{SCHEMA}.fk_acervo_usuarios_perfil_id', 'F') IS NULL
   AND OBJECT_ID('{_TABELA_PERFIS_NOVA}') IS NOT NULL
   AND COL_LENGTH('{_TABELA}', 'perfil_id') IS NOT NULL
ALTER TABLE {_TABELA}
    ADD CONSTRAINT fk_acervo_usuarios_perfil_id
    FOREIGN KEY (perfil_id) REFERENCES {_TABELA_PERFIS_NOVA} (id);
"""

# Versoes antigas ainda gravam apenas `perfil`. O gatilho preserva esse contrato
# enquanto faz `perfil_id` virar a referencia principal das versoes atuais.
# Precisa ser executado em lote separado: SQL Server exige CREATE TRIGGER como a
# primeira instrucao do lote.
GATILHO_SINCRONIZAR_PERFIL = f"""
CREATE OR ALTER TRIGGER {SCHEMA}.tr_acervo_usuarios_sincronizar_perfil
ON {_TABELA}
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    IF UPDATE(perfil_id)
    BEGIN
        UPDATE u
           SET perfil_id = COALESCE(i.perfil_id, p_nome.id),
               perfil = COALESCE(p_id.nome, p_nome.nome, i.perfil)
          FROM {_TABELA} u
          JOIN inserted i ON i.codigo = u.codigo
     LEFT JOIN {_TABELA_PERFIS_NOVA} p_id ON p_id.id = i.perfil_id
     LEFT JOIN {_TABELA_PERFIS_NOVA} p_nome
            ON p_nome.nome = LTRIM(RTRIM(i.perfil));
    END
    ELSE
    BEGIN
        UPDATE u
           SET perfil_id = p_nome.id,
               perfil = COALESCE(p_nome.nome, i.perfil)
          FROM {_TABELA} u
          JOIN inserted i ON i.codigo = u.codigo
     LEFT JOIN {_TABELA_PERFIS_NOVA} p_nome
            ON p_nome.nome = LTRIM(RTRIM(i.perfil));
    END
END
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


def _normalizar_telefone(valor: str) -> str | None:
    """Só os dígitos, ou `None` quando não veio telefone.

    Dígitos, e não o texto como foi digitado: "(61) 99999-0000", "61999990000" e
    "+55 61 99999-0000" são o mesmo número, e guardar três grafias faria qualquer
    busca por telefone depender de adivinhar como alguém escreveu. A máscara é
    trabalho da tela.
    """
    digitos = "".join(c for c in (valor or "") if c.isdigit())
    if not digitos:
        return None
    if len(digitos) not in (10, 11, 12, 13):
        raise HTTPException(
            400,
            "Telefone precisa de DDD e número: 10 ou 11 dígitos (12 ou 13 com o +55).",
        )
    return digitos


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
        _sincronizar_perfis_dos_usuarios(con)
        con.execute(GATILHO_SINCRONIZAR_PERFIL)

    # Fora do `with`: `dois_fatores.inicializar` abre a própria conexão, e
    # aninhar duas contra o mesmo banco não rende nada além de risco de trava.
    dois_fatores.inicializar()

    with conectar() as con:
        email = (_env("ACERVO_ADMIN_EMAIL") or "admin@acervo.local").lower()
        ja_tem = con.execute(f"SELECT TOP 1 codigo FROM {_TABELA}").fetchone()
        if ja_tem:
            return

        senha = _env("ACERVO_ADMIN_SENHA")
        # Sem senha no `.env`, a conta nasce com a senha padrão e o token sai com
        # `senhaPadrao: true` — a tela obriga a trocar antes de seguir. É melhor
        # que gerar uma senha aleatória que ninguém vê passar no log.
        hash_senha = _hash_de(senha) if senha else auth.SENHA_PADRAO_MD5
        perfil_id = perfis_lib.perfil_id_de("advogado", con=con)
        con.execute(
            f"INSERT INTO {_TABELA} (nome, email, senha_md5, perfil, perfil_id, ativo, criado_em)"
            " VALUES (?, ?, ?, 'advogado', ?, 1, ?)",
            ("Administrador", email, hash_senha, perfil_id, _agora()),
        )
        log.warning(
            "Nenhum usuário cadastrado: criada a conta inicial %s%s",
            email,
            "" if senha else " com a SENHA PADRÃO (123456) — troque no primeiro acesso",
        )


def _sincronizar_perfis_dos_usuarios(con: Any) -> None:
    # `perfil_id` e a fonte atual. Quando ele existe, a string antiga vira um
    # espelho canonico; quando falta, fazemos o backfill pelo nome legado.
    con.execute(
        f"""UPDATE u
               SET perfil = p.nome
              FROM {_TABELA} u
              JOIN {_TABELA_PERFIS_NOVA} p ON p.id = u.perfil_id
             WHERE u.perfil <> p.nome"""
    )
    con.execute(
        f"""UPDATE u
               SET perfil_id = p.id, perfil = p.nome
              FROM {_TABELA} u
              JOIN {_TABELA_PERFIS_NOVA} p
                ON p.nome = LTRIM(RTRIM(u.perfil))
             WHERE u.perfil_id IS NULL"""
    )


def _resolver_perfil_usuario(
    con: Any, perfil_id: int | None, perfil_legado: str | None
) -> tuple[int, str]:
    """Resolve o perfil dentro da mesma transacao que cria o usuario."""
    nome_legado = (perfil_legado or "").strip()
    if perfil_id is not None:
        nome = perfis_lib.perfil_nome_de_id(perfil_id, con=con)
        if nome is None:
            raise HTTPException(400, f"Perfil inexistente ou inativo: {perfil_id}.")
        if nome_legado and nome_legado != nome:
            raise HTTPException(
                400,
                "O identificador e o nome do perfil informados nao correspondem.",
            )
        return perfil_id, nome

    if not nome_legado:
        raise HTTPException(400, "Informe o perfil do usuario.")
    id_legado = perfis_lib.perfil_id_de(nome_legado, con=con)
    if id_legado is None:
        raise HTTPException(400, f"Perfil desconhecido: {nome_legado}.")
    return id_legado, nome_legado


def _linha_usuario(linha: Any) -> dict[str, Any]:
    perfil = linha["perfil_ref"] or linha["perfil"]
    return {
        "codigo": str(linha["codigo"]),
        "nome": linha["nome"],
        "email": linha["email"],
        "senha_md5": (linha["senha_md5"] or "").strip().lower(),
        "perfil": perfil,
        "perfil_id": linha["perfil_id"],
        "perfil_ativo": bool(linha["perfil_ativo"]) if linha["perfil_ativo"] is not None else False,
        "ativo": bool(linha["ativo"]),
    }


def _por_email(email: str) -> dict[str, Any] | None:
    with conectar() as con:
        linha = con.execute(
            f"""SELECT u.codigo, u.nome, u.email, u.senha_md5, u.perfil,
                       COALESCE(p_id.id, p_nome.id) AS perfil_id,
                       u.ativo,
                       COALESCE(p_id.nome, p_nome.nome) AS perfil_ref,
                       COALESCE(p_id.ativo, p_nome.ativo) AS perfil_ativo
                  FROM {_TABELA} u
             LEFT JOIN {_TABELA_PERFIS_NOVA} p_id ON p_id.id = u.perfil_id
             LEFT JOIN {_TABELA_PERFIS_NOVA} p_nome ON p_nome.nome = u.perfil
                 WHERE u.email = ?""",
            (email.strip().lower(),),
        ).fetchone()
    if linha is None:
        return None
    return _linha_usuario(linha)


def por_email(email: str) -> dict[str, Any] | None:
    """A conta, por e-mail. Versão pública de `_por_email`.

    Existe porque `app/dois_fatores.py` precisa do nome de quem vai receber o
    código para escrever a mensagem, e importar um `_privado` de outro módulo é
    o tipo de acoplamento que ninguém enxerga quando renomeia.
    """
    return _por_email(email)


def papeis_ativos_de_email(email: str) -> tuple[str, ...]:
    """Perfil atual da conta, consultado do banco para autorizacao."""
    pessoa = _por_email(email)
    if pessoa is None or not pessoa["ativo"] or not pessoa["perfil_ativo"]:
        return ()
    return (pessoa["perfil"],)


def _primeira_conta_ativa() -> dict[str, Any] | None:
    with conectar() as con:
        linha = con.execute(
            f"""SELECT TOP 1 u.codigo, u.nome, u.email, u.senha_md5, u.perfil,
                       COALESCE(p_id.id, p_nome.id) AS perfil_id,
                       u.ativo,
                       COALESCE(p_id.nome, p_nome.nome) AS perfil_ref,
                       COALESCE(p_id.ativo, p_nome.ativo) AS perfil_ativo
                  FROM {_TABELA} u
             LEFT JOIN {_TABELA_PERFIS_NOVA} p_id ON p_id.id = u.perfil_id
             LEFT JOIN {_TABELA_PERFIS_NOVA} p_nome ON p_nome.nome = u.perfil
                 WHERE u.ativo = 1
              ORDER BY u.codigo"""
        ).fetchone()
    if linha is None:
        return None
    return _linha_usuario(linha)


def _sessao_da_pessoa(pessoa: dict[str, Any]) -> dict[str, Any]:
    return {
        "codigo": pessoa["codigo"],
        "nome": pessoa["nome"],
        "email": pessoa["email"],
        "perfil": pessoa["perfil"],
        "perfilId": pessoa["perfil_id"],
        "ativo": pessoa["ativo"],
        "senhaPadrao": pessoa["senha_md5"] == auth.SENHA_PADRAO_MD5,
        "modulos": perfis_lib.modulos_ordenados_de([pessoa["perfil"]]),
    }


def _exigir_perfil_ativo(pessoa: dict[str, Any]) -> None:
    if not pessoa.get("perfil_id") or not pessoa.get("perfil_ativo"):
        raise HTTPException(
            403,
            "Esta conta usa um perfil desativado ou inexistente. Ajuste o usuário antes de entrar.",
        )


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

    #: O token que o widget do Turnstile produz no navegador. Vazio quando o
    #: captcha está desligado (`TURNSTILE_SECRET_KEY` ausente) — e aí
    #: `captcha.verificar` passa direto. Tem valor padrão para o `curl` de
    #: depuração continuar funcionando num ambiente sem captcha.
    captcha: str = ""


class PedidoCodigo(BaseModel):
    """O segundo passo: o código de seis dígitos que chegou por e-mail."""

    model_config = ConfigDict(extra="ignore")

    #: O identificador do desafio devolvido pelo primeiro passo. É ele que diz de
    #: QUEM é o código — a rota não aceita e-mail no corpo, senão bastaria ter um
    #: código válido qualquer para escolher em que conta entrar.
    desafio: Annotated[str, Field(min_length=8, max_length=64)]
    codigo: Annotated[str, Field(min_length=4, max_length=10)]


class PedidoReenvio(BaseModel):
    model_config = ConfigDict(extra="ignore")

    desafio: Annotated[str, Field(min_length=8, max_length=64)]


def _ip_do_pedido(request: Request) -> str:
    """De onde veio a requisição, para o Turnstile conferir.

    `X-Forwarded-For` primeiro porque em produção a API responde atrás de proxy,
    e ali `request.client.host` é o IP do proxy — igual para todo mundo, o que
    tornaria a checagem inútil. Só o PRIMEIRO endereço da lista é lido: os
    seguintes são anexados pelos saltos e podem ser forjados pelo cliente.
    """
    encaminhado = request.headers.get("x-forwarded-for", "")
    if encaminhado:
        return encaminhado.split(",")[0].strip()
    return request.client.host if request.client else ""


def _emitir_sessao(pessoa: dict[str, Any], resposta: Response) -> dict[str, Any]:
    """Assina o token, grava o cookie e devolve o envelope da sessão.

    Existe como função porque agora há DOIS caminhos que terminam em sessão
    aberta — o login direto (perfil isento de segundo fator) e a confirmação do
    código. Duplicar isto seria duplicar a emissão de credencial, que é
    exatamente o lugar onde dois trechos parecidos divergem sem ninguém notar.
    """
    senha_padrao = pessoa["senha_md5"] == auth.SENHA_PADRAO_MD5
    token = auth.gerar_token(
        codigo=pessoa["codigo"],
        nome=pessoa["nome"],
        email=pessoa["email"],
        perfil=pessoa["perfil"],
        senha_padrao=senha_padrao,
    )
    auth.definir_cookie(resposta, token)
    log.info("login: %s (%s)", pessoa["email"], pessoa["perfil"])
    return {
        "flag": True,
        "message": "Autenticado.",
        # Os módulos que este perfil alcança vão junto para a tela montar o menu
        # sem uma segunda ida ao servidor — e para o menu não oferecer botão que
        # a rota vai recusar depois.
        "data": {**_sessao_da_pessoa(pessoa), "etapa": "sessao"},
    }


def _conferir_credencial(email: str, senha: str) -> dict[str, Any]:
    """E-mail e senha. Levanta na credencial errada, na conta desativada e no
    perfil morto; devolve a pessoa quando passa."""
    pessoa = _por_email(email)
    informado = _hash_de(senha)

    # Uma resposta só para "não existe" e para "senha errada", de propósito:
    # respostas diferentes contam a quem tenta quais e-mails têm conta aqui.
    if pessoa is None or pessoa["senha_md5"] != informado:
        log.warning("login recusado para %s", email)
        raise HTTPException(401, "E-mail ou senha incorretos.")
    if not pessoa["ativo"]:
        raise HTTPException(403, "Esta conta está desativada. Procure quem administra.")
    _exigir_perfil_ativo(pessoa)
    return pessoa


@roteador_sessao.post("/authenticate")
def autenticar(pedido: PedidoLogin, request: Request, resposta: Response) -> dict[str, Any]:
    """Primeiro passo do login: captcha, senha e — quando o perfil exige — o
    código por e-mail.

    A ORDEM DAS TRÊS CHECAGENS NÃO É ARBITRÁRIA. O captcha vem antes da senha
    porque é ele que impede a conferência de senha de ser chamada mil vezes por
    minuto; conferir a senha primeiro deixaria a força bruta acontecer e só
    depois recusaria a resposta. E o segundo fator vem por último porque só faz
    sentido mandar código a quem já provou saber a senha — senão a rota vira um
    jeito de disparar e-mail em nome do sistema para qualquer endereço.

    A RESPOSTA TEM DUAS FORMAS, e o campo `etapa` diz qual:

    - `"sessao"`: acabou aqui. O cookie foi gravado e o `data` traz a sessão. É o
      caso do perfil isento (`cliente`) e o de quando o segundo fator está
      desligado;
    - `"dois_fatores"`: falta um passo. NENHUM cookie foi gravado — quem tem só a
      senha não recebe credencial nenhuma daqui — e o `data` traz o identificador
      do desafio, o e-mail mascarado e os prazos. A sessão nasce em
      `POST /api/user/authenticate/verify`.

    O token NÃO vai no corpo em nenhuma das duas. Devolvê-lo ali desfaria toda a
    proteção do `HttpOnly`: bastaria um XSS ler a resposta do login.
    """
    captcha.verificar(pedido.captcha, _ip_do_pedido(request))

    email = _decodificar(pedido.email).strip().lower()
    if not email or not pedido.senha:
        raise HTTPException(400, "Informe e-mail e senha.")

    pessoa = _conferir_credencial(email, pedido.senha)

    if not dois_fatores.exigido_para(pessoa["perfil"]):
        return _emitir_sessao(pessoa, resposta)

    if not dois_fatores.ATIVO:
        # SMTP faltando. Recusar ou deixar passar é escolha de quem implanta, e
        # ela está no `.env` — ver DOIS_FATORES_OBRIGATORIO. O que não pode é o
        # sistema decidir isto em silêncio: as duas saídas gritam no log.
        if dois_fatores.OBRIGATORIO:
            log.error(
                "login de %s recusado: segundo fator obrigatório e SMTP não configurado",
                email,
            )
            raise HTTPException(
                503,
                "O segundo fator de autenticação está indisponível. Procure quem "
                "administra o sistema.",
            )
        log.warning(
            "SEGUNDO FATOR PULADO para %s: SMTP não configurado. Preencha SMTP_HOST "
            "ou ligue DOIS_FATORES_OBRIGATORIO=1 para recusar em vez de deixar passar.",
            email,
        )
        return _emitir_sessao(pessoa, resposta)

    desafio = dois_fatores.abrir_desafio(email=pessoa["email"], nome=pessoa["nome"])
    return {
        "flag": True,
        "message": "Enviamos um código de acesso para o seu e-mail.",
        "data": {"etapa": "dois_fatores", **desafio},
    }


@roteador_sessao.post("/authenticate/verify")
def confirmar_codigo(pedido: PedidoCodigo, resposta: Response) -> dict[str, Any]:
    """Segundo passo: confere o código e só então abre a sessão.

    O captcha NÃO se repete aqui. Ele já filtrou o robô na porta, e o desafio tem
    limite próprio de tentativas (`dois_fatores.TENTATIVAS_MAXIMAS`) — pedir uma
    segunda verificação da Cloudflare cobraria mais um obstáculo de quem já provou
    duas coisas, sem fechar buraco nenhum.

    A conta é RELIDA do banco em vez de vir guardada junto do desafio: entre o
    primeiro passo e este alguém pode ter desativado a conta ou trocado o perfil,
    e a sessão tem de nascer com o que vale agora.
    """
    email = dois_fatores.conferir(pedido.desafio, pedido.codigo)
    pessoa = _por_email(email)
    if pessoa is None:
        raise HTTPException(401, "Esta conta não existe mais. Procure quem administra.")
    if not pessoa["ativo"]:
        raise HTTPException(403, "Esta conta está desativada. Procure quem administra.")
    _exigir_perfil_ativo(pessoa)
    return _emitir_sessao(pessoa, resposta)


@roteador_sessao.post("/authenticate/resend")
def reenviar_codigo(pedido: PedidoReenvio) -> dict[str, Any]:
    """Manda um código novo para o mesmo desafio.

    O corpo traz só o identificador do desafio — nunca o e-mail. Aceitar um
    endereço aqui transformaria a rota num disparador de e-mail para qualquer
    destinatário, em nome do escritório, sem ninguém precisar de senha.
    """
    return {
        "flag": True,
        "message": "Novo código enviado.",
        "data": {"etapa": "dois_fatores", **dois_fatores.reenviar(pedido.desafio)},
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
        pessoa = _primeira_conta_ativa()
        if pessoa is not None:
            _exigir_perfil_ativo(pessoa)
            return {"flag": True, "data": _sessao_da_pessoa(pessoa)}
        return {
            "flag": True,
            "data": {
                "codigo": usuario.id,
                "nome": usuario.nome,
                "email": usuario.email,
                "perfil": "advogado",
                "perfilId": perfis_lib.perfil_id_de("advogado"),
                "ativo": True,
                "senhaPadrao": False,
                "modulos": perfis_lib.modulos_ordenados_de(["advogado"]),
            },
        }

    pessoa = _por_email(usuario.email)
    if pessoa is None:
        # A conta sumiu depois do token emitido. Não é 404: do ponto de vista de
        # quem chama, a sessão é que deixou de valer.
        raise HTTPException(401, "Sua conta não existe mais. Entre novamente.")
    _exigir_perfil_ativo(pessoa)
    return {"flag": True, "data": _sessao_da_pessoa(pessoa)}


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
    _exigir_perfil_ativo(pessoa)
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
    return {"modulos": perfis_lib.catalogo()}


@roteador.get("/perfis/matriz", dependencies=[PodeGerir])
def matriz_de_perfis() -> dict[str, Any]:
    """Os perfis COM os módulos de cada um, para a tela de gerenciamento.

    Separada de `GET /perfis` porque as duas respondem a perguntas diferentes,
    para públicos diferentes. Aquela é vocabulário — "que perfis existem?" — e
    responde a qualquer conta autenticada, porque alimenta o seletor do cadastro. Esta diz o que cada
    perfil ALCANÇA, que é desenho de acesso do escritório e só interessa a quem
    administra. Juntar as duas obrigaria a proteger o vocabulário ou a expor a
    matriz; nenhuma das duas serve.
    """
    contagem = perfis_lib.usuarios_por_perfil()
    perfis = perfis_lib.listar()
    for perfil in perfis:
        # Zero explícito, e não ausência: a tela precisa dizer "nenhuma conta"
        # com a mesma confiança com que diz "4 contas", e um campo faltando ali
        # vira "—", que se lê como "não sei".
        perfil["usuarios"] = contagem.get(perfil["codigo"], {"total": 0, "ativos": 0})
    return {"perfis": perfis, "modulos": perfis_lib.catalogo()}


@roteador.get("/perfis/historico")
def historico_de_perfis(
    limite: Annotated[int, Query(ge=1, le=200)] = 50,
    _usuario: auth.Usuario = PodeGerir,
) -> dict[str, Any]:
    """As últimas alterações feitas nos perfis, com autor e o que mudou.

    Fica ao lado da matriz porque é a mesma pergunta em outro tempo verbal: a
    matriz diz como o acesso está, o histórico diz como ele chegou nesse estado
    — e quem administra precisa das duas para responder "quem abriu isto, e
    quando?" sem depender da memória de alguém.
    """
    return {"alteracoes": perfis_lib.historico(limite)}


@roteador.put("/perfis/{codigo}")
def salvar_perfil(
    codigo: str, pedido: PedidoPerfil, usuario: auth.Usuario = PodeGerir
) -> dict[str, Any]:
    """Cria ou atualiza um perfil e a matriz de módulos dele.

    O corpo traz o estado COMPLETO das caixas: a matriz é substituída inteira, em
    vez de comparada item a item — comparar só criaria caminho para a tela e o
    banco discordarem sobre o que está marcado.
    """
    if codigo != pedido.codigo:
        raise HTTPException(400, "O código do endereço e o do corpo precisam ser iguais.")
    try:
        return perfis_lib.salvar(
            pedido.codigo,
            pedido.rotulo,
            pedido.descricao,
            pedido.modulos,
            autor=_autor(usuario),
        )
    except ValueError as erro:
        raise HTTPException(400, str(erro)) from erro


@roteador.delete("/perfis/{codigo}")
def remover_perfil(codigo: str, usuario: auth.Usuario = PodeGerir) -> dict[str, str]:
    """Apaga um perfil. Os de sistema recusam — ver `perfis.SEMENTE`.

    Recusa também enquanto houver gente usando: apagar o perfil de alguém deixaria
    a conta sem nada que a matriz reconheça, e o sintoma seria uma pessoa que
    entra e não enxerga tela nenhuma, sem mensagem que explique.
    """
    with conectar() as con:
        perfil_id = perfis_lib.perfil_id_de(codigo, ativo=False, con=con)
        em_uso = con.execute(
            f"""SELECT COUNT(*) AS n
                  FROM {_TABELA}
                 WHERE perfil = ?
                    OR (? IS NOT NULL AND perfil_id = ?)""",
            (codigo, perfil_id, perfil_id),
        ).fetchone()
    if em_uso and int(em_uso["n"]):
        raise HTTPException(
            400,
            f"{em_uso['n']} usuário(s) ainda usam este perfil. Mova essas contas antes.",
        )
    try:
        perfis_lib.remover(codigo, autor=_autor(usuario))
    except ValueError as erro:
        raise HTTPException(400, str(erro)) from erro
    return {"codigo": codigo, "situacao": "removido"}


@roteador.get("/perfis")
def listar_perfis() -> dict[str, Any]:
    """Os perfis que a tela oferece. Vocabulário: não exige o módulo `usuarios`.

    Lê do banco em vez de uma lista cravada: é o que faz um perfil criado na tela
    aparecer no seletor do cadastro sem alguém editar código. Os módulos de cada
    perfil NÃO vêm aqui — quem pergunta isto está montando um seletor, e o
    desenho de acesso do escritório não precisa sair para isso. (A sessão continua
    exigida pelo middleware: `LIVRES_SEM_ADVOGADO` dispensa o PAPEL de advogado,
    não a autenticação.)

    Falha de banco deve aparecer como erro: devolver a semente sem IDs criaria
    contas inconsistentes e faria o cadastro parecer disponivel quando nao esta.
    """
    cadastrados = perfis_lib.listar()
    return {
        "perfis": [
            {
                "id": p["id"],
                "codigo": p["codigo"],
                "rotulo": p["rotulo"],
                "descricao": p["descricao"],
            }
            for p in cadastrados
        ]
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
    perfil_id: Annotated[
        int | None,
        Field(validation_alias=AliasChoices("perfilId", "perfil_id"), gt=0),
    ] = None
    #: Compatibilidade com clientes antigos. A tela atual envia `perfilId` e o
    #: servidor deriva este nome da tabela de perfis.
    perfil: Annotated[str | None, Field(default=None, min_length=2, max_length=60)] = None
    #: Opcional. Chega como foi digitado; `_normalizar_telefone` guarda só os dígitos.
    telefone: Annotated[str, Field(max_length=30)] = ""
    #: 8 é o mínimo que não é teatro. Vazio deixa a conta com a senha padrão, e o
    #: token sai marcado para a tela exigir a troca no primeiro acesso.
    senha: Annotated[str, Field(max_length=128)] = ""


@roteador.get("", dependencies=[PodeGerir])
def listar_usuarios(
    pagina: Annotated[int, Query(ge=1)] = 1,
    tamanho: Annotated[int, Query(ge=1, le=50)] = 12,
) -> dict[str, Any]:
    """Quem já existe, com o perfil de cada um.

    A forma da resposta é a mesma da época do Keycloak — `usuario`, `perfis` no
    plural — porque `components/Usuarios.tsx` a consome assim, e trocar os nomes
    aqui só renomearia o mesmo dado em dois lugares.
    """
    tamanho_real = max(1, min(int(tamanho or 12), 50))
    pagina_pedida = max(1, int(pagina or 1))

    with conectar() as con:
        total_linha = con.execute(f"SELECT COUNT(*) AS n FROM {_TABELA}").fetchone()
        total = int(total_linha["n"] if total_linha else 0)
        paginas = max(1, (total + tamanho_real - 1) // tamanho_real)
        pagina_real = min(pagina_pedida, paginas)
        offset = (pagina_real - 1) * tamanho_real
        linhas = con.execute(
            f"""SELECT u.codigo, u.nome, u.email, u.telefone, u.perfil, u.ativo,
                       COALESCE(p_id.id, p_nome.id) AS perfil_id,
                       COALESCE(p_id.nome, p_nome.nome) AS perfil_ref
                  FROM {_TABELA} u
             LEFT JOIN {_TABELA_PERFIS_NOVA} p_id ON p_id.id = u.perfil_id
             LEFT JOIN {_TABELA_PERFIS_NOVA} p_nome ON p_nome.nome = u.perfil
              ORDER BY u.nome
                OFFSET ? ROWS FETCH NEXT ? ROWS ONLY""",
            (offset, tamanho_real),
        ).fetchall()

    itens = [
        {
            "id": str(linha["codigo"]),
            "usuario": linha["email"],
            "nome": linha["nome"],
            "email": linha["email"],
            "telefone": linha["telefone"] or "",
            "ativo": bool(linha["ativo"]),
            "perfis": [linha["perfil_ref"] or linha["perfil"]],
            "perfilId": linha["perfil_id"],
        }
        for linha in linhas
    ]
    return {
        "itens": itens,
        "total": total,
        "pagina": pagina_real,
        "tamanho": tamanho_real,
        "paginas": paginas,
    }


def listar_colaboradores_ativos() -> list[dict[str, Any]]:
    with conectar() as con:
        linhas = con.execute(
            f"SELECT codigo, nome FROM {_TABELA} WHERE ativo = 1 ORDER BY nome"
        ).fetchall()
    return [{"id": str(linha["codigo"]), "nome": str(linha["nome"])} for linha in linhas]


@roteador.post("", status_code=201, dependencies=[PodeGerir])
def criar_usuario(pedido: NovoUsuario) -> dict[str, Any]:
    """Cria a conta e já deixa entrar — sem etapa de ativação.

    Não há e-mail de confirmação porque não há servidor de e-mail configurado, e
    exigir verificação deixaria toda conta nova barrada num e-mail que nunca
    chega. Quem cadastra está na frente da pessoa e entrega a senha na hora.
    """
    email = pedido.email.strip().lower()

    senha = pedido.senha.strip()
    if senha and not _parece_md5(senha) and len(senha) < 8:
        raise HTTPException(400, "A senha precisa de pelo menos 8 caracteres.")
    hash_senha = _hash_de(senha) if senha else auth.SENHA_PADRAO_MD5
    telefone = _normalizar_telefone(pedido.telefone)

    with conectar() as con:
        perfil_id, perfil = _resolver_perfil_usuario(con, pedido.perfil_id, pedido.perfil)
        existe = con.execute(
            f"SELECT 1 FROM {_TABELA} WHERE email = ?", (email,)
        ).fetchone()
        if existe:
            raise HTTPException(409, f"Já existe usuário com o e-mail {email}.")
        con.execute(
            f"INSERT INTO {_TABELA}"
            " (nome, email, telefone, senha_md5, perfil, perfil_id, ativo, criado_em)"
            " VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (pedido.nome.strip(), email, telefone, hash_senha, perfil, perfil_id, _agora()),
        )
        criado = con.execute(
            f"SELECT codigo FROM {_TABELA} WHERE email = ?", (email,)
        ).fetchone()

    log.info("usuario criado: %s (%s, id=%s)", email, perfil, perfil_id)
    return {
        "id": str(criado["codigo"]),
        "usuario": email,
        "nome": pedido.nome.strip(),
        "email": email,
        "perfil": perfil,
        "perfilId": perfil_id,
        "perfis": [perfil],
        "telefone": telefone or "",
        "ativo": True,
        "senhaPadrao": hash_senha == auth.SENHA_PADRAO_MD5,
    }


@roteador.delete("/{codigo}", dependencies=[PodeEditarContas])
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


# ------------------------------------------------------------------ edição


class EdicaoUsuario(BaseModel):
    """A conta inteira como deve ficar — não um remendo campo a campo.

    Completa pelo mesmo motivo da matriz de perfis: a tela manda o formulário
    inteiro, e aceitar só o que mudou criaria o caso de tela e banco discordarem
    sobre o que está gravado. A senha é a exceção, e por segurança: ela nunca sai
    do servidor, então a tela não tem o que reenviar — vazio só pode ser "manter".
    """

    model_config = ConfigDict(extra="forbid")

    nome: Annotated[str, Field(min_length=3, max_length=120)]
    email: Annotated[
        str, Field(min_length=5, max_length=160, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
    ]
    telefone: Annotated[str, Field(max_length=30)] = ""
    perfil_id: Annotated[
        int, Field(validation_alias=AliasChoices("perfilId", "perfil_id"), gt=0)
    ]
    ativo: bool = True
    senha: Annotated[str, Field(max_length=128)] = ""
    #: Volta a conta para a senha padrão, que obriga a troca no próximo acesso. É o
    #: caminho para "esqueci a senha": o secretário não precisa inventar uma senha
    #: e ditá-la, e a pessoa escolhe a dela ao entrar.
    redefinir_senha: Annotated[
        bool, Field(validation_alias=AliasChoices("redefinirSenha", "redefinir_senha"))
    ] = False


@roteador.put("/{codigo}")
def editar_usuario(
    codigo: int,
    pedido: EdicaoUsuario,
    resposta: Response,
    usuario: auth.Usuario = PodeEditarContas,
) -> dict[str, Any]:
    """Altera nome, e-mail, telefone, perfil, situação e senha de uma conta.

    SÓ O SECRETÁRIO — ver `PodeEditarContas`.

    DUAS RECUSAS SOBRE A PRÓPRIA CONTA

    O secretário não muda o próprio perfil nem desativa a própria conta. Nos dois
    casos ele perderia, no mesmo clique, o poder de desfazer o que fez — e sendo o
    único secretário, o escritório inteiro fica sem quem edite contas.

    O QUE ACONTECE COM QUEM ESTÁ LOGADO

    A autorização lê o perfil do BANCO pelo e-mail a cada requisição (ver
    `auth._papeis_atuais`). Então perfil trocado e conta desativada valem na hora.
    E-mail trocado desliga a sessão aberta da pessoa, que entra de novo com o
    e-mail novo. Senha trocada NÃO derruba sessão aberta — o token vale até 24 h
    e não carrega a senha; para cortar acesso agora, desative a conta.

    Quando é a própria conta e o e-mail ou a senha mudam, o token é reemitido,
    senão o secretário se desconectaria editando o próprio cadastro.
    """
    email = pedido.email.strip().lower()
    nome = pedido.nome.strip()
    telefone = _normalizar_telefone(pedido.telefone)

    senha = pedido.senha.strip()
    if senha and pedido.redefinir_senha:
        raise HTTPException(
            400, "Escolha entre definir uma senha nova e voltar para a senha padrão."
        )
    if senha and not _parece_md5(senha) and len(senha) < 8:
        raise HTTPException(400, "A senha precisa de pelo menos 8 caracteres.")
    if pedido.redefinir_senha:
        novo_hash: str | None = auth.SENHA_PADRAO_MD5
    else:
        novo_hash = _hash_de(senha) if senha else None

    with conectar() as con:
        atual = con.execute(
            f"""SELECT codigo, nome, email, telefone, perfil, perfil_id, ativo
                  FROM {_TABELA}
                 WHERE codigo = ?""",
            (codigo,),
        ).fetchone()
        if atual is None:
            raise HTTPException(404, "Usuário não encontrado.")

        perfil_id, perfil = _resolver_perfil_usuario(con, pedido.perfil_id, None)
        email_atual = str(atual["email"] or "").strip().lower()
        # Comparado pelo NOME do perfil, e não pelo id: conta antiga pode estar
        # sem `perfil_id` preenchido, e aí comparar ids acusaria mudança que não há.
        perfil_mudou = perfil != str(atual["perfil"] or "").strip()
        propria = auth.ATIVA and email_atual == usuario.email.strip().lower()

        if propria and perfil_mudou:
            raise HTTPException(
                400, "Você não pode mudar o próprio perfil. Peça a outro secretário."
            )
        if propria and not pedido.ativo:
            raise HTTPException(400, "Você não pode desativar a própria conta.")

        if email != email_atual:
            outro = con.execute(
                f"SELECT 1 FROM {_TABELA} WHERE email = ? AND codigo <> ?", (email, codigo)
            ).fetchone()
            if outro:
                raise HTTPException(409, f"Já existe outro usuário com o e-mail {email}.")

        alterados: list[str] = []
        if nome != atual["nome"]:
            alterados.append("nome")
        if email != email_atual:
            alterados.append("email")
        if telefone != (atual["telefone"] or None):
            alterados.append("telefone")
        if perfil_mudou:
            alterados.append("perfil")
        if pedido.ativo != bool(atual["ativo"]):
            alterados.append("situação")
        if pedido.redefinir_senha:
            alterados.append("senha padrão")
        elif novo_hash is not None:
            alterados.append("senha")

        con.execute(
            f"""UPDATE {_TABELA}
                   SET nome = ?, email = ?, telefone = ?, perfil = ?, perfil_id = ?, ativo = ?
                 WHERE codigo = ?""",
            (nome, email, telefone, perfil, perfil_id, 1 if pedido.ativo else 0, codigo),
        )
        if novo_hash is not None:
            con.execute(
                f"UPDATE {_TABELA} SET senha_md5 = ? WHERE codigo = ?", (novo_hash, codigo)
            )

    # O nome dos campos, nunca o valor: senha e e-mail antigos não vão para o log.
    log.info(
        "usuario %s editado por %s: %s",
        codigo,
        _autor(usuario),
        ", ".join(alterados) or "nada mudou",
    )

    if propria and ("email" in alterados or novo_hash is not None):
        pessoa = _por_email(email)
        if pessoa is not None:
            auth.definir_cookie(
                resposta,
                auth.gerar_token(
                    codigo=pessoa["codigo"],
                    nome=pessoa["nome"],
                    email=pessoa["email"],
                    perfil=pessoa["perfil"],
                    senha_padrao=pessoa["senha_md5"] == auth.SENHA_PADRAO_MD5,
                ),
            )

    return {
        "id": str(codigo),
        "usuario": email,
        "nome": nome,
        "email": email,
        "telefone": telefone or "",
        "perfil": perfil,
        "perfilId": perfil_id,
        "perfis": [perfil],
        "ativo": pedido.ativo,
        "alterados": alterados,
    }
