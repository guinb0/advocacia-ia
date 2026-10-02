"""Regressões da petição v10: cada erro encontrado nela tem de ser BLOQUEADO pela arquitetura nova.

Os textos abaixo reproduzem a ESTRUTURA dos defeitos da v10 (abertura duplicada com CNPJ preenchido num lugar e
[PENDENTE] no outro, dois "Objeto", capítulo V sem título, majoração lançada como 2ª indenização, "salários
mínimos" no dispositivo × "salário líquido" na fundamentação, ausência de documento como prova de ausência).
"""

import pytest

from app import auditor_final as af
from app import auditoria_estrutural as ae
from app import case_facts as cf
from app import petition_linter as lint
from app import peticao_skill_arquivos as skill
from app import plano_da_peticao as pp

PARAMS = skill.validacoes_da_skill()["parametros"]

CASO = ("Paulo Sergio Leandro Burcaos brasileiro casado agente de correios RG 2875340 CPF 152.815.582-34 Passagem Santa Fe 70 Belem PA. "
        "ECT CNPJ 34.028.316/0001-03 Rua Santo Antonio 438. Assalto em 05/12/2024. Salario liquido R$ 2.290,00. CAT emitida pela ECT.")

QUALI = ("**PAULO SERGIO LEANDRO BURCAOS**, brasileiro, casado, agente de correios, portador do RG nº 2875340, inscrito no CPF sob o nº "
         "152.815.582-34, residente na Passagem Santa Fe 70, Belem/PA, vem propor a presente")
REU = "em face de **EMPRESA BRASILEIRA DE CORREIOS E TELEGRAFOS**, inscrita no CNPJ sob o nº 34.028.316/0001-03."

PARTES = {"autor": {"nome": "Paulo Sergio Leandro Burcaos", "rg": "2875340", "cpf": "152.815.582-34", "endereco": "Passagem Santa Fe 70 Belem PA"},
          "reu": {"nome": "Empresa Brasileira de Correios e Telegrafos", "cnpj": "34.028.316/0001-03"}}


def ped(id_, tipo, objeto, tese="T01", natureza="cumulativo", valor=None, metodo=None, causa="", praxe=False):
    return {"id": id_, "tipo": tipo, "objeto": objeto, "fundamento": "art. 927 CC", "valor_ou_base": "", "de_praxe": praxe, "tese_origem": tese,
            "causa_de_pedir": causa, "natureza": natureza, "valor": valor, "metodo_calculo": metodo or {}, "dependencias": []}


def plano(pedidos=None, teses=None):
    return {"partes": PARTES, "fatos": [{"id": "F01", "fato": "Assalto em 05/12/2024", "data": "", "documentos": ["CAT"]}],
            "teses": teses or [{"id": "T01", "titulo": "Responsabilidade objetiva por assalto", "fatos_ids": ["F01"], "provas": ["CAT"], "consequencia": "dano moral", "gera_pedido": True}],
            "pedidos": pedidos or []}


def secoes(*textos, codigos=None):
    codigos = codigos or ["HEADING"] + ["LEGAL_GROUNDS"] * (len(textos) - 1)
    return [{"code": c, "label": "", "content": t} for c, t in zip(codigos, textos)]


def codigos(achados):
    return {a.codigo for a in achados if a.bloqueia}


# T1 — nunca duas qualificações completas do mesmo autor (v10: abertura repetida)
def test_1_duas_qualificacoes_completas_sao_bloqueadas_e_a_repetida_e_removida_deterministicamente():
    abertura = f"::: enderecamento\nAO JUÍZO DA VARA\n:::\n\n::: objeto\nObjeto: A\n:::\n\n{QUALI}\n\n::: titulo_acao\nRECLAMAÇÃO TRABALHISTA\n:::\n\n{REU}"
    repetida = abertura + f"\n\n{QUALI}\n\n**RECLAMAÇÃO TRABALHISTA**\n\n{REU.replace('34.028.316/0001-03', '[PENDENTE: CNPJ da reclamada]')}\n\n::: objeto\nObjeto: B\n:::"
    sec = secoes(repetida)
    assert {"QUALIFICACAO_DUPLICADA", "BLOCO_ESTRUTURAL_DUPLICADO"} <= codigos(ae.abertura_unica(sec, PARTES, PARAMS))
    limpas, removidos = ae.remover_aberturas_duplicadas(sec, PARTES, PARAMS)
    assert removidos >= 2 and not codigos(ae.abertura_unica(limpas, PARTES, PARAMS))
    assert limpas[0]["content"].count("152.815.582-34") == 1 and "Objeto: B" not in limpas[0]["content"]
    assert "PENDENTE" not in limpas[0]["content"]


