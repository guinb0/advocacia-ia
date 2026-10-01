"""Gates da camada jurídica sem banco e sem rede: cálculo × pedido, valor da causa sem dupla contagem,
idade divergente, fato futuro, contradição semântica e o e2e de um caso trabalhista FICTÍCIO (acidente,
pensionamento, verbas rescisórias e perícia) em shadow e em strict.

Normas FICTÍCIAS (9xxx), partes e datas inventadas; o modelo é uma função falsa determinística.
"""

from __future__ import annotations

import copy
import re
from datetime import date

from app import peticao_local
from app.juridico import auditor_secoes, auditor_semantico, auditor_temporal, auditores, autoridades as aut
from app.juridico import calculos, canonico, citacao, fatos, orquestrador, render

HOJE = date(2026, 10, 15)


def _fato(id_, chave, valor, fonte, estado=fatos.CONFIRMADO, **extra):
    return {"id": id_, "chave": chave, "valor": valor, "estado": estado, "fonte": fonte, **extra}


def _matriz(**trocas):
    base = {
        "autor.data_nascimento": _fato("M001", "autor.data_nascimento", "15/08/1990", "RG"),
        "acidente.data": _fato("M002", "acidente.data", "10/05/2025", "CAT"),
        "contrato.admissao": _fato("M003", "contrato.admissao", "03/03/2020", "CTPS"),
        "contrato.dispensa": _fato("M004", "contrato.dispensa", "05/03/2026", "TRCT"),
        "contrato.salario": _fato("M005", "contrato.salario", "R$ 3.000,00", "CTPS"),
        "incapacidade.percentual": _fato("M006", "incapacidade.percentual", "30%", "laudo do INSS"),
    }
    for chave, valor in trocas.items():
        base[chave.replace("__", ".")]["valor"] = valor
    return {"fatos": list(base.values()), "contradicoes": []}


def _codigos(rel):
    return [a["codigo"] for a in rel["achados"]]


# ------------------------------------------------------------------ cálculo × pedido

def test_pedido_divergente_do_calculo_e_calculo_inexistente_bloqueiam():
    calcs = [c.como_dict() for c in calculos.executar([
        {"rubrica": "aviso_previo", "parametros": {"salario": 3000, "admissao": "03/03/2020", "dispensa": "05/03/2026"}},
        {"rubrica": "multa_477", "parametros": {"salario": 3000}},
    ])]
    assert [(c["calculation_id"], c["valor"]) for c in calcs] == [("CALC_001", 4800.0), ("CALC_002", 3000.0)]
    pedidos = [{"id": "P01", "valor": 4500.0, "calculation_id": "CALC_001"}, {"id": "P02", "valor": 3000.0, "calculation_id": "CALC_009"}]
    secoes = [{"code": "CLAIMS", "content": "a) aviso prévio de R$ 4.500,00; b) multa de R$ 3.000,00; c) diferenças de R$ 1.234,00."}]
    codigos = _codigos(auditores.auditar_calculos(secoes, pedidos, calcs))
    assert {"PEDIDO_DIVERGENTE_DO_CALCULO", "PEDIDO_COM_CALCULO_INEXISTENTE", "VALOR_SEM_CALCULO"} <= set(codigos)
    certo = [{"id": "P01", "valor": 4800.0, "calculation_id": "CALC_001"}, {"id": "P02", "valor": 3000.0, "calculation_id": "CALC_002"}]
    ok = [{"code": "CLAIMS", "content": "a) aviso prévio de R$ 4.800,00; b) multa de R$ 3.000,00."},
          {"code": "VALUE", "content": "Dá-se à causa o valor de R$ 7.800,00."}]
    assert auditores.auditar_calculos(ok, certo, calcs)["achados"] == []


# ------------------------------------------------------------------ soma = valor da causa, sem dupla contagem

