"""A IA tem de extrair o MÁXIMO de cada documento, sem deixar informação passar."""

import io
import json

import httpx
import pytest
from PIL import Image

from app import (
    analise_documentos,
    indexacao_documento,
    mistral_ocr,
    peticao_local,
    pipeline,
    skill_de_arquivo,
    valor_documento,
    visao_documento,
)
from app.extractors import Linha


def _pdf_escaneado(paginas: int) -> bytes:
    """PDF de imagens (sem camada de texto), como o que sai de um scanner."""
    imagens = [Image.new("RGB", (1240, 1754), "white") for _ in range(paginas)]
    saida = io.BytesIO()
    imagens[0].save(saida, format="PDF", save_all=True, append_images=imagens[1:], resolution=150)
    return saida.getvalue()


@pytest.fixture
def ocr_falso(monkeypatch):
    lidas = []

    def ler(imagem, _lang="pt"):
        lidas.append(imagem.shape[:2])
        n = len(lidas)
        linhas = [Linha(f"conteúdo integral da página {n}, linha {i}", 0.95, float(i), 0.0) for i in range(5)]
        return linhas, {"fila_s": 0.0, "inferencia_s": 0.0, "pos_processamento_s": 0.0, "total_s": 0.0}

    monkeypatch.setattr(pipeline, "rodar_ocr_com_tempo", ler)
    monkeypatch.setattr(pipeline, "OCR_PAGINAS_PARALELAS", 1)
    monkeypatch.setattr(pipeline, "RESGATE_LIGADO", False)
    return lidas


def test_pdf_de_varias_paginas_e_lido_pagina_a_pagina_em_resolucao_legivel(ocr_falso):
    doc = pipeline.processar(_pdf_escaneado(6), "prontuario.pdf", gerar_arquivos_temporarios=False)

    # Antes as 6 páginas viravam UMA imagem reduzida a 2000 px de altura: ~330 px por página.
    assert len(ocr_falso) == 6
    assert all(altura >= 1500 for altura, _ in ocr_falso), ocr_falso
    texto = doc["texto_completo"]
    posicoes = [texto.index(f"página {n}, linha 0") for n in range(1, 7)]
    assert posicoes == sorted(posicoes), "as páginas saem na ordem do documento"
    assert doc["ocr"]["paginas"] == 6 and doc["ocr"]["lido_por_pagina"]


def test_pdf_de_uma_pagina_continua_numa_leitura_so(ocr_falso):
    doc = pipeline.processar(_pdf_escaneado(1), "rg.pdf", gerar_arquivos_temporarios=False)
    assert len(ocr_falso) == 1 and not doc["ocr"]["lido_por_pagina"]


def test_pagina_que_falha_nao_some_calada(monkeypatch):
    def ler(imagem, _lang="pt"):
        raise httpx.ConnectError("fora do ar")

    monkeypatch.setattr(pipeline, "rodar_ocr_com_tempo", ler)
    with pytest.raises(httpx.ConnectError):
        pipeline.processar(_pdf_escaneado(3), "laudo.pdf", gerar_arquivos_temporarios=False)


class _Resposta:
    def __init__(self, corpo: dict, status: int = 200):
        self._corpo, self.status_code, self.text = corpo, status, json.dumps(corpo)
        self.headers: dict = {}

    def json(self):
        return self._corpo

    def raise_for_status(self):
        return None


def test_ocr_cortado_no_teto_e_relido_pela_mistral(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "chave")
    monkeypatch.setenv("MISTRAL_API_KEY", "chave")
    enviados = []

    def post(_cliente, _url, **kwargs):
        enviados.append(kwargs["json"])
        return _Resposta({"choices": [{"finish_reason": "length", "message": {"content": "metade da página"}}]})

    monkeypatch.setattr(mistral_ocr, "_post_com_repeticao", post)
    monkeypatch.setattr(mistral_ocr.custos_api, "registrar", lambda *_a, **_k: None)
    monkeypatch.setattr(mistral_ocr, "_ocr_via_mistral", lambda *_a: {"pages": [{"markdown": "página inteira"}]})

    resposta = mistral_ocr._ocr_via_openrouter("image/png", b"x")
    assert resposta["pages"][0]["markdown"] == "página inteira"
    assert enviados[0]["max_tokens"] >= 16000
    instrucao = enviados[0]["messages"][0]["content"]
    assert "sem resumir" in instrucao and "[ilegível]" in instrucao and "manuscrito" in instrucao


def test_leitura_do_documento_devolve_todos_os_dados(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "chave")
    enviados = []
    achados = [{"campo": f"Salário {m:02d}/2025", "valor": f"R$ {1500 + m},00"} for m in range(1, 13)]
    achados += [{"campo": "CID", "valor": "M54.5"}, {"campo": "CID", "valor": "S62.3"}, {"campo": "CID", "valor": "M54.5"}]

    def post(_url, **kwargs):
        enviados.append(kwargs["json"])
        return _Resposta({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
            "documento": "CTPS", "codigo_documento": "ctps", "resumo": "Carteira com dois contratos.",
            "achados": achados, "atencao": [f"alerta {i}" for i in range(8)],
        })}}]})

    monkeypatch.setattr(valor_documento.httpx, "post", post)
    monkeypatch.setattr(valor_documento.custos_api, "registrar", lambda *_a, **_k: None)
    texto = [{"texto": "linha da carteira de trabalho " * 8} for _ in range(150)] + [{"texto": "ÚLTIMO CONTRATO: 2024"}]

    r = valor_documento.ler({"texto_linhas": texto})
    assert len(r["achados"]) == 14, "12 salários + 2 CIDs distintos; o CID repetido sai uma vez"
    assert r["resumo"] == "Carteira com dois contratos." and len(r["atencao"]) == 8
    assert enviados[0]["max_tokens"] >= 8000
    assert "ÚLTIMO CONTRATO: 2024" in enviados[0]["messages"][1]["content"], "o fim do documento chega ao modelo"
    assert "EXTRAIA O MÁXIMO" in enviados[0]["messages"][0]["content"]


