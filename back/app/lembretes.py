"""Lembretes do agendamento: QUANDO mandar é cálculo puro, o envio é idempotente.

Cada lembrete tem um horário teórico ("slot") derivado só da data do atendimento
e da configuração — nada de "último envio + intervalo". Assim o worker pode
rodar a cada 5 minutos, cair, voltar duas horas depois ou rodar em dois
processos ao mesmo tempo: o slot é o mesmo, a chave `lembrete:{id}:{slot}` é a
mesma, e `automacoes_whatsapp.reservar` deixa passar uma única mensagem.

Só o slot vencido MAIS RECENTE é enviado. Worker parado por um dia não despeja,
ao voltar, três lembretes atrasados de uma vez no cliente.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from . import atendimentos as at

log = logging.getLogger("lembretes")

#: Um slot vale por até 3 h (ou até o atendimento começar). Depois disso o
#: lembrete perdeu o sentido e não sai mais.
JANELA_SLOT = timedelta(hours=3)
#: Lembretes diários antes da data: no máximo este número.
MAX_SLOTS_DIARIOS = 30


def slots(
    data_hora: datetime, config: dict[str, Any], criado_em: datetime | None = None
) -> list[datetime]:
    """Todos os horários teóricos de lembrete, em ordem crescente."""
    if not config.get("ativo", True):
        return []
    saida: set[datetime] = set()
    intervalo = int(config.get("intervalo_dias") or 0)
    if intervalo > 0:
        k = 1
        while k * intervalo <= MAX_SLOTS_DIARIOS:
            slot = data_hora - timedelta(days=k * intervalo)
            if criado_em is not None and slot < criado_em:
                break
            saida.add(slot)
            k += 1
    for minutos in config.get("minutos_antes_no_dia") or []:
        slot = data_hora - timedelta(minutes=int(minutos))
        if criado_em is None or slot >= criado_em:
            saida.add(slot)
    return sorted(saida)


def slot_devido(
    data_hora: datetime, config: dict[str, Any], agora: datetime,
    criado_em: datetime | None = None,
) -> datetime | None:
    """O slot a enviar AGORA, se houver: o mais recente já vencido e ainda na janela."""
    if agora >= data_hora:
        return None
    vencidos = [s for s in slots(data_hora, config, criado_em) if s <= agora]
    if not vencidos:
        return None
    ultimo = vencidos[-1]
    return ultimo if agora < min(ultimo + JANELA_SLOT, data_hora) else None


def chave(atendimento_id: str, slot: datetime) -> str:
    return f"lembrete:{atendimento_id}:{slot.astimezone(timezone.utc).isoformat(timespec='minutes')}"


def processar(agora: datetime | None = None) -> dict[str, int]:
    """Uma passada do worker. Nunca levanta por causa de um atendimento só."""
    from . import whatsapp_modelos

    agora = agora or datetime.now(timezone.utc)
    resultado = {"enviados": 0, "ja_enviados": 0, "falhas": 0, "invalidos": 0, "faltas_avisadas": 0}
    config_geral = at.obter_config()
    padrao_lembretes = config_geral["lembretes"]
    horizonte = (agora + timedelta(days=MAX_SLOTS_DIARIOS + 1)).isoformat(timespec="seconds")
    for registro in at.listar(estados=[at.AGENDADA], de=agora.isoformat(timespec="seconds"), ate=horizonte):
        if not registro.get("telefone"):
            continue
        data = at.ler_data(registro.get("data_hora"))
        if data is None:
            continue
        config = registro.get("config_lembretes") or padrao_lembretes
        slot = slot_devido(data, config, agora, at.ler_data(registro.get("criado_em")))
        if slot is None:
            continue
        try:
            envio = whatsapp_modelos.enviar_modelo_sync(
                "lembrete_agendamento",
                telefone=registro["telefone"],
                chave=chave(registro["id"], slot),
                contexto=whatsapp_modelos.contexto_do_atendimento(registro),
                atendimento_id=registro["id"],
            )
        except Exception:  # noqa: BLE001
            log.warning("Lembrete do atendimento %s falhou.", registro["id"], exc_info=True)
            resultado["falhas"] += 1
            continue
        status = envio.get("status")
        if status == "enviado":
            resultado["enviados"] += 1
        elif status == "ja_enviado":
            resultado["ja_enviados"] += 1
        elif status == "destinatario_invalido":
            resultado["invalidos"] += 1
        elif status == "falhou":
            resultado["falhas"] += 1
    if config_geral.get("enviar_falta_automatico"):
        resultado["faltas_avisadas"] = avisar_faltas(agora)
    return resultado


def avisar_faltas(agora: datetime) -> int:
    """Mensagem de "sentimos sua falta" para quem faltou nas últimas 24 h. Uma por atendimento."""
    from . import whatsapp_modelos

    desde = (agora - timedelta(days=1)).isoformat(timespec="seconds")
    enviados = 0
    for registro in at.listar(estados=[at.CLIENTE_FALTOU], de=desde, ate=agora.isoformat(timespec="seconds")):
        if not registro.get("telefone"):
            continue
        envio = whatsapp_modelos.enviar_modelo_sync(
            "cliente_faltou",
            telefone=registro["telefone"],
            chave=f"cliente-faltou:{registro['id']}:{registro.get('data_hora') or ''}",
            contexto=whatsapp_modelos.contexto_do_atendimento(registro),
            atendimento_id=registro["id"],
        )
        if envio.get("status") == "enviado":
            enviados += 1
    return enviados
