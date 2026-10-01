"""Presença na sala e ciclo de vida dos alertas (cenários 3, 4, 5, 19, 20 e escalonamento)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import alertas
from app import atendimentos as at


def _agendado() -> dict:
    return at.criar(
        cliente="José da Silva", telefone="61999998888",
        data_hora=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(timespec="seconds"),
        responsavel_id="u-maria", responsavel_nome="Maria",
    )


def _linhas_de_alerta(banco, atendimento_id: str) -> list[tuple]:
    return banco.execute(
        "SELECT tipo, resolvido_em, motivo_resolucao FROM dbo.acervo_alertas WHERE atendimento_id = ? ORDER BY criado_em, tipo",
        (atendimento_id,),
    ).fetchall()


def test_cenario_3_cliente_entra_antes_do_responsavel_avisa_o_responsavel(banco_sqlite):
    registro = _agendado()

    depois = at.presenca_do_cliente(registro["sala"], "entrou")

    assert depois["estado"] == at.CLIENTE_AGUARDANDO
    do_responsavel = alertas.ativos_para("u-maria", set())
    assert len(do_responsavel) == 1
    alerta = do_responsavel[0]
    assert alerta["tipo"] == alertas.CLIENTE_AGUARDANDO
    assert alerta["titulo"] == "José da Silva entrou na sala da entrevista"
    assert alerta["acao"] == "entrar"
    assert alerta["dados"]["sala"] == registro["sala"]
    # Ainda dentro do prazo de escalonamento: o resto da equipe não é incomodado.
    assert alertas.ativos_para("u-joao", {"entrevista"}) == []


def test_cenario_4_responsavel_entra_e_o_alerta_se_resolve(banco_sqlite):
    registro = _agendado()
    at.presenca_do_cliente(registro["sala"], "entrou")

    depois = at.presenca_do_escritorio(registro["sala"], "entrou", "u-maria", "Maria")

    assert depois["estado"] == at.EM_ATENDIMENTO
    assert depois["atendente_id"] == "u-maria"
    assert alertas.ativos_para("u-maria", {"entrevista"}) == []
    linhas = _linhas_de_alerta(banco_sqlite, registro["id"])
    assert [(l[0], l[2]) for l in linhas] == [(alertas.CLIENTE_AGUARDANDO, "responsavel_entrou")]
    assert "responsavel_entrou" in [e["tipo"] for e in at.eventos(registro["id"])]


def test_cenario_5_outro_funcionario_assume_e_so_um_vence(banco_sqlite):
    registro = _agendado()
    at.presenca_do_cliente(registro["sala"], "entrou")

    assumido = at.iniciar_atendimento(registro["id"], "u-joao", "João")

    assert assumido["atendente_id"] == "u-joao"
    assert assumido["responsavel_id"] == "u-maria"
    assert "assumiu" in [e["tipo"] for e in at.eventos(registro["id"])]
    linhas = _linhas_de_alerta(banco_sqlite, registro["id"])
    assert [l[2] for l in linhas] == ["assumido_por_outro"]
    with pytest.raises(at.TransicaoInvalida):
        at.iniciar_atendimento(registro["id"], "u-ana", "Ana")
    # O próprio atendente clicar de novo não é erro.
    assert at.iniciar_atendimento(registro["id"], "u-joao", "João")["atendente_id"] == "u-joao"


def test_escalonamento_aparece_para_a_equipe_uma_vez_so(banco_sqlite):
    registro = _agendado()
    # O cliente está na sala há 4 minutos, com batidas em dia.
    with banco_sqlite:
        banco_sqlite.execute(
            "UPDATE dbo.acervo_atendimentos SET estado = ?, cliente_entrou_em = ?, cliente_batida_em = ? WHERE id = ?",
            (at.CLIENTE_AGUARDANDO,
             (datetime.now(timezone.utc) - timedelta(minutes=4)).isoformat(timespec="seconds"),
             at.agora(), registro["id"]),
        )

    # Cada batida e cada passada do beat sincronizam de novo.
    for _ in range(6):
        at.presenca_do_cliente(registro["sala"], "batida")
        alertas.varrer(forcar=True)

    linhas = _linhas_de_alerta(banco_sqlite, registro["id"])
    assert sorted(l[0] for l in linhas) == [alertas.CLIENTE_AGUARDANDO, alertas.ESCALONAMENTO]
    assert all(l[1] is None for l in linhas)
    da_equipe = alertas.ativos_para("u-joao", {"entrevista"})
    assert [a["tipo"] for a in da_equipe] == [alertas.ESCALONAMENTO]
    assert da_equipe[0]["acao"] == "assumir"
    assert da_equipe[0]["titulo"] == "Cliente aguardando atendimento"
    assert "Responsável: Maria" in da_equipe[0]["texto"]
    # O responsável recebe o aviso direto, não o escalonamento duplicado.
    assert [a["tipo"] for a in alertas.ativos_para("u-maria", {"entrevista"})] == [alertas.CLIENTE_AGUARDANDO]

    at.iniciar_atendimento(registro["id"], "u-joao", "João")
    assert alertas.ativos_para("u-joao", {"entrevista"}) == []
    motivos = {l[2] for l in _linhas_de_alerta(banco_sqlite, registro["id"])}
    assert motivos == {"assumido_por_outro"}


def test_escalonamento_respeita_o_prazo_configurado(banco_sqlite):
    at.salvar_config({"escalonar_apos_min": 10}, "teste")
    registro = _agendado()
    at.presenca_do_cliente(registro["sala"], "entrou")
    entrou = at.ler_data(at.exigir(registro["id"])["cliente_entrou_em"])

    alertas.sincronizar(at.exigir(registro["id"]), entrou + timedelta(seconds=60))

    tipos = [l[0] for l in _linhas_de_alerta(banco_sqlite, registro["id"])]
    assert tipos == [alertas.CLIENTE_AGUARDANDO]


def test_cenario_20_cliente_sai_e_o_alerta_some(banco_sqlite):
    registro = _agendado()
    at.presenca_do_cliente(registro["sala"], "entrou")

    depois = at.presenca_do_cliente(registro["sala"], "saiu")

    assert depois["estado"] == at.AGENDADA
    assert alertas.ativos_para("u-maria", {"entrevista"}) == []
    assert [l[2] for l in _linhas_de_alerta(banco_sqlite, registro["id"])] == ["cliente_saiu"]


def test_aba_fechada_sem_saiu_expira_pela_varredura(banco_sqlite):
    registro = _agendado()
    at.presenca_do_cliente(registro["sala"], "entrou")
    depois_de_2min = datetime.now(timezone.utc) + timedelta(seconds=at.PRESENCA_VALIDA_S + 30)

    alertas.varrer(depois_de_2min, forcar=True)

    assert at.exigir(registro["id"])["estado"] == at.AGENDADA
    assert all(l[1] for l in _linhas_de_alerta(banco_sqlite, registro["id"]))


def test_cenario_19_episodio_resolvido_nao_volta_a_tocar(banco_sqlite):
    registro = _agendado()
    at.presenca_do_cliente(registro["sala"], "entrou")
    retrato_aguardando = at.exigir(registro["id"])
    at.presenca_do_escritorio(registro["sala"], "entrou", "u-maria", "Maria")

    # Uma requisição atrasada sincroniza com o retrato antigo (ainda "aguardando").
    alertas.sincronizar(retrato_aguardando)

    assert alertas.ativos_para("u-maria", {"entrevista"}) == []
    assert len(_linhas_de_alerta(banco_sqlite, registro["id"])) == 1


def test_cliente_volta_depois_de_sair_e_novo_episodio(banco_sqlite):
    registro = _agendado()
    at.presenca_do_cliente(registro["sala"], "entrou")
    at.presenca_do_cliente(registro["sala"], "saiu")
    with banco_sqlite:
        # O relógio andou: a nova chegada tem outro instante (e outra chave).
        banco_sqlite.execute(
            "UPDATE dbo.acervo_alertas SET chave = chave || ':antigo' WHERE atendimento_id = ?",
            (registro["id"],),
        )

    at.presenca_do_cliente(registro["sala"], "entrou")

    assert len(alertas.ativos_para("u-maria", set())) == 1


def test_atendimento_cancelado_nao_responde_presenca(banco_sqlite):
    registro = _agendado()
    at.transicionar(registro["id"], at.CANCELADA)

    assert at.presenca_do_cliente(registro["sala"], "entrou") is None
    assert alertas.ativos_para("u-maria", {"entrevista"}) == []
