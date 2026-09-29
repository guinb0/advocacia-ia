"""Peças antigas (sem `#`) são migradas FORA do renderer; o renderer continua sem adivinhar."""

import io
import zipfile

from app import peticao_local, peticao_migracao_legado as m


def _xml(secoes):
    with zipfile.ZipFile(io.BytesIO(peticao_local.montar_docx(secoes))) as z:
        return z.read("word/document.xml").decode("utf-8")


def test_migracao_converte_titulos_e_enderecamento_do_formato_antigo():
    antigo = [{"code": "FACTS", "label": "", "content": "Ao Juízo da Vara do Trabalho de Tucuruí/PA\n\nI – DA ADMISSÃO\n\nTexto corrido do parágrafo.\n\nI.1 – Da jornada\n\nOutro texto."}]
    (novo,) = m.migrar_secoes(antigo)
    assert novo["formato"] == m.FORMATO_ATUAL
    linhas = novo["content"].split("\n")
    assert "::: enderecamento" in linhas and "# I – DA ADMISSÃO" in linhas and "## I.1 – Da jornada" in linhas
    assert "Texto corrido do parágrafo." in linhas  # corpo intacto


def test_secao_no_formato_novo_passa_intacta():
    nova = {"code": "X", "label": "", "content": "# Capítulo\nTEXTO EM CAIXA ALTA\n", "formato": 2}
    assert m.migrar_secoes([nova]) == [nova]
    sem_marca = {"code": "X", "label": "", "content": "TEXTO\n# já marcado"}
    assert m.migrar_secoes([sem_marca]) == [sem_marca]  # tem marcação: não é legado


def test_renderer_nao_adivinha_titulo_mas_a_migracao_o_faz_antes():
    novo = [{"code": "X", "label": "", "content": "DOS FATOS\n\nTexto.", "formato": 2}]
    assert "<w:b/>" not in _xml(novo)  # formato novo sem `#`: é corpo, e ponto
    antigo = [{"code": "X", "label": "", "content": "DOS FATOS\n\nTexto."}]
    assert "<w:b/>" in _xml(antigo)  # legado: migrado antes de renderizar
