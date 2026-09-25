"""Recuperação por tese, proveniência e portão de qualidade — sem banco e sem modelo."""

from types import SimpleNamespace

from app import conferencia_peticao as c
from app import jurimetria_caso, peticao_local as pl, peticao_skill_arquivos as skill, rag, recuperacao_por_tese as r

PLANO = {
    "cronologia": [{"fato": "Assalto à mão armada na agência em 05/12/2024", "fonte": "CAT"}],
    "teses": [
        {"tese": "Responsabilidade objetiva por atividade de risco", "fatos_que_sustentam": ["assalto no caixa"]},
        {"tese": "Dano moral in re ipsa", "fatos_que_sustentam": ["rendido sob arma"]},
    ],
}


def _trecho(processo, score, tipo="ACORDAO", texto="texto do julgado"):
    t = SimpleNamespace(
        texto=texto, similaridade=score, titulo=f"TRT8 {processo}", identificador=processo,
        metadados={"tipo_documento": tipo, "tribunal": "TRT8", "numero_processo": processo,
                   "status_verificacao": "VERIFIED"}, url="",
    )
    t.referencia = lambda: {"processo": processo, "identificador": processo}
    return t


def test_uma_consulta_por_tese_alem_da_global():
    consultas = r.consultas_do_plano(PLANO, "dossiê", "Acidente de Trabalho")
    assert len(consultas) == 3
    assert "Responsabilidade objetiva" in consultas[1]["consulta"] and "assalto no caixa" in consultas[1]["consulta"]
    assert len(consultas[0]["consulta"]) < 1000  # não é o dossiê inteiro


def test_sem_plano_a_consulta_global_nao_e_vazia():
    assert r.consultas_do_plano(None, "dossiê do caso" * 20, "Cat")[0]["consulta"]


def test_precedentes_unem_deduplicam_e_registram_as_teses(monkeypatch):
    por_consulta = {
        "resp": [_trecho("0001", .8), _trecho("0002", .7)],
        "moral": [_trecho("0001", .85), _trecho("0003", .6, tipo="Sentença")],
    }
    monkeypatch.setattr(jurimetria_caso, "buscar_focada",
                        lambda q, **k: (por_consulta["resp" if "objetiva" in q else "moral"], "TRT8", "PA"))
    trechos, provs, erros = r.precedentes(r.consultas_do_plano(PLANO, "", "x")[1:], "")
    ids = [p.id for p in provs]
    assert sorted(ids) == ["0001", "0002", "0003"] and not erros
    p1 = next(p for p in provs if p.id == "0001")
    assert len(p1.teses) == 2 and p1.score == .85  # serve a duas teses: sobe na ordem
    assert ids[0] == "0001"
    assert "persuasivo" in next(p for p in provs if p.id == "0003").natureza


def test_precedentes_respeitam_uf_estruturada_do_caso(monkeypatch):
    chamadas = []

    def buscar(consulta, **kwargs):
        chamadas.append(kwargs)
        return [_trecho("0001", .9)], "TRT8", "PA"

    monkeypatch.setattr(jurimetria_caso, "buscar_focada", buscar)
    trechos, _provs, erros = r.precedentes(
        r.consultas_do_plano(PLANO, "", "x")[:1], "relato sem endereço", uf="PA"
    )

    assert trechos and not erros
    assert chamadas and chamadas[0]["uf"] == "PA"


def test_precedente_nao_verificado_nunca_entra_no_contexto(monkeypatch):
    item = _trecho("0001", .9)
    item.metadados["status_verificacao"] = "UNVERIFIED"
    monkeypatch.setattr(jurimetria_caso, "buscar_focada", lambda *a, **k: ([item], "TRT8", "PA"))
    trechos, provs, erros = r.precedentes(r.consultas_do_plano(PLANO, "", "x")[:1], "")
    assert not trechos and not provs and not erros


def test_uf_da_jurisprudencia_vem_do_cadastro_antes_do_ocr(monkeypatch):
    monkeypatch.setattr(pl.armazenamento, "obter_caso", lambda _caso: {"uf": "PA"})
    monkeypatch.setattr(pl.armazenamento, "obter_qualificacao", lambda _caso: {"uf": "SP"})

    assert pl._uf_jurisprudencia_do_caso("caso", "endereço menciona RJ") == "PA"


def test_falha_do_vector_db_e_observavel_no_diagnostico(monkeypatch):
    def cai(*a, **k):
        raise RuntimeError("pgvector fora")
    monkeypatch.setattr(jurimetria_caso, "buscar_focada", cai)
    diag = {"recuperacao": {}, "fallbacks": []}
    pl._DIAG.set(diag)
    assert pl._precedentes_para_redigir("ctx", r.consultas_do_plano(PLANO, "", "x")) == ""
    info = diag["recuperacao"]["precedentes"]
    assert info["ok"] is False and "pgvector fora" in info["erro"]


