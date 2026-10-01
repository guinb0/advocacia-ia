"""Análise jurídica automática e sugestões de ação (cenários 9, 10 e 13)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import analise_acoes, auth, triagem
from app import atendimentos as at
from app.juridico import autoridades
from app.rotas import atendimentos as rotas

MARIA = auth.Usuario({"codigo": "u-maria", "nome": "Maria"})

CATALOGO = [
    {"codigo": "doenca_ocupacional", "nome": "Doença Ocupacional", "descricao": "", "quando_usar": "",
     "criterios": ["Doença ligada ao trabalho", "Afastamento ou sequela"], "documentos_minimos": ["CAT"]},
    {"codigo": "acidente_trabalho_geral", "nome": "Ações de Acidente de Trabalho Geral", "descricao": "",
     "quando_usar": "", "criterios": ["Acidente no trabalho ou trajeto"], "documentos_minimos": []},
    {"codigo": "auxilio_acidente", "nome": "Auxílio-Acidente", "descricao": "", "quando_usar": "",
     "criterios": ["Sequela que reduz a capacidade"], "documentos_minimos": []},
]

LEI = SimpleNamespace(id="lei-8213-art-20", titulo="Lei 8.213/91, art. 20", tipo="lei",
                      url="https://www.planalto.gov.br/ccivil_03/leis/l8213cons.htm", verificada=True)
SUMULA = SimpleNamespace(id="tst-sumula-378", titulo="Súmula 378 do TST", tipo="sumula", url="", verificada=True)

ENTRADA = {
    "transcricao": "Trabalhei 12 anos digitando, tenho tendinite e fiquei afastado pelo INSS. "
                   "Depois caí da escada no depósito e quebrei o punho.",
    "respostas": {"funcao": "Digitador", "afastamento": ["B91", "6 meses"]},
    "perguntas": {"funcao": "Qual a função?"},
    "documentos": ["CAT", "Laudo médico"],
}


def _triagem(*codigos: str) -> dict:
    return {"sugestoes": [{"codigo": c, "nome": c, "confianca": 0.6, "evidencias": ["termo"]} for c in codigos]}


@pytest.fixture
def ambiente(banco_sqlite, catalogo_falso, monkeypatch):
    monkeypatch.setattr(analise_acoes, "_enfileirar", lambda analise_id: None)
    monkeypatch.setattr(analise_acoes, "catalogo_para_analise", lambda: CATALOGO)
    monkeypatch.setattr(autoridades, "bloco_para_prompt", lambda lista: "=== BASE JURÍDICA VERIFICADA ===")
    monkeypatch.setattr(triagem, "classificar_entrevista", lambda texto: _triagem("doenca_ocupacional"))
    return monkeypatch


def _em_analise() -> dict:
    registro = at.criar(
        cliente="José da Silva", telefone="61999998888",
        data_hora=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
        responsavel_id=MARIA.id, responsavel_nome=MARIA.nome,
    )
    at.iniciar_atendimento(registro["id"], MARIA.id, MARIA.nome)
    rotas.finalizar_entrevista(registro["id"], MARIA)
    rotas.seguir_para_analise(registro["id"], rotas.SeguirParaAnalise(revisada=False), MARIA)
    assert at.exigir(registro["id"])["estado"] == at.ANALISE_JURIDICA
    return at.exigir(registro["id"])


def _rodar(registro: dict, resposta: dict, autoridades_lista=(LEI, SUMULA)) -> dict:
    analise = analise_acoes.iniciar(registro["id"], ENTRADA, usuario="Maria")
    return analise_acoes.executar(
        analise["id"],
        chamar_llm=lambda instrucao, conteudo: resposta,
        recuperar=lambda texto, sugestoes: (list(autoridades_lista), []),
    )


# --------------------------------------------------------- validação pura


def test_cenario_9_uma_acao_sugerida_com_criterios_e_fundamento():
    bruto = {"sugestoes": [{
        "tipo_codigo": "doenca_ocupacional", "confianca": 0.82, "justificativa": "Tendinite por digitação.",
        "criterios_atendidos": ["Doença ligada ao trabalho"], "criterios_pendentes": ["Afastamento ou sequela"],
        "fundamentos": [{"authority_id": "[lei-8213-art-20]", "motivo": "Equipara doença ocupacional a acidente."}],
    }]}

    resultado = analise_acoes.validar_resultado(bruto, CATALOGO, [LEI], _triagem("doenca_ocupacional"))

    assert len(resultado["sugestoes"]) == 1
    sugestao = resultado["sugestoes"][0]
    assert sugestao["nome"] == "Doença Ocupacional" and sugestao["origem"] == "ia"
    assert sugestao["criterios_pendentes"] == ["Afastamento ou sequela"]
    assert sugestao["fundamentos"][0]["authority_id"] == "lei-8213-art-20"
    assert sugestao["fundamentos"][0]["verificada"] is True
    assert sugestao["triagem_concorda"] is True
    assert resultado["fundamentos_descartados"] == 0


def test_cenario_10_multiplas_acoes_ordenadas_e_sem_repeticao():
    bruto = {"sugestoes": [
        {"tipo_codigo": "acidente_trabalho_geral", "confianca": 0.55},
        {"tipo_codigo": "doenca_ocupacional", "confianca": 0.9},
        {"tipo_codigo": "doenca_ocupacional", "confianca": 0.1},
        {"tipo_codigo": "codigo_inventado", "confianca": 1.0},
        {"tipo_codigo": "auxilio_acidente", "confianca": "7"},
    ]}

    resultado = analise_acoes.validar_resultado(bruto, CATALOGO, [], None)

    assert [s["tipo_codigo"] for s in resultado["sugestoes"]] == [
        "auxilio_acidente", "doenca_ocupacional", "acidente_trabalho_geral",
    ]
    assert resultado["sugestoes"][0]["confianca"] == 1.0


def test_fundamento_fora_do_acervo_recuperado_e_descartado():
    bruto = {
        "sugestoes": [{"tipo_codigo": "doenca_ocupacional", "confianca": 0.7, "fundamentos": [
            {"authority_id": "lei-8213-art-20", "motivo": "ok"},
            {"authority_id": "stj-resp-inventado", "motivo": "alucinado"},
            "texto solto",
        ]}],
        "novas_acoes": [{"nome": "Revisão da vida toda", "fundamentos": [{"authority_id": "tema-999"}]}],
    }

    resultado = analise_acoes.validar_resultado(bruto, CATALOGO, [LEI], None)

    assert [f["authority_id"] for f in resultado["sugestoes"][0]["fundamentos"]] == ["lei-8213-art-20"]
    assert resultado["novas_acoes"][0]["fundamentos"] == []
    assert resultado["fundamentos_descartados"] == 3


def test_cenario_13_ia_identifica_acao_que_o_catalogo_nao_tem():
    bruto = {"sugestoes": [], "novas_acoes": [
        {"nome": "Indenização por assédio moral", "descricao": "Cobranças vexatórias.",
         "criterios": ["Conduta abusiva reiterada", "Dano à saúde mental"],
         "documentos": [{"nome": "Atestado psiquiátrico", "minimo": True}, {"nome": "Prints", "minimo": False}, {"nome": ""}],
         "informacoes_necessarias": ["Nome do superior"]},
        {"nome": "doença ocupacional"},
        {"nome": "ab"},
    ]}

    resultado = analise_acoes.validar_resultado(bruto, CATALOGO, [], None)

    assert len(resultado["novas_acoes"]) == 1
    nova = resultado["novas_acoes"][0]
    assert nova["nome"] == "Indenização por assédio moral"
    assert nova["criterios"] == ["Conduta abusiva reiterada", "Dano à saúde mental"]
    assert nova["documentos"] == [{"nome": "Atestado psiquiátrico", "minimo": True}, {"nome": "Prints", "minimo": False}]
    assert len(nova["id"]) == 12


def test_triagem_divergente_entra_como_sugestao_para_conferir():
    bruto = {"sugestoes": [{"tipo_codigo": "acidente_trabalho_geral", "confianca": 0.8}]}

    resultado = analise_acoes.validar_resultado(bruto, CATALOGO, [], _triagem("doenca_ocupacional"))

    assert resultado["triagem"] == {"principal": "doenca_ocupacional", "divergiu": True}
    reserva = resultado["sugestoes"][-1]
    assert reserva["tipo_codigo"] == "doenca_ocupacional" and reserva["origem"] == "triagem"


# ------------------------------------------------------ fluxo com o banco


def test_analise_concluida_libera_a_confirmacao_das_acoes(ambiente):
    registro = _em_analise()

    analise = _rodar(registro, {"sugestoes": [
        {"tipo_codigo": "doenca_ocupacional", "confianca": 0.9,
         "fundamentos": [{"authority_id": "tst-sumula-378", "motivo": "estabilidade"}]},
        {"tipo_codigo": "acidente_trabalho_geral", "confianca": 0.7},
    ]})

    assert analise["status"] == analise_acoes.CONCLUIDA
    assert [s["tipo_codigo"] for s in analise["resultado"]["sugestoes"]] == ["doenca_ocupacional", "acidente_trabalho_geral"]
    assert analise["resultado"]["autoridades_consultadas"] == 2
    assert at.exigir(registro["id"])["estado"] == at.AGUARDANDO_CONFIRMACAO_ACOES
    # Executar de novo (fila + API) não roda duas vezes.
    assert analise_acoes.executar(analise["id"], chamar_llm=lambda *a: pytest.fail("rodou duas vezes"))["status"] == analise_acoes.CONCLUIDA


def test_falha_da_ia_vira_sugestao_da_triagem_e_nao_trava_o_fluxo(ambiente):
    registro = _em_analise()
    analise = analise_acoes.iniciar(registro["id"], ENTRADA, usuario="Maria")

    def fora_do_ar(instrucao, conteudo):
        raise TimeoutError("modelo não respondeu")

    final = analise_acoes.executar(analise["id"], chamar_llm=fora_do_ar, recuperar=lambda t, s: ([], ["sem acervo"]))

    assert final["status"] == analise_acoes.FALHOU
    assert "TimeoutError" in final["erro"]
    assert final["resultado"]["reserva"] is True
    assert final["resultado"]["sugestoes"][0]["tipo_codigo"] == "doenca_ocupacional"
    assert at.exigir(registro["id"])["estado"] == at.AGUARDANDO_CONFIRMACAO_ACOES


def test_analise_travada_expira_com_reserva(ambiente, banco_sqlite):
    registro = _em_analise()
    analise = analise_acoes.iniciar(registro["id"], ENTRADA)
    velho = (datetime.now(timezone.utc) - timedelta(minutes=analise_acoes.MINUTOS_TRAVADA + 1)).isoformat()
    with banco_sqlite:
        banco_sqlite.execute(
            f"UPDATE {analise_acoes.TABELA} SET status = ?, atualizado_em = ? WHERE id = ?",
            (analise_acoes.PROCESSANDO, velho, analise["id"]),
        )

    atual = analise_acoes.ultima(registro["id"])

    assert atual["status"] == analise_acoes.FALHOU
    assert at.exigir(registro["id"])["estado"] == at.AGUARDANDO_CONFIRMACAO_ACOES


def test_iniciar_e_idempotente_e_refazer_volta_para_a_analise(ambiente):
    registro = _em_analise()
    primeira = analise_acoes.iniciar(registro["id"], ENTRADA)
    assert analise_acoes.iniciar(registro["id"], dict(ENTRADA))["id"] == primeira["id"]

    analise_acoes.executar(primeira["id"], chamar_llm=lambda *a: {"sugestoes": []}, recuperar=lambda t, s: ([], []))
    assert at.exigir(registro["id"])["estado"] == at.AGUARDANDO_CONFIRMACAO_ACOES
    # Sem refazer, devolve a concluída; com refazer, nova análise e volta o estado.
    assert analise_acoes.iniciar(registro["id"], ENTRADA)["id"] == primeira["id"]
    refeita = analise_acoes.iniciar(registro["id"], ENTRADA, refazer=True)

    assert refeita["id"] != primeira["id"] and refeita["status"] == analise_acoes.PENDENTE
    assert at.exigir(registro["id"])["estado"] == at.ANALISE_JURIDICA


def test_analise_antes_da_entrevista_acabar_e_recusada(ambiente):
    registro = at.criar(cliente="Ana", data_hora=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    with pytest.raises(at.TransicaoInvalida):
        analise_acoes.iniciar(registro["id"], ENTRADA)