# T2 — dado canônico não pode estar preenchido numa parte e [PENDENTE] noutra
def test_2_pendente_de_dado_que_o_case_facts_ja_tem_e_bloqueado():
    sec = secoes(f"{QUALI} {REU}", "A reclamada, inscrita no CNPJ sob o nº [PENDENTE: CNPJ da reclamada], responde.")
    assert "PENDENTE_COM_DADO_CANONICO" in codigos(ae.pendencia_com_dado_canonico(sec, PARTES))
    sem_dado = {"autor": PARTES["autor"], "reu": {"nome": "ECT"}}
    assert not ae.pendencia_com_dado_canonico(sec, sem_dado)  # sem dado canônico, a pendência é legítima


def test_case_facts_resolve_conflito_por_regra_segura_e_recusa_o_que_nao_e_fonte_do_caso():
    fontes = [{"tipo": "documento", "nome": "CAT.pdf", "texto": "CNPJ 34.028.316/4948-66 CPF 152.815.582-34"},
              {"tipo": "documento", "nome": "LISA.pdf", "texto": "CNPJ 34.028.316/4948-66"},
              {"tipo": "documento", "nome": "Contrato.pdf", "texto": "CNPJ 34.028.316/0001-03"}]
    f = cf.montar(fontes=fontes, cadastro={"nome": "Autor Fixture Unitario"}, proposta_partes={})
    cnpj = f["PARTIES"]["reu"]["cnpj"]
    assert cnpj["valor"] == "34.028.316/4948-66" and cnpj["alternativas"] and not cnpj["conflito"]  # mesma raiz: compatível, vale o de mais fontes
    assert any(r["campo"] == "reu.cnpj" for r in f["RESOLUTIONS"])
    # sem regra segura (1 fonte contra 1 fonte) o campo fica SEM valor e vira incerteza — a peça não escolhe no chute
    duas = cf.montar(fontes=[{"tipo": "documento", "nome": "A", "texto": "CPF 111.111.111-11"}, {"tipo": "documento", "nome": "B", "texto": "CPF 222.222.222-22"}])
    assert duas["PARTIES"]["autor"]["cpf"]["valor"] is None and duas["UNCERTAINTIES"][0]["tipo"] == "conflito"
    assert "cpf" not in cf.partes_resolvidas(duas)["autor"]


# T8 — fatos das 700+ peças não entram no CASE_FACTS
def test_8_peca_do_acervo_e_recusada_como_fonte_e_o_dado_dela_e_barrado_na_peca():
    with pytest.raises(cf.FonteRecusada):
        cf.montar(fontes=[{"tipo": "acervo", "nome": "PETICAO ANTIGA.docx", "texto": "CPF 008.038.763-27"}])
    acervo = ["Maria, CPF 008.038.763-27, assaltada em 17/03/2019, recebia R$ 2.380,00."]
    contaminada = secoes(f"{QUALI} {REU}", "O assalto ocorreu em 17/03/2019 com salário de R$ 2.380,00.")
    assert "CONTAMINACAO_DO_ACERVO" in codigos(lint.lintar(contaminada, plano(), texto_do_caso=CASO, textos_do_acervo=acervo, params=PARAMS))


# T3 — pedidos semanticamente equivalentes / mesma lesão (v10: "majoração" como 2º pedido)
def test_3_majoracao_lancada_como_segunda_indenizacao_e_bloqueada():
    peds = [ped("P01", "dano moral", "indenização por danos morais do assalto", valor=27480.0),
            ped("P02", "majoração do dano moral", "majoração da indenização por dano moral em razão do adoecimento psíquico", "T01", valor=13740.0)]
    assert "MAJORACAO_COMO_SEGUNDA_INDENIZACAO" in codigos(ae.ledger(plano(peds)))


def test_3b_pedidos_diferentes_com_linguagem_parecida_nao_sao_barrados():
    peds = [ped("P01", "horas extras", "horas extras de 2023", "T01", valor=1000.0), ped("P02", "dano moral", "indenização por danos morais do assalto", "T02", valor=5000.0)]
    teses = [{"id": "T01", "titulo": "Horas", "fatos_ids": ["F01"], "consequencia": "x", "gera_pedido": True}, {"id": "T02", "titulo": "Moral", "fatos_ids": ["F01"], "consequencia": "y", "gera_pedido": True}]
    assert not codigos(ae.ledger(plano(peds, teses)))


