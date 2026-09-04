from app import casos


def test_situacao_lista_arquivo_em_leitura_ou_revisao_uma_vez():
    caso = {"id": "c1", "categoria": "acidente_trabalho_correios"}
    base = {
        "id": "e1", "caso_id": "c1", "item_codigo": "DOC.11", "arquivo": "ocorrencia.png",
        "tipo_detectado": "certidao_ocorrencia_policial", "tipo_confere": None,
        "veredito": "APROVADO_COM_RESSALVAS", "dados_utilizaveis": False,
        "confirmado_manual": False, "score_legibilidade": 99, "itens_atendidos": ["DOC.11"],
        "texto_utilizavel": True, "status_proc": "pronto", "erro_proc": None,
        "criado_em": "2026-09-02T12:00:00+00:00",
    }
    situacao = casos.situacao_de(caso, [
        {**base, "analise_status": "REVISAO_NECESSARIA", "analise_etapa": "revisao_humana"},
        {**base, "id": "e2", "arquivo": "rg.png", "itens_atendidos": ["DOC.03"], "status_proc": "processando", "analise_status": "PROCESSANDO", "analise_etapa": "ocr_mistral"},
        {**base, "id": "e3", "arquivo": "cpf.png", "itens_atendidos": ["DOC.04"], "analise_status": "CONCLUIDA"},
    ])
    assert [e["id"] for e in situacao["em_processamento"]] == ["e1", "e2"]
    assert situacao["progresso"]["em_processamento"] == 2
