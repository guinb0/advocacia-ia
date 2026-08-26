"""Testes dos dígitos verificadores. Rodar: .venv\\Scripts\\python.exe -m tests.test_validators"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import validators as V  # noqa: E402

CASOS = [
    # (função, valor, esperado, descrição)
    (V.validar_cpf, "111.444.777-35", True, "CPF válido formatado"),
    (V.validar_cpf, "11144477735", True, "CPF válido sem máscara"),
    (V.validar_cpf, "11144477736", False, "CPF com DV errado"),
    (V.validar_cpf, "111.111.111-11", False, "CPF com todos dígitos iguais"),
    (V.validar_cpf, "1114447773", False, "CPF com 10 dígitos"),

    (V.validar_cnpj, "11.222.333/0001-81", True, "CNPJ válido"),
    (V.validar_cnpj, "11222333000182", False, "CNPJ com DV errado"),

    (V.validar_pis, "12012345672", True, "PIS válido"),
    (V.validar_pis, "12012345671", False, "PIS com DV errado"),

    (V.validar_cnh, "12345678900", True, "CNH válida"),
    (V.validar_cnh, "12345678901", False, "CNH com DV errado"),

    (V.validar_titulo_eleitor, "123456780191", True, "Título válido"),
    (V.validar_titulo_eleitor, "123456780192", False, "Título com DV errado"),
    (V.validar_titulo_eleitor, "123456789991", False, "Título com UF inexistente"),

    (V.validar_cns, "123456789010000", True, "CNS definitivo válido"),
    (V.validar_cns, "123456789010001", False, "CNS com DV errado"),

    (V.validar_cep, "30130-010", True, "CEP válido"),
    (V.validar_cep, "3013001", False, "CEP com 7 dígitos"),

    (V.validar_data_nascimento, "15/03/1990", True, "Data de nascimento plausível"),
    (V.validar_data_nascimento, "15/03/2090", False, "Data de nascimento no futuro"),
    (V.validar_data_nascimento, "32/13/1990", False, "Data inexistente"),
    (V.validar_data_generica, "10/01/2030", True, "Validade futura aceita"),
]

FORMATACAO = [
    (V.formatar_cpf, "11144477735", "111.444.777-35"),
    (V.formatar_cnpj, "11222333000181", "11.222.333/0001-81"),
    (V.formatar_pis, "12012345672", "120.12345.67-2"),
    (V.formatar_cns, "123456789010000", "123 4567 8901 0000"),
]


def main() -> int:
    falhas = 0

    for fn, valor, esperado, desc in CASOS:
        obtido = fn(valor)
        ok = obtido == esperado
        falhas += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {desc:38} {valor!r} -> {obtido} (esperado {esperado})")

    print()
    for fn, entrada, esperado in FORMATACAO:
        obtido = fn(entrada)
        ok = obtido == esperado
        falhas += not ok
        print(f"{'PASS' if ok else 'FAIL'}  formatar {entrada!r} -> {obtido!r} (esperado {esperado!r})")

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
