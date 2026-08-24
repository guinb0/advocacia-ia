"""Envio de mensagens operacionais pela Evolution API.

A chave nunca chega ao navegador. O frontend envia apenas o telefone e a
finalidade; texto e link oficiais permanecem definidos no servidor.
"""

from __future__ import annotations

import os
import re

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

roteador = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

LINK_AVALIACAO = os.getenv("GOOGLE_AVALIACAO_URL", "https://share.google/jejesXtEzd87GKxbU")
MENSAGEM_AVALIACAO = (
    "Obrigado por conversar conosco. Sua avaliação ajuda outras pessoas a "
    "encontrarem nosso trabalho. Se puder, avalie a LARA & MELO no Google: "
)


class Destinatario(BaseModel):
    telefone: str


def _numero_brasileiro(valor: str) -> str:
    numero = re.sub(r"\D", "", valor)
    if len(numero) in (10, 11):
        numero = "55" + numero
    if len(numero) not in (12, 13) or not numero.startswith("55"):
        raise HTTPException(422, "Informe um telefone brasileiro com DDD.")
    return numero


@roteador.post("/avaliacao-google")
async def enviar_avaliacao_google(dados: Destinatario) -> dict[str, bool]:
    base = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
    chave = os.getenv("EVOLUTION_API_KEY", "")
    instancia = os.getenv("EVOLUTION_INSTANCE", "")
    if not base or not chave or not instancia:
        raise HTTPException(503, "O envio por WhatsApp ainda não foi configurado.")

    try:
        async with httpx.AsyncClient(timeout=20) as cliente:
            resposta = await cliente.post(
                f"{base}/message/sendText/{instancia}",
                headers={"apikey": chave, "Content-Type": "application/json"},
                json={
                    "number": _numero_brasileiro(dados.telefone),
                    "text": MENSAGEM_AVALIACAO + LINK_AVALIACAO,
                },
            )
            resposta.raise_for_status()
    except httpx.HTTPError as erro:
        raise HTTPException(502, "A Evolution API não confirmou o envio da mensagem.") from erro
    return {"enviado": True}
