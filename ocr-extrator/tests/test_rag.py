from scripts.ingerir_jurimetria import (
    dividir,
    limpar_texto,
    magistrados_do_payload,
    texto_do_payload,
)


def test_limpa_html_e_redige_dados_diretos() -> None:
    texto = limpar_texto(
        "<p>Contato teste@example.com</p><p>CPF 123.456.789-00 e prova pericial.</p>"
    )
    assert "<p>" not in texto
    assert "teste@example.com" not in texto
    assert "123.456.789-00" not in texto
    assert "prova pericial" in texto


def test_extrai_strings_longas_do_payload() -> None:
    longo = "Fundamentação jurídica e probatória. " * 10
    assert "Fundamentação" in texto_do_payload({"resultado": {"html": longo}})


def test_chunks_tem_sobreposicao() -> None:
    texto = "Frase de fundamentação probatória. " * 150
    chunks = dividir(texto, tamanho=500, sobreposicao=80)
    assert len(chunks) > 2
    assert all(80 <= len(chunk) <= 500 for chunk in chunks)


def test_extrai_magistrados_do_payload() -> None:
    payload = {"resultado": {"magistrado": ["ANA SILVA", "JOÃO SOUZA"]}}
    assert magistrados_do_payload(payload) == ["ANA SILVA", "JOÃO SOUZA"]
