"""Regressões da leitura de endereço em contas de consumo."""

from app.extractors import Linha, extrair_campos


def _linha(texto: str, y: float) -> Linha:
    return Linha(texto=texto, confianca=0.96, y=y, x=0, largura=len(texto), altura=1)


def test_endereco_rotulado_com_rua_abreviada_em_varias_linhas():
    linhas = [
        _linha("ENDEREÇO:", 0),
        _linha("R 26 NORTE LT 03 AP 1001 ED MOLIERE", 1),
        _linha("TAGUATINGA - DF", 2),
        _linha("CEP: 71.917-360", 3),
        _linha("REF: MÊS / ANO SET/2025", 4),
    ]
    campos = {campo.nome: campo for campo in extrair_campos(linhas, "comprovante_residencia")}
    assert campos["endereco"].valor == (
        "R 26 NORTE LT 03 AP 1001 ED MOLIERE TAGUATINGA - DF CEP: 71.917-360"
    )
    assert campos["cep"].valor == "71917-360"
