"""Trechos de documento dentro da petição: `> trecho (Fonte: …)` vira citação recuada.

Sem banco e sem modelo: os anexos e a petição são dublês.

O QUE ESTE TESTE PROTEGE

1. **só entra o que o documento diz, palavra por palavra** — trecho de memória, mesmo
   parecido, é citação falsa numa peça entregue ao juízo;
2. **a citação chega ao Word como citação** (recuo de 4 cm, corpo menor), e o marcador
   `>` não vaza como texto;
3. **a revisão por IA não parafraseia a citação** quando a crítica não fala dela;
4. **o chat só PROPÕE**: `propor_inclusao_de_trecho` não toca na peça, recusa o trecho
   que não está no documento, e quem insere é a ação confirmada.

    .venv\\Scripts\\python.exe -m tests.test_peticao_trechos
"""

import io
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import peticao_local  # noqa: E402
from app.agente import chat_peticao  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str) -> None:
    global falhas
    print(f"   {'OK  ' if condicao else 'FALHA'} {descricao}")
    if not condicao:
        falhas += 1


LAUDO = (
    "LAUDO MÉDICO. O paciente apresenta lesão grave no ombro direito, com limitação\n"
    "funcional permanente para o trabalho braçal. Recomenda-se afastamento por 90 dias."
)
ANEXOS = [
    {"id": "a1", "arquivo": "laudo.pdf", "tipo": "Laudo médico", "texto": LAUDO, "situacao": "lido", "campos": []},
    {"id": "a2", "arquivo": "IMG_0002.jpg", "tipo": "CTPS", "texto": "", "situacao": "sem_texto", "campos": []},
]
PETICAO = {
    "version": 3,
    "sections": [
        {"code": "FACTS", "label": "Dos fatos", "content": "O autor caiu da escada.\n\nFoi socorrido."},
        {"code": "CLOSING", "label": "Fecho", "content": "Termos em que pede deferimento."},
    ],
}
salvas: list = []
peticao_local.anexos_do_caso = lambda caso_id: ANEXOS if caso_id == "caso-1" else []
peticao_local.carregar = lambda caso_id: PETICAO if caso_id == "caso-1" else None


def _salvar_secoes(caso_id, secoes, usuario=""):
    salvas.append(secoes)
    por_codigo = {s["code"]: s["content"] for s in secoes}
    for s in PETICAO["sections"]:
        if s["code"] in por_codigo:
            s["content"] = por_codigo[s["code"]]
    PETICAO["version"] += 1
    return PETICAO


peticao_local.salvar_secoes = _salvar_secoes


print("1. só entra o que o documento diz")
PASSAGEM = "lesão grave no ombro direito, com limitação funcional permanente"
checar(peticao_local.trecho_esta_no_documento(LAUDO, PASSAGEM), "trecho exato, mesmo atravessando a quebra de linha do OCR")
checar(peticao_local.trecho_esta_no_documento(LAUDO, "LESÃO   GRAVE no ombro direito"), "caixa e espaço não contam")
checar(peticao_local.trecho_esta_no_documento(LAUDO, "lesao grave no ombro direito"), "acento não conta")
checar(not peticao_local.trecho_esta_no_documento(LAUDO, "lesão leve no ombro direito"), "palavra trocada NÃO passa")
checar(not peticao_local.trecho_esta_no_documento(LAUDO, "incapacidade total e permanente"), "o que o documento não diz NÃO passa")
checar(not peticao_local.trecho_esta_no_documento(LAUDO, "ombro"), "trecho curto demais não vale como citação")

print("2. a inserção")
resultado = peticao_local.inserir_trecho(
    "caso-1", "a1", PASSAGEM, secao="Dos fatos", depois_de="caiu da escada", usuario="adv"
)
fatos = PETICAO["sections"][0]["content"]
checar(
    fatos == f"O autor caiu da escada.\n\n> {PASSAGEM} (Fonte: Laudo médico — laudo.pdf)\n\n\nFoi socorrido.",
    "a citação entra logo abaixo do parágrafo indicado, com a fonte",
)
checar(resultado["posicao"] == "logo abaixo do parágrafo indicado" and resultado["arquivo"] == "laudo.pdf", "e o resultado diz onde")
checar(len(salvas) == 1, "vira UMA edição manual (versão/histórico)")

for erro_esperado, chamada in (
    ("não aparece", lambda: peticao_local.inserir_trecho("caso-1", "a1", "trecho inventado que o laudo nunca disse")),
    ("não é deste caso", lambda: peticao_local.inserir_trecho("caso-1", "outro", PASSAGEM)),
    ("Nenhuma petição", lambda: peticao_local.inserir_trecho("caso-2", "a1", PASSAGEM)),
    ("Não achei a seção", lambda: peticao_local.inserir_trecho("caso-1", "a1", PASSAGEM, secao="Das provas obscuras")),
    ("máximo", lambda: peticao_local.inserir_trecho("caso-1", "a1", "palavra " * 400)),
    ("Diga qual trecho", lambda: peticao_local.inserir_trecho("caso-1", "a1", "  ")),
):
    try:
        chamada()
        checar(False, f"deveria recusar: {erro_esperado}")
    except peticao_local.ErroPeticao as erro:
        checar(erro_esperado in str(erro), f"recusa: {erro_esperado}")
