"""Regressões estruturais da v12, abstraídas do caso real e sem dados do cliente."""

import io
import zipfile

from app import auditoria_estrutural as ae
from app import documento_final as df
from app import peticao_local as pl
from app import peticao_skill_arquivos as skill


PARAMS = skill.validacoes_da_skill()["parametros"]
PLANO = {"partes": {}, "fatos": [], "teses": [], "pedidos": [], "ausencias": [], "case_facts": {}}


def codigos(achados):
    return {a.codigo for a in achados}


def test_1_fechamento_duplicado_tem_um_unico_owner():
    secoes = [{"code": "CLOSING", "content": "Termos em que,\nPede deferimento.\n\n::: fechamento\nTermos em que,\nPede deferimento.\n:::"}]
    limpas, rel = df.higienizar(secoes, PLANO, PARAMS)
    texto = limpas[0]["content"]
    assert rel["fechamentos_duplicados_removidos"] == 1
    assert texto.lower().count("termos em que") == 1
    assert "EXACTLY_ONE_CLOSING_BLOCK" not in codigos(df.validar_documento_final(limpas, PLANO, PARAMS))


def test_2_marcador_de_fechamento_nunca_chega_ao_editor():
    limpas, _ = df.higienizar([{"code": "CLOSING", "content": "::: fechamento\nTermos em que,\nPede deferimento.\n:::"}], PLANO, PARAMS)
    assert ":::" not in limpas[0]["content"]


def test_3_todo_marcador_estrutural_e_removido_do_docx():
    secoes, _ = df.higienizar([{"code": "X", "content": "::: bloco-interno\nTexto visível.\n:::"}], PLANO, PARAMS)
    assert ":::" not in df.representacao_final(secoes, PARAMS)[0]["content"]
    with zipfile.ZipFile(io.BytesIO(pl.montar_docx(secoes))) as arquivo:
        assert ":::" not in arquivo.read("word/document.xml").decode("utf-8")


def test_4_subsecao_com_pai_incompativel_falha():
    secoes = [{"code": "LEGAL_GROUNDS", "content": "II. Do Direito\n\n### VII.1. Tema"}]
    assert "SUBSECAO_COM_PAI_INCONSISTENTE" in codigos(df.invariantes_estruturais(secoes))


def test_5_sequencia_principal_incoerente_falha():
    secoes = [{"code": "FACTS", "content": "VI. Dos Fatos"}, {"code": "LEGAL_GROUNDS", "content": "II. Do Direito"}, {"code": "CLAIMS", "content": "III. Dos Pedidos"}]
    assert "SEQUENCIA_DE_HEADINGS_INVALIDA" in codigos(df.invariantes_estruturais(secoes))


def test_titulo_romano_sem_markdown_vira_titulo_negrito_no_docx():
    secoes = [{"code": "LEGAL_GROUNDS", "content": "II. DA COMPETÊNCIA DA JUSTIÇA DO TRABALHO"}]
    with zipfile.ZipFile(io.BytesIO(pl.montar_docx(secoes))) as arquivo:
        xml = arquivo.read("word/document.xml").decode("utf-8")
    assert "II. DA COMPETÊNCIA DA JUSTIÇA DO TRABALHO" in xml
    assert "<w:b" in xml


def test_5b_higiene_deriva_capitulo_e_subsecao_da_mesma_ordem():
    secoes = [{"code": "FACTS", "content": "VI. Dos Fatos"}, {"code": "LEGAL_GROUNDS", "content": "II. Do Direito\n\n### VII.1. Tema"}, {"code": "CLAIMS", "content": "III. Dos Pedidos"}]
    limpas, _ = df.higienizar(secoes, PLANO, PARAMS)
    assert limpas[1]["content"].startswith("II. Do Direito")
    assert "II.1. Tema" in limpas[1]["content"]
    assert limpas[2]["content"].startswith("III. Dos Pedidos")


def test_6_duas_secoes_logicas_de_pedidos_falham():
    secoes = [{"code": "CLAIMS", "content": "I. Dos Pedidos"}, {"code": "CLAIMS", "content": "II. Requerimentos"}]
    assert "SECAO_ESTRUTURAL_DUPLICADA" in codigos(df.invariantes_estruturais(secoes))


def test_7_dois_fechamentos_falham_antes_da_higiene():
    secoes = [{"code": "CLOSING", "content": "Termos em que,\nPede deferimento.\n\nTermos em que,\nPede deferimento."}]
    assert "EXACTLY_ONE_CLOSING_BLOCK" in codigos(df.validar_documento_final(secoes, PLANO, PARAMS))


def test_8_julgamento_antecipado_com_pericia_necessaria_falha():
    secoes = [{"code": "LEGAL_GROUNDS", "content": "Requer julgamento antecipado por desnecessidade de audiência."}, {"code": "CLAIMS", "content": "É necessária prova pericial para confirmar a extensão do dano."}]
    assert "ESTRATEGIA_PROCESSUAL_INCONSISTENTE" in codigos(df.consistencia_procedimental(secoes))


def test_9_julgamento_antecipado_com_prova_testemunhal_necessaria_falha():
    secoes = [{"code": "LEGAL_GROUNDS", "content": "A causa dispensa audiência e instrução."}, {"code": "CLAIMS", "content": "É necessária prova testemunhal para confirmar os fatos."}]
    assert "ESTRATEGIA_PROCESSUAL_INCONSISTENTE" in codigos(df.consistencia_procedimental(secoes))


def test_10_referencia_curta_a_precedente_compartilhado_e_valida():
    secoes = [{"code": "LEGAL_GROUNDS", "content": "O precedente foi desenvolvido neste capítulo, com sua ratio e aplicação concreta."}, {"code": "LEGAL_GROUNDS", "content": "Aplica-se, ainda, o precedente já desenvolvido acima."}]
    assert "REPETICAO_DESNECESSARIA" not in codigos(ae.repeticao_de_conteudo(secoes, PARAMS))


def test_11_transcricao_substancialmente_repetida_e_sinalizada():
    texto = "O precedente vinculante define responsabilidade objetiva quando o risco da atividade se concretiza e impõe reparação integral do dano comprovado no caso concreto."
    secoes = [{"code": "LEGAL_GROUNDS", "content": texto}, {"code": "OTHER", "content": texto}]
    assert "REPETICAO_DESNECESSARIA" in codigos(ae.repeticao_de_conteudo(secoes, PARAMS))
