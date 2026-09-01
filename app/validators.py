"""Validadores de documentos brasileiros (dígitos verificadores e sanidade de datas)."""

from __future__ import annotations

import re
from datetime import date, datetime

# ---------------------------------------------------------------- utilitários


def only_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _all_same(digits: str) -> bool:
    return len(set(digits)) == 1


# ------------------------------------------------------------------- CPF


def validar_cpf(cpf: str) -> bool:
    """Valida os dois dígitos verificadores do CPF (módulo 11)."""
    d = only_digits(cpf)
    if len(d) != 11 or _all_same(d):
        return False

    for pos in (9, 10):
        soma = sum(int(d[i]) * (pos + 1 - i) for i in range(pos))
        dv = (soma * 10) % 11
        if dv == 10:
            dv = 0
        if dv != int(d[pos]):
            return False
    return True


def formatar_cpf(cpf: str) -> str:
    d = only_digits(cpf)
    if len(d) != 11:
        return cpf
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


# ------------------------------------------------------------------- CNPJ


def validar_cnpj(cnpj: str) -> bool:
    d = only_digits(cnpj)
    if len(d) != 14 or _all_same(d):
        return False

    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1

    for pesos, pos in ((pesos1, 12), (pesos2, 13)):
        soma = sum(int(d[i]) * pesos[i] for i in range(pos))
        resto = soma % 11
        dv = 0 if resto < 2 else 11 - resto
        if dv != int(d[pos]):
            return False
    return True


def formatar_cnpj(cnpj: str) -> str:
    d = only_digits(cnpj)
    if len(d) != 14:
        return cnpj
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


# --------------------------------------------------------------- PIS/PASEP


def validar_pis(pis: str) -> bool:
    """PIS/PASEP/NIT — 11 dígitos, DV por módulo 11 com pesos 3..2."""
    d = only_digits(pis)
    if len(d) != 11 or _all_same(d):
        return False

    pesos = [3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    soma = sum(int(d[i]) * pesos[i] for i in range(10))
    resto = soma % 11
    dv = 0 if resto < 2 else 11 - resto
    return dv == int(d[10])


def formatar_pis(pis: str) -> str:
    d = only_digits(pis)
    if len(d) != 11:
        return pis
    return f"{d[:3]}.{d[3:8]}.{d[8:10]}-{d[10]}"


# ------------------------------------------------------------------- CNH


def validar_cnh(cnh: str) -> bool:
    """Número de registro da CNH — 11 dígitos, algoritmo do Denatran."""
    d = only_digits(cnh)
    if len(d) != 11 or _all_same(d):
        return False

    soma = sum(int(d[i]) * (9 - i) for i in range(9))
    dsc = 0
    dv1 = soma % 11
    if dv1 >= 10:
        dv1 = 0
        dsc = 2

    soma2 = sum(int(d[i]) * (1 + i) for i in range(9))
    dv2 = soma2 % 11
    if dv2 >= 10:
        dv2 = 0
    else:
        dv2 = dv2 - dsc
        if dv2 < 0:
            dv2 += 11

    return dv1 == int(d[9]) and dv2 == int(d[10])


# --------------------------------------------------------- Título de eleitor


def validar_titulo_eleitor(titulo: str) -> bool:
    d = only_digits(titulo)
    if len(d) != 12:
        return False

    uf = int(d[8:10])
    if uf < 1 or uf > 28:
        return False

    seq = d[:8]
    soma = sum(int(seq[i]) * (i + 2) for i in range(8))
    dv1 = soma % 11
    if dv1 == 10:
        dv1 = 0
    if dv1 != int(d[10]):
        return False

    base = d[8:10] + str(dv1)
    soma2 = sum(int(base[i]) * (i + 7) for i in range(3))
    dv2 = soma2 % 11
    if dv2 == 10:
        dv2 = 0
    return dv2 == int(d[11])


# ---------------------------------------------------- CNS (Cartão SUS)


def validar_cns(cns: str) -> bool:
    """Cartão Nacional de Saúde — 15 dígitos, módulo 11 com pesos 15..1."""
    d = only_digits(cns)
    if len(d) != 15 or _all_same(d):
        return False

    if d[0] in "789":  # cartão provisório
        soma = sum(int(d[i]) * (15 - i) for i in range(15))
        return soma % 11 == 0

    if d[0] not in "12":
        return False

    pis = d[:11]
    soma = sum(int(pis[i]) * (15 - i) for i in range(11))
    resto = soma % 11
    dv = 11 - resto
    if dv == 11:
        dv = 0
    if dv == 10:
        soma += 2
        resto = soma % 11
        dv = 11 - resto
        esperado = pis + "001" + str(dv)
    else:
        esperado = pis + "000" + str(dv)
    return esperado == d


def formatar_cns(cns: str) -> str:
    d = only_digits(cns)
    if len(d) != 15:
        return cns
    return f"{d[:3]} {d[3:7]} {d[7:11]} {d[11:]}"


# ------------------------------------------------------------ CEP / datas


def validar_cep(cep: str) -> bool:
    d = only_digits(cep)
    return len(d) == 8 and not _all_same(d)


_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y")


def parse_data(texto: str) -> date | None:
    texto = (texto or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    return None


def validar_data_nascimento(texto: str) -> bool:
    d = parse_data(texto)
    if d is None:
        return False
    hoje = date.today()
    idade = hoje.year - d.year - ((hoje.month, hoje.day) < (d.month, d.day))
    return 0 <= idade <= 120


def validar_data_generica(texto: str) -> bool:
    """Aceita qualquer data plausível entre 1900 e 30 anos no futuro."""
    d = parse_data(texto)
    if d is None:
        return False
    return 1900 <= d.year <= date.today().year + 30


# ------------------------------------------------------------------- RG


def validar_rg(rg: str) -> bool:
    """RG não tem regra nacional de DV — validamos apenas o formato plausível."""
    d = only_digits(rg)
    return 5 <= len(d) <= 14


# --------------------------------------------------------------- registry

VALIDADORES = {
    "cpf": validar_cpf,
    "cnpj": validar_cnpj,
    "pis": validar_pis,
    "cnh": validar_cnh,
    "titulo_eleitor": validar_titulo_eleitor,
    "cns": validar_cns,
    "cep": validar_cep,
    "rg": validar_rg,
    "data_nascimento": validar_data_nascimento,
    "data_emissao": validar_data_generica,
    "data_validade": validar_data_generica,
    "data_admissao": validar_data_generica,
}

FORMATADORES = {
    "cpf": formatar_cpf,
    "cnpj": formatar_cnpj,
    "pis": formatar_pis,
    "cns": formatar_cns,
}