def test_achados_de_mesmo_nome_nao_se_perdem_no_documento():
    extracao = {"campos": [{"nome": "nome", "valor": "MARIA"}]}
    indexacao_documento.aplicar_interpretacao(extracao, {"achados": [
        {"campo": "CID", "valor": "M54.5"}, {"campo": "CID", "valor": "S62.3"},
        {"campo": "Nome", "valor": "OUTRA PESSOA"},
    ]})
    valores = {c["nome"]: c["valor"] for c in extracao["campos"]}
    assert valores["cid"] == "M54.5" and valores["cid_2"] == "S62.3"
    assert valores["nome"] == "MARIA" and "nome_2" not in valores, "campo do extrator não é duplicado"


def test_analise_do_caso_pensa_mais_e_devolve_mais_achados(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "chave")
    enviados = []

    def post(_url, **kwargs):
        enviados.append(kwargs["json"])
        return _Resposta({"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})

    monkeypatch.setattr(analise_documentos.httpx, "post", post)
    monkeypatch.setattr(analise_documentos.custos_api, "registrar", lambda *_a, **_k: None)
    analise_documentos._chamar_modelo("documentos")
    assert enviados[0]["reasoning"]["effort"] == "medium"
    assert "EXTRAIA O MÁXIMO" in analise_documentos.INSTRUCAO
    assert "Máximo 12" not in analise_documentos.INSTRUCAO and analise_documentos.MAX_ACHADOS >= 60
    assert analise_documentos.MAX_CARACTERES_POR_DOCUMENTO >= 25_000


def test_toda_leitura_de_documento_segue_a_skill_documental(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "chave")
    enviados = []

    def post(_url, **kwargs):
        enviados.append(kwargs["json"]["messages"][0]["content"])
        return _Resposta({"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})

    monkeypatch.setattr(analise_documentos.httpx, "post", post)
    monkeypatch.setattr(analise_documentos.custos_api, "registrar", lambda *_a, **_k: None)
    analise_documentos._chamar_modelo("documentos")
    caso = enviados[0]
    assert caso.startswith(analise_documentos.INSTRUCAO)
    assert "CRITÉRIOS DA SKILL DOCUMENTAL (analise-e-organizacao-documental)" in caso
    assert "Análise documento a documento" in caso and "Atualizado ou desatualizado" in caso
    assert "3.6 — Provas" in caso and "Arquivos duplicados" in caso
    assert "processo trabalhista" not in caso, "a skill vale para qualquer área do direito"

    for modulo in (valor_documento, visao_documento):
        texto = modulo.instrucao()
        assert texto.startswith(modulo.INSTRUCAO) and "Pode melhorar ou não pode melhorar" in texto
        assert "COMO APLICAR OS CRITÉRIOS DA SKILL" in texto

    monkeypatch.setattr(skill_de_arquivo, "carregar", lambda _n: (_ for _ in ()).throw(skill_de_arquivo.SkillAusente("x")))
    assert analise_documentos.instrucao_padrao() == analise_documentos.INSTRUCAO, "sem a skill, segue a instrução própria"
    assert valor_documento.instrucao() == valor_documento.INSTRUCAO


def test_peticao_recebe_o_que_a_leitura_achou_em_cada_documento():
    extracao = {"classificacao_semantica": {
        "tipo_semantico": "Laudo médico", "resumo": "Laudo conclui incapacidade parcial.",
        "achados": [{"campo": "CID", "valor": "S62.3"}, {"campo": "Médico", "valor": "Dr. João, CRM 1234"}],
        "atencao": ["Sem data de emissão"],
    }}
    leitura = peticao_local.leitura_da_ia(extracao)
    assert "Resumo: Laudo conclui incapacidade parcial." in leitura and "- CID: S62.3" in leitura
    assert "Atenção: Sem data de emissão" in leitura

    ledger = [{"numero": 1, "canonical_label": "Documento 01", "canonical_file": "laudo.pdf", "document_type": "Laudo",
               "source_files": ["laudo.pdf"]}]
    documentos = [{"arquivo": "laudo.pdf", "texto": "texto do laudo " * 2000, "leitura": leitura}]
    contexto = "\n".join(peticao_local._indice_e_textos_documentais(ledger, documentos))
    assert contexto.index("O QUE A LEITURA DE CADA DOCUMENTO ENCONTROU") < contexto.index("TEXTOS EXTRAÍDOS")
    assert "- Médico: Dr. João, CRM 1234" in contexto
    assert contexto.count("texto do laudo") == 2000, "documento de 30 mil caracteres entra inteiro"
