"""Críticas da petição revisada pelo escritório: memória de cálculo discriminada, pedido líquido, pressuposto
fático das verbas rescisórias (vínculo ativo), redação antiga de artigo e critério de gratuidade superado (ADC 80).

Tudo com dados fictícios e sem rede/banco.
"""

from __future__ import annotations

import copy
from datetime import UTC, date, datetime

from app import auditoria_estrutural
from app.acervo import jurisprudencia
from app.acervo.armazenamento import Memoria
from app.juridico import auditor_secoes, auditor_semantico, auditores, autoridades as aut, canonico, citacao, fatos, orquestrador, render, tabelas, teses

HOJE = date(2026, 10, 15)


def _fato(id_, chave, valor, fonte, estado=fatos.CONFIRMADO):
    return {"id": id_, "chave": chave, "valor": valor, "estado": estado, "fonte": fonte}


def _matriz(*, ativo: bool = False):
    lista = [
        _fato("M001", "autor.data_nascimento", "15/08/1990", "RG"),
        _fato("M002", "contrato.admissao", "03/03/2020", "CTPS"),
        _fato("M003", "contrato.salario", "R$ 3.000,00", "CTPS"),
    ]
    if not ativo:
        lista.append(_fato("M004", "contrato.dispensa", "05/03/2026", "TRCT"))
    return {"fatos": lista, "contradicoes": []}


def _codigos(rel):
    return [a["codigo"] for a in rel["achados"]]


# ------------------------------------------------------------------ pressuposto fático: verba rescisória × vínculo ativo

def test_verba_rescisoria_exige_termino_do_contrato_ou_rescisao_indireta():
    ativo = canonico.montar(_matriz(ativo=True), petition_date=HOJE)
    encerrado = canonico.montar(_matriz(), petition_date=HOJE)
    multa = {"tese": "Multa por atraso no pagamento das verbas rescisórias", "calculo": {"rubrica": "multa_477"}}
    assert "pressuposto fático ausente" in canonico.pressuposto_rescisorio(multa, ativo, rescisao_indireta=False)
    assert canonico.pressuposto_rescisorio(multa, ativo, rescisao_indireta=True) == ""
    assert canonico.pressuposto_rescisorio(multa, encerrado, rescisao_indireta=False) == ""
    assert canonico.pressuposto_rescisorio(multa, None, rescisao_indireta=False) == "", "sem dados canônicos não decide"
    so_texto = {"tese": "Multa do art. 477 da CLT", "calculo": {}}
    assert canonico.pressuposto_rescisorio(so_texto, ativo, rescisao_indireta=False)
    reflexo = {"tese": "Horas extras com reflexos em aviso prévio, férias + 1/3 e 13º salário", "calculo": {"rubrica": "horas_extras"}}
    assert canonico.pressuposto_rescisorio(reflexo, ativo, rescisao_indireta=False) == "", "reflexo não é pedido rescisório"
    assert canonico.pede_rescisao_indireta([{"tese": "Rescisão indireta do contrato (art. 483 da CLT)"}])


def _caso_vinculo_ativo():
    plano_est = {
        "partes": {"autor": {"nome": "Trabalhadora Fictícia"}, "reu": {"nome": "Comércio Exemplo Ltda"}},
        "fatos": [
            {"id": "F01", "data": "03/03/2020", "fato": "Admissão como vendedora, salário de R$ 3.000,00", "fonte": "CTPS", "documentos": ["CTPS"]},
            {"id": "F02", "data": "", "fato": "A reclamante continua trabalhando para a reclamada", "fonte": "entrevista", "documentos": []},
            {"id": "F03", "data": "", "fato": "Assédio moral reiterado pela gerente", "fonte": "testemunhas", "documentos": []},
            {"id": "F04", "data": "15/08/1990", "fato": "Nascimento da reclamante", "fonte": "RG", "documentos": ["RG"]},
            {"id": "F05", "data": "", "fato": "Contracheques sem pagamento de horas extras", "fonte": "contracheques", "documentos": ["contracheques"]},
        ],
        "teses": [{"id": "T01", "titulo": "Multa do art. 477 da CLT", "pedidos_ids": ["P01"]}],
        "pedidos": [{"id": "P01", "tipo": "Multa do art. 477 da CLT", "objeto": "pagamento da multa do art. 477 da CLT por atraso nas verbas rescisórias",
                     "tese_origem": "T01", "valor": 3000.0, "natureza": "cumulativo", "tipo_de_item": "autonomo"}],
        "ausencias": [],
        "case_facts": {"PARTIES": {"autor": {}, "reu": {}}, "UNCERTAINTIES": []},
    }
    fontes = [{"tipo": "documento", "nome": "CTPS", "texto": "Admissão 03/03/2020. Vendedora. Salário R$ 3.000,00. Sem data de saída."},
              {"tipo": "documento", "nome": "RG", "texto": "Data de nascimento 15/08/1990."}]
    return plano_est, fontes


