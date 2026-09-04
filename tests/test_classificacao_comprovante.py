"""Comprovante de residência é conta de concessionária — não qualquer papel.

Antes, termos genéricos ("nota fiscal", "total a pagar", "cliente", "CEP")
faziam recibo de Uber, resumo de alta hospitalar e boleto qualquer caírem em
comprovante de residência. Agora só uma conta de luz/água/gás (ou o nome da
concessionária) classifica; o resto vai para leitura semântica.

    PYTHONPATH=. .venv/Scripts/python.exe tests/test_classificacao_comprovante.py
"""

from __future__ import annotations

from app.extractors import classificar, normalizar


def checar(cond: bool, desc: str, detalhe: str = "") -> int:
    print(f"  {'PASS' if cond else '>> FALHA'} {desc}" + (f" ({detalhe})" if detalhe and not cond else ""))
    return 0 if cond else 1


NAO_COMPROVANTE = {
    "recibo de Uber": "Recibo Uber Viagem Motorista Ponto de partida CEP Nota Fiscal Total a pagar Cliente",
    "resumo de alta hospitalar": (
        "Resumo de Alta Hospitalar Paciente Data da internacao Data da alta Diagnostico "
        "exposicao ossea do 3 dedo Procedimento enxerto de pele CEP Cliente Total"
    ),
    "boleto genérico": "Nota Fiscal Codigo de barras Total a pagar Vencimento CEP Cliente",
}

COMPROVANTE = {
    "conta CEMIG": "CEMIG Conta de energia eletrica Unidade Consumidora kWh Vencimento CEP Total a pagar",
    "conta de água COPASA": "COPASA Conta de agua Leitura anterior Leitura atual Vencimento CEP",
    "conta ENEL": "ENEL Distribuicao Energia eletrica kWh Consumo faturado Vencimento",
}


def main_teste() -> int:
    falhas = 0
    print("\nNÃO é comprovante de residência")
    for nome, texto in NAO_COMPROVANTE.items():
        tipo = classificar(normalizar(texto))[0]
        falhas += checar(tipo != "comprovante_residencia", f"{nome} não vira comprovante", tipo)

    print("\nÉ comprovante de residência (conta de concessionária)")
    for nome, texto in COMPROVANTE.items():
        tipo = classificar(normalizar(texto))[0]
        falhas += checar(tipo == "comprovante_residencia", f"{nome} classifica como comprovante", tipo)

    print("\nTODOS OS TESTES PASSARAM" if not falhas else f"\n{falhas} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
