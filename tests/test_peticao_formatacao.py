"""Formatação feita no editor da tela (itálico, sublinhado, tamanho, cor, alinhamento)
chegando ao .docx como formatação de verdade — e nunca como marcação literal."""

import io
import re
import zipfile
from xml.etree import ElementTree

import pytest

from app import peticao_local

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _documento(conteudo: str, code: str = "VALUE") -> ElementTree.Element:
    docx = peticao_local.montar_docx([{"code": code, "label": "", "content": conteudo}])
    with zipfile.ZipFile(io.BytesIO(docx)) as pacote:
        return ElementTree.fromstring(pacote.read("word/document.xml"))


def _paragrafos(raiz: ElementTree.Element) -> list[ElementTree.Element]:
    return [p for p in raiz.iter("{%s}p" % NS["w"]) if "".join(p.itertext()).strip()]


def _run_com(raiz: ElementTree.Element, texto: str) -> ElementTree.Element:
    for run in raiz.iter("{%s}r" % NS["w"]):
        if "".join(run.itertext()) == texto:
            return run
    raise AssertionError(f"nenhum run com o texto {texto!r}")


def test_itálico_sublinhado_tamanho_e_cor_viram_propriedades_do_run():
    raiz = _documento(
        "Antes [[i]]inclinado[[/i]], [[u]]riscado[[/u]], "
        "[[tam=16]]grande[[/tam]] e [[cor=#C00000]]vermelho[[/cor]]."
    )
    assert _run_com(raiz, "inclinado").find("w:rPr/w:i", NS) is not None
    assert _run_com(raiz, "riscado").find("w:rPr/w:u", NS) is not None
    assert _run_com(raiz, "grande").find("w:rPr/w:sz", NS).get("{%s}val" % NS["w"]) == "32"
    assert _run_com(raiz, "vermelho").find("w:rPr/w:color", NS).get("{%s}val" % NS["w"]) == "C00000"


def test_nenhuma_marcação_vaza_como_texto():
    raiz = _documento(
        "[[alin=centro]]Linha [[i]]centrada[[/i]] **forte**\n"
        "[[tam=abc]]tamanho inválido[[/tam]] e [[cor=azul]]cor inválida[[/cor]] [[/i]]sobra"
    )
    texto = "".join(raiz.itertext())
    assert "[[" not in texto and "]]" not in texto
    assert "**" not in texto
    assert "tamanho inválido" in texto and "cor inválida" in texto and "sobra" in texto


def test_alinhamento_da_linha_prevalece_e_tira_o_recuo_ao_centralizar():
    raiz = _documento("[[alin=centro]]No meio\n[[alin=direita]]À direita\nComum")
    centro, direita, comum = _paragrafos(raiz)[:3]
    assert centro.find("w:pPr/w:jc", NS).get("{%s}val" % NS["w"]) == "center"
    assert centro.find("w:pPr/w:ind", NS).get("{%s}firstLine" % NS["w"]) == "0"
    assert direita.find("w:pPr/w:jc", NS).get("{%s}val" % NS["w"]) == "right"
    assert comum.find("w:pPr", NS) is None  # herda justificado + recuo do estilo


def test_alinhamento_justificado_mantém_o_recuo_do_corpo():
    (paragrafo,) = _paragrafos(_documento("[[alin=justificado]]Texto corrido"))
    assert paragrafo.find("w:pPr/w:jc", NS).get("{%s}val" % NS["w"]) == "both"
    assert paragrafo.find("w:pPr/w:ind", NS) is None


def test_linha_só_com_alinhamento_é_linha_em_branco():
    raiz = _documento("A\n[[alin=centro]]\nB")
    assert [("".join(p.itertext())) for p in _paragrafos(raiz)][:2] == ["A", "B"]


def test_título_reconhecido_mesmo_com_formatação_em_volta():
    (paragrafo,) = _paragrafos(_documento("[[tam=14]]DOS FATOS[[/tam]]"))
    assert paragrafo.find("w:r/w:rPr/w:b", NS) is not None
    assert paragrafo.find("w:pPr/w:jc", NS).get("{%s}val" % NS["w"]) == "left"


def test_alinhamento_escolhido_vale_sobre_o_do_título():
    (paragrafo,) = _paragrafos(_documento("[[alin=centro]]DOS FATOS"))
    assert paragrafo.find("w:pPr/w:jc", NS).get("{%s}val" % NS["w"]) == "center"


def test_negrito_sem_par_continua_sumindo_em_vez_de_sair_literal():
    raiz = _documento("**Fulano** de Tal e um asterisco ** solto")
    assert "**" not in "".join(raiz.itertext())
    assert _run_com(raiz, "Fulano").find("w:rPr/w:b", NS) is not None


