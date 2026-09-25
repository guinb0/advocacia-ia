import io
import zipfile

from app import peticao_local


def test_docx_da_peticao_usa_identidade_visual_trocavel(monkeypatch):
    logo = b"\x89PNG\r\n\x1a\nlogo-de-teste"
    monkeypatch.setattr(
        peticao_local,
        "identidade_visual",
        lambda: (logo, "Times New Roman", ".png", "modelo-geral.docx"),
    )

    conteudo = peticao_local.montar_docx(
        [{"code": "FACTS", "label": "Dos fatos", "content": "Conteúdo."}]
    )

    with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
        assert arquivo.testzip() is None
        assert arquivo.read("word/media/logo-escritorio.png") == logo
        # A fonte vem da skill (formatacao.md), não do modelo visual enviado: o padrão
        # do escritório manda sobre a última medição guardada.
        assert b'Arial' in arquivo.read("word/styles.xml")


def test_extrai_logo_do_cabecalho_e_fonte_do_modelo(monkeypatch):
    monkeypatch.setattr(
        peticao_local,
        "identidade_visual",
        lambda: (
            peticao_local.LOGO_LARA_MELO.read_bytes(),
            "Arial",
            ".png",
            "Padrão Lara & Melo",
        ),
    )
    modelo = peticao_local.montar_docx([])

    logo, fonte, extensao = peticao_local.extrair_identidade_visual(modelo)

    assert logo == peticao_local.LOGO_LARA_MELO.read_bytes()
    assert fonte == "Arial"
    assert extensao == ".png"


def test_tabela_markdown_vira_tabela_word_nativa(monkeypatch):
    monkeypatch.setattr(
        peticao_local,
        "identidade_visual",
        lambda: (b"\x89PNG\r\n\x1a\nlogo", "Arial", ".png", "modelo.docx"),
    )
    conteudo = peticao_local.montar_docx(
        [{
            "code": "FACTS",
            "label": "Dos fatos",
            "content": (
                "O vínculo está comprovado.\n\n"
                "| INFORMAÇÃO | DADOS DO CONTRATO |\n"
                "| --- | --- |\n"
                "| Data de admissão | 21/09/2000 |\n"
                "| Função | Carteiro |\n\n"
                "O restante dos fatos permanece em seguida."
            ),
        }]
    )

    with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
        documento = arquivo.read("word/document.xml").decode("utf-8")
    assert "<w:tbl>" in documento
    assert "INFORMAÇÃO" in documento
    assert "| INFORMAÇÃO" not in documento
    assert documento.index("O vínculo está comprovado.") < documento.index("<w:tbl>")
    assert documento.index("<w:tbl>") < documento.index("O restante dos fatos")


def test_docx_segue_o_layout_da_skill_formatacao():
    """`formatacao.md`: A4, margens 3/2/2/3, 12 pt, 1,5, recuo 1,25 cm, justificado,
    logo no cabeçalho e paginação "Página X de Y" em toda a peça."""
    import re

    conteudo = peticao_local.montar_docx(
        [{"code": "FACTS", "label": "Dos fatos", "content": "Conteúdo."}]
    )
    with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
        assert arquivo.testzip() is None
        documento = arquivo.read("word/document.xml").decode("utf-8")
        estilos = arquivo.read("word/styles.xml").decode("utf-8")
        rodape = arquivo.read("word/footer1.xml").decode("utf-8")
        cabecalho = arquivo.read("word/header1.xml").decode("utf-8")

    assert 'w:w="11906" w:h="16838"' in documento  # A4
    margens = re.search(r'<w:pgMar w:top="(\d+)" w:right="(\d+)" w:bottom="(\d+)" w:left="(\d+)"', documento)
    assert tuple(int(v) for v in margens.groups()) == (1701, 1134, 1134, 1701)  # 3/2/2/3 cm
    assert 'w:val="24"' in estilos  # 12 pt
    assert 'w:line="360"' in estilos  # 1,5
    assert 'w:firstLine="709"' in estilos  # 1,25 cm
    assert '<w:jc w:val="both"/>' in estilos  # justificado
    assert 'r:id="rIdFooter"' in documento and "PAGE" in rodape and "NUMPAGES" in rodape
    assert "Página" in rodape and "<w:drawing>" in cabecalho
