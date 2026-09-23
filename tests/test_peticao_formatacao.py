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
