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


def test_cpf_so_sai_da_foto_de_identidade():
    """CTPS/comprovante podem citar CPF; isso não vira o CPF do cliente."""
    linhas = [
        _linha("CPF 111.444.777-35", 0),
        _linha("NOME JOSE ROBERTO", 30),
        _linha("PIS 120.12345.67-2", 60),
    ]
    assert "cpf" not in {c.nome for c in extrair_campos(linhas, "ctps")}
    assert "cpf" not in {c.nome for c in extrair_campos(linhas, "comprovante_residencia")}

    cnh = {c.nome: c.valor for c in extrair_campos(
        [
            _linha("CPF 111.444.777-35", 0),
            _linha("NOME MARIA SILVA", 20),
            _linha("N REGISTRO 12345678900", 40),
        ],
        "cnh",
    )}
    assert cnh.get("cpf") == "111.444.777-35"
