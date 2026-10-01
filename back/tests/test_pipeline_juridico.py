"""Camada jurídica da geração: issue spotting, base jurídica versionada, gate de citação, cálculos e auditores.

Os números de norma e precedente destes testes são FICTÍCIOS (9xxx): o que se testa é o mecanismo
(vigência, superação, ausência de autoridade), não o conteúdo de nenhuma norma real.
"""

from __future__ import annotations

import re
from datetime import date

from app import documento_final, peticao_skill_arquivos, recuperacao_por_tese
from app import juridico
from app.juridico import auditores, autoridades as aut, calculos, fatos, orquestrador, plano, tabelas, teses

HOJE = date(2026, 10, 15)


# ------------------------------------------------------------------ caso de rescisão com várias teses (sem regra do caso no código)

def _caso_rescisao() -> tuple[dict, list[dict]]:
    plano_est = {
        "partes": {"autor": {"nome": "Trabalhador Exemplo"}, "reu": {"nome": "Restaurante Exemplo Ltda"}},
        "fatos": [
            {"id": "F01", "data": "01/02/2022", "fato": "Admissão como auxiliar de cozinha, salário de R$ 1.980,00", "fonte": "CTPS", "documentos": ["CTPS"]},
            {"id": "F02", "data": "", "fato": "Salários pagos com atraso de cerca de 20 dias nos últimos seis meses", "fonte": "extratos", "documentos": ["extratos"]},
            {"id": "F03", "data": "", "fato": "FGTS sem depósitos desde março de 2024", "fonte": "extrato FGTS", "documentos": ["extrato FGTS"]},
            {"id": "F04", "data": "", "fato": "Jornada das 14h às 23h40, seis dias por semana, sem intervalo", "fonte": "entrevista", "documentos": []},
            {"id": "F05", "data": "", "fato": "Trabalho junto aos fornos e entrada frequente em câmara fria sem EPI", "fonte": "entrevista", "documentos": []},
            {"id": "F06", "data": "", "fato": "Humilhações públicas pelo gerente na frente de clientes", "fonte": "entrevista", "documentos": []},
        ],
        "teses": [], "pedidos": [], "ausencias": [],
        "case_facts": {"PARTIES": {"autor": {}, "reu": {}}, "UNCERTAINTIES": []},
    }
    fontes = [
        {"tipo": "documento", "nome": "CTPS", "texto": "--- página 3 --- Admissão 01/02/2022. Cargo auxiliar de cozinha. Salário R$ 1.980,00"},
        {"tipo": "documento", "nome": "extratos", "texto": "Crédito salário 20/05/2026 R$ 1.980,00; crédito salário 21/04/2026 R$ 1.980,00"},
        {"tipo": "documento", "nome": "extrato FGTS", "texto": "Último depósito 02/2024"},
        {"tipo": "entrevista", "nome": "entrevista", "texto": "Trabalhava das 14h às 23h40 sem intervalo, perto dos fornos e na câmara fria. O gerente me humilhava."},
    ]
    return plano_est, fontes


#: Temas que um caso de rescisão com mora salarial, jornada e ambiente insalubre tem de FAZER CONSIDERAR.
#: Estão no TESTE (expectativa), não no código: o código lê o catálogo da skill.
TEMAS_A_CONSIDERAR = {
    "rescisão indireta": r"rescis[aã]o indireta",
    "mora salarial": r"atraso reiterado de sal[aá]rio|mora salarial",
    "FGTS": r"\bfgts\b",
    "horas extras": r"horas extras",
    "intervalo": r"intervalo intrajornada",
    "adicional noturno": r"adicional noturno",
    "insalubridade/calor/frio": r"insalubridade|calor|frio",
    "danos morais": r"dano moral",
    "multa do art. 477": r"477",
    "seguro-desemprego": r"seguro-desemprego",
    "justiça gratuita": r"justi[cç]a gratuita",
    "atualização monetária": r"corre[cç][aã]o monet[aá]ria|atualiza[cç][aã]o monet[aá]ria",
}


