"""Glossário de tipos de documento (`app/tipos_documento.py`), sem banco.

    .venv\\Scripts\\python.exe -m pytest tests/test_tipos_documento.py -q
"""

from __future__ import annotations

import pytest

from app import categorias, perfis
from app import tipos_documento as td
from app.extractors import ROTULOS_TIPO, normalizar


@pytest.fixture(autouse=True)
def _marcacoes_sem_banco(monkeypatch):
    """Nenhum tipo de caso marcado, a não ser o que o teste disser — sem ir ao banco."""
    monkeypatch.setattr(td, "_marcacoes", lambda: ())


def _marcar(monkeypatch, *marcacoes):
    linhas = tuple(
        {"nome": m["codigo"], "descricao": "", "ativo": True, **m} for m in marcacoes
    )
    monkeypatch.setattr(td, "_marcacoes", lambda: linhas)


def test_todo_item_de_checklist_pede_um_tipo_que_existe_no_glossario():
    sem_tipo = [
        (c.codigo, i.codigo)
        for c in categorias.CATEGORIAS.values()
        for i in c.itens
        if not i.tipo_documento
    ]
    fora_do_glossario = [
        (c.codigo, i.codigo, i.tipo_documento)
        for c in categorias.CATEGORIAS.values()
        for i in c.itens
        if i.tipo_documento and i.tipo_documento not in td.SEMENTE_POR_CODIGO
    ]
    assert sem_tipo == []
    assert fora_do_glossario == []


def test_o_mesmo_documento_tem_o_mesmo_tipo_em_todas_as_categorias():
    # O defeito que o glossário resolve: a correção gravava "DOC.10" no acidente
    # geral e "DOC.09" na doença ocupacional para o MESMO documento.
    tipos_da_cat = {
        item.tipo_documento
        for categoria in categorias.CATEGORIAS.values()
        for item in categoria.itens
        if item.nome.startswith("CAT")
    }
    assert tipos_da_cat == {"cat"}


def test_semente_sem_codigo_nem_nome_repetido():
    codigos = [s.codigo for s in td.SEMENTE]
    nomes = [normalizar(s.nome) for s in td.SEMENTE]
    assert len(codigos) == len(set(codigos))
    assert len(nomes) == len(set(nomes))
    assert all(td.RE_CODIGO.match(codigo) for codigo in codigos)


def test_tipos_do_classificador_tem_o_mesmo_codigo_no_glossario():
    assert set(ROTULOS_TIPO) - {"desconhecido"} <= set(td.SEMENTE_POR_CODIGO)


def test_item_com_classificador_usa_o_codigo_dele_como_tipo():
    rg = next(i for i in categorias.ACIDENTE_TRABALHO_GERAL.itens if i.tipo_ocr == "rg")
    assert rg.tipo_documento == "rg"
    assert rg.to_dict()["tipo_documento"] == "rg"


@pytest.mark.parametrize("codigo", ["DOC.13", "Laudo", "l", "", "1laudo", "laudo-medico"])
def test_codigo_invalido_e_recusado(codigo):
    with pytest.raises(td.ErroGlossario):
        td.validar_codigo(codigo)


def test_codigo_valido_e_gerado_do_nome():
    assert td.validar_codigo("laudo_medico") == "laudo_medico"
    assert td.gerar_codigo("Laudo médico — perícia") == "laudo_medico_pericia"
    assert td.gerar_codigo("123 teste") == "tipo_123_teste"


def test_sinonimos_sem_vazio_nem_repetido():
    assert td.normalizar_sinonimos("holerite, Holerite ,  folha  de pagamento,,") == [
        "holerite",
        "folha de pagamento",
    ]
    with pytest.raises(td.ErroGlossario):
        td.normalizar_sinonimos([f"sinonimo {n}" for n in range(td.MAXIMO_SINONIMOS + 1)])


def test_nome_obrigatorio():
    with pytest.raises(td.ErroGlossario):
        td.validar_nome("  ")


def test_desativacao_bloqueada_para_tipo_em_checklist_e_de_sistema():
    em_checklist = td.motivo_bloqueio_desativacao({"codigo": "cat", "sistema": True})
    assert em_checklist and "checklist" in em_checklist
    # A CIN não é pedida por item nenhum, mas o classificador a reconhece.
    de_sistema = td.motivo_bloqueio_desativacao({"codigo": "cin", "sistema": True})
    assert de_sistema and "sistema" in de_sistema
    assert td.motivo_bloqueio_desativacao({"codigo": "carta_do_sindicato", "sistema": False}) is None


