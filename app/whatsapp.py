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

import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app import armazenamento, auth, automacoes_whatsapp, casos, portal

roteador = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

LINK_AVALIACAO = os.getenv(
    "GOOGLE_AVALIACAO_URL", "https://share.google/BrQVYGnjqdSz3pEw7"
)
URL_PORTAL = os.getenv("URL_PORTAL", "http://localhost:3000").rstrip("/")
MENSAGEM_AVALIACAO = (
    "Obrigado por conversar conosco. Sua avaliação ajuda outras pessoas a "
    "encontrarem nosso trabalho. Se puder, avalie a LARA & MELO no Google: "
)
log = logging.getLogger("whatsapp")
INSTANCIA_OFICIAL = os.getenv("EVOLUTION_INSTANCE_FALLBACK", "Advocacia LM").strip()
DIAGNOSTICO_EVOLUTION = "EVO-DIAG-2"


def _url_instancia(base: str, recurso: str, instancia: str) -> str:
    """Monta a URL sem deixar espaços do nome da instância no caminho."""
    return f"{base}/{recurso}/{quote(instancia.strip(), safe='')}"


def _instancias_candidatas() -> list[str]:
    """Nome do deploy primeiro; nome oficial como recuperação de configuração antiga."""
    candidatas = [os.getenv("EVOLUTION_INSTANCE", "").strip(), INSTANCIA_OFICIAL]
    return list(dict.fromkeys(nome for nome in candidatas if nome))


def _mensagem_erro_evolution(erro: Exception, acao: str = "requisição") -> str:
    """Traduz a falha sem alegar uma causa que a resposta HTTP não comprova."""
    if isinstance(erro, httpx.HTTPStatusError):
        status = erro.response.status_code
        if status in (401, 403):
            return (
                f"A {acao} recebeu HTTP {status} do endpoint configurado "
                f"[{DIAGNOSTICO_EVOLUTION}-HTTP-{status}]. A requisição foi rejeitada, "
                "mas esse código sozinho não prova erro na chave: URL, proxy, "
                "instância e política de autenticação também precisam ser conferidos."
            )
        if status == 404:
            return (
                "A instância do WhatsApp não foi encontrada no endpoint configurado "
                f"[{DIAGNOSTICO_EVOLUTION}-HTTP-404]."
            )
        if status in (400, 409, 422):
            return (
                f"A {acao} foi rejeitada com HTTP {status} "
                f"[{DIAGNOSTICO_EVOLUTION}-HTTP-{status}]."
            )
        if status >= 500:
            return (
                f"O endpoint da Evolution respondeu HTTP {status} "
                f"[{DIAGNOSTICO_EVOLUTION}-HTTP-{status}]. Tente novamente."
            )
    if isinstance(erro, httpx.TimeoutException):
        return f"A Evolution demorou demais para responder [{DIAGNOSTICO_EVOLUTION}-TIMEOUT]."
    if isinstance(erro, ValueError):
        return f"A Evolution respondeu em formato inválido [{DIAGNOSTICO_EVOLUTION}-JSON]."
    return f"Não foi possível conectar à Evolution API [{DIAGNOSTICO_EVOLUTION}-NETWORK]."


class Destinatario(BaseModel):
    telefone: str
    #: Reenvio deliberado: o atendente pediu o link de novo com o cliente na
    #: chamada. Sem isto, um segundo pedido só ouviria "já foi enviado".
    forcar: bool = False


class PedidoLinkAssinatura(BaseModel):
    assinatura_id: str
    signatario_token: str


class ConfiguracaoCobranca(BaseModel):
    ativa: bool = False
    telefone: str = ""
    intervalo_dias: int = Field(default=3, ge=1, le=30)
    # `None` preserva clientes antigos da API, que conhecem apenas dias.
    intervalo_horas: int | None = Field(default=None, ge=1, le=720)
    max_envios_dia: int = Field(default=1, ge=1, le=6)
    incluir_opcionais: bool = False


