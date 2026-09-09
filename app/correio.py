"""Envio de e-mail pelo SMTP do escritório.

POR QUE ISTO NASCEU AGORA

O sistema nunca precisou mandar e-mail: o Keycloak saiu levando junto o
"esqueci a senha", e o convite de assinatura quem manda é a ZapSign, do lado
dela. O que trouxe o SMTP para cá foi o segundo fator do login
(`app/dois_fatores.py`), que precisa entregar um código de seis dígitos a quem
está entrando.

O QUE ESTE MÓDULO NÃO É

Não é fila. `smtplib` é bloqueante e o envio acontece dentro da requisição de
login, com prazo curto (`SMTP_TIMEOUT`). Isso basta para uma mensagem por
tentativa de acesso num escritório e evita trazer Celery para o caminho da
porta de entrada — mas quer dizer que um servidor SMTP lento aparece como login
lento. Se um dia o volume mudar, o lugar de arrumar é aqui, e não em quem chama.

SEM CONFIGURAÇÃO, DESLIGADO

`SMTP_HOST` vazio deixa `ATIVO` em `False` e `enviar()` levanta. Quem depende do
envio (o segundo fator) consulta `ATIVO` ANTES de prometer ao usuário que o
código foi mandado — mandar a tela pedir um código que nunca vai chegar é pior
que recusar o login com uma mensagem clara.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from . import ambiente

log = logging.getLogger("correio")

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


def _env(nome: str, padrao: str = "") -> str:
    return (os.getenv(nome, padrao) or "").strip()


SMTP_HOST = _env("SMTP_HOST")
SMTP_PORTA = int(_env("SMTP_PORTA", "587") or 587)
SMTP_USUARIO = _env("SMTP_USUARIO")
SMTP_SENHA = os.getenv("SMTP_SENHA", "")  # sem strip: senha pode terminar em espaço

#: `starttls` (587), `ssl` (465) ou `nenhuma` (25, rede interna). O padrão é o
#: caminho do Gmail/Office365, que é o que um escritório costuma ter à mão.
SMTP_SEGURANCA = (_env("SMTP_SEGURANCA", "starttls") or "starttls").lower()

#: De quem a mensagem parece vir. Sem isto, cai no usuário da conta SMTP — que
#: funciona, mas mostra ao destinatário o endereço técnico em vez do do
#: escritório.
SMTP_REMETENTE = _env("SMTP_REMETENTE") or SMTP_USUARIO
SMTP_REMETENTE_NOME = _env("SMTP_REMETENTE_NOME", "Acervo — Escritório jurídico")

#: Curto de propósito. O envio roda dentro do login: um SMTP que demora trinta
#: segundos precisa virar erro, e não fazer a pessoa olhar para um botão girando.
SMTP_TIMEOUT = float(_env("SMTP_TIMEOUT", "10") or 10)

ATIVO = bool(SMTP_HOST and SMTP_REMETENTE)


class FalhaDeEnvio(RuntimeError):
    """O e-mail não saiu. Quem chama decide o que dizer ao usuário."""


def enviar(*, para: str, assunto: str, texto: str, html: str = "") -> None:
    """Manda uma mensagem. Levanta `FalhaDeEnvio` quando não sai.

    O corpo vai em texto SEMPRE, e em HTML só quando informado. Cliente de
    e-mail corporativo com HTML bloqueado é comum, e um código de acesso que só
    existe na parte HTML simplesmente não chega para quem está nessa situação.
    """
    if not ATIVO:
        raise FalhaDeEnvio(
            "Envio de e-mail não configurado: falta SMTP_HOST (e SMTP_REMETENTE) no .env."
        )

    mensagem = EmailMessage()
    mensagem["From"] = formataddr((SMTP_REMETENTE_NOME, SMTP_REMETENTE))
    mensagem["To"] = para
    mensagem["Subject"] = assunto
    mensagem.set_content(texto)
    if html:
        mensagem.add_alternative(html, subtype="html")

    try:
        if SMTP_SEGURANCA == "ssl":
            contexto = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                SMTP_HOST, SMTP_PORTA, timeout=SMTP_TIMEOUT, context=contexto
            ) as servidor:
                _autenticar(servidor)
                servidor.send_message(mensagem)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORTA, timeout=SMTP_TIMEOUT) as servidor:
                if SMTP_SEGURANCA == "starttls":
                    servidor.starttls(context=ssl.create_default_context())
                _autenticar(servidor)
                servidor.send_message(mensagem)
    except Exception as erro:  # smtplib levanta uma família inteira de exceções
        # O destinatário NÃO vai no log: e-mail de usuário é dado pessoal e o log
        # do servidor é lido por mais gente que o banco. O motivo basta para
        # depurar credencial errada, porta fechada ou TLS recusado.
        log.error("falha ao enviar e-mail (%s:%s): %s", SMTP_HOST, SMTP_PORTA, erro)
        raise FalhaDeEnvio(str(erro)) from erro


def _autenticar(servidor: smtplib.SMTP) -> None:
    """Faz login no SMTP quando há credencial.

    Relay interno costuma não pedir nenhuma — e chamar `login()` sem usuário
    derruba a conexão com um erro que parece de senha errada.
    """
    if SMTP_USUARIO:
        servidor.login(SMTP_USUARIO, SMTP_SENHA)


if not ATIVO:
    log.info(
        "SMTP não configurado: o segundo fator por e-mail fica indisponível "
        "(ver SMTP_HOST no .env.example)."
    )
