"""Leitura do arquivo da entrevista de atendimento.

O que o advogado tem depois de atender um cliente é um arquivo: as anotações digitadas, o
roteiro preenchido, às vezes a transcrição de uma gravação. Este módulo tira o **texto** dele
— é o texto que a IA lê e que a tela mostra. O arquivo original continua guardado e
baixável, porque a formatação e as marcações de quem atendeu não cabem em texto puro.

Sem dependência nova: `.docx` é um zip com XML dentro, e o PDF já tem o `pypdfium2` que o
OCR usa. PDF **digitalizado** (imagem) não é tratado aqui de propósito — para isso existe o
caminho de documento do checklist, que roda OCR de verdade; devolver texto vazio com um aviso
é mais honesto do que fingir uma leitura.
"""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from pathlib import Path

__all__ = ["EXTENSOES_ENTREVISTA", "ErroDeLeitura", "extrair_texto"]

#: O que o escritório efetivamente produz num atendimento.
EXTENSOES_ENTREVISTA = {
    ".txt", ".md", ".docx", ".pdf", ".csv", ".tsv", ".json", ".jsonl",
    ".xml", ".html", ".htm", ".log", ".rtf", ".yaml", ".yml", ".srt", ".vtt",
}

#: Acima disto não é entrevista: é juntada de várias sessões ou arquivo errado.
LIMITE_CARACTERES = 200_000


class ErroDeLeitura(ValueError):
    """Arquivo que não dá para ler como entrevista, com o motivo em português."""


def extrair_texto(nome: str, conteudo: bytes) -> str:
    extensao = Path(nome).suffix.lower()
    if extensao == ".docx":
        texto = _texto_docx(conteudo)
    elif extensao == ".pdf":
        texto = _texto_pdf(conteudo)
    elif extensao in EXTENSOES_ENTREVISTA or _parece_texto(conteudo):
        texto = _texto_simples(conteudo)
    else:
        raise ErroDeLeitura(
            f"O arquivo {extensao or '(sem extensão)'} não parece conter texto legível. "
            "Envie um arquivo textual, DOCX ou PDF."
        )

    limpo = _normalizar(texto)
    if not limpo:
        raise ErroDeLeitura(
            "Não foi possível ler texto deste arquivo. Se for um PDF digitalizado, "
            "envie-o como documento do checklist para passar pelo OCR."
        )
    return limpo[:LIMITE_CARACTERES]


def _texto_simples(conteudo: bytes) -> str:
    for codificacao in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return conteudo.decode(codificacao)
        except UnicodeDecodeError:
            continue
    # `latin-1` aceita qualquer byte, então chegar aqui significa arquivo vazio.
    return ""


def _parece_texto(conteudo: bytes) -> bool:
    """Aceita extensões desconhecidas quando o conteúdo é realmente textual."""
    amostra = conteudo[:64 * 1024]
    if not amostra or b"\x00" in amostra:
        return False
    for codificacao in ("utf-8", "cp1252"):
        try:
            texto = amostra.decode(codificacao)
        except UnicodeDecodeError:
            continue
        legiveis = sum(caractere.isprintable() or caractere in "\r\n\t" for caractere in texto)
        return legiveis / max(len(texto), 1) >= 0.85
    return False


#: Um parágrafo do WordprocessingML. `w:p` é o parágrafo e `w:t` o texto dentro dele.
_PARAGRAFO = re.compile(rb"<w:p[ >].*?</w:p>", re.DOTALL)
_TEXTO = re.compile(rb"<w:t[^>]*>(.*?)</w:t>", re.DOTALL)
_TAG = re.compile(rb"<[^>]+>")


def _texto_docx(conteudo: bytes) -> str:
    """Extrai parágrafo a parágrafo, preservando as quebras.

    Concatenar todos os `w:t` de uma vez colaria as falas umas nas outras — e numa
    entrevista a quebra de linha é o que separa a pergunta da resposta.
    """
    try:
        with zipfile.ZipFile(BytesIO(conteudo)) as arquivo:
            documento = arquivo.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as erro:
        raise ErroDeLeitura("Arquivo .docx inválido ou corrompido.") from erro

    linhas: list[str] = []
    for paragrafo in _PARAGRAFO.findall(documento):
        pedacos = [_TAG.sub(b"", trecho) for trecho in _TEXTO.findall(paragrafo)]
        linhas.append(b"".join(pedacos).decode("utf-8", errors="replace"))
    return "\n".join(linhas)


def _texto_pdf(conteudo: bytes) -> str:
    """Texto nativo do PDF. Sem OCR: PDF de imagem devolve vazio, e isso é dito."""
    try:
        import pypdfium2 as pdfium
    except ImportError as erro:  # pragma: no cover - protegido por requirements.txt
        raise ErroDeLeitura("O suporte a PDF não está instalado no servidor.") from erro

    try:
        with pdfium.PdfDocument(conteudo) as documento:
            paginas = []
            for indice in range(len(documento)):
                pagina = documento[indice]
                textpage = pagina.get_textpage()
                paginas.append(textpage.get_text_range())
    except Exception as erro:  # pragma: no cover - pdfium levanta tipos variados
        raise ErroDeLeitura("Não foi possível abrir este PDF.") from erro
    return "\n".join(paginas)


def _normalizar(texto: str) -> str:
    """Tira o \\r do Windows e as linhas em branco repetidas, sem mexer no conteúdo."""
    sem_cr = texto.replace("\r\n", "\n").replace("\r", "\n")
    linhas = [linha.rstrip() for linha in sem_cr.split("\n")]
    resultado: list[str] = []
    for linha in linhas:
        if not linha and resultado[-1:] == [""]:
            continue
        resultado.append(linha)
    return "\n".join(resultado).strip()
