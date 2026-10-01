"""Máquina de estados do atendimento (cenários 1, 6, 7, 8, 19 e 20)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import alertas, auth, documentacao
from app import atendimentos as at
from app.rotas import atendimentos as rotas

MARIA = auth.Usuario({"codigo": "u-maria", "nome": "Maria"})
JOAO = auth.Usuario({"codigo": "u-joao", "nome": "João"})


def _daqui(minutos: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutos)).isoformat(timespec="seconds")


def _agendar(**extra) -> dict:
    dados = {
        "cliente": "José da Silva", "telefone": "61999998888", "data_hora": _daqui(60),
        "responsavel_id": MARIA.id, "responsavel_nome": MARIA.nome, "usuario_nome": MARIA.nome,
    }
    dados.update(extra)
    return at.criar(**dados)


def _ate_em_atendimento(registro: dict) -> dict:
    return at.iniciar_atendimento(registro["id"], MARIA.id, MARIA.nome)


def test_cenario_1_agendamento_normal_salva_sala_link_e_evento(banco_sqlite):
    registro = _agendar(data_hora="2026-10-20T14:30:00-03:00")

    assert registro["estado"] == at.AGENDADA
    assert len(registro["sala"]) == 32
    assert registro["link_cliente"].endswith(f"/chamada/{registro['sala']}")
    assert registro["data_hora"] == "2026-10-20T17:30:00+00:00"
    assert at.por_sala(registro["sala"])["id"] == registro["id"]
    assert [e["tipo"] for e in at.eventos(registro["id"])] == ["criado"]
    assert at.listar(de="2026-10-20T00:00:00-03:00", ate="2026-10-21T00:00:00-03:00")[0]["id"] == registro["id"]


def test_agendamento_sem_data_ou_cliente_e_recusado(banco_sqlite):
    with pytest.raises(at.ErroAtendimento):
        at.criar(cliente="", data_hora=_daqui(30))
    with pytest.raises(at.ErroAtendimento):
        at.criar(cliente="Ana", data_hora="amanhã")


def test_edicao_da_agenda_com_versao_antiga_e_recusada(banco_sqlite):
    registro = _agendar()
    at.atualizar_agenda(registro["id"], {"telefone": "61911112222"}, versao=registro["versao"], usuario_nome="Maria")
    with pytest.raises(at.TransicaoInvalida):
        at.atualizar_agenda(registro["id"], {"telefone": "61933334444"}, versao=registro["versao"], usuario_nome="Maria")


def test_transicao_fora_da_tabela_e_recusada_e_nao_grava(banco_sqlite):
    registro = _agendar()
    with pytest.raises(at.TransicaoInvalida):
        at.transicionar(registro["id"], at.QUALIFICACAO)
    assert at.exigir(registro["id"])["estado"] == at.AGENDADA


def test_transicao_concorrente_so_uma_vence(banco_sqlite):
    registro = _ate_em_atendimento(_agendar())
    at.transicionar(registro["id"], at.ENTREVISTA_FINALIZADA)
    with pytest.raises(at.TransicaoInvalida):
        at.transicionar(registro["id"], at.ENTREVISTA_FINALIZADA, de={at.EM_ATENDIMENTO})


def test_cenario_6_entrevista_finalizada_encerra_a_fila_da_documentacao(banco_sqlite):
    registro = at.garantir_para_entrevista(
        entrevista_id="entrevista-001", cliente="Ana Souza", sala=None,
        usuario_id=MARIA.id, usuario_nome=MARIA.nome,
    )
    assert registro["estado"] == at.EM_ATENDIMENTO and registro["origem"] == "avulso"
    with banco_sqlite:
        banco_sqlite.execute(
            "INSERT INTO dbo.acervo_atendimentos_documentacao (entrevista_id, cliente, status, "
            "entrevistador_id, entrevistador_nome, iniciado_em, atualizado_em) "
            "VALUES ('entrevista-001', 'Ana', 'solicitado', 'u', 'Maria', ?, ?)",
            (at.agora(), at.agora()),
        )

    final = rotas.finalizar_entrevista(registro["id"], MARIA)

    assert final["estado"] == at.ENTREVISTA_FINALIZADA
    status = banco_sqlite.execute(
        "SELECT status FROM dbo.acervo_atendimentos_documentacao WHERE entrevista_id = 'entrevista-001'"
    ).fetchone()[0]
    assert status == "encerrado"
    # Repetir o clique não muda nada.
    assert rotas.finalizar_entrevista(registro["id"], MARIA)["estado"] == at.ENTREVISTA_FINALIZADA


def test_entrevista_agendada_liga_ao_atendimento_existente(banco_sqlite):
    agendado = _agendar()
    ligado = at.garantir_para_entrevista(
        entrevista_id="entrevista-xyz", cliente="", sala=agendado["sala"],
        usuario_id=MARIA.id, usuario_nome=MARIA.nome,
    )
    assert ligado["id"] == agendado["id"]
    assert ligado["entrevista_id"] == "entrevista-xyz"
    assert ligado["estado"] == at.EM_ATENDIMENTO


@pytest.mark.parametrize("revisada", [True, False], ids=["cenario_7_revisada", "cenario_8_sem_revisao"])
def test_revisar_ou_pular_levam_a_mesma_analise(banco_sqlite, revisada):
    registro = _ate_em_atendimento(_agendar())
    rotas.finalizar_entrevista(registro["id"], MARIA)

    seguido = rotas.seguir_para_analise(registro["id"], rotas.SeguirParaAnalise(revisada=revisada), MARIA)

    assert seguido["estado"] == at.ANALISE_JURIDICA
    assert seguido["revisada"] is revisada
    evento = next(e for e in at.eventos(registro["id"]) if e["para_estado"] == at.ANALISE_JURIDICA)
    assert evento["detalhes"] == ("revisada" if revisada else "sem revisão")


def test_cenario_19_atendimento_antigo_nao_gera_alerta(banco_sqlite, monkeypatch):
    ontem = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    antigo = _agendar(data_hora=ontem)
    # Batida velha de um cliente que fechou a aba ontem.
    with banco_sqlite:
        banco_sqlite.execute(
            "UPDATE dbo.acervo_atendimentos SET estado = ?, cliente_batida_em = ?, cliente_entrou_em = ? WHERE id = ?",
            (at.CLIENTE_AGUARDANDO, ontem, ontem, antigo["id"]),
        )
        banco_sqlite.execute(
            "INSERT INTO dbo.acervo_atendimentos_documentacao (entrevista_id, cliente, status, "
            "entrevistador_id, entrevistador_nome, iniciado_em, solicitado_em, atualizado_em) "
            "VALUES ('entrevista-antiga', 'Ana', 'solicitado', 'u', 'Maria', ?, ?, ?)",
            (ontem, ontem, ontem),
        )
    alertas.varrer(forcar=True)

    assert alertas.ativos_para(MARIA.id, {"entrevista", "documentacao"}) == []
    assert at.exigir(antigo["id"])["estado"] in (at.AGENDADA, at.CLIENTE_FALTOU)
    documentacao.expirar_antigos(forcar=True)
    monkeypatch.setattr(documentacao, "_detalhes_documentos", lambda caso_id: None)
    fila = documentacao.listar()
    assert fila["solicitacoes"] == 0
    assert fila["atendimentos"] == []


def test_cenario_20_cliente_ja_atendido_nao_aparece_aguardando(banco_sqlite):
    registro = _agendar()
    at.presenca_do_cliente(registro["sala"], "entrou")
    assert len(alertas.ativos_para(MARIA.id, set())) == 1

    at.presenca_do_escritorio(registro["sala"], "entrou", MARIA.id, MARIA.nome)
    for _ in range(3):
        at.presenca_do_cliente(registro["sala"], "batida")

    atual = at.exigir(registro["id"])
    assert atual["estado"] == at.EM_ATENDIMENTO
    assert alertas.ativos_para(MARIA.id, {"entrevista"}) == []
    assert alertas.ativos_para(JOAO.id, {"entrevista"}) == []

    rotas.finalizar_entrevista(registro["id"], MARIA)
    at.presenca_do_cliente(registro["sala"], "entrou")
    assert at.exigir(registro["id"])["estado"] == at.ENTREVISTA_FINALIZADA
    assert alertas.ativos_para(MARIA.id, {"entrevista"}) == []
