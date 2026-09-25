"""Regressões REAIS da v11 — cada bug que chegou ao PDF tem de ser pego pelo validador FINAL (ou impedido antes).

Fixtures abstratas: reproduzem a estrutura dos defeitos, não o texto do caso.
"""

import io
import re
import zipfile

from app import auditoria_estrutural as ae
from app import document_ledger as dl
from app import documento_final as df
from app import peticao_local as pl
from app import peticao_skill_arquivos as skill
from app import plano_da_peticao as pp

PARAMS = skill.validacoes_da_skill()["parametros"]
PARTES = {"autor": {"nome": "Fulano de Tal", "cpf": "123.456.789-09", "rg": "1234567", "endereco": "Rua A 10 Cidade UF"},
          "reu": {"nome": "Empresa Ré SA", "cnpj": "11.222.333/0001-44"}}


def plano(pedidos=None, ausencias=None):
    return {"partes": PARTES, "fatos": [], "teses": [], "pedidos": pedidos or [], "ausencias": ausencias or [], "case_facts": {}}


def cods(achados, so_bloqueantes=True):
    return {a.codigo for a in achados if a.bloqueia or not so_bloqueantes}


# TESTE 1 — heading duplicado ("VI. Dos Pedidos" rótulo + "III. Dos Pedidos" no texto)
def test_1_heading_duplicado_e_barrado_no_validador_final_e_higienizado():
    secoes = [{"code": "LEGAL_GROUNDS", "label": "V. Do Direito", "content": "Texto do direito."},
              {"code": "CLAIMS", "label": "VI. Dos Pedidos", "content": "III. Dos Pedidos\nAnte o exposto, requer:\n\na) o pedido um;"}]
    achados = df.validar_documento_final(secoes, plano(), PARAMS)
    assert "HEADING_DUPLICADO" in cods(achados)
    limpas, rel = df.higienizar(secoes, plano(), PARAMS)
    assert rel["titulos_repetidos_removidos"] == 1
    final = df.representacao_final(limpas)
    texto = "\n".join(s["content"] for s in final)
    assert texto.count("Dos Pedidos") == 1 and "Ante o exposto" in texto
    assert "HEADING_DUPLICADO" not in cods(df.validar_documento_final(limpas, plano(), PARAMS))


def test_1b_numeracao_e_estrutural_nao_do_modelo():
    secoes = [{"code": "A", "label": "I. Dos Fatos", "content": "x"}, {"code": "B", "label": "III. Do Direito", "content": "y"},
              {"code": "C", "label": "III. Dos Pedidos", "content": "z"}]
    assert "NUMERACAO_DE_SECOES" in cods(df.validar_documento_final(secoes, plano(), PARAMS))
    limpas, _ = df.higienizar(secoes, plano(), PARAMS)
    assert [s["label"] for s in limpas] == ["I. Dos Fatos", "II. Do Direito", "III. Dos Pedidos"]
    assert not cods(df.validar_documento_final(limpas, plano(), PARAMS)) & {"NUMERACAO_DE_SECOES", "HEADING_DUPLICADO"}


# TESTE 2 — o mesmo número designa dois documentos
def test_2_mesmo_identificador_para_dois_documentos_falha():
    docs = [{"arquivo": f"Doc {i}.pdf", "texto": f"conteudo distinto numero {i} " * 30} for i in range(1, 14)]
    docs += [{"arquivo": "Contracheque 2026-06.pdf", "texto": "contracheque junho salario bruto " * 30},
             {"arquivo": "BO 2024-12-05.pdf", "texto": "boletim de ocorrencia policial roubo " * 30}]
    ledger = dl.montar(docs, {"Contracheque 2026-06.pdf": "Contracheque", "BO 2024-12-05.pdf": "Boletim de Ocorrência"})
    assert ledger[13]["canonical_label"] == "Documento 14" and ledger[14]["canonical_label"] == "Documento 15"
    sec = [{"code": "FACTS", "content": "O roubo foi registrado (Documento 15 — Boletim de Ocorrência). O salário consta dos Documentos 13-15 — Contracheques."}]
    achados = dl.validar_referencias(sec, ledger)
    assert "REFERENCIA_DOCUMENTAL_CONFLITANTE" in cods(achados)
    assert not dl.validar_referencias([{"code": "FACTS", "content": "O roubo foi registrado (Documento 15 — Boletim de Ocorrência)."}], ledger)


