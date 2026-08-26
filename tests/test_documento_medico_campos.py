from app.extractors import Linha, extrair_campos


def _linha(texto: str, y: float, altura: float = 14) -> Linha:
    return Linha(texto=texto, confianca=.96, y=y, x=0, largura=200, altura=altura)


def test_documento_medico_desconhecido_nao_inventa_dados_pessoais():
    linhas = [
        _linha("CLÍNICA INTEGRADA", 0, 42),
        _linha("MÉDICO PSIQUIATRA", 30, 18),
        _linha("CEP 72115-700", 60),
        _linha("Paciente compareceu à consulta", 90),
    ]
    campos = {campo.nome: campo.valor for campo in extrair_campos(linhas, "desconhecido")}
    assert "nome" not in campos
    assert "nome_mae" not in campos
    assert "cep" not in campos
    assert not any(nome.startswith("filiacao") for nome in campos)


def test_identidade_mantem_extracao_de_nome_e_filiacao():
    linhas = [
        _linha("NOME COMPLETO JOAO DA SILVA", 0, 20),
        _linha("NOME DA MAE JOANA PEREIRA", 30, 16),
    ]
    campos = {campo.nome: campo.valor for campo in extrair_campos(linhas, "cnh")}
    assert campos["nome"] == "JOAO DA SILVA"
    assert campos["nome_mae"] == "JOANA PEREIRA"
