from __future__ import annotations

from app import mistral_ocr


def test_blocos_preservam_bbox_e_confianca_real():
    resposta = {"pages": [{"blocks": [{
        "type": "text", "content": "Nome: Maria da Silva",
        "top_left_x": 10, "top_left_y": 20,
        "bottom_right_x": 210, "bottom_right_y": 42,
        "confidence_scores": {"average_content_confidence_score": 0.97},
    }]}]}
    linhas = mistral_ocr._linhas_da_resposta(resposta)
    assert len(linhas) == 1
    assert linhas[0].texto == "Nome: Maria da Silva"
    assert linhas[0].confianca == 0.97
    assert (linhas[0].x, linhas[0].y, linhas[0].largura, linhas[0].altura) == (10, 20, 200, 22)


def test_pdf_e_enviado_nativamente_e_com_schema(monkeypatch):
    capturado = {}

    class Resposta:
        def raise_for_status(self):
            return None

        def json(self):
            return {"pages": [{"index": 0, "markdown": "Documento teste", "blocks": []}], "document_annotation": "{}"}

    class Cliente:
        def __init__(self, **kwargs):
            capturado["timeout"] = kwargs["timeout"]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def post(self, url, *, headers, json):
            capturado.update(url=url, headers=headers, payload=json)
            return Resposta()

    monkeypatch.setenv("MISTRAL_API_KEY", "chave-de-teste")
    monkeypatch.setattr(mistral_ocr.httpx, "Client", Cliente)
    resultado = mistral_ocr.ler_documento(
        b"%PDF-1.4 teste", "processo.pdf", categoria="Teste",
        checklist=[{"codigo": "DOC.01", "nome": "Procuração"}],
    )
    payload = capturado["payload"]
    assert payload["model"] == "mistral-ocr-4-1"
    assert payload["document"]["type"] == "document_url"
    assert payload["include_blocks"] is True
    assert payload["document_annotation_format"]["json_schema"]["strict"] is True
    assert resultado["paginas"][0]["numero"] == 1