class EnvioDocumentos(BaseModel):
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
    return bool(
        os.getenv("EVOLUTION_API_URL", "").strip()
        and os.getenv("EVOLUTION_API_KEY", "").strip()
        and _instancias_candidatas()
    )


def _headers_evolution() -> dict[str, str]:
    return {"apikey": os.getenv("EVOLUTION_API_KEY", ""), "Content-Type": "application/json"}


def estado_conexao() -> dict[str, Any]:
    """Estado da instância do WhatsApp: conectado (`open`), conectando ou caído.

    É o que o painel de saúde lê para acender verde ou vermelho — e para decidir
    se oferece o QR de reconexão. Nunca levanta: uma Evolution fora do ar é um
    estado a mostrar, não um 500 na tela.
    """
    if not configurado():
        return {
            "configurado": False,
            "conectado": False,
            "estado": "desconfigurado",
            "diagnostico": DIAGNOSTICO_EVOLUTION,
        }
    base = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
    ultimo_erro = ""
    for instancia in _instancias_candidatas():
        try:
            resposta = httpx.get(
                _url_instancia(base, "instance/connectionState", instancia),
                headers=_headers_evolution(),
                timeout=15,
            )
            if resposta.status_code == 404:
                ultimo_erro = _mensagem_erro_evolution(
                    httpx.HTTPStatusError(
                        "Not found",
                        request=resposta.request,
                        response=resposta,
                    ),
                    "consulta de status",
                )
                continue
            resposta.raise_for_status()
            dados = resposta.json()
            if not isinstance(dados, dict):
                raise ValueError("resposta JSON não é um objeto")
            bloco = dados.get("instance") if isinstance(dados.get("instance"), dict) else dados
            estado = str(bloco.get("state") or dados.get("state") or "").lower()
            resultado = {
                "configurado": True,
                "conectado": estado == "open",
                "estado": estado or "desconhecido",
                "instancia": instancia,
                "numero": "",
                "perfil": "",
                "diagnostico": DIAGNOSTICO_EVOLUTION,
            }
            if estado == "open":
                # O número aparado só quando conectado — a lista traz o dono da
                # instância. Best-effort: se a Evolution não devolver, fica vazio.
                numero, perfil = _numero_conectado(base, instancia)
                resultado["numero"] = numero
                resultado["perfil"] = perfil
            return resultado
        except (httpx.HTTPError, ValueError) as erro:
            ultimo_erro = _mensagem_erro_evolution(erro, "consulta de status")
            log.warning(
                "Evolution recusou consulta de status: instancia=%s erro=%s",
                instancia,
                ultimo_erro,
            )
            continue
    return {
        "configurado": True,
        "conectado": False,
        "estado": "indisponivel",
        "erro": ultimo_erro,
        "diagnostico": DIAGNOSTICO_EVOLUTION,
    }


def _numero_conectado(base: str, instancia: str) -> tuple[str, str]:
    """Número e nome de perfil do WhatsApp pareado, quando a Evolution os expõe."""
    try:
        resposta = httpx.get(
            f"{base}/instance/fetchInstances",
            headers=_headers_evolution(),
            params={"instanceName": instancia},
            timeout=15,
        )
        resposta.raise_for_status()
        dados = resposta.json()
        if isinstance(dados, list):
            lista = dados
        elif isinstance(dados, dict):
            lista = dados.get("instances") or [dados]
        else:
            return "", ""
        alvo = _chave(instancia)
        for item in lista:
            if not isinstance(item, dict):
                continue
            ins = item.get("instance") if isinstance(item.get("instance"), dict) else item
            nome = str(ins.get("instanceName") or ins.get("name") or "")
            if lista and (len(lista) == 1 or _chave(nome) == alvo):
                bruto = str(ins.get("ownerJid") or ins.get("owner") or ins.get("number") or "")
                numero = bruto.split("@", 1)[0]
                return _formatar_numero(numero), str(ins.get("profileName") or "")
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    return "", ""


def _chave(nome: str) -> str:
    return "".join(ch for ch in str(nome).lower() if ch.isalnum())


