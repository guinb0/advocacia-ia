"""Impedimentos de protocolo apontados na revisão da peça do assalto na AC Jurunas."""
from app import case_facts, documento_final as df, petition_linter as lint, plano_da_peticao as pp


AUTOS = (
    "CAT AC Jurunas Belém/PA CNPJ 34.028.316/4948-66. "
    "Contracheque agosto IR R$ 611,12 contribuição extra R$ 364,99 seguros R$ 574,15 R$ 54,48 R$ 36,71. "
    "Um assaltante entrou na área interna e o outro abordou o autor. "
    "Receita da clínica especializada em dependência química, sem data."
)
PARAMS = {"qualificacao": {}, "estrutura": {}}
PLANO = {"partes": {"autor": {}, "reu": {"cnpj": "34.028.316/4948-66", "endereco": "AC Jurunas, Belém/PA"}},
         "fatos": [], "teses": [], "pedidos": [], "ausencias": []}


def codigos(achados):
    return {a.codigo for a in achados}


def test_cidade_e_cnpj_de_outro_caso_sao_barrados():
    secoes = [{"code": "HEADING", "content": (
        "em face da ECT, CNPJ 34.028.316/8384-68, com sede em Tucuruí/PA."
    )}]
    achados = lint.revisao_de_protocolo(secoes, AUTOS)
    assert "CIDADE_DE_OUTRO_CASO" in codigos(achados)
    assert "CPF_CNPJ_SEM_ORIGEM" in codigos(lint.lintar(
        secoes, PLANO, texto_do_caso="outline com 34.028.316/8384-68 e Tucuruí",
        textos_do_acervo=[], params=PARAMS, texto_dos_autos=AUTOS,
    ))


def test_cadastro_nao_traz_cidade_ausente_dos_documentos():
    assert not pp._valor_consta("endereco", "Rua X, Tucuruí/PA", pp.norm("AC Jurunas Belém/PA"), "")
    cf = case_facts.montar(
        fontes=[{"tipo": "documento", "nome": "CAT.pdf", "texto": "CNPJ 34.028.316/4948-66 Belém/PA"}],
        cadastro={"endereco": "Rua das Flores, Tucuruí/PA", "nome": "Paulo Sergio"},
    )
    assert "endereco" not in cf["PARTIES"]["autor"]
    assert cf["PARTIES"]["autor"]["nome"]["valor"] == "Paulo Sergio"


def test_higiene_troca_cnpj_e_cidade_e_deixa_um_fechamento():
    secoes = [{
        "code": "HEADING",
        "content": (
            "reclamada inscrita no CNPJ 34.028.316/8384-68, com sede em Tucuruí/PA.\n\n"
            "Nestes termos, pede deferimento.\n\n"
            "Dá-se à causa o valor de R$ 1,00.\n\n"
            "Termos em que,\nPede deferimento."
        ),
    }, {
        "code": "LEGAL_GROUNDS",
        "content": "Tema 21 do TST, incidente de resolução de demandas repetitivas, relator Aloysio.",
    }]
    limpas, rel = df.higienizar(secoes, PLANO, {"estrutura": {}, "metadata_interna": {}}, texto_dos_autos=AUTOS)
    abertura = limpas[0]["content"]
    assert "8384-68" not in abertura
    assert "4948-66" in abertura
    assert "Tucuruí" not in abertura
    assert "Belém" in abertura
    assert abertura.lower().count("pede deferimento") == 1
    assert "IRR" in limpas[1]["content"]
    assert "resolução de demandas repetitivas" not in limpas[1]["content"].lower()
    assert rel["fechamentos_duplicados_removidos"] == 1


def test_valores_medico_juros_e_pedidos_de_praxe():
    secoes = [
        {"code": "HEADING", "content": "ECT, Belém/PA, CNPJ 34.028.316/4948-66."},
        {"code": "PRELIMINARY", "content": "Descontos de IR R$ 611,25 e seguro R$ 500,00 no contracheque."},
        {"code": "LEGAL_GROUNDS", "content": (
            "## III.8 Da quantificação\n\n"
            "12 vezes, R$ 97.752,24, mais 8 vezes, R$ 65.168,16, total R$ 162.920,40.\n\n"
            "O Dr. Fernando é médico do trabalho da própria reclamada. "
            "A clínica de psiquiatria confirma a continuidade do tratamento. "
            "A correção incide desde o ajuizamento, art. 883 da CLT. "
            "Tema 21 do TST, Min. Aloysio Corrêa da Veiga."
        )},
        {"code": "CLAIMS", "content": (
            "a) indenização por dano moral de 18 vezes, R$ 146.628,36;\n\n"
            "b) indenização por dano moral agravado pelo TEPT, R$ 48.876,12;\n\n"
            "c) danos materiais [PENDENTE: valor], nos termos do art. 322 do CPC."
        )},
    ]
    c = codigos(lint.revisao_de_protocolo(secoes, AUTOS))
    assert "VALOR_DE_CONTRACHEQUE_SEM_LASTRO" in c
    assert "VALORES_DA_INDENIZACAO_DIVERGENTES" in c
    assert "BIS_IN_IDEM_DANO_MORAL" in c
    assert "MEDICO_ATRIBUIDO_A_RECLAMADA" in c
    assert "RECEITA_ALEM_DO_DOCUMENTO" in c
    assert "JUROS_CITADOS_COMO_CORRECAO" in c
    assert "RELATOR_DO_TEMA_21" in c
    assert "PEDIDO_GENERICO_ART_322" in c
    assert "PEDIDOS_DE_PRAXE_AUSENTES" in c


def test_v16_nao_perde_o_que_v14_e_v15_acertaram():
    """Endereço/CNPJ, comunicações, pedidos, valor único e [PENDENTE] são corrigidos no texto."""
    autos = "CAT: um entrou na área interna e o outro abordou o autor. CNPJ 34.028.316/4948-66 Belém/PA."
    secoes = [
        {"code": "HEADING", "content": "ECT, CNPJ 34.028.316/8384-68, com sede em Tucuruí/PA."},
        {"code": "LEGAL_GROUNDS", "content": "## Da quantificação\n\n12 vezes, R$ 97.752,24, e 8 vezes, R$ 65.168,16, total R$ 162.920,40."},
        {"code": "FACTS", "content": "O assaltante que entrou na área interna foi o que abordou o autor, enquanto o outro rendia colegas."},
        {"code": "CLAIMS", "content": "a) indenização por dano moral de R$ 146.628,36;\n\nb) danos materiais [PENDENTE: valor]."},
        {"code": "VALUE", "content": "Dá-se à causa o valor de R$ 146.628,36."},
    ]
    limpas, rel = df.higienizar(secoes, PLANO, {"estrutura": {}, "metadata_interna": {}}, texto_dos_autos=autos)
    texto = "\n".join(s["content"] for s in limpas)
    assert "8384-68" not in texto and "4948-66" in texto
    assert "Tucuruí" not in texto
    assert "[PENDENTE" not in texto
    assert "comunicações processuais" in texto.lower()
    assert "citação" in texto.lower() and "procedência" in texto.lower()
    assert "162.920,40" in texto
    assert "146.628,36" not in texto
    assert "DINAMICA_INVERTIDA" in codigos(lint.revisao_de_protocolo(secoes, autos))
    assert rel["estabilidade"]["comunicacoes_inseridas"] == 1
