import io
import zipfile

from app import armazenamento, peticao_local


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


def test_docx_aplica_configuracao_visual_explicita(monkeypatch):
    logo = peticao_local.LOGO_LARA_MELO.read_bytes()
    monkeypatch.setattr(
        peticao_local,
        "identidade_visual",
        lambda: (logo, "Arial", ".png", "logo.png"),
    )
    config = {
        **peticao_local.CONFIG_VISUAL_PADRAO,
        "fonte": "Garamond",
        "tamanho_fonte": 11,
        "tamanho_titulo": 16,
        "espacamento": 1.15,
        "alinhamento_logo": "right",
        "largura_logo_cm": 6,
        "cor_texto": "#252525",
        "cor_destaque": "#1E3A56",
        "mostrar_linha_cabecalho": True,
    }
    monkeypatch.setattr(peticao_local, "configuracao_visual", lambda _fonte=None: config)

    conteudo = peticao_local.montar_docx(
        [{"code": "FACTS", "label": "Dos fatos", "content": "Conteúdo."}]
    )

    with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
        estilos = arquivo.read("word/styles.xml")
        documento = arquivo.read("word/document.xml")
        cabecalho = arquivo.read("word/header1.xml")
        assert b'Garamond' in estilos
        assert b'w:sz w:val="22"' in estilos
        assert b'w:line="276"' in estilos
        assert b'w:sz w:val="32"' in documento
        assert b'w:color w:val="1E3A56"' in documento
        assert b'w:jc w:val="right"' in cabecalho
        assert b'w:pBdr' in cabecalho


def test_salvar_modelo_nao_reabre_o_banco_depois_de_gravar(monkeypatch):
    class Resultado:
        rowcount = 0

    class Conexao:
        def __init__(self):
            self.comandos = []

        def execute(self, sql, parametros):
            self.comandos.append((sql, parametros))
            return Resultado()

    class Contexto:
        def __init__(self, conexao):
            self.conexao = conexao

        def __enter__(self):
            return self.conexao

        def __exit__(self, *_args):
            return False

    conexao = Conexao()
    monkeypatch.setattr(armazenamento, "conectar", lambda: Contexto(conexao))
    monkeypatch.setattr(
        armazenamento,
        "obter_modelo",
        lambda _codigo: (_ for _ in ()).throw(AssertionError("leitura redundante")),
    )

    registro = armazenamento.salvar_modelo(
        peticao_local.MODELO_VISUAL_GERAL,
        nome_arquivo="marca.png",
        conteudo=b"imagem",
        enviado_por="Mariana",
    )

    assert len(conexao.comandos) == 2
    assert registro["nome_arquivo"] == "marca.png"
    assert registro["enviado_por"] == "Mariana"
    assert registro["atualizado_em"]
