"""Confirmação das ações pelo advogado e criação dos casos (cenários 11, 12, 14 e 16)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import armazenamento, auth, criterios_caso, pos_entrevista
from app import atendimentos as at
from app.rotas import atendimentos as rotas
from app.rotas import comum

MARIA = auth.Usuario({"codigo": "u-maria", "nome": "Maria"})


class Escritorio:
    """`armazenamento.criar_caso` e o portal, sem o banco dos casos."""

    def __init__(self) -> None:
        self.casos: list[dict] = []
        self.falhar_na: str | None = None

    def criar_caso(self, nome, categoria, descricao, telefone, nome_acao):
        if categoria == self.falhar_na:
            raise RuntimeError("banco dos casos caiu")
        caso = {"id": f"caso-{len(self.casos) + 1}", "nome": nome, "categoria": categoria,
                "descricao": descricao, "telefone": telefone, "acao": nome_acao}
        self.casos.append(caso)
        return caso

    def portal(self, caso_id):
        return {"url": f"https://portal/acesso/{caso_id}", "senha": "123456", "aviso": None}


@pytest.fixture
def escritorio(banco_sqlite, catalogo_falso, monkeypatch) -> Escritorio:
    falso = Escritorio()
    monkeypatch.setattr(armazenamento, "criar_caso", falso.criar_caso)
    monkeypatch.setattr(comum, "_criar_portal", falso.portal)
    monkeypatch.setattr(pos_entrevista, "_itens_do_caso", lambda caso_id: ([], None))
    monkeypatch.setattr(pos_entrevista, "_cpf_dos_casos", lambda ids: "")
    return falso


def _aguardando_confirmacao() -> dict:
    registro = at.criar(
        cliente="José da Silva", telefone="61999998888",
        data_hora=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
        responsavel_id=MARIA.id, responsavel_nome=MARIA.nome,
    )
    at.iniciar_atendimento(registro["id"], MARIA.id, MARIA.nome)
    rotas.finalizar_entrevista(registro["id"], MARIA)
    at.transicionar(registro["id"], at.ANALISE_JURIDICA, de={at.ENTREVISTA_FINALIZADA})
    return at.transicionar(registro["id"], at.AGUARDANDO_CONFIRMACAO_ACOES, de={at.ANALISE_JURIDICA})


def _confirmar(registro: dict, acoes: list[dict], **extra) -> dict:
    return pos_entrevista.confirmar_acoes(
        registro["id"], acoes=acoes, usuario_id=MARIA.id, usuario_nome=MARIA.nome, **extra
    )


def test_cenario_16_caso_criado_leva_a_qualificacao(escritorio):
    registro = _aguardando_confirmacao()

    resposta = _confirmar(registro, [{"codigo": "doenca_ocupacional", "origem": "ia"}],
                          documentos_declarados=["RG", "CAT"])

    assert resposta["repetido"] is False
    atendimento = resposta["atendimento"]
    assert atendimento["estado"] == at.QUALIFICACAO
    assert [c["categoria"] for c in atendimento["casos"]] == ["doenca_ocupacional"]
    assert resposta["casos"][0]["portal"]["senha"] == "123456"
    assert escritorio.casos[0]["nome"] == "José da Silva" and escritorio.casos[0]["telefone"] == "61999998888"
    assert atendimento["acoes"] == [{"codigo": "doenca_ocupacional", "nome": "Doença Ocupacional",
                                     "origem": "ia", "nova": False, "caso_id": "caso-1"}]
    assert {d["nome"] for d in atendimento["documentos"]["disponiveis"]} == {"RG", "CAT"}
    assert any(e["tipo"] == "caso_criado" for e in at.eventos(registro["id"]))


def test_cenario_11_sugestao_rejeitada_nao_vira_caso(escritorio):
    registro = _aguardando_confirmacao()
    # A análise sugeriu doença ocupacional e acidente; o advogado ficou só com a primeira.
    resposta = _confirmar(registro, [{"codigo": "doenca_ocupacional", "origem": "ia"}])

    assert [c["categoria"] for c in escritorio.casos] == ["doenca_ocupacional"]
    assert len(resposta["atendimento"]["casos"]) == 1


def test_cenario_12_advogado_adiciona_acao_manualmente(escritorio):
    registro = _aguardando_confirmacao()

    resposta = _confirmar(registro, [
        {"codigo": "doenca_ocupacional", "origem": "ia"},
        {"codigo": "auxilio_acidente", "origem": "manual"},
        {"codigo": "auxilio_acidente", "origem": "manual"},
    ])

    assert [c["categoria"] for c in escritorio.casos] == ["doenca_ocupacional", "auxilio_acidente"]
    assert [a["origem"] for a in resposta["atendimento"]["acoes"]] == ["ia", "manual"]


def test_cenario_14_acao_nova_vira_tipo_de_caso_rascunho(escritorio, catalogo_falso):
    registro = _aguardando_confirmacao()
    nova = {
        "descricao": "Cobranças vexatórias do gerente.",
        "criterios": ["Conduta abusiva reiterada", "Dano à saúde mental"],
        "documentos": [{"nome": "Atestado psiquiátrico", "minimo": True}, {"nome": "Prints", "minimo": False}],
        "informacoes_necessarias": ["Nome do superior"],
        "fundamentos": [{"authority_id": "clt-art-483", "titulo": "CLT, art. 483"}],
    }

    resposta = _confirmar(registro, [{"nome": "Indenização por assédio moral", "origem": "ia", "nova": nova}])

    caso = resposta["atendimento"]["casos"][0]
    assert caso["rascunho_ia"] is True
    tipo = catalogo_falso.criados[caso["categoria"]]
    assert tipo["nome"] == "Indenização por assédio moral"
    assert [(i["nome"], i["obrigatorio"]) for i in tipo["itens"]] == [("Atestado psiquiátrico", True), ("Prints", False)]
    meta = criterios_caso.metadados_ia()[caso["categoria"]]
    assert meta["requer_revisao"] is True and meta["origem"] == "ia"
    assert meta["informacoes_necessarias"] == ["Nome do superior"]
    assert meta["atendimento_id"] == registro["id"]
    assert [c["texto"] for c in criterios_caso.listar(caso["categoria"])] == nova["criterios"]

    # Aprovar tira o selo "requer revisão".
    assert criterios_caso.aprovar(caso["categoria"], "Dra. Ana")["requer_revisao"] is False


def test_mesma_acao_nova_aceita_duas_vezes_nao_duplica_o_tipo(escritorio, catalogo_falso):
    for _ in range(2):
        registro = _aguardando_confirmacao()
        _confirmar(registro, [{"nome": "Indenização por assédio moral", "nova": {"criterios": ["x" * 5]}}])
    assert len(catalogo_falso.criados) == 1


def test_confirmar_de_novo_nao_cria_casos_em_dobro(escritorio):
    registro = _aguardando_confirmacao()
    acoes = [{"codigo": "doenca_ocupacional"}, {"codigo": "acidente_trabalho_geral"}]

    primeira = _confirmar(registro, acoes)
    segunda = _confirmar(registro, acoes)

    assert len(escritorio.casos) == 2
    assert segunda["repetido"] is True
    assert [c["id"] for c in segunda["casos"]] == [c["id"] for c in primeira["casos"]]


def test_confirmacao_simultanea_e_barrada_pela_trava(escritorio, banco_sqlite):
    registro = _aguardando_confirmacao()
    with banco_sqlite:
        banco_sqlite.execute(
            f"INSERT INTO {at.TABELA_EVENTOS} (id, atendimento_id, tipo, criado_em) VALUES (?, ?, 'confirmando_acoes', ?)",
            (pos_entrevista._id_trava(registro["id"]), registro["id"], at.agora()),
        )
    with pytest.raises(pos_entrevista.ConfirmacaoEmAndamento):
        _confirmar(registro, [{"codigo": "doenca_ocupacional"}])
    assert escritorio.casos == []


def test_queda_no_meio_retoma_so_o_que_faltou(escritorio):
    registro = _aguardando_confirmacao()
    acoes = [{"codigo": "doenca_ocupacional"}, {"codigo": "acidente_trabalho_geral"}]
    escritorio.falhar_na = "acidente_trabalho_geral"
    with pytest.raises(RuntimeError):
        _confirmar(registro, acoes)
    assert at.exigir(registro["id"])["estado"] == at.AGUARDANDO_CONFIRMACAO_ACOES
    assert [c["categoria"] for c in at.exigir(registro["id"])["casos"]] == ["doenca_ocupacional"]

    escritorio.falhar_na = None
    resposta = _confirmar(registro, acoes)

    assert [c["categoria"] for c in escritorio.casos] == ["doenca_ocupacional", "acidente_trabalho_geral"]
    assert resposta["atendimento"]["estado"] == at.QUALIFICACAO


def test_acoes_invalidas_sao_recusadas(escritorio):
    registro = _aguardando_confirmacao()
    with pytest.raises(pos_entrevista.ErroPosEntrevista):
        _confirmar(registro, [])
    with pytest.raises(pos_entrevista.ErroPosEntrevista):
        _confirmar(registro, [{"codigo": "nao_existe"}])
    with pytest.raises(pos_entrevista.ErroPosEntrevista):
        _confirmar(registro, [{"codigo": f"c{i}"} for i in range(pos_entrevista.MAXIMO_ACOES + 1)])
    assert escritorio.casos == []
    assert at.exigir(registro["id"])["estado"] == at.AGUARDANDO_CONFIRMACAO_ACOES


def test_confirmar_antes_da_analise_e_recusado(escritorio):
    registro = at.criar(cliente="Ana", data_hora=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    with pytest.raises(at.TransicaoInvalida):
        _confirmar(registro, [{"codigo": "doenca_ocupacional"}])
