"""Envio do contrato para assinatura eletrônica e acompanhamento (ZapSign).

Nada aqui toca a ZapSign de verdade: o transporte é falso (`httpx.MockTransport`).
Bater na API real gastaria um documento do plano do escritório a cada execução —
e faria a suíte falhar por internet instável, que é o que já parou a vetorização.

O que está coberto é o que dói: signatário sem contato passando batido, papel
trocado entre cliente e escritório, "assinou" aparecendo por engano, e o link de
assinatura sumindo no primeiro refresh.

Rodar: .venv\\Scripts\\python.exe -m tests.test_assinatura
"""

from __future__ import annotations

import asyncio
import base64
import json
import os

import httpx

from app import assinatura


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


# ------------------------------------------------------------ ZapSign falsa

CRIACAO = {
    "open_id": 5,
    "token": "eb9c367a-e62f-4992-8360-b0219deaeecc",
    "status": "pending",
    "name": "Contrato de honorários — Maria Aparecida da Silva",
    "original_file": "https://zapsign.s3.amazonaws.com/pdf/x/y.pdf",
    "signed_file": None,
    "created_at": "2026-08-13T03:33:46.241747Z",
    "last_update_at": "2026-08-13T03:33:46.241775Z",
    "signers": [
        {
            "token": "921c115d-4a6e-445d-bdca-03fadedbbc0b",
            "sign_url": "https://app.zapsign.com.br/verificar/921c115d",
            "status": "new",
            "name": "Maria Aparecida da Silva",
            "email": "maria@exemplo.com",
            "phone_country": "55",
            "phone_number": "91988887777",
            "times_viewed": 0,
            "last_view_at": None,
            "signed_at": None,
        },
        {
            "token": "07fb0a0a-4b7d-49a5-bd7b-4958265c4e46",
            "sign_url": "https://app.zapsign.com.br/verificar/07fb0a0a",
            "status": "new",
            "name": "Bezerra Advogados",
            "email": "contato@escritorio.com",
            "phone_country": "",
            "phone_number": "",
            "times_viewed": 0,
            "last_view_at": None,
            "signed_at": None,
        },
    ],
}

#: A consulta de detalhe devolve os signatários em OUTRA ordem e sem `sign_url`.
#: Os dois são de propósito — é exatamente o que quebra um casamento por posição
#: e o que faz o link de assinatura sumir da tela.
DETALHE_PARCIAL = {
    "token": CRIACAO["token"],
    "name": CRIACAO["name"],
    "status": "pending",
    "signed_file": None,
    "signers": [
        {
            "token": "07fb0a0a-4b7d-49a5-bd7b-4958265c4e46",
            "status": "new",
            "name": "Bezerra Advogados",
            "email": "contato@escritorio.com",
            "times_viewed": 0,
            "signed_at": None,
        },
        {
            "token": "921c115d-4a6e-445d-bdca-03fadedbbc0b",
            "status": "signed",
            "name": "Maria Aparecida da Silva",
            "email": "maria@exemplo.com",
            "times_viewed": 3,
            "signed_at": "2026-08-13T14:02:11Z",
        },
    ],
}

PDF_ASSINADO = b"%PDF-1.4 contrato assinado\n%%EOF"

#: O que o transporte falso viu passar — é onde se confere o corpo do POST.
enviado: dict[str, object] = {}


def zapsign_falsa(pedido: httpx.Request) -> httpx.Response:
    caminho = pedido.url.path

    if pedido.method == "POST" and caminho.endswith("/docs/"):
        enviado["headers"] = dict(pedido.headers)
        enviado["corpo"] = json.loads(pedido.content)
        return httpx.Response(200, json=CRIACAO)

    if pedido.method == "GET" and "/docs/" in caminho:
        return httpx.Response(200, json=enviado.get("detalhe", DETALHE_PARCIAL))

    if "amazonaws" in pedido.url.host:
        enviado["headers_download"] = dict(pedido.headers)
        return httpx.Response(200, content=PDF_ASSINADO)

    return httpx.Response(404, json={"detail": "rota falsa não prevista"})


def cliente_falso() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(zapsign_falsa))


# ------------------------------------------------------------------- testes


