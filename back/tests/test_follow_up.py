"""A regra do relatório de follow-up: quando o cliente 'precisa ligar'.

Não toca o banco: prova só o critério que decide o alerta de ligação, que é o
que a issue pede definir e destacar. Ver `carteira._precisa_ligar`.

    PYTHONPATH=. .venv/Scripts/python.exe tests/test_follow_up.py
"""

from __future__ import annotations

from datetime import datetime, timedelta

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

    precisa, motivo = liga(
        "",
        {"ativa": 1, "ultimo_erro": "timeout"},
        carteira.DIAS_PARA_LIGAR,
        {"id": "call-1"},
    )
    falhas += checar(
        not precisa and motivo == "Ligação registrada.",
        "ligação sem data legível silencia o alerta (o conservador)",
    )

    # A JANELA DA LIGAÇÃO — o buraco que a fila tinha.
    #
    # Antes bastava existir UMA ligação, de qualquer época, para o caso sair da
    # aba "Ligar" para sempre: quem foi ligado uma vez e nunca mandou documento
    # nenhum não voltava à fila, e o caso apodrecia sem ninguém ver. Agora a
    # ligação silencia pelo prazo e depois devolve o caso para a fila.
    def ha_dias(n: int) -> dict[str, object]:
        return {"id": "call-1", "realizada_em": (datetime.now() - timedelta(days=n)).isoformat()}

    precisa, motivo = liga("", None, 30, ha_dias(0))
    falhas += checar(
        not precisa and motivo == "Ligação registrada.",
        "ligação de hoje tira o caso da fila",
    )

    precisa, _ = liga("", None, 30, ha_dias(carteira.DIAS_APOS_LIGACAO - 1))
    falhas += checar(not precisa, "dentro da janela o caso segue fora da fila")

    precisa, motivo = liga("", None, 30, ha_dias(carteira.DIAS_APOS_LIGACAO + 3))
    falhas += checar(
        precisa and "não chegaram" in motivo,
        "passada a janela sem documento, o caso VOLTA para a fila",
        motivo,
    )

    dias = carteira._dias_desde_ligacao(ha_dias(5))
    falhas += checar(dias == 5, "a tela recebe os dias desde a ligação", str(dias))
    falhas += checar(
        carteira._dias_desde_ligacao({"id": "x"}) is None,
        "sem data, a conta devolve None em vez de inventar",
    )

    print("TODOS OS TESTES PASSARAM" if not falhas else f"{falhas} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
