from app.rotas.documentos import midia_sem_transcricao


def test_audio_sem_texto_pode_pedir_transcricao():
    entrega = {"arquivo": "caso/audios/relato.opus", "status_proc": "pronto", "extracao": {"texto_completo": ""}}
    assert midia_sem_transcricao(entrega)


def test_audio_ja_transcrito_nao_repete():
    entrega = {"arquivo": "relato.mp3", "status_proc": "pronto", "extracao": {"texto_completo": "Fui assaltado."}}
    assert not midia_sem_transcricao(entrega)


def test_texto_por_linhas_conta_como_transcrito():
    entrega = {"arquivo": "relato.m4a", "status_proc": "pronto", "extracao": {"texto_linhas": [{"texto": "Olá"}]}}
    assert not midia_sem_transcricao(entrega)


def test_audio_em_leitura_nao_reenfileira():
    entrega = {"arquivo": "relato.ogg", "status_proc": "processando", "extracao": None}
    assert not midia_sem_transcricao(entrega)


def test_documento_que_nao_e_midia_fica_de_fora():
    entrega = {"arquivo": "rg.pdf", "status_proc": "pronto", "extracao": {}}
    assert not midia_sem_transcricao(entrega)