def testar_telefone() -> int:
    falhas = 0
    casos = [
        ("(91) 98888-7777", ("55", "91988887777"), "máscara do roteiro"),
        ("+55 91 98888-7777", ("55", "91988887777"), "com DDI colado"),
        ("5591988887777", ("55", "91988887777"), "tudo grudado com DDI"),
        ("091988887777", ("55", "91988887777"), "0 da operadora na frente"),
        ("9132224444", ("55", "9132224444"), "fixo com DDA"),
        ("", ("", ""), "vazio"),
        ("98888-7777", ("", ""), "sem DDD não vira telefone adivinhado"),
        ("não tem", ("", ""), "texto livre"),
    ]
    for bruto, esperado, descricao in casos:
        obtido = assinatura.normalizar_telefone(bruto)
        falhas += not checar(obtido == esperado, f"telefone: {descricao} ({obtido})")
    return falhas


def testar_signatarios() -> int:
    falhas = 0

    # Sem e-mail e sem telefone o convite não tem para onde ir. A ZapSign
    # aceitaria o documento e ele ficaria parado para sempre.
    try:
        assinatura.montar_signatario("João sem contato")
        falhas += not checar(False, "signatário sem contato é recusado")
    except assinatura.ErroAssinatura as exc:
        falhas += not checar(
            "sem e-mail e sem telefone" in str(exc),
            f"signatário sem contato é recusado com motivo ({exc})",
        )

    try:
        assinatura.montar_signatario("", email="x@y.com")
        falhas += not checar(False, "signatário sem nome é recusado")
    except assinatura.ErroAssinatura:
        falhas += not checar(True, "signatário sem nome é recusado")

    # Só telefone basta — cliente de escritório trabalhista muitas vezes não tem
    # e-mail, e o roteiro deixa o campo opcional justamente por isso.
    so_telefone = assinatura.montar_signatario("Maria", telefone="(91) 98888-7777")
    falhas += not checar(
        so_telefone["phone_number"] == "91988887777" and so_telefone["email"] == "",
        "cliente sem e-mail passa pelo telefone",
    )
    falhas += not checar(
        so_telefone["send_automatic_email"] is False,
        "não se pede envio de e-mail para quem não tem e-mail",
    )

    # O modo de autenticação tem de caber no contato que o signatário tem. Pedir
    # código por e-mail a quem não tem e-mail cria contrato que ninguém assina.
    os.environ["ZAPSIGN_AUTH_MODE"] = "assinaturaTela-tokenEmail"
    sem_email = assinatura.montar_signatario("Maria", telefone="(91) 98888-7777")
    com_email = assinatura.montar_signatario("Maria", email="maria@exemplo.com")
    falhas += not checar(
        sem_email["auth_mode"] == "assinaturaTela",
        f"tokenEmail é rebaixado para quem não tem e-mail ({sem_email['auth_mode']})",
    )
    falhas += not checar(
        com_email["auth_mode"] == "assinaturaTela-tokenEmail",
        "quem tem e-mail mantém o modo configurado",
    )

    os.environ["ZAPSIGN_AUTH_MODE"] = "assinaturaTela-tokenSms"
    sem_fone = assinatura.montar_signatario("Maria", email="maria@exemplo.com")
    falhas += not checar(
        sem_fone["auth_mode"] == "assinaturaTela",
        f"tokenSms é rebaixado para quem não tem telefone ({sem_fone['auth_mode']})",
    )
    os.environ["ZAPSIGN_AUTH_MODE"] = "assinaturaTela"

    respostas = {
        "nome": "Maria Aparecida da Silva",
        "email": "maria@exemplo.com",
        "telefone": "(91) 98888-7777",
    }

    os.environ["ZAPSIGN_SIGNATARIO_NOME"] = "Bezerra Advogados"
    os.environ["ZAPSIGN_SIGNATARIO_EMAIL"] = "contato@escritorio.com"
    lista = assinatura.signatarios_do_contrato(respostas)
    falhas += not checar(len(lista) == 2, f"cliente + escritório ({len(lista)})")
    falhas += not checar(
        [s["_papel"] for s in lista] == ["cliente", "escritório"],
        "cada um sai com o seu papel",
    )

    # O escritório configurado no .env não pode entrar duas vezes quando ele
    # próprio é o cliente — assinatura duplicada trava o documento.
    duplicado = assinatura.signatarios_do_contrato(
        {"nome": "Bezerra Advogados", "email": "contato@escritorio.com"}
    )
    falhas += not checar(len(duplicado) == 1, f"escritório não se duplica ({len(duplicado)})")

    os.environ["ZAPSIGN_SIGNATARIO_NOME"] = ""
    os.environ["ZAPSIGN_SIGNATARIO_EMAIL"] = ""
    sozinho = assinatura.signatarios_do_contrato(respostas)
    falhas += not checar(len(sozinho) == 1, "sem escritório no .env, só o cliente assina")

    return falhas


