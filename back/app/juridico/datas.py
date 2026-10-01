"""Datas no texto da peça: numéricas (05/12/2024, 05.12.2024, 2024-12-05), por extenso («5 de dezembro de
2024», «1º de maio de 2025») e de mês («dezembro de 2024»). Usado pelo fechamento renderizado e pelo auditor
temporal — a mesma leitura nos dois lados.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho",
         "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")
_MES = r"janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro"
_NUM_MES = {m: i for i, m in enumerate(("janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
                                         "setembro", "outubro", "novembro", "dezembro"), start=1)}

_EXTENSO = re.compile(rf"\b(\d{{1,2}})\s*(?:º|°|o\b)?\s+de\s+({_MES})\s+de\s+(\d{{4}})\b", re.I)
_NUMERICA = re.compile(r"(?<![\d/.])(\d{1,2})[/.](\d{1,2})[/.](\d{4})(?![\d/])")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MES_ANO = re.compile(rf"\b(?:em\s+|de\s+)?({_MES})\s+(?:de\s+)?(\d{{4}})\b", re.I)
#: Marcador de modelo que nunca pode chegar à peça: «[data por extenso]», «[dia] de [mês] de [ano]», «[local e data]»…
PLACEHOLDER = re.compile(r"\[\s*(?:data(?:\s+(?:por\s+extenso|atual|da\s+assinatura))?|dia|m[eê]s|ano|local(?:\s+e\s+data)?)\s*\]", re.I)


@dataclass(frozen=True)
class DataNoTexto:
    valor: date
    trecho: str
    inicio: int
    fim: int
    precisao: str  # dia | mes


def _mes(nome: str) -> int:
    return _NUM_MES[nome.lower().replace("ç", "c")]


def _criar(a: int, m: int, d: int) -> date | None:
    try:
        return date(a, m, d)
    except ValueError:
        return None


def extrair(texto: str) -> list[DataNoTexto]:
    texto = str(texto or "")
    achadas: list[DataNoTexto] = []
    ocupado: list[tuple[int, int]] = []

    def livre(i: int, f: int) -> bool:
        return all(f <= a or i >= b for a, b in ocupado)

    def add(d: date | None, m: re.Match[str], precisao: str) -> None:
        if d and livre(m.start(), m.end()):
            achadas.append(DataNoTexto(d, m.group(0), m.start(), m.end(), precisao))
            ocupado.append((m.start(), m.end()))

    for m in _EXTENSO.finditer(texto):
        add(_criar(int(m[3]), _mes(m[2]), int(m[1])), m, "dia")
    for m in _NUMERICA.finditer(texto):
        add(_criar(int(m[3]), int(m[2]), int(m[1])), m, "dia")
    for m in _ISO.finditer(texto):
        add(_criar(int(m[1]), int(m[2]), int(m[3])), m, "dia")
    for m in _MES_ANO.finditer(texto):
        add(_criar(int(m[2]), _mes(m[1]), 1), m, "mes")
    return sorted(achadas, key=lambda x: x.inicio)


def posterior(d: DataNoTexto, referencia: date) -> bool:
    if d.precisao == "mes":
        return (d.valor.year, d.valor.month) > (referencia.year, referencia.month)
    return d.valor > referencia


def por_extenso(d: date) -> str:
    dia = "1º" if d.day == 1 else str(d.day)
    return f"{dia} de {MESES[d.month - 1]} de {d.year}"
