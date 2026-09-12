"""A regra que decide o que a IA aprende com as correções do escritório.

Sem banco: `_chave` e `_licoes` são funções puras justamente para isto — a
consulta ao pgvector fica de fora, e o que se testa aqui é a regra.

O que estas verificações protegem, tudo medido contra o banco real antes de
existir (ver o diagnóstico da retroalimentação):

- A IA lembrava de 5 lições por categoria. Gravadas 7, esquecia as duas
  primeiras — o escritório reensinava o que já tinha ensinado.
- A mesma lição escrita de novo ocupava outra vaga e afogava as demais.
- Toda crítica instruía as próximas petições, inclusive "troque o nome do
  cliente", que não é lição de categoria nenhuma.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import peticao_criticas as pc  # noqa: E402
from app import peticao_local as pl  # noqa: E402


def checar(condicao: bool, texto: str) -> bool:
    print(("  PASS " if condicao else "  FALHA ") + texto)
    return condicao


def testar_teto_da_janela() -> int:
    """20 lições cabem; a 21ª mais antiga sai, e a ordem é a de quem ensinou."""
    falhas = 0
    recentes = [f"licao {n}" for n in range(30, 0, -1)]  # 30 é a mais recente
    licoes = pc._licoes(recentes, pl.CRITICAS_RECENTES_POR_CATEGORIA)

    falhas += not checar(len(licoes) == 20, f"guarda 20 lições (guardou {len(licoes)})")
    falhas += not checar(licoes[-1] == "licao 30", "a mais recente vai por último no prompt")
    falhas += not checar(licoes[0] == "licao 11", "a 21ª mais antiga já não instrui")
    falhas += not checar(
        pl.CRITICAS_RECENTES_POR_CATEGORIA >= 20,
        "o teto em vigor não voltou a ser pequeno o bastante para esquecer lição",
    )
    return falhas


def testar_repetida_nao_gasta_vaga() -> int:
    """Caixa, pontuação e espaço não fazem duas lições de uma."""
    falhas = 0
    licoes = pc._licoes(
        [
            "Separe dano moral do material nos pedidos!!",  # a mais recente
            "  SEPARE DANO MORAL DO MATERIAL NOS PEDIDOS.  ",
            "separe dano moral do material nos pedidos",
            "sempre peça gratuidade da justiça",
        ],
        20,
    )
    falhas += not checar(len(licoes) == 2, f"três redações viram uma vaga ({licoes})")
    falhas += not checar(
        licoes[-1] == "Separe dano moral do material nos pedidos!!",
        "fica a redação mais recente da lição repetida",
    )
    return falhas


def testar_licao_diferente_continua_valendo() -> int:
    """Deduplicar não pode juntar lições que só se parecem.

    A normalização é de forma, não de sentido — e é assim de propósito: casar
    por semelhança semântica erraria em silêncio, fundindo duas instruções
    diferentes numa só e fazendo a IA obedecer a metade do que foi ensinado.
    """
    falhas = 0
    licoes = pc._licoes(
        ["separe dano moral do material", "junte dano moral e material num pedido só"], 20
    )
    falhas += not checar(len(licoes) == 2, "lições de sentido oposto continuam as duas")
    return falhas


def testar_vazio_nao_instrui() -> int:
    """Crítica em branco não vira lição — ocuparia vaga sem ensinar nada."""
    falhas = 0
    licoes = pc._licoes(["   ", "", "sempre peça gratuidade"], 20)
    falhas += not checar(licoes == ["sempre peça gratuidade"], f"só o que tem texto ({licoes})")
    return falhas


def main_teste() -> int:
    falhas = 0
    for titulo, teste in (
        ("o teto da janela de lições", testar_teto_da_janela),
        ("lição repetida não gasta vaga", testar_repetida_nao_gasta_vaga),
        ("lições diferentes não se fundem", testar_licao_diferente_continua_valendo),
        ("crítica vazia não instrui", testar_vazio_nao_instrui),
    ):
        print(f"\n{titulo}")
        falhas += teste()
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