def _sustenta(*ids):
    return {"fatos_que_suportam": list(ids), "fatos_necessarios": [{"fato": "x", "presente": True, "fato_id": ids[0]}]}


TESES_ATIVO = [
    {"tese": "Indenização por danos morais por assédio moral", "decisao": "SUPPORTED", "motivo": "assédio reiterado", **_sustenta("M003"),
     "pedido": "indenização por danos morais decorrentes do assédio moral",
     "calculo": {"rubrica": "valor_informado", "parametros": {"valor": 20000, "criterio": "gravidade e reiteração"}}},
    {"tese": "Multa por atraso no pagamento das verbas rescisórias", "decisao": "SUPPORTED", "motivo": "atraso", **_sustenta("M001"),
     "pedido": "pagamento da multa do art. 477 da CLT", "calculo": {"rubrica": "multa_477", "parametros": {}}},
    {"tese": "Aviso prévio indenizado", "decisao": "SUPPORTED", "motivo": "dispensa", **_sustenta("M001"),
     "pedido": "pagamento do aviso prévio indenizado", "calculo": {"rubrica": "aviso_previo", "parametros": {"dispensa": "01/09/2026"}}},
]
FATOS_ATIVO = [
    {"chave": "autor.data_nascimento", "valor": "15/08/1990", "fonte": "RG"},
    {"chave": "contrato.admissao", "valor": "03/03/2020", "fonte": "CTPS"},
    {"chave": "contrato.salario", "valor": "R$ 3.000,00", "fonte": "CTPS"},
]


def _modelo_ativo(instrucao: str, entrada: str) -> dict:
    if "TEXTO OFICIAL" in instrucao:
        return {"itens": []}
    if "CONTRADIÇÕES INTERNAS" in instrucao:
        return {"contradicoes": []}
    return {"teses": copy.deepcopy(TESES_ATIVO), "fatos_extraidos": copy.deepcopy(FATOS_ATIVO)}


def _preparar_ativo():
    citacao.limpar_cache()
    plano_est, fontes = _caso_vinculo_ativo()
    return orquestrador.preparar(plano_est=plano_est, contexto_caso="", fontes=fontes, llm=_modelo_ativo,
                                 textos_skill={"SKILL.md": ""}, data_referencia=HOJE)


def test_vinculo_ativo_rebaixa_multa_477_e_aviso_e_retira_pedido_do_planejador():
    prep = _preparar_ativo()
    por_tese = {t["tese"]: t for t in prep["issues"]["teses"]}
    for nome in ("Multa por atraso no pagamento das verbas rescisórias", "Aviso prévio indenizado"):
        assert por_tese[nome]["decisao"] == teses.POTENCIAL and "pressuposto fático ausente" in por_tese[nome]["rebaixada_por"]
    assert {c["rubrica"] for c in prep["calculos"]} == {"valor_informado"}, "sem cálculo de verba rescisória"
    pedidos = prep["plano_est"]["pedidos"]
    assert all("477" not in f"{p.get('tipo')} {p.get('objeto')}" and "aviso" not in str(p.get("objeto")).lower() for p in pedidos), pedidos
    assert any(p.startswith("Pedido retirado: Multa do art. 477") for p in prep["pendencias"]), prep["pendencias"]
    assert any(p.startswith("A confirmar: Multa por atraso") for p in prep["pendencias"])
    assert prep["plano_est"]["valor_da_causa_calculado"]["valor"] == 20000.0

    secoes, rel = render.renderizar([{"code": "CLAIMS", "content": "Diante do exposto, requer:"}, {"code": "CLOSING", "content": "Termos em que, pede deferimento."}], prep)
    claims = next(s["content"] for s in secoes if s["code"] == "CLAIMS")
    assert "477" not in claims and "aviso prévio" not in claims.lower()


