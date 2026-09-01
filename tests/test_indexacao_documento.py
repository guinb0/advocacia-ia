from app import indexacao_documento


def test_classificacao_semantica_usa_texto_integral(monkeypatch):
    recebido = {}

    def falso(extracao, pendencias, categoria):
        recebido["texto"] = extracao["texto_completo"]
        recebido["pendencias"] = pendencias
        return {"documento": "Relatório médico — psiquiatria", "achados": []}

    monkeypatch.setattr(indexacao_documento.valor_documento, "ler", falso)
    resultado = indexacao_documento.classificar(
        {"texto_completo": "Paciente compareceu à consulta médica."}, "Trabalhista"
    )
    assert recebido["texto"] == "Paciente compareceu à consulta médica."
    assert recebido["pendencias"] == []
    assert resultado["tipo_semantico"] == "Relatório médico — psiquiatria"
    assert resultado["classificador"] == "deepseek"


def test_fragmentacao_preserva_documento():
    texto = "A" * 2200 + "\n" + "B" * 2200
    partes = indexacao_documento._fragmentar(texto)
    assert len(partes) >= 2
    assert all(len(parte) <= 1800 for parte in partes)


def test_interpretacao_preenche_tipo_e_campos_sem_sobrescrever_validado():
    extracao = {
        "tipo": {"detectado": "desconhecido", "descricao_detectado": "Documento não identificado"},
        "campos": [{"nome": "cpf", "rotulo": "CPF", "valor": "111.444.777-35"}],
    }
    semantica = {
        "codigo_documento": "nao_estruturado",
        "tipo_semantico": "Laudo médico — psiquiatria",
        "achados": [
            {"campo": "CID", "valor": "F43.1"},
            {"campo": "CPF", "valor": "valor que não pode sobrescrever"},
        ],
    }

    resultado = indexacao_documento.aplicar_interpretacao(extracao, semantica)

    assert resultado["tipo"]["descricao_detectado"] == "Laudo médico — psiquiatria"
    assert resultado["tipo"]["detectado"] == "desconhecido"
    assert [campo["nome"] for campo in resultado["campos"]] == ["cpf", "cid"]
    assert resultado["campos"][1]["origem"] == "deepseek"


def test_interpretacao_nao_inventa_cpf_nem_cnh():
    extracao = {
        "tipo": {"detectado": "desconhecido"},
        "campos": [],
    }
    semantica = {
        "codigo_documento": "nao_estruturado",
        "tipo_semantico": "Comprovante",
        "achados": [
            {"campo": "CPF", "valor": "111.444.777-35"},
            {"campo": "CNH", "valor": "12345678900"},
            {"campo": "CID", "valor": "M54.5"},
        ],
    }
    resultado = indexacao_documento.aplicar_interpretacao(extracao, semantica)
    nomes = [campo["nome"] for campo in resultado["campos"]]
    assert nomes == ["cid"]
    assert "cpf" not in nomes
    assert "cnh" not in nomes