def test_2b_numero_inexistente_falha_e_bijecao_do_ledger():
    ledger = dl.montar([{"arquivo": "a.pdf", "texto": "aaa " * 50}, {"arquivo": "b.pdf", "texto": "bbb " * 50}])
    assert not dl.validar_bijecao(ledger)
    assert "DOCUMENTO_INEXISTENTE_NO_LEDGER" in cods(dl.validar_referencias([{"code": "X", "content": "ver Documento 07"}], ledger))


# TESTE 3 — duplicata física → um documento lógico, um rótulo
def test_3_uploads_da_mesma_lisa_viram_um_documento_logico():
    lisa = "LEVANTAMENTO INTERNO SOBRE ACIDENTES LISA 54233677 descricao do evento " * 20
    docs = [{"arquivo": "Doc 9. LISA 2024-12-05.pdf", "texto": lisa}, {"arquivo": "Doc 10. CAT.pdf", "texto": "CAT comunicacao acidente " * 20},
            {"arquivo": "Doc 9. LISA 2024-12-05 (Duplicado).pdf", "texto": lisa + " "}]
    ledger = dl.montar(docs)
    assert len(ledger) == 2 and ledger[0]["source_files"] == ["Doc 9. LISA 2024-12-05.pdf", "Doc 9. LISA 2024-12-05 (Duplicado).pdf"]
    # o número canônico é o "Doc N." do arquivo (a numeração da pasta de protocolo que o advogado vê)
    assert ledger[0]["canonical_label"] == "Documento 09" and ledger[1]["canonical_label"] == "Documento 10"
    assert "mesmo documento enviado também como" in dl.aviso_de_copias(ledger)


def test_3b_contexto_da_peca_usa_so_rotulos_canonicos(monkeypatch):
    lisa = "LISA 54233677 " * 40
    monkeypatch.setattr(pl, "documentos_ocr", lambda c: [{"arquivo": "LISA.pdf", "texto": lisa}, {"arquivo": "LISA (Duplicado).pdf", "texto": lisa},
                                                          {"arquivo": "CAT.pdf", "texto": "CAT " * 40}])
    monkeypatch.setattr(pl, "_dados_por_documento", lambda c: {})
    ledger, docs = pl.documentos_logicos("c1")
    assert [d["rotulo"] for d in docs] == ["Documento 01", "Documento 02"] and docs[1]["arquivo"] == "CAT.pdf"


# TESTE 4 — ausência documental
def test_4_ausencia_documental_nao_vira_ausencia_comprovada():
    ruim = "A ausência de vigilância armada e de controle de acesso é, portanto, documentalmente demonstrável, e não mera alegação."
    bom = "Os documentos atualmente disponíveis não registram a existência de vigilância armada nem de controle de acesso na agência."
    assert "AUSENCIA_REDIGIDA_COMO_CONFIRMADA" in cods(df.epistemica([{"code": "LEGAL_GROUNDS", "content": ruim}], PARAMS, plano()))
    assert not df.epistemica([{"code": "LEGAL_GROUNDS", "content": bom}], PARAMS, plano())
    ruim2 = "Está comprovado que não havia vigilância na agência no momento do roubo."
    assert "AUSENCIA_REDIGIDA_COMO_CONFIRMADA" in cods(df.epistemica([{"code": "FACTS", "content": ruim2}], PARAMS, plano()))