# T4 / T5 — subsidiário não soma como cumulativo; valor da causa fecha com os cumulativos
def test_4_5_subsidiario_nao_entra_na_soma_e_valor_da_causa_e_conferido():
    peds = [ped("P01", "dano moral", "indenização por danos morais", valor=10000.0),
            ped("P02", "dano material", "ressarcimento subsidiário de despesas", valor=500.0, natureza="subsidiario"),
            ped("P03", "honorários", "honorários de sucumbência", valor=None, praxe=True)]
    pl = plano(peds)
    assert ae.soma_cumulativos(pl) == 10000.0
    errado = secoes("x", "Dá-se à causa o valor de R$ 10.500,00.", codigos=["HEADING", "CLAIMS"])
    certo = secoes("x", "Dá-se à causa o valor de R$ 10.000,00.", codigos=["HEADING", "CLAIMS"])
    assert "VALOR_DA_CAUSA_NAO_FECHA" in codigos(ae.valor_da_causa(errado, pl)) and not ae.valor_da_causa(certo, pl)
    assert "VALOR_DA_CAUSA_AUSENTE" in codigos(ae.valor_da_causa(secoes("x", codigos=["HEADING"]), pl))
    somado = [{**p, "incluido_no_valor_da_causa": p["natureza"] == "subsidiario"} for p in peds]
    assert "SUBSIDIARIO_SOMADO_AO_PRINCIPAL" in codigos(ae.ledger(plano(somado)))


# T6 — critério de cálculo da fundamentação = o dos pedidos (v10: "salário líquido" × "salários mínimos")
def test_6_criterio_da_fundamentacao_diferente_do_dos_pedidos_e_bloqueado():
    fund = "### h) Da quantificação da indenização\n\nAdota-se como parâmetro o salário líquido do reclamante, de R$ 2.290,00, multiplicado por 12."
    pedidos = "a) indenização por dano moral no valor de R$ 27.480,00, correspondente a 12 salários mínimos;"
    sec = [{"code": "LEGAL_GROUNDS", "content": fund}, {"code": "CLAIMS", "content": pedidos}]
    assert "CRITERIO_DE_CALCULO_DIVERGENTE" in codigos(ae.criterio_de_calculo(sec, PARAMS))
    coerente = [sec[0], {"code": "CLAIMS", "content": "a) indenização no valor de R$ 27.480,00, correspondente a 12 vezes o salário líquido;"}]
    assert not ae.criterio_de_calculo(coerente, PARAMS)


def test_valor_x_metodo_no_ledger():
    p = ped("P01", "dano moral", "indenização", valor=27480.0, metodo={"base": 2290.0, "multiplicador": 12, "resultado": 30000.0})
    assert "VALOR_INCONSISTENTE_COM_METODO" in codigos(ae.ledger(plano([p])))


# T7 — duas teses/capítulos com conteúdo substancialmente idêntico
def test_7_capitulos_que_repetem_o_mesmo_texto_sao_barrados():
    corpo = ("O reclamante foi rendido no caixa da agência por dois assaltantes armados, que exigiram a entrega dos valores, conforme registrou a própria reclamada na CAT "
             "e no LISA, o que caracteriza atividade de risco e atrai a responsabilidade objetiva prevista no art. 927, parágrafo único, do Código Civil, nos termos do Tema 932 do STF, "
             "de modo que a empregadora responde pelos danos independentemente de culpa, sendo irrelevante a alegação de fato de terceiro por se tratar de fortuito interno inerente à atividade explorada. ") * 2
    sec = [{"code": "LEGAL_GROUNDS", "content": f"### a) Da responsabilidade objetiva\n\n{corpo}\n\n### b) Do dano moral\n\n{corpo}"}]
    assert "REPETICAO_ENTRE_TOPICOS" in codigos(ae.repeticao_entre_topicos(sec))
    distintos = [{"code": "LEGAL_GROUNDS", "content": f"### a) Da responsabilidade objetiva\n\n{corpo}\n\n### b) Do dano moral\n\n" + "A dor psíquica documentada em receituário e atestado revela lesão à integridade emocional, presumida pela violência, e a indenização deve considerar a extensão do dano, a capacidade econômica da ofensora e o caráter pedagógico da condenação, sem enriquecimento indevido. " * 3}]
    assert not ae.repeticao_entre_topicos(distintos)


# T9 — ausência de documento não vira afirmação categórica de inexistência
def test_9_ausencia_documental_como_prova_e_bloqueada_mas_a_alegacao_ancorada_passa():
    from app import conferencia_peticao as c

    regras = skill.validacoes_da_skill()
    fontes = c.Fontes(anexos=[], numerados=[])

    def achados(t):
        return {a.codigo for a in c.conferir([{"code": "LEGAL_GROUNDS", "content": t}], fontes, regras)}

    ruim = "Esse reconhecimento, somado à ausência de qualquer medida de segurança documentada, confirma a culpa omissiva da reclamada."
    ruim2 = "A reclamada não adotou nenhuma medida de segurança na agência."
    bom = "Não consta dos documentos juntados nenhuma medida de segurança da agência, cabendo à reclamada, que detém a prova, demonstrá-la (art. 818, § 1º, da CLT)."
    assert "AUSENCIA_DOCUMENTAL_COMO_PROVA" in achados(ruim) and "AUSENCIA_DOCUMENTAL_COMO_PROVA" in achados(ruim2)
    assert "AUSENCIA_DOCUMENTAL_COMO_PROVA" not in achados(bom)


