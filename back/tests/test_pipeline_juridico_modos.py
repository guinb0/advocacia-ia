"""Camada jurídica: modos shadow/strict, renderer sem conteúdo jurídico próprio, classificação das teses e provedor de busca.

Números de norma e precedente FICTÍCIOS (9xxx), como em `test_pipeline_juridico`.
"""

from __future__ import annotations

from app import documento_final, peticao_local
from app.juridico import auditores, autoridades as aut, orquestrador, tabelas, teses
from app.juridico.busca import Filtros, ProvedorDeAutoridades

from tests.test_pipeline_juridico import HOJE, _caso_rescisao, _issues, _registro_versionado, _tese

PARAMS = {"estrutura": {}, "metadata_interna": {}}
SECOES_LEGADAS = [
    {"code": "HEADING", "content": "EXCELENTÍSSIMO JUÍZO DA VARA DO TRABALHO"},
    {"code": "IRR", "content": "Conforme o IRDR do TST no Tema 9002, a tese é aplicável."},
    {"code": "CLAIMS", "content": "a) indenização por dano moral de R$ 10.000,00;\nb) indenização por dano moral agravado pelo TEPT de R$ 5.000,00;\n"
                                   "c) adicional de insalubridade [PENDENTE: grau];"},
]


# ------------------------------------------------------------------ renderer: nada jurídico próprio em strict

def test_strict_o_renderer_nao_insere_nem_apaga_conteudo_juridico():
    limpas, rel = documento_final.higienizar([dict(s) for s in SECOES_LEGADAS], {"partes": {}, "_juridico_estrito": True}, PARAMS)
    texto = "\n".join(s["content"] for s in limpas)
    for proibido in ("272", "427", "841", "Requer, ainda", "Recursos de Revista Repetitivos"):
        assert proibido not in texto, f"renderer escreveu «{proibido}» em strict"
    assert "agravado pelo TEPT" in texto, "o segundo pedido de dano moral não pode sumir em silêncio"
    assert "[PENDENTE: grau]" in texto and "adicional de insalubridade" in texto, "pedido sem valor fica visível, não é apagado"
    assert rel["estabilidade"]["modo"] == "strict" and rel["estabilidade"]["placeholders_mantidos"] == 1


def test_legado_continua_igual_sem_strict():
    limpas, rel = documento_final.higienizar([dict(s) for s in SECOES_LEGADAS], {"partes": {}}, PARAMS)
    texto = "\n".join(s["content"] for s in limpas)
    assert "Súmula 427" in texto and "art. 841" in texto and "agravado pelo TEPT" not in texto
    assert rel["estabilidade"]["comunicacoes_inseridas"] == 1


def test_pedidos_obrigatorios_vem_da_skill_e_o_auditor_bloqueia():
    params = {"pedidos_obrigatorios": [{"nome": "citação da reclamada", "padrao": "\\bcita"}, {"nome": "procedência", "padrao": "procedencia"}]}
    secoes = [{"code": "CLAIMS", "content": "Requer a citação da reclamada."}]
    assert documento_final.pedidos_obrigatorios_ausentes(secoes, params) == ["procedência"]
    assert documento_final.pedidos_obrigatorios_ausentes(secoes, {}) == [], "sem declaração na skill, nada é cobrado"
    cons = auditores.auditar_consistencia(secoes, issues=_issues(), plano_est={}, pendencias=[], matriz={"fatos": [], "contradicoes": []},
                                          pedidos_obrigatorios_ausentes=["procedência"])
    assert [a["codigo"] for a in cons["achados"]] == ["PEDIDO_OBRIGATORIO_AUSENTE"]


def test_irdr_junto_a_tese_do_tst_vira_alerta_e_nao_reescrita():
    legal = auditores.auditar_legal([SECOES_LEGADAS[1]], _registro_versionado(), HOJE)
    assert any(a["codigo"] == "INSTITUTO_A_CONFERIR" and a["severidade"] == auditores.ALERTA for a in legal["achados"])


def test_valor_em_coluna_de_contracheque_sem_cifrao_conta_como_fonte():
    secoes = [{"code": "FACTS", "content": "O salário-base era de R$ 2.324,51 e houve desconto de R$ 96,26 e de R$ 7.777,77."}]
    fontes = "PROVENTOS\nSalário base 30,00 2.324,51\nINSS 96,26\nTotal 12.324,51"
    fato = auditores.auditar_fatos(secoes, {"fatos": []}, texto_das_fontes=fontes)
    sem_fonte = [a["trecho"] for a in fato["achados"] if a["codigo"] == "FATO_SEM_FONTE"]
    assert sem_fonte == ["R$ 7.777,77"], sem_fonte


def test_data_de_julgamento_de_precedente_nao_e_fato_do_caso():
    secoes = [{"code": "LEGAL_GROUNDS", "content": "(TST, RR-9001-00.2020.5.09.0001, Rel. Min. Fulano, julgado em 14/10/2029) "
                                                   "O reclamante foi admitido em 03/03/2029."}]
    fato = auditores.auditar_fatos(secoes, {"fatos": []}, texto_das_fontes="")
    assert [a["trecho"] for a in fato["achados"]] == ["03/03/2029"]


