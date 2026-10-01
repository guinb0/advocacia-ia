"""Catálogo de tipos de caso (`app/tipos_caso.py`), sem banco.

    .venv\\Scripts\\python.exe -m pytest tests/test_tipos_caso.py -q
"""

from __future__ import annotations

import re

import pytest

from app import categorias, perfis, triagem
from app import tipos_caso as tc


@pytest.fixture(autouse=True)
def _catalogo_sem_banco(monkeypatch):
    """Nenhuma ação criada, a não ser o que o teste disser — sem ir ao banco."""
    monkeypatch.setattr(tc, "_catalogo", lambda: ())


def _registro(**campos):
    base = {
        "codigo": "acidente_transporte",
        "nome": "Acidente de transporte",
        "descricao": "Motorista ferido em serviço.",
        "quando_usar": "Quando o veículo é a ferramenta de trabalho.",
        "pistas": [{"expressao": "caminhão", "peso": 9}],
        "ativo": True,
        "sistema": False,
        "versao": 1,
        "criado_em": "2026-09-23T00:00:00+00:00",
        "criado_por": "gestor",
        "atualizado_em": "2026-09-23T00:00:00+00:00",
        "atualizado_por": "gestor",
        "itens": [],
        "total_obrigatorios": 0,
    }
    return {**base, **campos}


def _com_catalogo(monkeypatch, *registros):
    monkeypatch.setattr(tc, "_catalogo", lambda: tuple(registros))


# ---------------------------------------------------------------- validação


def test_codigo_gerado_a_partir_do_nome():
    assert tc.gerar_codigo("Acidente de transporte") == "acidente_de_transporte"
    assert tc.gerar_codigo("Doença ocupacional — LER/DORT") == "doenca_ocupacional_ler_dort"
    # Nome que começa por número não vira código começando por número.
    assert tc.gerar_codigo("13º salário").startswith("caso_")


def test_codigo_de_acao_do_sistema_e_recusado():
    """Com o mesmo código, a ação criada SUBSTITUIRIA a do .docx em `catalogo()`."""
    with pytest.raises(tc.ConflitoTipoCaso):
        tc.criar(nome="Outra coisa", codigo="acidente_trabalho_correios", usuario="gestor")
    with pytest.raises(tc.ConflitoTipoCaso):
        tc.criar(nome="Outra coisa", codigo="em_triagem", usuario="gestor")


def test_item_que_aponta_para_tipo_fora_do_glossario_e_recusado(monkeypatch):
    monkeypatch.setattr(tc.tipos_documento, "codigos_conhecidos", lambda: {"cat", "rg"})
    with pytest.raises(tc.ErroTipoCaso, match="glossário"):
        tc.validar_itens([{"nome": "Laudo do IML", "tipo_documento": "laudo_iml"}])
    # Sem tipo o item é aceito: nem todo documento do checklist tem classificador.
    assert tc.validar_itens([{"nome": "Laudo do IML"}])[0]["tipo_documento"] is None


def test_itens_recebem_a_ordem_em_que_vieram(monkeypatch):
    monkeypatch.setattr(tc.tipos_documento, "codigos_conhecidos", lambda: {"rg"})
    itens = tc.validar_itens(
        [{"nome": "Procuração", "obrigatorio": True}, {"nome": "RG", "tipo_documento": "rg"}]
    )
    assert [i["numero"] for i in itens] == [1, 2]
    # O código NÃO sai da tela: quem o dá é a gravação, e ele nunca se repete.
    assert [i["codigo"] for i in itens] == ["", ""]


def test_pistas_sem_repetir_e_com_peso_na_faixa():
    pistas = tc.normalizar_pistas(
        [{"expressao": "caminhão", "peso": 9}, {"expressao": "CAMINHAO", "peso": 3}]
    )
    assert pistas == [{"expressao": "caminhão", "peso": 9}]
    with pytest.raises(tc.ErroTipoCaso, match="peso"):
        tc.normalizar_pistas([{"expressao": "carreta", "peso": 99}])
    # Texto colado da lista do escritório, sem peso: vale o peso médio.
    assert tc.normalizar_pistas("carreta, motorista") == [
        {"expressao": "carreta", "peso": 6},
        {"expressao": "motorista", "peso": 6},
    ]


# -------------------------------------------- o catálogo que o Acervo enxerga


def test_acao_criada_entra_no_catalogo_como_categoria(monkeypatch):
    _com_catalogo(
        monkeypatch,
        _registro(
            itens=[
                {
                    "codigo": "DOC.01",
                    "numero": 1,
                    "nome": "CNH",
                    "obrigatorio": True,
                    "tipo_documento": "cnh",
                    "observacao": "",
                }
            ]
        ),
    )
    catalogo = categorias.catalogo()
    assert "acidente_transporte" in catalogo
    nova = catalogo["acidente_transporte"]
    assert isinstance(nova, categorias.Categoria)
    assert [i.codigo for i in nova.obrigatorios] == ["DOC.01"]
    # O resto do Acervo lê pelo mesmo caminho das cinco do código.
    assert categorias.obter("acidente_transporte").nome == "Acidente de transporte"


def test_acao_desativada_some_da_criacao_mas_continua_respondendo(monkeypatch):
    _com_catalogo(monkeypatch, _registro(ativo=False))
    assert "acidente_transporte" not in [c.codigo for c in categorias.listar()]
    # O caso aberto antes do desligamento precisa do checklist dela.
    assert categorias.obter("acidente_transporte") is not None


