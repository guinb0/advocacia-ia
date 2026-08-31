from app import roteamento, valor_documento
from app.categorias import Categoria, ItemChecklist


def _categoria() -> Categoria:
    return Categoria(
        codigo="acidente",
        nome="Acidente do trabalho",
        descricao="",
        itens=(
            ItemChecklist("DOC.CAT", 1, "CAT", True, None, ""),
            ItemChecklist("DOC.CTPS", 2, "CTPS", True, "ctps", ""),
        ),
    )


def test_correcao_anterior_entra_no_prompt_sem_texto_de_outro_cliente(monkeypatch):
    capturado = {}

    def responder(mensagem: str):
        capturado["mensagem"] = mensagem
        return {
            "documento": "CAT",
            "codigo_documento": "nao_estruturado",
            "serve_para": [{"item": "DOC.CAT", "porque": "título CAT"}],
        }

    monkeypatch.setattr(valor_documento, "_chamar_modelo", responder)
    extracao = {
        "texto_linhas": [{"texto": "COMUNICAÇÃO DE ACIDENTE DE TRABALHO " * 3}]
    }
    valor_documento.ler(
        extracao,
        [{"codigo": "DOC.CAT", "nome": "CAT"}],
        "acidente",
        correcoes=[
            {
                "tipo_sugerido": "CTPS",
                "rotulo_correto": "CAT",
                "item_codigo": "DOC.CAT",
                "quantidade": 3,
            }
        ],
    )
    assert "3 vez(es): 'CTPS' foi corrigido para 'CAT'" in capturado["mensagem"]


def test_confusao_conhecida_recebe_segunda_leitura_sem_descartar_fallback(monkeypatch):
    categoria = _categoria()
    extracao = {
        "tipo": {"detectado": "ctps", "descricao_detectado": "CTPS"},
        "validacao": {"texto_utilizavel": True},
    }
    monkeypatch.setattr(
        roteamento.armazenamento,
        "memoria_correcoes_classificacao",
        lambda _categoria: [
            {
                "tipo_sugerido": "CTPS",
                "rotulo_correto": "CAT",
                "item_codigo": "DOC.CAT",
                "quantidade": 2,
            }
        ],
    )
    monkeypatch.setattr(
        roteamento,
        "_semantico",
        lambda *_args: (["DOC.CAT"], 65, "corrigido pela leitura", {"documento": "CAT"}),
    )
    destino = roteamento.decidir(extracao, categoria)
    assert destino.itens == ["DOC.CAT"]
    assert destino.origem == roteamento.SEMANTICO
