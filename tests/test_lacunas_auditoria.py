"""Lacunas do relatório anterior: repetição curta, dono do conteúdo, CASE_FACTS por confiança/independência,
auditor semântico realmente chamado e revisão do ledger exercitada (todos offline, com modelo/embeddings simulados)."""

import pytest

from app import auditor_final as af
from app import auditoria_estrutural as ae
from app import case_facts as cf
from app import peticao_skill_arquivos as skill
from app import plano_da_peticao as pp
from app.conferencia_peticao import Violacao

PARAMS = skill.validacoes_da_skill()["parametros"]


def bloqueantes(achados):
    return {a.codigo for a in achados if a.bloqueia}


def todos(achados):
    return {a.codigo for a in achados}


def secs(**por_codigo):
    return [{"code": c, "label": "", "content": t} for c, t in por_codigo.items()]


COMUNICACOES = ("Nos termos do art. 272, § 1º, do CPC, requer que todas as publicações, notificações e intimações sejam dirigidas "
                "exclusivamente ao advogado Dr. Fulano de Tal, inscrito na OAB/PA nº 1234, sob pena de nulidade.")
PROVAS = ("Requer a produção de todas as provas em direito admitidas, especialmente a prova testemunhal, com a oitiva de Beltrano e Sicrano, "
          "que presenciaram a abordagem armada e poderão confirmar as circunstâncias do evento, a agressividade dos assaltantes e o pavor causado ao reclamante, "
          "e o depoimento pessoal do representante legal da reclamada, sob pena de confissão, além da exibição de documentos pela reclamada.")


# 1 + 4) duplicação CURTA entre duas seções (comunicações repetidas integralmente nos pedidos)
def test_1_4_comunicacao_processual_repetida_nos_pedidos_e_detectada_mesmo_sendo_curta():
    sec = secs(PRELIMINARY=COMUNICACOES, CLAIMS=f"a) a condenação da reclamada;\n\nb) {COMUNICACOES}")
    a = ae.repeticao_de_conteudo(sec, PARAMS)
    assert "REPETICAO_DESNECESSARIA" in bloqueantes(a)
    assert len(COMUNICACOES.split()) < 120  # o caso é CURTO: o limiar de 120 palavras nunca pegaria


# 2) referência curta legítima nos pedidos NÃO é removida
def test_2_referencia_curta_e_legitima_nos_pedidos():
    sec = secs(PRELIMINARY=COMUNICACOES, EVIDENCE=PROVAS,
               CLAIMS="a) a condenação da reclamada ao pagamento de indenização por danos morais (art. 927 do CC);\n\n"
                      "b) a intimação exclusiva do advogado indicado (item I);\n\n"
                      "c) a produção de todas as provas em direito admitidas, na forma do capítulo das provas.")
    assert not bloqueantes(ae.repeticao_de_conteudo(sec, PARAMS))


# 3) prova testemunhal desenvolvida em Provas não é repetida nos pedidos
def test_3_prova_testemunhal_reproduzida_nos_pedidos_e_barrada():
    sec = secs(EVIDENCE=PROVAS, CLAIMS=f"a) a condenação da reclamada;\n\nb) {PROVAS}")
    a = ae.repeticao_de_conteudo(sec, PARAMS)
    assert {"PEDIDO_REPRODUZ_DESENVOLVIMENTO", "REPETICAO_DESNECESSARIA"} & bloqueantes(a)


def test_dono_do_conteudo_desenvolvido_em_duas_secoes_e_apontado():
    outra = "A justiça gratuita é devida porque o autor, hipossuficiente, declarou não poder arcar com custas sem prejuízo do sustento, nos termos do art. 790, § 4º, da CLT e do art. 99 do CPC, o que basta à concessão do benefício. " * 2
    sec = secs(PRELIMINARY=outra, FACTS="A justiça gratuita deve ser concedida ao autor hipossuficiente que declarou não ter condições de pagar as custas do processo sem prejuízo próprio, conforme o art. 790 da CLT. " + "Fatos do caso. " * 5)
    assert "CONTEUDO_DESENVOLVIDO_FORA_DA_SECAO_COMPETENTE" in todos(ae.repeticao_de_conteudo(sec, PARAMS))


# 5–7) CASE_FACTS: conflito, independência das fontes e peso da fonte primária
def _doc(nome, texto, tipo="", dados=None):
    return {"tipo": "documento", "nome": nome, "texto": texto, "tipo_documento": tipo, "dados": dados or []}


