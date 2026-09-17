from scripts.ingerir_corpus_juridico import decodificar, extrair, dispositivos

def test_rejeita_mojibake():
    try:
        decodificar(b'Constitui\xc3\x83\xc2\xa7\xc3\x83\xc2\xa3o')
    except ValueError as e:
        assert 'ENCODING_CORRUPTO' in str(e)
    else:
        raise AssertionError('mojibake não pode entrar no corpus')

def test_preserva_artigos_e_contexto():
    texto = extrair('<h1>TÍTULO I</h1><p>Art. 1º Texto integral.</p><p>Art. 2º Outro texto.</p>')
    itens = dispositivos({'nome':'Lei de teste'}, texto)
    assert [x[0] for x in itens] == ['art-1º', 'art-2º']
    assert 'Lei de teste' in itens[0][3]
