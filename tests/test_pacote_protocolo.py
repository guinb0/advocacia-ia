import io
import zipfile

import pypdfium2 as pdfium
import pytest
from PIL import Image

from app import analise_documental, analise_documentos, armazenamento, casos, pacote_protocolo, peticao_local

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
    monkeypatch.setattr(armazenamento, "listar_extracoes_do_caso", lambda _id: [
        {"id": "e2", "arquivo": "IMG_2031.png", "extracao": {"classificacao_semantica": {
            "tipo_semantico": "Procuração", "resumo": "Procuração ad judicia outorgada ao escritório.",
            "achados": [{"campo": "Outorgado", "valor": "Lara & Melo Advogados"}],
        }}},
    ])
    monkeypatch.setattr(pacote_protocolo, "_JULGAMENTOS", {})
    monkeypatch.setattr(analise_documental, "obter", lambda _id: None)


def _citar(monkeypatch, texto: str) -> None:
    monkeypatch.setattr(peticao_local, "carregar", lambda _id: {
        "sections": [
            {"code": "QUALIFICACAO", "content": "propor em face de EMPRESA BRASILEIRA DE CORREIOS E TELÉGRAFOS - ECT, pessoa jurídica"},
            {"code": "FATOS", "content": texto},
        ],
    })


def _por_id(conferencia: dict) -> dict:
    return {d["entrega_id"]: d for d in conferencia["documentos"]}


def test_conferencia_pelas_regras_separa_o_que_vai_do_que_fica(caso):
    conferencia = pacote_protocolo.sugerir("c1", usar_ia=False)
    docs = _por_id(conferencia)

    assert conferencia["analisado_por"] == "regras"
    assert docs["e1"]["sugerido"] and docs["e1"]["rotulo"] == "Doc 1. CNH"
    assert docs["e2"]["sugerido"] and docs["e2"]["rotulo"] == "Doc 2. Procuração"
    assert "Procuração ad judicia" in docs["e2"]["leitura"] and "Outorgado: Lara & Melo" in docs["e2"]["leitura"]
    assert not docs["e3"]["sugerido"] and "Cópia repetida do Documento 02" in docs["e3"]["motivo"]
    assert not docs["e4"]["sugerido"] and docs["e4"]["categoria"] == "interno"
    assert docs["e5"]["sugerido"] and docs["e5"]["categoria"] == "planilha"
    assert docs["e2"]["converte_para_pdf"] and not docs["e5"]["converte_para_pdf"]
    assert conferencia["pendencias"] == ["Confirmar o CEP da reclamada"]


def test_conferencia_com_ia_decide_e_aponta_o_que_falta(caso, monkeypatch):
    _citar(monkeypatch, "Conforme a CNH (Documento 01) e o Documento 07.")
    chamadas = []

    def modelo(mensagem, *, instrucao=None, max_tokens=None):
        chamadas.append((mensagem, instrucao))
        return {
            "documentos": [
                {"id": "e1", "incluir": False, "motivo": "Identifica o reclamante."},
                {"id": "e2", "incluir": False, "motivo": "Procuração vencida, de outro processo."},
                {"id": "e4", "incluir": True, "motivo": "É, na verdade, a declaração de uma testemunha."},
            ],
            "faltando": [{"documento": "Contracheques", "motivo": "Provam o salário pedido."}],
        }

    monkeypatch.setattr(analise_documentos, "_chamar_modelo", modelo)
    conferencia = pacote_protocolo.sugerir("c1")
    docs = _por_id(conferencia)

    assert conferencia["analisado_por"] == "ia"
    # Documento citado pela petição continua marcado, mesmo que o modelo discorde.
    assert docs["e1"]["sugerido"] and "cita este arquivo como Documento 01" in docs["e1"]["motivo"]
    assert not docs["e2"]["sugerido"] and docs["e2"]["motivo"] == "Procuração vencida, de outro processo."
    assert docs["e4"]["sugerido"] and "testemunha" in docs["e4"]["motivo"]
    faltando = [f["documento"] for f in conferencia["faltando"]]
    assert "Documento 07" in faltando and "Contracheques" in faltando
    mensagem, instrucao = chamadas[0]
    assert "CITADO NA PETIÇÃO" in mensagem and "Procuração ad judicia" in mensagem
    assert "Pense com cuidado em cada documento" in instrucao

    pacote_protocolo.sugerir("c1")
    assert len(chamadas) == 1  # reabrir a conferência não paga outra volta no modelo


