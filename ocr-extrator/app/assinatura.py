"""Assinatura eletrônica do contrato de honorários (ZapSign).

O contrato sai de `app/contrato.py` como .docx — modelo do escritório com os
colchetes preenchidos. Daqui em diante ele só tramita: sobe para a ZapSign, que
converte para PDF, manda o link a cada signatário e devolve o documento assinado
com a trilha de auditoria.

O QUE ESTE MÓDULO NÃO FAZ

Não redige, não altera e não reordena cláusula nenhuma — o .docx que chega aqui
é o que vai para a assinatura, byte por byte. E não decide quem assina: os
signatários vêm de quem chamou (a entrevista dá o cliente; o escritório sai do
`.env`). Documento com signatário errado é contrato assinado por quem não é
parte, e isso não se conserta depois.

POR QUE O ENVIO PASSA PELO NOSSO BACKEND

1. O token da conta ZapSign vale por todos os contratos do escritório. No
   navegador ele estaria à mão de qualquer extensão instalada.
2. O .docx nunca sai da máquina do advogado por outro caminho: quem faz o upload
   é o servidor, no mesmo processo que acabou de preencher o modelo.
3. Os links de download que a ZapSign devolve **expiram em 60 minutos**. Se a
   tela guardasse a URL, o botão "baixar assinado" quebraria sozinho depois do
   almoço. Aqui a URL é sempre pedida na hora e o PDF fica guardado em
   `dados/contratos/`, que é a cópia que o escritório mantém.

DUAS GRAFIAS PARA O MESMO ESTADO

A API responde o estado do signatário ora em inglês (`new`, `link-opened`,
`signed`), ora em português (`nao_abriu`, `abriu`, `assinou`) — depende do
endpoint. `_estado_signatario` reduz as duas a um vocabulário só. Valor
desconhecido vira `pendente`, nunca `assinou`: errar para "ainda falta" faz o
advogado conferir; errar para "já assinou" faz o escritório protocolar ação com
contrato em branco.
"""

from __future__ import annotations

import base64
import logging
import os
import re
from typing import Any

import httpx

log = logging.getLogger("assinatura")

#: Criar documento inclui a conversão do .docx em PDF do lado deles — é mais
#: lento que uma consulta e não vale a pena cortar cedo.
TEMPO_LIMITE_S = 45.0
TEMPO_LIMITE_DOWNLOAD_S = 60.0

#: O maior contrato do escritório tem poucas páginas; o teto existe para não
#: aceitar um arquivo trocado por engano. A ZapSign recusa acima de 10 MB.
MAX_BYTES = 10 * 1024 * 1024


class ErroAssinatura(Exception):
    """Falha que o usuário precisa ver — conta sem crédito, e-mail inválido…"""


# ------------------------------------------------------------- configuração


def _env(nome: str, padrao: str = "") -> str:
    return (os.getenv(nome, padrao) or "").strip()


def token() -> str:
    return _env("ZAPSIGN_API_TOKEN")


def base_url() -> str:
    return _env("ZAPSIGN_BASE_URL", "https://api.zapsign.com.br/api/v1").rstrip("/")


def modo_autenticacao() -> str:
    return _env("ZAPSIGN_AUTH_MODE", "assinaturaTela")


def whatsapp_ativo() -> bool:
    return _env("ZAPSIGN_WHATSAPP", "0").lower() in ("1", "true", "sim")


def ativa() -> bool:
    """Lido a cada chamada, e não uma vez na importação.

    Quem põe o `.env` no ambiente é o `app.rag` (`carregar_env`, no import) ou o
    `iniciar.ps1`; o teste e o console mexem na variável depois. Congelar isso na
    importação daria um módulo respondendo "desligado" com a chave no ambiente —
    e a ordem em que os módulos são importados passaria a decidir se o escritório
    consegue mandar assinar.
    """
    return bool(token())


def signatario_do_escritorio() -> dict[str, str] | None:
    """O segundo signatário, quando o escritório também assina pelo sistema."""
    nome = _env("ZAPSIGN_SIGNATARIO_NOME")
    email = _env("ZAPSIGN_SIGNATARIO_EMAIL")
    if not nome or not email:
        return None
    return {"nome": nome, "email": email, "papel": "escritório"}


def configuracao() -> dict[str, Any]:
    """O que a tela precisa saber antes de oferecer o botão de enviar."""
    escritorio = signatario_do_escritorio()
    return {
        "ativa": ativa(),
        "auth_mode": modo_autenticacao(),
        "whatsapp": whatsapp_ativo(),
        "signatario_escritorio": escritorio,
    }


