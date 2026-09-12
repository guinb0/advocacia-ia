"""ZIP com os documentos MARCADOS dentro de uma classificação.

Cobre a rota `POST /api/casos/{caso_id}/documentos.zip`, que é a irmã seletiva do
GET de mesmo endereço: em vez do caso inteiro, empacota só as entregas que o
atendente marcou dentro de UM item do checklist.

O que se mede aqui é o recorte e as guardas — quais arquivos entram, quais são
recusados e o que acontece nos limites. O OCR é falso (mesmo esquema do
`test_uploads_api`): o que importa é o byte que subiu voltar íntegro dentro do
ZIP, não a leitura.

Rodar: .venv\\Scripts\\python.exe -m tests.test_zip_selecao
"""

from __future__ import annotations

import io
import tempfile
import time
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

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
    """Substitui o OCR. Só devolve metadados plausíveis para a entrega ficar
    'pronta' — o arquivo em si já foi gravado pela rota antes de chegar aqui."""
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
    """Situação do caso já com todas as leituras encerradas — o upload responde
    antes do OCR, e sem esperar aqui o teste mediria a máquina, não o código."""
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


def _enviar(cliente: TestClient, caso_id: str, item: str, nome: str, corpo: bytes) -> str:
    resposta = cliente.post(
        f"/api/casos/{caso_id}/documentos",
        data={"item": item, "idioma": "pt", "usar_para_rg_e_cpf": "false"},
        files={"arquivo": (nome, corpo, "application/pdf")},
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["entrega"]["id"]


def main_teste() -> int:
    temporario = Path(tempfile.mkdtemp(prefix="zip-selecao-"))
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
                data={"cliente": "Ana / Zíper", "categoria": "acidente_trabalho_correios"},
            ).json()["id"]

            # Três documentos na classificação DOC.03, cada um com conteúdo
            # distinto — é o que deixa a conferência de integridade valer.
            corpos = {
                "laudo-a.pdf": b"%PDF-1.7 conteudo do laudo A " + b"A" * 40,
                "laudo-b.pdf": b"%PDF-1.7 conteudo do laudo B " + b"B" * 80,
                "laudo-c.pdf": b"%PDF-1.7 conteudo do laudo C " + b"C" * 120,
            }
            ids_doc03 = [
                _enviar(cliente, caso_id, "DOC.03", nome, corpo)
                for nome, corpo in corpos.items()
            ]
            # Um documento numa OUTRA classificação, para provar que não vaza.
            id_doc04 = _enviar(
                cliente, caso_id, "DOC.04", "outro.pdf", b"%PDF-1.7 documento de outra classe"
            )
            esperar_leitura(cliente, caso_id)

            # --- cenário da issue: marcar 3, gerar o ZIP, validar o conteúdo ----
            resposta = cliente.request(
                "POST",
                f"/api/casos/{caso_id}/documentos.zip",
                json={"classificacao": "DOC.03", "entregas": ids_doc03},
            )
            falhas += not checar(resposta.status_code == 200, "seleção de 3 gera o ZIP (200)")
            falhas += not checar(
                resposta.headers.get("content-type") == "application/zip",
                "resposta vem como application/zip",
            )
            falhas += not checar(
                resposta.headers.get("X-Arquivos") == "3", "cabeçalho X-Arquivos == 3"
            )

            with zipfile.ZipFile(io.BytesIO(resposta.content)) as pacote:
                nomes = pacote.namelist()
                falhas += not checar(len(nomes) == 3, "o ZIP tem exatamente 3 arquivos")
                falhas += not checar(
                    all(" - " in n for n in nomes) and all(not n.startswith("00") for n in nomes),
                    "cada arquivo sai prefixado pela classificação",
                )
                # Integridade: cada byte que subiu volta igual, casado pelo
                # sufixo do nome original preservado dentro do pacote.
                por_sufixo = {n.rsplit(" - ", 1)[-1]: pacote.read(n) for n in nomes}
                integro = all(
                    por_sufixo.get(nome) == corpo for nome, corpo in corpos.items()
                )
                falhas += not checar(integro, "conteúdo descompactado bate byte a byte")

            # --- documento de outra classificação não entra por engano ---------
            intruso = cliente.request(
                "POST",
                f"/api/casos/{caso_id}/documentos.zip",
                json={"classificacao": "DOC.03", "entregas": [*ids_doc03[:2], id_doc04]},
            )
            falhas += not checar(
                intruso.status_code == 409, "id de outra classificação recusa o pedido inteiro (409)"
            )

            # --- id que não existe / não é do caso ----------------------------
            fantasma = cliente.request(
                "POST",
                f"/api/casos/{caso_id}/documentos.zip",
                json={"classificacao": "DOC.03", "entregas": ["nao-existe"]},
            )
            falhas += not checar(fantasma.status_code == 409, "id inexistente recusa (409)")

            # --- classificação que não existe na categoria -------------------
            sem_classe = cliente.request(
                "POST",
                f"/api/casos/{caso_id}/documentos.zip",
                json={"classificacao": "DOC.99", "entregas": ids_doc03},
            )
            falhas += not checar(
                sem_classe.status_code == 404, "classificação inexistente na categoria (404)"
            )

            # --- teto de quantidade -----------------------------------------
            with patch.object(main, "MAX_ITENS_ZIP_SELECAO", 2):
                estourou = cliente.request(
                    "POST",
                    f"/api/casos/{caso_id}/documentos.zip",
                    json={"classificacao": "DOC.03", "entregas": ids_doc03},
                )
            falhas += not checar(
                estourou.status_code == 413, "seleção acima do teto de itens recusa (413)"
            )

            # --- lista vazia barrada pelo schema ---------------------------
            vazio = cliente.request(
                "POST",
                f"/api/casos/{caso_id}/documentos.zip",
                json={"classificacao": "DOC.03", "entregas": []},
            )
            falhas += not checar(vazio.status_code == 422, "lista vazia barrada na validação (422)")
    finally:
        pipeline.processar = processador_original
        celery_app.conf.task_always_eager = eager_original
        celery_app.conf.task_eager_propagates = propaga_original

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