def _formatar_numero(digitos: str) -> str:
    """55DDDNNNNNNNNN -> +55 (DD) 9XXXX-XXXX, o quanto der; senão devolve como veio."""
    d = "".join(ch for ch in digitos if ch.isdigit())
    if len(d) >= 12 and d.startswith("55"):
        ddd, resto = d[2:4], d[4:]
        meio = resto[:-4], resto[-4:]
        return f"+55 ({ddd}) {meio[0]}-{meio[1]}"
    return digitos


def desconectar() -> dict[str, Any]:
    """Desliga o WhatsApp da instância (logout) — o número deixa de estar pareado.

    Não apaga a instância: depois é só escanear um QR novo para reconectar (o
    mesmo número ou outro). Autonomia do escritório para trocar de aparelho/número.
    """
    if not configurado():
        raise RuntimeError("O WhatsApp (Evolution) não está configurado no servidor.")
    base = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
    ultimo_erro = "A instância do WhatsApp configurada no servidor não foi encontrada."
    for instancia in _instancias_candidatas():
        try:
            resposta = httpx.delete(
                _url_instancia(base, "instance/logout", instancia),
                headers=_headers_evolution(),
                timeout=20,
            )
            if resposta.status_code == 404:
                continue
            resposta.raise_for_status()
            return {"desconectado": True, "instancia": instancia}
        except (httpx.HTTPError, ValueError) as erro:
            raise RuntimeError(_mensagem_erro_evolution(erro, "desconexão")) from erro
    raise RuntimeError(ultimo_erro)


def abrir_conexao_qrcode() -> dict[str, Any]:
    """Pede à Evolution um QR novo para reconectar a instância caída.

    Devolve o QR em base64 (para desenhar) e o código de pareamento, quando a
    versão da Evolution o expõe. É o que dá autonomia ao escritório para religar
    o próprio WhatsApp — ou trocar de número — sem passar pela infra.
    """
    if not configurado():
        raise RuntimeError("O WhatsApp (Evolution) não está configurado no servidor.")
    base = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
    ultimo_erro = "A instância do WhatsApp configurada no servidor não foi encontrada."
    for instancia in _instancias_candidatas():
        try:
            resposta = httpx.get(
                _url_instancia(base, "instance/connect", instancia),
                headers=_headers_evolution(),
                timeout=20,
            )
            if resposta.status_code == 404:
                continue
            resposta.raise_for_status()
            dados = resposta.json()
            if not isinstance(dados, dict):
                raise ValueError("resposta JSON não é um objeto")
            qr = dados.get("qrcode") if isinstance(dados.get("qrcode"), dict) else {}
            base64 = str(dados.get("base64") or qr.get("base64") or "").strip()
            codigo = str(
                dados.get("code") or dados.get("pairingCode") or qr.get("code") or ""
            ).strip()
            if not base64 and not codigo:
                raise RuntimeError(
                    f"A Evolution respondeu sem QR nem código de pareamento "
                    f"[{DIAGNOSTICO_EVOLUTION}-QR-EMPTY]."
                )
            return {"qrcode": base64, "codigo": codigo, "instancia": instancia}
        except (httpx.HTTPError, ValueError) as erro:
            raise RuntimeError(_mensagem_erro_evolution(erro, "geração do QR")) from erro
    raise RuntimeError(ultimo_erro)


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

    try:
        async with httpx.AsyncClient(timeout=20) as cliente:
            candidatas = _instancias_candidatas()
            for indice, instancia in enumerate(candidatas):
                resposta = await cliente.post(
                    _url_instancia(base, "message/sendText", instancia),
                    headers={"apikey": chave, "Content-Type": "application/json"},
                    json={"number": numero, "text": texto},
                )
                if resposta.status_code == 404 and indice < len(candidatas) - 1:
                    log.warning(
                        "Instância Evolution configurada não existe; tentando a oficial."
                    )
                    continue
                resposta.raise_for_status()
                return
    except httpx.HTTPError as erro:
        status = (
            erro.response.status_code
            if isinstance(erro, httpx.HTTPStatusError)
            else None
        )
        log.warning(
            "Falha no envio pela Evolution: status=%s tipo=%s",
            status,
            type(erro).__name__,
        )
        raise HTTPException(502, _mensagem_erro_evolution(erro, "envio da mensagem")) from erro


