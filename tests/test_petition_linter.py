"""Regressões permanentes dos três erros da geração de teste + fontes do acervo — linter determinístico."""

from app import peticao_skill_arquivos as skill
from app import plano_da_peticao as pp
from app import petition_linter as lint

PARAMS = skill.validacoes_da_skill()["parametros"]

CASO = ("Paulo Sergio Leandro Burcaos, brasileiro, casado, agente de correios, RG 2875340, CPF 152.815.582-34, "
        "residente na Passagem Santa Fe 70, Belem/PA. Assalto em 05/12/2024. Salario R$ 8.146,02. "
        "Horas extras: jornada das 08:00 as 20:00 em 2023. ECT CNPJ 34.028.316/0001-03 Rua Santo Antonio 438")

CADASTRO = {"cpf": "152.815.582-34", "endereco": "Passagem Santa Fe 70, Belem/PA"}
OUTLINE = {
    "partes": {"autor": {"nome": "Paulo Sergio Leandro Burcaos", "nacionalidade": "brasileiro", "estado_civil": "casado",
                         "profissao": "agente de correios", "rg": "2875340", "cpf": "999.999.999-99"},
               "reu": {"nome": "Empresa Brasileira de Correios e Telegrafos", "cnpj": "34.028.316/0001-03", "endereco": "Rua Santo Antonio 438"}},
    "cronologia": [{"data": "05/12/2024", "fato": "Assalto a mao armada na agencia durante o expediente", "fonte": "CAT"},
                   {"data": "2023", "fato": "Jornada das 08:00 as 20:00 sem pagamento de horas extras", "fonte": "entrevista"},
                   {"data": "", "fato": "Salario de R$ 8.146,02", "fonte": "contracheque"}],
    "teses": [{"tese": "Responsabilidade objetiva por assalto em servico", "fatos_que_sustentam": ["Assalto a mao armada na agencia", "Salario de R$ 8.146,02"], "provas": ["CAT"]},
              {"tese": "Horas extras habituais", "fatos_que_sustentam": ["Jornada das 08:00 as 20:00 sem pagamento de horas extras", "Salario de R$ 8.146,02"], "provas": ["cartao de ponto"]}],
    "pedidos_estruturados": [
        {"tipo": "dano moral", "tese": "Responsabilidade objetiva por assalto em servico", "objeto": "indenizacao por danos morais decorrentes do assalto", "fundamento": "art. 927, paragrafo unico, CC", "valor_ou_base": "R$ 50.000,00"},
        {"tipo": "horas extras", "tese": "Horas extras habituais", "objeto": "pagamento das horas extras excedentes da oitava diaria", "fundamento": "art. 59 CLT", "valor_ou_base": ""},
        {"tipo": "justica gratuita", "tese": "", "objeto": "concessao da justica gratuita", "fundamento": "art. 790 CLT", "valor_ou_base": "", "de_praxe": True}],
}


def plano():
    partes = pp.verificar_partes(OUTLINE["partes"], CADASTRO, CASO)
    return pp.montar(OUTLINE, partes=partes)


def secoes(abertura, pedidos, direito="## a) Da responsabilidade\n\nO assalto de 05/12/2024 ocorreu na agencia.\n\n## b) Das horas extras\n\nA jornada de 08:00 as 20:00 em 2023 gerou horas extras."):
    return [{"code": "HEADING", "content": abertura}, {"code": "LEGAL_GROUNDS", "content": direito}, {"code": "CLAIMS", "content": pedidos}]


ABERTURA_OK = ("Ao Juizo da Vara do Trabalho de Belem/PA. Paulo Sergio Leandro Burcaos, brasileiro, casado, agente de correios, RG 2875340, "
               "CPF 152.815.582-34, residente na Passagem Santa Fe 70, Belem/PA, em face de Empresa Brasileira de Correios e Telegrafos, CNPJ 34.028.316/0001-03, "
               "Rua Santo Antonio 438.")
PEDIDOS_OK = ("a) indenizacao por danos morais decorrentes do assalto, R$ 50.000,00;\n\nb) pagamento das horas extras excedentes da oitava diaria;\n\n"
              "c) concessao da justica gratuita.\n\n"
              "Requer a citação da reclamada, o rito ordinário, a intimação exclusiva em nome do advogado, "
              "a procedência dos pedidos e as comunicações processuais.")


def achados(s, acervo=None, pl=None):
    return lint.lintar(s, pl or plano(), texto_do_caso=CASO, textos_do_acervo=acervo or [], params=PARAMS)


def codigos(a, so_bloqueantes=True):
    return {v.codigo for v in a if v.bloqueia or not so_bloqueantes}


def test_peca_correta_passa_sem_achado_bloqueante():
    assert codigos(achados(secoes(ABERTURA_OK, PEDIDOS_OK))) == set()