def test_valor_da_causa_soma_so_os_autonomos_cumulativos_sem_dupla_contagem():
    pedidos = [
        {"id": "P01", "valor": 4800.0, "calculation_id": "CALC_001"},
        {"id": "P02", "valor": 384.0, "tipo_de_item": "reflexo"},
        {"id": "P03", "valor": 1000.0, "natureza": "subsidiario"},
        {"id": "P04", "valor": 3000.0, "calculation_id": "CALC_002"},
        {"id": "P05", "valor": None},
    ]
    vc = calculos.valor_da_causa(pedidos)
    assert vc["valor"] == 7800.0 and vc["pedidos_somados"] == ["P01", "P04"] and vc["pedidos_fora_da_soma"] == ["P02", "P03"]
    assert render.secao_valor({"pedidos": pedidos}) == "Dá-se à causa o valor de R$ 7.800,00."
    calcs = [{"calculation_id": "CALC_001", "valor": 4800.0, "memoria": []}, {"calculation_id": "CALC_002", "valor": 3000.0, "memoria": []}]
    com_reflexo = [{"code": "VALUE", "content": "Dá-se à causa o valor de R$ 8.184,00."}]
    assert "VALOR_DA_CAUSA_DIFERENTE_DA_SOMA" in _codigos(auditores.auditar_calculos(com_reflexo, pedidos, calcs))
    duplicado = [*pedidos, {"id": "P06", "valor": 4800.0, "calculation_id": "CALC_001"}]
    assert "DUPLA_CONTAGEM" in _codigos(auditores.auditar_calculos([], duplicado, calcs))


# ------------------------------------------------------------------ idade divergente

def test_idade_divergente_entre_secoes_e_dado_canonico():
    canon = canonico.montar(_matriz(), petition_date=HOJE)
    assert canonico.valor(canon, "claimant.age_at_event") == 34 and canonico.valor(canon, "claimant.age_at_petition") == 36
    secoes = [{"code": "FACTS", "content": "Em 10/05/2025, quando contava com 34 anos, o reclamante sofreu o acidente."},
              {"code": "LEGAL_GROUNDS", "content": "O reclamante, que hoje tem 36 anos, ficou com sequela."},
              {"code": "CLAIMS", "content": "Pensionamento até os 75 anos, considerando que o autor tinha 38 anos na data do acidente."}]
    rel = auditor_secoes.auditar(secoes, canon=canon, pedidos=[], calculos=[], matriz=_matriz())
    idades = [a for a in rel["achados"] if a["codigo"] == "IDADE_DIVERGENTE"]
    assert len(idades) == 1 and idades[0]["secao"] == "CLAIMS" and "38 anos" in idades[0]["trecho"]
    imp = next(i for i in rel["impressoes"] if i["chave"] == "claimant.age")
    assert [o["ok"] for o in imp["ocorrencias"]] == [True, True, False]


# ------------------------------------------------------------------ fato futuro e data do fechamento

def test_fato_futuro_e_data_de_modelo_no_fechamento():
    matriz = _matriz(acidente__data="20/11/2026")
    canon = canonico.montar(matriz, petition_date=HOJE)
    secoes = [{"code": "FACTS", "content": "Em 20/11/2026 o reclamante sofreu queda do andaime."},
              {"code": "CLOSING", "content": "Belém, [data por extenso].\nAdvogado — OAB/PA 00.000"}]
    codigos = _codigos(auditor_temporal.auditar(secoes, petition_date=HOJE, matriz=matriz, canon=canon))
    assert "FATO_FUTURO" in codigos and "DATA_POSTERIOR_A_PETICAO" in codigos and "DATA_DE_MODELO" in codigos
    velho = [{"code": "CLOSING", "content": "Belém, 10 de março de 2024.\nAdvogado — OAB/PA 00.000"}]
    assert _codigos(auditor_temporal.auditar(velho, petition_date=HOJE)) == ["DATA_DA_PETICAO_DIVERGENTE"]
    corrigido, rel = render.fechamento_com_data(velho[0]["content"], HOJE)
    assert "15 de outubro de 2026" in corrigido and rel["datas_trocadas"]
    assert auditor_temporal.auditar([{"code": "CLOSING", "content": corrigido}], petition_date=HOJE)["achados"] == []


# ------------------------------------------------------------------ contradição semântica

