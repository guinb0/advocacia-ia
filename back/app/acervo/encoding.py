"""Bytes da fonte oficial → texto. Texto de lei com erro de codificação é FALHA, nunca dado.

Ordem: BOM → charset declarado (cabeçalho HTTP ou <meta>) → UTF-8 → Windows-1252. Cada tentativa
só vale se o resultado não tiver caractere de substituição, controle C1 nem sequência de mojibake
(UTF-8 lido como Latin-1/1252: "Ã§", "Ã£", "Ã¡", "â€“", "â€œ", "Â§", "Âº"). Nunca `errors='replace'`.

Reparo seguro: se todas as leituras saem com mojibake, tenta desfazer a dupla codificação
(`texto.encode('cp1252').decode('utf-8')`). Só aceita se o resultado sair limpo E o reparo for
reversível (codificar de volta dá o texto de antes). Qualquer dúvida vira ErroEncoding: a norma fica
em ERRO e não ganha embedding.
"""

from __future__ import annotations

import re
import unicodedata

#: UTF-8 interpretado como Latin-1/1252. "Ã" sozinho é legítimo ("CONSTITUIÇÃO"); o par não é.
MOJIBAKE = re.compile(r"(?:Ã|Â)[\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc\u2013-\u203a\u20ac\u2122]|â€[\u0080-\u00bf\u2018-\u203a\u2122\u0153\u02dc]")
_C1 = re.compile(r"[\u0080-\u009f]")
_META = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_\-]+)""", re.I)
_NOMES = {"utf8": "utf-8", "utf-8": "utf-8", "iso-8859-1": "cp1252", "latin1": "cp1252", "latin-1": "cp1252",
          "windows-1252": "cp1252", "cp1252": "cp1252", "us-ascii": "utf-8", "ascii": "utf-8"}


class ErroEncoding(ValueError):
    """ENCODING_CORROMPIDO: nenhum decoder seguro produziu texto válido."""


def corrompido(texto: str) -> bool:
    return "\ufffd" in texto or bool(MOJIBAKE.search(texto)) or bool(_C1.search(texto))


def reparar(texto: str) -> str | None:
    """Desfaz UTF-8 lido como Windows-1252, se o reparo for limpo e reversível; senão None."""
    if not MOJIBAKE.search(texto):
        return None
    try:
        reparado = texto.encode("cp1252").decode("utf-8")
        reversivel = reparado.encode("utf-8").decode("cp1252") == texto
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    if corrompido(reparado) or not reversivel:
        return None
    return reparado


def _declarado(bruto: bytes, content_type: str | None) -> str | None:
    m = re.search(r"charset\s*=\s*([\w\-]+)", content_type or "", re.I)
    nome = m[1] if m else None
    if not nome:
        mm = _META.search(bruto[:4096])
        nome = mm[1].decode("ascii", "ignore") if mm else None
    return _NOMES.get((nome or "").strip().lower()) if nome else None


def decodificar(bruto: bytes, content_type: str | None = None) -> tuple[str, str]:
    """(texto, encoding usado). Levanta `ErroEncoding` se nada produzir texto íntegro."""
    tentativas: list[tuple[str, str]] = []
    if bruto.startswith(b"\xef\xbb\xbf"):
        tentativas.append(("utf-8-sig", "utf-8"))
    elif bruto.startswith((b"\xff\xfe", b"\xfe\xff")):
        tentativas.append(("utf-16", "utf-16"))
    declarado = _declarado(bruto, content_type)
    if declarado:
        tentativas.append((declarado, "windows-1252" if declarado == "cp1252" else declarado))
    tentativas += [("utf-8", "utf-8"), ("cp1252", "windows-1252")]
    vistos: set[str] = set()
    lidos: list[tuple[str, str]] = []
    for codec, nome in tentativas:
        if codec in vistos:
            continue
        vistos.add(codec)
        try:
            texto = bruto.decode(codec)
        except UnicodeDecodeError:
            continue
        if not corrompido(texto):
            return texto, nome
        lidos.append((texto, nome))
    for texto, nome in lidos:
        reparado = reparar(texto)
        if reparado is not None:
            return reparado, f"{nome}+reparo-dupla-codificacao"
    raise ErroEncoding("ENCODING_CORROMPIDO: nenhum decoder seguro produziu texto jurídico válido")


def normalizar(texto: str) -> str:
    """NFC, sem NUL, espaços colapsados por linha e linhas vazias/repetidas fora. Não muda letra nenhuma."""
    texto = unicodedata.normalize("NFC", texto.replace("\x00", "").replace("\u00a0", " "))
    linhas: list[str] = []
    for linha in texto.splitlines():
        linha = re.sub(r"[ \t\r\f\v]+", " ", linha).strip()
        if linha and (not linhas or linhas[-1] != linha):
            linhas.append(linha)
    saida = "\n".join(linhas)
    if corrompido(saida):
        reparado = reparar(saida)
        if reparado is None:
            raise ErroEncoding("ENCODING_CORROMPIDO após normalização")
        saida = reparado
    return saida
