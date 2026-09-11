"""Assinatura eletrônica pela Autentique — conta do PRÓPRIO escritório-cliente.

Alternativa opcional ao ZapSign (padrão, `app/assinatura_navegador.py`). O
escritório entra em Configurações, cola o token da conta Autentique dele e testa;
o token fica cifrado no banco (`app/assinatura_config.py`) e só é lido aqui, na hora
de mandar. Sem token testado com sucesso, o dispatcher (`app/assinatura_provedores.py`)
nem chama este módulo.

A API da Autentique é GraphQL (`https://api.autentique.com.br/v2/graphql`), então
"criar documento com signatário e subir o PDF" é UMA chamada, com o arquivo indo por
`multipart/form-data` no formato da spec GraphQL-multipart (`operations` + `map` +
a parte do arquivo) — é como a documentação deles mostra o curl de exemplo.

GRAU DE CERTEZA

Implementado a partir da documentação pública, sem conta real para calibrar (o
escritório é quem vai ter uma — ver a conversa que originou este módulo). Se o
primeiro teste real devolver campo/nome diferente do que está aqui, é questão de
ajustar a mutation e a query de teste; a estrutura (cifra do token, teste antes de
ativar, nunca travar o envio por outra via) já está certa.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

log = logging.getLogger("assinatura.autentique")

TEMPO_LIMITE_S = 45.0


class ErroAutentique(Exception):
    """Falha que a tela precisa ver — token recusado, PDF grande demais…"""


def _env(nome: str, padrao: str = "") -> str:
    return (os.getenv(nome, padrao) or "").strip()


def base_url() -> str:
    return _env("AUTENTIQUE_BASE_URL", "https://api.autentique.com.br/v2/graphql").rstrip("/")


def _cabecalhos(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _pedir_graphql(
    token: str,
    query: str,
    variaveis: dict[str, Any],
    arquivo: tuple[str, bytes] | None = None,
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Uma chamada GraphQL, com ou sem arquivo anexo (spec `graphql-multipart-request`)."""

    async def executar(cliente: httpx.AsyncClient) -> httpx.Response:
        if arquivo is None:
            return await cliente.post(
                base_url(),
                headers={**_cabecalhos(token), "Content-Type": "application/json"},
                json={"query": query, "variables": variaveis},
            )
        nome_arquivo, conteudo = arquivo
        return await cliente.post(
            base_url(),
            headers=_cabecalhos(token),
            data={
                "operations": json.dumps({"query": query, "variables": variaveis}),
                "map": json.dumps({"0": ["variables.file"]}),
            },
            files={"0": (nome_arquivo, conteudo, "application/pdf")},
        )

    try:
        if http is not None:
            resposta = await executar(http)
        else:
            async with httpx.AsyncClient(timeout=TEMPO_LIMITE_S) as cliente:
                resposta = await executar(cliente)
    except httpx.HTTPError as exc:
        log.warning("Autentique inacessível: %s", str(exc)[:160])
        raise ErroAutentique("A Autentique não respondeu. Tente de novo em instantes.") from exc

    if resposta.status_code == 401 or resposta.status_code == 403:
        raise ErroAutentique("A Autentique recusou o token — confira o valor colado nas configurações.")
    if resposta.status_code >= 400:
        raise ErroAutentique(f"A Autentique recusou o pedido (HTTP {resposta.status_code}).")

    try:
        corpo = resposta.json()
    except Exception as exc:
        raise ErroAutentique("Resposta ilegível da Autentique.") from exc

    erros = corpo.get("errors")
    if erros:
        mensagem = "; ".join(str(e.get("message", e)) for e in erros)[:300]
        raise ErroAutentique(f"A Autentique recusou o pedido: {mensagem}")
    return corpo.get("data") or {}


async def testar(token: str, http: httpx.AsyncClient | None = None) -> tuple[bool, str]:
    """"Testar conexão": um GraphQL simples que só passa com token válido."""
    token = (token or "").strip()
    if not token:
        return False, "Cole o token antes de testar."
    try:
        dados = await _pedir_graphql(
            token, "query { documents(page: 1) { total } }", {}, http=http
        )
    except ErroAutentique as exc:
        return False, str(exc)
    total = ((dados.get("documents") or {}).get("total"))
    if total is None:
        return False, "A Autentique respondeu, mas de um jeito inesperado — confira o token."
    return True, "Conexão com a Autentique confirmada."


_MUTATION_CRIAR_DOCUMENTO = """
mutation CriarDocumento($document: DocumentInput!, $signers: [SignerInput!]!, $file: Upload!) {
  createDocument(document: $document, signers: $signers, file: $file) {
    id
    name
    signatures {
      public_id
      name
      email
      link { short_link }
    }
  }
}
"""


async def enviar(
    token: str,
    nome_documento: str,
    pdf: bytes,
    cliente_nome: str,
    cliente_email: str,
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Sobe o PDF e cria o documento com um signatário. Nunca levanta — ver o retorno.

    `{"ok", "link", "erro"}`, no mesmo formato que `assinatura_navegador.enviar_para_assinatura`
    devolve para o ZapSign — é o que permite o dispatcher (`assinatura_provedores.py`)
    tratar os provedores sem `if` espalhado pelas rotas.
    """
    if not pdf:
        return {"ok": False, "link": "", "erro": "Documento vazio — nada a enviar."}
    if not cliente_email.strip():
        return {"ok": False, "link": "", "erro": "A Autentique exige e-mail do signatário."}

    try:
        dados = await _pedir_graphql(
            token,
            _MUTATION_CRIAR_DOCUMENTO,
            {
                "document": {"name": nome_documento},
                "signers": [{"email": cliente_email.strip(), "action": "SIGN"}],
                "file": None,
            },
            arquivo=(f"{nome_documento}.pdf".replace("/", "-"), pdf),
            http=http,
        )
    except ErroAutentique as exc:
        return {"ok": False, "link": "", "erro": str(exc)}

    documento = dados.get("createDocument") or {}
    assinaturas = documento.get("signatures") or []
    achado = next(
        (s for s in assinaturas if (s.get("email") or "").strip().lower() == cliente_email.strip().lower()),
        (assinaturas[0] if assinaturas else {}),
    )
    link = ((achado.get("link") or {}).get("short_link")) or ""
    return {
        "ok": bool(documento.get("id")),
        "link": link,
        "erro": "" if documento.get("id") else "A Autentique não devolveu o documento criado.",
    }