@pytest.mark.parametrize("campo,v_cadastro,v_oficial,texto_oficial", [
    ("nome", "Fulano Qualquer", "Maria Aparecida Souza", "RG NOME MARIA APARECIDA SOUZA"),
    ("endereco", "Rua Nova 10 Curitiba PR", "Passagem Santa Fe 70 Belem PA", "RG endereco Passagem Santa Fe 70 Belem PA"),
    ("cpf", "111.111.111-11", "222.222.222-22", "RG CPF 222.222.222-22"),
    ("data_admissao", "01/01/2000", "04/05/1983", "CTPS admissao 04/05/1983"),
    ("cargo", "Motorista", "Agente de Correios", "CTPS cargo Agente de Correios"),
])
def test_5_7_conflito_entre_cadastro_e_documento_oficial_gera_um_unico_valor_canonico(campo, v_cadastro, v_oficial, texto_oficial):
    fontes = [_doc("RG.pdf", texto_oficial, "RG", dados=[("autor", campo, v_oficial)])]
    f = cf.montar(fontes=fontes, cadastro={campo: v_cadastro})
    e = f["PARTIES"]["autor"][campo]
    assert e["valor"] == v_oficial and not e["conflito"] and e["alternativas"][0]["valor"] == v_cadastro
    assert any(u["tipo"] == "divergencia_resolvida" and u["campo"] == f"autor.{campo}" for u in f["UNCERTAINTIES"])  # divergência REGISTRADA
    # a versão perdedora não pode aparecer na peça (uma só verdade)
    sec = secs(HEADING=f"Qualificação de {v_cadastro} e de {v_oficial}") if campo in ("nome", "endereco", "cargo") else secs(HEADING=f"{campo} {v_cadastro} / {v_oficial}")
    assert "DADO_REJEITADO_NO_TEXTO" in bloqueantes(ae.dado_rejeitado_no_texto(sec, f))
    assert not ae.dado_rejeitado_no_texto(secs(HEADING=f"Qualificação de {v_oficial}"), f)


def test_6_copias_do_mesmo_documento_nao_aumentam_a_confianca():
    contrato = "CONTRATO firmado por Fulano Contratual CPF 333.333.333-33"
    tres_copias = [_doc("Contrato.pdf", contrato), _doc("Contrato (Duplicado).pdf", contrato), _doc("Contrato (Duplicado 2).pdf", contrato)]
    oficial = _doc("RG.pdf", "RG CPF 444.444.444-44", "RG")
    f = cf.montar(fontes=[*tres_copias, oficial])
    cpf = f["PARTIES"]["autor"]["cpf"]
    assert cpf["valor"] == "444.444.444-44"                       # 1 fonte primária > 3 cópias do mesmo documento
    assert f["DOCUMENTS"][0]["copias"] == 2                       # as cópias foram colapsadas, não somadas


def test_7_fonte_primaria_pesa_mais_e_sem_margem_o_dado_fica_em_conflito():
    # oficial (1.0) × comprobatório (0.6): vence
    ok = cf.montar(fontes=[_doc("RG.pdf", "CPF 555.555.555-55", "RG"), _doc("Fatura.pdf", "CPF 666.666.666-66")])
    assert ok["PARTIES"]["autor"]["cpf"]["valor"] == "555.555.555-55"
    # dois comprobatórios independentes, mesma classe: empate → SEM valor (não escolhe no chute) e uma incerteza
    empate = cf.montar(fontes=[_doc("A.pdf", "CPF 555.555.555-55"), _doc("B.pdf", "CPF 666.666.666-66")])
    assert empate["PARTIES"]["autor"]["cpf"]["valor"] is None and empate["UNCERTAINTIES"][0]["tipo"] == "conflito"
    # o humano confirmou: vale mais que tudo
    humano = cf.montar(fontes=[_doc("RG.pdf", "CPF 555.555.555-55", "RG")], extraidos=[{"papel": "autor", "campo": "cpf", "valor": "777.777.777-77"}])
    assert humano["PARTIES"]["autor"]["cpf"]["valor"] == "777.777.777-77"


# 8–12) auditor semântico: chamado de fato, detecta duplicação, preserva distintas/subsidiárias, acusa contradição
def _plano(teses=None):
    return {"partes": {}, "fatos": [], "teses": teses or [], "pedidos": []}