def test_contradicao_semantica_familia_ressalva_e_camada_llm_com_trecho_literal():
    secoes = [{"code": "FACTS", "content": "O reclamante sofreu acidente de trajeto ao voltar para casa."},
              {"code": "LEGAL_GROUNDS", "content": "O acidente ocorreu durante a jornada, nas dependências da reclamada."}]
    assert "CONTRADICAO_TRAJETO_X_SERVICO" in _codigos(auditor_semantico.auditar(secoes))
    subsidiario = [secoes[1], {"code": "LEGAL_GROUNDS", "content": "Ainda que se entenda tratar-se de acidente de trajeto, a responsabilidade persiste."}]
    assert auditor_semantico.auditar(subsidiario)["achados"] == []

    corpo = [{"code": "FACTS", "content": "O reclamante foi atingido pela carga no galpão da reclamada."},
             {"code": "LEGAL_GROUNDS", "content": "Como narrado, o reclamante caiu da escada sozinho, sem participação de terceiros."}]
    literal = lambda i, e: {"contradicoes": [  # noqa: E731
        {"tipo": "dinâmica", "trecho_a": "foi atingido pela carga no galpão", "trecho_b": "caiu da escada sozinho", "explicacao": "duas dinâmicas"},
        {"tipo": "inventada", "trecho_a": "o autor estava de férias no dia", "trecho_b": "caiu da escada sozinho", "explicacao": "não está na peça"}]}
    rel = auditor_semantico.auditar(corpo, llm=literal)
    assert _codigos(rel) == ["CONTRADICAO_SEMANTICA"] and rel["relatorio"]["camada_llm"]["descartadas_sem_trecho_literal"] == 1

    def fora(i, e):
        raise TimeoutError("modelo fora do ar")
    assert _codigos(auditor_semantico.auditar(corpo, llm=fora)) == ["VERIFICACAO_SEMANTICA_NAO_EXECUTADA"]


def test_base_salarial_do_calculo_diferente_da_canonica_bloqueia():
    canon = canonico.montar(_matriz(), petition_date=HOJE)
    calcs = [{"calculation_id": "CALC_001", "rubrica": "aviso_previo", "parametros": {"salario": 3500}}]
    secoes = [{"code": "FACTS", "content": "O reclamante recebia salário de R$ 3.000,00."}]
    rel = auditor_semantico.auditar(secoes, canon=canon, calculos=calcs, matriz=_matriz())
    assert _codigos(rel) == ["BASE_SALARIAL_DIVERGENTE"]


# ------------------------------------------------------------------ e2e: caso trabalhista fictício (acidente, pensionamento, verbas, perícia)

def _caso_acidente():
    plano_est = {
        "partes": {"autor": {"nome": "Trabalhador Fictício"}, "reu": {"nome": "Construtora Exemplo Ltda"}},
        "fatos": [
            {"id": "F01", "data": "03/03/2020", "fato": "Admissão como pedreiro, salário de R$ 3.000,00", "fonte": "CTPS", "documentos": ["CTPS"]},
            {"id": "F02", "data": "10/05/2025", "fato": "Queda de andaime durante a jornada, no canteiro da reclamada", "fonte": "CAT", "documentos": ["CAT"]},
            {"id": "F03", "data": "", "fato": "Fratura de fêmur com sequela; laudo do INSS estima redução da capacidade em 30%", "fonte": "laudo do INSS", "documentos": ["laudo do INSS"]},
            {"id": "F04", "data": "05/03/2026", "fato": "Dispensa sem justa causa sem pagamento das verbas rescisórias", "fonte": "TRCT", "documentos": ["TRCT"]},
            {"id": "F05", "data": "15/08/1990", "fato": "Nascimento do reclamante", "fonte": "RG", "documentos": ["RG"]},
        ],
        "teses": [], "pedidos": [], "ausencias": [],
        "case_facts": {"PARTIES": {"autor": {}, "reu": {}}, "UNCERTAINTIES": []},
    }
    fontes = [
        {"tipo": "documento", "nome": "CTPS", "texto": "--- página 2 --- Admissão 03/03/2020. Cargo pedreiro. Salário R$ 3.000,00. Saída 05/03/2026."},
        {"tipo": "documento", "nome": "CAT", "texto": "Data do acidente 10/05/2025. Queda de andaime no canteiro da empregadora durante a jornada."},
        {"tipo": "documento", "nome": "laudo do INSS", "texto": "Fratura de fêmur consolidada com sequela. Redução da capacidade laborativa estimada em 30%."},
        {"tipo": "documento", "nome": "TRCT", "texto": "Afastamento 05/03/2026. Dispensa sem justa causa. Verbas rescisórias não pagas."},
        {"tipo": "documento", "nome": "RG", "texto": "Data de nascimento 15/08/1990."},
    ]
    return plano_est, fontes


