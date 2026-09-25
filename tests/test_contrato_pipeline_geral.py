from app import contrato_secoes, peticao_skill_arquivos, petition_linter


def _sec(code, text="texto", label=""):
    return {"code": code, "label": label, "content": text}


def test_estrutura_da_skill_vira_contrato_ordenado():
    contrato = contrato_secoes.montar(peticao_skill_arquivos.estrutura_da_skill())
    assert contrato["fonte"] == "references/estrutura_peca.md"
    assert contrato["permitidos"] == [
        "HEADING", "PRELIMINARY", "FACTS", "LEGAL_GROUNDS", "CLAIMS", "VALUE", "CLOSING"
    ]


def test_capitulo_inventado_e_ordem_errada_retidos():
    contrato = contrato_secoes.montar(peticao_skill_arquivos.estrutura_da_skill())
    _, achados = contrato_secoes.canonicalizar([
        _sec("FACTS"), _sec("JULGAMENTO_ANTECIPADO"), _sec("HEADING")
    ], contrato)
    assert {a.codigo for a in achados} >= {
        "SECAO_NAO_AUTORIZADA_PELA_SKILL", "ORDEM_DE_SECOES_DIVERGENTE_DA_SKILL"
    }


def test_cnpj_canonico_ausente_na_abertura_bloqueia():
    params = {"qualificacao": {"exigida": True, "campos": {
        "autor": ["nome"], "reu": ["nome", "cnpj"]
    }}}
    plano = {"partes": {"autor": {"nome": "Maria Silva"}, "reu": {
        "nome": "Empresa Exemplo Ltda", "cnpj": "12.345.678/0001-90"
    }}}
    achados = petition_linter._estrutura_e_qualificacao(  # noqa: SLF001
        [_sec("HEADING", "AO JUÍZO ... Maria Silva, em face de Empresa Exemplo Ltda")], plano, params
    )
    assert any(a.codigo == "QUALIFICACAO_AUSENTE" and "reu.cnpj" in a.motivo for a in achados)