def test_citação_segue_sem_negrito_e_em_corpo_menor():
    (paragrafo,) = _paragrafos(_documento("> **O laudo** diz [[i]]isto[[/i]]"))
    assert paragrafo.find("w:pPr/w:ind", NS).get("{%s}left" % NS["w"]) == "2268"
    for run in paragrafo.findall("w:r", NS):
        assert run.find("w:rPr/w:b", NS) is None
        assert run.find("w:rPr/w:sz", NS).get("{%s}val" % NS["w"]) == "20"
    assert _run_com(paragrafo, "isto").find("w:rPr/w:i", NS) is not None


def test_tabela_e_foto_continuam_reconhecidas_com_alinhamento_na_frente():
    conteudo = (
        "[[alin=centro]]| Informação | Dado |\n"
        "| --- | --- |\n"
        "| [[i]]Cargo[[/i]] | Agente |"
    )
    raiz = _documento(conteudo)
    assert raiz.find(".//w:tbl", NS) is not None
    texto = "".join(raiz.itertext())
    assert "[[" not in texto and "|" not in texto
    assert "Cargo" in texto and "Agente" in texto


def test_ordem_das_propriedades_do_run_segue_o_esquema():
    raiz = _documento("[[u]][[i]][[cor=#112233]][[tam=12]]**tudo**[[/tam]][[/cor]][[/i]][[/u]]")
    filhos = [re.sub(r"\{.*\}", "", f.tag) for f in _run_com(raiz, "tudo").find("w:rPr", NS)]
    assert filhos == ["b", "i", "color", "sz", "szCs", "u"]


@pytest.mark.parametrize("tam,esperado", [("2", "12"), ("500", "144")])
def test_tamanho_absurdo_é_limitado(tam, esperado):
    run = _run_com(_documento(f"[[tam={tam}]]x[[/tam]]"), "x")
    assert run.find("w:rPr/w:sz", NS).get("{%s}val" % NS["w"]) == esperado


# ----------------------------------------------------------------- tachado, tabulação
#
# O que a barra e a régua da tela aplicam precisa existir NO DOCUMENTO. Um
# controle que só mexe no HTML da prévia é pior que controle nenhum: o advogado
# formata, baixa o .docx e a formatação não está lá.


def test_tachado_vira_propriedade_do_run():
    raiz = _documento("Valor [[s]]antigo[[/s]] corrigido")
    assert _run_com(raiz, "antigo").find("w:rPr/w:strike", NS) is not None
    assert _run_com(raiz, "Valor ").find("w:rPr/w:strike", NS) is None


def test_tabulação_vira_elemento_e_não_espaço():
    (paragrafo,) = _paragrafos(_documento("a) horas extras\tR$ 12.400,00"))
    assert paragrafo.find(".//w:tab", NS) is not None
    assert "\t" not in "".join(paragrafo.itertext())


def test_ordem_das_propriedades_do_run_com_tachado():
    raiz = _documento("[[u]][[i]][[s]][[cor=#112233]][[tam=12]]**tudo**[[/tam]][[/cor]][[/s]][[/i]][[/u]]")
    filhos = [re.sub(r"\{.*\}", "", f.tag) for f in _run_com(raiz, "tudo").find("w:rPr", NS)]
    assert filhos == ["b", "i", "strike", "color", "sz", "szCs", "u"]


# ----------------------------------------------------------------------------- régua


def _ind(paragrafo: ElementTree.Element) -> dict[str, str]:
    no = paragrafo.find("w:pPr/w:ind", NS)
    return {} if no is None else {k.split("}")[-1]: v for k, v in no.attrib.items()}


def test_recuos_da_régua_viram_twips():
    (paragrafo,) = _paragrafos(_documento("[[par=esq:2;dir:1]]Recuado dos dois lados"))
    assert _ind(paragrafo) == {"left": "1134", "right": "567"}


def test_primeira_linha_negativa_vira_deslocamento():
    """`w:firstLine` negativo o Word ignora; deslocamento é `w:hanging` positivo."""
    (paragrafo,) = _paragrafos(_documento("[[par=esq:1.25;pri:-1.25]]a) o pedido"))
    assert _ind(paragrafo) == {"left": "709", "hanging": "709"}


def test_medida_da_régua_vence_o_recuo_zerado_do_centralizado():
    """Centralizar zera o recuo por conta própria — mas não por cima de quem arrastou."""
    (paragrafo,) = _paragrafos(_documento("[[alin=centro]][[par=pri:1]]No meio, com recuo pedido"))
    assert _ind(paragrafo) == {"firstLine": "567"}
    assert paragrafo.find("w:pPr/w:jc", NS).get("{%s}val" % NS["w"]) == "center"


