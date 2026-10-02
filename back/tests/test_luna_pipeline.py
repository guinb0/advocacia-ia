from app.juridico import luna_pipeline


def _llm(_i, _e):
    return {"teses": [{"catalogo_id": "K1", "tese": "Dano moral", "decisao": "SUPPORTED", "fatos_que_suportam": ["M01"]}]}


def test_double_pass_deduplica_e_registra_metricas():
    saida, telemetria, skill = luna_pipeline.issue_spotting_duplo(
        _llm, matriz={"fatos": [{"id": "M01", "fato": "acidente"}]}, catalogo=[{"id": "K1", "tema": "dano"}], textos_skill={"SKILL.md": "regra"})
    assert len(saida["teses"]) == 1 and len(telemetria) == 2 and skill["files_loaded"] == ["SKILL.md"]


def test_contrato_de_capitulo_so_referencia_ids_autorizados():
    prep = {"issues": {"teses": [{"id": "I1", "decisao": "INCLUIR", "fatos_que_suportam": ["M1"], "prova": ["DOC1"]}]},
            "plano_est": {"pedidos": [{"id": "P1", "issue_id": "I1"}]}, "autoridades_por_tese": {"I1": []}}
    contrato = luna_pipeline.contratos_de_capitulo(prep)[0]
    assert contrato["allowed_fact_ids"] == ["M1"] and contrato["linked_request_ids"] == ["P1"]


def test_prompt_de_capitulo_e_revisores_sao_read_only():
    contrato = {"chapter_id": "CH_I1", "allowed_fact_ids": ["M1"], "allowed_authority_ids": ["A1"]}
    texto = luna_pipeline.prompt_capitulo(contrato, {"thesis": "x"})
    revisoes = luna_pipeline.prompts_de_revisao([{"content": "texto"}], {"facts": [], "issues": []})
    assert "NAO_CRIAR_REQUESTS" in texto and len(revisoes) == 3 and all("NAO_ALTERE_DOCUMENTO" in x["prompt"] for x in revisoes)