def test_auditor_bloqueia_pedido_rescisorio_com_vinculo_ativo_e_aceita_reflexo_e_rescisao_indireta():
    ativo = canonico.montar(_matriz(ativo=True), petition_date=HOJE)
    legado = [{"code": "FACTS", "content": "A reclamante continua trabalhando para a reclamada."},
              {"code": "CLAIMS", "content": "a) multa do art. 477 da CLT pelo atraso no pagamento das verbas rescisórias, no valor de R$ 3.000,00;\n"
                                            "b) horas extras com reflexos em aviso prévio e FGTS, no valor de R$ 1.000,00."}]
    rel = auditor_secoes.auditar(legado, canon=ativo, pedidos=[], calculos=[], matriz=_matriz(ativo=True))
    sev = {a["codigo"]: a["severidade"] for a in rel["achados"] if "PRESSUPOSTO" in a["codigo"]}
    assert sev == {"PEDIDO_SEM_PRESSUPOSTO_FATICO": auditores.BLOQUEIA, "REFLEXO_SEM_PRESSUPOSTO_FATICO": auditores.ALERTA}
    assert "CONTRADICAO_VINCULO_ATIVO_X_VERBA_RESCISORIA" in _codigos(auditor_semantico.auditar(legado))
    indireta = [*legado, {"code": "LEGAL_GROUNDS", "content": "Requer-se a rescisão indireta do contrato, nos termos do art. 483 da CLT."}]
    assert not [a for a in auditor_secoes.auditar(indireta, canon=ativo, pedidos=[], calculos=[])["achados"] if "PRESSUPOSTO" in a["codigo"]]
    encerrado = canonico.montar(_matriz(), petition_date=HOJE)
    assert not [a for a in auditor_secoes.auditar(legado, canon=encerrado, pedidos=[], calculos=[])["achados"] if "PRESSUPOSTO" in a["codigo"]]


# ------------------------------------------------------------------ memória de cálculo e pedido líquido

def test_memoria_de_calculo_sempre_anexada_aos_pedidos_com_base_e_fonte():
    prep = _preparar_ativo()
    secoes, rel = render.renderizar([{"code": "CLAIMS", "content": "Diante do exposto, requer:"}], prep)
    claims = secoes[0]["content"]
    assert rel.get("memoria_de_calculo_anexada") and render.INTRODUCAO_MEMORIA in claims
    assert "| Cálculo | Rubrica | Base e fonte | Memória | Resultado |" in claims
    assert "R$ 20.000,00" in claims and "CALC_001" in claims
    tabela = tabelas.construir("memoria_de_calculo", matriz=prep["matriz"], canon=prep["canonico"], calculos=prep["calculos"])
    assert tabela in claims, "a tabela é exatamente a do código (o CROSS_SECTION confere)"
    rel_cruzado = auditor_secoes.auditar(secoes, canon=prep["canonico"], pedidos=prep["plano_est"]["pedidos"], calculos=prep["calculos"], matriz=prep["matriz"])
    assert not [a for a in rel_cruzado["achados"] if a["codigo"] in ("TABELA_FORA_DA_FONTE_UNICA", "TABELA_DIVERGENTE")]
    assert not [a for a in auditores.auditar_calculos(secoes, prep["plano_est"]["pedidos"], prep["calculos"])["achados"]
                if a["severidade"] == auditores.BLOQUEIA]