def test_dois_valores_da_causa_no_texto_bloqueiam():
    secoes = [{"code": "CLAIMS", "content": "Dá-se à causa o valor de R$ 14.208,50, correspondente à soma dos pedidos."},
              {"code": "VALUE", "content": "Dá-se à causa o valor de R$ 7.586,45."}]
    conta = auditores.auditar_calculos(secoes, [], [])
    assert any(a["codigo"] == "VALOR_DA_CAUSA_DIVERGENTE" for a in conta["achados"]), conta["achados"]


# ------------------------------------------------------------------ classificação explícita das teses

def test_classificacao_explica_por_que_cada_tese_morreu():
    m = {"fatos": [{"id": "M001", "estado": "confirmado", "fato": "atraso salarial", "chave": "pagamento.atraso_dias", "valor": "20"}],
         "contradicoes": []}
    bruto = {"teses": [
        {"tese": "Dano moral", "decisao": "REJECTED_NO_FACTUAL_BASIS", "motivo": "sem prejuízo", "fatos_que_suportam": ["M001"]},
        {"tese": "Estabilidade", "decisao": "REJECTED_LEGAL", "motivo": "contrato por prazo determinado"},
        {"tese": "Equiparação", "decisao": "REJECTED_STRATEGIC", "motivo": "skill: não deduzir sem paradigma identificado"},
        {"tese": "Horas extras", "decisao": "REJECTED_NO_FACTUAL_BASIS", "motivo": ""},
        {"tese": "Justiça gratuita", "decisao": "INCLUIR", "motivo": "declaração", "fatos_que_suportam": ["M001"],
         "fatos_necessarios": [{"fato": "declaração", "presente": True, "fato_id": "M001"}]},
        {"tese": "Aviso prévio", "decisao": "DESCARTAR", "motivo": "pedido de demissão"},
    ]}
    por = {t["tese"]: t for t in teses.normalizar(bruto, [], m)["teses"]}
    assert por["Dano moral"]["decisao"] == teses.POTENCIAL and "M001" in por["Dano moral"]["rebaixada_por"]
    assert por["Estabilidade"]["decisao"] == teses.REJEITADA_JURIDICA
    assert por["Equiparação"]["decisao"] == teses.REJEITADA_ESTRATEGICA
    assert por["Horas extras"]["decisao"] == teses.POTENCIAL and por["Horas extras"]["rebaixada_por"] == "rejeitada sem motivo"
    assert por["Justiça gratuita"]["decisao"] == teses.SUPPORTED
    assert por["Aviso prévio"]["decisao"] == teses.REJEITADA_SEM_FATO
    assert all(t["decisao"] in teses.DECISOES for t in por.values())
    assert set(teses.ROTULOS) == teses.DECISOES


# ------------------------------------------------------------------ provedor de busca substituível

class _ProvedorDeTeste:
    """Outro provedor (como seria o de Postgres): o orquestrador não precisa saber qual é."""

    def __init__(self) -> None:
        self.base = _registro_versionado()
        self.alertas: list[str] = []
        self.consultas: list[str] = []

    def consultar(self, consulta, filtros, top_k):
        self.consultas.append(consulta)
        return self.base.consultar(consulta, filtros, top_k)

    def resolver(self, citacao, data_referencia):
        return self.base.resolver(citacao, data_referencia)

    def por_referencia(self, referencia):
        return self.base.por_referencia(referencia)

    def inativas_com_marcadores(self, data_referencia):
        return self.base.inativas_com_marcadores(data_referencia)

    def adicionar(self, autoridade):
        self.base.adicionar(autoridade)

    def __len__(self):
        return len(self.base)


def test_provedor_de_busca_e_substituivel_sem_mudar_o_orquestrador():
    assert isinstance(aut.Registro(), ProvedorDeAutoridades)
    provedor = _ProvedorDeTeste()
    assert isinstance(provedor, ProvedorDeAutoridades)
    assert provedor.consultar("critério novo", Filtros(data_referencia=HOJE), 3)
    plano_est, fontes = _caso_rescisao()

    def llm(instrucao, entrada):
        return {"teses": [{"tese": "justiça gratuita", "decisao": "SUPPORTED", "motivo": "declaração", "fatos_que_suportam": ["M001"],
                           "fatos_necessarios": [{"fato": "x", "presente": True, "fato_id": "M001"}],
                           "jurisprudencia_a_pesquisar": ["critério antigo de concessão"]}]}
    prep = orquestrador.analisar(plano_est=plano_est, contexto_caso="", fontes=fontes, llm=llm, textos_skill={"SKILL.md": ""}, data_referencia=HOJE)
    prep = orquestrador.fundamentar(prep, provedor=provedor)
    assert provedor.consultas, "a busca por tese passou pelo provedor injetado"
    tese = next(t for t in prep["issues"]["teses"] if t["tese"] == "justiça gratuita")
    assert "stf:adc:9003" in [a.id for a in prep["autoridades_por_tese"][tese["id"]]]
    assert next(e for e in prep["rastro"].etapas if e["etapa"] == "base_juridica")["provedor"] == "_ProvedorDeTeste"


