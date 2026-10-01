"""Modelos de mensagem do WhatsApp, o envio rastreado e o webhook de entrega.

O texto de cada mensagem automática (confirmação, lembrete, falta, documentação,
avaliação) fica numa tabela editável pela tela WhatsApp. O que nunca sai do
servidor é a decisão de PARA QUEM e COM QUAL LINK: o modelo só escolhe as
palavras em volta de `{link_sala}`, `{link}` e companhia.

Todo envio passa por `automacoes_whatsapp.reservar` com uma chave determinística.
É o que deixa o worker de lembretes rodar de novo, cair no meio ou disputar com
a API sem mandar a mesma mensagem duas vezes.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import auth, automacoes_whatsapp, banco
from .banco import PREFIXO, SCHEMA
from .esquema_portavel import Coluna, Tabela, criar as criar_tabelas

log = logging.getLogger("whatsapp_modelos")

TABELA = f"{SCHEMA}.{PREFIXO}whatsapp_modelos"
FUSO = ZoneInfo("America/Sao_Paulo")

TABELAS = (
    Tabela(
        TABELA,
        (
            Coluna("codigo", "codigo", nula=False),
            Coluna("nome", "curto", nula=False, padrao=""),
            Coluna("descricao", "texto"),
            Coluna("texto", "longo", nula=False),
            Coluna("ativo", "inteiro", nula=False, padrao=1),
            Coluna("sistema", "inteiro", nula=False, padrao=1),
            Coluna("versao", "inteiro", nula=False, padrao=1),
            Coluna("atualizado_em", "data", nula=False),
            Coluna("atualizado_por", "curto"),
        ),
        ("codigo",),
    ),
)

#: Os modelos que o sistema usa. O texto aqui é o padrão — "Restaurar" volta a ele.
PADROES: dict[str, dict[str, str]] = {
    "confirmacao_agendamento": {
        "nome": "Confirmação do agendamento",
        "descricao": "Enviada ao agendar (ou pelo botão Enviar confirmação).",
        "texto": (
            "Olá, {primeiro_nome}! Seu atendimento com a {escritorio} está marcado para "
            "{data} às {hora}.\n\nNo horário, entre pela sala online:\n{link_sala}\n\n"
            "Se precisar remarcar, responda esta mensagem."
        ),
    },
    "lembrete_agendamento": {
        "nome": "Lembrete do atendimento",
        "descricao": "Enviado pelo worker nos horários configurados antes do atendimento.",
        "texto": (
            "Olá, {primeiro_nome}. Lembrete: seu atendimento com a {escritorio} é em "
            "{data} às {hora}.\n\nLink da sala:\n{link_sala}"
        ),
    },
    "cliente_faltou": {
        "nome": "Cliente não compareceu",
        "descricao": "Enviada quando o horário passa sem o cliente entrar na sala.",
        "texto": (
            "Olá, {primeiro_nome}. Sentimos sua falta no atendimento de {data} às {hora}. "
            "Responda esta mensagem para combinarmos um novo horário."
        ),
    },
    "documentacao_pendente": {
        "nome": "Cobrança de documentos",
        "descricao": "Usada pela cobrança automática de documentos do caso.",
        "texto": (
            "Olá, {primeiro_nome}.\n\nAinda precisamos dos seguintes documentos para dar "
            "andamento ao atendimento:\n\n{documentos}\n\nPor segurança, não envie documentos "
            "por esta conversa de WhatsApp.\nUse somente o portal oficial do escritório:\n{link}"
        ),
    },
    "avaliacao_google": {
        "nome": "Avaliação do escritório no Google",
        "descricao": "Enviada na etapa de avaliação, ao final do atendimento.",
        "texto": (
            "Obrigado por conversar conosco, {primeiro_nome}. Sua avaliação ajuda outras "
            "pessoas a encontrarem nosso trabalho. Se puder, avalie a {escritorio} no "
            "Google: {link}"
        ),
    },
}

VARIAVEIS = (
    "cliente", "primeiro_nome", "data", "hora", "link_sala", "escritorio", "link", "documentos",
)

#: Modelos que a cobrança e a avaliação antigas já tinham em código: só o texto
#: EDITADO substitui o original (que tem variação de abertura e não deve sumir).
_TEXTO_LEGADO = {"documentacao_pendente", "avaliacao_google"}

_cache: dict[str, tuple[float, str | None]] = {}
_CACHE_S = 60.0


def inicializar() -> None:
    instante = _agora()
    with banco.conectar() as con:
        criar_tabelas(con, TABELAS)
        existentes = {
            linha["codigo"] for linha in con.execute(f"SELECT codigo FROM {TABELA}").fetchall()
        }
        for codigo, padrao in PADROES.items():
            if codigo in existentes:
                continue
            con.execute(
                f"""INSERT INTO {TABELA}
                    (codigo, nome, descricao, texto, ativo, sistema, versao, atualizado_em)
                    VALUES (?, ?, ?, ?, 1, 1, 1, ?)""",
                (codigo, padrao["nome"], padrao["descricao"], padrao["texto"], instante),
            )


def _agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _registro(linha: Any) -> dict[str, Any]:
    r = dict(zip(linha.keys(), linha))
    r["ativo"] = bool(r.get("ativo"))
    r["sistema"] = bool(r.get("sistema"))
    r["padrao"] = PADROES.get(r["codigo"], {}).get("texto")
    r["personalizado"] = bool(r["padrao"]) and r["texto"] != r["padrao"]
    return r


def listar() -> list[dict[str, Any]]:
    with banco.conectar() as con:
        linhas = con.execute(f"SELECT * FROM {TABELA} ORDER BY codigo").fetchall()
    registros = {r["codigo"]: r for r in (_registro(linha) for linha in linhas)}
    return [registros[c] for c in PADROES if c in registros] + [
        r for c, r in registros.items() if c not in PADROES
    ]


def obter(codigo: str) -> dict[str, Any] | None:
    with banco.conectar() as con:
        linha = con.execute(f"SELECT * FROM {TABELA} WHERE codigo = ?", (codigo,)).fetchone()
    return _registro(linha) if linha else None


def texto_do_modelo(codigo: str) -> str | None:
    """Texto a usar no envio: o salvo, se ativo; o padrão quando a tabela não responde."""
    try:
        registro = obter(codigo)
    except Exception:  # noqa: BLE001 - sem tabela, o texto padrão ainda serve
        registro = None
    if registro is None:
        return PADROES.get(codigo, {}).get("texto")
    return registro["texto"] if registro["ativo"] else None


def texto_personalizado(codigo: str) -> str | None:
    """Só o texto que o escritório EDITOU (para os envios que já tinham texto em código)."""
    agora = time.monotonic()
    em_cache = _cache.get(codigo)
    if em_cache and agora - em_cache[0] < _CACHE_S:
        return em_cache[1]
    try:
        registro = obter(codigo)
    except Exception:  # noqa: BLE001
        registro = None
    valor = registro["texto"] if registro and registro["ativo"] and registro["personalizado"] else None
    _cache[codigo] = (agora, valor)
    return valor


def salvar(codigo: str, *, texto: str, ativo: bool, versao: int, usuario: str) -> dict[str, Any]:
    texto = (texto or "").strip()
    if not texto:
        raise HTTPException(422, "O texto do modelo não pode ficar vazio.")
    if len(texto) > 3000:
        raise HTTPException(422, "Texto longo demais para uma mensagem de WhatsApp.")
    with banco.conectar() as con:
        alteradas = con.execute(
            f"""UPDATE {TABELA} SET texto = ?, ativo = ?, versao = versao + 1,
                       atualizado_em = ?, atualizado_por = ?
                 WHERE codigo = ? AND versao = ?""",
            (texto, int(ativo), _agora(), usuario[:200], codigo, int(versao)),
        ).rowcount
    if not alteradas:
        if obter(codigo) is None:
            raise HTTPException(404, "Modelo não encontrado.")
        raise HTTPException(409, "O modelo foi alterado por outra pessoa. Recarregue.")
    _cache.pop(codigo, None)
    return obter(codigo) or {}


class _Seguro(dict):
    """Variável desconhecida fica como está, em vez de derrubar o envio."""

    def __missing__(self, chave: str) -> str:
        return "{" + chave + "}"


def renderizar(texto: str, contexto: dict[str, Any]) -> str:
    valores = {k: ("" if v is None else str(v)) for k, v in (contexto or {}).items()}
    valores.setdefault("escritorio", os.getenv("ESCRITORIO_NOME", "LARA & MELO"))
    cliente = valores.get("cliente", "")
    valores.setdefault("primeiro_nome", (cliente.strip().split(" ")[0] if cliente.strip() else "") or "tudo bem")
    try:
        return texto.format_map(_Seguro(valores))
    except (ValueError, IndexError):
        # Chave mal formada ("{ ", "{0}") — manda o texto cru a mandar nada.
        return texto


def contexto_do_atendimento(registro: dict[str, Any], **extra: Any) -> dict[str, Any]:
    from . import atendimentos

    data = atendimentos.ler_data(registro.get("data_hora"))
    local = data.astimezone(FUSO) if data else None
    contexto = {
        "cliente": registro.get("cliente") or "",
        "data": local.strftime("%d/%m/%Y") if local else "",
        "hora": local.strftime("%H:%M") if local else "",
        "link_sala": registro.get("link_cliente") or (
            atendimentos.url_cliente(registro["sala"]) if registro.get("sala") else ""
        ),
    }
    contexto.update(extra)
    return contexto


def enviar_modelo_sync(
    codigo: str,
    *,
    telefone: str,
    chave: str,
    contexto: dict[str, Any],
    atendimento_id: str | None = None,
    caso_id: str | None = None,
    forcar: bool = False,
    texto: str | None = None,
) -> dict[str, Any]:
    """Envia um modelo com rastreio. Nunca levanta: o status diz o que aconteceu.

    `status`: enviado | ja_enviado | destinatario_invalido | desativado | falhou | sem_whatsapp.
    """
    from . import whatsapp

    if not whatsapp.configurado():
        return {"status": "sem_whatsapp", "enviado": False, "motivo": "WhatsApp não configurado."}
    corpo = texto if texto is not None else texto_do_modelo(codigo)
    if not corpo:
        return {"status": "desativado", "enviado": False, "motivo": "Modelo desativado."}
    mensagem = renderizar(corpo, contexto)
    numero: str | None = None
    motivo = ""
    try:
        numero = whatsapp._numero_brasileiro(telefone or "")
    except HTTPException as erro:
        motivo = str(erro.detail)
    if numero is not None and whatsapp.numero_tem_whatsapp_sync(numero) is False:
        motivo = "O número não tem WhatsApp."
    if motivo:
        if automacoes_whatsapp.reservar(
            chave, codigo, numero or (telefone or "")[:30], caso_id, forcar,
            atendimento_id=atendimento_id, texto=mensagem,
        ):
            automacoes_whatsapp.finalizar(
                chave, motivo, status_entrega=automacoes_whatsapp.DESTINATARIO_INVALIDO
            )
        return {"status": "destinatario_invalido", "enviado": False, "motivo": motivo}
    if not automacoes_whatsapp.reservar(
        chave, codigo, numero, caso_id, forcar, atendimento_id=atendimento_id, texto=mensagem,
    ):
        envio = automacoes_whatsapp.obter_envio(chave) or {}
        return {"status": "ja_enviado", "enviado": False, "envio": envio}
    try:
        resposta = whatsapp._enviar_texto_sync(numero, mensagem)
    except Exception as erro:  # noqa: BLE001
        automacoes_whatsapp.finalizar(chave, str(erro)[:500])
        return {"status": "falhou", "enviado": False, "motivo": str(erro)[:300]}
    automacoes_whatsapp.finalizar(chave, mensagem_id=whatsapp.id_da_mensagem(resposta))
    return {"status": "enviado", "enviado": True, "envio": automacoes_whatsapp.obter_envio(chave)}


def chave_confirmacao(atendimento_id: str, data_hora: str | None) -> str:
    return f"confirmacao:{atendimento_id}:{data_hora or ''}"


def enviar_confirmacao(registro: dict[str, Any], *, forcar: bool = False) -> dict[str, Any]:
    if not registro.get("telefone"):
        return {"status": "sem_telefone", "enviado": False, "motivo": "Agendamento sem telefone."}
    return enviar_modelo_sync(
        "confirmacao_agendamento",
        telefone=registro["telefone"],
        chave=chave_confirmacao(registro["id"], registro.get("data_hora")),
        contexto=contexto_do_atendimento(registro),
        atendimento_id=registro["id"],
        forcar=forcar,
    )


def chave_avaliacao(atendimento_id: str) -> str:
    return f"avaliacao-google:{atendimento_id}"


def estado_avaliacao(atendimento_id: str) -> dict[str, Any]:
    """pendente | enviado | entregue | lido | falhou — o que a etapa de avaliação mostra."""
    envio = automacoes_whatsapp.obter_envio(chave_avaliacao(atendimento_id))
    if envio is None:
        return {"status": "pendente", "envio": None}
    entrega = str(envio.get("status_entrega") or "").upper()
    if envio.get("status") == "falhou" or entrega in automacoes_whatsapp.REENVIAVEIS:
        status = "falhou"
    elif entrega == automacoes_whatsapp.LIDO:
        status = "lido"
    elif entrega == automacoes_whatsapp.ENTREGUE:
        status = "entregue"
    elif envio.get("status") == "enviado":
        status = "enviado"
    else:
        status = "pendente"
    return {"status": status, "envio": envio}


def enviar_avaliacao(registro: dict[str, Any], telefone: str, *, forcar: bool = False) -> dict[str, Any]:
    from . import whatsapp

    atual = estado_avaliacao(registro["id"])
    envio = atual.get("envio") or {}
    reenviavel = str(envio.get("status_entrega") or "").upper() in automacoes_whatsapp.REENVIAVEIS
    resultado = enviar_modelo_sync(
        "avaliacao_google",
        telefone=telefone,
        chave=chave_avaliacao(registro["id"]),
        contexto=contexto_do_atendimento(registro, link=whatsapp.LINK_AVALIACAO),
        atendimento_id=registro["id"],
        forcar=forcar or reenviavel,
        texto=whatsapp.texto_avaliacao(registro.get("cliente") or ""),
    )
    resultado["avaliacao"] = estado_avaliacao(registro["id"])
    return resultado


# ------------------------------------------------------------------ webhook

#: Evolution v1 manda o status como número (0 erro ... 5 tocado).
_STATUS_NUMERICO = {0: "FALHOU", 1: "PROCESSANDO", 2: "ENVIADO", 3: "ENTREGUE", 4: "LIDO", 5: "LIDO"}
_STATUS_TEXTO = {
    "ERROR": "FALHOU", "FAILED": "FALHOU", "PENDING": "PROCESSANDO",
    "SERVER_ACK": "ENVIADO", "DELIVERY_ACK": "ENTREGUE", "DELIVERED": "ENTREGUE",
    "READ": "LIDO", "PLAYED": "LIDO",
}


def _status_normalizado(bruto: Any) -> str | None:
    if isinstance(bruto, bool):
        return None
    if isinstance(bruto, int):
        return _STATUS_NUMERICO.get(bruto)
    texto = str(bruto or "").strip().upper()
    if texto.isdigit():
        return _STATUS_NUMERICO.get(int(texto))
    return _STATUS_TEXTO.get(texto)


def interpretar_webhook(corpo: dict[str, Any]) -> list[tuple[str, str]]:
    """(mensagem_id, status) de um `messages.update` da Evolution v1 ou v2."""
    evento = str(corpo.get("event") or "").lower().replace("_", ".")
    if evento and evento != "messages.update":
        return []
    dados = corpo.get("data")
    itens = dados if isinstance(dados, list) else [dados] if isinstance(dados, dict) else []
    saida: list[tuple[str, str]] = []
    for item in itens:
        if not isinstance(item, dict):
            continue
        chave = item.get("key") if isinstance(item.get("key"), dict) else {}
        mensagem_id = item.get("keyId") or chave.get("id") or item.get("id")
        atualizacao = item.get("update") if isinstance(item.get("update"), dict) else {}
        status = _status_normalizado(item.get("status", atualizacao.get("status")))
        if mensagem_id and status:
            saida.append((str(mensagem_id)[:120], status))
    return saida


def processar_webhook(corpo: dict[str, Any]) -> int:
    alteradas = 0
    for mensagem_id, status in interpretar_webhook(corpo):
        try:
            alteradas += automacoes_whatsapp.atualizar_entrega(mensagem_id, status)
        except Exception:  # noqa: BLE001 - webhook nunca devolve 500 para a Evolution
            log.warning("Falha ao gravar entrega %s.", mensagem_id, exc_info=True)
    return alteradas


# ------------------------------------------------------------------- rotas

roteador = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])
PodeConfigurar = Depends(auth.exigir_algum_modulo("whatsapp", "entrevista"))


class EdicaoModelo(BaseModel):
    texto: str = Field(..., min_length=1, max_length=3000)
    ativo: bool = True
    versao: int


class Previa(BaseModel):
    texto: str | None = Field(None, max_length=3000)
    cliente: str = Field("Maria Silva", max_length=200)


def _nome(usuario: auth.Usuario) -> str:
    return usuario.nome or usuario.email or usuario.id or "escritório"


@roteador.get("/modelos", dependencies=[Depends(auth.usuario_atual)])
def rota_listar_modelos() -> dict[str, Any]:
    return {"modelos": listar(), "variaveis": list(VARIAVEIS)}


@roteador.put("/modelos/{codigo}")
def rota_salvar_modelo(
    codigo: str, pedido: EdicaoModelo, usuario: auth.Usuario = PodeConfigurar
) -> dict[str, Any]:
    return salvar(codigo, texto=pedido.texto, ativo=pedido.ativo, versao=pedido.versao,
                  usuario=_nome(usuario))


@roteador.post("/modelos/{codigo}/restaurar")
def rota_restaurar_modelo(codigo: str, usuario: auth.Usuario = PodeConfigurar) -> dict[str, Any]:
    padrao = PADROES.get(codigo)
    atual = obter(codigo)
    if padrao is None or atual is None:
        raise HTTPException(404, "Modelo sem texto padrão.")
    return salvar(codigo, texto=padrao["texto"], ativo=True, versao=atual["versao"],
                  usuario=_nome(usuario))


@roteador.post("/modelos/{codigo}/previa", dependencies=[Depends(auth.usuario_atual)])
def rota_previa(codigo: str, pedido: Previa) -> dict[str, Any]:
    texto = pedido.texto if pedido.texto is not None else texto_do_modelo(codigo)
    if texto is None:
        raise HTTPException(404, "Modelo não encontrado ou desativado.")
    from . import whatsapp

    exemplo = {
        "cliente": pedido.cliente,
        "data": "15/10/2026",
        "hora": "14:30",
        "link_sala": f"{whatsapp.URL_PORTAL}/chamada/exemplo",
        "link": whatsapp.LINK_AVALIACAO if codigo == "avaliacao_google" else f"{whatsapp.URL_PORTAL}/portal/exemplo",
        "documentos": "- RG\n- Comprovante de residência",
    }
    return {"texto": renderizar(texto, exemplo)}


@roteador.get("/historico", dependencies=[Depends(auth.usuario_atual)])
def rota_historico(
    dias: int = Query(30, ge=1, le=365),
    tipo: str | None = Query(None, max_length=60),
    atendimento_id: str | None = Query(None, max_length=64),
    caso_id: str | None = Query(None, max_length=64),
) -> dict[str, Any]:
    return {
        "envios": automacoes_whatsapp.historico(
            dias=dias, tipo=tipo, atendimento_id=atendimento_id, caso_id=caso_id
        )
    }


@roteador.post("/webhook")
async def rota_webhook(token: str = Query("", max_length=200),
                       corpo: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    """Pública (a Evolution não tem login), protegida pelo token da URL."""
    esperado = os.getenv("WHATSAPP_WEBHOOK_TOKEN", "")
    if not esperado or not secrets.compare_digest(token, esperado):
        raise HTTPException(403, "Token do webhook inválido.")
    alteradas = await run_in_threadpool(processar_webhook, corpo)
    return {"ok": True, "atualizadas": alteradas}