def test_base_e_fonte_aponta_o_documento_de_cada_parametro_e_ressalva_a_pericia():
    matriz = _matriz()
    matriz["fatos"].append(_fato("M005", "incapacidade.percentual", "30%", "laudo do INSS"))
    canon = canonico.montar(matriz, petition_date=HOJE)
    params, usados = canonico.completar_parametros("aviso_previo", {}, canon)
    fontes = canonico.fontes_dos_parametros(params, usados, canon)
    assert fontes["salario"]["fonte"] == "CTPS" and fontes["dispensa"]["exibir"] == "05/03/2026" and fontes["dispensa"]["fonte"] == "TRCT"
    calc = {"calculation_id": "CALC_001", "rubrica": "aviso_previo", "valor": 4800.0, "memoria": ["6 ano(s) completo(s) → 48 dias"],
            "parametros": {**params, "anos": 6}, "fontes": fontes}
    celula = tabelas.base_e_fonte(calc)
    assert "salário atual: R$ 3.000,00 (CTPS)" in celula and "data de término do contrato: 05/03/2026 (TRCT)" in celula
    assert "demais parâmetros: análise do caso" in celula
    canon["campos"]["disability_percentage"]["certeza"] = canonico.REQUIRES_EXPERT_CONFIRMATION
    p_pens, u_pens = canonico.completar_parametros("pensionamento", {}, canon)
    assert "a ser confirmado por perícia" in canonico.fontes_dos_parametros(p_pens, u_pens, canon)["percentual_incapacidade"]["fonte"]


def test_pedido_deixado_para_liquidacao_bloqueia_mas_juros_e_honorarios_nao():
    secoes = [{"code": "CLAIMS", "content": "a) pagamento das horas extras, em valor a ser apurado em liquidação de sentença;\n"
                                            "b) juros e correção monetária a serem apurados em liquidação;\n"
                                            "c) honorários de 15% sobre o valor a liquidar."}]
    achados = [a for a in auditores.auditar_calculos(secoes, [], [])["achados"] if a["codigo"] == "PEDIDO_ILIQUIDO"]
    assert len(achados) == 1 and "horas extras" in achados[0]["trecho"] and achados[0]["severidade"] == auditores.BLOQUEIA


def test_percentual_com_casas_decimais_na_memoria_nao_vira_divergencia():
    matriz = _matriz()
    matriz["fatos"].append(_fato("M005", "incapacidade.percentual", "30%", "laudo do INSS"))
    canon = canonico.montar(matriz, petition_date=HOJE)
    secoes = [{"code": "CLAIMS", "content": "| x | percentual de incapacidade: 30% (laudo do INSS) | R$ 3.000,00 × 30.00% = R$ 900,00 por mês |"}]
    rel = auditor_secoes.auditar(secoes, canon=canon, pedidos=[], calculos=[], matriz=matriz)
    assert "PERCENTUAL_DIVERGENTE" not in _codigos(rel)


def test_tabela_no_word_ocupa_a_largura_util_e_e_compacta():
    import re as _re

    from app import peticao_local
    cab = ["Cálculo", "Rubrica", "Base e fonte", "Memória", "Resultado"]
    linhas = [["CALC_001", "aviso previo", "salário atual: R$ 3.000,00 (CTPS); data de término do contrato: 05/03/2026 (TRCT)",
               "6 ano(s) completo(s) → 30 + 3 × 6 = 48 dias; R$ 3.000,00 ÷ 30 × 48 = R$ 4.800,00", "R$ 4.800,00"]]
    xml = peticao_local._tabela_xml(cab, linhas, largura_total=9070)
    larguras = [int(w) for w in _re.findall(r'<w:gridCol w:w="(\d+)"/>', xml)]
    assert sum(larguras) == 9070 and '<w:tblW w:w="9070"' in xml
    assert larguras[3] > 2 * larguras[0] and larguras[2] > 2 * larguras[4], larguras
    assert min(larguras) >= peticao_local.LARGURA_MINIMA_COLUNA
    assert '<w:spacing w:before="0" w:after="0" w:line="240"' in xml and '<w:sz w:val="18"/>' in xml
    assert "<w:tblHeader/>" in xml and '<w:jc w:val="right"/></w:pPr><w:r><w:rPr><w:sz w:val="18"/>' in xml
    duas = peticao_local._tabela_xml(["Dado", "Valor"], [["Admissão", "03/03/2020"]])
    assert '<w:tblW w:w="9070"' in duas and '<w:sz w:val="20"/>' in duas
    assert peticao_local._largura_da_tabela({"margem_esquerda_cm": 3, "margem_direita_cm": 2}) == 9071
    assert peticao_local._largura_da_tabela({}) == peticao_local.LARGURA_TABELA_PADRAO


