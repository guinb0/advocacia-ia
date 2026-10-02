"""Motor jurídico (fase 1): níveis de severidade, grafo de raciocínio, matriz de prova e lacunas, proposições com
certeza jurídica, contrateses, scores e a integração no orquestrador.

Números de norma e precedente são FICTÍCIOS (9xxx): testa-se o mecanismo, não o conteúdo de norma real.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.juridico import (auditores, autoridades as aut, contrateses, orquestrador, proposicoes, prova, raciocinio, scores,
                          teses)
from app.juridico.fatos import ALEGADO, CONFIRMADO, INFERIDO

HOJE = date(2026, 10, 15)


def _fato(id_, fato, *, estado=CONFIRMADO, documento="", fonte="", chave="", valor="", contradicoes=None):
    return {"id": id_, "fato": fato, "chave": chave, "valor": valor, "fonte": fonte or documento or "entrevista",
            "documento": documento, "pagina": None, "confianca": 0.9, "estado": estado, "contradicoes": contradicoes or [],
            "origem": "teste"}


def _matriz():
    return {"fatos": [
        _fato("M001", "contrato de trabalho de 44 horas semanais", documento="CTPS", chave="contrato.carga_horaria", valor="44h"),
        _fato("M002", "trabalhava das 8h às 20h de segunda a sábado", estado=ALEGADO),
        _fato("M003", "horas além da oitava nunca foram pagas", documento="contracheques"),
        _fato("M004", "gerente humilhava o reclamante de forma reiterada na frente de clientes", estado=ALEGADO),
        _fato("M005", "atestado médico de transtorno de ansiedade", documento="atestado médico"),
        _fato("M006", "salário de R$ 2.000,00", documento="CTPS", contradicoes=["M007"]),
        _fato("M007", "salário de R$ 2.400,00", estado=ALEGADO, contradicoes=["M006"]),
        _fato("M008", "o reclamante parecia cansado", estado=INFERIDO),
    ], "contradicoes": []}


def _tese(id_, nome, decisao=teses.SUPPORTED, **extra):
    base = {"id": id_, "tese": nome, "decisao": decisao, "fatos_que_suportam": [], "fatos_necessarios": [], "requisitos": [],
            "proposicoes": [], "base_legal_a_pesquisar": [], "jurisprudencia_a_pesquisar": [], "pedido": "", "reflexos": [],
            "exige_pericia": False}
    return {**base, **extra}


def _issues():
    return {"teses": [
        _tese("I01", "Horas extras habituais", fatos_que_suportam=["M002", "M003"],
              requisitos=[{"requisito": "jornada contratual", "fatos": ["M001", "M999"], "presente": True}],
              proposicoes=["É devido o pagamento das horas excedentes à oitava diária", "O empregador com mais de vinte empregados deve controlar a jornada"],
              pedido="horas extras com adicional de 50%", reflexos=["DSR", "FGTS"]),
        _tese("I02", "Dano moral por assédio moral", fatos_que_suportam=["M004", "M005"], pedido="indenização por dano moral"),
        _tese("I03", "Adicional de insalubridade", decisao=teses.POTENCIAL, fatos_que_suportam=["M008"]),
        _tese("I04", "Tese descartada", decisao=teses.REJEITADA_SEM_FATO),
    ]}


def _motor(llm=None):
    m = _matriz()
    rac = raciocinio.montar(_issues(), m, calculos=[{"tese_id": "I01", "calculation_id": "C1", "valor": 30000.0, "erro": ""}])
    prova.montar(rac, m)
    prova.lacunas(rac)
    contrateses.gerar(rac, m, llm=llm)
    return rac, m


# ------------------------------------------------------------------ níveis de severidade

def test_codigo_critico_bloqueia_mesmo_declarado_como_alerta_e_veredito_conta_criticos():
    a = auditores._achado("TESTE", "DISPOSITIVO_INEXISTENTE", auditores.ALERTA, "LEGAL_GROUNDS", "art. 9999 da CLT")  # noqa: SLF001
    assert a["nivel"] == auditores.CRITICAL and a["severidade"] == auditores.BLOQUEIA
    b = auditores._achado("TESTE", "QUALQUER_COISA", auditores.ALERTA)  # noqa: SLF001
    assert b["nivel"] == auditores.WARNING
    v = auditores.veredito({"auditor": "TESTE", "achados": [a, b]})
    assert v["critico"] and v["niveis"][auditores.CRITICAL] == 1 and auditores.criticos([a, b]) == [a]


# ------------------------------------------------------------------ grafo

def test_grafo_tem_requisitos_do_catalogo_com_fatos_da_matriz_e_ignora_fato_inexistente():
    rac, m = _motor()
    ids = [t["tese_id"] for t in rac["teses"]]
    assert ids == ["I01", "I02", "I03"], "tese rejeitada não entra no grafo"
    he = raciocinio.tese(rac, "I01")
    assert "horas_extras" in he["institutos"]
    reqs = {r["id"]: r for r in he["requisitos"]}
    assert reqs["horas_extras.jornada_contratual"]["estado"] == raciocinio.ATENDIDO
    assert [f["id"] for f in reqs["horas_extras.jornada_contratual"]["fatos"]] == ["M001"]
    assert reqs["horas_extras.jornada_efetiva"]["estado"] == raciocinio.SO_ALEGADO
    assert all(f["id"] != "M999" for r in he["requisitos"] for f in r["fatos"])
    assert he["pedido"]["valor"] == 30000.0 and he["pedido"]["calculation_id"] == "C1"
    assert [p["id"] for p in he["proposicoes"]] == ["I01.P1", "I01.P2"]


def test_requisito_do_modelo_liga_so_ao_requisito_mais_especifico():
    rac, _ = _motor()
    he = raciocinio.tese(rac, "I01")
    efetiva = next(r for r in he["requisitos"] if r["id"] == "horas_extras.jornada_efetiva")
    assert "M001" not in [f["id"] for f in efetiva["fatos"]], "«jornada contratual» não é prova da jornada efetiva"


def test_explicar_e_grafo_mostram_caminho_com_origem():
    rac, m = _motor()
    fatos = {f["id"]: f for f in m["fatos"]}
    linhas = raciocinio.explicar(rac, "I01", fatos)
    assert linhas[0].startswith("Tese «Horas extras habituais»")
    assert any("CTPS" in x for x in linhas) and any("Contratese" in x for x in linhas)
    g = raciocinio.como_grafo(raciocinio.tese(rac, "I01"), fatos)
    tipos = {n["tipo"] for n in g["nos"]}
    assert {"tese", "requisito", "fato", "prova", "proposicao", "contratese", "pedido", "reflexo"} <= tipos
    assert all(a.get("origem") is not None for a in g["arestas"])


# ------------------------------------------------------------------ matriz de prova e lacunas

def test_classes_de_prova_e_lacuna_com_prova_tipica_e_alternativa():
    rac, m = _motor()
    fatos = {f["id"]: f for f in m["fatos"]}
    assert prova.classe_do_fato(fatos["M001"]) == prova.PRIMARY_DOCUMENT
    assert prova.classe_do_fato(fatos["M005"]) == prova.MEDICAL_RECORD
    assert prova.classe_do_fato(fatos["M002"]) == prova.PARTY_STATEMENT
    assert prova.classe_do_fato(fatos["M008"]) == prova.INFERENCE_ONLY
    efetiva = next(x for x in rac["matriz_de_prova"] if x["requisito_id"] == "horas_extras.jornada_efetiva")
    assert efetiva["forca"] == prova.FRACA and efetiva["prova_futura_necessaria"]
    lac = next(x for x in rac["lacunas"] if x["requisito_id"] == "horas_extras.jornada_efetiva")
    assert "cartões de ponto" in lac["ausente"] and "testemunhal" in lac["alternativa"]
    texto = prova.pendencias(rac)
    assert any(t.startswith("Lacuna de prova — Tese: Horas extras habituais / Força:") and "Alternativa:" in t for t in texto)
    assert not any("insalubridade" in t.lower() for t in texto), "lacuna de tese só potencial não vira pendência"


# ------------------------------------------------------------------ proposições, certeza e conflito

def _p(*autoridades):
    return {"texto": "proposição", "autoridades": list(autoridades)}


def _a(id_, prioridade, posicao, *, avaliada=True, verificada=True, vigente=True):
    return {"id": id_, "titulo": id_, "prioridade": prioridade, "posicao": posicao, "avaliada": avaliada, "verificada": verificada,
            "vigente": vigente, "tipo": "sumula", "data": ""}


def test_niveis_de_certeza_e_conflito():
    assert proposicoes.certeza(_p())["certeza"] == proposicoes.RESEARCH_REQUIRED
    assert proposicoes.certeza(_p(_a("s1", 2, "sustenta")))["certeza"] == proposicoes.BINDING
    assert proposicoes.certeza(_p(_a("s1", 2, "sustenta", verificada=False)))["certeza"] == proposicoes.STRONG
    assert proposicoes.certeza(_p(_a("t1", 6, "sustenta")))["certeza"] == proposicoes.PERSUASIVE
    contestada = proposicoes.certeza(_p(_a("t1", 6, "sustenta"), _a("t2", 6, "contraria")))
    assert contestada["certeza"] == proposicoes.CONTESTED and contestada["conflito"]["unresolved_conflict"]
    controlada = proposicoes.certeza(_p(_a("s1", 2, "contraria"), _a("t1", 6, "sustenta")))
    assert controlada["certeza"] == proposicoes.UNSETTLED and controlada["conflito"]["controlling_authority"] == "s1"
    presumida = proposicoes.certeza(_p(_a("s1", 1, "relacionada", avaliada=False)))
    assert presumida["certeza"] == proposicoes.PERSUASIVE and presumida["classificacao"] == "presumida"
    superada = proposicoes.certeza(_p(_a("s1", 1, "sustenta", vigente=False)))
    assert superada["certeza"] == proposicoes.RESEARCH_REQUIRED


def _registro():
    return aut.Registro([
        aut.Autoridade(id="tst:sum:9010", tipo="sumula", chave="", titulo="Súmula 9010 do TST", tribunal="TST",
                       tese="horas excedentes à oitava diária são devidas como extras com adicional", verificada=True, data="2020-01-01"),
        aut.Autoridade(id="trt:9011", tipo="precedente", chave="", titulo="RO 9011 do TRT-9", tribunal="TRT9",
                       tese="horas excedentes à oitava diária devidas com adicional de horas extras", verificada=True, data="2012-01-01"),
    ])


def test_pesquisa_por_proposicao_classifica_com_trecho_literal_e_define_tom():
    proposicoes.limpar_cache()
    rac, _ = _motor()

    def llm(instrucao, entrada):
        itens = []
        for bloco in entrada.split("### ")[1:]:
            id_ = bloco.split("\n", 1)[0].strip()
            literal = "horas excedentes à oitava diária" in bloco
            itens.append({"id": id_, "posicao": "sustenta" if literal else "irrelevante",
                          "trecho": "horas excedentes à oitava diária" if literal else ""})
        return {"itens": itens}

    r = proposicoes.pesquisar(rac, _registro(), data_referencia=HOJE, llm=llm)
    assert r["consultas"] >= 2 and r["classificadas"]
    p1 = raciocinio.tese(rac, "I01")["proposicoes"][0]
    assert p1["autoridades"][0]["id"] == "tst:sum:9010", "superior vem antes do regional"
    assert p1["certeza"] == proposicoes.BINDING and p1["tom"] == proposicoes.TOM[proposicoes.BINDING]


def test_trecho_que_nao_existe_na_autoridade_nao_vale_como_sustentacao():
    proposicoes.limpar_cache()
    rac, _ = _motor()
    llm = lambda i, e: {"itens": [{"id": b.split("\n", 1)[0].strip(), "posicao": "sustenta", "trecho": "texto inventado pelo modelo"}  # noqa: E731
                                  for b in e.split("### ")[1:]]}
    proposicoes.pesquisar(rac, _registro(), data_referencia=HOJE, llm=llm)
    p1 = raciocinio.tese(rac, "I01")["proposicoes"][0]
    assert all(a["posicao"] != "sustenta" for a in p1["autoridades"])


def test_auditor_de_certeza_acusa_linguagem_absoluta_em_proposicao_incerta():
    rac, _ = _motor()
    p = raciocinio.tese(rac, "I01")["proposicoes"][0]
    p["certeza"] = proposicoes.CONTESTED
    secoes = [{"code": "LEGAL_GROUNDS", "content": "É pacífico que é devido o pagamento das horas excedentes à oitava diária."}]
    achados = proposicoes.auditar_certeza(secoes, rac)["achados"]
    assert [a["codigo"] for a in achados] == ["LINGUAGEM_ABSOLUTA_EM_PROPOSICAO_INCERTA"]
    assert achados[0]["nivel"] == auditores.WARNING


def test_auditor_de_precedentes_acusa_regional_com_superior_disponivel():
    proposicoes.limpar_cache()
    rac, _ = _motor()
    reg = _registro()
    proposicoes.pesquisar(rac, reg, data_referencia=HOJE)
    a = reg.por_id["trt:9011"]
    secoes = [{"code": "LEGAL_GROUNDS", "content": "Conforme o RO 9011 do TRT-9, são devidas as horas."}]

    class _Reg:
        por_id = reg.por_id

        def resolver(self, c, d):
            return {"authority_id": a.id}

    import app.juridico.proposicoes as mod
    original = mod.aut.extrair_citacoes
    mod.aut.extrair_citacoes = lambda texto: [aut.Citacao(tipo="precedente", chave="x", trecho="RO 9011 do TRT-9", inicio=0)]
    try:
        achados = proposicoes.auditar_precedentes(secoes, rac, _Reg(), HOJE)["achados"]
    finally:
        mod.aut.extrair_citacoes = original
    codigos = {x["codigo"] for x in achados}
    assert "PRECEDENTE_REGIONAL_COM_SUPERIOR_DISPONIVEL" in codigos


def test_ranking_prefere_a_mais_recente_entre_iguais_e_a_vigente():
    reg = aut.Registro([
        aut.Autoridade(id="a", tipo="precedente", chave="", tribunal="TRT9", tese="horas extras habituais devidas", data="2005-01-01"),
        aut.Autoridade(id="b", tipo="precedente", chave="", tribunal="TRT9", tese="horas extras habituais devidas", data="2025-01-01"),
    ])
    assert [a.id for a, _ in reg.buscar("horas extras habituais", data_referencia=HOJE)][0] == "b"


# ------------------------------------------------------------------ contrateses

def test_contrateses_do_catalogo_sem_modelo_e_capitulo_vulneravel():
    rac, _ = _motor()
    he = raciocinio.tese(rac, "I01")
    assert 1 <= len(he["contrateses"]) <= contrateses.MAX_POR_TESE
    assert all(c["origem"] == "catalogo" for c in he["contrateses"])
    ponto = next(c for c in he["contrateses"] if c["requisito_id"] == "horas_extras.jornada_efetiva")
    assert not ponto["tem_prova"] and ponto["vulneravel"] and "cartões de ponto" in ponto["orientacao"]
    assert any(v["tese_id"] == "I01" for v in rac["capitulos_vulneraveis"])
    assert all(t["contrateses"] == [] for t in rac["teses"] if t["decisao"] not in (teses.SUPPORTED, teses.POTENCIAL))


def test_contrateses_do_modelo_sao_validadas_contra_grafo_e_matriz():
    def llm(instrucao, entrada):
        return {"teses": [{"tese_id": "I01", "defesas": [
            {"defesa": "jornada contratual era de 40h", "requisito_id": "horas_extras.jornada_contratual", "fatos_que_a_enfrentam": ["M001", "M404"], "forca": "alta"},
            {"defesa": "requisito inventado", "requisito_id": "nao.existe", "fatos_que_a_enfrentam": [], "forca": "enorme"},
        ]}]}
    rac, _ = _motor(llm)
    he = raciocinio.tese(rac, "I01")
    assert [c["origem"] for c in he["contrateses"]] == ["modelo", "modelo"]
    c1, c2 = he["contrateses"]
    assert c1["fatos_que_a_enfrentam"] == ["M001"] and c1["tem_prova"]
    assert c2["requisito_id"] == "" and c2["forca"] == "media"


def test_modelo_que_falha_cai_para_o_catalogo():
    def llm(instrucao, entrada):
        raise RuntimeError("fora do ar")
    m = _matriz()
    rac = raciocinio.montar(_issues(), m)
    prova.montar(rac, m)
    r = contrateses.gerar(rac, m, llm=llm)
    assert r["origem"] == "catalogo" and "fora do ar" in r["erro"] and raciocinio.tese(rac, "I01")["contrateses"]


def test_auditor_de_contrateses_exige_trecho_literal_da_peca():
    rac, _ = _motor()
    capitulo = "Os cartões de ponto não refletem a jornada real, pois o reclamante registrava a saída e continuava trabalhando."
    secoes = [{"code": "LEGAL_GROUNDS", "content": "Das horas extras habituais\n\n" + capitulo}]

    def llm(instrucao, entrada):
        itens = []
        for b in entrada.split("### ")[1:]:
            id_ = b.split("\n", 1)[0].strip()
            ponto = "cartões de ponto registram" in b
            itens.append({"id": id_, "respondida": True, "trecho": capitulo[:60] if ponto else "frase que não está na peça"})
        return {"itens": itens}

    r = contrateses.auditar(secoes, rac, llm=llm)
    he = raciocinio.tese(rac, "I01")
    ponto = next(c for c in he["contrateses"] if c["requisito_id"] == "horas_extras.jornada_efetiva")
    outras = [c for c in he["contrateses"] if c is not ponto]
    assert r["avaliacao"] == "modelo" and ponto["respondida"] and all(c["respondida"] is False for c in outras)
    assert any(a["codigo"] == "CONTRATESE_SEM_PROVA_NA_MATRIZ" for a in r["achados"])
    assert all(a["severidade"] == auditores.ALERTA for a in r["achados"]), "contratese nunca retém a peça"


# ------------------------------------------------------------------ scores

def test_scores_deterministicos_com_motivos_e_risco_de_contradicao():
    rac, m = _motor()
    s1 = scores.calcular(rac, m)
    s2 = scores.calcular(rac, m)
    assert s1 == s2
    he = raciocinio.tese(rac, "I01")["scores"]
    for nome in scores.NOMES:
        assert 0 <= he[nome]["valor"] <= 1 and he[nome]["motivos"]
    assert he["legal_support"]["valor"] == 0, "sem pesquisa, nenhuma proposição tem certeza"
    assert rac["ordem_por_prioridade"][0] in {"I01", "I02", "I03"}
    m["fatos"][2]["contradicoes"] = ["M002"]
    rac2 = raciocinio.montar(_issues(), m)
    prova.montar(rac2, m)
    contrateses.gerar(rac2, m)
    scores.calcular(rac2, m)
    assert raciocinio.tese(rac2, "I01")["scores"]["contradiction_risk"]["valor"] > he["contradiction_risk"]["valor"]
    assert any("sem autoridade verificada" in a for a in scores.alertas(rac))


# ------------------------------------------------------------------ integração no orquestrador

def _prep_minimo(monkeypatch=None):
    plano_est = {"partes": {}, "fatos": [
        {"id": "F01", "data": "", "fato": "Jornada das 8h às 20h sem pagamento de horas extras", "fonte": "entrevista", "documentos": []},
        {"id": "F02", "data": "", "fato": "Contracheques sem horas extras", "fonte": "contracheques", "documentos": ["contracheques"]},
    ], "teses": [], "pedidos": [], "ausencias": [], "case_facts": {"PARTIES": {"autor": {}, "reu": {}}, "UNCERTAINTIES": []}}
    fontes = [{"tipo": "documento", "nome": "contracheques", "texto": "Contracheque sem rubrica de horas extras"}]

    def llm(instrucao, entrada):
        import re
        kid = re.search(r"(?m)^(K\d+) \| ", instrucao)
        return {"teses": [{"catalogo_id": kid[1] if kid else None, "tese": "Horas extras habituais", "decisao": "INCLUIR",
                           "motivo": "jornada", "fatos_que_suportam": ["M001", "M002"],
                           "fatos_necessarios": [{"fato": "jornada", "presente": True, "fato_id": "M001"}],
                           "proposicoes": ["horas excedentes à oitava diária são devidas"]}]}
    return orquestrador.preparar(plano_est=plano_est, contexto_caso="", fontes=fontes, llm=llm, textos_skill={"SKILL.md": ""},
                                 autoridades_base=_registro().autoridades, data_referencia=HOJE)


def test_orquestrador_monta_motor_e_o_leva_ao_prompt_auditoria_e_trace():
    proposicoes.limpar_cache()
    prep = _prep_minimo()
    rac = prep["raciocinio"]
    assert rac["teses"] and not rac["falhas"]
    etapas = [e["etapa"] for e in prep["rastro"].etapas]
    assert {"grafo_e_prova", "contrateses", "proposicoes", "scores"} <= set(etapas)
    assert "MOTOR JURÍDICO" in prep["texto_plano"]
    secoes = [{"code": "LEGAL_GROUNDS", "content": "Das horas extras habituais. São devidas as horas excedentes à oitava diária."}]
    aud = orquestrador.auditar(secoes, prep, pendencias=[])
    assert {"COUNTERARGUMENT", "LEGAL_CERTAINTY", "PRECEDENT_QUALITY"} <= set(aud["veredito"]["auditores"])
    tr = orquestrador.trace(prep, aud)
    assert tr["raciocinio"]["teses"][0]["grafo"]["nos"] and tr["raciocinio"]["matriz_de_prova"]
    assert isinstance(tr["pendencias_do_motor"], list)
    assert orquestrador.trace_de_falha("strict", ["x"])["raciocinio"] is None


def test_falha_do_motor_nao_derruba_a_analise(monkeypatch):
    def quebra(*a, **k):
        raise RuntimeError("bug no grafo")
    monkeypatch.setattr(raciocinio, "montar", quebra)
    prep = _prep_minimo()
    assert prep["raciocinio"]["teses"] == [] and "bug no grafo" in prep["raciocinio"]["falhas"][0]
    assert prep["plano_est"] is not None and prep["texto_plano"]
    aud = orquestrador.auditar([{"code": "LEGAL_GROUNDS", "content": "texto"}], prep, pendencias=[])
    assert "COUNTERARGUMENT" not in aud["veredito"]["auditores"]


# ------------------------------------------------------------------ legado assistido

def test_assistido_so_com_modo_off_e_desligavel(monkeypatch):
    from app import juridico
    monkeypatch.delenv("PETICAO_PIPELINE_JURIDICO_MODE", raising=False)
    monkeypatch.delenv("PETICAO_PIPELINE_JURIDICO", raising=False)
    monkeypatch.delenv("PETICAO_MOTOR_JURIDICO", raising=False)
    assert not juridico.assistido(), "strict é o padrão seguro"
    monkeypatch.setenv("PETICAO_PIPELINE_JURIDICO_MODE", "off")
    assert juridico.assistido()
    monkeypatch.setenv("PETICAO_MOTOR_JURIDICO", "0")
    assert not juridico.assistido()
    monkeypatch.setenv("PETICAO_MOTOR_JURIDICO", "1")
    monkeypatch.setenv("PETICAO_PIPELINE_JURIDICO_MODE", "shadow")
    assert not juridico.assistido()


def test_orientacao_do_motor_nao_espera_alem_do_teto_e_nunca_levanta(monkeypatch):
    from concurrent.futures import Future

    peticao_local = pytest.importorskip("app.peticao_local", reason="dependências completas do back ausentes (job leve do CI)")
    monkeypatch.setattr(peticao_local, "ESPERA_MOTOR_NO_APROFUNDAMENTO_S", 0.01)
    assert peticao_local._orientacoes_do_motor(None)[0] == {}  # noqa: SLF001
    pendente: Future = Future()
    orient, rel = peticao_local._orientacoes_do_motor(pendente)  # noqa: SLF001
    assert orient == {} and "não terminou" in rel["motivo"]
    falhou: Future = Future()
    falhou.set_exception(RuntimeError("x"))
    assert peticao_local._orientacoes_do_motor(falhou)[1]["aplicado"] is False  # noqa: SLF001
    rac, _ = _motor()
    pronto: Future = Future()
    pronto.set_result({"raciocinio": rac})
    orient, rel = peticao_local._orientacoes_do_motor(pronto)  # noqa: SLF001
    assert rel["aplicado"] and "I01" in orient
    texto = raciocinio.orientacao_para_topico(orient, "Das horas extras habituais", "")
    assert texto.startswith("ORIENTAÇÃO DO MOTOR JURÍDICO") and "cartões de ponto" in texto
    assert raciocinio.orientacao_para_topico(orient, "Da justiça gratuita", "") == ""


def test_pendencias_do_assistido_ignoram_inexistencia_contra_base_vazia():
    peticao_local = pytest.importorskip("app.peticao_local", reason="dependências completas do back ausentes (job leve do CI)")
    achados = [auditores._achado("LEGAL", "AUTORIDADE_INEXISTENTE", auditores.BLOQUEIA, "", "Súmula 9999"),  # noqa: SLF001
               auditores._achado("CALCULO", "VALOR_DA_CAUSA_NAO_FECHA", auditores.BLOQUEIA, "", "", "soma 10 ≠ 20")]  # noqa: SLF001
    trace = {"pendencias_do_motor": ["Lacuna de prova — Tese: x"], "falhas": ["autoridades: base verificada vazia"],
             "auditoria": {"achados": achados}}
    pend = peticao_local._pendencias_do_motor(trace)  # noqa: SLF001
    assert pend[0] == "Lacuna de prova — Tese: x"
    assert any("VALOR_DA_CAUSA_NAO_FECHA" in p for p in pend) and not any("AUTORIDADE_INEXISTENTE" in p for p in pend)
    trace["falhas"] = []
    assert any("AUTORIDADE_INEXISTENTE" in p for p in peticao_local._pendencias_do_motor(trace))  # noqa: SLF001
    assert peticao_local._pendencias_do_motor(None) == []  # noqa: SLF001


@pytest.mark.parametrize("decisao", [teses.SUPPORTED, teses.POTENCIAL])
def test_pendencias_do_motor_so_de_teses_sustentadas(decisao):
    issues = {"teses": [_tese("I01", "Horas extras habituais", decisao=decisao, fatos_que_suportam=["M002"])]}
    m = _matriz()
    rac = raciocinio.montar(issues, m)
    prova.montar(rac, m)
    prova.lacunas(rac)
    contrateses.gerar(rac, m)
    pend = orquestrador.pendencias_do_motor({"raciocinio": rac})
    assert bool(pend) == (decisao == teses.SUPPORTED)