def test_conferencia_usa_a_skill_documental(caso, monkeypatch):
    monkeypatch.setattr(analise_documental, "obter", lambda _id: {"status": "ready", "resultado": {"documentos": [
        {"documento_id": "e1", "tipo": "CNH", "legivel": False, "problema": "foto cortada"},
        {"documento_id": "e2", "tipo": "Procuração", "legivel": True, "data": "2019-03-01",
         "atualizacao": "DESATUALIZADO", "motivo_atualizacao": "outorgada em 2019, para outro processo",
         "vulnerabilidades": ["sem reconhecimento de firma"]},
    ]}})
    chamadas = []

    def modelo(mensagem, *, instrucao=None, max_tokens=None):
        chamadas.append((mensagem, instrucao))
        return {"documentos": [], "faltando": [
            {"documento": "PPP", "motivo": "Prova a exposição.", "classificacao": "era melhor ter",
             "como_obter": "Requerimento ao empregador (art. 58, §4º, Lei 8.213/91)."},
            {"documento": "CTPS", "motivo": "Prova o vínculo.", "classificacao": "inventada"},
        ]}

    monkeypatch.setattr(analise_documentos, "_chamar_modelo", modelo)
    conferencia = pacote_protocolo.sugerir("c1")
    docs = _por_id(conferencia)
    mensagem, instrucao = chamadas[0]

    assert "1 documento = 1 arquivo PDF" in instrucao and "COMPROMETE" in instrucao
    assert "Contrato de Honorários" in instrucao and "Atualizado ou desatualizado" in instrucao
    assert "ILEGÍVEL (foto cortada)" in mensagem and "DESATUALIZADO (outorgada em 2019" in mensagem
    assert "fraqueza: sem reconhecimento de firma" in mensagem
    assert "ilegível" in docs["e1"]["motivo"] and "desatualizado" in docs["e2"]["motivo"]
    faltando = {f["documento"]: f for f in conferencia["faltando"]}
    assert faltando["PPP"]["classificacao"] == "ERA_MELHOR_TER" and "Lei 8.213" in faltando["PPP"]["como_obter"]
    assert faltando["CTPS"]["classificacao"] == ""


def test_conferencia_sem_ia_disponivel_segue_pelas_regras(caso, monkeypatch):
    def fora_do_ar(*_a, **_k):
        raise analise_documentos.ErroAnaliseDocumentos("sem chave")

    monkeypatch.setattr(analise_documentos, "_chamar_modelo", fora_do_ar)
    conferencia = pacote_protocolo.sugerir("c1")
    assert conferencia["analisado_por"] == "regras" and "não respondeu" in conferencia["aviso"]
    assert _por_id(conferencia)["e1"]["sugerido"]


def test_pasta_com_a_selecao_conferida(caso, monkeypatch):
    _citar(monkeypatch, "Procuração anexa (Documento 02).")
    pacote = pacote_protocolo.montar("c1", ["e1", "e4"], ["Contracheques de 2025"])
    try:
        with zipfile.ZipFile(pacote.caminho) as zipado:
            nomes = sorted(n.split("/", 1)[1] for n in zipado.namelist())
            lista = _texto(zipado.read(next(n for n in zipado.namelist() if n.endswith("Protocolo.pdf"))))
            checklist = _texto(zipado.read(next(n for n in zipado.namelist() if n.endswith("/Checklist.pdf"))))
            extra = zipado.read(next(n for n in zipado.namelist() if "Doc 4." in n))
    finally:
        pacote.caminho.unlink()

    assert nomes == sorted([
        "Petição Inicial.pdf", "Doc 1. CNH.pdf", "Doc 4. Checklist.pdf",
        "Lista De Documentação Para Protocolo.pdf", "Checklist.pdf",
    ])
    assert extra[:4] == b"%PDF"
    assert "IMG_2031.png (retirado na conferência)" in lista
    assert "cita o Documento 02" in checklist and "Contracheques de 2025" in checklist
    assert "ficou fora da pasta" in checklist  # a planilha existe, mas não foi marcada


def test_selecao_com_arquivo_de_outro_caso_e_recusada(caso):
    with pytest.raises(pacote_protocolo.ErroSelecao):
        pacote_protocolo.montar("c1", ["e1", "de-outro-caso"])


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
