"""Cifra do token de provedor e os adaptadores Clicksign/Autentique.

Nada aqui bate nas APIs de verdade: o transporte é falso (`httpx.MockTransport`),
como em `tests/test_assinatura.py`. Ninguém tem conta Clicksign/Autentique própria
para calibrar contra — o escritório-cliente é quem vai ter (ver o cabeçalho de
`app/assinatura_clicksign.py` e `app/assinatura_autentique.py`) —, então o que se
cobre é a FORMA do pedido (token no cabeçalho certo, PDF inteiro, e-mail exigido) e
a tradução de erro em `{"ok": False, "erro": ...}`, nunca uma exceção não tratada
estourando a rota.

A tabela do banco (`app/assinatura_config.py`) não é exercitada aqui: ela precisa
de conexão SQL Server, e este arquivo é sobre o que roda sem rede nem banco. A
persistência tem a mesma cobertura manual que o resto do projeto já usa para
tabelas novas (ver `tests/test_login_dois_fatores.py`).

Rodar: .venv\\Scripts\\python.exe -m tests.test_assinatura_provedores
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx

from app import assinatura_autentique, assinatura_clicksign, cripto


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


# --------------------------------------------------------------------- cripto


def testar_cripto() -> int:
    """`CRIPTO_SECRET`, não `JWT_SECRET`: este é lido do ambiente a cada chamada
    (ver `app/cripto.py`); `auth.JWT_SECRET` já foi fixado na importação do
    processo, antes deste teste rodar, e mudar `os.environ` agora não o alcança.
    """
    falhas = 0
    velho = os.environ.get("CRIPTO_SECRET")
    os.environ["CRIPTO_SECRET"] = "segredo-de-teste-nao-usar-em-producao"

    try:
        cifrado = cripto.cifrar("token-super-secreto-do-escritorio")
        falhas += not checar(
            "token-super-secreto" not in cifrado, "o valor cifrado não contém o texto original"
        )
        falhas += not checar(
            cripto.decifrar(cifrado) == "token-super-secreto-do-escritorio",
            "decifrar devolve exatamente o que foi cifrado",
        )

        os.environ["CRIPTO_SECRET"] = "outra-chave-completamente-diferente"
        try:
            cripto.decifrar(cifrado)
            falhas += not checar(False, "trocar a chave invalida o cifrado antigo")
        except cripto.ErroCripto:
            falhas += not checar(True, "trocar a chave invalida o cifrado antigo")
    finally:
        if velho is None:
            os.environ.pop("CRIPTO_SECRET", None)
        else:
            os.environ["CRIPTO_SECRET"] = velho

    return falhas


# ------------------------------------------------------------------ Clicksign

_CLICKSIGN_VISTO: dict[str, object] = {}


def _clicksign_falsa(pedido: httpx.Request) -> httpx.Response:
    caminho = pedido.url.path
    _CLICKSIGN_VISTO.setdefault("pedidos", []).append((pedido.method, caminho))
    _CLICKSIGN_VISTO["ultimo_auth"] = pedido.headers.get("authorization")

    if pedido.method == "GET" and caminho.endswith("/envelopes"):
        if _CLICKSIGN_VISTO.get("token_invalido"):
            return httpx.Response(401, json={"errors": [{"detail": "token inválido"}]})
        return httpx.Response(200, json={"data": []})

    if pedido.method == "POST" and caminho.endswith("/envelopes"):
        return httpx.Response(201, json={"data": {"id": "env-1", "type": "envelopes"}})
    if pedido.method == "POST" and caminho.endswith("/documents"):
        return httpx.Response(201, json={"data": {"id": "doc-1", "type": "documents"}})
    if pedido.method == "POST" and caminho.endswith("/signers"):
        return httpx.Response(
            201,
            json={
                "data": {
                    "id": "signer-1",
                    "type": "signers",
                    "attributes": {"sign_url": "https://app.clicksign.com/sign/abc123"},
                }
            },
        )
    if pedido.method == "POST" and caminho.endswith("/requirements"):
        return httpx.Response(201, json={"data": {"id": "req-1"}})
    if pedido.method == "PATCH" and "/envelopes/" in caminho:
        return httpx.Response(200, json={"data": {"id": "env-1", "attributes": {"status": "running"}}})

    return httpx.Response(404, json={"errors": [{"detail": "rota falsa não prevista"}]})


def testar_clicksign() -> int:
    falhas = 0
    _CLICKSIGN_VISTO.clear()

    async def executar():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_clicksign_falsa)) as http:
            ok, msg = await assinatura_clicksign.testar("token-valido", http=http)
            resultado = await assinatura_clicksign.enviar(
                "token-valido",
                "Contrato de honorários",
                b"%PDF-1.4 conteudo\n%%EOF",
                "Maria Aparecida",
                "maria@exemplo.com",
                http=http,
            )
            return ok, msg, resultado

    ok, msg, resultado = asyncio.run(executar())
    falhas += not checar(ok, f"teste de conexão passa com token válido ({msg})")
    falhas += not checar(
        _CLICKSIGN_VISTO["ultimo_auth"] == "Bearer token-valido",
        "o token vai no header Authorization com prefixo Bearer",
    )
    falhas += not checar(resultado["ok"], f"envio dá certo ({resultado})")
    falhas += not checar(
        resultado["link"] == "https://app.clicksign.com/sign/abc123",
        "o link de assinatura do signatário volta no resultado",
    )
    caminhos_chamados = [c for _m, c in _CLICKSIGN_VISTO["pedidos"]]
    falhas += not checar(
        any(c.endswith("/envelopes") for c in caminhos_chamados)
        and any(c.endswith("/documents") for c in caminhos_chamados)
        and any(c.endswith("/signers") for c in caminhos_chamados)
        and any(c.endswith("/requirements") for c in caminhos_chamados),
        "as cinco etapas do envelope são chamadas em sequência",
    )

    # --- e-mail vazio nunca chega a chamar a API -----------------------
    async def sem_email():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_clicksign_falsa)) as http:
            return await assinatura_clicksign.enviar(
                "token-valido", "Contrato", b"%PDF", "Maria", "", http=http
            )

    resultado_sem_email = asyncio.run(sem_email())
    falhas += not checar(
        not resultado_sem_email["ok"] and "e-mail" in resultado_sem_email["erro"],
        "sem e-mail do signatário, nem tenta mandar",
    )

    # --- token recusado vira {"ok": False}, nunca uma exceção -----------
    _CLICKSIGN_VISTO["token_invalido"] = True
    try:
        async def testar_invalido():
            async with httpx.AsyncClient(transport=httpx.MockTransport(_clicksign_falsa)) as http:
                return await assinatura_clicksign.testar("token-errado", http=http)

        ok_invalido, msg_invalido = asyncio.run(testar_invalido())
        falhas += not checar(not ok_invalido, f"token inválido falha o teste ({msg_invalido})")
    finally:
        _CLICKSIGN_VISTO["token_invalido"] = False

    return falhas


# ----------------------------------------------------------------- Autentique

_AUTENTIQUE_VISTO: dict[str, object] = {}


def _autentique_falsa(pedido: httpx.Request) -> httpx.Response:
    _AUTENTIQUE_VISTO["ultimo_auth"] = pedido.headers.get("authorization")

    if b"multipart/form-data" in (pedido.headers.get("content-type", "").encode()):
        # Corpo multipart (spec graphql-multipart-request): confere que o
        # PDF chegou junto e que a operação é a mutation de criar documento.
        corpo = pedido.content
        _AUTENTIQUE_VISTO["multipart_tem_pdf"] = b"%PDF" in corpo
        _AUTENTIQUE_VISTO["multipart_tem_mutation"] = b"createDocument" in corpo
        return httpx.Response(
            200,
            json={
                "data": {
                    "createDocument": {
                        "id": "doc-123",
                        "name": "Contrato de honorários",
                        "signatures": [
                            {
                                "public_id": "sig-1",
                                "name": "Maria Aparecida",
                                "email": "maria@exemplo.com",
                                "link": {"short_link": "https://autentique.com.br/s/abc"},
                            }
                        ],
                    }
                }
            },
        )

    corpo_json = json.loads(pedido.content)
    if _AUTENTIQUE_VISTO.get("token_invalido"):
        return httpx.Response(200, json={"errors": [{"message": "token inválido"}]})
    if "documents" in corpo_json.get("query", ""):
        return httpx.Response(200, json={"data": {"documents": {"total": 3}}})
    return httpx.Response(404, json={"errors": [{"message": "rota falsa não prevista"}]})


def testar_autentique() -> int:
    falhas = 0
    _AUTENTIQUE_VISTO.clear()

    async def executar():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_autentique_falsa)) as http:
            ok, msg = await assinatura_autentique.testar("token-valido", http=http)
            resultado = await assinatura_autentique.enviar(
                "token-valido",
                "Contrato de honorários",
                b"%PDF-1.4 conteudo\n%%EOF",
                "Maria Aparecida",
                "maria@exemplo.com",
                http=http,
            )
            return ok, msg, resultado

    ok, msg, resultado = asyncio.run(executar())
    falhas += not checar(ok, f"teste de conexão passa com token válido ({msg})")
    falhas += not checar(
        _AUTENTIQUE_VISTO["ultimo_auth"] == "Bearer token-valido",
        "o token vai no header Authorization com prefixo Bearer",
    )
    falhas += not checar(resultado["ok"], f"envio dá certo ({resultado})")
    falhas += not checar(
        resultado["link"] == "https://autentique.com.br/s/abc",
        "o link curto do signatário volta no resultado",
    )
    falhas += not checar(
        bool(_AUTENTIQUE_VISTO.get("multipart_tem_pdf")),
        "o PDF sobe junto no multipart (spec graphql-multipart-request)",
    )
    falhas += not checar(
        bool(_AUTENTIQUE_VISTO.get("multipart_tem_mutation")),
        "a mutation de criar documento vai na parte `operations`",
    )

    # --- token recusado pela API vira {"ok": False} no teste ------------
    _AUTENTIQUE_VISTO["token_invalido"] = True
    try:
        async def testar_invalido():
            async with httpx.AsyncClient(transport=httpx.MockTransport(_autentique_falsa)) as http:
                return await assinatura_autentique.testar("token-errado", http=http)

        ok_invalido, msg_invalido = asyncio.run(testar_invalido())
        falhas += not checar(not ok_invalido, f"token inválido falha o teste ({msg_invalido})")
    finally:
        _AUTENTIQUE_VISTO["token_invalido"] = False

    return falhas


def main_teste() -> int:
    falhas = 0
    for titulo, teste in (
        ("cifra do token (round-trip e chave trocada)", testar_cripto),
        ("Clicksign: fluxo do envelope e erros traduzidos", testar_clicksign),
        ("Autentique: GraphQL com upload e erros traduzidos", testar_autentique),
    ):
        print(f"\n{titulo}")
        falhas += teste()

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
