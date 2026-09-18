"""Busca do checklist no CONTEÚDO lido dos documentos (campos e texto do OCR)."""

from app import armazenamento, casos

EXTRACOES = [
    {
        "id": "e1",
        "arquivo": "comprovante.pdf",
        "item_codigo": "comprovante_residencia",
        "status_proc": "pronto",
        "extracao": {
            "tipo": {"descricao": "Comprovante de residência"},
            "campos": [
                {"rotulo": "Titular", "valor": "José da Silva"},
                {"rotulo": "CEP", "valor": "70.040-010"},
            ],
            "texto_completo": "CONTA DE LUZ\nSQN 102 Bloco A Brasília DF CEP 70.040-010",
        },
    },
    {
        "id": "e2",
        "arquivo": "cin.jpg",
        "item_codigo": "rg",
        "status_proc": "pronto",
        "extracao": {
            "campos": [{"rotulo": "Nome", "valor": "José da Silva"}],
            "texto_completo": "CARTEIRA DE IDENTIDADE NACIONAL",
        },
    },
]


def _preparar(monkeypatch):
    monkeypatch.setattr(armazenamento, "obter_caso", lambda caso_id: {"id": caso_id})
    monkeypatch.setattr(armazenamento, "listar_extracoes_do_caso", lambda caso_id: EXTRACOES)
    monkeypatch.setattr(
        armazenamento,
        "listar_entregas",
        lambda caso_id: [
            {"id": "e1", "itens_atendidos": ["comprovante_residencia"]},
            {"id": "e2", "itens_atendidos": ["rg", "cpf"]},
        ],
    )


def test_rotulo_do_campo_acha_o_documento(monkeypatch):
    _preparar(monkeypatch)
    [achado] = casos.buscar_no_conteudo("c1", "cep")
    assert achado["itens"] == ["comprovante_residencia"]
    assert achado["onde"] == ["CEP: 70.040-010"]


def test_numero_sem_pontuacao_acha_o_valor_formatado(monkeypatch):
    _preparar(monkeypatch)
    [achado] = casos.buscar_no_conteudo("c1", "70040010")
    assert achado["entrega_id"] == "e1"


def test_texto_do_ocr_sem_acento_e_todos_os_termos(monkeypatch):
    _preparar(monkeypatch)
    assert [a["entrega_id"] for a in casos.buscar_no_conteudo("c1", "brasilia luz")] == ["e1"]
    assert casos.buscar_no_conteudo("c1", "brasilia identidade") == []


def test_documento_que_atende_varios_itens(monkeypatch):
    _preparar(monkeypatch)
    [achado] = casos.buscar_no_conteudo("c1", "identidade nacional")
    assert achado["itens"] == ["rg", "cpf"]
    assert "IDENTIDADE NACIONAL" in achado["onde"][0]


def test_caso_inexistente_e_busca_vazia(monkeypatch):
    _preparar(monkeypatch)
    assert casos.buscar_no_conteudo("c1", "   ") == []
    monkeypatch.setattr(armazenamento, "obter_caso", lambda caso_id: None)
    assert casos.buscar_no_conteudo("c1", "cep") is None
