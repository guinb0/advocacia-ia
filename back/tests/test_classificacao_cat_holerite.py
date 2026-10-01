"""CAT e contracheque não podem ser classificados como CTPS."""

from app.extractors import classificar, normalizar
from app import categorias, roteamento, valor_documento
from unittest.mock import patch


def _texto_cat() -> str:
    return normalizar("""
    COMUNICACAO DE ACIDENTE DE TRABALHO
    MINISTERIO DO TRABALHO E EMPREGO
    PREVIDENCIA SOCIAL
    SECRETARIA DE INSPECAO DO TRABALHO
    PIS 12012345678
    NIT 12012345678
    """)


def _texto_holerite() -> str:
    return normalizar("""
    CONTRACHEQUE
    FOLHA DE PAGAMENTO
    PROVENTOS DESCONTOS
    SALARIO BRUTO SALARIO LIQUIDO
    BASE INSS
    PIS 12012345678
    """)


def test_cat_nao_classifica_como_ctps():
    tipo, _, _ = classificar(_texto_cat())
    assert tipo != "ctps"
    assert tipo == "desconhecido"


def test_contracheque_nao_classifica_como_ctps():
    tipo, _, _ = classificar(_texto_holerite())
    assert tipo != "ctps"
    assert tipo == "desconhecido"


def test_cnh_cat_hab_continua_cnh():
    texto = normalizar("CARTEIRA NACIONAL DE HABILITACAO CAT. HAB AB DETRAN")
    tipo, _, _ = classificar(texto)
    assert tipo == "cnh"


def test_roteamento_cat_enviada_no_campo_errado():
    categoria = categorias.obter("acidente_trabalho_correios")
    item_ctps = next(i for i in categoria.itens if i.codigo == "DOC.06")
    item_cat = next(i for i in categoria.itens if i.codigo == "DOC.10")

    extracao = {
        "tipo": {
            "detectado": "desconhecido",
            "descricao_detectado": "desconhecido",
            "confianca_classificacao": 0,
        },
        "validacao": {"texto_utilizavel": True, "dados_utilizaveis": False},
        "texto_completo": _texto_cat(),
        "campos": [],
    }

    def leitura_cat(*_a, **_k):
        return {
            "documento": "CAT",
            "serve_para": [{"item": "DOC.10", "porque": "comunica o acidente"}],
            "achados": [],
            "atencao": [],
            "sugere_pedir": [],
        }

    with patch.object(roteamento.valor_documento, "ler", leitura_cat):
        destino = roteamento.decidir(extracao, categoria, item_cat)
    assert destino.itens == ["DOC.10"]
    assert destino.origem in {roteamento.SEMANTICO, roteamento.ESCOLHA}

    # Texto de CAT nunca deve ir para CTPS mesmo se alguém marcou DOC.06.
    extracao_ctps_falso = {
        **extracao,
        "tipo": {
            "detectado": "ctps",
            "descricao_detectado": "CTPS",
            "confianca_classificacao": 20,
        },
    }
    with patch.object(roteamento.valor_documento, "ler", leitura_cat):
        destino = roteamento.decidir(extracao_ctps_falso, categoria, item_cat)
    assert "DOC.06" not in destino.itens
    assert destino.itens == ["DOC.10"] or destino.itens == [item_cat.codigo]