def testar_estados() -> int:
    falhas = 0

    # As duas grafias que a API usa têm de cair no mesmo lugar.
    pares = [("new", "pendente"), ("nao_abriu", "pendente"), ("link-opened", "abriu"),
             ("abriu", "abriu"), ("signed", "assinou"), ("assinou", "assinou"),
             ("refused", "recusou"), ("recusou", "recusou"), ("expirou", "expirou")]
    for bruto, esperado in pares:
        falhas += not checar(
            assinatura._estado_signatario(bruto) == esperado,
            f"estado {bruto!r} → {esperado!r}",
        )

    # Valor que eles inventarem amanhã tem de cair em "pendente", jamais em
    # "assinou": errar para "ainda falta" faz conferir; errar para "já assinou"
    # faz protocolar ação com contrato em branco.
    falhas += not checar(
        assinatura._estado_signatario("estado_novo_deles") == "pendente",
        "estado desconhecido vira 'pendente', nunca 'assinou'",
    )
    return falhas


def testar_envio() -> int:
    falhas = 0
    os.environ["ZAPSIGN_API_TOKEN"] = "token-de-teste"
    os.environ["ZAPSIGN_SIGNATARIO_NOME"] = "Bezerra Advogados"
    os.environ["ZAPSIGN_SIGNATARIO_EMAIL"] = "contato@escritorio.com"

    docx = b"PK\x03\x04 finge que sou um docx"
    respostas = {
        "nome": "Maria Aparecida da Silva",
        "email": "maria@exemplo.com",
        "telefone": "(91) 98888-7777",
    }

    async def executar():
        async with cliente_falso() as http:
            signatarios = assinatura.signatarios_do_contrato(respostas)
            resposta = await assinatura.enviar(
                "Contrato de honorários — Maria Aparecida da Silva",
                docx,
                signatarios,
                http=http,
            )
            return signatarios, resposta

    signatarios, resposta = asyncio.run(executar())
    corpo = enviado["corpo"]

    falhas += not checar(
        base64.b64decode(corpo["base64_docx"]) == docx,
        "o .docx sobe inteiro e sem alteração — é o modelo do escritório",
    )
    falhas += not checar(
        "base64_pdf" not in corpo,
        "não se manda PDF: a conversão é do lado deles",
    )
    falhas += not checar(
        enviado["headers"].get("authorization") == "Bearer token-de-teste",
        "o token vai no header Authorization",
    )
    falhas += not checar(
        all("_papel" not in s for s in corpo["signers"]),
        "o rótulo interno `_papel` não vaza para a API (ela recusa campo estranho)",
    )
    falhas += not checar(
        corpo["signers"][0]["lock_name"] is True,
        "o cliente não pode trocar o próprio nome na hora de assinar",
    )
    falhas += not checar(corpo["lang"] == "pt-br", "o documento vai em português")

    # --- papéis e resumo na criação ---------------------------------------
    anteriores = assinatura.casar_com_enviados(signatarios, resposta)
    resumo = assinatura.resumir(resposta, anteriores)

    falhas += not checar(resumo["estado"] == "pendente", "recém-criado está pendente")
    falhas += not checar(resumo["assinaram"] == 0, "ninguém assinou ainda")
    falhas += not checar(len(resumo["faltam"]) == 2, "os dois constam como faltando")
    falhas += not checar(
        [s["papel"] for s in resumo["signatarios"]] == ["cliente", "escritório"],
        f"papéis casados na criação ({[s['papel'] for s in resumo['signatarios']]})",
    )
    falhas += not checar(
        all(s["url_assinatura"] for s in resumo["signatarios"]),
        "cada signatário sai com o seu link de assinatura",
    )

    # --- refresh: ordem trocada e sem sign_url ----------------------------
    async def consultar():
        async with cliente_falso() as http:
            return await assinatura.consultar(resposta["token"], http=http)

    detalhe = asyncio.run(consultar())
    por_token = {s["token"]: s for s in resumo["signatarios"]}
    resumo2 = assinatura.resumir(detalhe, por_token)

    cliente = next(s for s in resumo2["signatarios"] if s["nome"].startswith("Maria"))
    escritorio = next(s for s in resumo2["signatarios"] if s["nome"].startswith("Bezerra"))

    falhas += not checar(
        cliente["papel"] == "cliente" and escritorio["papel"] == "escritório",
        "com a ordem trocada no refresh, cada papel segue no seu dono",
    )
    falhas += not checar(
        cliente["estado"] == "assinou" and escritorio["estado"] == "pendente",
        "quem assinou e quem falta saem certos",
    )
    falhas += not checar(
        resumo2["faltam"] == ["Bezerra Advogados"],
        f"a lista de quem falta traz só quem falta ({resumo2['faltam']})",
    )
    falhas += not checar(resumo2["assinaram"] == 1, "a contagem de assinaturas confere")
    falhas += not checar(
        cliente["url_assinatura"] == "https://app.zapsign.com.br/verificar/921c115d",
        "o link de assinatura sobrevive ao refresh que não o repete",
    )
    falhas += not checar(
        resumo2["estado"] == "pendente",
        "com um faltando, o documento continua pendente",
    )
    return falhas