# ----------------------------------------------------------------- contatos


def normalizar_telefone(bruto: str) -> tuple[str, str]:
    """"(91) 98888-7777" → ("55", "91988887777").

    A ZapSign quer o país num campo e DDD+número no outro, tudo em dígito. O
    roteiro pergunta "Telefone / WhatsApp" numa caixa livre, então chega de tudo:
    com máscara, com +55, com o 0 da operadora na frente.

    Número que não bate com nenhum formato reconhecível volta vazio — melhor
    mandar o convite só por e-mail do que por um telefone adivinhado, que é
    contrato oferecido a estranho.
    """
    digitos = re.sub(r"\D", "", bruto or "")
    if not digitos:
        return "", ""

    # 0 de operadora ("0 91 98888-7777") e o 0800 não são DDD.
    if len(digitos) in (11, 12) and digitos.startswith("0") and not digitos.startswith("0800"):
        digitos = digitos[1:]

    if len(digitos) in (12, 13) and digitos.startswith("55"):
        digitos = digitos[2:]

    # 10 = fixo com DDD, 11 = celular com DDD.
    return ("55", digitos) if len(digitos) in (10, 11) else ("", "")


def _modo_viavel(modo: str, tem_email: bool, tem_telefone: bool) -> str:
    """Rebaixa o modo de autenticação que este signatário não teria como cumprir.

    `tokenEmail` manda um código para o e-mail; `tokenSms` e `tokenWhatsapp`, para
    o telefone. Cliente de escritório trabalhista com frequência não tem e-mail —
    e o roteiro deixa o campo opcional justamente por isso. Mandar assim recusa o
    documento inteiro na API, ou pior: cria um contrato que o cliente não
    consegue assinar e ninguém entende por quê.

    O que sobra é `assinaturaTela`, que é desenhar a assinatura na tela — o modo
    padrão da conta e o que o escritório já usava antes de existir esta tela.
    """
    if "tokenEmail" in modo and not tem_email:
        return "assinaturaTela"
    if ("tokenSms" in modo or "tokenWhatsapp" in modo) and not tem_telefone:
        return "assinaturaTela"
    return modo


def montar_signatario(
    nome: str,
    email: str = "",
    telefone: str = "",
    papel: str = "",
    auth_mode: str = "",
) -> dict[str, Any]:
    """Um signatário no formato da API, já validado.

    Exige nome e ao menos uma forma de contato: sem isso a ZapSign aceita o
    documento e ele fica parado para sempre, sem ninguém para avisar.
    """
    nome = (nome or "").strip()
    email = (email or "").strip()
    if not nome:
        raise ErroAssinatura("Todo signatário precisa de nome.")

    ddi, numero = normalizar_telefone(telefone)
    if not email and not numero:
        raise ErroAssinatura(
            f"{nome} ficou sem e-mail e sem telefone válido — não há para onde mandar o convite."
        )

    # WhatsApp só quando a conta tem o canal ligado E há número: pedir envio sem
    # número faz a API recusar o documento inteiro.
    por_whatsapp = bool(numero) and whatsapp_ativo()

    return {
        "name": nome,
        "email": email,
        "phone_country": ddi,
        "phone_number": numero,
        "auth_mode": _modo_viavel(auth_mode or modo_autenticacao(), bool(email), bool(numero)),
        "send_automatic_email": bool(email),
        "send_automatic_whatsapp": por_whatsapp,
        # O cliente não deve poder trocar o próprio nome nem o contato na hora de
        # assinar: o contrato qualifica quem a entrevista qualificou.
        "lock_name": True,
        "lock_email": bool(email),
        "lock_phone": bool(numero),
        # Guardado só do nosso lado, para a tela dizer "cliente" e "escritório".
        "_papel": papel,
    }


def signatarios_do_contrato(
    respostas: dict[str, Any], extras: list[dict[str, str]] | None = None
) -> list[dict[str, Any]]:
    """Cliente (da entrevista) + escritório (do `.env`) + quem vier a mais."""
    def r(chave: str) -> str:
        valor = respostas.get(chave, "")
        if isinstance(valor, list):
            valor = ", ".join(str(v) for v in valor)
        return str(valor or "").strip()

    lista = [montar_signatario(r("nome"), r("email"), r("telefone"), papel="cliente")]

    for extra in extras or []:
        lista.append(
            montar_signatario(
                extra.get("nome", ""),
                extra.get("email", ""),
                extra.get("telefone", ""),
                papel=extra.get("papel", ""),
            )
        )

    escritorio = signatario_do_escritorio()
    if escritorio and not any(
        s["email"].lower() == escritorio["email"].lower() for s in lista if s["email"]
    ):
        lista.append(
            montar_signatario(escritorio["nome"], escritorio["email"], papel="escritório")
        )

    return lista


