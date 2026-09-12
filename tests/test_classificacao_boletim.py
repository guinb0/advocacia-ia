"""Boletim de ocorrência não é documento de identidade — mesmo citando CPF/CNH.

Um BO de acidente traz o CPF e a CNH do envolvido no corpo do relato, e o
classificador o mandava para "cnh" (visto num caso real: HILDEBRANDO). É
narrativo: nenhum tipo cadastral serve, então cai em "desconhecido" e a leitura
semântica o nomeia como boletim.

    PYTHONPATH=. .venv/Scripts/python.exe tests/test_classificacao_boletim.py
"""

from __future__ import annotations

from app.extractors import classificar, normalizar


def checar(cond: bool, desc: str, detalhe: str = "") -> int:
    print(f"  {'PASS' if cond else '>> FALHA'} {desc}" + (f" ({detalhe})" if detalhe and not cond else ""))
    return 0 if cond else 1


def main_teste() -> int:
    falhas = 0

    bo = normalizar(
        "BOLETIM DE OCORRENCIA POLICIA MILITAR BOPM acidente de transito com vitima "
        "Envolvido HILDEBRANDO ALMEIDA CPF 084.040.147-79 CNH 04139716913 categoria B "
        "primeira habilitacao validade CAT HAB DETRAN"
    )
    falhas += checar(classificar(bo)[0] == "desconhecido",
                     "BO que cita CNH do envolvido NÃO vira 'cnh'", classificar(bo)[0])

    bo2 = normalizar(
        "REGISTRO DE OCORRENCIA DELEGACIA autoridade policial vitima CPF 111.222.333-44 "
        "guarnicao historico do fato"
    )
    falhas += checar(classificar(bo2)[0] == "desconhecido",
                     "registro de ocorrência não vira documento cadastral", classificar(bo2)[0])

    # A CNH de verdade continua classificando como CNH.
    cnh = normalizar(
        "CARTEIRA NACIONAL DE HABILITACAO PRIMEIRA HABILITACAO CAT HAB categoria B "
        "VALIDADE ACC DETRAN registro nacional condutor"
    )
    falhas += checar(classificar(cnh)[0] == "cnh", "a CNH real segue como 'cnh'", classificar(cnh)[0])

    print("TODOS OS TESTES PASSARAM" if not falhas else f"{falhas} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
