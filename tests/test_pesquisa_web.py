"""A hierarquia das fontes da pesquisa na web: o que sustenta uma petição e o que não.

Sem rede: a classificação é por DOMÍNIO, e é assim de propósito — perguntar ao modelo se
a fonte dele é confiável é perguntar à parte interessada.

O QUE ESTE TESTE PROTEGE

Um número de súmula lido no site do TST e o mesmo número tirado de um portal jurídico
têm exatamente o mesmo aspecto dentro de uma resposta bem escrita. Só um dos dois
sustenta a peça, e é o advogado que assina. Por isso a camada da fonte é medida aqui,
sai ordenada (oficial primeiro) e viaja com a mensagem até a tela.

    .venv\\Scripts\\python.exe -m tests.test_pesquisa_web
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import pesquisa_web  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str) -> None:
    global falhas
    print(f"   {'OK  ' if condicao else 'FALHA'} {descricao}")
    if not condicao:
        falhas += 1


print("\n1. Em que camada cada domínio cai")

CASOS = [
    ("https://www.planalto.gov.br/ccivil_03/leis/l8213.htm", "OFICIAL"),
    ("https://lexml.gov.br/urn/urn:lex:br:federal:lei:1991-07-24;8213", "OFICIAL"),
    ("https://www.in.gov.br/web/dou/-/portaria-123", "OFICIAL"),
    ("https://www25.senado.leg.br/web/atividade/materias", "OFICIAL"),
    # `.jus.br` é restrito ao Judiciário: o domínio já é a credencial.
    ("https://www3.tst.jus.br/jurisprudencia/Sumulas.html", "TRIBUNAL"),
    ("https://portal.stf.jus.br/jurisprudencia", "TRIBUNAL"),
    ("https://portal.trt3.jus.br/internet/conheca-o-trt", "TRIBUNAL"),
    ("https://www.cnj.jus.br/programas", "TRIBUNAL"),
    # Órgão público que não julga nem publica a norma: vale, mas não é fundamento.
    ("https://www.gov.br/inss/pt-br/assuntos/auxilio-por-incapacidade", "PUBLICA"),
    ("https://gov.br", "PUBLICA"),
    ("https://www.mpsp.mp.br/portal/page", "PUBLICA"),
    # O resto — inclusive o que se parece com fonte oficial.
    ("https://www.jusbrasil.com.br/jurisprudencia/tst/sumula-378", "SECUNDARIA"),
    ("https://blog.escritorioadvocacia.com.br/sumula-378-explicada", "SECUNDARIA"),
    ("https://www.migalhas.com.br/coluna/123", "SECUNDARIA"),
    # Um domínio que IMITA o oficial não passa: a comparação é por rótulo inteiro.
    ("https://planalto.gov.br.exemplo.com/lei", "SECUNDARIA"),
    ("https://naoplanalto.gov.br.io/lei", "SECUNDARIA"),
]

for url, esperado in CASOS:
    obtido = pesquisa_web._confianca(url)
    checar(obtido == esperado, f"{esperado:<11} {url[:62]}")


print("\n2. A lista chega ordenada, e a ausência de fonte oficial é medida")


def anotacao(url: str, titulo: str = "") -> dict:
    return {
        "type": "url_citation",
        "url_citation": {"url": url, "title": titulo, "content": "trecho qualquer"},
    }


fontes = pesquisa_web._fontes(
    [
        anotacao("https://www.jusbrasil.com.br/x", "Portal"),
        anotacao("https://www.gov.br/inss/y", "INSS"),
        anotacao("https://www3.tst.jus.br/sumula", "TST"),
        anotacao("https://www.planalto.gov.br/lei", "Planalto"),
    ]
)
checar(
    [f["confianca"] for f in fontes] == ["OFICIAL", "TRIBUNAL", "PUBLICA", "SECUNDARIA"],
    "oficial primeiro, secundária por último — quem lê de cima lê o que sustenta",
)
checar(
    [f["titulo"] for f in fontes][0] == "Planalto",
    "e a ordem original do modelo não manda na apresentação",
)

repetida = pesquisa_web._fontes([anotacao("https://x.jus.br/a"), anotacao("https://x.jus.br/a")])
checar(len(repetida) == 1, "URL repetida entra uma vez só")

vazia = pesquisa_web._fontes([{"type": "outra_coisa"}, anotacao("ftp://x/y")])
checar(vazia == [], "anotação que não é citação de URL http(s) é descartada")


print("\n3. O que o chat recebe quando NADA é oficial")

from app.agente import chat_peticao  # noqa: E402

pesquisa_web.pesquisar = lambda pergunta: {  # type: ignore[assignment]
    "pergunta": pergunta,
    "resposta": "A súmula 378 trata disso.",
    "fontes": pesquisa_web._fontes([anotacao("https://www.jusbrasil.com.br/x", "Portal")]),
    "modelo": "teste",
}
so_portal = chat_peticao._pesquisar_na_web("caso-1", "súmula 378")
checar(so_portal["tem_fonte_oficial"] is False, "a ausência de fonte oficial é declarada")
checar(
    "NENHUMA fonte oficial" in so_portal["aviso"],
    "e o modelo é instruído a dizer isso em vez de citar o número como confirmado",
)

pesquisa_web.pesquisar = lambda pergunta: {  # type: ignore[assignment]
    "pergunta": pergunta,
    "resposta": "Art. 118 da Lei 8.213/1991.",
    "fontes": pesquisa_web._fontes(
        [anotacao("https://www.planalto.gov.br/lei"), anotacao("https://blog.x.com/y")]
    ),
    "modelo": "teste",
}
com_norma = chat_peticao._pesquisar_na_web("caso-1", "estabilidade acidentária")
checar(com_norma["tem_fonte_oficial"] is True, "com a norma no Planalto, a busca se sustenta")
checar(com_norma["fontes_oficiais"] == 1, "e o chat sabe quantas fontes oficiais achou")
checar(
    "NENHUMA fonte oficial" not in com_norma["aviso"],
    "sem o alarme quando não é o caso — alarme que toca sempre ninguém lê",
)


print("\n4. A falha da busca não vira resposta inventada")


class ErroFalso(pesquisa_web.ErroPesquisa):
    pass


def falhar(pergunta):
    raise ErroFalso("Pesquisa na web desligada: falta OPENROUTER_API_KEY no .env.")


pesquisa_web.pesquisar = falhar  # type: ignore[assignment]
quebrada = chat_peticao._pesquisar_na_web("caso-1", "qualquer coisa")
checar(quebrada["falhou"] is True, "a falha volta como dado, não como exceção")
checar(
    "OPENROUTER_API_KEY" in quebrada["motivo"],
    "com o motivo real, para a IA contar o que houve em vez de responder de memória",
)
checar(quebrada["fontes"] == [], "e sem fonte nenhuma para citar")


if __name__ == "__main__":
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    raise SystemExit(1 if falhas else 0)
