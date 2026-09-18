"""Fotos dentro da petição: `[[FOTO:id|legenda]]` no texto vira imagem no .docx.

Sem banco e sem modelo: o anexo é uma imagem gerada aqui e o armazenamento é dublê.

O QUE ESTE TESTE PROTEGE

1. **a linha de foto vira imagem de verdade no Word**, com a legenda embaixo, e o
   pacote continua válido (XML bem formado, relação e mídia gravadas);
2. **foto de celular sai em pé** — a rotação do EXIF é aplicada antes de gravar;
3. **anexo que não abre vira [PENDENTE]** visível, nunca some em silêncio;
4. **a revisão por IA não apaga a foto** quando a crítica não fala de foto;
5. **o chat só PROPÕE**: `propor_inclusao_de_foto` não toca na peça, e quem insere
   é a ação confirmada.

    .venv\\Scripts\\python.exe -m tests.test_peticao_fotos
"""

import io
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from app import armazenamento, peticao_local  # noqa: E402
from app.agente import chat_peticao  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str) -> None:
    global falhas
    print(f"   {'OK  ' if condicao else 'FALHA'} {descricao}")
    if not condicao:
        falhas += 1


def _jpeg_deitado() -> bytes:
    """800×400 gravado deitado, com EXIF dizendo "gire 90°" (orientação 6)."""
    imagem = Image.new("RGB", (800, 400), "red")
    exif = Image.Exif()
    exif[0x0112] = 6
    saida = io.BytesIO()
    imagem.save(saida, "JPEG", exif=exif)
    return saida.getvalue()


ARQUIVOS = {"foto1": _jpeg_deitado(), "quebrada": b"isto nao e imagem"}
ENTREGAS = {
    "foto1": {"id": "foto1", "caso_id": "caso-1", "arquivo": "IMG_0001.jpg"},
    "quebrada": {"id": "quebrada", "caso_id": "caso-1", "arquivo": "IMG_0002.jpg"},
    "pdf": {"id": "pdf", "caso_id": "caso-1", "arquivo": "laudo.pdf"},
}

armazenamento.obter_entrega = lambda i: ENTREGAS.get(i)
armazenamento.caminho_duravel_da_entrega = lambda i: None
armazenamento.conteudo_arquivo_entrega = lambda e: ARQUIVOS.get(e["id"])

PETICAO = {
    "version": 3,
    "sections": [
        {"code": "FACTS", "label": "Dos fatos", "content": "O autor caiu da escada.\n\nFoi socorrido."},
        {"code": "CLOSING", "label": "Fecho", "content": "Termos em que pede deferimento."},
    ],
}
salvas: list = []
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


print("1. a linha de foto vira imagem no .docx")
secoes = [
    {"code": "FACTS", "label": "Dos fatos", "content": "Texto.\n[[FOTO:foto1|Foto 1 – lesão no braço]]\nMais texto."},
    {"code": "CLOSING", "label": "Fecho", "content": "[[FOTO:quebrada|Foto 2]]"},
]
docx = peticao_local.montar_docx(secoes)
with zipfile.ZipFile(io.BytesIO(docx)) as pacote:
    nomes = pacote.namelist()
    documento = pacote.read("word/document.xml").decode("utf-8")
    relacoes = pacote.read("word/_rels/document.xml.rels").decode("utf-8")
    tipos = pacote.read("[Content_Types].xml").decode("utf-8")
    for parte in ("word/document.xml", "word/_rels/document.xml.rels", "[Content_Types].xml"):
        try:
            ElementTree.fromstring(pacote.read(parte))
            checar(True, f"{parte} é XML bem formado")
        except ElementTree.ParseError as erro:
            checar(False, f"{parte} é XML bem formado ({erro})")
    midia = pacote.read("word/media/foto-1.jpeg") if "word/media/foto-1.jpeg" in nomes else b""
checar("word/media/foto-1.jpeg" in nomes, "a foto foi gravada em word/media")
checar('r:embed="rIdFoto1"' in documento and 'Id="rIdFoto1"' in relacoes, "o desenho aponta para a relação da foto")
checar('Extension="jpeg"' in tipos, "o tipo jpeg está declarado")
checar("Foto 1 – lesão no braço" in documento, "a legenda saiu no documento")
checar("[[FOTO:" not in documento, "o marcador não vazou como texto")
checar("Texto." in documento and "Mais texto." in documento, "o texto em volta continua")