def _enviar_texto_sync(numero: str, texto: str) -> None:
    """Versão síncrona para o worker periódico do Celery."""
    if not configurado():
        raise RuntimeError("O envio por WhatsApp ainda não foi configurado.")
    base = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
    try:
        candidatas = _instancias_candidatas()
        for indice, instancia in enumerate(candidatas):
            resposta = httpx.post(
                _url_instancia(base, "message/sendText", instancia),
                headers={
                    "apikey": os.getenv("EVOLUTION_API_KEY", ""),
                    "Content-Type": "application/json",
                },
                json={"number": numero, "text": texto},
                timeout=20,
            )
            if resposta.status_code == 404 and indice < len(candidatas) - 1:
                log.warning(
                    "Instância Evolution configurada não existe; tentando a oficial."
                )
                continue
            resposta.raise_for_status()
            return
    except httpx.HTTPError as erro:
        status = (
            erro.response.status_code
            if isinstance(erro, httpx.HTTPStatusError)
            else None
        )
        log.warning(
            "Falha no envio pela Evolution: status=%s tipo=%s",
            status,
            type(erro).__name__,
        )
        raise RuntimeError(_mensagem_erro_evolution(erro, "envio da mensagem")) from erro


@roteador.post("/avaliacao-google")
async def enviar_avaliacao_google(dados: Destinatario) -> dict[str, bool]:
    numero = _numero_brasileiro(dados.telefone)
    chave = f"avaliacao-google:{numero}"
    reservado = await run_in_threadpool(
        automacoes_whatsapp.reservar,
        chave,
        "avaliacao_google",
        numero,
        None,
        dados.forcar,
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


@roteador.get("/status", dependencies=[Depends(auth.usuario_atual)])
async def status_conexao():
    """Se o WhatsApp do escritório está conectado — para o painel de saúde."""
    return await run_in_threadpool(estado_conexao)


@roteador.post("/conectar", dependencies=[Depends(auth.usuario_atual)])
async def conectar_whatsapp():
    """Um QR novo para religar a instância caída (ou trocar de número)."""
    try:
        return await run_in_threadpool(abrir_conexao_qrcode)
    except RuntimeError as erro:
        raise HTTPException(503, str(erro)) from erro


@roteador.post("/desconectar", dependencies=[Depends(auth.usuario_atual)])
async def desconectar_whatsapp():
    """Desliga o número do WhatsApp (logout) — depois é só escanear outro QR."""
    try:
        return await run_in_threadpool(desconectar)
    except RuntimeError as erro:
        raise HTTPException(503, str(erro)) from erro


def _primeiro_nome(nome: str) -> str:
    return (nome or "").strip().split(" ")[0] or "você"


def _rotulo_do_documento(nome_registrado: str) -> str:
    """ "Procuração — Fulano de Tal" vira "a procuração".

    O nome guardado carrega o cliente para o advogado distinguir os documentos na
    lista. Repeti-lo para o próprio cliente ("assine Procuração — Fulano") soa a
    protocolo, não a mensagem de escritório.
    """
    rotulo = (nome_registrado or "").split("—")[0].strip()
    return rotulo.lower() if rotulo else "o documento"


def _variante_cobranca(chave: str, total: int) -> int:
    if total <= 1:
        return 0
    digest = hashlib.sha256(chave.encode("utf-8")).digest()
    return digest[0] % total


def _mensagem_cobranca_documentos(
    *,
    cliente: str,
    pendentes: list[dict[str, Any]],
    url_portal: str,
    senha: str | None = None,
    chave_variante: str = "",
) -> str:
    """Mensagem mínima para WhatsApp: pendência e portal, sem documento no chat.

    A variação é determinística e moderada. Ela deixa a conversa menos mecânica
    para o cliente, mas a proteção real contra bloqueio é cadência, limite diário
    e idempotência da automação.
    """
    nome = _primeiro_nome(cliente)
    aberturas = [
        f"Bom dia, {nome}.",
        f"Olá, {nome}.",
        f"Oi, {nome}.",
    ]
    indice = _variante_cobranca(chave_variante or cliente, len(aberturas))
    linhas = [
        aberturas[indice],
        "",
        "Ainda precisamos dos seguintes documentos para dar andamento ao atendimento:",
        "",
    ]
    limite = 12
    for item in pendentes[:limite]:
        linhas.append(f"- {item.get('nome') or item.get('codigo') or 'Documento'}")
    restante = len(pendentes) - limite
    if restante > 0:
        linhas.append(f"- e mais {restante} documento(s) pendente(s) no portal")
    linhas += [
        "",
        "Por segurança, não envie documentos por esta conversa de WhatsApp.",
        "Use somente o portal oficial do escritório:",
        url_portal,
    ]
    if senha:
        linhas.append(f"Senha de acesso: {senha}")
    return "\n".join(linhas)


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
    registro = await run_in_threadpool(
        armazenamento.obter_assinatura, dados.assinatura_id
    )
    if registro is None:
        raise HTTPException(404, "Documento não encontrado.")

    signatario = _localizar_signatario(registro, dados.signatario_token)
    if signatario.get("estado") == "assinou":
        raise HTTPException(
            409, f"{signatario.get('nome', 'O signatário')} já assinou."
        )

    url = str(signatario.get("url_assinatura") or "").strip()
    if not url:
        raise HTTPException(
            409,
            "Este documento não tem link individual guardado — use o convite que a "
            "ZapSign mandou por e-mail.",
        )

    telefone = str(signatario.get("telefone") or "").strip()
    if not telefone:
        raise HTTPException(
            422, f"{signatario.get('nome', 'O signatário')} não tem telefone."
        )

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
            automacoes_whatsapp.reservar,
            chave,
            "zapsign",
            numero,
            registro.get("caso_id"),
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


@roteador.get(
    "/casos/{caso_id}/cobranca-documentos", dependencies=[Depends(auth.usuario_atual)]
)
async def obter_cobranca_documentos(caso_id: str) -> dict[str, Any]:
    if not await run_in_threadpool(automacoes_whatsapp.caso_existe, caso_id):
        raise HTTPException(404, "Caso não encontrado.")
    return await run_in_threadpool(automacoes_whatsapp.obter_cobranca, caso_id)


@roteador.put(
    "/casos/{caso_id}/cobranca-documentos", dependencies=[Depends(auth.usuario_atual)]
)
async def configurar_cobranca_documentos(
    caso_id: str,
    dados: ConfiguracaoCobranca,
) -> dict[str, Any]:
    if not await run_in_threadpool(automacoes_whatsapp.caso_existe, caso_id):
        raise HTTPException(404, "Caso não encontrado.")
    telefone_origem = await run_in_threadpool(automacoes_whatsapp.telefone_do_caso, caso_id)
    telefone = _numero_brasileiro(telefone_origem) if telefone_origem.strip() else ""
    if dados.ativa and not telefone:
        raise HTTPException(
            422,
            "O caso não possui WhatsApp do cliente. Preencha o telefone no cadastro/entrevista do caso.",
        )
    return await run_in_threadpool(
        automacoes_whatsapp.salvar_cobranca,
        caso_id,
        ativa=dados.ativa,
        telefone=telefone,
        intervalo_dias=dados.intervalo_dias,
        intervalo_horas=dados.intervalo_horas,
        max_envios_dia=dados.max_envios_dia,
        incluir_opcionais=dados.incluir_opcionais,
    )


@roteador.post(
    "/casos/{caso_id}/enviar-documentos",
    dependencies=[Depends(auth.usuario_atual)],
)
async def enviar_documentos_agora(
    caso_id: str, dados: EnvioDocumentos
) -> dict[str, bool]:
    """Envia em um clique o pedido atualizado e o portal seguro do cliente."""
    caso = await run_in_threadpool(armazenamento.obter_caso_com_segredos, caso_id)
    if not caso:
        raise HTTPException(404, "Caso não encontrado.")

    config = await run_in_threadpool(automacoes_whatsapp.obter_cobranca, caso_id)
    telefone = str(config.get("telefone") or "").strip()
    if not telefone:
        raise HTTPException(
            422,
            "O caso não possui WhatsApp do cliente no cadastro/entrevista.",
        )
    numero = _numero_brasileiro(telefone)

    resumo = await run_in_threadpool(
        casos.documentos_pendentes_do_caso, caso_id, dados.incluir_opcionais
    )
    if not resumo:
        raise HTTPException(404, "Checklist do caso não encontrado.")

    pendentes = resumo.get("pendentes") or []
    if not pendentes:
        raise HTTPException(409, "Este caso não possui documentos pendentes para cobrar.")

    token = str(caso.get("portal_token") or "").strip()
    senha: str | None = None
    if not token:
        token = portal.gerar_token()
        senha = portal.gerar_senha()
        senha_hash, sal = portal.hash_senha(senha)
        await run_in_threadpool(
            armazenamento.definir_portal, caso_id, token, senha_hash, sal
        )
        portal.limpar_tentativas(token)

    mensagem = _mensagem_cobranca_documentos(
        cliente=str(caso.get("cliente") or resumo.get("caso", {}).get("cliente") or ""),
        pendentes=pendentes,
        url_portal=f"{URL_PORTAL}/portal/{token}",
        senha=senha,
        chave_variante=f"manual:{caso_id}:{len(pendentes)}",
    )

    await _enviar_texto(numero, mensagem)
    return {"enviado": True, "portal_criado": senha is not None}


@roteador.post(
    "/casos/{caso_id}/cobranca-documentos/teste-disparo",
    dependencies=[Depends(auth.usuario_atual)],
)
async def disparar_teste_cobranca_documentos(
    caso_id: str,
    dados: ConfiguracaoCobranca | None = Body(default=None),
) -> dict[str, Any]:
    """Botão temporário: salva a configuração visível e executa o fluxo do timer."""
    if not await run_in_threadpool(automacoes_whatsapp.caso_existe, caso_id):
        raise HTTPException(404, "Caso não encontrado.")
    if dados is not None:
        telefone_origem = await run_in_threadpool(automacoes_whatsapp.telefone_do_caso, caso_id)
        telefone = _numero_brasileiro(telefone_origem) if telefone_origem.strip() else ""
        if dados.ativa and not telefone:
            raise HTTPException(
                422,
                "O caso não possui WhatsApp do cliente. Preencha o telefone no cadastro/entrevista do caso.",
            )
        config = await run_in_threadpool(
            automacoes_whatsapp.salvar_cobranca,
            caso_id,
            ativa=dados.ativa,
            telefone=telefone,
            intervalo_dias=dados.intervalo_dias,
            intervalo_horas=dados.intervalo_horas,
            max_envios_dia=dados.max_envios_dia,
            incluir_opcionais=dados.incluir_opcionais,
        )
    else:
        config = await run_in_threadpool(automacoes_whatsapp.obter_cobranca, caso_id)
    if not config.get("ativa"):
        raise HTTPException(409, "Ative a cobrança automática antes do teste.")
    if not str(config.get("telefone") or "").strip():
        raise HTTPException(422, "O caso não possui WhatsApp cadastrado para testar.")
    # A mensagem é real e conta no limite diário, mas o teste não desloca a
    # próxima execução configurada pelo gestor.
    config = {
        **config,
        "proximo_envio_em": datetime.now(timezone.utc).isoformat(),
    }
    enviado = await run_in_threadpool(
        _processar_cobranca_documentos, config, reagendar=False
    )
    atualizada = await run_in_threadpool(automacoes_whatsapp.obter_cobranca, caso_id)
    return {
        "enviado": enviado,
        "teste_temporario": True,
        "ultimo_erro": str(atualizada.get("ultimo_erro") or ""),
    }


def _processar_cobranca_documentos(
    config: dict[str, Any], *, reagendar: bool = True
) -> bool:
    caso = armazenamento.obter_caso_com_segredos(config["caso_id"])
    token_portal = str((caso or {}).get("portal_token") or "").strip()
    if not token_portal:
        automacoes_whatsapp.registrar_resultado_cobranca(
            config["caso_id"],
            config["intervalo_dias"],
            None,
            "O caso não possui link ativo para o portal do cliente.",
            config.get("intervalo_horas"),
            reagendar=reagendar,
        )
        return False
    resumo = casos.documentos_pendentes_do_caso(
        config["caso_id"], config["incluir_opcionais"]
    )
    if not resumo:
        automacoes_whatsapp.registrar_resultado_cobranca(
            config["caso_id"],
            config["intervalo_dias"],
            None,
            "Caso ou categoria não encontrado.",
            config.get("intervalo_horas"),
            reagendar=reagendar,
        )
        return False
    pendentes = resumo.get("pendentes") or []
    if not pendentes:
        # Não cobra quem já concluiu. O agendamento fica para uma eventual
        # nova pendência, mas nenhuma mensagem de cobrança é enviada.
        automacoes_whatsapp.registrar_resultado_cobranca(
            config["caso_id"],
            config["intervalo_dias"],
            None,
            intervalo_horas=config.get("intervalo_horas"),
            reagendar=reagendar,
        )
        return False
    max_envios = int(config.get("max_envios_dia") or 1)
    if automacoes_whatsapp.envios_de_cobranca_hoje(config["caso_id"]) >= max_envios:
        if reagendar:
            automacoes_whatsapp.reagendar_cobranca_para_amanha(config["caso_id"])
        return False

    try:
        numero = _numero_brasileiro(str(config.get("telefone") or ""))
    except HTTPException as erro:
        automacoes_whatsapp.registrar_resultado_cobranca(
            config["caso_id"],
            config["intervalo_dias"],
            None,
            str(erro.detail),
            config.get("intervalo_horas"),
            reagendar=reagendar,
        )
        return False

    chave = (
        f"cobranca-documentos:{config['caso_id']}:"
        f"{hashlib.sha256(str(config.get('proximo_envio_em') or '').encode()).hexdigest()[:12]}"
    )
    if not automacoes_whatsapp.reservar(
        chave,
        "cobranca_documentos",
        numero,
        config["caso_id"],
    ):
        return False

    texto = _mensagem_cobranca_documentos(
        cliente=str((resumo.get("caso") or {}).get("cliente") or ""),
        pendentes=pendentes,
        url_portal=f"{URL_PORTAL}/portal/{token_portal}",
        chave_variante=f"{chave}:{len(pendentes)}",
    )
    texto_hash = hashlib.sha256(texto.encode("utf-8")).hexdigest()
    try:
        _enviar_texto_sync(numero, texto)
    except Exception as erro:  # próxima execução volta a tentar
        automacoes_whatsapp.finalizar(chave, str(erro))
        automacoes_whatsapp.registrar_resultado_cobranca(
            config["caso_id"], config["intervalo_dias"], texto_hash, str(erro),
            config.get("intervalo_horas"),
            reagendar=reagendar,
        )
        return False
    automacoes_whatsapp.finalizar(chave)
    automacoes_whatsapp.registrar_resultado_cobranca(
        config["caso_id"], config["intervalo_dias"], texto_hash,
        intervalo_horas=config.get("intervalo_horas"),
        reagendar=reagendar,
    )
    return True


def processar_cobrancas_documentos() -> int:
    """Envia cobranças vencidas sempre com o checklist mais recente."""
    enviados = 0
    for config in automacoes_whatsapp.listar_cobrancas_vencidas():
        if _processar_cobranca_documentos(config):
            enviados += 1
    return enviados
