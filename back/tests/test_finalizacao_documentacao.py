"""Finalizar o atendimento e chamar a equipe de documentação (cenários 17 e 18)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import alertas, armazenamento, auth, documentacao, pos_entrevista
from app import atendimentos as at
from app.casos import PENDENTE
from app.rotas import atendimentos as rotas
from app.rotas import comum

MARIA = auth.Usuario({"codigo": "u-maria", "nome": "Maria"})
CARLA = auth.Usuario({"codigo": "u-carla", "nome": "Carla"})


@pytest.fixture
def ambiente(banco_sqlite, catalogo_falso, whatsapp_falso, monkeypatch):
    contador = iter(range(1, 100))
    monkeypatch.setattr(armazenamento, "criar_caso",
                        lambda nome, categoria, descricao, telefone, acao: {"id": f"caso-{next(contador)}"})
    monkeypatch.setattr(comum, "_criar_portal", lambda caso_id: {"url": f"https://portal/{caso_id}", "senha": "1", "aviso": None})
    itens = [
        {"codigo": "rg", "nome": "RG", "obrigatorio": True, "tipo": "rg", "status": PENDENTE},
        {"codigo": "cat", "nome": "CAT", "obrigatorio": True, "tipo": "cat", "status": PENDENTE},
    ]
    monkeypatch.setattr(pos_entrevista, "_itens_do_caso", lambda caso_id: (itens, None))
    monkeypatch.setattr(pos_entrevista, "_cpf_dos_casos", lambda ids: "")
    monkeypatch.setattr(documentacao, "_detalhes_documentos", lambda caso_id: None)
    return whatsapp_falso


def _na_avaliacao() -> dict:
    registro = at.garantir_para_entrevista(
        entrevista_id="entrevista-77", cliente="José da Silva", sala=None,
        usuario_id=MARIA.id, usuario_nome=MARIA.nome,
    )
    at.gravar(registro["id"], {"telefone": "61999998888"})
    rotas.finalizar_entrevista(registro["id"], MARIA)
    at.transicionar(registro["id"], at.ANALISE_JURIDICA, de={at.ENTREVISTA_FINALIZADA})
    at.transicionar(registro["id"], at.AGUARDANDO_CONFIRMACAO_ACOES, de={at.ANALISE_JURIDICA})
    pos_entrevista.confirmar_acoes(
        registro["id"], acoes=[{"codigo": "doenca_ocupacional"}, {"codigo": "auxilio_acidente"}],
        documentos_declarados=["CAT"], usuario_id=MARIA.id, usuario_nome=MARIA.nome,
    )
    return pos_entrevista.concluir_qualificacao(registro["id"], usuario_id=MARIA.id, usuario_nome=MARIA.nome)


def _finalizar(registro: dict, **extra) -> dict:
    return pos_entrevista.finalizar(registro["id"], usuario_id=MARIA.id, usuario_nome=MARIA.nome, **extra)


def _fila(entrevista_id: str, banco_sqlite) -> str | None:
    linha = banco_sqlite.execute(
        "SELECT status FROM dbo.acervo_atendimentos_documentacao WHERE entrevista_id = ?", (entrevista_id,)
    ).fetchone()
    return linha[0] if linha else None


def test_finalizar_exige_avaliacao_enviada_ou_pulada(ambiente):
    registro = _na_avaliacao()
    assert registro["estado"] == at.AVALIACAO_ESCRITORIO

    with pytest.raises(pos_entrevista.ErroPosEntrevista):
        _finalizar(registro)

    envio = pos_entrevista.enviar_avaliacao(registro["id"], usuario_nome=MARIA.nome)
    assert envio["status"] == "enviado"
    assert pos_entrevista.estado_avaliacao(registro["id"])["status"] == "enviado"
    assert len(ambiente.enviadas) == 1
    assert _finalizar(registro)["estado"] == at.DOCUMENTACAO_PENDENTE


def test_cenario_17_documentacao_pendente_com_resumo_e_fila(ambiente, banco_sqlite):
    registro = _na_avaliacao()

    final = _finalizar(registro, pular_avaliacao=True)

    assert final["estado"] == at.DOCUMENTACAO_PENDENTE
    assert _nomes(final["documentos"]["faltantes"]) == ["RG"]
    assert _nomes(final["documentos"]["disponiveis"]) == ["CAT"]
    assert _fila("entrevista-77", banco_sqlite) == "aguardando_documentacao"
    fila = documentacao.listar()
    assert fila["aguardando_documentacao"] == 1
    assert fila["atendimentos"][0]["caso_id"] == final["casos"][0]["id"]
    evento = next(e for e in at.eventos(registro["id"]) if e["para_estado"] == at.DOCUMENTACAO_PENDENTE)
    assert evento["detalhes"] == "avaliação pulada"
    # Clicar de novo não duplica nada.
    assert _finalizar(registro, pular_avaliacao=True)["estado"] == at.DOCUMENTACAO_PENDENTE


def test_cenario_18_alerta_para_a_equipe_de_documentacao(ambiente):
    registro = _na_avaliacao()
    _finalizar(registro, pular_avaliacao=True)

    vistos = alertas.ativos_para(CARLA.id, {"documentacao"})
    assert len(vistos) == 1
    alerta = vistos[0]
    assert alerta["titulo"] == "Novo caso aguardando documentação"
    assert alerta["acao"] == "abrir_caso"
    assert alerta["dados"]["cliente"] == "José da Silva"
    assert alerta["dados"]["acoes"] == ["Doença Ocupacional", "Auxílio-Acidente"]
    assert len(alerta["dados"]["casos"]) == 2
    assert alerta["dados"]["pendentes"] == ["RG"] and alerta["dados"]["disponiveis"] == ["CAT"]
    assert alerta["dados"]["responsavel"]
    # Quem não é da documentação não recebe.
    assert alertas.ativos_para("u-outro", {"entrevista"}) == []

    documentacao.assumir("entrevista-77", CARLA)

    assert at.exigir(registro["id"])["estado"] == at.CONCLUIDA
    assert alertas.ativos_para(CARLA.id, {"documentacao"}) == []
    resolvido = next(a for a in alertas.historico(registro["id"]) if a["tipo"] == alertas.DOCUMENTACAO_PENDENTE)
    assert resolvido["motivo_resolucao"] == "documentacao_assumida"
    # Uma segunda pessoa não assume o mesmo caso.
    with pytest.raises(Exception):
        documentacao.assumir("entrevista-77", MARIA)


def test_finalizar_fora_de_ordem_e_recusado(ambiente):
    registro = at.criar(cliente="Ana", data_hora=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    with pytest.raises(at.TransicaoInvalida):
        _finalizar(registro, pular_avaliacao=True)


def _nomes(lista: list[dict]) -> list[str]:
    return sorted(d["nome"] for d in lista)
