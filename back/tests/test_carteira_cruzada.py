"""Nada passa despercebido: dado de item que falta, achado em OUTRO documento.

O cliente não traz a CTPS, mas o número e o PIS dela aparecem no CNIS, no
holerite, no TRCT. O item fica pendente e a informação, que já está no caso, some
de vista. Aqui prova-se que o detector acha o dado — e que NÃO inventa indício em
documento que não tem nada com carteira (boletim, receita).

    PYTHONPATH=. .venv/Scripts/python.exe tests/test_carteira_cruzada.py
"""

from __future__ import annotations

from app import casos


def checar(cond: bool, desc: str, detalhe: str = "") -> int:
    print(f"  {'PASS' if cond else '>> FALHA'} {desc}" + (f" ({detalhe})" if detalhe and not cond else ""))
    return 0 if cond else 1


def main_teste() -> int:
    falhas = 0

    achou_pis = casos._carteira_no_texto("CADASTRO NACIONAL ... NIT/PIS/PASEP: 123.45678.90-1")
    falhas += checar(achou_pis == "PIS 123.45678.90-1", "acha o PIS no CNIS", str(achou_pis))

    achou_ctps = casos._carteira_no_texto("TERMO DE RESCISAO ... CTPS nº 0012345 serie 00678-RJ")
    falhas += checar(bool(achou_ctps) and "CTPS" in achou_ctps, "acha o número da CTPS no TRCT", str(achou_ctps))

    # Sem rótulo de PIS por perto, um número de 11 dígitos NÃO vira indício de PIS
    # (poderia ser CPF). Indício errado é pior que indício nenhum.
    cpf_solto = casos._carteira_no_texto("Inscrito no CPF 123.456.789-09, residente na rua tal")
    falhas += checar(cpf_solto is None, "CPF solto não vira indício de PIS", str(cpf_solto))

    boletim = casos._carteira_no_texto("BOLETIM DE OCORRENCIA colisao de veiculo, vitima socorrida")
    falhas += checar(boletim is None, "boletim de ocorrência não gera falso indício")

    receita = casos._carteira_no_texto("Prescricao: Pregabalina 75mg, Tramadol. CRM 12345")
    falhas += checar(receita is None, "receita médica não gera falso indício")

    falhas += checar(casos._item_e_carteira("CTPS e PIS"), "item 'CTPS e PIS' é reconhecido como carteira")
    falhas += checar(casos._item_e_carteira("Carteira de Trabalho e Previdência Social"), "nome por extenso também")
    falhas += checar(not casos._item_e_carteira("RG"), "RG não é item de carteira")
    falhas += checar(not casos._item_e_carteira("Comprovante de residência"), "comprovante não é item de carteira")

    print("TODOS OS TESTES PASSARAM" if not falhas else f"{falhas} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