def test_acao_do_codigo_desligada_na_tela_some_da_lista(monkeypatch):
    _com_catalogo(
        monkeypatch,
        _registro(codigo="assalto_carteiro", nome="Assalto a Carteiro", sistema=True, ativo=False),
    )
    oferecidas = [c.codigo for c in categorias.listar()]
    assert "assalto_carteiro" not in oferecidas
    assert "acidente_trabalho_correios" in oferecidas
    assert categorias.obter("assalto_carteiro") is not None


def test_criadas_vem_depois_das_do_codigo(monkeypatch):
    _com_catalogo(monkeypatch, _registro(), _registro(codigo="zelador", nome="Zelador"))
    oferecidas = [c.codigo for c in categorias.listar()]
    assert oferecidas[: len(categorias._CATEGORIAS_ATIVAS)] == list(categorias._CATEGORIAS_ATIVAS)
    assert oferecidas[-2:] == ["acidente_transporte", "zelador"]


# ------------------------------------------------------------------ triagem


def test_triagem_pontua_a_acao_criada(monkeypatch):
    _com_catalogo(
        monkeypatch,
        _registro(
            pistas=[
                {"expressao": "carreta", "peso": 14},
                {"expressao": "motorista carreteiro", "peso": 14},
            ]
        ),
    )
    resultado = triagem.classificar_entrevista(
        "Sou motorista carreteiro e capotei a carreta na BR-040 voltando da entrega."
    )
    assert resultado["sugestoes"][0]["codigo"] == "acidente_transporte"


def test_pistas_de_acao_desativada_nao_pontuam(monkeypatch):
    _com_catalogo(monkeypatch, _registro(ativo=False, pistas=[{"expressao": "carreta", "peso": 14}]))
    assert tc.pistas_de_triagem() == {}


def test_a_instrucao_do_modelo_descreve_a_acao_criada(monkeypatch):
    _com_catalogo(monkeypatch, _registro())
    texto = triagem.instrucao()
    assert "6. acidente_transporte — Acidente de transporte" in texto
    assert "Quando o veículo é a ferramenta de trabalho." in texto
    # O bloco entra ANTES das regras de decisão, não depois.
    assert texto.index("acidente_transporte") < texto.index(triagem.MARCA_DECISAO)


def test_a_instrucao_fixa_tem_onde_encaixar_as_acoes_criadas():
    """Se alguém reescrever a instrução e tirar a marca, o bloco não entraria."""
    assert triagem.MARCA_DECISAO in triagem.INSTRUCAO
    numeradas = re.findall(r"^\d+\. [a-z_]+ —", triagem.INSTRUCAO, re.M)
    assert len(numeradas) == triagem.CATEGORIAS_NA_INSTRUCAO


# ---------------------------------------------------- código de item estável


class _ConexaoFalsa:
    """Só o bastante para conferir o que `_gravar_itens` manda para o banco."""

    def __init__(self):
        self.comandos: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.comandos.append((" ".join(sql.split()), tuple(params)))
        return self

    def fetchall(self):
        return []

    def fetchone(self):
        return None


def test_codigo_de_item_removido_nunca_e_reaproveitado():
    """Reaproveitar faria os documentos do item antigo reaparecerem no novo."""
    con = _ConexaoFalsa()
    antes = [
        {"codigo": "DOC.01", "numero": 1, "nome": "Procuração", "obrigatorio": True,
         "tipo_documento": "procuracao", "observacao": ""},
        {"codigo": "DOC.02", "numero": 2, "nome": "RG", "obrigatorio": True,
         "tipo_documento": "rg", "observacao": ""},
    ]
    # O gestor tira o RG e acrescenta a CNH: ela é o item 3, não o 2.
    depois = [
        {"codigo": "DOC.01", "numero": 1, "nome": "Procuração", "obrigatorio": True,
         "tipo_documento": "procuracao", "observacao": ""},
        {"codigo": "", "numero": 2, "nome": "CNH", "obrigatorio": False,
         "tipo_documento": "cnh", "observacao": ""},
    ]
    proximo = tc._gravar_itens(con, "acidente_transporte", antes, depois, 3)
    assert depois[1]["codigo"] == "DOC.03"
    assert proximo == 4
    apagados = [p for sql, p in con.comandos if sql.startswith("DELETE")]
    assert apagados == [("acidente_transporte", "DOC.02")]


def test_trocar_so_o_tipo_do_item_conta_como_alteracao():
    """O retrato do histórico resume o item; a comparação da edição não pode usá-lo.

    Pelo resumo, "DOC.01 RG *" antes e depois são iguais — e a edição que só trocou o
    tipo do glossário voltaria como "nada a fazer", sem gravar e sem avisar.
    """
    def _reg(tipo_documento, observacao=""):
        return {
            "nome": "Acidente de transporte",
            "descricao": "",
            "quando_usar": "",
            "pistas": [],
            "ativo": True,
            "itens": [
                {"codigo": "DOC.01", "numero": 1, "nome": "RG", "obrigatorio": True,
                 "tipo_documento": tipo_documento, "observacao": observacao},
            ],
        }

    assert tc._retrato(_reg("rg")) == tc._retrato(_reg("cnh"))
    assert tc._estado(_reg("rg")) != tc._estado(_reg("cnh"))
    assert tc._estado(_reg("rg")) != tc._estado(_reg("rg", "frente e verso"))


# -------------------------------------------------------------------- acesso


def test_o_modulo_existe_e_esta_com_quem_administra_o_escritorio():
    assert tc.MODULO in perfis.CODIGOS_MODULOS
    por_codigo = {p["codigo"]: p for p in perfis.SEMENTE}
    assert tc.MODULO in por_codigo["advogado"]["modulos"]
    assert tc.MODULO in por_codigo["secretario"]["modulos"]
    # Quem só revisa petição não mexe no catálogo de ações.
    assert tc.MODULO not in por_codigo["revisor"]["modulos"]