# T10 — pedido relevante sem tese/fundamentação; tese sem pedido (bidirecional)
def test_10_pedido_sem_tese_ou_fato_e_tese_sem_pedido_sao_detectados():
    from tests.test_petition_linter import PARAMS as P2  # noqa: F401

    orfao = ped("P01", "vínculo", "reconhecimento de vínculo", tese="")
    achados = lint._pedidos(secoes("x", "a) reconhecimento de vínculo empregatício;", codigos=["HEADING", "CLAIMS"]), plano([orfao]))
    assert "PEDIDO_SEM_TESE" in codigos(achados)
    tese_sem_pedido = plano([], [{"id": "T01", "titulo": "Dano moral", "fatos_ids": ["F01"], "consequencia": "indenização", "gera_pedido": True}])
    assert any(a.codigo == "TESE_SEM_PEDIDO" for a in ae.ledger(tese_sem_pedido))


# T11 — placeholder [PENDENTE] não passa silenciosamente numa peça "pronta"
def test_11_pendente_no_texto_e_listado_para_o_readiness():
    sec = secoes("Texto [PENDENTE: valor a apurar com comprovantes]", "Outro [PENDENTE: data]")
    assert [m for _, m in ae.pendencias(sec)] == ["[PENDENTE: valor a apurar com comprovantes]", "[PENDENTE: data]"]


# T12 — numeração de seções: não pula nem duplica (v10: I,II,III,IV,VI,VII)
def test_12_numeracao_que_pula_ou_repete_e_bloqueada():
    assert "NUMERACAO_DE_SECOES" in codigos(ae.numeracao([("A", "I. DOS FATOS"), ("B", "II. DAS PRELIMINARES"), ("C", "IV. DO DIREITO")]))
    assert not ae.numeracao([("A", "I. A"), ("B", "II. B"), ("C", "III. C")])
    assert "NUMERACAO_DE_SUBITENS" in codigos(ae.subitens([{"code": "X", "content": "### a) A\n\ntexto\n\n### c) C\n\ntexto"}]))


def test_12b_capitulo_cujo_conteudo_abre_com_subcapitulo_continua_com_titulo_impresso():
    """A causa raiz do capítulo V sumido na v10: `##`/`###` era tratado como 'o título da seção'."""
    secao = {"code": "LEGAL_GROUNDS", "label": "V. DO DIREITO", "content": "### a) Da prescrição\n\ntexto"}
    assert lint.deve_imprimir_rotulo(secao["label"], secao["content"]) is True
    assert lint.titulos_impressos([secao]) == [("LEGAL_GROUNDS", "V. DO DIREITO")]
    com_titulo_proprio = {"code": "X", "label": "V. DO DIREITO", "content": "# V. DO DIREITO\n\ntexto"}
    assert lint.deve_imprimir_rotulo(com_titulo_proprio["label"], com_titulo_proprio["content"]) is False


# auditor final: laço com limite e pendência humana no fim
def test_auditor_final_corrige_uma_vez_e_encaminha_ao_humano_o_que_nao_consegue():
    sec = secoes("abertura", "texto com defeito")
    chamadas = {"n": 0}

    def verificacoes(s, p):
        ruim = "defeito" in s[1]["content"]
        return [lint.Violacao("X", "LEGAL_GROUNDS", "defeito", "há defeito", "corrija", True)] if ruim else []

    def reescrever(secao, orientacao):
        chamadas["n"] += 1
        return secao["content"].replace("defeito", "ok")

    novas, achados, rel = af.executar(sec, plano(), {"PARTIES": {}, "UNCERTAINTIES": []}, params=PARAMS, verificacoes=verificacoes,
                                      chamar=lambda i, e: {"itens": []}, reescrever=reescrever, rerenderizar_pedidos=lambda s, p: s)
    assert rel["liberada"] and "ok" in novas[1]["content"] and len(rel["iteracoes"]) == 2

    def teimoso(secao, orientacao):
        return secao["content"]  # nunca resolve

    novas, achados, rel = af.executar(sec, plano(), {"PARTIES": {}, "UNCERTAINTIES": []}, params=PARAMS, verificacoes=verificacoes,
                                      chamar=lambda i, e: {"itens": []}, reescrever=teimoso, rerenderizar_pedidos=lambda s, p: s, max_iteracoes=3)
    assert not rel["liberada"] and len(rel["iteracoes"]) == 3 and rel["pendencias_humanas"]  # limite de iterações → revisão humana
