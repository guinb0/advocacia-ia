from app import contrato_secoes, document_ledger, peticao_skill_arquivos, petition_linter


def _sec(code, text="texto", label=""):
    return {"code": code, "label": label, "content": text}


def test_estrutura_da_skill_vira_contrato_ordenado():
    contrato = contrato_secoes.montar(peticao_skill_arquivos.estrutura_da_skill())
    assert contrato["fonte"] == "references/estrutura_peca.md"
    assert contrato["permitidos"] == [
        "HEADING", "PRELIMINARY", "FACTS", "LEGAL_GROUNDS", "CLAIMS", "VALUE", "CLOSING"
    ]


def test_skill_exige_relatorio_interno_separado_da_peca():
    regras = peticao_skill_arquivos._ler("regras_de_geracao.md")  # noqa: SLF001
    assert "RELATÓRIO AO ADVOGADO são produtos separados" in regras
    assert "DIVERGÊNCIAS documentais" in regras
    assert "Contrato completo da inicial trabalhista" in regras
    assert "anteriores aos cinco anos que antecedem o ajuizamento" in regras


def test_modelo_assalto_nao_reproduz_regras_e_precedentes_errados():
    modelo = peticao_skill_arquivos._ler("assalto_carteiro/modelo_peticao.md")  # noqa: SLF001
    assert "RE 220.907" not in modelo
    assert "arts. 76 e 77 da CLT" not in modelo
    assert "art. 272, §1º" not in modelo
    assert "salário **líquido**" not in modelo
    assert "piso mínimo de R$ 30.000,00" not in modelo.lower()
    assert "Não há lista de precedentes pronta para copiar" in modelo


def test_checklist_interno_nao_recebe_numero_de_documento_protocolavel():
    ledger = document_ledger.montar([
        {"arquivo": "Checklist de documentação.pdf", "texto": "lista interna"},
        {"arquivo": "Contracheque 08-2026.pdf", "texto": "remuneração do empregado"},
    ])
    assert [d["canonical_file"] for d in ledger] == ["Contracheque 08-2026.pdf"]


def test_capitulo_inventado_e_ordem_errada_retidos():
    contrato = contrato_secoes.montar(peticao_skill_arquivos.estrutura_da_skill())
    _, achados = contrato_secoes.canonicalizar([
        _sec("FACTS"), _sec("JULGAMENTO_ANTECIPADO"), _sec("HEADING")
    ], contrato)
    assert {a.codigo for a in achados} >= {
        "SECAO_NAO_AUTORIZADA_PELA_SKILL", "ORDEM_DE_SECOES_DIVERGENTE_DA_SKILL"
    }


def test_secao_literal_repetida_e_removida_antes_do_docx():
    contrato = contrato_secoes.montar(peticao_skill_arquivos.estrutura_da_skill())
    secoes, achados = contrato_secoes.canonicalizar([
        _sec("LEGAL_GROUNDS", "II. DO DIREITO\nTexto idêntico"),
        _sec("LEGAL_GROUNDS", "II. DO DIREITO\nTexto idêntico"),
    ], contrato)
    assert len(secoes) == 1
    assert any(a.codigo == "SECAO_DUPLICADA" for a in achados)


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