# --------------------------------------------------------------- vocabulário

#: Estado do signatário nas duas grafias que a API usa, reduzido a uma.
_ESTADOS_SIGNATARIO = {
    "new": "pendente",
    "nao_abriu": "pendente",
    "não_abriu": "pendente",
    "link-opened": "abriu",
    "link_opened": "abriu",
    "abriu": "abriu",
    "signed": "assinou",
    "assinou": "assinou",
    "refused": "recusou",
    "recusou": "recusou",
    "expired": "expirou",
    "expirou": "expirou",
    "canceled": "cancelado",
    "cancelled": "cancelado",
    "cancelado": "cancelado",
}

_ESTADOS_DOCUMENTO = {
    "pending": "pendente",
    "signed": "assinado",
    "refused": "recusado",
}

ROTULOS_SIGNATARIO = {
    "pendente": "ainda não abriu",
    "abriu": "abriu, não assinou",
    "assinou": "assinou",
    "recusou": "recusou assinar",
    "expirou": "prazo expirado",
    "cancelado": "cancelado",
}


def _estado_signatario(bruto: str) -> str:
    chave = (bruto or "").strip().lower()
    estado = _ESTADOS_SIGNATARIO.get(chave)
    if estado is None:
        # Valor novo do lado deles. Cai em "pendente" de propósito — ver o
        # cabeçalho do módulo sobre a direção segura do erro.
        log.warning("Estado de signatário desconhecido na ZapSign: %r", bruto)
        return "pendente"
    return estado


def _estado_documento(bruto: str) -> str:
    chave = (bruto or "").strip().lower()
    return _ESTADOS_DOCUMENTO.get(chave, "pendente")


# ------------------------------------------------------------------- resumo


def _identidade(nome: str, email: str, telefone: str) -> tuple[str, ...]:
    """Chaves pelas quais dois registros do mesmo signatário se reconhecem."""
    chaves = []
    if email:
        chaves.append(f"e:{email.strip().lower()}")
    digitos = re.sub(r"\D", "", telefone or "")
    if digitos:
        chaves.append(f"t:{digitos[-11:]}")
    if nome:
        chaves.append(f"n:{nome.strip().lower()}")
    return tuple(chaves)