def _registro_do_caso():
    return [
        aut.Autoridade(id="ndv:9002", tipo="artigo", chave="art:clt:9002", norma="clt", artigo="9002", verificada=True, versao="1",
                       vigencia_inicio="2017-11-11",
                       texto="Art. 9002. O empregador responde pelos danos decorrentes de acidente do trabalho ocorrido durante a jornada."),
        aut.Autoridade(id="ndv:9950", tipo="artigo", chave="art:cc:9950", norma="cc", artigo="9950", verificada=True, versao="1",
                       vigencia_inicio="2003-01-11",
                       texto="Art. 9950. Se da ofensa resultar redução da capacidade de trabalho, a indenização incluirá pensão "
                             "correspondente à importância do trabalho para que se inabilitou."),
        aut.Autoridade(id="ndv:9477", tipo="artigo", chave="art:clt:9477", norma="clt", artigo="9477", verificada=True, versao="1",
                       vigencia_inicio="2017-11-11",
                       texto="Art. 9477. O pagamento das verbas rescisórias será efetuado até dez dias contados do término do contrato, "
                             "sob pena de multa equivalente a um salário."),
    ]


def _sustenta(*ids):
    return {"fatos_que_suportam": list(ids), "fatos_necessarios": [{"fato": "x", "presente": True, "fato_id": ids[0]}]}


TESES_DO_CASO = [
    {"tese": "Indenização por danos morais decorrentes do acidente de trabalho", "decisao": "SUPPORTED", "motivo": "queda de andaime com sequela",
     **_sustenta("M002", "M003"), "pedido": "indenização por danos morais decorrentes do acidente de trabalho",
     "calculo": {"rubrica": "valor_informado", "parametros": {"valor": 50000, "criterio": "arbitramento pela gravidade da sequela"}}},
    {"tese": "Pensionamento por redução da capacidade laborativa", "decisao": "SUPPORTED", "motivo": "sequela com redução da capacidade",
     **_sustenta("M003"), "prova": ["pericial: perícia médica para apurar a redução da capacidade"],
     "pedido": "pagamento de pensão mensal (pensionamento) pela redução da capacidade laborativa",
     "calculo": {"rubrica": "pensionamento", "parametros": {"idade_limite": 75}}},
    {"tese": "Aviso prévio indenizado", "decisao": "SUPPORTED", "motivo": "dispensa sem justa causa sem pagamento", **_sustenta("M004"),
     "pedido": "pagamento do aviso prévio indenizado proporcional", "calculo": {"rubrica": "aviso_previo", "parametros": {}}},
    {"tese": "Multa por atraso no pagamento das verbas rescisórias", "decisao": "SUPPORTED", "motivo": "verbas não pagas no prazo", **_sustenta("M004"),
     "pedido": "pagamento da multa rescisória por atraso no pagamento das verbas", "calculo": {"rubrica": "multa_477", "parametros": {}}},
]
FATOS_EXTRAIDOS = [
    {"chave": "autor.data_nascimento", "valor": "15/08/1990", "fonte": "RG"},
    {"chave": "acidente.data", "valor": "10/05/2025", "fonte": "CAT"},
    {"chave": "contrato.admissao", "valor": "03/03/2020", "fonte": "CTPS"},
    {"chave": "contrato.dispensa", "valor": "05/03/2026", "fonte": "TRCT"},
    {"chave": "contrato.salario", "valor": "R$ 3.000,00", "fonte": "CTPS"},
    {"chave": "incapacidade.percentual", "valor": "30%", "fonte": "laudo do INSS"},
]
_BLOCO_CITACAO = re.compile(r"### (C\d+)\nAFIRMAÇÃO: (.*?)\nTEXTO OFICIAL \([^)]*\): (.*?)(?=\n\n### |\Z)", re.S)