def _catalogo():
    return teses.catalogo_da_skill(peticao_skill_arquivos.textos_do_disco())


def test_catalogo_da_skill_cobre_os_temas_do_caso():
    cat = _catalogo()
    texto = lambda k: f"{k['tema']} {k['descricao']}"  # noqa: E731
    for nome, padrao in TEMAS_A_CONSIDERAR.items():
        assert any(re.search(padrao, texto(k), re.I) for k in cat), f"catálogo da skill não traz «{nome}»"
    assert all(k["arquivo"] for k in cat)
    assert len({k["arquivo"] for k in cat}) > 3, "o catálogo deve vir de vários arquivos de assunto, não de um só"


def _modelo_falso(decisoes_por_padrao: dict[str, dict], *, metade_na_primeira: bool = True):
    """Simula o modelo: decide pelo tema do catálogo listado na instrução. Na 1ª chamada avalia só metade."""
    chamadas = {"n": 0}

    def llm(instrucao: str, entrada: str) -> dict:
        chamadas["n"] += 1
        itens = re.findall(r"(?m)^(K\d+) \| ([^|]+) \|", instrucao)
        if metade_na_primeira and chamadas["n"] == 1:
            itens = itens[: len(itens) // 2]
        saida = []
        for kid, tema in itens:
            d = next((v for p, v in decisoes_por_padrao.items() if re.search(p, tema, re.I)), None)
            saida.append({"catalogo_id": kid, "tese": tema.strip(), **(d or {"decisao": "DESCARTAR", "motivo": "sem fato no caso"})})
        return {"teses": saida, "fatos_extraidos": [
            {"chave": "contrato.salario", "valor": "R$ 1.980,00", "fonte": "CTPS", "categoria": "contrato"},
            {"chave": "contrato.admissao", "valor": "01/02/2022", "fonte": "CTPS", "categoria": "contrato"},
        ]}
    return llm, chamadas


def _decisoes():
    sustenta = lambda *ids: {"fatos_que_suportam": list(ids), "fatos_necessarios": [{"fato": "x", "presente": True, "fato_id": ids[0]}]}  # noqa: E731
    return {
        r"rescis[aã]o indireta": {"decisao": "INCLUIR", "motivo": "mora salarial reiterada", **sustenta("M002"), "pedido": "reconhecimento da rescisão indireta"},
        r"fgts n[aã]o recolhido": {"decisao": "INCLUIR", "motivo": "extrato sem depósitos", **sustenta("M003"),
                                   "pedido": "depósitos de FGTS", "calculo": {"rubrica": "fgts", "parametros": {"base_mensal": 1980, "meses": 26}}},
        r"horas extras habituais": {"decisao": "INCLUIR", "motivo": "jornada alegada", **sustenta("M004"), "pedido": "horas extras",
                                    "calculo": {"rubrica": "horas_extras", "parametros": {"salario": 1980, "horas_mensais": 40, "meses": 24}}},
        r"intervalo intrajornada suprimido": {"decisao": "INCLUIR", "motivo": "sem intervalo", **sustenta("M004"), "pedido": "intervalo suprimido",
                                              "calculo": {"rubrica": "intervalo_intrajornada", "parametros": {"salario": 1980}, "parametros_faltantes": ["minutos suprimidos"]}},
        r"^adicional noturno$": {"decisao": "INCLUIR", "motivo": "jornada até 23h40", "fatos_que_suportam": ["M004"],
                                 "fatos_necessarios": [{"fato": "horas noturnas habituais registradas", "presente": False, "fato_id": None}]},
        r"adicional de insalubridade": {"decisao": "INCLUIR", "motivo": "calor e frio", "fatos_que_suportam": ["M005"],
                                        "fatos_necessarios": [{"fato": "exposição a agente", "presente": True, "fato_id": "M005"}],
                                        "prova": ["pericial: laudo de insalubridade"], "pedido": "adicional de insalubridade"},
        r"dano moral por outros": {"decisao": "POTENTIAL_ISSUE_NEEDS_CONFIRMATION", "motivo": "só entrevista; confirmar testemunha", "fatos_que_suportam": ["M006"]},
        r"multa do art\. 477": {"decisao": "POTENTIAL_ISSUE_NEEDS_CONFIRMATION", "motivo": "depende da data da rescisão"},
        r"seguro-desemprego": {"decisao": "INCLUIR", "motivo": "consequência da rescisão indireta", **sustenta("M002"), "pedido": "guias"},
        r"justi[cç]a gratuita": {"decisao": "INCLUIR", "motivo": "hipossuficiência declarada", **sustenta("M001"), "pedido": "gratuidade"},
        r"corre[cç][aã]o monet": {"decisao": "INCLUIR", "motivo": "de praxe", **sustenta("M001"), "pedido": "juros e correção"},
    }


def test_issue_spotting_considera_todas_as_teses_sem_obrigar_inclusao():
    plano_est, fontes = _caso_rescisao()
    llm, chamadas = _modelo_falso(_decisoes())
    prep = orquestrador.preparar(plano_est=plano_est, contexto_caso="material do caso", fontes=fontes, llm=llm,
                                 textos_skill=peticao_skill_arquivos.textos_do_disco(), data_referencia=HOJE)
    issues = prep["issues"]
    assert chamadas["n"] == 2 and issues.get("repescagem"), "itens não avaliados na 1ª passada devem ser repescados"
    assert not issues["nao_avaliados"], "toda tese do catálogo tem de ser avaliada"
    consideradas = " | ".join(f"{t['tese']}" for t in issues["teses"])
    for nome, padrao in TEMAS_A_CONSIDERAR.items():
        if nome == "mora salarial":
            continue  # é fato da rescisão indireta (descrição da subtese), não item próprio do catálogo
        assert re.search(padrao, consideradas, re.I), f"issue spotting não considerou «{nome}»"
    por_tema = {t["tese"].lower(): t for t in issues["teses"]}
    noturno = next(t for k, t in por_tema.items() if k == "adicional noturno")
    assert noturno["decisao"] == teses.POTENCIAL and "horas noturnas" in noturno["rebaixada_por"]
    insal = next(t for k, t in por_tema.items() if k.startswith("adicional de insalubridade"))
    assert insal["exige_pericia"]
    assert any(t["decisao"] == teses.REJEITADA_SEM_FATO and t["motivo"] for t in issues["teses"])


# ------------------------------------------------------------------ 1. lei antiga não substitui a vigente

def _registro_versionado() -> aut.Registro:
    return aut.Registro([
        aut.Autoridade(id="ndv:1", tipo="artigo", chave="art:clt:9001", texto="redação antiga", norma="clt", artigo="9001",
                       vigencia_inicio="1943-11-10", vigencia_fim="2017-11-11", status="revogado", verificada=True, versao="1"),
        aut.Autoridade(id="ndv:2", tipo="artigo", chave="art:clt:9001", texto="redação atual", norma="clt", artigo="9001",
                       vigencia_inicio="2017-11-11", verificada=True, versao="2"),
        aut.Autoridade(id="tst:tema:9002", tipo="tema", chave="tema:tst:9002", titulo="Tema 9002 do TST", tribunal="TST", orgao="Pleno",
                       tese="critério antigo de concessão", vigencia_inicio="2024-01-01", vigencia_fim="2026-09-20", status="superado",
                       superado_por="stf:adc:9003", marcadores=["critério percentual antigo do teto"], verificada=True),
        aut.Autoridade(id="stf:adc:9003", tipo="controle_concentrado", chave="adc:stf:9003", titulo="ADC 9003", tribunal="STF", classe="ADC",
                       numero="9003", tese="critério novo", vigencia_inicio="2026-09-20", vinculante=True, verificada=True),
    ])


def test_lei_antiga_nao_substitui_a_vigente_e_precedente_superado_e_detectado():
    reg = _registro_versionado()
    cit = aut.extrair_citacoes("nos termos do art. 9001 da CLT")[0]
    assert reg.resolver(cit, HOJE)["authority_id"] == "ndv:2"
    assert reg.resolver(cit, date(2015, 1, 1))["authority_id"] == "ndv:1"
    superado = aut.gate("conforme o Tema 9002 do TST", reg, HOJE)[0]
    assert superado["status"] == aut.SUPERADA and superado["superado_por"] == "stf:adc:9003" and not superado["aprovada"]
    assert aut.gate("conforme o Tema 9002 do TST", reg, date(2025, 5, 1))[0]["status"] == aut.VALIDADA
    assert aut.criterios_superados("adota-se o critério percentual antigo do teto", reg, HOJE)
    alertas = orquestrador._auditar_skill({"references/x.md": "Use o critério percentual antigo do teto (Tema 9002 do TST)."}, reg, HOJE)  # noqa: SLF001
    assert len(alertas) >= 2 and all("NÃO reproduza" in a for a in alertas)


def test_atualidade_por_tese_traz_a_autoridade_substituta():
    plano_est, fontes = _caso_rescisao()

    def llm(instrucao, entrada):
        kid = re.search(r"(?m)^(K\d+) \| justi", instrucao, re.I)
        return {"teses": [{"catalogo_id": kid[1] if kid else None, "tese": "justiça gratuita", "decisao": "INCLUIR", "motivo": "declaração",
                           "fatos_que_suportam": ["M001"], "fatos_necessarios": [{"fato": "x", "presente": True, "fato_id": "M001"}],
                           "base_legal_a_pesquisar": ["critério de concessão"], "jurisprudencia_a_pesquisar": ["critério antigo de concessão"]}]}
    prep = orquestrador.preparar(plano_est=plano_est, contexto_caso="", fontes=fontes, llm=llm, textos_skill={"SKILL.md": ""},
                                 autoridades_base=_registro_versionado().autoridades, data_referencia=HOJE)
    tese = next(t for t in prep["issues"]["teses"] if t["tese"] == "justiça gratuita")
    ids = [a.id for a in prep["autoridades_por_tese"][tese["id"]]]
    assert "stf:adc:9003" in ids and "tst:tema:9002" not in ids
    assert any("superado" in a and "ADC 9003" in a for a in prep["alertas_juridicos"])


# ------------------------------------------------------------------ 2/3/9. artigo e jurisprudência inexistentes; referência sem authority_id

def test_artigo_e_jurisprudencia_inexistentes_sao_rejeitados():
    reg = _registro_versionado()
    texto = "Art. 9999 da CLT; Súmula nº 9998 do TST; OJ 9997 da SDI-1; processo 0009999-11.2020.5.08.0001."
    resultado = aut.gate(texto, reg, HOJE)
    assert len(resultado) == 4
    assert all(r["status"] == aut.REQUIRES_LEGAL_RESEARCH and r["authority_id"] is None for r in resultado)
    legal = auditores.auditar_legal([{"code": "LEGAL_GROUNDS", "content": texto}], reg, HOJE)
    assert auditores.veredito(legal)["auditores"]["LEGAL"]["status"] == "FAIL"


def test_nenhuma_referencia_legal_aprovada_sem_authority_id():
    reg = _registro_versionado()
    texto = "Pelo art. 9001 da CLT e pela ADC 9003, e ainda pela Súmula 9998 do TST."
    legal = auditores.auditar_legal([{"code": "LEGAL_GROUNDS", "content": texto}], reg, HOJE)
    assert {c["authority_id"] for c in legal["citacoes"] if c["aprovada"]} == {"ndv:2", "stf:adc:9003"}
    assert all(c["authority_id"] for c in legal["citacoes"] if c["aprovada"])
    assert legal["authority_ids"] == ["ndv:2", "stf:adc:9003"]
    assert any(a["codigo"] == aut.REQUIRES_LEGAL_RESEARCH for a in legal["achados"])
    pendente = auditores.auditar_legal([{"code": "LEGAL_GROUNDS", "content": "[REQUIRES_LEGAL_RESEARCH: critério de concessão]"}], reg, HOJE)
    assert auditores.veredito(pendente)["pronta"] is False


# ------------------------------------------------------------------ 4. fato sem fonte não vira verdade

def test_fato_sem_fonte_nao_e_apresentado_como_verdadeiro():
    plano_est, fontes = _caso_rescisao()
    m = fatos.montar(plano_est, fontes=fontes, fatos_extraidos=[
        {"chave": "contrato.salario", "valor": "R$ 1.980,00", "fonte": "CTPS"},
        {"chave": "pagamento.gratificacao", "valor": "R$ 7.777,00", "fonte": "contracheque"},
    ])
    por = {f["chave"]: f for f in m["fatos"] if f["chave"]}
    assert por["contrato.salario"]["estado"] == fatos.CONFIRMADO and por["contrato.salario"]["pagina"] == "3"
    assert por["pagamento.gratificacao"]["estado"] == fatos.INFERIDO
    assert next(f for f in m["fatos"] if f["ref"] == "F04")["estado"] == fatos.ALEGADO
    secoes = [{"code": "FACTS", "content": "Recebia R$ 1.980,00 e gratificação de R$ 7.777,00, além de R$ 4.321,00 por fora."}]
    achados = auditores.auditar_fatos(secoes, m)["achados"]
    codigos = {(a["codigo"], a["trecho"]) for a in achados}
    assert ("FATO_INFERIDO_AFIRMADO", "R$ 7.777,00") in codigos
    assert ("FATO_SEM_FONTE", "R$ 4.321,00") in codigos
    assert not any(a["trecho"] == "R$ 1.980,00" for a in achados)


# ------------------------------------------------------------------ 5. contradição entre fontes gera alerta

def test_contradicao_entre_fontes_gera_alerta():
    plano_est, fontes = _caso_rescisao()
    fontes.append({"tipo": "documento", "nome": "TRCT", "texto": "Salário base R$ 2.150,00"})
    m = fatos.montar(plano_est, fontes=fontes, fatos_extraidos=[
        {"chave": "contrato.salario", "valor": "R$ 1.980,00", "fonte": "CTPS"},
        {"chave": "contrato.salario", "valor": "R$ 2.150,00", "fonte": "TRCT"},
    ])
    assert [c["chave"] for c in m["contradicoes"]] == ["contrato.salario"]
    assert fatos.por_chave(m, "contrato.salario") is None, "valor contraditório não pode ser usado"
    _, pendencias = plano.integrar(plano_est, {"teses": []}, [], m)
    assert any("Contradição em contrato.salario" in p for p in pendencias)
    secoes = [{"code": "FACTS", "content": "Salário de R$ 2.150,00."}]
    assert any(a["codigo"] == "FATO_CONTRADITORIO_USADO" for a in auditores.auditar_fatos(secoes, m)["achados"])
    cons = auditores.auditar_consistencia(secoes, issues={"teses": []}, plano_est=plano_est, pendencias=[], matriz=m)
    assert any(a["codigo"] == "CONTRADICAO_NAO_EXPOSTA" for a in cons["achados"])


# ------------------------------------------------------------------ 6. soma dos pedidos = valor da causa

def test_soma_dos_pedidos_igual_ao_valor_da_causa():
    pedidos = [{"id": "P01", "valor": 3600.0}, {"id": "P02", "valor": 1234.56},
               {"id": "P03", "valor": 999.0, "natureza": "subsidiario"}, {"id": "P04", "valor": None}]
    vc = calculos.valor_da_causa(pedidos)
    assert vc["valor"] == 4834.56 and vc["pedidos_somados"] == ["P01", "P02"] and vc["pedidos_fora_da_soma"] == ["P03"]
    ok = [{"code": "CLAIMS", "content": "a) R$ 3.600,00; b) R$ 1.234,56; c) subsidiariamente R$ 999,00"},
          {"code": "VALUE", "content": "Dá-se à causa o valor de R$ 4.834,56."}]
    assert auditores.auditar_calculos(ok, pedidos, [])["achados"] == []
    dois = [ok[0], {"code": "VALUE", "content": "Valor da causa R$ 4.834,56."}, {"code": "CLOSING", "content": "valor da causa de R$ 5.000,00"}]
    assert any(a["codigo"] == "VALOR_DA_CAUSA_DIVERGENTE" for a in auditores.auditar_calculos(dois, pedidos, [])["achados"])
    errado = [ok[0], {"code": "VALUE", "content": "Valor da causa R$ 9.000,00."}]
    assert any(a["codigo"] == "VALOR_DA_CAUSA_DIFERENTE_DA_SOMA" for a in auditores.auditar_calculos(errado, pedidos, [])["achados"])
    inventado = [{"code": "CLAIMS", "content": "a) R$ 3.600,00; b) R$ 1.234,56; d) R$ 555,55"}]
    assert any(a["codigo"] == "VALOR_SEM_CALCULO" for a in auditores.auditar_calculos(inventado, pedidos, [])["achados"])


def test_valor_da_causa_do_ledger_nao_e_inflado_pelas_bases_do_calculo():
    secoes = [{"code": "CLAIMS", "content": "a) horas extras: valor-hora R$ 10,00 × 1,5 × 240 h = R$ 3.600,00;"},
              {"code": "VALUE", "content": "Dá-se à causa o valor de R$ 1,00."}]
    rel = {"valores_alinhados": 0}
    legado = documento_final._alinhar_valor_da_causa(secoes, dict(rel))  # noqa: SLF001
    assert "3.610,00" in legado[1]["content"], "comportamento legado (soma todo R$) preservado sem a camada jurídica"
    novo = documento_final._alinhar_valor_da_causa(secoes, dict(rel), 3600.0)  # noqa: SLF001
    assert "3.600,00" in novo[1]["content"]


# ------------------------------------------------------------------ 7. tese do issue spotting não some em silêncio

def _issues(*teses_):
    return {"teses": list(teses_), "nao_avaliados": []}


def _tese(id_, nome, decisao, **extra):
    base = {"id": id_, "tese": nome, "decisao": decisao, "motivo": "m", "rebaixada_por": "", "fatos_que_suportam": [], "fatos_faltantes": [],
            "prova": [], "exige_pericia": False, "pedido": "", "reflexos": [], "base_legal_a_pesquisar": [], "jurisprudencia_a_pesquisar": [],
            "calculo": {"rubrica": None, "parametros": {}, "parametros_faltantes": []}}
    return {**base, **extra}


def test_tese_do_issue_spotting_nao_desaparece_em_silencio():
    m = {"fatos": [], "contradicoes": []}
    iss = _issues(_tese("I01", "Horas extras habituais", teses.INCLUIR), _tese("I02", "Adicional noturno", teses.POTENCIAL))
    secoes = [{"code": "LEGAL_GROUNDS", "content": "Da rescisão indireta."}]
    achados = auditores.auditar_consistencia(secoes, issues=iss, plano_est={"pedidos": []}, pendencias=[], matriz=m)["achados"]
    assert {a["codigo"] for a in achados} >= {"TESE_SUMIU", "TESE_SUMIU_SEM_REGISTRO"}
    plano_novo, pendencias = plano.integrar({"teses": [], "pedidos": []}, iss, [], m)
    secoes_ok = [{"code": "LEGAL_GROUNDS", "content": "Das horas extras habituais prestadas."}]
    assert auditores.auditar_consistencia(secoes_ok, issues=iss, plano_est=plano_novo, pendencias=pendencias, matriz=m)["achados"] == []


def test_tese_incluida_com_calculo_pendente_vai_para_pendencias_e_bloqueia():
    m = {"fatos": [], "contradicoes": []}
    t = _tese("I01", "Intervalo intrajornada suprimido", teses.INCLUIR, pedido="intervalo",
              calculo={"rubrica": "intervalo_intrajornada", "parametros": {"salario": 1980}, "parametros_faltantes": ["minutos suprimidos"]})
    calc = calculos.executar([{"rubrica": "intervalo_intrajornada", "parametros": {"salario": 1980}, "tese_id": "I01"}])
    plano_novo, pend = plano.integrar({"teses": [], "pedidos": []}, _issues(t), [c.como_dict() for c in calc], m)
    assert any("Calcular antes do protocolo: Intervalo" in p for p in pend) and not plano_novo["pedidos"]
    achados = auditores.auditar_consistencia([], issues=_issues(t), plano_est=plano_novo, pendencias=pend, matriz=m)["achados"]
    assert [a["codigo"] for a in achados] == ["TESE_PENDENTE_DE_CALCULO"]


# ------------------------------------------------------------------ 8. fato que exige perícia gera pedido de prova

def test_fato_que_exige_pericia_gera_pedido_de_prova():
    m = {"fatos": [], "contradicoes": []}
    iss = _issues(_tese("I01", "Adicional de insalubridade", teses.INCLUIR, exige_pericia=True))
    sem = [{"code": "LEGAL_GROUNDS", "content": "Do adicional de insalubridade devido."}]
    assert any(a["codigo"] == "PERICIA_NAO_REQUERIDA" for a in auditores.auditar_consistencia(sem, issues=iss, plano_est={}, pendencias=[], matriz=m)["achados"])
    com = sem + [{"code": "CLAIMS", "content": "Requer a produção de prova pericial no local de trabalho."}]
    assert auditores.auditar_consistencia(com, issues=iss, plano_est={}, pendencias=[], matriz=m)["achados"] == []
    normalizado = teses.normalizar({"teses": [{"tese": "Insalubridade", "decisao": "POTENTIAL_ISSUE_NEEDS_CONFIRMATION", "motivo": "m", "prova": ["pericial: laudo"]}]}, [], m)
    assert normalizado["teses"][0]["exige_pericia"]


# ------------------------------------------------------------------ cálculos determinísticos

def test_calculos_deterministicos():
    c = calculos.calcular
    assert c("aviso_previo", {"salario": 3000, "admissao": "01/02/2019", "dispensa": "10/03/2025"}).valor == 4800.0
    assert calculos.avos_entre("01/02/2024", "20/11/2024") == 10
    assert c("decimo_terceiro", {"salario": 1200, "avos": 5}).valor == 500.0
    assert c("ferias", {"salario": 1200, "avos": 6, "periodos_vencidos": 1}).valor == 2400.0
    assert c("horas_extras", {"salario": 2200, "horas_mensais": 20, "meses": 12}).valor == 3600.0
    assert c("intervalo_intrajornada", {"salario": 2200, "minutos_suprimidos_dia": 30, "dias_por_mes": 22, "meses": 10}).valor == 1650.0
    assert c("adicional_noturno", {"salario": 2200, "horas_noturnas_mensais": 35, "meses": 1}).valor == 80.0
    assert c("fgts", {"base_mensal": 2000, "meses": 10, "ja_depositado": 400}).valor == 1200.0
    assert c("multa_fgts", {"saldo_fgts": 5000}).valor == 2000.0
    assert c("honorarios", {"base": 10000, "percentual": 0.15}).valor == 1500.0
    assert c("dsr_reflexo", {"valor_variavel_total": 2500, "dias_uteis": 25, "dias_descanso": 5}).valor == 500.0
    he = c("horas_extras", {"salario": 2200, "horas_mensais": 20, "meses": 12}, parametros_legais={"adicional_hora_extra": 0.7})
    assert he.valor == 4080.0 and he.parametros_legais["adicional_hora_extra"]["origem"] == "informado"
    assert c("horas_extras", {"salario": 2200}).erro and c("rubrica_inexistente", {}).erro


# ------------------------------------------------------------------ entrada priorizada, tabelas, flag, hardcode

def test_entrada_da_redacao_nunca_corta_o_plano():
    plano_txt = "=== PETITION_PLAN ===\n" + "x" * 5000
    entrada, corte = orquestrador.montar_entrada(plano_txt, "c" * 200_000, limite=50_000)
    assert entrada.startswith(plano_txt) and len(entrada) <= 50_000 and corte["caso_cortado"] > 0


def test_decisao_de_tabelas():
    m = {"fatos": [{"chave": "jornada.entrada", "valor": "14h"}, {"chave": "jornada.saida", "valor": "23h40"},
                   {"chave": "contrato.salario", "valor": "R$ 1,00", "documento": "CTPS"}, {"data": "01/01/2024"}]}
    d = tabelas.decidir(m, [{"valor": 10.0, "erro": ""}])
    assert d["jornada"]["decisao"] == "USE_TABLE" and d["memoria_de_calculo"]["decisao"] == "USE_TABLE"
    assert d["contrato"]["decisao"] == "NO_TABLE"
    assert tabelas.decidir(m, [], {"contrato": True})["contrato"]["decisao"] == "USE_TABLE"


def test_camada_desligada_por_padrao_e_sem_consulta_fixa(monkeypatch):
    monkeypatch.delenv("PETICAO_PIPELINE_JURIDICO", raising=False)
    monkeypatch.delenv("PETICAO_PIPELINE_JURIDICO_MODE", raising=False)
    assert juridico.ativo() is False and juridico.modo() == juridico.DESLIGADO
    monkeypatch.setenv("PETICAO_PIPELINE_JURIDICO", "1")
    assert juridico.ativo() is True and juridico.estrito()
    monkeypatch.setenv("PETICAO_PIPELINE_JURIDICO_MODE", "shadow")
    assert juridico.sombra() and not juridico.estrito()
    monkeypatch.setenv("PETICAO_PIPELINE_JURIDICO_MODE", "qualquer-coisa")
    monkeypatch.delenv("PETICAO_PIPELINE_JURIDICO")
    assert juridico.modo() == juridico.DESLIGADO
    plano_ = {"teses": [{"tese": "responsabilidade objetiva"}]}
    legado = recuperacao_por_tese.consultas_do_plano(plano_, "assalto na agência", "acidente")
    novo = recuperacao_por_tese.consultas_do_plano(plano_, "assalto na agência", "acidente", consulta_fixa_legada=False)
    assert len(legado) == len(novo) + 1


def test_extracao_de_citacoes_reconhece_as_formas_usuais():
    chaves = [c.chave for c in aut.extrair_citacoes(
        "art. 477, § 8º, da CLT; Súmula nº 338, III, do TST; OJ 394 da SDI-1; Tema 1046 do STF; ADC 58; "
        "art. 7º, XXIX, da CF/88; Súmula Vinculante 4; 0000123-45.2019.5.08.0001; artigo 71, §4º, da CLT")]
    assert chaves == ["art:clt:477", "sumula:tst:338", "oj:sdi1:394", "tema:stf:1046", "adc:stf:58", "art:cf:7",
                      "sv:stf:4", "processo:00001234520195080001", "art:clt:71"]