def test_sinonimo_do_glossario_chega_a_leitura_automatica():
    contracheque = next(
        i for i in categorias.ACIDENTE_TRABALHO_GERAL.itens if i.tipo_documento == "contracheque"
    )
    glossario = {"contracheque": {"nome": "Contracheque", "sinonimos": ["holerite"]}}
    descricao = td.descrever_item(contracheque, glossario)
    assert descricao.startswith(contracheque.nome)
    assert "holerite" in descricao
    assert td.descrever_item(contracheque, {}) == contracheque.nome


def test_tipo_marcado_entra_no_fim_do_checklist_do_tipo_de_caso(monkeypatch):
    _marcar(
        monkeypatch,
        {"codigo": "carta_sindicato", "categoria": "doenca_ocupacional", "nome": "Carta do sindicato"},
    )
    item = categorias.obter("doenca_ocupacional").itens[-1]
    assert item.codigo == "GLOS.carta_sindicato"
    assert item.nome == "Carta do sindicato"
    assert item.tipo_documento == "carta_sindicato"
    assert item.do_glossario and not item.obrigatorio
    assert item.numero == max(i.numero for i in categorias.DOENCA_OCUPACIONAL.itens) + 1
    # Só no tipo de caso marcado, e sem mexer no checklist fixo.
    assert all(i.do_glossario is False for i in categorias.obter("acidente_trabalho_geral").itens)
    assert all(not i.do_glossario for i in categorias.CATEGORIAS["doenca_ocupacional"].itens)
    doenca = next(c for c in categorias.listar() if c.codigo == "doenca_ocupacional")
    assert doenca.itens[-1].codigo == "GLOS.carta_sindicato"


def test_tipo_desativado_ou_ja_pedido_nao_ganha_item(monkeypatch):
    _marcar(
        monkeypatch,
        {"codigo": "carta_sindicato", "categoria": "doenca_ocupacional", "ativo": False},
        {"codigo": "cnis", "categoria": "doenca_ocupacional"},
    )
    assert categorias.obter("doenca_ocupacional") == categorias.DOENCA_OCUPACIONAL


def test_tipos_de_caso_validados_na_ordem_do_catalogo_sem_os_ja_pedidos():
    assert td.validar_categorias(
        ["doenca_ocupacional", "acidente_trabalho_geral", "doenca_ocupacional"], "carta_sindicato"
    ) == ["acidente_trabalho_geral", "doenca_ocupacional"]
    # O CNIS já está no checklist fixo de todos esses: nada a gravar.
    assert td.validar_categorias(["doenca_ocupacional", "auxilio_acidente"], "cnis") == []
    with pytest.raises(td.ErroGlossario):
        td.validar_categorias(["nao_existe"], "carta_sindicato")


def test_tipo_marcado_so_desativa_quando_desmarcado(monkeypatch):
    _marcar(monkeypatch, {"codigo": "carta_sindicato", "categoria": "auxilio_acidente"})
    tipo = {"codigo": "carta_sindicato", "nome": "Carta do sindicato", "sistema": False}
    bloqueio = td.motivo_bloqueio_desativacao(tipo)
    assert bloqueio and "Desmarque" in bloqueio
    assert td.motivo_bloqueio_desativacao(tipo, marcadas=[]) is None
    item = td.itens_do_checklist("carta_sindicato", nome="Carta do sindicato")
    assert item == [
        {
            "categoria": "auxilio_acidente",
            "categoria_nome": categorias.AUXILIO_ACIDENTE.nome,
            "item": "GLOS.carta_sindicato",
            "nome": "Carta do sindicato",
            "do_glossario": True,
        }
    ]


def test_manter_o_glossario_e_modulo_de_quem_administra():
    assert td.MODULO in perfis.CODIGOS_MODULOS
    semente = {perfil["codigo"]: perfil["modulos"] for perfil in perfis.SEMENTE}
    assert td.MODULO in semente["advogado"]
    assert td.MODULO in semente["secretario"]
    assert td.MODULO not in semente["cliente"]
    assert td.MODULO not in semente["revisor"]
