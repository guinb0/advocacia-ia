"""A triagem não pontua o que o cliente NEGOU, nem pedaço de palavra.

Medido numa entrevista real (26/08/2026): "Acidente de Trabalho Geral" venceu
com 18 pontos, e os 18 eram artefato —

    +10  ACIDENTE DE TRABALHO   dentro de "não teve via acidente de trabalho"
    + 5  CAT                    dentro de "não sei que que é a CAT"
    + 3  CAI                    dentro da palavra "enCAIxa"

O cliente dissera, em voz alta, que não sofrera acidente de trabalho. A tela
respondeu classificando o caso exatamente como aquilo que ele negou.

Custa caro errar aqui: a categoria decide o checklist de documentos que o
cliente vai ser mandado juntar, e mandar um carteiro assaltado buscar laudo de
máquina é perder a confiança dele na primeira tarefa.

Rodar: .venv\\Scripts\\python.exe -m tests.test_triagem_negacao
"""

from __future__ import annotations

from app import triagem


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


def pontos(texto: str) -> dict[str, int]:
    r = triagem.classificar_entrevista(texto)
    return {s["codigo"] if isinstance(s, dict) else s.codigo:
            s["pontos"] if isinstance(s, dict) else s.pontos
            for s in r["sugestoes"]}


def cenario_negacao() -> int:
    falhas = 0

    # Sem "obra" e sem "queda": qualquer outra pista somaria por conta própria e
    # o número deixaria de medir o que este teste quer medir.
    negado = "Sou vendedor de loja. Eu nunca sofri acidente de trabalho nenhum."
    falhas += not checar(
        pontos(negado).get("acidente_trabalho_geral", 0) == 0,
        f"'nunca sofri acidente de trabalho' não pontua ({pontos(negado)})",
    )

    afirmado = "Sou vendedor de loja. Eu sofri um acidente de trabalho e quebrei o braço."
    falhas += not checar(
        pontos(afirmado).get("acidente_trabalho_geral", 0) > 0,
        f"mas 'sofri um acidente de trabalho' pontua ({pontos(afirmado)})",
    )

    # O lado que a correção NÃO pode estragar: negação seguida de causa deixa o
    # fato de pé. "Não consigo trabalhar POR CAUSA do acidente" — o acidente é
    # real, e suprimi-lo apagaria caso verdadeiro.
    com_causa = "Hoje eu não consigo mais trabalhar por causa do acidente de trabalho que sofri."
    falhas += not checar(
        pontos(com_causa).get("acidente_trabalho_geral", 0) > 0,
        f"'não consigo trabalhar POR CAUSA do acidente' continua pontuando ({pontos(com_causa)})",
    )
    return falhas


def cenario_pedaco_de_palavra() -> int:
    falhas = 0

    # "CAI" é pista de acidente (peso 3) e vive dentro de dezenas de palavras.
    encaixa = "Trabalho de carteiro. Isso encaixa bem no que eu preciso resolver."
    falhas += not checar(
        pontos(encaixa).get("acidente_trabalho_geral", 0) == 0,
        f"'encaixa' não vale como 'CAI' ({pontos(encaixa)})",
    )

    caiu = "Trabalho de carteiro. Eu cai da moto durante a entrega."
    falhas += not checar(
        "CAI" in triagem.normalizar(caiu),
        "o termo continua existindo no texto (a diferença é ser palavra)",
    )
    return falhas


def cenario_entrevista_real() -> int:
    """O caso que originou tudo: assalto de carteiro, acidente NEGADO."""
    falhas = 0
    fala = (
        "É, eu trabalho no nos Correios há aproximadamente três anos e meio. "
        "Às vezes eu fazia entrega, mas não tava no meu contrato. "
        "Foi durante uma das minhas entregas lá em Ceilândia. "
        "Não, apenas apenas fui assaltado. Eu desenvolvi um trauma devido ao assalto. "
        "Não, eu não sei que que é a CAT. "
        "Eu falei que é, mas não teve via acidente de trabalho. "
        "É, doença ocupacional encaixa, e aí encaixa também o bagulho da"
    )
    p = pontos(fala)
    falhas += not checar(
        p.get("acidente_trabalho_geral", 0) == 0,
        f"a categoria que o cliente NEGOU não pontua ({p.get('acidente_trabalho_geral', 0)})",
    )
    falhas += not checar(
        p.get("acidente_trabalho_correios", 0) > 0,
        f"e 'Correios', que ele afirmou, continua pontuando ({p.get('acidente_trabalho_correios', 0)})",
    )
    return falhas


def main_teste() -> int:
    falhas = 0
    for titulo, teste in (
        ("o que o cliente negou não pontua", cenario_negacao),
        ("pista tem de ser palavra, não pedaço", cenario_pedaco_de_palavra),
        ("a entrevista real que originou o caso", cenario_entrevista_real),
    ):
        print(f"\n{titulo}")
        falhas += teste()
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
