"""Cloudflare Turnstile na porta de entrada.

O QUE ELE RESOLVE, E O QUE NÃO RESOLVE

Resolve robô: enquanto não havia nada aqui, `POST /api/user/authenticate` aceitava
quantas tentativas por segundo alguém quisesse mandar, e a senha do sistema é MD5
sem sal (ver o cabeçalho de `app/usuarios.py`) — a combinação convida a força
bruta. O Turnstile faz o navegador provar que é navegador antes de a senha ser
sequer conferida.

NÃO resolve alguém que já tenha a senha, e não substitui o segundo fator
(`app/dois_fatores.py`). São camadas diferentes: o captcha filtra QUEM bate na
porta, o segundo fator confirma QUEM está entrando.

POR QUE TURNSTILE E NÃO reCAPTCHA

É gratuito sem teto, quase sempre invisível (sem "clique nos semáforos"), e não
manda o comportamento de navegação do usuário para a rede de publicidade do
Google — o que num sistema que guarda documento de cliente de escritório é
diferença que interessa, não preferência de gosto.

A CHAVE PÚBLICA VAI PELO `/api/config`, E NÃO POR `NEXT_PUBLIC_*`

A `site key` é pública por definição — o navegador precisa dela. Ainda assim ela
não vira variável embutida no bundle: o `.env.example` já registra o estrago que
`NEXT_PUBLIC_*` fez quando o sistema foi aberto de outro computador. Servida pelo
`/api/config`, ela acompanha o servidor que respondeu.

SEM CHAVE, DESLIGADO

`TURNSTILE_SECRET_KEY` vazio deixa `ATIVO` em `False` e `verificar()` passa
direto — é o mesmo desenho do `JWT_SECRET`, para o projeto continuar subindo em
máquina de desenvolvimento sem conta na Cloudflare. O log avisa.
"""

from __future__ import annotations

import logging
import os

from fastapi import HTTPException

from . import ambiente

log = logging.getLogger("captcha")

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


VERIFICACAO_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def _env(nome: str, padrao: str = "") -> str:
    return (os.getenv(nome, padrao) or "").strip()


#: Vai para o navegador (ver `auth.configuracao_publica`). Não é segredo.
SITE_KEY = _env("TURNSTILE_SITE_KEY")

#: Fica só aqui. Quem tiver esta chave consegue validar tokens em nome do site.
SECRET_KEY = _env("TURNSTILE_SECRET_KEY")

#: Curto: é uma chamada à Cloudflare no meio do login. Se ela não responde em
#: cinco segundos, o certo é decidir sem ela — ver `FALHA_ABERTA`.
TIMEOUT = float(_env("TURNSTILE_TIMEOUT", "5") or 5)

#: O que fazer quando a Cloudflare está fora do ar ou inalcançável.
#:
#: `1` (padrão) deixa passar: uma indisponibilidade de terceiro não pode trancar
#: o escritório inteiro para fora do próprio sistema, e a senha e o segundo fator
#: continuam valendo. `0` recusa — escolha de quem prefere ficar de fora a
#: aceitar uma tentativa não verificada.
FALHA_ABERTA = _env("TURNSTILE_FALHA_ABERTA", "1") != "0"

ATIVO = bool(SECRET_KEY)


if not ATIVO:
    log.warning(
        "CAPTCHA DESLIGADO: sem TURNSTILE_SECRET_KEY o login aceita tentativa "
        "automatizada sem nenhum filtro. Não suba assim em produção."
    )


def verificar(token: str, ip: str = "") -> None:
    """Confere o token do Turnstile. Levanta 400 quando não confere.

    O `ip` vai junto quando conhecido: é o que permite à Cloudflare recusar um
    token legítimo REUTILIZADO de outra máquina. Vazio, a verificação continua
    valendo — só perde essa checagem a mais.
    """
    if not ATIVO:
        return

    if not token:
        raise HTTPException(400, "Confirme que você não é um robô e tente novamente.")

    import httpx

    dados = {"secret": SECRET_KEY, "response": token}
    if ip:
        dados["remoteip"] = ip

    try:
        # Cliente SÍNCRONO de propósito: a rota de login é `def`, e o FastAPI a
        # roda em threadpool justamente porque o pyodbc é bloqueante. Um
        # `AsyncClient` aqui obrigaria a rota a virar `async` e aí cada consulta
        # ao banco travaria o event loop inteiro — trocaria um problema por um pior.
        with httpx.Client(timeout=TIMEOUT) as cliente:
            resposta = cliente.post(VERIFICACAO_URL, data=dados)
            resposta.raise_for_status()
            corpo = resposta.json()
    except Exception as erro:
        log.error("Turnstile inalcançável: %s", erro)
        if FALHA_ABERTA:
            log.warning("verificação de captcha PULADA nesta tentativa (falha aberta)")
            return
        raise HTTPException(
            503, "A verificação de segurança está indisponível. Tente em instantes."
        ) from erro

    if corpo.get("success"):
        return

    codigos = corpo.get("error-codes") or []
    log.warning("captcha recusado: %s", ", ".join(str(c) for c in codigos) or "sem motivo")

    # `timeout-or-duplicate` é o caso comum e tem conserto do lado do usuário:
    # o token vale poucos minutos e só uma vez. Merece mensagem própria, senão a
    # pessoa relê a senha achando que errou nela.
    if "timeout-or-duplicate" in codigos:
        raise HTTPException(
            400, "A verificação de segurança expirou. Recarregue a página e tente de novo."
        )
    raise HTTPException(400, "Verificação de segurança não aprovada. Tente novamente.")


def configuracao_publica() -> dict[str, object]:
    """O que a tela precisa para desenhar (ou não) o widget."""
    return {"ativo": ATIVO, "site_key": SITE_KEY}