# ------------------------------------------------------------------ redação antiga de artigo

def _versoes_do_artigo():
    antiga = aut.Autoridade(id="ndv:9790:v1", tipo="artigo", chave="art:clt:9790", norma="clt", artigo="9790", versao="1", verificada=True,
                            vigencia_inicio="1943-05-01", vigencia_fim="2017-11-10",
                            texto="Art. 9790. É facultado conceder o benefício a quem perceber salário igual ou inferior ao dobro do mínimo legal.")
    vigente = aut.Autoridade(id="ndv:9790:v2", tipo="artigo", chave="art:clt:9790", norma="clt", artigo="9790", versao="2", verificada=True,
                             vigencia_inicio="2017-11-11",
                             texto="Art. 9790. O benefício será concedido à parte que comprovar insuficiência de recursos para o pagamento das custas.")
    return aut.Registro([antiga, vigente])


def _gate(texto):
    citacao.limpar_cache()
    llm = lambda i, e: {"itens": [{"id": "C1", "classificacao": "EXACT_SUPPORT", "trecho_oficial": "O benefício será concedido à parte que comprovar", "justificativa": "literal"}]}  # noqa: E731
    return citacao.verificar([{"code": "PRELIMINARIES", "content": texto}], _versoes_do_artigo(), HOJE, llm=llm)


def test_transcricao_da_redacao_antiga_do_artigo_bloqueia():
    antiga = _gate('Dispõe o art. 9790 da CLT: "É facultado conceder o benefício a quem perceber salário igual ou inferior ao dobro do mínimo legal."')
    assert "REDACAO_ANTIGA_CITADA" in _codigos(antiga) and not antiga["citacoes"][0]["aprovada"]
    assert "vigente até 2017-11-10" in next(a["detalhe"] for a in antiga["achados"] if a["codigo"] == "REDACAO_ANTIGA_CITADA")
    inventada = _gate("Nos termos do art. 9790 da CLT, “o benefício é automático para todo trabalhador que o requerer”.")
    assert "TRANSCRICAO_DIVERGENTE_DO_TEXTO_OFICIAL" in _codigos(inventada)
    vigente = _gate("O art. 9790 da CLT dispõe que “O benefício será concedido à parte que comprovar insuficiência (...) para o pagamento das custas”.")
    assert vigente["achados"] == [] and vigente["citacoes"][0]["aprovada"]


# ------------------------------------------------------------------ atualização jurídica: ADC 80 no Acervo

