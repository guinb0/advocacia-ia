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
import hashlib
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app import armazenamento, auth, automacoes_whatsapp, casos

roteador = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

LINK_AVALIACAO = os.getenv("GOOGLE_AVALIACAO_URL", "https://share.google/BrQVYGnjqdSz3pEw7")
URL_PORTAL = os.getenv("URL_PORTAL", "http://localhost:3000").rstrip("/")
MENSAGEM_AVALIACAO = (
    "Obrigado por conversar conosco. Sua avaliação ajuda outras pessoas a "
    "encontrarem nosso trabalho. Se puder, avalie a LARA & MELO no Google: "
)
log = logging.getLogger("whatsapp")


class Destinatario(BaseModel):
    telefone: str


class PedidoLinkAssinatura(BaseModel):
    assinatura_id: str
    signatario_token: str


class ConfiguracaoCobranca(BaseModel):
    ativa: bool = False
    telefone: str = ""
    intervalo_dias: int = Field(default=3, ge=1, le=30)
    incluir_opcionais: bool = False


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


def _enviar_texto_sync(numero: str, texto: str) -> None:
    """Versão síncrona para o worker periódico do Celery."""
    if not configurado():
        raise RuntimeError("O envio por WhatsApp ainda não foi configurado.")
    base = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
    try:
        resposta = httpx.post(
            f"{base}/message/sendText/{os.getenv('EVOLUTION_INSTANCE', '')}",
            headers={"apikey": os.getenv("EVOLUTION_API_KEY", ""), "Content-Type": "application/json"},
            json={"number": numero, "text": texto}, timeout=20,
        )
        resposta.raise_for_status()
    except httpx.HTTPError as erro:
        raise RuntimeError("A Evolution API não confirmou o envio da mensagem.") from erro


@roteador.post("/avaliacao-google")
async def enviar_avaliacao_google(dados: Destinatario) -> dict[str, bool]:
    numero = _numero_brasileiro(dados.telefone)
    chave = f"avaliacao-google:{numero}"
    reservado = await run_in_threadpool(
        automacoes_whatsapp.reservar, chave, "avaliacao_google", numero, None
    )
    if not reservado:
        return {"enviado": False, "ja_enviado": True}
    try:
        await _enviar_texto(numero, MENSAGEM_AVALIACAO + LINK_AVALIACAO)
    except Exception as erro:
        await run_in_threadpool(automacoes_whatsapp.finalizar, chave, str(erro))
        raise
    await run_in_threadpool(automacoes_whatsapp.finalizar, chave)
    return {"enviado": True, "ja_enviado": False}


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


async def enviar_links_assinatura_automaticos(registro: dict[str, Any]) -> int:
    """Envia cada link individual assim que o envelope é persistido.

    Signatários do escritório ficam fora: a automação é para o cliente e demais
    partes externas. Uma falha no WhatsApp nunca invalida o documento já criado
    na ZapSign; ela fica registrada e pode ser tentada novamente.
    """
    enviados = 0
    for signatario in registro.get("signatarios") or []:
        if str(signatario.get("papel", "")).lower() == "escritório":
            continue
        telefone = str(signatario.get("telefone") or "").strip()
        url = str(signatario.get("url_assinatura") or "").strip()
        token = str(signatario.get("token") or "").strip()
        if not telefone or not url or not token:
            continue
        numero = _numero_brasileiro(telefone)
        chave = f"zapsign:{registro['id']}:{token}"
        if not await run_in_threadpool(
            automacoes_whatsapp.reservar, chave, "zapsign", numero, registro.get("caso_id")
        ):
            continue
        texto = (
            f"Olá, {_primeiro_nome(str(signatario.get('nome', '')))}. Aqui é a LARA & MELO. "
            f"Para assinar {_rotulo_do_documento(str(registro.get('nome', '')))}, "
            f"é só abrir este link — dá para assinar pelo próprio celular: {url}"
        )
        try:
            await _enviar_texto(numero, texto)
        except Exception as erro:  # o envelope ZapSign já existe e continua válido
            await run_in_threadpool(automacoes_whatsapp.finalizar, chave, str(erro))
            log.exception("Falha no envio automático do link %s", chave)
            continue
        await run_in_threadpool(automacoes_whatsapp.finalizar, chave)
        enviados += 1
    return enviados


@roteador.get("/casos/{caso_id}/cobranca-documentos", dependencies=[Depends(auth.usuario_atual)])
async def obter_cobranca_documentos(caso_id: str) -> dict[str, Any]:
    if not await run_in_threadpool(automacoes_whatsapp.caso_existe, caso_id):
        raise HTTPException(404, "Caso não encontrado.")
    return await run_in_threadpool(automacoes_whatsapp.obter_cobranca, caso_id)


@roteador.put("/casos/{caso_id}/cobranca-documentos", dependencies=[Depends(auth.usuario_atual)])
async def configurar_cobranca_documentos(
    caso_id: str, dados: ConfiguracaoCobranca,
) -> dict[str, Any]:
    if not await run_in_threadpool(automacoes_whatsapp.caso_existe, caso_id):
        raise HTTPException(404, "Caso não encontrado.")
    telefone = _numero_brasileiro(dados.telefone) if dados.ativa else (
        _numero_brasileiro(dados.telefone) if dados.telefone.strip() else ""
    )
    return await run_in_threadpool(
        automacoes_whatsapp.salvar_cobranca, caso_id, ativa=dados.ativa,
        telefone=telefone, intervalo_dias=dados.intervalo_dias,
        incluir_opcionais=dados.incluir_opcionais,
    )


def processar_cobrancas_documentos() -> int:
    """Envia cobranças vencidas sempre com o checklist mais recente."""
    enviados = 0
    for config in automacoes_whatsapp.listar_cobrancas_vencidas():
        caso = armazenamento.obter_caso_com_segredos(config["caso_id"])
        token_portal = str((caso or {}).get("portal_token") or "").strip()
        if not token_portal:
            automacoes_whatsapp.registrar_resultado_cobranca(
                config["caso_id"], config["intervalo_dias"], None,
                "O caso não possui link ativo para o portal do cliente.",
            )
            continue
        pedido = casos.montar_pedido(config["caso_id"], config["incluir_opcionais"])
        if not pedido:
            automacoes_whatsapp.registrar_resultado_cobranca(
                config["caso_id"], config["intervalo_dias"], None, "Caso ou categoria não encontrado."
            )
            continue
        pendentes = pedido["faltando_obrigatorios"] or pedido["reenviar"]
        if config["incluir_opcionais"]:
            pendentes = pendentes or pedido["faltando_opcionais"]
        if not pendentes:
            # Não cobra quem já concluiu. O agendamento fica para uma eventual
            # nova pendência, mas nenhuma mensagem de cobrança é enviada.
            automacoes_whatsapp.registrar_resultado_cobranca(
                config["caso_id"], config["intervalo_dias"], None
            )
            continue
        texto = (
            f"{pedido['texto']}\n\n"
            "Envie os documentos com segurança pelo seu portal:\n"
            f"{URL_PORTAL}/portal/{token_portal}"
        )
        texto_hash = hashlib.sha256(texto.encode("utf-8")).hexdigest()
        try:
            _enviar_texto_sync(config["telefone"], texto)
        except Exception as erro:  # próxima execução volta a tentar
            automacoes_whatsapp.registrar_resultado_cobranca(
                config["caso_id"], config["intervalo_dias"], texto_hash, str(erro)
            )
            continue
        automacoes_whatsapp.registrar_resultado_cobranca(
            config["caso_id"], config["intervalo_dias"], texto_hash
        )
        enviados += 1
    return enviados