# TESTE 5 — afirma X categoricamente e pede prova para descobrir X
def test_5_afirmacao_categorica_x_prova_requerida():
    sec = [{"code": "LEGAL_GROUNDS", "content": "A ausência de vigilância armada e de protocolos de segurança está documentalmente demonstrada, não sendo mera alegação."},
           {"code": "CLAIMS", "content": "b) a exibição, pela reclamada, dos documentos sobre vigilância armada e protocolos de segurança da agência, para esclarecer as medidas adotadas."}]
    assert "AFIRMACAO_CATEGORICA_X_PROVA_REQUERIDA" in cods(df.epistemica(sec, PARAMS, plano()))
    ok = [{"code": "LEGAL_GROUNDS", "content": "Os documentos disponíveis não registram vigilância armada nem protocolos de segurança na agência."}, sec[1]]
    assert not df.epistemica(ok, PARAMS, plano())


# TESTE 6 — agravante não vira segundo pedido econômico
def _p(id_, tipo, objeto, valor=None, tipo_de_item="autonomo", agrava="", **extra):
    base = {"id": id_, "tipo": tipo, "objeto": objeto, "fundamento": "f", "valor_ou_base": "", "de_praxe": False, "tese_origem": "T01",
            "causa_de_pedir": "", "natureza": "cumulativo", "valor": valor, "metodo_calculo": {}, "dependencias": [],
            "tipo_de_item": tipo_de_item, "agrava": agrava}
    base.update(extra)
    return base


def test_6_majoracao_por_consequencia_do_mesmo_evento_nao_e_segunda_indenizacao():
    a = _p("P01", "dano moral", "indenização por dano moral decorrente do evento X", 16698.0)
    b = _p("P02", "majoração do dano moral", "majoração da indenização por dano moral em razão da consequência Y decorrente do mesmo evento X", 7590.0)
    assert "MAJORACAO_COMO_SEGUNDA_INDENIZACAO" in cods(ae.ledger(plano([a, b])))
    # como AGRAVANTE: não soma, não vira alínea, alimenta a quantificação do principal
    b2 = _p("P02", "agravamento", "adoecimento que aumenta a extensão do dano", None, "agravante", "dano moral")
    pl_ok = pp.montar({"pedidos_estruturados": []}, partes=PARTES)
    pl_ok["pedidos"] = [a, b2]
    b2["agrava_id"] = "P01"
    assert not cods(ae.ledger(pl_ok)) and ae.soma_cumulativos(pl_ok) == 16698.0
    vistos = []
    texto, rel = pp.renderizar_pedidos(pl_ok, lambda ps: vistos.extend(ps) or {"itens": {p["id"]: p["objeto"] for p in ps}})
    assert [p["id"] for p in vistos] == ["P01"] and vistos[0]["fatores_de_quantificacao"] == ["adoecimento que aumenta a extensão do dano"]
    assert "b)" not in texto
    # agravante com valor próprio continua bloqueado
    b3 = dict(b2, valor=7590.0)
    assert "AGRAVANTE_COM_VALOR_PROPRIO" in cods(ae.ledger(plano([a, b3])))
    # e no TEXTO final (o que o PDF mostra)
    claims = "c) indenização por dano moral decorrente do evento X, no valor de R$ 16.698,00;\n\nd) a majoração da indenização por dano moral em razão da consequência Y, no valor de R$ 7.590,00;"
    assert "MAJORACAO_COMO_SEGUNDA_INDENIZACAO" in cods(df.pedidos_no_texto([{"code": "CLAIMS", "content": claims}]))


def test_6b_mesma_reparacao_por_bem_juridico_evento_e_objeto_mesmo_com_texto_diferente():
    a = _p("P01", "reparação", "compensação pecuniária", 10000.0, bem_juridico="integridade psíquica", evento_causador="evento X", objeto_economico="indenização em dinheiro", dano="abalo psíquico")
    b = _p("P02", "compensação", "valor pelo sofrimento", 5000.0, bem_juridico="integridade psíquica", evento_causador="evento X", objeto_economico="indenização em dinheiro", dano="abalo psíquico agravado")
    assert "MESMA_REPARACAO_DUAS_VEZES" in cods(ae.ledger(plano([a, b])))


