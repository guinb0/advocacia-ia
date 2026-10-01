"""De qual TRT é cada estado, e a ordem de fallback (estado → região → país).

    PYTHONPATH=. .venv/Scripts/python.exe tests/test_tribunais.py
"""

from __future__ import annotations

from app import tribunais


def checar(cond: bool, desc: str, detalhe: str = "") -> int:
    print(f"  {'PASS' if cond else '>> FALHA'} {desc}" + (f" ({detalhe})" if detalhe and not cond else ""))
    return 0 if cond else 1


def main_teste() -> int:
    falhas = 0

    falhas += checar(tribunais.normalizar_uf("sp") == "SP", "aceita sigla minúscula")
    falhas += checar(tribunais.normalizar_uf("São Paulo") == "SP", "aceita nome por extenso")
    falhas += checar(tribunais.normalizar_uf("Pará") == "PA", "nome com acento vira sigla")
    falhas += checar(tribunais.normalizar_uf("xyz") == "", "desconhecido vira vazio")

    pa = tribunais.tribunais_por_prioridade("PA")
    falhas += checar(pa[0] == ["TRT8"], "PA começa pelo TRT8", str(pa[0]))
    falhas += checar(len(pa[1]) == len(set(pa[1])), "camada de região sem duplicatas", str(pa[1]))
    falhas += checar(pa[-1] == [], "última camada é o acervo nacional")

    sp = tribunais.tribunais_por_prioridade("SP")
    falhas += checar(sp[0] == ["TRT2", "TRT15"], "SP traz os dois regionais (capital + interior)", str(sp[0]))

    desconhecido = tribunais.tribunais_por_prioridade("")
    falhas += checar(desconhecido == [[]], "sem UF, busca nacional direta")

    print("TODOS OS TESTES PASSARAM" if not falhas else f"{falhas} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
