"""Leitura e guarda da entrevista de atendimento.

    .venv\\Scripts\\python.exe -m tests.test_entrevista
"""

import sys
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import armazenamento  # noqa: E402

_TEMP = Path(tempfile.mkdtemp(prefix="ocr-entrevista-"))
armazenamento.DIR_DADOS = _TEMP
armazenamento.DIR_ARQUIVOS = _TEMP / "casos"
armazenamento.DIR_CONTRATOS = _TEMP / "contratos"
armazenamento.CAMINHO_BANCO = _TEMP / "casos.db"

from app import entrevista  # noqa: E402
from app.agente import dossie  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str) -> None:
    global falhas
    print(f"   {'OK  ' if condicao else 'FALHA'} {descricao}")
    if not condicao:
        falhas += 1


def docx_falso(paragrafos: list[str]) -> bytes:
    """Um .docx mínimo de verdade: zip com o XML que o Word escreve."""
    corpo = "".join(
        f"<w:p><w:r><w:t>{texto}</w:t></w:r></w:p>" for texto in paragrafos
    )
    documento = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{corpo}</w:body></w:document>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as arquivo:
        arquivo.writestr("word/document.xml", documento)
    return buffer.getvalue()


def main() -> int:
    armazenamento.inicializar()

    print("1. Leitura do arquivo")
    texto = entrevista.extrair_texto("atendimento.txt", "CLIENTE: entrei em 2018.".encode())
    checar(texto == "CLIENTE: entrei em 2018.", "texto simples é lido como está")

    acentuado = entrevista.extrair_texto("a.txt", "Nº do benefício: 6312".encode("cp1252"))
    checar("benefício" in acentuado, "arquivo salvo em cp1252 (Bloco de Notas antigo) é lido")

    docx = entrevista.extrair_texto("a.docx", docx_falso(["ADVOGADA: e depois?", "CLIENTE: fui demitido."]))
    checar(
        docx == "ADVOGADA: e depois?\nCLIENTE: fui demitido.",
        "o .docx preserva a quebra entre pergunta e resposta",
    )

    try:
        entrevista.extrair_texto("audio.mp3", b"\x00\x01")
    except entrevista.ErroDeLeitura as erro:
        checar("mp3" in str(erro), "extensão não suportada diz qual é e o que aceita")
    else:
        checar(False, "extensão não suportada diz qual é e o que aceita")

    try:
        entrevista.extrair_texto("vazio.txt", b"   \n  \n")
    except entrevista.ErroDeLeitura as erro:
        checar("OCR" in str(erro), "arquivo sem texto sugere o caminho do OCR em vez de falhar mudo")
    else:
        checar(False, "arquivo sem texto sugere o caminho do OCR em vez de falhar mudo")

    print("\n2. Guarda no caso")
    caso = armazenamento.criar_caso("Marcos Costa", "doenca_ocupacional")
    caso_id = caso["id"]
    destino = armazenamento.DIR_ARQUIVOS / caso_id / "entrevistas"
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / "atendimento.txt"
    caminho.write_text("CLIENTE: entrei em 2018.", encoding="utf-8")

    registro = armazenamento.registrar_entrevista(
        caso_id,
        arquivo="atendimento.txt",
        caminho=caminho,
        texto="CLIENTE: entrei em 2018.",
        realizada_em="12/08/2026",
        entrevistador="Dra. Helena",
    )
    checar(registro["arquivo"] == "atendimento.txt", "a entrevista é guardada no caso")
    checar(not registro["enviada"], "entrevista nasce como não lida pelo agente")

    armazenamento.marcar_entrevista_lida(
        registro["id"], resumo="Cliente relatou lesão de ombro.", perguntas=["Conferir CTPS."], fatos_gerados=7
    )
    relida = armazenamento.obter_entrevista(registro["id"])
    checar(relida["enviada"], "depois de lida, a entrevista fica marcada")
    checar(relida["fatos_gerados"] == 7, "o número de fatos relatados fica registrado")
    checar(relida["perguntas"] == ["Conferir CTPS."], "as perguntas em aberto voltam como lista")

    print("\n3. Etapa da entrevista no dossiê")
    sem = dossie._etapa_entrevista([])
    checar(sem["estado"] == "pendente", "caso sem entrevista aparece como pendente")

    nao_lida = dossie._etapa_entrevista([dossie._entrevista_resumida(registro)])
    checar(
        nao_lida["estado"] == "andamento",
        "entrevista anexada mas não lida não é 'pronto' — nada dela chegou ao caso",
    )

    lida = dossie._etapa_entrevista([dossie._entrevista_resumida(relida)])
    checar(lida["estado"] == "pronto" and "7 fato" in lida["detalhe"], "entrevista lida mostra quantos fatos gerou")

    vazia = dict(relida)
    vazia["fatos_gerados"] = 0
    sem_fato = dossie._etapa_entrevista([dossie._entrevista_resumida(vazia)])
    checar(
        sem_fato["estado"] == "atencao",
        "entrevista lida sem nenhum fato aproveitado é atenção, não sucesso",
    )

    resumida = dossie._entrevista_resumida(relida)
    checar(
        "texto" not in resumida and resumida["previa"],
        "o dossiê leva prévia, não o texto inteiro — a tela recarrega o tempo todo",
    )

    print("\n4. Exclusão")
    checar(caminho.exists(), "o arquivo está em disco antes da exclusão")
    armazenamento.excluir_entrevista(registro["id"])
    checar(not caminho.exists(), "excluir a entrevista apaga o arquivo")
    checar(armazenamento.obter_entrevista(registro["id"]) is None, "e some do caso")

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
