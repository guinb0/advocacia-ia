"""O link que abre o processo usado como base da jurimetria.

POR QUE ELE É DERIVADO, E NÃO GUARDADO

O advogado quer abrir o processo que fundou o número — e a tela mostrava só o
número. O campo `url` existe de ponta a ponta (coluna `fontes.url` no pgvector,
`rag.TrechoSimilar.referencia`, o tipo no frontend, o `<a>` nos dois painéis), mas
está vazio: medido no acervo, 7566 fontes e 2 com url, as duas de consulta de
CNPJ. A API de comunicações do DJEN não devolve link, então não há o que guardar.

O número CNJ, por outro lado, carrega tudo o que o link precisa:
`NNNNNNN-DD.AAAA.J.TR.OOOO` — `J` é o segmento da Justiça, `TR` o regional e
`OOOO` a unidade de origem (`0000` = o próprio tribunal, 2º grau). Daí sai a
consulta processual pública do PJe daquele TRT.

O QUE ESTE TESTE PROTEGE

Link errado é pior que link ausente: manda o advogado conferir no lugar errado, e
ele não tem como saber. Então o que se mede aqui é sobretudo quando NÃO se monta
link — número fora do padrão, outro segmento da Justiça, regional inexistente.

Rodar: .venv\\Scripts\\python.exe -m tests.test_link_processo
"""

from __future__ import annotations

from app import tribunais as t


def checar(condicao: bool, texto: str, detalhe: str = "") -> bool:
    print(("  PASS  " if condicao else "  FALHA ") + texto + (f"\n          {detalhe}" if not condicao and detalhe else ""))
    return condicao


#: Processos reais do acervo (aparecem na jurimetria do caso `da5a030b`).
TRT8_1G = "00009437220255080105"
TRT8_2G = "00010527620265080000"
TRT2_1G = "00005093720225020001"


def testar_numero_legivel() -> int:
    falhas = 0
    falhas += not checar(
        t.numero_processo_formatado(TRT8_1G) == "0000943-72.2025.5.08.0105",
        f"os 20 dígitos crus ganham a pontuação do CNJ ({t.numero_processo_formatado(TRT8_1G)})",
    )
    falhas += not checar(
        t.numero_processo_formatado("0000943-72.2025.5.08.0105") == "0000943-72.2025.5.08.0105",
        "número já formatado passa igual",
    )
    # Número que não é CNJ volta como veio: melhor mostrar o que há do que esconder.
    falhas += not checar(
        t.numero_processo_formatado("PROC-123/2024") == "PROC-123/2024",
        "o que não é CNJ é devolvido intacto, não apagado",
    )
    falhas += not checar(t.numero_processo_formatado(None) == "", "nulo vira vazio, sem estourar")
    return falhas


def testar_link_da_justica_do_trabalho() -> int:
    falhas = 0
    link = t.link_do_processo(TRT8_1G)
    falhas += not checar(
        link == "https://pje.trt8.jus.br/consultaprocessual/detalhe-processo/0000943-72.2025.5.08.0105/1",
        f"1º grau do TRT8 aponta para o PJe dele, no grau 1 ({link})",
    )
    falhas += not checar(
        t.link_do_processo(TRT8_2G).endswith("/0001052-76.2026.5.08.0000/2"),
        f"unidade 0000 é o tribunal — grau 2 ({t.link_do_processo(TRT8_2G)})",
    )
    falhas += not checar(
        "pje.trt2.jus.br" in t.link_do_processo(TRT2_1G),
        f"cada regional aponta para o próprio host ({t.link_do_processo(TRT2_1G)})",
    )
    falhas += not checar(
        t.tribunal_do_processo(TRT8_1G) == "TRT8" and t.tribunal_do_processo(TRT2_1G) == "TRT2",
        "e o tribunal sai nomeado, para o link dizer para onde vai",
    )
    return falhas


def testar_quando_nao_monta_link() -> int:
    """A parte que protege o advogado: no que não dá para saber, não há link."""
    falhas = 0
    # Segmento 4 = Justiça Federal. O acervo é trabalhista e o caminho do PJe de
    # outro segmento não foi verificado; montar link ali seria chute.
    falhas += not checar(
        t.link_do_processo("00001234520234036100") == "",
        "processo de outro segmento da Justiça não ganha link",
    )
    falhas += not checar(t.link_do_processo("123") == "", "número curto não ganha link")
    falhas += not checar(
        t.link_do_processo("00009437220255990105") == "",
        "regional inexistente (99) não ganha link",
    )
    falhas += not checar(t.link_do_processo("") == "" and t.link_do_processo(None) == "", "vazio e nulo também não")
    falhas += not checar(
        t.tribunal_do_processo("00001234520234036100") == "",
        "e o nome do tribunal também fica vazio fora do trabalhista",
    )
    return falhas


def testar_referencia_do_precedente() -> int:
    """O que a tela recebe de fato — `rag.TrechoSimilar.referencia`."""
    from app import rag

    falhas = 0
    trecho = rag.TrechoSimilar(
        texto="...",
        similaridade=0.8461,
        titulo="Sentença",
        identificador="djen:1",
        url=None,
        metadados={
            "numero_processo": TRT8_1G,
            "rotulo": "IMPROCEDENTE",
            "orgao_julgador": "VARA DO TRABALHO DE CAPANEMA",
        },
    )
    ref = trecho.referencia()
    falhas += not checar(bool(ref["url"]), "sem url guardada, o precedente ganha o link derivado")
    falhas += not checar(
        ref["processo_formatado"] == "0000943-72.2025.5.08.0105",
        "e o número formatado vai junto",
    )
    falhas += not checar(ref["tribunal"] == "TRT8", "com o tribunal nomeado")

    # URL guardada na fonte VENCE a derivada: se algum dia o coletor trouxer o
    # link da decisão em si, ele é melhor que a consulta do processo.
    com_url = rag.TrechoSimilar(
        texto="...",
        similaridade=0.5,
        titulo="Sentença",
        identificador="x",
        url="https://exemplo.jus.br/decisao/1",
        metadados={"numero_processo": TRT8_1G},
    )
    falhas += not checar(
        com_url.referencia()["url"] == "https://exemplo.jus.br/decisao/1",
        "url guardada na fonte tem prioridade sobre a derivada",
    )

    # Precedente sem número: a tela não pode receber um link quebrado.
    sem_numero = rag.TrechoSimilar(
        texto="...", similaridade=0.5, titulo="S", identificador="x", url=None, metadados={}
    )
    falhas += not checar(
        sem_numero.referencia()["url"] == "", "precedente sem número não recebe link"
    )
    return falhas


def main_teste() -> int:
    falhas = 0
    for titulo, teste in (
        ("1. O número como o advogado lê", testar_numero_legivel),
        ("2. O link do PJe do regional", testar_link_da_justica_do_trabalho),
        ("3. Quando NÃO se monta link", testar_quando_nao_monta_link),
        ("4. O precedente como a tela recebe", testar_referencia_do_precedente),
    ):
        print(f"\n{titulo}")
        falhas += teste()
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
