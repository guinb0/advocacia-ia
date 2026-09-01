"""O relatório .docx da entrevista: símbolo do escritório e análise assistida.

O que estraga um relatório é ele não ABRIR — um .docx é um zip com um esquema
rígido, e o Word recusa o pacote inteiro por um namespace faltando ou uma relação
de imagem quebrada, sem dizer o quê. Por isso o teste monta o arquivo de verdade
e confere: zip íntegro, todas as partes XML bem-formadas, o PNG do emblema
presente e ligado por relação, e a análise renderizada com as citações de
precedente. Não abre o Word (não há Word aqui), mas valida tudo que o Word exige
para abrir.

Rodar: .venv\\Scripts\\python.exe -m tests.test_relatorio
"""

from __future__ import annotations

import io
import zipfile
from xml.dom.minidom import parseString

from app import relatorio


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


RESPOSTAS = {
    "nome": "Maria Aparecida da Silva",
    "cpf": "",  # obrigatório em branco, para exercitar as pendências
    "relato_fato": "Fui assaltada duas vezes entregando correspondência na periferia.",
}

ANALISE = {
    "resumo": "Indícios de acidente de trabalho por equiparação; faltam documentos.",
    "acoes": [
        {
            "acao": "Solicitar a CAT à empregadora",
            "porque": "Sem a CAT o nexo fica frágil.",
            "precedentes": ["P1", "P3"],
        }
    ],
    "riscos": [{"risco": "Prescrição bienal se o afastamento for antigo", "precedentes": ["P2"]}],
    "lacunas": ["Data exata do primeiro afastamento", "Nome de testemunhas"],
    "precedentes": [
        {
            "indice": "P1",
            "processo": "0001234-56.2023.5.08.0001",
            "resultado": "procedente",
            "fonte": "trt8_juris",
            "similaridade": 0.81,
        }
    ],
    "aviso": "Análise assistiva; requer revisão do advogado.",
}


def _abrir(data: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(data))


def _xml_bem_formado(z: zipfile.ZipFile) -> bool:
    for nome in z.namelist():
        if nome.endswith((".xml", ".rels")):
            parseString(z.read(nome))  # levanta se malformado
    return True


def testar_com_analise() -> int:
    falhas = 0
    data, dados = relatorio.gerar_docx(RESPOSTAS, "empregado_publico", "Dra. Ana", ANALISE)
    z = _abrir(data)

    falhas += not checar(z.testzip() is None, "o zip do .docx está íntegro")
    falhas += not checar(_xml_bem_formado(z), "todas as partes XML são bem-formadas")

    doc = z.read("word/document.xml").decode("utf-8")
    falhas += not checar("word/media/logo.png" in z.namelist(), "o emblema está embutido")
    falhas += not checar(len(z.read("word/media/logo.png")) > 1000, "o PNG do emblema tem conteúdo")
    falhas += not checar('r:embed="rIdLogo"' in doc, "o desenho referencia a imagem")
    rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
    falhas += not checar("media/logo.png" in rels, "a relação da imagem existe")
    ct = z.read("[Content_Types].xml").decode("utf-8")
    falhas += not checar("image/png" in ct, "o tipo png está declarado")

    falhas += not checar("ANÁLISE ASSISTIDA POR PRECEDENTES" in doc, "a seção de análise entrou")
    falhas += not checar("Solicitar a CAT" in doc, "a ação sugerida aparece")
    falhas += not checar("[P1, P3]" in doc, "a ação cita os precedentes que a sustentam")
    falhas += not checar("Prescrição bienal" in doc.replace("&#237;", "í") or "Prescri" in doc, "o risco aparece")
    falhas += not checar("0001234-56.2023.5.08.0001" in doc, "o precedente consultado é listado")

    falhas += not checar(dados["faltando_obrigatorias"], "as pendências obrigatórias foram apuradas")
    return falhas