def test_acervo_traz_adc_80_vigente_e_tema_21_e_sumula_463_superados():
    itens = jurisprudencia.carregar_arquivo(jurisprudencia.PASTA_PADRAO / "gratuidade_adc80.json")
    normalizados = {i["chave"]: i for i in (jurisprudencia.normalizar(b) for b in itens)}
    assert set(normalizados) == {"adc:stf:80", "tema:tst:21", "sumula:tst:463"}
    assert normalizados["adc:stf:80"]["status"] == "vigente" and normalizados["adc:stf:80"]["vinculante"]
    assert normalizados["tema:tst:21"]["superado_por"] == normalizados["adc:stf:80"]["id"] == "acervo:adc:stf:80"

    store = Memoria()
    rel = jurisprudencia.importar(itens, armazenamento=store, agora=datetime(2026, 10, 1, tzinfo=UTC))
    assert rel["novas"] == 3 and rel["superadas"] == 2 and rel["invalidas"] == 0
    registro = aut.Registro(aut.de_registro_bruto(store.autoridades()))
    assert registro.por_referencia(normalizados["tema:tst:21"]["superado_por"]).chave == "adc:stf:80"
    velho = "A reclamante percebe salário igual ou inferior a 40% do limite máximo dos benefícios do RGPS."
    achados = aut.criterios_superados(velho, registro, HOJE)
    assert achados and achados[0]["chave"] == "tema:tst:21" and achados[0]["superado_por"] == "acervo:adc:stf:80"
    citada = aut.extrair_citacoes("conforme a ADC 80 do STF")[0]
    assert citada.chave == "adc:stf:80" and registro.resolver(citada, HOJE)["authority_id"] == "acervo:adc:stf:80"


def test_controle_concentrado_sem_classe_e_recusado():
    try:
        jurisprudencia.normalizar({"tipo": "controle_concentrado", "tribunal": "STF", "numero": "80", "texto": "x", "fonte_oficial": "STF", "url": "https://stf"})
    except jurisprudencia.ItemInvalido as erro:
        assert "classe" in str(erro)
    else:
        raise AssertionError("ADC sem classe geraria a chave ':stf:80', que nenhuma citação casa")


# ------------------------------------------------------------------ fluxo legado (auditoria estrutural)

def test_fluxo_legado_aponta_verba_rescisoria_com_vinculo_ativo_e_criterio_de_gratuidade_superado():
    plano = {"pedidos": [{"id": "P01", "tipo": "Multa do art. 477 da CLT", "objeto": "pagamento da multa do art. 477"},
                         {"id": "P02", "tipo": "Horas extras", "objeto": "horas extras com reflexos em aviso prévio"}], "fatos": []}
    secoes = [
        {"code": "PRELIMINARIES", "content": "A reclamante percebe salário inferior a 40% do limite máximo dos benefícios do RGPS (Súmula 463, I, do TST)."},
        {"code": "FACTS", "content": "A reclamante continua trabalhando para a reclamada."},
        {"code": "CLAIMS", "content": "a) multa do art. 477, no valor de R$ 3.000,00;\nb) horas extras, em valor a ser apurado em liquidação."},
    ]
    achados = {v.codigo: v for v in auditoria_estrutural.pressupostos_e_atualidade(secoes, plano)}
    assert achados["VERBA_RESCISORIA_COM_VINCULO_ATIVO"].secao == "LEDGER" and achados["VERBA_RESCISORIA_COM_VINCULO_ATIVO"].bloqueia
    assert "P01" in achados["VERBA_RESCISORIA_COM_VINCULO_ATIVO"].trecho and "P02" not in achados["VERBA_RESCISORIA_COM_VINCULO_ATIVO"].trecho
    assert achados["GRATUIDADE_CRITERIO_SUPERADO"].secao == "PRELIMINARIES" and "ADC 80" in achados["GRATUIDADE_CRITERIO_SUPERADO"].correcao
    assert not achados["PEDIDO_ILIQUIDO"].bloqueia and not achados["MEMORIA_DE_CALCULO_AUSENTE"].bloqueia

    dispensada = [{**secoes[1], "content": "A reclamante foi dispensada sem justa causa em 05/03/2026."}, secoes[2]]
    assert "VERBA_RESCISORIA_COM_VINCULO_ATIVO" not in {v.codigo for v in auditoria_estrutural.pressupostos_e_atualidade(dispensada, plano)}
    atual = [{"code": "PRELIMINARIES", "content": "Pela ADC 80 do STF, presume-se a insuficiência de quem recebe até R$ 5.000,00."}]
    assert "GRATUIDADE_CRITERIO_SUPERADO" not in {v.codigo for v in auditoria_estrutural.pressupostos_e_atualidade(atual, {"pedidos": []})}