def _rodar(secoes, plano, auditor, embed=None, reescrever=None, verificar=None):
    chamadas = []

    def chamar(instr, entrada):
        chamadas.append(entrada)
        return auditor(entrada)

    def verificacoes(s, p):
        return ae.auditar(s, p, PARAMS, [], embed=embed) + (verificar(s, p) if verificar else [])

    out = af.executar(secoes, plano, {"PARTIES": {}, "UNCERTAINTIES": []}, params=PARAMS, verificacoes=verificacoes, chamar=chamar,
                      reescrever=reescrever or (lambda s, o: s["content"]), rerenderizar_pedidos=lambda s, p: s)
    return out, chamadas


def test_8_o_auditor_semantico_e_realmente_chamado_no_fluxo_com_o_material_completo():
    sec = secs(HEADING="abertura", LEGAL_GROUNDS="### a) X\n\ntexto do capítulo")
    (novas, achados, rel), chamadas = _rodar(sec, _plano(), lambda e: {"itens": []})
    assert len(chamadas) == 1 and rel["liberada"]
    assert "rascunho" in chamadas[0] and "ledger_de_pedidos" in chamadas[0] and "mapa_de_teses" in chamadas[0] and "CASE_FACTS" in chamadas[0]
    assert "duplicação substancial" in af.INSTRUCAO and "subsidiária" in af.INSTRUCAO and "fatos não se contradizem" in af.INSTRUCAO


def test_9_auditor_recebe_o_candidato_de_paráfrase_e_a_correcao_e_disparada():
    a = "A empresa deixou de fornecer proteção adequada ao empregado, expondo-o ao risco de assaltos na agência aberta ao público durante o atendimento. " * 3
    b = "A empregadora não adotou medidas suficientes para garantir a segurança do trabalhador, sujeitando-o a roubos no balcão de atendimento da unidade. " * 3
    sec = secs(LEGAL_GROUNDS=f"### a) Da responsabilidade subjetiva\n\n{a}\n\n### b) Do dever de segurança\n\n{b}")
    vetores = {0: [1.0, 0.0, 0.0], 1: [0.99, 0.1, 0.0]}      # paráfrases: embeddings quase iguais (n-gramas não pegariam)
    embed = lambda textos: [vetores[i] for i in range(len(textos))]  # noqa: E731
    assert "REPETICAO_ENTRE_TOPICOS" not in todos(ae.repeticao_entre_topicos(sec))  # o n-grama NÃO detecta a paráfrase
    assert "SOBREPOSICAO_SEMANTICA_CANDIDATA" in todos(ae.candidatos_semanticos(sec, _plano(), embed))

    def auditor(entrada):
        assert "candidatos_de_sobreposicao" in entrada and "Do dever de segurança" in entrada
        return {"itens": [{"criterio": "sem repetição argumentativa excessiva", "ok": False, "severidade": "critico", "secao": "LEGAL_GROUNDS",
                           "trecho": "Do dever de segurança", "problema": "mesmo argumento dos itens a) e b)", "correcao": "funda os capítulos"}]}

    chamadas_reescrita = []

    def reescrever(s, orientacao):
        chamadas_reescrita.append(orientacao)
        return s["content"].replace("### b) Do dever de segurança", "### b) Do dever de segurança (ver item a)")

    def verificar(s, p):
        return []  # o embed só alimenta o candidato; a decisão é do auditor

    (novas, achados, rel), chamadas = _rodar(sec, _plano(), auditor, embed=embed, reescrever=reescrever)
    assert chamadas_reescrita and "AUDITOR_" in chamadas_reescrita[0] and rel["iteracoes"][0]["criticos"]


def test_10_teses_relacionadas_com_fundamentos_diferentes_nao_sao_duplicacao():
    fato = "O reclamante foi vítima de assalto à mão armada em 05/12/2024 no interior da agência onde exercia a função de atendente. "
    a = fato + "Aplica-se a responsabilidade objetiva do art. 927, parágrafo único, do CC, pois a atividade implica risco especial reconhecido pelo Tema 932 do STF, dispensada a prova de culpa. " * 2
    b = fato + "O dano moral é presumido pela violência sofrida e sua quantificação observa o art. 223-G da CLT, a capacidade econômica da ofensora e o caráter pedagógico da medida, sem enriquecimento sem causa. " * 2
    sec = secs(LEGAL_GROUNDS=f"### a) Da responsabilidade objetiva\n\n{a}\n\n### b) Do dano moral in re ipsa\n\n{b}")
    vetores = {0: [1.0, 0.0, 0.0], 1: [0.4, 0.9, 0.1]}       # sentidos diferentes
    embed = lambda textos: [vetores[i] for i in range(len(textos))]  # noqa: E731
    assert not bloqueantes(ae.repeticao_entre_topicos(sec))
    assert not ae.candidatos_semanticos(sec, _plano(), embed)  # compartilhar fato não é duplicação


