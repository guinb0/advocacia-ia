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
