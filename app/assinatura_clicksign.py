"""Assinatura eletrônica pela Clicksign — conta do PRÓPRIO escritório-cliente.

Alternativa opcional ao ZapSign (padrão, `app/assinatura_navegador.py`). O
escritório entra em Configurações, cola o Access Token da conta Clicksign dele
(gerado em Configurações → API, na conta deles) e testa; o token fica cifrado no
banco (`app/assinatura_config.py`) e só é lido aqui, na hora de mandar. Sem token
testado com sucesso, o dispatcher (`app/assinatura_provedores.py`) nem chama este
módulo.

O FLUXO DA API v3 (JSON:API) — um envelope por documento

A Clicksign organiza o envio em "envelope": cria-se o envelope, sobe-se o
documento nele (PDF em base64), adiciona-se o signatário, liga-se um ao outro
("requirement" de assinatura) e por fim muda-se o status do envelope para
`running`, que dispara o convite por e-mail. Cinco chamadas em sequência; a
primeira falha interrompe as demais.

GRAU DE CERTEZA

Implementado a partir da documentação pública, sem conta real para calibrar (o
escritório é quem vai ter uma). O esquema de autenticação da v3 (nome do
cabeçalho e se leva prefixo `Bearer`) varia entre versões da documentação deles —
por isso é configurável por ambiente (`CLICKSIGN_AUTH_HEADER`, `CLICKSIGN_AUTH_PREFIX`),
do mesmo jeito que `app/assinatura_navegador.py` deixa os seletores de tela
configuráveis por env: se o primeiro teste real vier com 401, é ali que se ajusta,
sem precisar mexer no fluxo.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

import httpx

log = logging.getLogger("assinatura.clicksign")

TEMPO_LIMITE_S = 45.0


class ErroClicksign(Exception):
    """Falha que a tela precisa ver — token recusado, PDF grande demais…"""


def _env(nome: str, padrao: str = "") -> str:
    return (os.getenv(nome, padrao) or "").strip()


def base_url() -> str:
    return _env("CLICKSIGN_BASE_URL", "https://api.clicksign.com/api/v3").rstrip("/")


def _cabecalhos(token: str) -> dict[str, str]:
    nome = _env("CLICKSIGN_AUTH_HEADER", "Authorization")
    prefixo = _env("CLICKSIGN_AUTH_PREFIX", "Bearer")
    valor = f"{prefixo} {token}".strip() if prefixo else token
    return {nome: valor, "Content-Type": "application/vnd.api+json", "Accept": "application/vnd.api+json"}


async def _pedir(
    metodo: str,
    caminho: str,
    token: str,
    corpo: dict[str, Any] | None = None,
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    url = f"{base_url()}{caminho}"
    cabecalhos = _cabecalhos(token)

    async def executar(cliente: httpx.AsyncClient) -> httpx.Response:
        return await cliente.request(metodo, url, headers=cabecalhos, json=corpo)

    try:
        if http is not None:
            resposta = await executar(http)
        else:
            async with httpx.AsyncClient(timeout=TEMPO_LIMITE_S) as cliente:
                resposta = await executar(cliente)
    except httpx.HTTPError as exc:
        log.warning("Clicksign inacessível em %s %s: %s", metodo, caminho, str(exc)[:160])
        raise ErroClicksign("A Clicksign não respondeu. Tente de novo em instantes.") from exc

    if resposta.status_code in (401, 403):
        raise ErroClicksign("A Clicksign recusou o token — confira o valor colado nas configurações.")
    if resposta.status_code >= 400:
        detalhe = ""
        try:
            corpo_erro = resposta.json()
            partes = [
                str((e or {}).get("detail") or (e or {}).get("title") or e)
                for e in (corpo_erro.get("errors") or [])
            ]
            detalhe = "; ".join(p for p in partes if p)[:300]
        except Exception:  # noqa: BLE001
            detalhe = resposta.text[:200].strip()
        raise ErroClicksign(f"A Clicksign recusou o pedido: {detalhe or f'HTTP {resposta.status_code}'}")

    if not resposta.content:
        return {}
    try:
        return resposta.json()
    except Exception as exc:
        raise ErroClicksign("Resposta ilegível da Clicksign.") from exc


async def testar(token: str, http: httpx.AsyncClient | None = None) -> tuple[bool, str]:
    """"Testar conexão": lista envelopes (página mínima) — só passa com token válido."""
    token = (token or "").strip()
    if not token:
        return False, "Cole o token antes de testar."
    try:
        await _pedir("GET", "/envelopes?page[size]=1", token, http=http)
    except ErroClicksign as exc:
        return False, str(exc)
    return True, "Conexão com a Clicksign confirmada."


async def enviar(
    token: str,
    nome_documento: str,
    pdf: bytes,
    cliente_nome: str,
    cliente_email: str,
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Cria o envelope, sobe o PDF, adiciona o signatário e dispara o envio.

    Nunca levanta — devolve `{"ok", "link", "erro"}`, no mesmo formato que
    `assinatura_navegador.enviar_para_assinatura` devolve para o ZapSign, para o
    dispatcher (`assinatura_provedores.py`) tratar os provedores sem `if`
    espalhado pelas rotas. `link` fica vazio quando a Clicksign manda o convite
    só por e-mail (não devolve link de assinatura direto nesse modo) — o envio em
    si já saiu, e é isso que `ok=True` confirma.
    """
    if not pdf:
        return {"ok": False, "link": "", "erro": "Documento vazio — nada a enviar."}
    cliente_email = cliente_email.strip()
    if not cliente_email:
        return {"ok": False, "link": "", "erro": "A Clicksign exige e-mail do signatário."}

    async def criar(cliente: httpx.AsyncClient) -> dict[str, Any]:
        envelope = await _pedir(
            "POST",
            "/envelopes",
            token,
            {"data": {"type": "envelopes", "attributes": {"name": nome_documento, "locale": "pt-BR"}}},
            http=cliente,
        )
        envelope_id = str((envelope.get("data") or {}).get("id") or "")
        if not envelope_id:
            raise ErroClicksign("A Clicksign não devolveu o envelope criado.")

        documento = await _pedir(
            "POST",
            f"/envelopes/{envelope_id}/documents",
            token,
            {
                "data": {
                    "type": "documents",
                    "attributes": {
                        "filename": f"{nome_documento}.pdf".replace("/", "-"),
                        "content_base64": f"data:application/pdf;base64,{base64.b64encode(pdf).decode('ascii')}",
                    },
                }
            },
            http=cliente,
        )
        documento_id = str((documento.get("data") or {}).get("id") or "")
        if not documento_id:
            raise ErroClicksign("A Clicksign não devolveu o documento enviado.")

        signatario = await _pedir(
            "POST",
            f"/envelopes/{envelope_id}/signers",
            token,
            {
                "data": {
                    "type": "signers",
                    "attributes": {
                        "name": cliente_nome or "Cliente",
                        "email": cliente_email,
                        "has_documentation": False,
                        "communicate_events": {
                            "document_signed": "email",
                            "signature_request": "email",
                            "document_refused": "email",
                        },
                    },
                }
            },
            http=cliente,
        )
        signer_id = str((signatario.get("data") or {}).get("id") or "")
        if not signer_id:
            raise ErroClicksign("A Clicksign não devolveu o signatário criado.")

        await _pedir(
            "POST",
            f"/envelopes/{envelope_id}/requirements",
            token,
            {
                "data": {
                    "type": "requirements",
                    "attributes": {"action": "agree", "role": "sign"},
                    "relationships": {
                        "document": {"data": {"type": "documents", "id": documento_id}},
                        "signer": {"data": {"type": "signers", "id": signer_id}},
                    },
                }
            },
            http=cliente,
        )

        await _pedir(
            "PATCH",
            f"/envelopes/{envelope_id}",
            token,
            {"data": {"id": envelope_id, "type": "envelopes", "attributes": {"status": "running"}}},
            http=cliente,
        )

        link = ((signatario.get("data") or {}).get("attributes") or {}).get("sign_url") or ""
        return {"ok": True, "link": link, "erro": ""}

    try:
        if http is not None:
            return await criar(http)
        async with httpx.AsyncClient(timeout=TEMPO_LIMITE_S) as cliente:
            return await criar(cliente)
    except ErroClicksign as exc:
        return {"ok": False, "link": "", "erro": str(exc)}