# TESTE 7 — danos juridicamente autônomos e fundamentados: preservar ambos
def test_7_danos_autonomos_sao_preservados():
    moral = _p("P01", "dano moral", "indenização por dano moral", 10000.0, bem_juridico="integridade psíquica", evento_causador="evento X", objeto_economico="indenização", dano="sofrimento psíquico")
    estetico = _p("P02", "dano estético", "indenização por dano estético", 8000.0, bem_juridico="integridade física", evento_causador="evento X", objeto_economico="indenização", dano="cicatriz permanente")
    material = _p("P03", "dano material", "ressarcimento de despesas médicas", 1200.0)
    assert not cods(ae.ledger(plano([moral, estetico, material])))
    assert ae.soma_cumulativos(plano([moral, estetico, material])) == 19200.0


# TESTE 8 — título da ação duas vezes
def test_8_titulo_da_acao_fica_uma_vez_apos_propor_a_presente():
    abertura = ("::: titulo_acao\nRECLAMAÇÃO TRABALHISTA\n(INDENIZAÇÃO POR DANOS MORAIS — EVENTO)\n:::\n\n"
                "**FULANO DE TAL**, brasileiro, CPF 123.456.789-09, RG 1234567, residente na Rua A 10 Cidade UF, vem propor a presente\n\n"
                "**RECLAMAÇÃO TRABALHISTA**\n**(Indenização por Danos Morais)**\n\nem face de **EMPRESA RÉ SA**.")
    sec = [{"code": "HEADING", "label": "", "content": abertura}]
    assert "TITULO_DA_ACAO_DUPLICADO" in cods(df.validar_documento_final(sec, plano(), PARAMS))
    limpas, _ = df.higienizar(sec, plano(), PARAMS)
    t = limpas[0]["content"]
    assert t.count("RECLAMAÇÃO TRABALHISTA") == 1 and re.search(r"propor a presente\s+\*\*RECLAMAÇÃO TRABALHISTA", t)
    assert "TITULO_DA_ACAO_DUPLICADO" not in cods(df.validar_documento_final(limpas, plano(), PARAMS))


# TESTE 9 — metadata interna
def test_9_alteracoes_realizadas_nunca_chega_ao_documento():
    sec = [{"code": "CLAIMS", "label": "", "content": "a) pedido;"},
           {"code": "CLOSING", "label": "", "content": "Termos em que, pede deferimento.\n\nALTERAÇÕES REALIZADAS\n\nFormatação: A4.\n\nOrganização: x.\n\nInclusões: y.\n\nExclusões: z."}]
    assert "METADATA_INTERNA_NO_DOCUMENTO" in cods(df.validar_documento_final(sec, plano(), PARAMS))
    limpas, rel = df.higienizar(sec, plano(), PARAMS)
    assert "ALTERAÇÕES" not in "\n".join(s["content"] for s in limpas) and rel["metadata_interna_removida"]
    # a seção inteira com esse título também sai; e o RENDERER não imprime metadado nem de peça antiga/editada à mão
    so_meta = [{"code": "X", "label": "Alterações Realizadas", "content": "Formatação: A4."}]
    assert df.higienizar(so_meta, plano(), PARAMS)[0] in ([], so_meta) and not df._cortar_metadata(so_meta, PARAMS)[0]  # noqa: SLF001
    docx = pl.montar_docx(sec)
    with zipfile.ZipFile(io.BytesIO(docx)) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert "ALTERAÇÕES REALIZADAS" not in xml and "Termos em que" in xml


def test_9b_rotulos_de_relatorio_sem_titulo_tambem_saem():
    sec = [{"code": "CLOSING", "label": "", "content": "Pede deferimento.\n\nFormatação: Peça formatada.\nOrganização: reorganizada.\nAjustes jurídicos: inclusão.\nExclusões: nada."}]
    limpas, rel = df.higienizar(sec, plano(), PARAMS)
    assert limpas[0]["content"].strip() == "Pede deferimento." and rel["metadata_interna_removida"]