# ------------------------------------------------------------------ shadow: compara sem mexer na peça

def test_shadow_registra_diferencas_sem_alterar_a_peca_legada():
    plano_est, fontes = _caso_rescisao()

    def llm(instrucao, entrada):
        return {"teses": [{"tese": "Adicional noturno habitual", "decisao": "SUPPORTED", "motivo": "jornada até 23h40",
                           "fatos_que_suportam": ["M001"], "fatos_necessarios": [{"fato": "x", "presente": True, "fato_id": "M001"}],
                           "pedido": "adicional noturno"}]}
    prep = orquestrador.fundamentar(orquestrador.analisar(plano_est=plano_est, contexto_caso="", fontes=fontes, llm=llm,
                                                          textos_skill={"SKILL.md": ""}, data_referencia=HOJE),
                                    autoridades_base=_registro_versionado().autoridades)
    legado = [{"code": "LEGAL_GROUNDS", "content": "Da rescisão indireta, nos termos da Súmula 9998 do TST."}]
    copia = [dict(s) for s in legado]
    auditoria = orquestrador.auditar(legado, prep, pendencias=[])
    comp = orquestrador.comparar_com_legado(legado, prep, auditoria, plano_legado={"pedidos": []}, pendencias_legado=[])
    assert legado == copia, "shadow não altera a peça entregue"
    assert comp["teses_sustentadas_ausentes_no_legado"] == ["Adicional noturno habitual"]
    assert [c["status"] for c in comp["citacoes_reprovadas_no_legado"]] == [aut.REQUIRES_LEGAL_RESEARCH]
    assert comp["veredito_se_fosse_strict"]["pronta"] is False and comp["bloqueios_que_o_strict_apontaria"]
    rastro = orquestrador.trace(prep, auditoria, modo="shadow", comparacao=comp)
    assert rastro["modo"] == "shadow" and rastro["comparacao_com_legado"] is comp
    assert rastro["teses"][0]["rotulo"] and rastro["teses"][0]["fatos_detalhados"][0]["id"] == "M001"


# ------------------------------------------------------------------ strict: falha nunca vira peça pronta

def test_strict_falha_de_etapa_impede_peca_pronta():
    dados = {"readiness": {"ready": True, "blocking_issues": [], "warnings": []}}
    auditoria = {"veredito": {"pronta": True, "auditores": {}}, "achados": []}
    peticao_local._aplicar_veredito_juridico(dados, auditoria, ["autoridades: base verificada vazia"])  # noqa: SLF001
    assert dados["readiness"]["ready"] is False
    assert any("Camada jurídica falhou — autoridades" in b for b in dados["readiness"]["blocking_issues"])
    sem = {"readiness": {"ready": True}}
    peticao_local._aplicar_veredito_juridico(sem, None, [])  # noqa: SLF001
    assert sem["readiness"]["ready"] is False


def test_etapa_juridica_registra_falha_em_vez_de_cair_em_silencio():
    falhas: list[str] = []
    diag: dict = {}

    def quebra():
        raise RuntimeError("modelo fora do ar")
    assert peticao_local._etapa_juridica("análise", quebra, falhas, diag) is None  # noqa: SLF001
    assert falhas == ["análise: RuntimeError: modelo fora do ar"] and diag["fallbacks"]
    rastro = orquestrador.trace_de_falha("strict", falhas)
    assert rastro["falhas"] == falhas and rastro["teses"] == [] and rastro["auditoria"] is None


def test_shadow_sem_analise_devolve_rastro_de_falha_sem_excecao():
    rastro = peticao_local._juridico_em_sombra(None, [], {}, [], "", {}, "PA")  # noqa: SLF001
    assert rastro["modo"] == "shadow" and rastro["falhas"] == ["análise: não iniciou"]


# ------------------------------------------------------------------ tabela com 3 itens homogêneos

def test_tres_itens_homogeneos_preferem_tabela_salvo_veto_da_skill():
    m = {"fatos": [{"data": "01/01/2024"}, {"data": "01/02/2024"}, {"data": "01/03/2024"},
                   {"chave": "pagamento.pix", "valor": "R$ 1,00"}, {"chave": "pagamento.pix", "valor": "R$ 2,00"}, {"chave": "pagamento.pix", "valor": "R$ 3,00"}]}
    d = tabelas.decidir(m, [])
    assert d["cronologia"]["decisao"] == "USE_TABLE" and d["pagamentos"]["decisao"] == "USE_TABLE"
    assert max(tabelas.LIMIARES.values()) <= tabelas.LIMIAR_HOMOGENEO
    assert tabelas.decidir(m, [], {"pagamentos": False})["pagamentos"]["decisao"] == "NO_TABLE"
