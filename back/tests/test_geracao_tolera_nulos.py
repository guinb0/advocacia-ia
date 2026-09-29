"""Lista explícita `null` no JSON não pode abortar a geração da petição.

`.get("chave", [])` devolve None quando a chave existe e o valor é null. O
efeito na tela era: ``'NoneType' object is not iterable``.
"""
from app import auditor_final, auditoria_estrutural, case_facts, documento_final, petition_linter, plano_da_peticao


def test_case_facts_aceita_dados_nulos():
    cf = case_facts.montar(
        fontes=[{"tipo": "documento", "nome": "rg.pdf", "texto": "Paulo", "dados": None}],
        proposta_partes={"autor": None, "reu": {"nome": None}},
        eventos=None,
    )
    assert cf["UNCERTAINTIES"] == []
    assert case_facts.partes_resolvidas(cf)["autor"] == {}


def test_plano_e_auditor_aceitam_listas_nulas():
    plano = {
        "partes": {"autor": {"nome": "Paulo"}, "reu": {}},
        "fatos": [{"id": "F01", "data": "", "fato": "assalto", "documentos": None, "fonte": "bo"}],
        "teses": [{"id": "T01", "titulo": "responsabilidade", "fatos_ids": None, "pedidos_ids": None}],
        "pedidos": [],
        "ausencias": None,
        "case_facts": {"PARTIES": None, "UNCERTAINTIES": None},
    }
    assert plano_da_peticao.fatos_comuns(plano) == set()
    assert "assalto" in plano_da_peticao.para_prompt(plano)
    achados = auditor_final.auditar_com_modelo(
        lambda _i, _e: {"itens": None},
        plano["case_facts"],
        {"teses": None, "fatos": None, "pedidos": None},
        [{"code": "FACTS", "label": "Fatos", "content": "texto"}],
    )
    assert achados == []


def test_linter_e_metadata_aceitam_parametros_nulos():
    secoes = [{"code": "HEADING", "label": "Abertura", "content": "Juízo do Trabalho\nPaulo"}]
    plano = {
        "partes": {"autor": {"nome": "Paulo"}, "reu": {}},
        "teses": [{"id": "T01", "titulo": "tese", "fatos_ids": None}],
        "fatos": [],
        "pedidos": [],
    }
    params = {
        "qualificacao": {"exigida": True, "campos": {"autor": None, "reu": None}},
        "estrutura": {"blocos_unicos": None, "enderecamento_regex": "ju[íi]zo"},
        "metadata_interna": {"titulos": None, "rotulos": None},
    }
    petition_linter.lintar(secoes, plano, texto_do_caso="Paulo", textos_do_acervo=[], params=params)
    auditoria_estrutural.abertura_unica(secoes, plano["partes"], params)
    limpas, _removidos = documento_final._cortar_metadata(secoes, params)  # noqa: SLF001
    assert limpas[0]["content"].startswith("Juízo")