# TESTE 10 — o validador final roda sobre o que o RENDERER imprime (rótulo + conteúdo)
def test_10_heading_reintroduzido_pela_combinacao_rotulo_mais_conteudo_e_pego_no_final():
    # rascunho "correto" por seção: cada uma tem um título... mas o renderer imprime o rótulo E o conteúdo abre com outro título
    sec = [{"code": "CLAIMS", "label": "VI. Dos Pedidos", "content": "### III. Dos Pedidos\n\na) pedido;"}]
    final = df.representacao_final(sec)
    assert final[0]["content"].startswith("# VI. Dos Pedidos")
    assert "HEADING_DUPLICADO" in cods(df.validar_documento_final(sec, plano(), PARAMS))


def test_10b_nada_muda_depois_do_validador_final_hash_da_impressao():
    sec = [{"code": "X", "label": "I. A", "content": "texto"}]
    h = df.impressao_hash(sec)
    assert h == df.impressao_hash([dict(sec[0])])
    assert h != df.impressao_hash([{**sec[0], "content": "texto alterado"}])
    assert h != df.impressao_hash([{**sec[0], "label": "I. B"}])  # o rótulo impresso conta


def test_ordem_vem_da_skill_modelo_do_assunto_sem_capitulo_de_provas():
    modelo = skill._ler("assalto_carteiro/modelo_peticao.md")  # noqa: SLF001
    titulos = re.findall(r"^## ([IVX]+)[^.]*\. (.+)$", modelo, re.M)
    assert titulos[-1][1].startswith("Dos Pedidos") and not any("Provas" in t for _, t in titulos)
    assert "Produção de todas as provas" in modelo  # provas é pedido de praxe DENTRO dos pedidos
    assert "EVIDENCE" not in pl.peticao_skill_arquivos.carregar("x", "x", "")  # o motor não impõe seção de provas


def test_orcamento_de_tempo_pula_etapas_opcionais(monkeypatch):
    """Passado o orçamento, as etapas opcionais (aprofundamento, auditor por modelo) são puladas — a geração cabe na espera da tela."""
    import time as _t

    tok = pl._INICIO_DA_GERACAO.set(_t.monotonic() - pl.ORCAMENTO_SUAVE_S - 1)
    try:
        assert pl._sem_tempo()
        chamadas = []
        monkeypatch.setattr(pl, "_reescrever_secao", lambda *a, **k: chamadas.append(1) or "x")
        corpo = "palavra " * 120
        secoes = [{"code": "LEGAL_GROUNDS", "label": "", "content": f"## a) Um\n\n{corpo}"}]
        novas, info = pl._aprofundar_pela_referencia("c", secoes, None, [], contexto="ctx", plano=None, assuntos=[])
        assert not chamadas and novas[0]["content"].split() == secoes[0]["content"].split() and info["por_topico"][0].get("pulado")
    finally:
        pl._INICIO_DA_GERACAO.reset(tok)
    assert not pl._sem_tempo()  # fora de uma geração, nada é pulado


def test_contracheques_de_meses_diferentes_nao_sao_fundidos_e_numero_vem_do_arquivo():
    base = "CORREIOS DEMONSTRATIVO DE PAGAMENTO salario base adicional desconto postalis consignado liquido " * 12
    docs = [{"arquivo": "Doc 13. Contracheque 2026-06.pdf", "texto": base + " junho 2291,41"},
            {"arquivo": "Doc 14. Contracheque 2026-07.pdf", "texto": base + " julho 2289,59"},
            {"arquivo": "Doc 15. Contracheque 2026-08.pdf", "texto": base + " agosto 2472,22"},
            {"arquivo": "Doc 8. BO 2024-12-05.pdf", "texto": "boletim de ocorrencia " * 20}]
    ledger = dl.montar(docs)
    assert [d["canonical_label"] for d in ledger] == ["Documento 08", "Documento 13", "Documento 14", "Documento 15"]
    assert not dl.validar_bijecao(ledger)
