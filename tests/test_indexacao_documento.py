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