def testar_sem_analise() -> int:
    """Sem análise, o relatório sai como antes — organizado, com o símbolo."""
    falhas = 0
    data, _ = relatorio.gerar_docx(RESPOSTAS, "empregado_publico", "", None)
    z = _abrir(data)
    doc = z.read("word/document.xml").decode("utf-8")

    falhas += not checar(z.testzip() is None and _xml_bem_formado(z), "o .docx é válido")
    falhas += not checar("word/media/logo.png" in z.namelist(), "o emblema entra mesmo sem análise")
    falhas += not checar("ANÁLISE ASSISTIDA" not in doc, "sem análise, a seção não aparece")
    falhas += not checar("RELATÓRIO DE ENTREVISTA" in doc, "o corpo do relatório está lá")
    return falhas


def testar_base_indisponivel() -> int:
    """Base fora do ar vira NOTA, não erro — o relatório ainda sai."""
    falhas = 0
    nota = {"indisponivel": "A base de precedentes não respondeu a tempo."}
    data, _ = relatorio.gerar_docx(RESPOSTAS, "empregado_publico", "", nota)
    z = _abrir(data)
    doc = z.read("word/document.xml").decode("utf-8")

    falhas += not checar(_xml_bem_formado(z), "o .docx é válido com a nota")
    falhas += not checar("não respondeu" in doc, "a nota de indisponibilidade aparece")
    falhas += not checar("Solicitar" not in doc, "não inventa ação quando a base caiu")
    return falhas


def testar_analise_malformada() -> int:
    """Modelo devolvendo campo torto não pode quebrar a geração."""
    falhas = 0
    torto = {
        "resumo": "ok",
        "acoes": ["não é um dict", {"acao": "válida", "precedentes": "P1"}],
        "riscos": None,
        "lacunas": [""],
    }
    try:
        data, _ = relatorio.gerar_docx(RESPOSTAS, "empregado_publico", "", torto)
        z = _abrir(data)
        ok = z.testzip() is None and _xml_bem_formado(z)
    except Exception as exc:  # noqa: BLE001
        ok = False
        print("   ", exc)
    falhas += not checar(ok, "campos tortos são descartados sem estourar")
    return falhas


def testar_emblema_valido() -> int:
    """O PNG embutido é uma imagem de verdade, não bytes quaisquer."""
    from PIL import Image

    from app import marca

    falhas = 0
    largura, altura = marca.dimensao_emblema()
    falhas += not checar(largura > altura, "o emblema é uma faixa larga (cabeçalho)")
    img = Image.open(io.BytesIO(marca.emblema_png()))
    img.verify()
    falhas += not checar(True, "o PNG do emblema é válido")
    return falhas


def testar_pdf_analisado() -> int:
    """A entrega final é PDF válido, paginado e com texto pesquisável."""
    import pypdfium2 as pdfium

    falhas = 0
    data, dados = relatorio.gerar_pdf(
        RESPOSTAS, "empregado_publico", "Dra. Ana", ANALISE
    )
    falhas += not checar(data.startswith(b"%PDF-"), "a entrega começa com o cabeçalho PDF")
    documento = pdfium.PdfDocument(data)
    falhas += not checar(len(documento) >= 1, "o PDF tem ao menos uma página")
    texto = "\n".join(
        documento[i].get_textpage().get_text_range() for i in range(len(documento))
    )
    falhas += not checar("RELATÓRIO DE ENTREVISTA" in texto, "o título é pesquisável")
    falhas += not checar("Solicitar a CAT" in texto, "a análise entrou no PDF")
    falhas += not checar(bool(dados["faltando_obrigatorias"]), "as pendências foram preservadas")
    return falhas


def main_teste() -> int:
    falhas = 0
    for titulo, teste in (
        ("relatório analisado, com emblema", testar_com_analise),
        ("relatório sem análise", testar_sem_analise),
        ("base de precedentes indisponível", testar_base_indisponivel),
        ("análise malformada não quebra", testar_analise_malformada),
        ("emblema é imagem válida", testar_emblema_valido),
        ("relatório analisado em PDF", testar_pdf_analisado),
    ):
        print(f"\n{titulo}")
        falhas += teste()

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
