"""Leitura do texto digital de documentos de escritório (DOCX, TXT).

Ao contrário de uma foto ou PDF escaneado, estes formatos já trazem o texto
gravado — não há imagem a rasterizar nem OCR a rodar. Basta ler o conteúdo e
entregá-lo ao mesmo caminho de classificação e extração de campos do OCR, para
que um DOCX (uma procuração, um contrato) deixe de ficar "preservado sem OCR" e
tenha seus dados lidos e roteados como qualquer outro documento.
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET

# Formatos cujo texto é digital e pode ser lido sem OCR. `.doc` (Word 97-2003) é
# binário e não entra aqui: não é um zip e exigiria conversão externa.
EXTENSOES_TEXTO = {".docx", ".txt"}

# Namespace do WordprocessingML — todo elemento do corpo do DOCX vem com ele.
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class ErroLeituraTexto(ValueError):
    """Arquivo anunciado como texto digital, mas ilegível ou corrompido."""


def _texto_do_paragrafo(paragrafo: ET.Element) -> str:
    """Junta os trechos (`w:t`) de um parágrafo, respeitando tab e quebra."""
    partes: list[str] = []
    for no in paragrafo.iter():
        if no.tag == _W + "t":
            partes.append(no.text or "")
        elif no.tag == _W + "tab":
            partes.append("\t")
        elif no.tag in (_W + "br", _W + "cr"):
            partes.append("\n")
    return "".join(partes)


def extrair_texto_docx(conteudo: bytes) -> str:
    """Texto do corpo de um .docx — um parágrafo por linha, tabelas incluídas.

    O .docx é um zip; o texto vive em `word/document.xml`. Percorrer os `w:p` em
    ordem de documento captura também os parágrafos dentro de células de tabela,
    que é onde muitos formulários guardam nome e CPF.
    """
    if not conteudo:
        raise ErroLeituraTexto("O documento está vazio.")
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
            with arquivo.open("word/document.xml") as documento:
                arvore = ET.parse(documento)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise ErroLeituraTexto(
            "Não foi possível ler o conteúdo do documento Word."
        ) from exc

    linhas = [_texto_do_paragrafo(p) for p in arvore.getroot().iter(_W + "p")]
    return "\n".join(linhas)


def extrair_texto_txt(conteudo: bytes) -> str:
    """Decodifica um .txt tentando as codificações mais comuns em português."""
    for codificacao in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return conteudo.decode(codificacao)
        except UnicodeDecodeError:
            continue
    return conteudo.decode("utf-8", errors="replace")


def extrair_texto(conteudo: bytes, extensao: str) -> str:
    """Roteia para o leitor conforme a extensão. Devolve o texto cru."""
    ext = (extensao or "").lower()
    if ext == ".docx":
        return extrair_texto_docx(conteudo)
    if ext == ".txt":
        return extrair_texto_txt(conteudo)
    raise ErroLeituraTexto(f"Extensão {ext or 'sem extensão'!r} não é texto digital.")
