"""Estado durável das automações de WhatsApp.

O texto de cobrança não é armazenado: ele é remontado a partir do checklist no
instante do envio. Assim, cada documento recebido altera automaticamente a
próxima mensagem, sem o atendente precisar editar uma cópia antiga.
"""

from __future__ import annotations

import logging

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pyodbc

from . import armazenamento
from .banco import conectar

log = logging.getLogger(__name__)
FUSO_NEGOCIO = ZoneInfo("America/Sao_Paulo")


def _agora_dt() -> datetime:
    return datetime.now(timezone.utc)


def _iso(valor: datetime | None = None) -> str:
    return (valor or _agora_dt()).isoformat()


def reservar(
    chave: str, tipo: str, destino: str, caso_id: str | None = None, forcar: bool = False
) -> bool:
    """Reserva um envio, impedindo duplicidade entre API e workers concorrentes.

    `forcar` libera um reenvio deliberado: um envio já CONCLUÍDO ('enviado')
    deixa de barrar a operação — é o caso do atendente que, com o cliente ainda
    na chamada, pede o link de novo. O que nunca é liberado é um envio EM
    ANDAMENTO ('enviando'): essa continua sendo a defesa contra clique duplo e
    corrida entre a API e o worker.
    """
    instante = _iso()
    try:
        with conectar() as con:
            # UPDATE condicional é uma única operação no banco. O antigo
            # SELECT seguido de UPDATE deixava dois workers lerem "falhou" e
            # ambos reservarem a mesma chave.
            atualizada = con.execute(
                """UPDATE automacoes_whatsapp
                      SET status = 'enviando', tentativas = tentativas + 1,
                          ultimo_erro = NULL, atualizado_em = ?
                   OUTPUT inserted.chave
                    WHERE chave = ?
                      AND status <> 'enviando'
                      AND (? = 1 OR status <> 'enviado')""",
                (instante, chave, int(forcar)),
            ).fetchone()
            if atualizada:
                return True
            con.execute(
                """INSERT INTO automacoes_whatsapp
                   (chave, tipo, caso_id, destino, status, tentativas, criado_em, atualizado_em)
                   VALUES (?, ?, ?, ?, 'enviando', 1, ?, ?)""",
                (chave, tipo, caso_id, destino, instante, instante),
            )
        return True
    except pyodbc.IntegrityError:
        return False


def finalizar(chave: str, erro: str | None = None) -> None:
    instante = _iso()
    with conectar() as con:
        con.execute(
            """UPDATE automacoes_whatsapp
                  SET status = ?, ultimo_erro = ?, enviado_em = ?, atualizado_em = ?
                WHERE chave = ?""",
            ("falhou" if erro else "enviado", erro, None if erro else instante, instante, chave),
        )


def telefone_do_caso(caso_id: str) -> str:
    """O WhatsApp que a entrevista colheu, recuperado do caso.

    DOIS LUGARES, NESTA ORDEM

    1. **A coluna `casos.telefone`**, gravada quando o caso nasce do
       atendimento: a entrevista pergunta o telefone (obrigatória, no roteiro) e
       agora ele viaja junto na criação do caso. É a fonte que existe desde o
       primeiro minuto, antes de haver contrato.
    2. **O signatário da assinatura**, que era a única fonte até aqui. O
       contrato é montado com as respostas, e `assinatura.montar_signatario`
       grava `phone_country` e `phone_number`. Continua valendo para os casos
       abertos antes desta coluna existir e para os que foram criados à mão pela
       carteira, sem passar pela entrevista.

    A ordem importa: a assinatura só aparece depois que o contrato vai para a
    ZapSign, e até lá a cobrança automática abria com o campo em branco pedindo
    um número que o cliente já tinha ditado. Era o tipo de retrabalho que faz o
    recurso ficar desligado porque ninguém preencheu o campo.

    Vazio quando as duas fontes falham — aí o campo continua para digitar à mão,
    como antes.
    """
    try:
        caso = armazenamento.obter_caso(caso_id)
        do_cadastro = str((caso or {}).get("telefone") or "").strip()
        if do_cadastro:
            return do_cadastro
    except Exception:
        # Cai para a assinatura: banco antigo, sem a coluna, não pode derrubar a
        # única fonte que já funcionava.
        log.debug("Não foi possível ler o telefone do caso %s.", caso_id, exc_info=True)

    try:
        assinaturas = armazenamento.listar_assinaturas(caso_id=caso_id)
        if not assinaturas:
            # Nome sozinho não identifica: um homônimo receberia a lista e o
            # link de portal de outra pessoa. Para legado sem `caso_id`, exige o
            # mesmo par nome + CPF usado pelo painel de assinaturas.
            caso = armazenamento.obter_caso(caso_id)
            qualificacao = armazenamento.obter_qualificacao(caso_id) or {}
            cliente = str((caso or {}).get("cliente") or "").strip()
            cpf = str(qualificacao.get("cpf") or "").strip()
            if cliente and cpf:
                assinaturas = armazenamento.listar_assinaturas(cliente=cliente, cpf=cpf)
    except Exception:
        log.debug("Não foi possível procurar o telefone do caso %s.", caso_id, exc_info=True)
        return ""

    for registro in assinaturas:
        for signatario in registro.get("signatarios") or []:
            # DOIS FORMATOS, e a diferença já enganou: `phone_number` /
            # `phone_country` é o payload que vai PARA a ZapSign (ver
            # `assinatura.montar_signatario`); o que fica GRAVADO na coluna
            # `signatarios` é a forma interna, com `telefone` num campo só.
            # Ler os dois cobre registro antigo e registro novo.
            numero = str(
                signatario.get("telefone") or signatario.get("phone_number") or ""
            ).strip()
            if not numero:
                continue
            ddi = str(signatario.get("phone_country") or "").strip()
            # O `_numero_brasileiro` do `whatsapp.py` acrescenta o 55 sozinho
            # quando o número vem com 10 ou 11 dígitos, então o caso comum não
            # precisa de prefixo. DDI estrangeiro (raro, mas existe) vai junto
            # para não virar um telefone brasileiro inventado.
            return f"+{ddi}{numero}" if ddi and ddi != "55" else numero
    return ""


