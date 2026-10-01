"""As skills de arquivo entram no catálogo do módulo Skills."""

from app import skill_de_arquivo as sk


def test_skills_de_arquivo_entram_no_catalogo():
    itens = {item["id"]: item for item in sk.listar()}
    assert "analise-e-organizacao-documental" in itens
    assert itens["analise-e-organizacao-documental"]["nome"] == "Análise e organização documental"
    assert itens["analise-e-organizacao-documental"]["origem"] == "arquivo"
    assert itens["escritorio-trabalhista"]["nome"] == "Escritório trabalhista"
    assert "Reclamação" in itens["escritorio-trabalhista"]["descricao"]


def test_rotulo_de_skill_adicionada_usa_o_nome():
    assert sk.rotulo("minha-skill", "Previdenciário") == "Previdenciário"
    assert sk.rotulo("analise-e-organizacao-documental") == "Análise e organização documental"
