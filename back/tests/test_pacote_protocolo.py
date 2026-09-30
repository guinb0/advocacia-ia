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


def _png() -> bytes:
    imagem = io.BytesIO()
    Image.new("RGB", (30, 30), "white").save(imagem, format="PNG")
    return imagem.getvalue()


def _instantaneo(pasta) -> dict:
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(pasta.iterdir())}


def test_avulsos_entram_na_pasta_sem_tocar_nos_originais(caso, tmp_path):
    antes = _instantaneo(tmp_path)
    entregas_antes = [dict(e) for e in armazenamento.listar_entregas("c1")]
    avulsos = [
        pacote_protocolo.ArquivoAvulso(nome="Laudo complementar", arquivo="laudo.png", conteudo=_png()),
        pacote_protocolo.ArquivoAvulso(nome="", arquivo="declaracao testemunha.pdf", conteudo=_pdf()),
    ]
    pacote = pacote_protocolo.montar("c1", ["e1", "e2"], [], avulsos)
    try:
        with zipfile.ZipFile(pacote.caminho) as zipado:
            nomes = [n.split("/", 1)[1] for n in zipado.namelist()]
            laudo = zipado.read(next(n for n in zipado.namelist() if "Laudo" in n))
    finally:
        pacote.caminho.unlink()

    assert nomes == [
        "Petição Inicial.pdf", "Doc 1. CNH.pdf", "Doc 2. Procuração.pdf",
        "Doc 4. Laudo Complementar.pdf", "Doc 5. Declaracao Testemunha.pdf",
        "Lista De Documentação Para Protocolo.pdf", "Checklist.pdf",
    ]
    assert laudo[:4] == b"%PDF"  # a foto avulsa também vira PDF
    # Nada gravado, renomeado ou alterado nos arquivos do caso, e nenhuma entrega nova.
    assert _instantaneo(tmp_path) == antes
    assert armazenamento.listar_entregas("c1") == entregas_antes


def test_documento_com_falha_nao_derruba_a_pasta_e_diz_qual_foi(caso, monkeypatch, tmp_path):
    originais = armazenamento.caminho_duravel_da_entrega
    monkeypatch.setattr(
        armazenamento, "caminho_duravel_da_entrega",
        lambda entrega_id: tmp_path / "sumiu.pdf" if entrega_id == "e1" else originais(entrega_id),
    )
    monkeypatch.setattr(armazenamento, "obter_entrega", lambda _id: {})
    monkeypatch.setattr(armazenamento, "conteudo_arquivo_entrega", lambda _e: None)
    converter = pacote_protocolo.conversao_pdf.converter_para_pdf

    def conversao_quebrada(origem, nome, destino):
        if nome == "IMG_2031.png":
            raise RuntimeError("imagem corrompida")
        return converter(origem, nome, destino)

    monkeypatch.setattr(pacote_protocolo.conversao_pdf, "converter_para_pdf", conversao_quebrada)
    vazio = pacote_protocolo.ArquivoAvulso(nome="Vazio", arquivo="vazio.pdf", conteudo=b"")
    pacote = pacote_protocolo.montar("c1", ["e1", "e2", "e4"], [], [vazio])
    try:
        with zipfile.ZipFile(pacote.caminho) as zipado:
            nomes = [n.split("/", 1)[1] for n in zipado.namelist()]
            checklist = _texto(zipado.read(next(n for n in zipado.namelist() if n.endswith("/Checklist.pdf"))))
    finally:
        pacote.caminho.unlink()

    assert "Doc 4. Checklist.pdf" in nomes and not any("CNH" in n or "Procuração" in n for n in nomes)
    problemas = " | ".join(pacote.problemas)
    assert "«Doc 1. CNH.pdf»: o arquivo não foi encontrado" in problemas
    assert "«IMG_2031.png»: não foi possível preparar o arquivo (imagem corrompida)" in problemas
    assert "«vazio.pdf»: o arquivo chegou vazio" in problemas
    assert set(pacote.faltando) == {"Doc 1. CNH.pdf", "IMG_2031.png", "vazio.pdf"}
    assert "Doc 1. CNH.pdf» não pôde ser incluído" in checklist


def test_nomes_seguros_e_sem_sobrescrever_no_zip():
    assert pacote_protocolo._nome_seguro('Doc 4. Laudo: 1/2 "final"?\x07') == "Doc 4. Laudo- 1-2 -final--"
    assert pacote_protocolo._nome_seguro(" ... ") == "Documento"
    usados: set[str] = set()
    assert [pacote_protocolo._nome_unico(n, usados) for n in ["Doc 1. RG.pdf", "doc 1. rg.pdf", "Doc 1. RG.pdf"]] == [
        "Doc 1. RG.pdf", "doc 1. rg (2).pdf", "Doc 1. RG (3).pdf",
    ]


def test_rota_com_avulsos_monta_e_informa_os_problemas(caso):
    import json
    from urllib.parse import unquote

    from starlette.datastructures import UploadFile

    from app.agente import rotas

    resposta = rotas.montar_pacote_com_avulsos(
        "c1",
        selecao=json.dumps({"selecionados": ["e1"], "faltando": []}),
        avulsos=[
            UploadFile(io.BytesIO(_pdf()), filename="rg novo.pdf"),
            UploadFile(io.BytesIO(b""), filename="vazio.pdf"),
        ],
        nomes_avulsos=["RG atualizado", ""],
    )
    try:
        with zipfile.ZipFile(resposta.path) as zipado:
            nomes = [n.split("/", 1)[1] for n in zipado.namelist()]
    finally:
        pacote_protocolo.Path(resposta.path).unlink()

    assert "Doc 4. RG Atualizado.pdf" in nomes
    problemas = json.loads(unquote(resposta.headers["X-Problemas"]))
    assert problemas == ["«vazio.pdf»: o arquivo chegou vazio e ficou fora da pasta."]