checar(len(salvas) == 1, "e nenhuma recusa gravou nada")

peticao_local.inserir_trecho("caso-1", "a1", PASSAGEM, secao="Fecho")
checar(
    PETICAO["sections"][1]["content"].endswith(f"> {PASSAGEM} (Fonte: Laudo médico — laudo.pdf)"),
    "sem `depois_de`, a citação vai para o fim da seção",
)

print("3. no Word, é citação")
docx = peticao_local.montar_docx([{"code": "FACTS", "label": "Dos fatos", "content": f"Texto.\n> {PASSAGEM} (Fonte: Laudo — laudo.pdf)\nMais texto."}])
with zipfile.ZipFile(io.BytesIO(docx)) as pacote:
    documento = pacote.read("word/document.xml").decode("utf-8")
    ElementTree.fromstring(pacote.read("word/document.xml"))
checar('w:left="2268"' in documento, "recuo de 4 cm à esquerda")
checar(PASSAGEM in documento and "Fonte: Laudo — laudo.pdf" in documento, "o trecho e a fonte saem no documento")
checar("&gt; " not in documento and "> lesão" not in documento, "o marcador `>` não vaza como texto")
checar("Texto." in documento and "Mais texto." in documento, "o texto em volta continua")

print("4. a revisão por IA não parafraseia a citação")
citacao = f"> {PASSAGEM} (Fonte: Laudo médico — laudo.pdf)"
antes = [{"code": "FACTS", "content": f"A.\n\n{citacao}\n\nB."}]
depois = [{"code": "FACTS", "content": "A reescrito. O laudo diz que há lesão importante.\n\nB."}]
restaurado = peticao_local._preservar_citacoes(antes, depois, "melhore os fatos")
checar(citacao in restaurado[0]["content"], "citação que a IA deixou cair volta para a seção")
intocado = peticao_local._preservar_citacoes(antes, [{"code": "FACTS", "content": f"A.\n\n{citacao}\n\nB melhor."}], "melhore")
checar(intocado[0]["content"].count(citacao) == 1, "citação mantida não é duplicada")
checar(
    peticao_local._preservar_citacoes(antes, depois, "tire o trecho do laudo") == depois,
    "se a crítica fala de trecho, quem decide é ela",
)

print("5. o chat só propõe")
antes_da_peca = PETICAO["sections"][0]["content"]
versao = PETICAO["version"]
proposta = chat_peticao.executar_ferramenta(
    "propor_inclusao_de_trecho",
    "caso-1",
    {"arquivo": "laudo.pdf", "trecho": PASSAGEM, "secao": "Dos fatos", "depois_de": "Foi socorrido"},
)
checar(proposta["registrada"] and proposta["tipo"] == "INCLUIR_TRECHO" and proposta["anexo_id"] == "a1", "propor devolve a ação")
checar(
    PETICAO["sections"][0]["content"] == antes_da_peca and PETICAO["version"] == versao,
    "e não toca na peça",
)
inventado = chat_peticao.executar_ferramenta(
    "propor_inclusao_de_trecho", "caso-1", {"arquivo": "laudo.pdf", "trecho": "o autor ficou incapaz para sempre"}
)
checar(inventado["registrada"] is False and "NÃO aparece" in inventado["erro"], "trecho que o documento não diz é recusado, com a orientação de procurar")
sem_texto = chat_peticao.executar_ferramenta(
    "propor_inclusao_de_trecho", "caso-1", {"arquivo": "IMG_0002.jpg", "trecho": "qualquer coisa escrita aqui"}
)
checar(sem_texto["registrada"] is False, "documento sem texto lido não fornece citação")
ambiguo = chat_peticao.executar_ferramenta("propor_inclusao_de_trecho", "caso-1", {"arquivo": "xyz", "trecho": PASSAGEM})
checar(ambiguo["registrada"] is False and "documentos_do_caso" in ambiguo, "documento não identificado lista as opções")

texto, extra = chat_peticao._executar(
    "caso-1", "Ana", {k: v for k, v in proposta.items() if k != "registrada"}
)
checar("Incluí o trecho de laudo.pdf" in texto and "Dos fatos" in texto, "a ação confirmada insere e conta o que fez")
checar(PETICAO["version"] == versao + 1, "e só ela cria a versão nova")

if __name__ == "__main__":
    print(f"\n{'TUDO OK' if not falhas else f'{falhas} FALHA(S)'}")
    raise SystemExit(1 if falhas else 0)