def testar_download() -> int:
    falhas = 0
    os.environ["ZAPSIGN_API_TOKEN"] = "token-de-teste"

    # --- ainda falta alguém: o erro precisa dizer QUEM ---------------------
    enviado["detalhe"] = DETALHE_PARCIAL

    async def cedo_demais():
        async with cliente_falso() as http:
            return await assinatura.url_do_assinado(CRIACAO["token"], http=http)

    try:
        asyncio.run(cedo_demais())
        falhas += not checar(False, "baixar antes de todos assinarem falha")
    except assinatura.ErroAssinatura as exc:
        falhas += not checar(
            "Bezerra Advogados" in str(exc),
            f"o erro nomeia quem ainda falta assinar ({exc})",
        )

    # --- todos assinaram --------------------------------------------------
    completo = json.loads(json.dumps(DETALHE_PARCIAL))
    completo["status"] = "signed"
    completo["signed_file"] = "https://zapsign.s3.amazonaws.com/signed/contrato.pdf"
    for s in completo["signers"]:
        s["status"] = "signed"
        s["signed_at"] = "2026-08-13T15:00:00Z"
    enviado["detalhe"] = completo

    async def baixar():
        async with cliente_falso() as http:
            url = await assinatura.url_do_assinado(CRIACAO["token"], http=http)
            return url, await assinatura.baixar(url, http=http)

    url, pdf = asyncio.run(baixar())
    falhas += not checar(pdf == PDF_ASSINADO, "o PDF assinado chega inteiro")
    falhas += not checar(
        "authorization" not in enviado["headers_download"],
        "o token NÃO acompanha o download do S3 — a URL já vem assinada",
    )
    falhas += not checar(
        assinatura.resumir(completo)["estado"] == "assinado",
        "com todos assinados o documento fica 'assinado'",
    )
    falhas += not checar(url.startswith("https://"), "a URL do assinado é pedida na hora")

    enviado.pop("detalhe", None)
    return falhas