def test_trechos_recuperados_entram_no_contexto_e_na_proveniencia(monkeypatch):
    monkeypatch.setattr(jurimetria_caso, "buscar_focada", lambda q, **k: ([_trecho("0001", .9, texto="ECT responde objetivamente")], "TRT8", "PA"))
    diag = {"recuperacao": {}, "fallbacks": []}
    pl._DIAG.set(diag)
    bloco = pl._precedentes_para_redigir("ctx", r.consultas_do_plano(PLANO, "", "x"))
    assert "[J1]" in bloco and "ECT responde objetivamente" in bloco and "persuasivo" in bloco
    assert diag["proveniencia"] and diag["proveniencia"][0][0].canal == "precedente"


def test_influencia_distingue_executou_de_contribuiu():
    usado = r.Proveniencia("precedente", "0000123-45.2024.5.08.0001", teses=["a"])
    ignorado = r.Proveniencia("precedente", "0009999-99.2024.5.08.0009", teses=["a"])
    secoes = [{"code": "LEGAL_GROUNDS", "content": "Conforme o processo 0000123-45.2024.5.08.0001, a ECT responde."}]
    r.medir_influencia([(usado, ""), (ignorado, "")], secoes)
    assert usado.contribuiu and usado.secoes == ["LEGAL_GROUNDS"]
    assert ignorado.contribuiu is False


def test_peca_do_acervo_so_conta_se_o_argumento_foi_reaproveitado():
    trecho = "a responsabilidade objetiva do empregador decorre da atividade de risco desenvolvida pela empresa em suas agências"
    prov = r.Proveniencia("peca", "modelo.docx")
    r.medir_influencia([(prov, trecho)], [{"code": "X", "content": trecho + " e mais texto"}])
    assert prov.contribuiu
    outra = r.Proveniencia("peca", "outra.docx")
    r.medir_influencia([(outra, trecho)], [{"code": "X", "content": "texto sem relação alguma com o trecho recuperado da peça"}])
    assert outra.contribuiu is False


def test_assunto_do_acervo_inclui_o_geral_do_modelo_especifico():
    texto = "assalto à mão armada agência Correios roubo atendente caixa"
    assert skill.assuntos_relacionados("Acidente de Trabalho - Correios", "x", texto)[0] == "assalto_carteiro"
    assert "doenca_ocupacional_acidente_trabalho" in skill.assuntos_relacionados("Acidente de Trabalho - Correios", "x", texto)


def test_portao_de_qualidade_barra_marcadores_no_corpo():
    secoes = [{"code": "LEGAL_GROUNDS", "content": "A ECT responde. [PESQUISAR PRECEDENTE ATUAL E APLICÁVEL SOBRE ESTE PONTO]"},
              {"code": "FACTS", "content": "Súmula 463 [CONFERIR: citação não verificada no acervo]"}]
    achados = c.conferir(secoes, c.Fontes(anexos=[], numerados=[]))
    bloqueantes = [a for a in achados if a.codigo == "PLACEHOLDER_NO_TEXTO" and a.bloqueia]
    assert len(bloqueantes) == 2


def test_precedentes_vinculantes_do_assunto_vem_da_skill():
    texto = skill.carregar("Acidente de Trabalho - Correios", "x", "assalto à mão armada agência Correios roubo atendente")
    assert "Tema nº 932" in texto and "Tema nº 84" in texto and "Tema nº 21" in texto


def test_citacao_de_tema_que_esta_na_skill_nao_e_barrada():
    fontes = c.Fontes(anexos=[], numerados=[], material=skill.carregar("Acidente de Trabalho - Correios", "x", "assalto Correios agência atendente roubo"))
    achados = c.conferir([{"code": "LEGAL_GROUNDS", "content": "Aplica-se o Tema nº 932 do STF."}], fontes)
    assert not [a for a in achados if a.codigo == "CITACAO_NAO_VERIFICADA"]


def test_aspas_so_valem_para_texto_que_esta_no_material():
    fontes = c.Fontes(anexos=[], numerados=[], material="a jurisprudência é iterativa e notória no sentido de que o dano moral é in re ipsa nas hipóteses de assalto ao banco postal")
    ok = "Decidiu-se que “a jurisprudência é iterativa e notória no sentido de que o dano moral é in re ipsa nas hipóteses de assalto”."
    inventada = "Decidiu-se que “a empresa deve pagar indenização integral por qualquer assalto ocorrido em agência dos correios do país”."
    assert not [a for a in c.conferir([{"code": "X", "content": ok}], fontes) if a.codigo == "CITACAO_LITERAL_SEM_FONTE"]
    assert [a for a in c.conferir([{"code": "X", "content": inventada}], fontes) if a.codigo == "CITACAO_LITERAL_SEM_FONTE" and a.bloqueia]


def test_secao_sem_titulo_do_redator_fica_sem_titulo():
    (secao,) = pl._normalizar_secoes([{"code": "HEADING", "content": "texto"}])
    assert secao["label"] == ""
