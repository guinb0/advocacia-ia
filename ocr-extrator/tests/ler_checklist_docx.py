"""Lê um checklist em .docx preservando a cor de cada item (vermelho = obrigatório).

Serve para transcrever um checklist novo do escritório para `app/categorias.py`.
Não depende de python-docx: um .docx é um zip com XML dentro.

    .venv\\Scripts\\python.exe -m tests.ler_checklist_docx "docs\\CHECK LIST ....docx"
"""

import sys
import zipfile
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _texto(elemento) -> str:
    return "".join(t.text or "" for t in elemento.iter(f"{W}t"))


def _formatacao(run) -> tuple[str | None, str | None]:
    """(cor da fonte, marca-texto) de um <w:r>."""
    rpr = run.find(f"{W}rPr")
    if rpr is None:
        return None, None
    cor = rpr.find(f"{W}color")
    marca = rpr.find(f"{W}highlight")
    return (
        cor.get(f"{W}val") if cor is not None else None,
        marca.get(f"{W}val") if marca is not None else None,
    )


def eh_vermelho(cor: str | None, marca: str | None) -> bool:
    if marca and "red" in marca.lower():
        return True
    if not cor or cor.lower() in ("auto", "000000"):
        return False
    try:
        r, g, b = int(cor[0:2], 16), int(cor[2:4], 16), int(cor[4:6], 16)
    except (ValueError, IndexError):
        return False
    # Vermelho dominante: canal R alto e bem acima dos outros dois.
    return r > 120 and r > g * 1.6 and r > b * 1.6


def ler(caminho: str) -> list[dict]:
    with zipfile.ZipFile(caminho) as z:
        raiz = ET.fromstring(z.read("word/document.xml"))

    corpo = raiz.find(f"{W}body")
    itens: list[dict] = []

    for p in corpo.iter(f"{W}p"):
        trechos, cores, vermelho = [], set(), False
        for r in p.findall(f"{W}r"):
            texto = _texto(r)
            if not texto.strip():
                continue
            cor, marca = _formatacao(r)
            if cor:
                cores.add(cor)
            if eh_vermelho(cor, marca):
                vermelho = True
            trechos.append(texto)

        linha = "".join(trechos).strip()
        if linha:
            itens.append({"texto": linha, "obrigatorio": vermelho, "cores": sorted(cores)})

    return itens


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    itens = ler(sys.argv[1])
    # stdout do Windows costuma ser cp1252 e engole os acentos.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    for item in itens:
        print(f"{'[X]' if item['obrigatorio'] else '[ ]'} {item['texto']}")

    print(f"\n{len(itens)} linhas · {sum(i['obrigatorio'] for i in itens)} em vermelho")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