def testar_erros() -> int:
    falhas = 0

    # Sem chave, o módulo diz o que fazer em vez de estourar um KeyError.
    os.environ["ZAPSIGN_API_TOKEN"] = ""
    falhas += not checar(not assinatura.ativa(), "sem token, a assinatura está desligada")
    try:
        asyncio.run(assinatura.consultar("qualquer"))
        falhas += not checar(False, "sem token, a chamada falha explicando")
    except assinatura.ErroAssinatura as exc:
        falhas += not checar(
            "ZAPSIGN_API_TOKEN" in str(exc), f"o erro diz qual variável falta ({exc})"
        )

    os.environ["ZAPSIGN_API_TOKEN"] = "token-de-teste"

    # A mensagem específica da ZapSign vale mais na tela que "Erro 400".
    def recusando(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"signers": ["E-mail inválido: maria@@exemplo"]})

    async def recusado():
        async with httpx.AsyncClient(transport=httpx.MockTransport(recusando)) as http:
            await assinatura.enviar("x", b"docx", [{"name": "M", "email": "m@x.com"}], http=http)

    try:
        asyncio.run(recusado())
        falhas += not checar(False, "erro 400 vira ErroAssinatura")
    except assinatura.ErroAssinatura as exc:
        falhas += not checar(
            "E-mail inválido" in str(exc),
            f"a mensagem da ZapSign chega à tela ({exc})",
        )

    def sem_autorizacao(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid token."})

    async def token_ruim():
        async with httpx.AsyncClient(transport=httpx.MockTransport(sem_autorizacao)) as http:
            await assinatura.consultar("t", http=http)

    try:
        asyncio.run(token_ruim())
        falhas += not checar(False, "401 vira ErroAssinatura")
    except assinatura.ErroAssinatura as exc:
        falhas += not checar(
            "ZAPSIGN_API_TOKEN" in str(exc), "401 manda conferir a chave no .env"
        )

    # Documento sem signatário ficaria parado para sempre, sem ninguém a avisar.
    try:
        asyncio.run(assinatura.enviar("x", b"docx", []))
        falhas += not checar(False, "envio sem signatário é recusado")
    except assinatura.ErroAssinatura:
        falhas += not checar(True, "envio sem signatário é recusado antes de sair da máquina")

    try:
        asyncio.run(assinatura.enviar("x", b"", [{"name": "M"}]))
        falhas += not checar(False, "contrato vazio é recusado")
    except assinatura.ErroAssinatura:
        falhas += not checar(True, "contrato vazio é recusado")

    return falhas


def testar_persistencia() -> int:
    """A tabela local: o índice que diz qual contrato é de qual cliente."""
    falhas = 0
    from app import armazenamento

    armazenamento.inicializar()

    signatarios = [
        {"token": "s1", "nome": "Maria", "papel": "cliente", "estado": "pendente"},
        {"token": "s2", "nome": "Bezerra", "papel": "escritório", "estado": "pendente"},
    ]
    registro = armazenamento.registrar_assinatura(
        doc_token="doc-token-de-teste",
        nome="Contrato de honorários — Maria",
        cliente="Maria",
        signatarios=signatarios,
    )
    falhas += not checar(bool(registro.get("id")), "a assinatura é registrada localmente")
    falhas += not checar(registro["faltam"] == ["Maria", "Bezerra"], "os dois constam faltando")
    falhas += not checar(
        registro["arquivo_local"] is False, "ainda não há cópia do assinado em disco"
    )

    assinados = [{**signatarios[0], "estado": "assinou"}, signatarios[1]]
    atualizado = armazenamento.atualizar_assinatura(registro["id"], "pendente", assinados)
    falhas += not checar(atualizado["assinaram"] == 1, "a contagem é recalculada na leitura")
    falhas += not checar(atualizado["faltam"] == ["Bezerra"], "só quem falta continua na lista")

    achado = [a for a in armazenamento.listar_assinaturas() if a["id"] == registro["id"]]
    falhas += not checar(len(achado) == 1, "a assinatura aparece na listagem")
    falhas += not checar(
        "doc_token" in achado[0],
        "o doc_token fica disponível internamente (a rota é que o remove da resposta)",
    )

    falhas += not checar(
        armazenamento.excluir_assinatura(registro["id"]), "a assinatura é removida do índice"
    )
    falhas += not checar(
        armazenamento.obter_assinatura(registro["id"]) is None, "e some da consulta"
    )
    return falhas


def main_teste() -> int:
    guardado = {
        chave: os.environ.get(chave)
        for chave in (
            "ZAPSIGN_API_TOKEN",
            "ZAPSIGN_AUTH_MODE",
            "ZAPSIGN_SIGNATARIO_NOME",
            "ZAPSIGN_SIGNATARIO_EMAIL",
            "ZAPSIGN_WHATSAPP",
        )
    }
    os.environ["ZAPSIGN_WHATSAPP"] = "0"

    falhas = 0
    for titulo, teste in (
        ("telefone do roteiro → formato da API", testar_telefone),
        ("quem assina", testar_signatarios),
        ("vocabulário de estados", testar_estados),
        ("envio do contrato e acompanhamento", testar_envio),
        ("download do assinado", testar_download),
        ("falhas que o usuário precisa ver", testar_erros),
        ("índice local dos contratos", testar_persistencia),
    ):
        print(f"\n{titulo}")
        falhas += teste()

    for chave, valor in guardado.items():
        if valor is None:
            os.environ.pop(chave, None)
        else:
            os.environ[chave] = valor

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
