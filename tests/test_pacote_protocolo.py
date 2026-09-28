import io
import zipfile

import pypdfium2 as pdfium
import pytest
from PIL import Image

from app import armazenamento, casos, pacote_protocolo, peticao_local

PASTA = "Protocolo (Reclamação Trabalhista - Assalto Em Serviço) Paulo Sergio Leandro Burcaos"


def _pdf(paginas: int = 1) -> bytes:
    documento = pdfium.PdfDocument.new()
    for _ in range(paginas):
        documento.new_page(595, 842)
    saida = io.BytesIO()
    documento.save(saida)
    return saida.getvalue()


def _texto(conteudo: bytes) -> str:
    documento = pdfium.PdfDocument(conteudo)
    return "\n".join(documento[i].get_textpage().get_text_range() for i in range(len(documento)))


@pytest.fixture
def caso(monkeypatch, tmp_path):
    imagem = io.BytesIO()
    Image.new("RGB", (40, 60), "white").save(imagem, format="PNG")
    arquivos = {
        "e1": ("Doc 1. CNH.pdf", _pdf(2)),
        "e2": ("IMG_2031.png", imagem.getvalue()),
        "e3": ("IMG_2031 (Duplicado).png", imagem.getvalue()),
        "e4": ("Checklist.pdf", _pdf()),
        "e5": ("Planilha De Cálculo.PJC", b"<?xml version='1.0'?><Calculo/>"),
    }
    caminhos = {}
    for entrega_id, (nome, conteudo) in arquivos.items():
        caminho = tmp_path / f"{entrega_id}{nome[nome.rfind('.'):]}"
        caminho.write_bytes(conteudo)
        caminhos[entrega_id] = caminho
    entregas = [{"id": i, "arquivo": nome, "identificacao_ia": ""} for i, (nome, _) in arquivos.items()]
    monkeypatch.setattr(armazenamento, "obter_caso", lambda _id: {
        "id": "c1", "cliente": "PAULO SERGIO LEANDRO BURCAOS", "tipo_acao": "Assalto em serviço", "categoria": "x",
    })
    monkeypatch.setattr(armazenamento, "listar_entregas", lambda _id: entregas)
    monkeypatch.setattr(armazenamento, "caminho_duravel_da_entrega", lambda entrega_id: caminhos[entrega_id])
    monkeypatch.setattr(casos, "situacao_de", lambda *_a: {"categoria": {"nome": "Acidente de trabalho"}})
    monkeypatch.setattr(peticao_local, "carregar", lambda _id: {
        "sections": [
            {"code": "QUALIFICACAO", "content": "propor em face de EMPRESA BRASILEIRA DE CORREIOS E TELÉGRAFOS - ECT, pessoa jurídica"},
            {"code": "VALOR", "content": "Dá-se à causa o valor da causa de **R$ 37.083,30**."},
        ],
        "readiness": {"pendencias": ["Confirmar o CEP da reclamada"]},
    })
    monkeypatch.setattr(peticao_local, "ler_pdf", lambda _id: _pdf(15))
    monkeypatch.setattr(peticao_local, "documentos_logicos", lambda _id: ([
        {"numero": 1, "canonical_file": "Doc 1. CNH.pdf", "source_files": ["Doc 1. CNH.pdf"], "document_type": ""},
        {"numero": 2, "canonical_file": "IMG_2031.png", "source_files": ["IMG_2031.png", "IMG_2031 (Duplicado).png"],
         "document_type": "PROCURAÇÃO"},
        {"numero": 3, "canonical_file": "Planilha De Cálculo.PJC", "source_files": ["Planilha De Cálculo.PJC"], "document_type": ""},
    ], []))


def test_pasta_para_protocolo_segue_o_modelo_do_escritorio(caso):
    pacote = pacote_protocolo.montar("c1")
    try:
        with zipfile.ZipFile(pacote.caminho) as zipado:
            nomes = sorted(zipado.namelist())
            lista = _texto(zipado.read(f"{PASTA}/Lista De Documentação Para Protocolo.pdf"))
            checklist = _texto(zipado.read(f"{PASTA}/Checklist.pdf"))
            procuracao = zipado.read(f"{PASTA}/Doc 2. Procuração.pdf")
    finally:
        pacote.caminho.unlink()

    assert pacote.nome == f"{PASTA}.zip"
    assert nomes == sorted(f"{PASTA}/{n}" for n in [
        "Petição Inicial.pdf", "Doc 1. CNH.pdf", "Doc 2. Procuração.pdf", "Planilha De Cálculo.PJC",
        "Lista De Documentação Para Protocolo.pdf", "Checklist.pdf",
    ])
    assert procuracao[:4] == b"%PDF"  # a foto virou PDF
    assert "Paulo Sergio Leandro Burcaos × EMPRESA BRASILEIRA DE CORREIOS" in lista
    assert "IMG_2031 (Duplicado).png (cópia do Doc 2)" in lista
    assert "Checklist.pdf (uso interno)" in lista
    assert "R$ 37.083,30" in checklist and "Confirmar o CEP da reclamada" in checklist
    assert "Doc 1. CNH" in checklist and "Doc 2. Procuração" in checklist
    assert pacote.faltando == []


def test_sem_peticao_nao_monta_a_pasta(caso, monkeypatch):
    monkeypatch.setattr(peticao_local, "carregar", lambda _id: None)
    with pytest.raises(pacote_protocolo.ErroPacote, match="Gere a petição"):
        pacote_protocolo.montar("c1")


def test_marcar_e_desmarcar_protocolo(monkeypatch):
    guardado = {"sections": [], "status": "APPROVED"}
    monkeypatch.setattr(peticao_local, "carregar", lambda _id: dict(guardado))
    monkeypatch.setattr(peticao_local, "_salvar", lambda _id, dados: guardado.update(dados) or dados)

    dados = peticao_local.marcar_protocolo(
        "c1", protocolada=True, numero=" 0000123-45.2026.5.08.0001 ", data="2026-09-28", por="Ana"
    )
    assert dados["protocolo"]["numero"] == "0000123-45.2026.5.08.0001"
    assert dados["protocolo"]["data"] == "2026-09-28" and dados["protocolo"]["marcado_por"] == "Ana"
    assert dados["status"] == "APPROVED"  # protocolo não mexe na revisão
    assert peticao_local.para_api(dados)["protocolo"]["numero"] == "0000123-45.2026.5.08.0001"

    with pytest.raises(ValueError, match="Data"):
        peticao_local.marcar_protocolo("c1", protocolada=True, data="28/09/2026")

    assert peticao_local.marcar_protocolo("c1", protocolada=False)["protocolo"] is None
