from datetime import datetime, timezone

from app.pesquisa_jurisprudencial import (
    PrecedenteEstruturado, StatusVerificacao, planejar, pontuar, providers_padrao,
)


def test_registro_tem_provider_para_todos_os_trts_sem_fingir_automacao():
    registros = providers_padrao()
    assert all(f"TRT{i}" in registros for i in range(1, 25))
    assert registros["TRT8"].capacidade().disponibilidade == "MANUAL_ONLY"


def test_planejador_usa_uf_e_fatos_do_plano():
    plano = {"cronologia": [{"fato": "assalto durante atendimento em agência"}],
             "teses": [{"tese": "responsabilidade por atividade de risco",
                         "fatos_que_sustentam": ["empregada rendida"]}]}
    resultado = planejar(plano, "", uf="PA")
    assert resultado.tribunal_principal == "TRT8"
    assert "assalto" in resultado.consultas[0].texto


def test_score_barra_nao_verificado_e_expoe_componentes():
    p = PrecedenteEstruturado(tribunal="TRT8", numero_processo="0001", ementa="texto", fonte_url="https://oficial")
    assert pontuar(p, tribunal_preferido="TRT8", similaridade_juridica=1, similaridade_fatica=1)["verificacao"] == 0
    p.status_verificacao = StatusVerificacao.VERIFIED
    score = pontuar(p, tribunal_preferido="TRT8", similaridade_juridica=.8, similaridade_fatica=.9)
    assert score["total"] > .8 and score["tribunal_competente"] > 0
