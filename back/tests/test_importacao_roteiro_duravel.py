from app.tasks import roteiro as tarefa_roteiro


def test_worker_le_arquivo_duravel_sem_depender_do_tmp(monkeypatch, tmp_path):
    caminho_inexistente = tmp_path / "container-da-api" / "entrevista.pdf"
    conteudo = b"conteudo que veio do banco"
    atualizacoes = []

    monkeypatch.setattr(tarefa_roteiro.jobs, "conteudo_arquivo", lambda _job: conteudo)
    monkeypatch.setattr(tarefa_roteiro.jobs, "atualizar", lambda *args, **kwargs: atualizacoes.append((args, kwargs)))
    monkeypatch.setattr(tarefa_roteiro.roteiro_ia, "texto_do_documento", lambda nome, recebido: ("texto integral", "OCR") if recebido == conteudo else (_ for _ in ()).throw(AssertionError("conteúdo errado")))
    monkeypatch.setattr(tarefa_roteiro.roteiro_ia, "gerar", lambda *args, **kwargs: {"codigo": "teste", "nome": "Teste", "descricao": "", "blocos": []})
    roteiro = type("RoteiroFalso", (), {"to_dict": lambda self: {"codigo": "teste", "nome": "Teste", "descricao": "", "blocos": []}})()
    monkeypatch.setattr(tarefa_roteiro.roteiros, "de_dict", lambda _proposta: roteiro)

    resultado = tarefa_roteiro.importar_roteiro.run("job-1", str(caminho_inexistente), "Entrevista.pdf")

    assert resultado["leitura"] == "OCR"
    assert resultado["texto"] == "texto integral"
    assert not caminho_inexistente.exists()