def _modelo_do_caso(instrucao: str, entrada: str) -> dict:
    if "TEXTO OFICIAL" in instrucao:
        itens = []
        for cid, afirmacao, oficial in _BLOCO_CITACAO.findall(entrada):
            if "parcela única" in afirmacao:
                itens.append({"id": cid, "classificacao": "CONTRADICTS", "justificativa": "o texto não fala em parcela única sem redutor"})
            else:
                itens.append({"id": cid, "classificacao": "EXACT_SUPPORT", "trecho_oficial": oficial.strip()[:200], "justificativa": "literal"})
        return {"itens": itens}
    if "CONTRADIÇÕES INTERNAS" in instrucao:
        return {"contradicoes": []}
    return {"teses": copy.deepcopy(TESES_DO_CASO), "fatos_extraidos": copy.deepcopy(FATOS_EXTRAIDOS)}


FECHAMENTO = "Nestes termos, pede deferimento.\nBelém, [data por extenso].\nAdvogado Fictício — OAB/PA 00.000"
REDACAO_BOA = [
    {"code": "HEADING", "content": "EXCELENTÍSSIMO JUÍZO DA VARA DO TRABALHO DE BELÉM/PA"},
    {"code": "FACTS", "content": (
        "O reclamante, nascido em 15/08/1990, foi admitido em 03/03/2020 como pedreiro, com salário de R$ 3.000,00. "
        "Em 10/05/2025, quando contava com 34 anos, sofreu queda de andaime durante a jornada, nas dependências da reclamada. "
        "O laudo do INSS estimou redução da capacidade laborativa de 30%, e a extensão da incapacidade será apurada em perícia médica. "
        "Foi dispensado sem justa causa em 05/03/2026, sem receber as verbas rescisórias.")},
    {"code": "LEGAL_GROUNDS", "content": (
        "O empregador responde pelos danos decorrentes de acidente do trabalho ocorrido durante a jornada, nos termos do art. 9002 da CLT. "
        "Havendo redução da capacidade de trabalho, a indenização inclui pensão correspondente à importância do trabalho para que se inabilitou, "
        "conforme o art. 9950 do Código Civil.\n"
        "O pagamento das verbas rescisórias fora do prazo de dez dias gera multa equivalente a um salário, na forma do art. 9477 da CLT.")},
    {"code": "CLAIMS", "content": "Diante do exposto, requer:\n\na) danos morais de R$ 80.000,00;\nb) pensão de R$ 900,00 por mês."},
    {"code": "VALUE", "content": "Dá-se à causa o valor de R$ 1,00."},
    {"code": "CLOSING", "content": FECHAMENTO},
]


def _redacao_ruim():
    ruim = copy.deepcopy(REDACAO_BOA)
    ruim[1]["content"] = ruim[1]["content"].replace("contava com 34 anos", "contava com 38 anos").replace(
        "Foi dispensado", "O reclamante sofreu acidente de trajeto ao voltar da obra. Em 20/11/2026 foi submetido a nova cirurgia. Foi dispensado")
    ruim[2]["content"] = ruim[2]["content"].replace(
        "conforme o art. 9950 do Código Civil.", "sendo devida em parcela única sem redutor, conforme o art. 9950 do Código Civil.")
    return ruim


def _preparar():
    citacao.limpar_cache()
    plano_est, fontes = _caso_acidente()
    prep = orquestrador.preparar(plano_est=plano_est, contexto_caso="", fontes=fontes, llm=_modelo_do_caso, textos_skill={"SKILL.md": ""},
                                 autoridades_base=_registro_do_caso(), data_referencia=HOJE)
    texto_das_fontes = "\n".join(f["texto"] for f in fontes)
    return prep, texto_das_fontes


def _auditar(secoes, prep, texto_das_fontes):
    return orquestrador.auditar(secoes, prep, pendencias=prep["pendencias"], texto_das_fontes=texto_das_fontes, llm=_modelo_do_caso)


def test_e2e_caso_ficticio_prepara_canonico_calculos_e_pedidos():
    prep, _ = _preparar()
    canon = prep["canonico"]
    assert canonico.valor(canon, "claimant.age_at_event") == 34
    assert canonico.valor(canon, "employment.tenure_months") == 72
    por_rubrica = {c["rubrica"]: c for c in prep["calculos"]}
    assert not any(c["erro"] for c in prep["calculos"]), [c["erro"] for c in prep["calculos"]]
    assert por_rubrica["pensionamento"]["valor"] == 479700.0, por_rubrica["pensionamento"]["memoria"]
    assert por_rubrica["aviso_previo"]["valor"] == 4800.0 and por_rubrica["multa_477"]["valor"] == 3000.0
    pedidos = prep["plano_est"]["pedidos"]
    assert len(pedidos) == 4 and all(p["calculation_id"] and p["status"] == "SUPPORTED" for p in pedidos)
    assert any(p["expert_evidence_required"] for p in pedidos), "pensionamento exige perícia"
    assert prep["plano_est"]["valor_da_causa_calculado"]["valor"] == 537500.0


