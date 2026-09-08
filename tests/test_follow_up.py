"""A regra do relatório de follow-up: quando o cliente 'precisa ligar'.

Não toca o banco: prova só o critério que decide o alerta de ligação, que é o
que a issue pede definir e destacar. Ver `carteira._precisa_ligar`.

    PYTHONPATH=. .venv/Scripts/python.exe tests/test_follow_up.py
"""

from __future__ import annotations

from app import carteira


def checar(cond: bool, desc: str, detalhe: str = "") -> int:
    print(f"  {'PASS' if cond else '>> FALHA'} {desc}" + (f" ({detalhe})" if detalhe and not cond else ""))
    return 0 if cond else 1


def main_teste() -> int:
    falhas = 0
    liga = carteira._precisa_ligar

    # sem telefone: só dá para ligar, independente do resto
    precisa, _ = liga("", {"ativa": 1}, 0)
    falhas += checar(precisa, "sem telefone sempre precisa ligar")

    # WhatsApp do follow-up falhou
    precisa, motivo = liga("21999998888", {"ativa": 1, "ultimo_erro": "timeout"}, 1)
    falhas += checar(precisa and "falhou" in motivo, "erro no follow-up precisa ligar")

    # sem follow-up e parado além do prazo de cobrança
    precisa, _ = liga("21999998888", None, carteira.DIAS_PARA_COBRAR)
    falhas += checar(precisa, "sem follow-up e parado >= prazo precisa ligar")

    # sem follow-up mas ainda dentro do prazo: não liga
    precisa, _ = liga("21999998888", {"ativa": 0}, carteira.DIAS_PARA_COBRAR - 1)
    falhas += checar(not precisa, "sem follow-up mas recente NÃO precisa ligar")

    # follow-up ativo e recente: não liga (o WhatsApp está cuidando)
    precisa, _ = liga("21999998888", {"ativa": 1}, carteira.DIAS_PARA_COBRAR)
    falhas += checar(not precisa, "follow-up ativo e dentro do prazo NÃO precisa ligar")

    # follow-up ativo mas parado tempo demais: liga assim mesmo
    precisa, _ = liga("21999998888", {"ativa": 1}, carteira.DIAS_PARA_LIGAR)
    falhas += checar(precisa, "follow-up ativo mas parado demais precisa ligar")

    print("TODOS OS TESTES PASSARAM" if not falhas else f"{falhas} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
