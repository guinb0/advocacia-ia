"""Segundo fator do login: código de seis dígitos por e-mail.

POR QUE O SEGUNDO FATOR, E POR QUE POR E-MAIL

A senha sozinha é o único obstáculo entre uma credencial vazada e a carteira
inteira do escritório — casos, documentos de cliente, gravação de entrevista. E a
senha aqui é MD5 sem sal (ver o cabeçalho de `app/usuarios.py`): um vazamento da
tabela devolve as senhas em claro. O segundo fator é o que faz esse vazamento
deixar de ser acesso imediato.

O e-mail foi a escolha do escritório sobre o TOTP. Vale registrar honestamente o
que ela custa: quem controlar a caixa de e-mail da pessoa passa pelo segundo
fator, então ele protege contra senha vazada e não contra conta de e-mail
comprometida. O TOTP não teria essa dependência — trocar depois é substituir
este módulo, e não mexer nas rotas.

O QUE FICA GUARDADO

Não o código: o que a tabela guarda é o SHA-256 dele, salgado com o `JWT_SECRET`
e com o id do desafio. Um SELECT no banco durante os dez minutos de validade não
entrega o acesso de ninguém.

AS TRÊS TRAVAS

Seis dígitos são um milhão de combinações — sem limite, um robô as percorre em
minutos. Por isso o desafio morre por três caminhos: `VALIDADE_MINUTOS`,
`TENTATIVAS_MAXIMAS` erradas e `ENVIOS_MAXIMOS` reenvios. O contador de
tentativas NÃO zera no reenvio, de propósito: se zerasse, pedir código novo seria
o jeito de tentar para sempre.

QUEM PRECISA PASSAR POR AQUI

Todo perfil interno. `cliente` fica de fora: ele entra pelo portal com link
próprio, não tem senha do escritório, e exigir e-mail a cada acesso trocaria
segurança que ele não tem por documento que ele não envia.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from . import ambiente, auth, correio
from .banco import PREFIXO, SCHEMA, conectar

log = logging.getLogger("dois_fatores")

# O `.env` é lido AQUI, e não deixado por conta de quem sobe o processo.
#
# `banco.py` só o carrega dentro de `dsn()`, e este módulo lê a configuração no
# import: subir a API por `uvicorn app.main:app` — sem o `iniciar.ps1`, que
# exporta o arquivo antes — deixaria a proteção desligada sem ninguém ter pedido,
# e desligada em silêncio é o pior dos estados. É o mesmo motivo que fez
# `app/ambiente.py` existir. Idempotente e sem sobrescrever: variável já presente
# no ambiente continua vencendo o arquivo.
#
# `app/auth.py` NÃO faz isto, de propósito — mudar a carga dele mudaria quando a
# autenticação liga, que é comportamento de anos e não é assunto deste módulo.
ambiente.carregar()


_TABELA = f"{SCHEMA}.{PREFIXO}login_desafios"


def _env(nome: str, padrao: str = "") -> str:
    return (os.getenv(nome, padrao) or "").strip()


#: Dez minutos: sobra para achar o e-mail numa caixa cheia e não deixa um código
#: interceptado valer a tarde inteira.
VALIDADE_MINUTOS = int(_env("DOIS_FATORES_VALIDADE_MIN", "10") or 10)

TENTATIVAS_MAXIMAS = int(_env("DOIS_FATORES_TENTATIVAS", "5") or 5)
ENVIOS_MAXIMOS = int(_env("DOIS_FATORES_ENVIOS", "3") or 3)

#: Espera mínima entre reenvios. Sem ela o botão "reenviar" vira um jeito de
#: fazer o sistema mandar e-mail em rajada para a caixa de outra pessoa.
ESPERA_REENVIO_S = int(_env("DOIS_FATORES_ESPERA_REENVIO_S", "60") or 60)

#: Perfis que NÃO passam pelo segundo fator. Só o cliente, por padrão.
ISENTOS = {
    p.strip().lower()
    for p in (_env("DOIS_FATORES_PERFIS_ISENTOS", "cliente") or "").split(",")
    if p.strip()
}

#: `1` recusa o login quando o SMTP não está configurado, em vez de deixar
#: passar direto.
#:
#: O padrão é `0` porque o projeto inteiro adota "abre e grita no log" para
#: configuração faltando (é o que o `JWT_SECRET` faz), e trancar todo mundo para
#: fora por causa de um `.env` incompleto em desenvolvimento seria pior. Em
#: produção, ligue: é a diferença entre "o segundo fator está ligado" e "o
#: segundo fator está ligado quando dá".
OBRIGATORIO = _env("DOIS_FATORES_OBRIGATORIO", "0") == "1"

#: Sem `JWT_SECRET` não há sal para o hash do código. Nesse caso a autenticação
#: inteira já está desligada (`auth.ATIVA`), então o segundo fator também está —
#: o valor abaixo existe só para o módulo importar sem explodir nos testes.
_SAL = auth.JWT_SECRET or "acervo-dois-fatores-sem-segredo"


ESQUEMA = f"""
IF OBJECT_ID('{_TABELA}') IS NULL
CREATE TABLE {_TABELA} (
    id          char(36)      NOT NULL CONSTRAINT pk_acervo_login_desafios PRIMARY KEY,
    email       nvarchar(160) NOT NULL,
    codigo_hash char(64)      NOT NULL,
    criado_em   varchar(40)   NOT NULL,
    enviado_em  varchar(40)   NOT NULL,
    expira_em   varchar(40)   NOT NULL,
    tentativas  int           NOT NULL CONSTRAINT df_acervo_desafios_tentativas DEFAULT 0,
    envios      int           NOT NULL CONSTRAINT df_acervo_desafios_envios DEFAULT 1,
    consumido   bit           NOT NULL CONSTRAINT df_acervo_desafios_consumido DEFAULT 0
);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_acervo_login_desafios_email')
CREATE INDEX ix_acervo_login_desafios_email ON {_TABELA} (email);
"""


def inicializar() -> None:
    """Cria a tabela do desafio. Idempotente, chamada junto de `usuarios.inicializar`."""
    with conectar() as con:
        for lote in ESQUEMA.split(";\n"):
            if lote.strip():
                con.execute(lote)
        _apagar_vencidos(con)


ATIVO = correio.ATIVO
"""Se o segundo fator consegue funcionar. Depende só do SMTP: sem canal de
entrega, não há como mandar o código."""


def exigido_para(perfil: str) -> bool:
    """Se esta conta precisa do segundo passo.

    Com a autenticação desligada, ninguém precisa: não há token para emitir nem
    sessão para proteger, e exigir código no modo de depuração só inventaria um
    obstáculo sem nada do outro lado.
    """
    if not auth.ATIVA:
        return False
    return (perfil or "").strip().lower() not in ISENTOS


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _iso(momento: datetime) -> str:
    return momento.isoformat(timespec="seconds")


def _de_iso(texto: str) -> datetime:
    """Lê o instante gravado. Data ilegível conta como VENCIDA.

    O fallback devolve o passado distante em vez de levantar: uma linha corrompida
    tem de recusar o código, e não derrubar a rota de login inteira.
    """
    try:
        momento = datetime.fromisoformat((texto or "").strip())
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def _hash(desafio_id: str, codigo: str) -> str:
    """SHA-256 do código, salgado com o id do desafio e o segredo do servidor.

    O id entra no sal para dois desafios com o mesmo código não terem o mesmo
    hash — sem ele, quem lesse a tabela veria repetições e teria por onde começar.
    """
    return hashlib.sha256(f"{_SAL}:{desafio_id}:{codigo}".encode()).hexdigest()


def _apagar_vencidos(con: Any) -> None:
    """Varre os desafios mortos.

    Roda na inicialização e a cada desafio novo, em vez de num agendamento: é uma
    linha de DELETE contra uma tabela que nunca passa de algumas dezenas de
    registros, e um `celery beat` a mais para isso seria peça de manutenção sem
    retorno.
    """
    con.execute(f"DELETE FROM {_TABELA} WHERE expira_em < ? OR consumido = 1", (_iso(_agora()),))


def mascarar(email: str) -> str:
    """`fulano@escritorio.com` vira `fu****@escritorio.com`.

    A tela precisa dizer PARA ONDE o código foi — senão quem tem duas contas não
    sabe qual caixa abrir. Mostrar o endereço inteiro numa tela que ainda não
    exigiu o segundo fator entregaria o e-mail cadastrado a quem só tem a senha.
    """
    usuario, _, dominio = (email or "").partition("@")
    if not dominio:
        return "seu e-mail"
    visivel = usuario[:2] if len(usuario) > 3 else usuario[:1]
    return f"{visivel}{'*' * max(len(usuario) - len(visivel), 1)}@{dominio}"


def _gerar_codigo() -> str:
    """Seis dígitos sorteados criptograficamente.

    `secrets` e não `random`: o segundo é previsível a partir de saídas
    anteriores, o que aqui significaria adivinhar o código de outra pessoa.
    """
    return f"{secrets.randbelow(1_000_000):06d}"


def abrir_desafio(*, email: str, nome: str) -> dict[str, Any]:
    """Sorteia o código, grava o hash e manda o e-mail.

    Devolve o que a tela precisa: o identificador do desafio, o e-mail mascarado
    e quantos segundos ele ainda vale.

    O e-mail sai ANTES do commit? Não — grava primeiro e envia depois, e se o
    envio falhar o desafio é apagado. A ordem importa: código entregue sem linha
    no banco vira um código que nunca confere, que é o pior dos dois erros.
    """
    if not ATIVO:
        raise HTTPException(
            503,
            "O segundo fator está indisponível: o servidor de e-mail não está "
            "configurado. Procure quem administra o sistema.",
        )

    desafio_id = str(uuid.uuid4())
    codigo = _gerar_codigo()
    agora = _agora()
    expira = agora + timedelta(minutes=VALIDADE_MINUTOS)

    with conectar() as con:
        _apagar_vencidos(con)
        # Um desafio por conta: pedir código novo invalida o anterior. Dois
        # códigos válidos ao mesmo tempo dobrariam a superfície de adivinhação e
        # confundiriam quem recebeu os dois e-mails.
        con.execute(f"DELETE FROM {_TABELA} WHERE email = ?", (email.lower(),))
        con.execute(
            f"""INSERT INTO {_TABELA}
                    (id, email, codigo_hash, criado_em, enviado_em, expira_em,
                     tentativas, envios, consumido)
                VALUES (?, ?, ?, ?, ?, ?, 0, 1, 0)""",
            (
                desafio_id,
                email.lower(),
                _hash(desafio_id, codigo),
                _iso(agora),
                _iso(agora),
                _iso(expira),
            ),
        )

    try:
        _enviar(email=email, nome=nome, codigo=codigo)
    except correio.FalhaDeEnvio as erro:
        with conectar() as con:
            con.execute(f"DELETE FROM {_TABELA} WHERE id = ?", (desafio_id,))
        raise HTTPException(
            502,
            "Não foi possível enviar o código de acesso por e-mail. Tente de novo "
            "em instantes ou procure quem administra o sistema.",
        ) from erro

    log.info("segundo fator enviado para %s", mascarar(email))
    return {
        "desafio": desafio_id,
        "email": mascarar(email),
        "expira_em_segundos": VALIDADE_MINUTOS * 60,
        "reenviar_em_segundos": ESPERA_REENVIO_S,
    }


def reenviar(desafio_id: str) -> dict[str, Any]:
    """Sorteia um código NOVO para um desafio que já existe.

    Mantém o mesmo identificador para a tela não precisar trocar de estado no
    meio do fluxo, e mantém o contador de tentativas — ver o cabeçalho.
    """
    linha = _ler(desafio_id)
    if linha is None:
        raise HTTPException(400, "Este pedido de acesso não vale mais. Entre novamente.")

    if linha["envios"] >= ENVIOS_MAXIMOS:
        raise HTTPException(
            429,
            "Limite de reenvios atingido. Entre novamente para começar um novo acesso.",
        )

    espera = ESPERA_REENVIO_S - (_agora() - _de_iso(linha["enviado_em"])).total_seconds()
    if espera > 0:
        raise HTTPException(429, f"Aguarde {int(espera) + 1}s para pedir outro código.")

    from . import usuarios

    # A conta é reconferida aqui, e não só na hora de confirmar o código: entre
    # os dois passos alguém pode tê-la desativado, e mandar mais um e-mail para
    # uma conta que não vai entrar é ruído que ainda por cima parece funcionar.
    pessoa = usuarios.por_email(linha["email"])
    if pessoa is None or not pessoa["ativo"]:
        with conectar() as con:
            con.execute(f"DELETE FROM {_TABELA} WHERE id = ?", (desafio_id,))
        raise HTTPException(400, "Este pedido de acesso não vale mais. Entre novamente.")

    codigo = _gerar_codigo()
    agora = _agora()
    with conectar() as con:
        con.execute(
            f"""UPDATE {_TABELA}
                   SET codigo_hash = ?, enviado_em = ?, expira_em = ?, envios = envios + 1
                 WHERE id = ?""",
            (
                _hash(desafio_id, codigo),
                _iso(agora),
                _iso(agora + timedelta(minutes=VALIDADE_MINUTOS)),
                desafio_id,
            ),
        )

    try:
        _enviar(email=linha["email"], nome=pessoa["nome"], codigo=codigo)
    except correio.FalhaDeEnvio as erro:
        raise HTTPException(
            502, "Não foi possível reenviar o código. Tente de novo em instantes."
        ) from erro

    return {
        "desafio": desafio_id,
        "email": mascarar(linha["email"]),
        "expira_em_segundos": VALIDADE_MINUTOS * 60,
        "reenviar_em_segundos": ESPERA_REENVIO_S,
    }


def conferir(desafio_id: str, codigo: str) -> str:
    """Confere o código e devolve o e-mail da conta. Consome o desafio.

    Consumir é o ponto: o mesmo código não entra duas vezes, então um código
    lido por cima do ombro (ou deixado na caixa de e-mail) morre no primeiro uso.
    """
    linha = _ler(desafio_id)
    if linha is None:
        raise HTTPException(
            400, "Este código não vale mais — ele expirou ou já foi usado. Entre novamente."
        )

    if linha["tentativas"] >= TENTATIVAS_MAXIMAS:
        with conectar() as con:
            con.execute(f"DELETE FROM {_TABELA} WHERE id = ?", (desafio_id,))
        raise HTTPException(429, "Código errado vezes demais. Entre novamente.")

    informado = (codigo or "").strip()
    # `compare_digest` e não `==`: a comparação comum para no primeiro byte
    # diferente, e o tempo que ela leva conta ao atacante quantos dígitos ele já
    # acertou.
    if not secrets.compare_digest(_hash(desafio_id, informado), linha["codigo_hash"]):
        with conectar() as con:
            con.execute(
                f"UPDATE {_TABELA} SET tentativas = tentativas + 1 WHERE id = ?",
                (desafio_id,),
            )
        restantes = TENTATIVAS_MAXIMAS - linha["tentativas"] - 1
        log.warning("segundo fator recusado para %s", mascarar(linha["email"]))
        if restantes <= 0:
            raise HTTPException(429, "Código errado vezes demais. Entre novamente.")
        raise HTTPException(401, f"Código incorreto. Restam {restantes} tentativas.")

    with conectar() as con:
        con.execute(f"DELETE FROM {_TABELA} WHERE id = ?", (desafio_id,))
    return str(linha["email"])


def _ler(desafio_id: str) -> dict[str, Any] | None:
    """O desafio vivo. `None` quando não existe, venceu ou já foi consumido."""
    identificador = (desafio_id or "").strip()
    if not identificador:
        return None

    with conectar() as con:
        linha = con.execute(
            f"""SELECT id, email, codigo_hash, criado_em, enviado_em, expira_em,
                       tentativas, envios
                  FROM {_TABELA}
                 WHERE id = ? AND consumido = 0""",
            (identificador,),
        ).fetchone()

    if linha is None:
        return None

    # A comparação de validade é feita em Python e não no SQL de propósito: a
    # coluna é `varchar` (o padrão de data deste banco, ver `app/banco.py`), e
    # comparar texto com texto depende de os dois lados terem exatamente o mesmo
    # formato. Aqui o `datetime` decide.
    if _de_iso(str(linha["expira_em"])) <= _agora():
        with conectar() as con:
            con.execute(f"DELETE FROM {_TABELA} WHERE id = ?", (identificador,))
        return None

    return {
        "id": str(linha["id"]),
        "email": str(linha["email"]),
        "codigo_hash": str(linha["codigo_hash"]).strip(),
        "enviado_em": str(linha["enviado_em"]),
        "tentativas": int(linha["tentativas"]),
        "envios": int(linha["envios"]),
    }


def _enviar(*, email: str, nome: str, codigo: str) -> None:
    """A mensagem com o código.

    Curta e sem link. Um botão "confirmar acesso" no e-mail treinaria a equipe a
    clicar em botão de e-mail para entrar no sistema — que é exatamente o hábito
    de que uma campanha de phishing precisa.
    """
    primeiro_nome = (nome or "").split(" ")[0] or "Olá"
    minutos = VALIDADE_MINUTOS

    texto = (
        f"{primeiro_nome},\n\n"
        f"Seu código de acesso ao Acervo é: {codigo}\n\n"
        f"Ele vale por {minutos} minutos e serve uma única vez.\n\n"
        "Se não foi você que tentou entrar, alguém pode ter a sua senha. "
        "Troque-a assim que puder e avise quem administra o sistema.\n\n"
        "Esta mensagem é automática — não responda."
    )

    html = f"""
    <div style="font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif;
                color:#20334a;line-height:1.6;max-width:520px">
      <p>{primeiro_nome},</p>
      <p>Seu código de acesso ao <strong>Acervo</strong> é:</p>
      <p style="font-size:32px;font-weight:700;letter-spacing:6px;
                color:#102033;margin:24px 0">{codigo}</p>
      <p>Ele vale por <strong>{minutos} minutos</strong> e serve uma única vez.</p>
      <p style="color:#65758a;font-size:14px">
        Se não foi você que tentou entrar, alguém pode ter a sua senha.
        Troque-a assim que puder e avise quem administra o sistema.
      </p>
      <p style="color:#8fa1b5;font-size:12px">Esta mensagem é automática — não responda.</p>
    </div>
    """

    correio.enviar(
        para=email,
        assunto=f"{codigo} é o seu código de acesso ao Acervo",
        texto=texto,
        html=html,
    )


def configuracao_publica() -> dict[str, Any]:
    """O que a tela sabe sobre o segundo fator antes de alguém entrar.

    Nada por conta: só que ele existe e quanto tempo o código vale. Dizer QUAIS
    perfis passam por ele contaria o desenho de acesso do escritório a quem
    ainda nem se identificou.
    """
    return {
        "ativo": ATIVO,
        "validade_minutos": VALIDADE_MINUTOS,
        "reenviar_em_segundos": ESPERA_REENVIO_S,
    }
