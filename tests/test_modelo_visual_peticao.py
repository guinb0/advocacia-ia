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
        assert b'Times New Roman' in arquivo.read("word/styles.xml")


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