def test_rota_com_avulsos_por_http_como_o_frontend_envia(caso):
    import json
    from urllib.parse import unquote

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.agente import rotas

    app = FastAPI()
    app.include_router(rotas.roteador)
    cliente = TestClient(app)
    resposta = cliente.post(
        "/api/agente/casos/c1/pacote-protocolo/com-avulsos",
        data={"selecao": json.dumps({"selecionados": ["e1", "e2"], "faltando": ["PPP"]}),
              "nomes_avulsos": ["Laudo", "Declaração"]},
        files=[("avulsos", ("laudo.png", _png(), "image/png")), ("avulsos", ("decl.pdf", _pdf(), "application/pdf"))],
    )
    assert resposta.status_code == 200, resposta.text
    with zipfile.ZipFile(io.BytesIO(resposta.content)) as zipado:
        nomes = [n.split("/", 1)[1] for n in zipado.namelist()]
    assert nomes[:5] == [
        "Petição Inicial.pdf", "Doc 1. CNH.pdf", "Doc 2. Procuração.pdf", "Doc 4. Laudo.pdf", "Doc 5. Declaração.pdf",
    ]
    assert json.loads(unquote(resposta.headers["X-Problemas"])) == []

    sem_nomes = cliente.post(
        "/api/agente/casos/c1/pacote-protocolo/com-avulsos",
        data={"selecao": json.dumps({"selecionados": [], "faltando": []})},
        files=[("avulsos", ("recibo.pdf", _pdf(), "application/pdf"))],
    )
    assert sem_nomes.status_code == 200
    with zipfile.ZipFile(io.BytesIO(sem_nomes.content)) as zipado:
        assert any(n.endswith("/Doc 4. Recibo.pdf") for n in zipado.namelist())  # sem nome, vale o do arquivo


def test_rota_com_avulsos_recusa_arquivo_grande(caso, monkeypatch):
    import json

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.agente import rotas

    monkeypatch.setattr(pacote_protocolo, "MAXIMO_BYTES_AVULSO", 10)
    app = FastAPI()
    app.include_router(rotas.roteador)
    resposta = TestClient(app).post(
        "/api/agente/casos/c1/pacote-protocolo/com-avulsos",
        data={"selecao": json.dumps({"selecionados": ["e1"], "faltando": []})},
        files=[("avulsos", ("enorme.pdf", _pdf(), "application/pdf"))],
    )
    assert resposta.status_code == 413 and "enorme.pdf" in resposta.json()["detail"]


def test_rota_com_avulsos_recusa_selecao_invalida(caso):
    from fastapi import HTTPException

    from app.agente import rotas

    with pytest.raises(HTTPException) as erro:
        rotas.montar_pacote_com_avulsos("c1", selecao="{quebrado", avulsos=[], nomes_avulsos=[])
    assert erro.value.status_code == 400


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
        peticao_local.marcar_protocolo("c1", protocolada=True, numero="123", data="28/09/2026")

    assert peticao_local.marcar_protocolo("c1", protocolada=False)["protocolo"] is None


def test_marcar_protocolo_exige_o_numero(monkeypatch):
    guardado = {"sections": [], "status": "IN_REVIEW", "protocolo": None}
    monkeypatch.setattr(peticao_local, "carregar", lambda _id: dict(guardado))
    monkeypatch.setattr(peticao_local, "_salvar", lambda _id, dados: guardado.update(dados) or dados)

    for vazio in ("", "   "):
        with pytest.raises(ValueError, match="número do protocolo"):
            peticao_local.marcar_protocolo("c1", protocolada=True, numero=vazio, data="2026-09-28")
    assert guardado["protocolo"] is None


def test_lista_so_as_peticoes_protocoladas(monkeypatch):
    import json

    from app import armazenamento

    def linha(caso_id, cliente, protocolo, titulo="Petição inicial"):
        return {
            "caso_id": caso_id,
            "cliente": cliente,
            "categoria": "assalto",
            "dados_json": json.dumps({"title": titulo, "status": "APPROVED", "protocolo": protocolo}, ensure_ascii=False),
        }

    linhas = [
        linha("c1", "Ana", {"numero": "111", "data": "2026-09-20", "marcado_por": "Bia", "marcado_em": "x"}),
        linha("c2", "João", None),
        linha("c3", "Rui", {"numero": "333", "data": "2026-09-28", "marcado_por": "Bia", "marcado_em": "y"}),
        {"caso_id": "c4", "cliente": "Quebrado", "categoria": "", "dados_json": "{nao é json"},
    ]
    consultas = []

    class _Con:
        def execute(self, sql, parametros):
            consultas.append((sql, parametros))
            return self

        def fetchall(self):
            return linhas

    class _Conectar:
        def __enter__(self):
            return _Con()

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(armazenamento, "conectar", lambda: _Conectar())
    lista = armazenamento.listar_peticoes_protocoladas()

    assert [p["caso_id"] for p in lista] == ["c3", "c1"]  # mais recente primeiro
    assert lista[0]["numero"] == "333" and lista[0]["cliente"] == "Rui"
    assert lista[1]["marcado_por"] == "Bia" and lista[1]["titulo"] == "Petição inicial"
    assert consultas[0][1] == ('%"protocolo": {%',)
    # O filtro do LIKE precisa casar com o que o `json.dumps` grava.
    assert '"protocolo": {' in linhas[0]["dados_json"]