def test_marcadores_de_parágrafo_em_qualquer_ordem():
    (paragrafo,) = _paragrafos(_documento("[[par=esq:3]][[alin=direita]]Ordem inversa"))
    assert _ind(paragrafo)["left"] == "1701"
    assert paragrafo.find("w:pPr/w:jc", NS).get("{%s}val" % NS["w"]) == "right"


def test_medida_absurda_da_régua_é_limitada():
    (paragrafo,) = _paragrafos(_documento("[[par=esq:99;dir:99]]Exagero"))
    assert _ind(paragrafo) == {"left": "5669", "right": "5669"}  # 10 cm, o teto


# ----------------------------------------------------------------- quebra de página


def test_quebra_de_página_vira_br_do_tipo_page():
    raiz = _documento("Fim dos fatos\n[[pagina]]\nDOS PEDIDOS")
    quebra = raiz.find('.//w:br[@w:type="page"]', NS)
    assert quebra is not None
    assert "[[" not in "".join(raiz.itertext())


def test_quebra_de_página_só_vale_sozinha_na_linha():
    """`[[pagina]]` no meio de uma frase é texto que a pessoa digitou, não comando."""
    raiz = _documento("o prazo [[pagina]] venceu")
    assert raiz.find('.//w:br[@w:type="page"]', NS) is None


def test_medida_inválida_some_sem_levar_o_texto():
    (paragrafo,) = _paragrafos(_documento("[[par=esq:abc;dir:1]]Texto que fica"))
    assert "Texto que fica" in "".join(paragrafo.itertext())
    assert _ind(paragrafo) == {"right": "567"}


def test_parágrafo_sem_marcador_continua_herdando_o_estilo():
    (paragrafo,) = _paragrafos(_documento("Texto corrido sem nada aplicado"))
    assert paragrafo.find("w:pPr", NS) is None


def test_linha_só_com_marcador_de_parágrafo_é_linha_em_branco():
    raiz = _documento("A\n[[par=esq:2]]\nB")
    assert [("".join(p.itertext())) for p in _paragrafos(raiz)][:2] == ["A", "B"]


def test_tabela_continua_reconhecida_com_marcador_de_parágrafo_na_frente():
    raiz = _documento(
        "[[par=esq:2]]| Informação | Dado |\n| --- | --- |\n| Cargo | Agente |"
    )
    assert raiz.find(".//w:tbl", NS) is not None
    assert "[[" not in "".join(raiz.itertext())


# ------------------------------------------------------------------------ tabelas
#
# A tabela que o editor grava é a MESMA que a IA escreve: cabeçalho, linha
# separadora e corpo, em Markdown. Estes testes travam esse contrato — a tela
# escreve neste formato e o Word tem de receber `w:tbl`, não barras.


def test_cronologia_em_markdown_vira_tabela_nativa():
    raiz = _documento(
        "Os fatos seguem a ordem abaixo.\n"
        "\n"
        "| Data | Fato | Documento |\n"
        "| --- | --- | --- |\n"
        "| 12/03/2019 | Admissão | CTPS, fl. 3 |\n"
        "| 04/08/2024 | Dispensa | TRCT |"
    )
    tabela = raiz.find(".//w:tbl", NS)
    assert tabela is not None
    linhas = tabela.findall("w:tr", NS)
    assert len(linhas) == 3  # cabeçalho + duas linhas de dados
    celulas = ["".join(c.itertext()) for c in linhas[0].findall("w:tc", NS)]
    assert celulas == ["Data", "Fato", "Documento"]
    primeira = ["".join(c.itertext()) for c in linhas[1].findall("w:tc", NS)]
    assert primeira == ["12/03/2019", "Admissão", "CTPS, fl. 3"]
    texto = "".join(raiz.itertext())
    assert "|" not in texto and "---" not in texto
    assert "Os fatos seguem a ordem abaixo." in texto


def test_cabeçalho_da_tabela_sai_em_negrito():
    raiz = _documento("| Item | Valor |\n| --- | --- |\n| Perícia | R$ 2.500,00 |")
    cabecalho = raiz.find(".//w:tbl/w:tr", NS)
    assert all(run.find("w:rPr/w:b", NS) is not None for run in cabecalho.iter("{%s}r" % NS["w"]))


def test_tabela_sem_linha_de_dados_continua_texto():
    """Mesmo critério da tela: sem corpo não há tabela, e as barras viram texto."""
    raiz = _documento("| A | B |\n| --- | --- |")
    assert raiz.find(".//w:tbl", NS) is None