def test_11_tese_principal_e_subsidiaria_do_mesmo_evento_sao_preservadas():
    txt = "O empregador responde pelos danos do assalto sofrido em serviço, porque a atividade de atendimento em agência aberta ao público expõe o trabalhador a risco acentuado e previsível de roubo, e a segurança do ambiente de trabalho é dever seu. " * 3
    sec = secs(LEGAL_GROUNDS=f"### a) Da responsabilidade objetiva do empregador\n\n{txt}\n\n### b) Subsidiariamente, da responsabilidade subjetiva do empregador\n\n{txt}")
    teses = [{"id": "T01", "titulo": "Responsabilidade objetiva do empregador", "relacao": "principal", "fatos_ids": [], "pedidos_ids": []},
             {"id": "T02", "titulo": "Subsidiariamente, responsabilidade subjetiva do empregador", "relacao": "subsidiaria_de:T01", "fatos_ids": [], "pedidos_ids": []}]
    assert "REPETICAO_ENTRE_TOPICOS" in todos(ae.repeticao_entre_topicos(sec))                       # sem o plano: pareceria duplicação
    assert not ae.repeticao_entre_topicos(sec, plano=_plano(teses))                                    # com a relação declarada: preservadas
    vetores = {0: [1.0, 0.0], 1: [1.0, 0.0]}
    assert not ae.candidatos_semanticos(sec, _plano(teses), lambda t: [vetores[i] for i in range(len(t))])


def test_12_contradicao_entre_capitulos_e_detectada():
    plano = {"partes": {}, "teses": [], "pedidos": [], "fatos": [{"id": "F01", "data": "05/12/2024", "fato": "Assalto à mão armada na agência durante o expediente do reclamante", "documentos": []}]}
    sec = secs(FACTS="O assalto à mão armada na agência durante o expediente do reclamante ocorreu em 05/12/2024.", LEGAL_GROUNDS="O assalto à mão armada na agência durante o expediente do reclamante ocorreu em 15/12/2024.")
    a = ae.contradicao_de_data(sec, plano)
    assert "CONTRADICAO_DE_DATA" in bloqueantes(a) and "15/12/2024" in a[0].motivo

    def auditor(entrada):
        return {"itens": [{"criterio": "fatos não se contradizem", "ok": False, "severidade": "critico", "secao": "FACTS", "trecho": "X", "problema": "afirma X e depois não-X", "correcao": "harmonize"}]}

    (n, ach, rel), _ = _rodar(sec, plano, auditor)
    assert any(c.startswith("AUDITOR_") for c in rel["iteracoes"][0]["criticos"] for c in [c.split(":")[0]])


# 13–16) revisão do ledger exercitada
def _p(id_, tipo, objeto, tese="T01", natureza="cumulativo", valor=None, causa="", metodo=None, praxe=False):
    return {"id": id_, "tipo": tipo, "objeto": objeto, "fundamento": "art. 927 CC", "valor_ou_base": "", "de_praxe": praxe, "tese_origem": tese,
            "causa_de_pedir": causa, "natureza": natureza, "valor": valor, "metodo_calculo": metodo or {}, "dependencias": []}


def _pl(pedidos):
    return {"partes": {}, "fatos": [], "teses": [{"id": "T01", "titulo": "Dano moral", "fatos_ids": ["F01"], "consequencia": "x", "gera_pedido": True}], "pedidos": pedidos}


def test_13_duplicidade_literal_e_semantica_no_ledger():
    a = _p("P01", "dano moral", "indenização por dano psicológico decorrente do assalto", valor=10000.0)
    literal = dict(a, id="P02")
    unicos, fundidos = pp.deduplicar([a, literal])
    assert len(unicos) == 1 and fundidos[0]["motivo"] == "mesmo tipo/objeto/tese/base"
    b = _p("P03", "reparação", "indenização pelo abalo psíquico decorrente do mesmo evento", valor=10000.0)
    juiz_calls = []
    unicos, _ = pp.deduplicar([a, b], similaridade=lambda x, y: 0.95, adjudicar=lambda u, p: juiz_calls.append((u["id"], p["id"])) or True)
    assert len(unicos) == 1 and juiz_calls == [("P01", "P03")]  # a decisão semântica passou pelo juiz


