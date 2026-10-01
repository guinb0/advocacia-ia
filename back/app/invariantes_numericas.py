"""Invariantes numéricas e de identificação da peça final, resolvidas por CÓDIGO e não por prompt.

O que aqui vive nunca é deixado ao modelo: valor por extenso, dígito verificador de CPF/CNPJ, data do fecho,
letras duplicadas na lista de pedidos, e as verificações que impedem o PDF (conta que não fecha, sobrevida
impossível, mesmo identificador escrito de dois jeitos).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

_UNIDADES = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze",
             "treze", "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"]
_DEZENAS = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
_CENTENAS = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos", "oitocentos", "novecentos"]


def _ate_999(n: int) -> str:
    if n == 100:
        return "cem"
    partes = []
    if n >= 100:
        partes.append(_CENTENAS[n // 100])
        n %= 100
    if n >= 20:
        partes.append(_DEZENAS[n // 10] + (f" e {_UNIDADES[n % 10]}" if n % 10 else ""))
    elif n > 0:
        partes.append(_UNIDADES[n])
    return " e ".join(partes)


def inteiro_por_extenso(n: int) -> str:
    if n == 0:
        return "zero"
    grupos: list[str] = []
    for singular, plural, base in (("bilhão", "bilhões", 10**9), ("milhão", "milhões", 10**6), ("mil", "mil", 10**3)):
        q, n = divmod(n, base)
        if q:
            grupos.append("mil" if base == 1000 and q == 1 else f"{_ate_999(q)} {singular if q == 1 else plural}")
    resto = n
    if resto:
        grupos.append(_ate_999(resto))
    if len(grupos) == 1:
        return grupos[0]
    # «mil e quinhentos», «mil e cem», mas «noventa e seis mil, duzentos e sete»: o «e» só liga o último
    # grupo quando ele é menor que 100 ou centena exata; sem resto, o último grupo é o milhar/milhão.
    liga_com_e = (not resto) or resto < 100 or resto % 100 == 0
    return ", ".join(grupos[:-1]) + (" e " if liga_com_e else ", ") + grupos[-1]


def reais_por_extenso(valor: float) -> str:
    centavos_total = int(round(float(valor) * 100))
    reais, centavos = divmod(centavos_total, 100)
    partes = []
    if reais or not centavos:
        de = " de" if reais and reais % 10**6 == 0 else ""
        partes.append(f"{inteiro_por_extenso(reais)}{de} {'real' if reais == 1 else 'reais'}")
    if centavos:
        partes.append(f"{inteiro_por_extenso(centavos)} {'centavo' if centavos == 1 else 'centavos'}")
    return " e ".join(partes)


def _float(texto: str) -> float:
    return float(texto.replace(".", "").replace(",", "."))


def _formatar(valor: float) -> str:
    return f"{valor:,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")


_VALOR_E_EXTENSO = re.compile(r"(R\$\s*)([\d.]+,\d{2})(\s*\()([^()\n]*?\b(?:reais?|centavos?)\b[^()\n]*)(\))", re.IGNORECASE)


def sincronizar_extenso(secoes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """O extenso entre parênteses é sempre derivado do número que o precede."""
    trocas = 0

    def trocar(m: re.Match[str]) -> str:
        nonlocal trocas
        correto = reais_por_extenso(_float(m.group(2)))
        if m.group(4).strip().lower() != correto:
            trocas += 1
        return f"{m.group(1)}{m.group(2)}{m.group(3)}{correto}{m.group(5)}"

    novas = [{**s, "content": _VALOR_E_EXTENSO.sub(trocar, s["content"])} if isinstance(s.get("content"), str) else s for s in secoes]
    return novas, trocas


_CNPJ = re.compile(r"\b(\d{2})\.(\d{3})\.(\d{3})/(\d{4})-(\d{2})\b")
_CPF = re.compile(r"\b(\d{3})\.(\d{3})\.(\d{3})-(\d{2})\b")


def _dv_cnpj(base12: str) -> str:
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = sum(int(a) * b for a, b in zip(base12, pesos1)) % 11
    d1 = 0 if d1 < 2 else 11 - d1
    pesos2 = [6, *pesos1]
    d2 = sum(int(a) * b for a, b in zip(base12 + str(d1), pesos2)) % 11
    d2 = 0 if d2 < 2 else 11 - d2
    return f"{d1}{d2}"


def _dv_cpf(base9: str) -> str:
    d1 = sum(int(a) * b for a, b in zip(base9, range(10, 1, -1))) * 10 % 11 % 10
    d2 = sum(int(a) * b for a, b in zip(base9 + str(d1), range(11, 1, -1))) * 10 % 11 % 10
    return f"{d1}{d2}"


def cnpj_valido(cnpj: str) -> bool:
    d = re.sub(r"\D", "", cnpj)
    return len(d) == 14 and len(set(d)) > 1 and _dv_cnpj(d[:12]) == d[12:]


def cpf_valido(cpf: str) -> bool:
    d = re.sub(r"\D", "", cpf)
    return len(d) == 11 and len(set(d)) > 1 and _dv_cpf(d[:9]) == d[9:]


def corrigir_digitos_verificadores(secoes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """OCR erra o dígito final com frequência; ele é função dos demais, então se recalcula."""
    corrigidos: list[dict[str, str]] = []

    def cnpj(m: re.Match[str]) -> str:
        base = "".join(m.group(i) for i in range(1, 5))
        dv = _dv_cnpj(base)
        if dv == m.group(5):
            return m.group(0)
        novo = f"{m.group(1)}.{m.group(2)}.{m.group(3)}/{m.group(4)}-{dv}"
        corrigidos.append({"tipo": "CNPJ", "de": m.group(0), "para": novo})
        return novo

    def cpf(m: re.Match[str]) -> str:
        base = "".join(m.group(i) for i in range(1, 4))
        if len(set(base)) == 1:
            return m.group(0)
        dv = _dv_cpf(base)
        if dv == m.group(4):
            return m.group(0)
        novo = f"{m.group(1)}.{m.group(2)}.{m.group(3)}-{dv}"
        corrigidos.append({"tipo": "CPF", "de": m.group(0), "para": novo})
        return novo

    novas = []
    for s in secoes:
        c = s.get("content")
        if isinstance(c, str) and c:
            s = {**s, "content": _CPF.sub(cpf, _CNPJ.sub(cnpj, c))}
        novas.append(s)
    return novas, corrigidos


_DATA_VAZIA = re.compile(r"(?m)^([ \t]*[^\n,\[\]]{3,60}/[A-Z]{2}),[ \t]*\.?[ \t]*$")


def preencher_data_do_fecho(secoes: list[dict[str, Any]], hoje: date) -> tuple[list[dict[str, Any]], int]:
    from .juridico import datas

    n = 0
    novas = []
    for s in secoes:
        c = s.get("content")
        if isinstance(c, str) and _DATA_VAZIA.search(c):
            c, k = _DATA_VAZIA.subn(lambda m: f"{m.group(1)}, {datas.por_extenso(hoje)}.", c)
            n += k
            s = {**s, "content": c}
        novas.append(s)
    return novas, n


_LETRA_DUPLICADA = re.compile(r"(?m)^([ \t]*)([a-z])\)[ \t]+\2\)[ \t]+")


def sem_letra_duplicada(secoes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    n = 0
    novas = []
    for s in secoes:
        c = s.get("content")
        if isinstance(c, str) and _LETRA_DUPLICADA.search(c):
            c, k = _LETRA_DUPLICADA.subn(r"\1\2) ", c)
            n += k
            s = {**s, "content": c}
        novas.append(s)
    return novas, n


# ----------------------------------------------------------------------------- verificações que bloqueiam

_CONTA = re.compile(r"R\$\s*([\d.]+,\d{2})\s*[×x]\s*([\d.]+(?:,\d+)?)\s*\|\s*R\$\s*([\d.]+,\d{2})")
_IDADE = re.compile(r"\baos\s+(\d{2})\s+anos\b", re.IGNORECASE)
_PERIODO = re.compile(r"pensionamento[^|\n]{0,80}?(\d{1,3}(?:[.,]\d+)?)\s*anos", re.IGNORECASE)
_NB = re.compile(r"\bNB\s*(\d{3}\.?\d{3}\.?\d{3}-?\d)\b")
LIMITE_DE_IDADE_NO_PENSIONAMENTO = 85


def contas_que_nao_fecham(texto: str) -> list[str]:
    erradas = []
    for m in _CONTA.finditer(texto):
        a, b, c = _float(m.group(1)), float(m.group(2).replace(".", "").replace(",", ".")), _float(m.group(3))
        casas = len(m.group(2).split(",")[1]) if "," in m.group(2) else 0
        folga = a * 0.5 * 10 ** -casas + 0.05  # o fator vem arredondado na sua última casa
        if abs(a * b - c) > folga:
            erradas.append(f"R$ {m.group(1)} × {m.group(2)} = R$ {_formatar(a * b)}, mas a peça informa R$ {m.group(3)}")
    return erradas


def sobrevida_impossivel(texto: str) -> str:
    idade, periodo = _IDADE.search(texto), _PERIODO.search(texto)
    if not (idade and periodo):
        return ""
    anos = float(periodo.group(1).replace(",", "."))
    if int(idade.group(1)) + anos > LIMITE_DE_IDADE_NO_PENSIONAMENTO:
        return f"pensionamento de {periodo.group(1)} anos para quem tem {idade.group(1)}: iria além dos {LIMITE_DE_IDADE_NO_PENSIONAMENTO} anos"
    return ""


def identificadores_divergentes(texto: str) -> list[str]:
    """NBs que diferem por 1 ou 2 dígitos são o mesmo benefício escrito de dois jeitos (erro de OCR ou de digitação)."""
    nbs = sorted({re.sub(r"\D", "", m) for m in _NB.findall(texto)})
    suspeitos: set[str] = set()
    for i, a in enumerate(nbs):
        for b in nbs[i + 1:]:
            if len(a) == len(b) and sum(x != y for x, y in zip(a, b)) <= 2:
                suspeitos.update((a, b))
    return sorted(suspeitos)
