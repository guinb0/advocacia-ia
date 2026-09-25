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
    """`formatacao.md` (bloco estilo): A4, margens 3/2/2/3, 12 pt, 1,3, recuo 1,25 cm, justificado,
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
    assert 'w:line="312"' in estilos  # 1,3
    assert 'w:after="120"' in estilos  # 6 pt depois do parágrafo
    assert 'w:firstLine="709"' in estilos  # 1,25 cm
    assert '<w:jc w:val="both"/>' in estilos  # justificado
    assert 'r:id="rIdFooter"' in documento and "PAGE" in rodape and "NUMPAGES" in rodape
    assert "Página" in rodape and "<w:drawing>" in cabecalho


_FORMATACAO_ALTERNATIVA = """# Outra skill
```estilo
pagina.fonte: Georgia
pagina.margem_superior_cm: 2
pagina.margem_esquerda_cm: 4
pagina.margem_inferior_cm: 2
pagina.margem_direita_cm: 1
corpo.tamanho_pt: 11
corpo.alinhamento: esquerda
corpo.espacamento_linha: 2
corpo.depois_pt: 0
corpo.recuo_primeira_linha_cm: 0
titulo1.negrito: sim
titulo1.cor: 1F4E79
titulo1.caixa_alta: sim
titulo1.alinhamento: centro
blockquote.italico: sim
blockquote.recuo_esquerdo_cm: 2
destaque.borda_cor: FF0000
destaque.preenchimento: FFFF00
destaque.recuo_esquerdo_cm: 6
cabecalho.logo_altura_cm: 1
rodape.formato: Pág. {pagina}/{total}
rodape.alinhamento: centro
rodape.tamanho_pt: 8
```
"""


def test_trocar_so_a_skill_muda_todo_o_documento(monkeypatch):
    """Teste de pureza: nenhuma linha do motor muda; só o texto de `formatacao.md`.

    Fonte, margens, espaçamento, título colorido/centralizado, blockquote, bloco nomeado
    com borda e preenchimento, altura da logo e rodapé têm de vir da skill.
    """
    import re
    from app import peticao_skill_arquivos as skill

    original = skill._ler
    monkeypatch.setattr(skill, "_ler", lambda nome: _FORMATACAO_ALTERNATIVA if nome == "formatacao.md" else original(nome))
    conteudo = peticao_local.montar_docx([
        {"code": "X", "label": "", "content": "# Capítulo\nParágrafo.\n> Citação\n::: destaque\nBloco\n:::"}
    ])
    with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
        documento = arquivo.read("word/document.xml").decode("utf-8")
        estilos = arquivo.read("word/styles.xml").decode("utf-8")
        rodape = arquivo.read("word/footer1.xml").decode("utf-8")
        cabecalho = arquivo.read("word/header1.xml").decode("utf-8")

    assert 'w:ascii="Georgia"' in estilos and 'w:val="22"' in estilos and 'w:line="480"' in estilos
    margens = re.search(r'<w:pgMar w:top="(\d+)" w:right="(\d+)" w:bottom="(\d+)" w:left="(\d+)"', documento)
    assert tuple(int(v) for v in margens.groups()) == (1134, 567, 1134, 2268)
    assert 'w:color w:val="1F4E79"' in documento and "<w:caps" not in documento  # caixa alta = texto em maiúsculas
    assert "CAPÍTULO" in documento and '<w:jc w:val="center"/>' in documento
    assert "<w:i/>" in documento and 'w:left="1134"' in documento  # blockquote da skill
    assert 'w:fill="FFFF00"' in documento and 'w:color="FF0000"' in documento and 'w:left="3402"' in documento
    assert ">" not in re.sub(r"<[^>]+>", "", documento)  # o `>` não vaza como texto
    assert "Pág." in rodape and 'w:val="center"' in rodape and 'w:val="16"' in rodape
    assert 'cy="360000"' in cabecalho  # logo com 1 cm de altura


def test_sem_bloco_estilo_o_motor_nao_inventa_paginacao(monkeypatch):
    from app import peticao_skill_arquivos as skill

    original = skill._ler
    monkeypatch.setattr(skill, "_ler", lambda nome: "# sem estilos" if nome == "formatacao.md" else original(nome))
    conteudo = peticao_local.montar_docx([{"code": "X", "label": "", "content": "Texto."}])
    with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
        assert "PAGE" not in arquivo.read("word/footer1.xml").decode("utf-8")
