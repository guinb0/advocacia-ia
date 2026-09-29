"""Roteamento do agente geral: para onde vai cada pergunta.

Sem banco e sem rede — o que se prova aqui é a decisão, que é pura e determinística:

    .venv\\Scripts\\python.exe -m tests.test_conversa_geral

O que estes testes protegem, em uma frase: a tela nunca deve responder por aproximação
uma pergunta que atravessa o acervo, e nunca deve escolher um caso por sorteio.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agente import conversa_geral as cg  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str) -> None:
    global falhas
    print(f"   {'OK  ' if condicao else 'FALHA'} {descricao}")
    if not condicao:
        falhas += 1


ACERVO_DE_TESTE = [
    {"id": "caso-1", "cliente": "Maria Silva Santos"},
    {"id": "caso-2", "cliente": "João Souza Lima"},
    {"id": "caso-3", "cliente": "Transportes Beta"},
    {"id": "caso-4", "cliente": "Maria Aparecida Rocha"},
]


def rotear(pergunta: str, **kwargs):
    return cg.rotear(pergunta, ACERVO_DE_TESTE, **kwargs)


print("\n1. A pergunta sobre o acervo inteiro não é respondida")
for pergunta in (
    "Quais casos estão parados esperando documento?",
    "Quantos casos temos em aberto?",
    "Me mostre os prazos que vencem esta semana",
):
    checar(rotear(pergunta).natureza == cg.ACERVO, f"{pergunta!r} -> ACERVO")

honesta = cg.texto_do_acervo()
checar("ainda não sei responder" in honesta["conteudo"], "a recusa diz que não sabe")
checar(len(honesta["falta"]) == 3, "e diz o que faltaria para saber")


print("\n2. A pergunta que nomeia um caso vai para o chat daquele caso")
checar(rotear("Resuma o caso da Maria Silva").caso_id == "caso-1", "nome de duas palavras")
checar(rotear("e o caso do Joao Souza?").caso_id == "caso-2", "sem acento casa igual")
checar(rotear("como está Transportes Beta").caso_id == "caso-3", "cliente de dois nomes")
checar(rotear("o caso caso-4 travou?").caso_id == "caso-4", "identificador do caso")


print("\n3. Primeiro nome sozinho NÃO escolhe um caso")
# Duas Marias no acervo: escolher uma seria responder sobre o caso errado com toda a
# confiança do mundo.
decisao = rotear("o que falta no caso da Maria?")
checar(decisao.natureza != cg.CASO, "'Maria' sozinha não vira caso")
checar(decisao.caso_id is None, "e nenhum caso é escolhido por sorteio")


print("\n4. Duas citações viram pergunta, não escolha do sistema")
decisao = rotear("compare Maria Silva com Joao Souza")
checar(decisao.natureza == cg.ESCOLHA, "dois casos citados -> ESCOLHA")
checar(len(decisao.candidatos) == 2, "os dois candidatos voltam para a tela")


print("\n5. Pergunta sobre o produto é respondida pelo glossário")
casos_de_uso = {
    "O que é um fato alegado?": "fato-alegado",
    "qual a diferença entre pendência bloqueante e recomendável?": "pendencia",
    "como funciona a entrevista guiada": "entrevista",
    "para que serve o portal do cliente": "portal",
    "o que é jurimetria": "jurimetria",
}
for pergunta, codigo in casos_de_uso.items():
    decisao = rotear(pergunta)
    checar(
        decisao.natureza == cg.SISTEMA and decisao.verbete is not None
        and decisao.verbete.codigo == codigo,
        f"{pergunta!r} -> {codigo}",
    )

checar(
    all(v.texto.strip() and v.titulo.strip() for v in cg.GLOSSARIO),
    "nenhum verbete do glossário está vazio",
)


print("\n6. O glossário prefere não reconhecer a reconhecer errado")
# "comprovado" contém "provado": sem limite de palavra, o glossário explicaria fato
# provado a quem perguntou de comprovante.
checar(
    rotear("preciso do comprovante de residência").natureza == cg.ACERVO,
    "'comprovante' não dispara o verbete de fato provado",
)
checar(cg.verbete_para("bom dia") is None, "pergunta sem termo conhecido não casa nada")
checar(
    cg.verbete_para("o que é um fato alegado").codigo == "fato-alegado",
    "expressão de duas palavras vence a de uma",
)


print("\n7. Precedência: pergunta > conversa")
checar(
    rotear("e o caso do Joao Souza?", caso_fixado="caso-1").caso_id == "caso-2",
    "o caso citado na pergunta vence o caso da conversa",
)
checar(
    rotear("o que falta aqui?", caso_fixado="caso-1").caso_id == "caso-1",
    "sem citação, a conversa continua sobre o mesmo caso",
)
checar(
    rotear("o que é um fato alegado?", caso_fixado="caso-1").natureza == cg.CASO,
    "com caso na conversa, a pergunta vai para ele e não para o glossário",
)


print("\n8. A citação mais específica manda")
# O acervo real tem "Guilherme Nunes" ao lado de "Guilherme" — cliente cadastrado só com o
# primeiro nome acontece. Sem esta regra, perguntar pelo nome completo traria os homônimos
# de primeiro nome junto, e a lista de escolha viraria ruído sobre uma pergunta que já
# tinha sido específica.
COM_HOMONIMOS = [
    {"id": "g1", "cliente": "Guilherme Nunes"},
    {"id": "g2", "cliente": "Guilherme"},
    {"id": "g3", "cliente": "GUilherme"},
]
decisao = cg.rotear("Resuma o caso de Guilherme Nunes", COM_HOMONIMOS)
checar(decisao.natureza == cg.CASO and decisao.caso_id == "g1", "nome completo vence primeiro nome")
decisao = cg.rotear("e o caso do Guilherme?", COM_HOMONIMOS)
checar(decisao.natureza == cg.ESCOLHA, "só o primeiro nome ainda é ambíguo")
checar(
    {c["id"] for c in decisao.candidatos} == {"g2", "g3"},
    "e os ambíguos são os cadastrados com um nome só",
)
checar(
    cg.rotear("o caso g1 travou?", COM_HOMONIMOS).caso_id == "g1",
    "o identificador vence qualquer nome",
)


print("\n9. Acervo vazio não quebra nem inventa")
checar(cg.rotear("Resuma o caso da Maria Silva", []).natureza == cg.ACERVO, "sem casos -> ACERVO")
checar(cg.casos_citados("", ACERVO_DE_TESTE) == [], "pergunta vazia não cita ninguém")
checar(
    cg.casos_citados("qualquer coisa", [{"id": "x", "cliente": ""}]) == [],
    "cliente sem nome não casa com nada",
)


# O placar e a saída ficam sob a guarda de `__main__`, como nos demais testes da casa
# (ver `tests/test_perfis.py`). Solto no nível do módulo, o `SystemExit` era disparado
# durante o IMPORT do arquivo — e como o nome começa com `test_`, qualquer `pytest`
# que varresse a pasta morria em `INTERNALERROR` ao coletar este arquivo, levando
# junto a suíte inteira. O jeito de rodar continua o mesmo: `python -m tests.<nome>`.
if __name__ == "__main__":
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    raise SystemExit(1 if falhas else 0)