def casar_com_enviados(
    enviados: list[dict[str, Any]], documento: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Casa o token que a ZapSign deu com o papel que nós demos a cada signatário.

    "Cliente" e "escritório" são rótulo nosso — a API não os guarda, e sem eles a
    tela não sabe dizer se quem falta assinar é o cliente ou o sócio.

    O casamento é por e-mail ou telefone antes de ser por posição: a lista volta
    na mesma ordem em que foi mandada, mas apoiar-se só nisso significa trocar os
    papéis no dia em que eles mudarem a ordem — e um contrato mostrando "o
    cliente já assinou" quando quem assinou foi o escritório é pior que não
    mostrar rótulo nenhum.
    """
    por_chave: dict[str, dict[str, Any]] = {}
    for enviado in enviados:
        for chave in _identidade(
            enviado.get("name", ""), enviado.get("email", ""), enviado.get("phone_number", "")
        ):
            por_chave.setdefault(chave, enviado)

    casados: dict[str, dict[str, Any]] = {}
    devolvidos = documento.get("signers") or []
    for i, s in enumerate(devolvidos):
        token_signatario = str(s.get("token", ""))
        if not token_signatario:
            continue
        achado = None
        for chave in _identidade(
            s.get("name", ""), s.get("email", ""), s.get("phone_number", "")
        ):
            if chave in por_chave:
                achado = por_chave[chave]
                break
        if achado is None and i < len(enviados):
            achado = enviados[i]
        casados[token_signatario] = {"papel": (achado or {}).get("_papel", "")}
    return casados


def resumir(
    documento: dict[str, Any], anteriores: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Traduz a resposta da ZapSign no que a tela mostra.

    `anteriores` é o que já se sabia de cada signatário, por token. Serve para
    dois campos que a consulta de detalhe NÃO repete: o papel (rótulo nosso) e o
    `sign_url`, que só vem na criação. Sem isto, o link individual de assinatura
    sumiria da tela no primeiro refresh — e é justamente ele que o escritório
    reenvia por WhatsApp quando o e-mail do cliente cai em spam.
    """
    anteriores = anteriores or {}
    signatarios = []
    for s in documento.get("signers") or []:
        estado = _estado_signatario(str(s.get("status", "")))
        token_signatario = str(s.get("token", ""))
        antes = anteriores.get(token_signatario, {})
        signatarios.append(
            {
                "token": token_signatario,
                "nome": (s.get("name") or "").strip(),
                "email": (s.get("email") or "").strip(),
                "telefone": (s.get("phone_number") or "").strip(),
                "papel": antes.get("papel", ""),
                "estado": estado,
                "rotulo": ROTULOS_SIGNATARIO[estado],
                "assinou_em": s.get("signed_at"),
                "visualizado_em": s.get("last_view_at"),
                "vezes_visto": s.get("times_viewed") or 0,
                "url_assinatura": s.get("sign_url") or antes.get("url_assinatura", ""),
            }
        )

    assinaram = [s for s in signatarios if s["estado"] == "assinou"]
    faltam = [s for s in signatarios if s["estado"] not in ("assinou", "recusou", "cancelado")]
    recusaram = [s for s in signatarios if s["estado"] == "recusou"]

    estado_doc = _estado_documento(str(documento.get("status", "")))
    if recusaram and estado_doc == "pendente":
        estado_doc = "recusado"

    return {
        "doc_token": str(documento.get("token", "")),
        "nome": (documento.get("name") or "").strip(),
        "estado": estado_doc,
        "signatarios": signatarios,
        "assinaram": len(assinaram),
        "total": len(signatarios),
        "faltam": [s["nome"] for s in faltam],
        "recusaram": [s["nome"] for s in recusaram],
        # A ZapSign só publica o arquivo final depois do último assinar.
        "tem_assinado": bool(documento.get("signed_file")),
        "criado_em": documento.get("created_at"),
        "atualizado_em": documento.get("last_update_at"),
    }


# ---------------------------------------------------------------- transporte


def _cabecalhos() -> dict[str, str]:
    chave = token()
    if not chave:
        raise ErroAssinatura(
            "Assinatura eletrônica desligada: falta ZAPSIGN_API_TOKEN no .env. "
            "O contrato continua podendo ser baixado e assinado à mão."
        )
    return {"Authorization": f"Bearer {chave}", "Content-Type": "application/json"}


def _detalhe_do_erro(resposta: httpx.Response) -> str:
    """A mensagem da ZapSign, que é específica e vale mais que o código HTTP.

    Ela responde ora `{"detail": "..."}`, ora `{"campo": ["erro"]}`, ora uma
    lista. Sem isto a tela mostraria "Erro 400" para "e-mail inválido".
    """
    try:
        corpo = resposta.json()
    except Exception:
        return resposta.text[:200].strip() or f"HTTP {resposta.status_code}"

    if isinstance(corpo, dict):
        for chave in ("detail", "error", "message"):
            if corpo.get(chave):
                return str(corpo[chave])[:300]
        partes = [
            f"{k}: {'; '.join(str(x) for x in v) if isinstance(v, list) else v}"
            for k, v in corpo.items()
        ]
        return " | ".join(partes)[:300] or f"HTTP {resposta.status_code}"
    if isinstance(corpo, list) and corpo:
        return str(corpo[0])[:300]
    return f"HTTP {resposta.status_code}"


async def _pedir(
    metodo: str,
    caminho: str,
    http: httpx.AsyncClient | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Uma chamada à API, com o erro já traduzido para a tela.

    `http` existe para o teste injetar um transporte falso — bater na ZapSign de
    verdade gastaria documento do plano do escritório a cada `pytest`.
    """
    url = f"{base_url()}{caminho}"
    cabecalhos = _cabecalhos()

    async def executar(cliente: httpx.AsyncClient) -> httpx.Response:
        return await cliente.request(metodo, url, headers=cabecalhos, **kwargs)

    try:
        if http is not None:
            resposta = await executar(http)
        else:
            async with httpx.AsyncClient(timeout=TEMPO_LIMITE_S) as cliente:
                resposta = await executar(cliente)
    except httpx.HTTPError as exc:
        # `str(exc)` de um erro do httpx traz a URL, nunca o header — o token
        # não vaza para o log nem para a tela.
        log.warning("ZapSign inacessível em %s %s: %s", metodo, caminho, str(exc)[:160])
        raise ErroAssinatura("A ZapSign não respondeu. Tente de novo em instantes.") from exc

    if resposta.status_code == 401 or resposta.status_code == 403:
        raise ErroAssinatura("A ZapSign recusou o token. Confira ZAPSIGN_API_TOKEN no .env.")
    if resposta.status_code == 404:
        raise ErroAssinatura("Documento não encontrado na ZapSign — pode ter sido excluído lá.")
    if resposta.status_code >= 400:
        raise ErroAssinatura(f"A ZapSign recusou o pedido: {_detalhe_do_erro(resposta)}")

    try:
        return resposta.json()
    except Exception as exc:
        raise ErroAssinatura("Resposta ilegível da ZapSign.") from exc


# -------------------------------------------------------------------- ações


async def enviar(
    nome_documento: str,
    docx: bytes,
    signatarios: list[dict[str, Any]],
    identificador_externo: str = "",
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Sobe o .docx e dispara os convites. Devolve a resposta crua da ZapSign.

    O .docx vai como está: a conversão para PDF é do lado deles, e é o PDF
    convertido que o cliente assina. Não se manda PDF gerado aqui porque não há
    conversor confiável na máquina — o LibreOffice não é dependência do projeto.
    """
    if not docx:
        raise ErroAssinatura("Contrato vazio — nada a enviar.")
    if len(docx) > MAX_BYTES:
        raise ErroAssinatura(
            f"O contrato tem {len(docx) // 1024} KB e o limite da ZapSign é 10 MB."
        )
    if not signatarios:
        raise ErroAssinatura("Nenhum signatário — o documento ficaria parado sem ninguém a avisar.")

    corpo = {
        "name": nome_documento,
        "base64_docx": base64.b64encode(docx).decode("ascii"),
        "lang": "pt-br",
        # Sem ordem: cliente e escritório assinam quando puderem. Ordem forçada
        # atrasa o protocolo por causa da agenda do advogado.
        "signature_order_active": False,
        # `_papel` é rótulo nosso; a API recusa campo que não conhece.
        "signers": [{k: v for k, v in s.items() if not k.startswith("_")} for s in signatarios],
    }
    if identificador_externo:
        corpo["external_id"] = identificador_externo

    return await _pedir("POST", "/docs/", http=http, json=corpo)


async def consultar(doc_token: str, http: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Estado atual do documento — quem já assinou e quem falta."""
    if not doc_token:
        raise ErroAssinatura("Documento sem token na ZapSign.")
    return await _pedir("GET", f"/docs/{doc_token}/", http=http)


async def url_do_assinado(doc_token: str, http: httpx.AsyncClient | None = None) -> str:
    """A URL do PDF assinado, pedida na hora porque ela expira em 60 minutos."""
    documento = await consultar(doc_token, http=http)
    url = documento.get("signed_file") or ""
    if not url:
        resumo = resumir(documento)  # sem `anteriores`: aqui só se lê quem falta
        if resumo["faltam"]:
            raise ErroAssinatura(
                "O documento assinado só existe depois que todos assinam. "
                f"Falta: {', '.join(resumo['faltam'])}."
            )
        raise ErroAssinatura("A ZapSign ainda não publicou o arquivo assinado.")
    return str(url)


async def baixar(url: str, http: httpx.AsyncClient | None = None) -> bytes:
    """Puxa o PDF assinado do S3 da ZapSign.

    A URL já vem assinada e temporária, então vai SEM o nosso token — mandar o
    header `Authorization` para um bucket de terceiro é entregar a chave da conta
    a quem não precisa dela.
    """
    try:
        if http is not None:
            resposta = await http.get(url)
        else:
            async with httpx.AsyncClient(
                timeout=TEMPO_LIMITE_DOWNLOAD_S, follow_redirects=True
            ) as cliente:
                resposta = await cliente.get(url)
        resposta.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Download do contrato assinado falhou: %s", str(exc)[:160])
        raise ErroAssinatura(
            "Não foi possível baixar o contrato assinado. O link da ZapSign dura 60 "
            "minutos; tente de novo para pedir um novo."
        ) from exc

    conteudo = resposta.content
    if not conteudo:
        raise ErroAssinatura("A ZapSign devolveu um arquivo vazio.")
    return conteudo