def obter_cobranca(caso_id: str) -> dict[str, Any]:
    with conectar() as con:
        linha = con.execute(
            "SELECT * FROM cobrancas_documentos WHERE caso_id = ?", (caso_id,)
        ).fetchone()
    if not linha:
        return {
            "caso_id": caso_id, "ativa": False,
            # Já vem preenchido na primeira abertura da tela: o número é o mesmo
            # que o cliente ditou na entrevista.
            "telefone": telefone_do_caso(caso_id), "intervalo_dias": 3,
            "intervalo_horas": 24, "max_envios_dia": 1,
            "incluir_opcionais": False, "proximo_envio_em": None,
            "ultimo_envio_em": None, "ultimo_erro": None,
        }
    intervalo_dias = int(linha["intervalo_dias"])
    intervalo_horas_salvo = linha.get("intervalo_horas")
    intervalo_horas = int(intervalo_horas_salvo or 0) or intervalo_dias * 24
    # Uma versão intermediária da migração criou a coluna com DEFAULT 24. Para
    # linha antiga de 2+ dias, 24 não foi escolha do gestor: foi preenchimento
    # automático do schema. A UI nova sempre salva 24h junto com 1 dia.
    if intervalo_horas == 24 and intervalo_dias > 1:
        intervalo_horas = intervalo_dias * 24
    return {
        "caso_id": linha["caso_id"], "ativa": bool(linha["ativa"]),
        # O cadastro atual vence. O número salvo só cobre configuração antiga
        # enquanto o caso ainda não tiver uma fonte identificável e segura.
        "telefone": telefone_do_caso(caso_id) or linha["telefone"],
        "intervalo_dias": intervalo_dias,
        "intervalo_horas": max(1, intervalo_horas),
        "max_envios_dia": max(1, int(linha.get("max_envios_dia") or 1)),
        "incluir_opcionais": bool(linha["incluir_opcionais"]),
        "proximo_envio_em": linha["proximo_envio_em"],
        "ultimo_envio_em": linha["ultimo_envio_em"], "ultimo_erro": linha["ultimo_erro"],
    }