print("2. foto de celular sai em pé")
with Image.open(io.BytesIO(midia)) as gravada:
    checar(gravada.height > gravada.width, f"girada pelo EXIF ({gravada.width}×{gravada.height})")

print("3. anexo ilegível vira pendência visível")
checar("[PENDENTE: foto não encontrada nos anexos — Foto 2]" in documento, "aviso [PENDENTE] no lugar da foto")

print("4. a revisão por IA não apaga a foto")
antes = [{"code": "FACTS", "content": "A.\n[[FOTO:foto1|x]]"}]
depois = [{"code": "FACTS", "content": "A reescrito."}]
voltou = peticao_local._preservar_fotos(antes, depois, "melhore a narrativa dos fatos")
checar("[[FOTO:foto1|x]]" in voltou[0]["content"], "crítica sem foto: marcador devolvido")
tirou = peticao_local._preservar_fotos(antes, depois, "tire a foto dos fatos")
checar("[[FOTO:" not in tirou[0]["content"], "crítica que fala de foto: a IA decide")

print("5. inserir na peça")
resultado = peticao_local.inserir_foto("caso-1", "foto1", legenda="Foto 1 – lesão", usuario="dra")
checar(resultado["secao"] == "Fecho", "sem seção: vai para o fim da petição")
checar(PETICAO["sections"][-1]["content"].endswith("[[FOTO:foto1|Foto 1 – lesão]]"), "marcador no fim do fecho")
peticao_local.inserir_foto("caso-1", "foto1", secao="dos fatos", depois_de="caiu da escada")
linhas = [l for l in PETICAO["sections"][0]["content"].split("\n") if l.strip()]
checar(linhas[:3] == ["O autor caiu da escada.", "[[FOTO:foto1]]", "Foi socorrido."], "logo abaixo do parágrafo pedido")
for anexo, esperado in (("pdf", "não é uma foto"), ("quebrada", "Não consegui abrir"), ("inexistente", "não é deste caso")):
    try:
        peticao_local.inserir_foto("caso-1", anexo)
        checar(False, f"{anexo}: recusado")
    except peticao_local.ErroPeticao as erro:
        checar(esperado in str(erro), f"{anexo}: recusado ({erro})")

print("6. o chat só propõe")
peticao_local.anexos_do_caso = lambda caso_id: [
    {"id": e["id"], "arquivo": e["arquivo"], "tipo": "", "campos": [], "texto": "", "situacao": "sem_texto"}
    for e in ENTREGAS.values()
]
checar(chat_peticao.CATALOGO["propor_inclusao_de_foto"][2] is True, "catalogada como proposta")
checar(chat_peticao.CATALOGO["listar_fotos"][2] is False, "listar_fotos é leitura")
fotos = chat_peticao.executar_ferramenta("listar_fotos", "caso-1", {})
checar([f["arquivo"] for f in fotos["fotos"]] == ["IMG_0001.jpg", "IMG_0002.jpg"], "lista só as imagens")
checar(fotos["fotos"][0]["ja_esta_na_peticao"] is True, "sabe que a foto já está na peça")
versao = PETICAO["version"]
proposta = chat_peticao.executar_ferramenta(
    "propor_inclusao_de_foto", "caso-1", {"arquivo": "IMG_0001.jpg", "legenda": "Foto do machucado"}
)
checar(proposta.get("registrada") and proposta["anexo_id"] == "foto1", "proposta aponta a entrega certa")
checar(PETICAO["version"] == versao, "propor não mexeu na peça")
ambigua = chat_peticao.executar_ferramenta("propor_inclusao_de_foto", "caso-1", {"arquivo": "IMG"})
checar(not ambigua.get("registrada") and len(ambigua["fotos_do_caso"]) == 2, "nome ambíguo: devolve as candidatas")
texto, extra = chat_peticao._executar("caso-1", "dra", {k: v for k, v in proposta.items() if k != "registrada"})
checar(PETICAO["version"] == versao + 1 and "Incluí a foto IMG_0001.jpg" in texto, "a ação confirmada insere")

print()
print("TUDO OK" if not falhas else f"{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)
