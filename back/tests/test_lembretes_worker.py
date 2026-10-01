"""Worker de lembretes, status de entrega e reenvio seguro (cenários 2 e 21)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app import automacoes_whatsapp, lembretes, whatsapp_modelos
from app import atendimentos as at

AGORA = datetime.now(timezone.utc).replace(microsecond=0)


def _agendar(horas: float, lembretes_cfg: dict | None = None, telefone: str = "61999998888") -> dict:
    return at.criar(
        cliente="José da Silva", telefone=telefone,
        data_hora=(AGORA + timedelta(hours=horas)).isoformat(),
        responsavel_id="u-maria", responsavel_nome="Maria", config_lembretes=lembretes_cfg,
    )


# ------------------------------------------------------------ cálculo puro


def test_cenario_2_slots_seguem_a_configuracao_salva():
    data = datetime(2026, 10, 20, 17, 0, tzinfo=timezone.utc)
    config = {"ativo": True, "intervalo_dias": 3, "minutos_antes_no_dia": [120, 30]}
    criado = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)

    assert lembretes.slots(data, config, criado) == [
        data - timedelta(days=9), data - timedelta(days=6), data - timedelta(days=3),
        data - timedelta(minutes=120), data - timedelta(minutes=30),
    ]
    assert lembretes.slots(data, {**config, "intervalo_dias": 1}, data - timedelta(days=2)) == [
        data - timedelta(days=2), data - timedelta(days=1),
        data - timedelta(minutes=120), data - timedelta(minutes=30),
    ]
    assert lembretes.slots(data, {**config, "ativo": False}) == []


def test_so_o_slot_vencido_mais_recente_e_enviado():
    data = datetime(2026, 10, 20, 17, 0, tzinfo=timezone.utc)
    config = {"ativo": True, "intervalo_dias": 1, "minutos_antes_no_dia": [120, 30]}
    # Worker parado desde a véspera: volta 20 min antes do atendimento.
    agora = data - timedelta(minutes=20)
    assert lembretes.slot_devido(data, config, agora) == data - timedelta(minutes=30)
    # Depois do horário, nada.
    assert lembretes.slot_devido(data, config, data + timedelta(minutes=1)) is None
    # Slot diário vencido há mais de 3 h perdeu o sentido.
    assert lembretes.slot_devido(data, {"intervalo_dias": 1}, data - timedelta(hours=20)) is None


def test_lembretes_do_agendamento_sobrescrevem_o_padrao(banco_sqlite):
    at.salvar_config({"lembretes": {"ativo": True, "intervalo_dias": 3, "minutos_antes_no_dia": [60]}}, "teste")
    proprio = _agendar(5, {"ativo": True, "intervalo_dias": 0, "minutos_antes_no_dia": [240, 15]})
    padrao = _agendar(5)

    assert proprio["config_lembretes"] == {"ativo": True, "intervalo_dias": 0, "minutos_antes_no_dia": [240, 15]}
    assert padrao["config_lembretes"] is None
    assert at.obter_config()["lembretes"]["minutos_antes_no_dia"] == [60]


# ------------------------------------------------------------------ worker


def test_cenario_21_worker_nao_envia_lembrete_duplicado(banco_sqlite, whatsapp_falso):
    _agendar(3, {"ativo": True, "intervalo_dias": 0, "minutos_antes_no_dia": [120, 30]})
    no_slot_de_2h = AGORA + timedelta(minutes=70)

    primeira = lembretes.processar(no_slot_de_2h)
    segunda = lembretes.processar(no_slot_de_2h + timedelta(minutes=5))

    assert primeira["enviados"] == 1
    assert segunda == {**segunda, "enviados": 0, "ja_enviados": 1}
    assert len(whatsapp_falso.enviadas) == 1
    numero, texto = whatsapp_falso.enviadas[0]
    assert numero == "5561999998888"
    assert "José" in texto and "/chamada/" in texto

    # O slot seguinte é outra chave: sai uma vez, e só uma.
    no_slot_de_30 = AGORA + timedelta(minutes=155)
    assert lembretes.processar(no_slot_de_30)["enviados"] == 1
    assert lembretes.processar(no_slot_de_30)["ja_enviados"] == 1
    assert len(whatsapp_falso.enviadas) == 2
    historico = automacoes_whatsapp.historico(dias=1, tipo="lembrete_agendamento")
    assert len(historico) == 2
    assert {h["status_entrega"] for h in historico} == {automacoes_whatsapp.ENVIADO}


def test_worker_ignora_atendimento_cancelado_ou_iniciado(banco_sqlite, whatsapp_falso):
    cancelado = _agendar(3, {"ativo": True, "intervalo_dias": 0, "minutos_antes_no_dia": [120]})
    iniciado = _agendar(3, {"ativo": True, "intervalo_dias": 0, "minutos_antes_no_dia": [120]})
    at.transicionar(cancelado["id"], at.CANCELADA)
    at.iniciar_atendimento(iniciado["id"], "u-maria", "Maria")

    assert lembretes.processar(AGORA + timedelta(minutes=70))["enviados"] == 0
    assert whatsapp_falso.enviadas == []


def test_destinatario_sem_whatsapp_vira_status_proprio(banco_sqlite, whatsapp_falso):
    whatsapp_falso.sem_whatsapp.add("5561988887777")
    _agendar(3, {"ativo": True, "intervalo_dias": 0, "minutos_antes_no_dia": [120]}, telefone="61988887777")

    resultado = lembretes.processar(AGORA + timedelta(minutes=70))

    assert resultado["invalidos"] == 1
    assert whatsapp_falso.enviadas == []
    envio = automacoes_whatsapp.historico(dias=1)[0]
    assert envio["status_entrega"] == automacoes_whatsapp.DESTINATARIO_INVALIDO


# ------------------------------------------------ entrega e reenvio seguro


def test_webhook_atualiza_a_entrega_sem_voltar_atras(banco_sqlite, whatsapp_falso):
    registro = _agendar(24)
    assert whatsapp_modelos.enviar_confirmacao(registro)["status"] == "enviado"
    chave = whatsapp_modelos.chave_confirmacao(registro["id"], registro["data_hora"])

    assert whatsapp_modelos.processar_webhook(
        {"event": "messages.update", "data": {"keyId": "MSG1", "status": "DELIVERY_ACK"}}
    ) == 1
    assert automacoes_whatsapp.obter_envio(chave)["status_entrega"] == automacoes_whatsapp.ENTREGUE
    # Evolution v1: status numérico, formato com `key.id`.
    whatsapp_modelos.processar_webhook({"event": "MESSAGES_UPDATE", "data": [{"key": {"id": "MSG1"}, "update": {"status": 4}}]})
    envio = automacoes_whatsapp.obter_envio(chave)
    assert envio["status_entrega"] == automacoes_whatsapp.LIDO and envio["lido_em"]
    # Um "entregue" atrasado não rebaixa o "lido".
    assert whatsapp_modelos.processar_webhook({"event": "messages.update", "data": {"keyId": "MSG1", "status": "DELIVERY_ACK"}}) == 0
    # Evento de outro tipo e mensagem desconhecida são ignorados.
    assert whatsapp_modelos.processar_webhook({"event": "connection.update", "data": {}}) == 0
    assert whatsapp_modelos.processar_webhook({"event": "messages.update", "data": {"keyId": "X", "status": "READ"}}) == 0


def test_webhook_exige_token(banco_sqlite, monkeypatch):
    monkeypatch.setenv("WHATSAPP_WEBHOOK_TOKEN", "segredo-do-webhook")
    with pytest.raises(HTTPException) as erro:
        asyncio.run(whatsapp_modelos.rota_webhook(token="errado", corpo={}))
    assert erro.value.status_code == 403
    assert asyncio.run(whatsapp_modelos.rota_webhook(token="segredo-do-webhook", corpo={}))["ok"] is True


def test_reenvio_so_com_confirmacao_explicita_ou_apos_falha(banco_sqlite, whatsapp_falso):
    registro = _agendar(24)
    assert whatsapp_modelos.enviar_confirmacao(registro)["status"] == "enviado"
    assert whatsapp_modelos.enviar_confirmacao(registro)["status"] == "ja_enviado"
    assert whatsapp_modelos.enviar_confirmacao(registro, forcar=True)["status"] == "enviado"
    assert len(whatsapp_falso.enviadas) == 2

    # Falhou: o próximo pedido reenvia sem precisar forçar.
    whatsapp_falso.falhar = True
    assert whatsapp_modelos.enviar_avaliacao(registro, registro["telefone"])["status"] == "falhou"
    assert whatsapp_modelos.estado_avaliacao(registro["id"])["status"] == "falhou"
    whatsapp_falso.falhar = False
    resultado = whatsapp_modelos.enviar_avaliacao(registro, registro["telefone"])
    assert resultado["status"] == "enviado"
    assert resultado["avaliacao"]["status"] == "enviado"
    assert whatsapp_modelos.enviar_avaliacao(registro, registro["telefone"])["status"] == "ja_enviado"


def test_envio_orfao_em_andamento_volta_a_ser_reservavel(banco_sqlite):
    assert automacoes_whatsapp.reservar("teste:orfao", "lembrete_agendamento", "5561999998888")
    assert not automacoes_whatsapp.reservar("teste:orfao", "lembrete_agendamento", "5561999998888", forcar=True)
    velho = (datetime.now(timezone.utc) - timedelta(minutes=automacoes_whatsapp.MINUTOS_ENVIO_ORFAO + 1)).isoformat()
    with banco_sqlite:
        banco_sqlite.execute(
            "UPDATE dbo.acervo_automacoes_whatsapp SET atualizado_em = ? WHERE chave = 'teste:orfao'", (velho,)
        )
    assert automacoes_whatsapp.reservar("teste:orfao", "lembrete_agendamento", "5561999998888")
    assert automacoes_whatsapp.obter_envio("teste:orfao")["tentativas"] == 2


def test_modelo_desativado_nao_envia(banco_sqlite, whatsapp_falso):
    modelo = whatsapp_modelos.obter("lembrete_agendamento")
    whatsapp_modelos.salvar("lembrete_agendamento", texto=modelo["texto"], ativo=False,
                            versao=modelo["versao"], usuario="teste")
    _agendar(3, {"ativo": True, "intervalo_dias": 0, "minutos_antes_no_dia": [120]})

    lembretes.processar(AGORA + timedelta(minutes=70))

    assert whatsapp_falso.enviadas == []


def test_modelo_editado_com_versao_antiga_e_recusado(banco_sqlite):
    modelo = whatsapp_modelos.obter("confirmacao_agendamento")
    whatsapp_modelos.salvar("confirmacao_agendamento", texto="Olá {cliente}", ativo=True,
                            versao=modelo["versao"], usuario="teste")
    with pytest.raises(HTTPException) as erro:
        whatsapp_modelos.salvar("confirmacao_agendamento", texto="Oi", ativo=True,
                                versao=modelo["versao"], usuario="teste")
    assert erro.value.status_code == 409
    assert whatsapp_modelos.renderizar("Olá {primeiro_nome}, {desconhecida}", {"cliente": "Ana Lima"}) == "Olá Ana, {desconhecida}"