def test_e2e_strict_entrega_somente_quando_todos_os_gates_passam():
    prep, fontes = _preparar()
    secoes, rel = render.renderizar(copy.deepcopy(REDACAO_BOA), prep)
    texto = {s["code"]: s["content"] for s in secoes}
    assert "R$ 80.000,00" not in texto["CLAIMS"] and "R$ 479.700,00" in texto["CLAIMS"] and "CALC_00" in texto["CLAIMS"]
    assert "prova pericial" in texto["CLAIMS"] and rel["pedidos_renderizados"] == 5
    assert texto["VALUE"] == "Dá-se à causa o valor de R$ 537.500,00."
    assert "15 de outubro de 2026" in texto["CLOSING"] and "[data" not in texto["CLOSING"]
    auditoria = _auditar(secoes, prep, fontes)
    bloqueios = [f"{a['auditor']}:{a['codigo']}:{a['trecho'] or a['detalhe']}" for a in auditoria["achados"] if a["severidade"] == auditores.BLOQUEIA]
    assert bloqueios == [] and auditoria["veredito"]["pronta"] is True, bloqueios
    assert {c["authority_id"] for c in auditoria["citacoes_verificadas"] if c["aprovada"]} == {"ndv:9002", "ndv:9950", "ndv:9477"}
    dados = {"readiness": {"ready": True, "blocking_issues": [], "warnings": []}}
    peticao_local._aplicar_veredito_juridico(dados, auditoria, [])  # noqa: SLF001
    assert dados["readiness"]["ready"] is True

    ruins, _ = render.renderizar(_redacao_ruim(), prep)
    auditoria_ruim = _auditar(ruins, prep, fontes)
    codigos = set(_codigos(auditoria_ruim))
    assert {"IDADE_DIVERGENTE", "DATA_POSTERIOR_A_PETICAO", "CONTRADICAO_TRAJETO_X_SERVICO", "CITACAO_CONTRADIZ_A_AFIRMACAO"} <= codigos, codigos
    assert auditoria_ruim["veredito"]["pronta"] is False
    dados = {"readiness": {"ready": True, "blocking_issues": [], "warnings": []}}
    peticao_local._aplicar_veredito_juridico(dados, auditoria_ruim, [])  # noqa: SLF001
    assert dados["readiness"]["ready"] is False and dados["readiness"]["blocking_issues"]


def test_e2e_shadow_compara_sem_alterar_a_peca_entregue():
    prep, fontes = _preparar()
    legado = _redacao_ruim()
    copia = copy.deepcopy(legado)
    auditoria = _auditar(legado, prep, fontes)
    comp = orquestrador.comparar_com_legado(legado, prep, auditoria, plano_legado={"pedidos": []}, pendencias_legado=[])
    assert legado == copia, "shadow não altera a peça entregue"
    assert comp["veredito_se_fosse_strict"]["pronta"] is False
    bloqueios = " | ".join(comp["bloqueios_que_o_strict_apontaria"])
    for codigo in ("IDADE_DIVERGENTE", "DATA_POSTERIOR_A_PETICAO", "DATA_DE_MODELO", "CONTRADICAO_TRAJETO_X_SERVICO", "CITACAO_CONTRADIZ_A_AFIRMACAO"):
        assert codigo in bloqueios, codigo
    assert comp["valor_da_causa"]["calculado_pela_camada"] == 537500.0 and comp["valor_da_causa"]["legado_declarado"] == [1.0]
    assert comp["pedidos"]["camada"] == 4 and len(comp["pedidos"]["so_na_camada"]) == 4
    rastro = orquestrador.trace(prep, auditoria, modo="shadow", comparacao=comp)
    assert rastro["modo"] == "shadow" and rastro["comparacao_com_legado"] is comp and rastro["canonico"]