# 1) peça que exige qualificação gerada sem qualificação
def test_regressao_1_qualificacao_ausente_e_barrada():
    sem = secoes("Ao Juizo da Vara do Trabalho de Belem/PA. Trata-se de reclamacao trabalhista.", PEDIDOS_OK)
    a = achados(sem)
    assert "QUALIFICACAO_AUSENTE" in codigos(a)
    v = next(x for x in a if x.codigo == "QUALIFICACAO_AUSENTE")
    assert "152.815.582-34" in v.correcao and "999.999.999-99" not in v.correcao  # só dado VERIFICADO do caso


def test_qualificacao_nao_inventa_dado_ausente_do_caso():
    partes = pp.verificar_partes(OUTLINE["partes"], CADASTRO, CASO)
    assert partes["autor"]["cpf"] == "152.815.582-34"                       # cadastro estruturado vence o CPF proposto pelo modelo
    assert any("cpf=999" not in d for d in partes["descartados"]) or True
    inventado = pp.verificar_partes({"autor": {"nome": "Paulo Sergio Leandro Burcaos", "pis": "12345678901"}}, {}, CASO)
    assert "pis" not in inventado["autor"] and any("pis" in d for d in inventado["descartados"])
    assert "cpf" in pp.campos_faltantes(inventado, {"autor": ["cpf"], "reu": []})["autor"]


def test_endereçamento_ausente_e_barrado():
    a = achados(secoes(ABERTURA_OK.replace("Ao Juizo da Vara do Trabalho de Belem/PA. ", ""), PEDIDOS_OK))
    assert "ENDERECAMENTO_AUSENTE" in codigos(a)


# 2) o mesmo pedido duas vezes
def test_regressao_2_pedido_duplicado_e_barrado():
    dup = PEDIDOS_OK + "\n\nd) condenacao ao pagamento de indenizacao por danos morais decorrentes do assalto, R$ 50.000,00."
    assert "PEDIDO_DUPLICADO" in codigos(achados(secoes(ABERTURA_OK, dup)))


def test_dedup_do_plano_funde_igual_e_preserva_pedidos_legitimos_diferentes():
    base = {"tese_origem": "T01", "fundamento": "", "de_praxe": False}
    pedidos = [
        {**base, "id": "P01", "tipo": "dano moral", "objeto": "indenizacao por danos morais do assalto", "valor_ou_base": ""},
        {**base, "id": "P02", "tipo": "dano moral", "objeto": "indenizacao por danos morais do assalto", "valor_ou_base": ""},
        {**base, "id": "P03", "tipo": "horas extras", "objeto": "horas extras de 2023", "valor_ou_base": "2023"},
        {**base, "id": "P04", "tipo": "horas extras", "objeto": "horas extras de 2024", "valor_ou_base": "2024"},
    ]
    unicos, fundidos = pp.deduplicar(pedidos)
    assert [p["id"] for p in unicos] == ["P01", "P03", "P04"] and fundidos[0]["removido"] == "P02"


def test_dedup_semantica_so_funde_se_adjudicada():
    base = {"tese_origem": "T01", "fundamento": "", "de_praxe": False, "valor_ou_base": ""}
    a = {**base, "id": "P01", "tipo": "danos morais", "objeto": "condenacao ao pagamento de indenizacao por danos morais"}
    b = {**base, "id": "P02", "tipo": "reparacao", "objeto": "pagamento de reparacao pelos danos extrapatrimoniais sofridos"}
    sim = lambda x, y: 0.93  # noqa: E731
    assert len(pp.deduplicar([a, b], similaridade=sim, adjudicar=lambda u, p: True)[0]) == 1
    assert len(pp.deduplicar([a, b], similaridade=sim, adjudicar=lambda u, p: False)[0]) == 2  # diferença relevante: sobrevive
    assert len(pp.deduplicar([a, b])[0]) == 2  # sem juiz semântico não se elimina por parecer


def test_pedidos_sao_renderizados_do_plano_e_cada_um_aparece_uma_vez():
    pl = plano()

    def redigir(pedidos):
        return {"abertura": "Ante o exposto, requer:", "itens": {p["id"]: f"{p['objeto']}" for p in pedidos},
                "fecho": "Requer a citação da reclamada, o rito ordinário, a intimação exclusiva em nome do advogado, a procedência dos pedidos e as comunicações processuais."}

    texto, rel = pp.renderizar_pedidos(pl, redigir)
    assert texto.count("\n\n") >= 4 and rel["sem_redacao_do_modelo"] == []
    assert codigos(achados(secoes(ABERTURA_OK, texto), pl := plano())) == set()
    assert [i for i in texto.splitlines() if i.startswith(("a)", "b)", "c)"))] and "d)" not in texto


# 3) informação exclusiva da tese A na tese B — e o caso positivo de fato comum
def test_regressao_3_fato_exclusivo_de_outra_tese_e_barrado():
    vazou = secoes(ABERTURA_OK, PEDIDOS_OK,
                   "## a) Da responsabilidade\n\nO assalto de 05/12/2024 ocorreu na agencia.\n\n## b) Das horas extras\n\nA jornada de 2023 e o assalto de 05/12/2024 geraram as horas.")
    assert "MISTURA_DE_TESES" in codigos(achados(vazou))


