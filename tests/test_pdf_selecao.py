"""PDF único com os documentos MARCADOS dentro de uma classificação.

Cobre a rota `POST /api/casos/{caso_id}/documentos.pdf`, irmã de
`test_zip_selecao.py`: mesma seleção e mesmas guardas — o que muda é a saída,
um único PDF com as páginas de todos os arquivos marcados, na ordem em que
foram marcados. PDF entra intacto; imagem vira página.

Rodar: .venv\\Scripts\\python.exe -m tests.test_pdf_selecao
"""

from __future__ import annotations

import io
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pypdfium2 as pdfium
from fastapi.testclient import TestClient
from PIL import Image

from app import armazenamento, main, pipeline
from app.celery_app import celery_app

from tests.banco_de_teste import exigir_banco_de_teste

exigir_banco_de_teste()


def processar_falso(
    conteudo: bytes,
    nome: str,
    idioma: str,
    tipo_forcado: str | None = None,
    **_opcoes: object,
) -> dict:
    tipo = tipo_forcado or "rg"
    return {
        "id": f"resultado-{nome}",
        "arquivo": nome,
        "tipo": {
            "codigo": tipo,
            "detectado": tipo,
            "descricao": tipo,
            "descricao_detectado": tipo,
            "confianca_classificacao": 30,
        },
        "campos": [],
        "validacao": {
            "veredito": "APROVADO",
            "dados_utilizaveis": True,
            "texto_utilizavel": True,
            "score_legibilidade": 95,
        },
    }


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


def esperar_leitura(cliente: TestClient, caso_id: str, limite_s: float = 20.0) -> dict:
    limite = time.monotonic() + limite_s
    while True:
        situacao = cliente.get(f"/api/casos/{caso_id}").json()
        lendo = [
            entrega
            for item in situacao["itens"]
            for entrega in item["entregas"]
            if entrega.get("status_proc") in {"na_fila", "processando"}
        ]
        if not lendo:
            return situacao
        if time.monotonic() > limite:
            raise AssertionError(f"{len(lendo)} entrega(s) ainda em leitura")
        time.sleep(0.05)


def _png_de_uma_pagina(cor: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (120, 160), cor).save(buf, format="PNG")
    return buf.getvalue()


def _pdf_de_duas_paginas() -> bytes:
    buf = io.BytesIO()
    imagem = Image.new("RGB", (100, 140), "white")
    outra = Image.new("RGB", (100, 140), "black")
    imagem.save(buf, format="PDF", save_all=True, append_images=[outra])
    return buf.getvalue()


def _enviar(cliente: TestClient, caso_id: str, item: str, nome: str, corpo: bytes, tipo: str) -> str:
    resposta = cliente.post(
        f"/api/casos/{caso_id}/documentos",
        data={"item": item, "idioma": "pt", "usar_para_rg_e_cpf": "false"},
        files={"arquivo": (nome, corpo, tipo)},
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["entrega"]["id"]


def main_teste() -> int:
    temporario = Path(tempfile.mkdtemp(prefix="pdf-selecao-"))
    armazenamento.DIR_DADOS = temporario
    armazenamento.DIR_ARQUIVOS = temporario / "casos"
    # `CAMINHO_BANCO` não redireciona mais o banco (era do tempo do SQLite): a conexão
    # vem de `SQLSERVER_*`. A trava no topo do arquivo é o que impede este teste de
    # escrever em produção — ver `tests/banco_de_teste.py`.
    armazenamento.CAMINHO_BANCO = temporario / "casos.db"
    armazenamento.inicializar()

    processador_original = pipeline.processar
    pipeline.processar = processar_falso

    eager_original = celery_app.conf.task_always_eager
    propaga_original = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False

    falhas = 0

    try:
        with (
            patch.object(main, "_tentar_aquecer"),
            patch.object(main.auth, "ATIVA", False),
            TestClient(main.app) as cliente,
        ):
            caso_id = cliente.post(
                "/api/casos",
                data={"cliente": "Beto do Combinado", "categoria": "acidente_trabalho_correios"},
            ).json()["id"]

            # DOC.03: uma imagem (1 página) + um PDF de 2 páginas = 3 páginas.
            id_imagem = _enviar(
                cliente, caso_id, "DOC.03", "foto.png", _png_de_uma_pagina("red"), "image/png"
            )
            id_pdf = _enviar(
                cliente, caso_id, "DOC.03", "laudo.pdf", _pdf_de_duas_paginas(), "application/pdf"
            )
            # Outra classificação, para provar que não entra no combinado.
            id_doc04 = _enviar(
                cliente, caso_id, "DOC.04", "outro.png", _png_de_uma_pagina("blue"), "image/png"
            )
            esperar_leitura(cliente, caso_id)

            resposta = cliente.request(
                "POST",
                f"/api/casos/{caso_id}/documentos.pdf",
                json={"classificacao": "DOC.03", "entregas": [id_imagem, id_pdf]},
            )
            falhas += not checar(resposta.status_code == 200, "seleção mista gera o PDF (200)")
            falhas += not checar(
                resposta.headers.get("content-type") == "application/pdf",
                "resposta vem como application/pdf",
            )
            falhas += not checar(
                resposta.headers.get("X-Arquivos") == "2", "cabeçalho X-Arquivos == 2"
            )
            falhas += not checar(
                resposta.headers.get("X-Paginas") == "3",
                "cabeçalho X-Paginas == 3 (1 da imagem + 2 do PDF)",
            )

            with pdfium.PdfDocument(resposta.content) as combinado:
                falhas += not checar(len(combinado) == 3, "o PDF final tem 3 páginas")

            # --- documento de outra classificação não entra no combinado -----
            intruso = cliente.request(
                "POST",
                f"/api/casos/{caso_id}/documentos.pdf",
                json={"classificacao": "DOC.03", "entregas": [id_imagem, id_doc04]},
            )
            falhas += not checar(
                intruso.status_code == 409, "id de outra classificação recusa o pedido inteiro (409)"
            )

            # --- teto de páginas -----------------------------------------
            with patch.object(main, "MAX_PAGINAS_PDF_SELECAO", 2):
                estourou = cliente.request(
                    "POST",
                    f"/api/casos/{caso_id}/documentos.pdf",
                    json={"classificacao": "DOC.03", "entregas": [id_imagem, id_pdf]},
                )
            falhas += not checar(
                estourou.status_code == 415, "seleção acima do teto de páginas recusa (415)"
            )
    finally:
        pipeline.processar = processador_original
        celery_app.conf.task_always_eager = eager_original
        celery_app.conf.task_eager_propagates = propaga_original

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
