"""O analisador do modelo visual capta tamanho, espaçamento, alinhamento e margens.

É o que alimenta o "O que identificamos no seu modelo" da tela: sobe um .docx e
o escritório vê, em texto, o padrão que foi captado. Nada de rede — monta um
.docx mínimo em memória.

    PYTHONPATH=. .venv/Scripts/python.exe tests/test_modelo_estilo.py
"""

from __future__ import annotations

import io
import zipfile

from app import peticao_local

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

STYLES = f"""<?xml version="1.0"?>
<w:styles xmlns:w="{W}">
  <w:docDefaults><w:rPrDefault><w:rPr>
    <w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/>
    <w:sz w:val="24"/>
  </w:rPr></w:rPrDefault>
  <w:pPrDefault><w:pPr>
    <w:spacing w:line="360"/>
    <w:jc w:val="both"/>
  </w:pPr></w:pPrDefault></w:docDefaults>
</w:styles>"""

DOCUMENT = f"""<?xml version="1.0"?>
<w:document xmlns:w="{W}"><w:body><w:sectPr>
  <w:pgMar w:top="1701" w:right="1134" w:bottom="1134" w:left="1701"/>
</w:sectPr></w:body></w:document>"""


def _docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/styles.xml", STYLES)
        z.writestr("word/document.xml", DOCUMENT)
        z.writestr("word/media/logo.png", b"\x89PNG\r\n\x1a\n")
    return buf.getvalue()


def checar(cond: bool, desc: str, detalhe: str = "") -> int:
    print(f"  {'PASS' if cond else '>> FALHA'} {desc}" + (f" ({detalhe})" if detalhe and not cond else ""))
    return 0 if cond else 1


def main_teste() -> int:
    a = peticao_local.analisar_estilo(_docx())
    falhas = 0
    falhas += checar(a.get("tamanho_fonte_pt") == 12.0, "tamanho: sz=24 meios-pontos vira 12pt", str(a))
    falhas += checar(a.get("espacamento_linha") == 1.5, "espaçamento: line=360 vira 1,5", str(a))
    falhas += checar(a.get("alinhamento") == "justificado", "jc=both vira 'justificado'", str(a))
    m = a.get("margens_cm") or {}
    falhas += checar(m.get("top") == 3.0, "margem superior 1701 twips ~ 3,0 cm", str(m))
    falhas += checar(m.get("left") == 3.0 and m.get("right") == 2.0, "margens esq/dir corretas", str(m))

    # Um .docx sem estilos não quebra — devolve dict vazio.
    vazio = io.BytesIO()
    with zipfile.ZipFile(vazio, "w") as z:
        z.writestr("word/media/logo.png", b"x")
    falhas += checar(peticao_local.analisar_estilo(vazio.getvalue()) == {}, "sem estilos, dict vazio, sem erro")

    print("TODOS OS TESTES PASSARAM" if not falhas else f"{falhas} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
