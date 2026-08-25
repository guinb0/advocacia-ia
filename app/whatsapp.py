"""Envio de mensagens operacionais pela Evolution API.

A chave nunca chega ao navegador. O frontend envia apenas o telefone (ou o
identificador de um documento já registrado) e a finalidade; texto e link
oficiais permanecem definidos no servidor.

POR QUE O LINK DE ASSINATURA NÃO VEM DO NAVEGADOR

O envio do link de assinatura recebe `assinatura_id` e `signatario_token`, e vai
buscar a URL no registro do documento. Aceitar a URL pronta seria mais simples e
transformaria o WhatsApp do escritório num relay: qualquer um com acesso à tela
mandaria qualquer link, em nome da LARA & MELO, para qualquer número. O mesmo
vale para o telefone — ele sai do signatário registrado, que é quem a entrevista
qualificou, e não de um campo que a tela pode ter editado depois.

UMA MENSAGEM POR DOCUMENTO

São três envelopes na ZapSign (contrato, procuração e declaração), cada um com
link próprio. Cada um sai numa mensagem separada, nomeando o documento: três
links soltos numa mensagem só o cliente clica no primeiro e acha que acabou.
"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app import armazenamento, auth

roteador = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

LINK_AVALIACAO = os.getenv("GOOGLE_AVALIACAO_URL", "https://share.google/BrQVYGnjqdSz3pEw7")
MENSAGEM_AVALIACAO = (
    "Obrigado por conversar conosco. Sua avaliação ajuda outras pessoas a "
    "encontrarem nosso trabalho. Se puder, avalie a LARA & MELO no Google: "
)


class Destinatario(BaseModel):
    telefone: str


class PedidoLinkAssinatura(BaseModel):
    assinatura_id: str
    signatario_token: str


def _numero_brasileiro(valor: str) -> str:
    numero = re.sub(r"\D", "", valor)
    if len(numero) in (10, 11):
        numero = "55" + numero
    if len(numero) not in (12, 13) or not numero.startswith("55"):
        raise HTTPException(422, "Informe um telefone brasileiro com DDD.")
    return numero


def configurado() -> bool:
    """Há instância da Evolution pareada e apontada no `.env`?

    A tela pergunta antes de oferecer o botão. Sem isto o atendente clicaria e
    tomaria 503 no meio do atendimento — e o convite por e-mail da ZapSign, que
    sai de qualquer jeito, pareceria não ter saído.
    """
    return all(
        os.getenv(nome, "").strip()
        for nome in ("EVOLUTION_API_URL", "EVOLUTION_API_KEY", "EVOLUTION_INSTANCE")
    )


async def _enviar_texto(numero: str, texto: str) -> None:
    """Uma mensagem de texto pela instância do escritório.

    Erro de configuração é 503 (falta ligar), erro da Evolution é 502 (ligado,
    mas não confirmou) — são ações diferentes: uma é mexer no `.env`, a outra é
    conferir se o celular ainda está pareado.
    """
    if not configurado():
        raise HTTPException(503, "O envio por WhatsApp ainda não foi configurado.")
    base = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
    chave = os.getenv("EVOLUTION_API_KEY", "")
    instancia = os.getenv("EVOLUTION_INSTANCE", "")

    try:
        async with httpx.AsyncClient(timeout=20) as cliente:
            resposta = await cliente.post(
                f"{base}/message/sendText/{instancia}",
                headers={"apikey": chave, "Content-Type": "application/json"},
                json={"number": numero, "text": texto},
            )
            resposta.raise_for_status()
    except httpx.HTTPError as erro:
        raise HTTPException(502, "A Evolution API não confirmou o envio da mensagem.") from erro


@roteador.post("/avaliacao-google")
async def enviar_avaliacao_google(dados: Destinatario) -> dict[str, bool]:
    await _enviar_texto(_numero_brasileiro(dados.telefone), MENSAGEM_AVALIACAO + LINK_AVALIACAO)
    return {"enviado": True}


def _primeiro_nome(nome: str) -> str:
    return (nome or "").strip().split(" ")[0] or "você"


def _rotulo_do_documento(nome_registrado: str) -> str:
    """"Procuração — Fulano de Tal" vira "a procuração".

    O nome guardado carrega o cliente para o advogado distinguir os documentos na
    lista. Repeti-lo para o próprio cliente ("assine Procuração — Fulano") soa a
    protocolo, não a mensagem de escritório.
    """
    rotulo = (nome_registrado or "").split("—")[0].strip()
    return rotulo.lower() if rotulo else "o documento"


def _localizar_signatario(registro: dict[str, Any], token: str) -> dict[str, Any]:
    for s in registro.get("signatarios") or []:
        if str(s.get("token", "")) == token:
            return s
    raise HTTPException(404, "Signatário não encontrado neste documento.")


@roteador.post("/link-assinatura", dependencies=[Depends(auth.usuario_atual)])
async def enviar_link_assinatura(dados: PedidoLinkAssinatura) -> dict[str, bool]:
    """Manda a UM signatário o link de assinatura de UM documento.

    Só o que o registro já sabe: o link que a ZapSign devolveu na criação e o
    telefone do signatário. Quem já assinou não recebe nada — reenviar link a
    quem assinou faz o cliente achar que a assinatura não valeu.
    """
    registro = await run_in_threadpool(armazenamento.obter_assinatura, dados.assinatura_id)
    if registro is None:
        raise HTTPException(404, "Documento não encontrado.")

    signatario = _localizar_signatario(registro, dados.signatario_token)
    if signatario.get("estado") == "assinou":
        raise HTTPException(409, f"{signatario.get('nome', 'O signatário')} já assinou.")

    url = str(signatario.get("url_assinatura") or "").strip()
    if not url:
        raise HTTPException(
            409,
            "Este documento não tem link individual guardado — use o convite que a "
            "ZapSign mandou por e-mail.",
        )

    telefone = str(signatario.get("telefone") or "").strip()
    if not telefone:
        raise HTTPException(422, f"{signatario.get('nome', 'O signatário')} não tem telefone.")

    texto = (
        f"Olá, {_primeiro_nome(str(signatario.get('nome', '')))}. Aqui é a LARA & MELO. "
        f"Para assinar {_rotulo_do_documento(str(registro.get('nome', '')))}, "
        f"é só abrir este link — dá para assinar pelo próprio celular: {url}"
    )
    await _enviar_texto(_numero_brasileiro(telefone), texto)
    return {"enviado": True}
