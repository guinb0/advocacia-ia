"""Escolhe qual provedor manda o documento à assinatura — ZapSign, Clicksign ou Autentique.

As rotas de envio (`app/main.py`) chamavam só `app/assinatura_navegador.py` (ZapSign
pelo site). Agora chamam este módulo, que olha `app/assinatura_config.provedor_ativo()`
e decide:

- `zapsign` (padrão, sempre disponível quando há login no `.env`) → continua indo
  para `assinatura_navegador`, sem NENHUMA mudança de comportamento.
- `clicksign` / `autentique` → só é usado se o escritório configurou E testou o
  token com sucesso (`assinatura_config.esta_pronto`). Caso contrário, cai de volta
  para a ZapSign — o sistema nunca fica sem caminho de envio por causa de uma
  integração nova mal configurada.

Isto é o único lugar que sabe que existem três provedores; as rotas continuam
chamando `enviar_um` / `enviar_varios` e recebendo `{"ok", "link"/"documentos", "erro"}`,
como sempre receberam da ZapSign.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from starlette.concurrency import run_in_threadpool

from . import assinatura_autentique, assinatura_clicksign, assinatura_config, assinatura_navegador

log = logging.getLogger("assinatura.provedores")

_ADAPTADORES = {
    "clicksign": assinatura_clicksign,
    "autentique": assinatura_autentique,
}


def _provedor_efetivo() -> str:
    """`provedor_ativo()`, mas rebaixado para `zapsign` se ele não estiver pronto.

    Ativar exige teste aprovado (`assinatura_config.ativar`), então isto só entra
    em jogo se o token passou a falhar DEPOIS de ativado — ex.: revogado do lado
    do provedor. Aí o envio cai para a ZapSign em vez de travar o escritório.
    """
    provedor = assinatura_config.provedor_ativo()
    if provedor == "zapsign":
        return "zapsign"
    if assinatura_config.esta_pronto(provedor):
        return provedor
    log.warning(
        "Provedor de assinatura %s está ativo mas sem token pronto; usando ZapSign.", provedor
    )
    return "zapsign"


def configurado() -> bool:
    """Há algum caminho de envio disponível AGORA, seja qual for o provedor?"""
    provedor = _provedor_efetivo()
    if provedor == "zapsign":
        return assinatura_navegador.configurado()
    return True


def mensagem_nao_configurado() -> str:
    provedor = _provedor_efetivo()
    if provedor == "zapsign":
        return (
            "O envio para assinatura não está configurado: falta o login "
            "(ZAPSIGN_LOGIN_EMAIL/ZAPSIGN_LOGIN_SENHA) no ambiente, ou configure "
            "Clicksign/Autentique em Configurações → Assinatura."
        )
    return f"O envio pela {provedor} não está configurado."


async def enviar_um(
    pdf: bytes,
    nome_arquivo: str,
    cliente_nome: str,
    cliente_email: str,
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Um documento. Formato de retorno igual ao de `assinatura_navegador.enviar_para_assinatura`."""
    provedor = _provedor_efetivo()
    if provedor == "zapsign":
        # Playwright é síncrono e bloqueante — roda em thread para não travar o
        # loop de eventos, do mesmo jeito que `app/main.py` sempre chamou isto.
        return await run_in_threadpool(
            assinatura_navegador.enviar_para_assinatura, pdf, nome_arquivo, cliente_nome, cliente_email
        )

    adaptador = _ADAPTADORES[provedor]
    token = assinatura_config.token_de(provedor)
    return await adaptador.enviar(token, nome_arquivo, pdf, cliente_nome, cliente_email, http=http)


async def enviar_varios(
    documentos: list[dict[str, Any]],
    cliente_nome: str,
    cliente_email: str,
) -> dict[str, Any]:
    """Vários documentos. Formato de retorno igual ao de `enviar_varios_para_assinatura`.

    Na ZapSign os três sobem numa sessão de navegador só (o login é caro). Nos
    provedores por API não há sessão para reaproveitar — cada chamada já é uma
    requisição HTTP independente —, então aqui é só um laço, com o mesmo cliente
    HTTP para as três, para não abrir conexão nova a cada documento.
    """
    provedor = _provedor_efetivo()
    if provedor == "zapsign":
        return await run_in_threadpool(
            assinatura_navegador.enviar_varios_para_assinatura, documentos, cliente_nome, cliente_email
        )

    adaptador = _ADAPTADORES[provedor]
    token = assinatura_config.token_de(provedor)
    resultados: list[dict[str, str]] = []
    erro_geral = ""
    async with httpx.AsyncClient(timeout=45.0) as cliente:
        for doc in documentos:
            nome = str(doc.get("nome") or "documento.pdf")
            r = await adaptador.enviar(
                token, nome, bytes(doc["pdf"]), cliente_nome, cliente_email, http=cliente
            )
            resultados.append(
                {"rotulo": str(doc.get("rotulo") or nome), "nome": nome, "link": r.get("link", "")}
            )
            if not r.get("ok") and not erro_geral:
                erro_geral = str(r.get("erro") or f"Falha ao enviar {nome}.")

    return {
        "ok": not erro_geral,
        "documentos": resultados,
        "erro": erro_geral,
        "screenshot": "",
        "url_final": "",
    }