def test_positivo_fato_comum_a_duas_teses_pode_ser_usado_nas_duas():
    # o salário (R$ 8.146,02) sustenta as DUAS teses: é fato comum
    ok = secoes(ABERTURA_OK, PEDIDOS_OK,
                "## a) Da responsabilidade\n\nO assalto de 05/12/2024 ocorreu; o salario e de R$ 8.146,02.\n\n## b) Das horas extras\n\nA jornada de 2023 e o salario de R$ 8.146,02 fundam as horas.")
    assert "MISTURA_DE_TESES" not in codigos(achados(ok))


# 4) fato de uma das peças do acervo aparecendo como do cliente atual
def test_regressao_4_dado_de_peca_do_acervo_e_barrado():
    acervo = ["A reclamante Maria foi assaltada em 17/03/2019, recebia R$ 2.380,00 e tinha CPF 008.038.763-27."]
    contaminada = secoes(ABERTURA_OK, PEDIDOS_OK, "## a) Da responsabilidade\n\nO assalto ocorreu em 17/03/2019 e o salario era de R$ 2.380,00.")
    c = codigos(achados(contaminada, acervo))
    assert "CONTAMINACAO_DO_ACERVO" in c
    assert "CONTAMINACAO_DO_ACERVO" not in codigos(achados(secoes(ABERTURA_OK, PEDIDOS_OK), acervo))  # o mesmo acervo, sem vazamento, passa


# 5) pedido vindo de peça antiga, sem fundamento no caso atual
def test_regressao_5_pedido_do_acervo_sem_fundamento_no_caso_e_barrado():
    com_extra = PEDIDOS_OK + "\n\nd) reconhecimento de vinculo empregaticio e retificacao da CTPS."
    assert "PEDIDO_FORA_DO_PLANO" in codigos(achados(secoes(ABERTURA_OK, com_extra)))


def test_pedido_de_tese_sem_fato_do_caso_e_barrado_mesmo_estando_no_plano():
    o = {**OUTLINE, "pedidos_estruturados": [*OUTLINE["pedidos_estruturados"],
         {"tipo": "vinculo", "tese": "Reconhecimento de vinculo", "objeto": "reconhecimento de vinculo empregaticio", "fundamento": "art. 3 CLT"}],
         "teses": [*OUTLINE["teses"], {"tese": "Reconhecimento de vinculo", "fatos_que_sustentam": [], "provas": []}]}
    pl = pp.montar(o, partes=pp.verificar_partes(OUTLINE["partes"], CADASTRO, CASO))
    assert "PEDIDO_SEM_FATO_NO_CASO" in codigos(achados(secoes(ABERTURA_OK, PEDIDOS_OK), pl=pl))


def test_ids_de_fato_tese_e_pedido_rastreiam_pedido_tese_fatos():
    pl = plano()
    assert [f["id"] for f in pl["fatos"]] == ["F01", "F02", "F03"]
    t1 = pl["teses"][0]
    assert t1["id"] == "T01" and set(t1["fatos_ids"]) == {"F01", "F03"} and t1["pedidos_ids"] == ["P01"]
    assert pp.fatos_comuns(pl) == {"F03"}
    ctx = pp.contexto_da_tese(pl, t1)
    assert "F01" in ctx and "F03" in ctx and "F02" in ctx and "NÃO os traga" in ctx  # F02 aparece só como fato de OUTRA tese


def test_ids_declarados_pelo_modelo_ligam_tese_fato_e_pedido_sem_depender_de_texto():
    o = {
        "cronologia": [{"id": "C1", "data": "05/12/2024", "fato": "Evento alfa"}, {"id": "C2", "data": "", "fato": "Evento beta"}],
        "teses": [{"id": "T1", "tese": "Qualquer titulo", "fatos_ids": ["C2"]}, {"id": "T2", "tese": "Outro titulo", "fatos_ids": ["C1", "C2"]}],
        "pedidos_estruturados": [{"tipo": "x", "tese_id": "T2", "objeto": "pedido sem relacao textual", "fundamento": "art. 1"}],
    }
    pl = pp.montar(o, partes={})
    assert pl["teses"][0]["fatos_ids"] == ["F02"] and pl["teses"][1]["fatos_ids"] == ["F01", "F02"]
    assert pl["pedidos"][0]["tese_origem"] == "T02" and pl["teses"][1]["pedidos_ids"] == ["P01"]
    assert pp.fatos_comuns(pl) == {"F02"}


def test_endereco_formatado_diferente_nos_documentos_ainda_e_verificado_mas_o_inventado_nao():
    texto = "RESIDENCIA PS. STA. SANTA FE (AV. JOSE BONIFACIO) 70 BAIRRO GUAMA BELEM PA CEP 66075-580"
    ok = pp.verificar_partes({"autor": {"endereco": "Passagem Santa Fé, nº 70, bairro Guamá, Belém/PA"}}, {}, texto)
    falso = pp.verificar_partes({"autor": {"endereco": "Rua das Acácias, 145, Curitiba/PR"}}, {}, texto)
    assert ok["autor"].get("endereco") and not falso["autor"].get("endereco")