def salvar_cobranca(
    caso_id: str, *, ativa: bool, telefone: str, intervalo_dias: int,
    incluir_opcionais: bool, intervalo_horas: int | None = None,
    max_envios_dia: int = 1,
) -> dict[str, Any]:
    instante = _iso()
    intervalo_horas = max(1, min(int(intervalo_horas or intervalo_dias * 24), 24 * 30))
    max_envios_dia = max(1, min(int(max_envios_dia or 1), 6))
    with conectar() as con:
        existe = con.execute(
            "SELECT caso_id, ativa, proximo_envio_em FROM cobrancas_documentos WHERE caso_id = ?",
            (caso_id,),
        ).fetchone()
        # Alterar frequência não dispara cobrança imediatamente. Só a transição
        # desligada -> ativa agenda para agora; desativar limpa a agenda.
        proximo = None
        if ativa:
            proximo = (
                existe["proximo_envio_em"]
                if existe and bool(existe["ativa"]) and existe["proximo_envio_em"]
                else instante
            )
        if existe:
            con.execute(
                """UPDATE cobrancas_documentos SET ativa = ?, telefone = ?, intervalo_dias = ?,
                   intervalo_horas = ?, max_envios_dia = ?, incluir_opcionais = ?,
                   proximo_envio_em = ?, ultimo_erro = NULL,
                   atualizado_em = ? WHERE caso_id = ?""",
                (
                    int(ativa), telefone, intervalo_dias, intervalo_horas,
                    max_envios_dia, int(incluir_opcionais), proximo, instante, caso_id,
                ),
            )
        else:
            con.execute(
                """INSERT INTO cobrancas_documentos
                   (caso_id, ativa, telefone, intervalo_dias, intervalo_horas,
                    max_envios_dia, incluir_opcionais,
                    proximo_envio_em, criado_em, atualizado_em)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    caso_id, int(ativa), telefone, intervalo_dias, intervalo_horas,
                    max_envios_dia, int(incluir_opcionais), proximo, instante, instante,
                ),
            )
    return obter_cobranca(caso_id)


def listar_cobrancas_vencidas() -> list[dict[str, Any]]:
    """As cobranças no ponto de enviar, já com o telefone resolvido.

    O `telefone <> ''` saiu do SQL de propósito. Ele filtrava a coluna, que pode
    estar em branco num caso configurado ANTES de o contrato existir — e desde
    que `obter_cobranca` passou a recuperar o número da assinatura, esse caso
    aparecia ativo na tela, com o número à vista, e mesmo assim nunca era
    cobrado. Ficar "ligado" sem enviar nada é pior que não ligar.

    Agora o filtro é sobre o valor RESOLVIDO. Quem continuar sem número nenhum é
    descartado aqui, e não vira uma tentativa de envio fadada a falhar.
    """
    instante = _iso()
    with conectar() as con:
        linhas = con.execute(
            """SELECT caso_id FROM cobrancas_documentos
                WHERE ativa = 1
                  AND (proximo_envio_em IS NULL OR proximo_envio_em <= ?)""",
            (instante,),
        ).fetchall()
    resolvidas = [obter_cobranca(linha["caso_id"]) for linha in linhas]
    return [c for c in resolvidas if str(c.get("telefone") or "").strip()]


def registrar_resultado_cobranca(
    caso_id: str, intervalo_dias: int, texto_hash: str | None, erro: str | None = None,
    intervalo_horas: int | None = None,
    reagendar: bool = True,
) -> None:
    instante = _agora_dt()
    horas = max(1, int(intervalo_horas or intervalo_dias * 24))
    proximo = instante + timedelta(hours=horas)
    with conectar() as con:
        con.execute(
            """UPDATE cobrancas_documentos
                  SET proximo_envio_em = CASE WHEN ? = 1 THEN ? ELSE proximo_envio_em END,
                      ultimo_envio_em = COALESCE(?, ultimo_envio_em),
                      ultimo_hash = COALESCE(?, ultimo_hash),
                      ultimo_erro = ?, atualizado_em = ? WHERE caso_id = ?""",
            (
                int(reagendar),
                _iso(proximo),
                _iso(instante) if texto_hash and not erro else None,
                texto_hash,
                erro,
                _iso(instante),
                caso_id,
            ),
        )


def envios_de_cobranca_hoje(caso_id: str) -> int:
    """Quantas cobranças de documento já saíram hoje para este caso."""
    agora_local = _agora_dt().astimezone(FUSO_NEGOCIO)
    inicio = agora_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(
        timezone.utc
    )
    with conectar() as con:
        linha = con.execute(
            """SELECT COUNT(*) AS total FROM automacoes_whatsapp
                WHERE caso_id = ?
                  AND tipo = 'cobranca_documentos'
                  AND status = 'enviado'
                  AND enviado_em >= ?""",
            (caso_id, _iso(inicio)),
        ).fetchone()
    return int(linha["total"] if linha else 0)


def reagendar_cobranca_para_amanha(caso_id: str) -> None:
    """Evita reprocessar a mesma cobrança depois de bater o limite diário."""
    agora = _agora_dt()
    agora_local = agora.astimezone(FUSO_NEGOCIO)
    proximo = (agora_local + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc)
    with conectar() as con:
        con.execute(
            """UPDATE cobrancas_documentos
                  SET proximo_envio_em = ?, atualizado_em = ?
                WHERE caso_id = ?""",
            (_iso(proximo), _iso(agora), caso_id),
        )


def caso_existe(caso_id: str) -> bool:
    return armazenamento.obter_caso(caso_id) is not None