def test_14_pedidos_cumulativos_distintos_e_parecidos_mas_diferentes_sao_preservados():
    horas23 = _p("P01", "horas extras", "horas extras de 2023", "T01", valor=1000.0)
    horas24 = _p("P02", "horas extras", "horas extras de 2024", "T01", valor=2000.0)
    moral = _p("P03", "dano moral", "indenização por danos morais", "T01", valor=5000.0)
    unicos, fundidos = pp.deduplicar([horas23, horas24, moral], similaridade=lambda x, y: 0.93, adjudicar=lambda u, p: False)
    assert [p["id"] for p in unicos] == ["P01", "P02", "P03"] and not fundidos
    assert not [a for a in ae.ledger(_pl([horas23, horas24, moral])) if a.bloqueia]


def test_15_majoracao_nao_vira_segunda_indenizacao_e_a_revisao_do_ledger_e_validada():
    principal = _p("P01", "dano moral", "indenização por danos morais do assalto", valor=27480.0, causa="assalto")
    major = _p("P02", "majoração do dano moral", "majoração da indenização por dano moral em razão do adoecimento psíquico", valor=13740.0, causa="assalto")
    problemas = [a for a in ae.ledger(_pl([principal, major])) if a.bloqueia]
    assert {a.codigo for a in problemas} == {"MAJORACAO_COMO_SEGUNDA_INDENIZACAO"}
    fundido = {"pedidos": [{"tipo": "dano moral", "tese_origem": "T01", "objeto": "indenização por danos morais do assalto, considerado o agravamento psíquico na quantificação",
                            "valor": 41220.0, "natureza": "cumulativo", "causa_de_pedir": "assalto", "fundamento": "art. 927 CC",
                            "metodo_calculo": {"base": 3435.0, "multiplicador": 12, "resultado": 41220.0}}]}
    novos = af.revisar_ledger(lambda i, e: fundido, _pl([principal, major]), problemas)
    assert novos and len(novos) == 1 and novos[0]["id"] == "P01"
    ainda_ruim = {"pedidos": [dict(principal), dict(major)]}     # o modelo "corrige" sem corrigir: NÃO é aceito
    assert af.revisar_ledger(lambda i, e: ainda_ruim, _pl([principal, major]), problemas) is None
    assert af.revisar_ledger(lambda i, e: {}, _pl([principal, major]), problemas) is None


def test_16_principal_e_subsidiario_nao_entram_juntos_na_soma_do_valor_da_causa():
    principal = _p("P01", "dano moral", "indenização por danos morais", valor=10000.0)
    subsid = _p("P02", "dano moral", "indenização por danos morais em valor menor, se afastada a responsabilidade objetiva", valor=4000.0, natureza="subsidiario")
    pl = _pl([principal, subsid])
    assert ae.soma_cumulativos(pl) == 10000.0
    sec = secs(CLAIMS="Dá-se à causa o valor de R$ 14.000,00.")
    assert "VALOR_DA_CAUSA_NAO_FECHA" in bloqueantes(ae.valor_da_causa(sec, pl))
    assert not ae.valor_da_causa(secs(CLAIMS="Dá-se à causa o valor de R$ 10.000,00."), pl)
    # e o subsidiário (mesma linguagem do principal) NÃO é tratado como duplicado
    assert not [a for a in ae.ledger(pl) if a.codigo in ("PEDIDOS_SOBREPOSTOS", "PEDIDO_DUPLICADO")]


def test_8b_o_auditor_e_chamado_pelo_pipeline_real_de_lintar_e_corrigir(monkeypatch):
    """Integração: `peticao_local._lintar_e_corrigir` (usado em `gerar`) chama o auditor semântico com o material completo."""
    from app import peticao_local as pl

    vistos = []
    monkeypatch.setattr(pl, "_llm_json", lambda instrucao, entrada, timeout=0: vistos.append(instrucao) or {"itens": []})
    monkeypatch.setattr(pl, "_fontes_da_conferencia", lambda caso_id, **k: __import__("app.conferencia_peticao", fromlist=["Fontes"]).Fontes(anexos=[], numerados=[]))
    plano = {"partes": {}, "fatos": [], "teses": [], "pedidos": [], "case_facts": {"PARTIES": {}, "UNCERTAINTIES": []}}
    sec = [{"code": "HEADING", "label": "", "content": "Ao Juízo da Vara do Trabalho de Belém/PA. abertura"}]
    _, _, rel = pl._lintar_e_corrigir("c1", sec, plano, texto_do_caso="", textos_do_acervo=[], material="")
    assert any(af.INSTRUCAO[:60] in i for i in vistos) and rel["iteracoes"]
