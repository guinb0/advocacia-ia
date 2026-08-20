"""Integração dos fluxos de envio do frontend com a API.

Cobre a rota de análise avulsa e as duas ações do checklist (Enviar e Enviar
outro), usando um processador falso para testar só o transporte multipart e o
registro da entrega, sem carregar o modelo OCR.

O falso entra em `pipeline.processar`, e não em `main._processar`, porque os dois
caminhos deixaram de ser o mesmo: `/api/extrair` ainda passa pelo `_processar`,
mas o envio pelo checklist grava a entrega como pendente e delega o OCR à task
`tasks.ocr.processar_entrega`, que chama o pipeline direto. Trocar só o
`_processar` deixaria o checklist lendo o PDF de mentira com o Paddle de verdade.

O checklist deixou de ler o documento numa thread da API: hoje ele enfileira no
Celery, e quem lê é o worker que mantém o Paddle aquecido. Por isso o teste liga
`task_always_eager` — sem worker vivo a entrega ficaria "processando" para
sempre, e o teste mediria a ausência de infraestrutura em vez do código. Em eager
o `apply_async` roda a task no próprio processo, então o caminho exercitado
continua sendo o de produção (`processar_entrega` de verdade), só que síncrono.

Rodar: .venv\\Scripts\\python.exe -m tests.test_uploads_api
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import armazenamento, main, pipeline
from app.celery_app import celery_app


def resultado_falso(nome: str, tipo_forcado: str | None) -> dict:
    tipo = tipo_forcado or "rg"
    return {
        "id": f"resultado-{len(CHAMADAS) + 1}",
        "arquivo": nome,
        "tipo": {"codigo": tipo, "detectado": tipo, "descricao": tipo},
        "validacao": {
            "veredito": "APROVADO",
            "dados_utilizaveis": True,
            "score_legibilidade": 95,
        },
    }


CHAMADAS: list[tuple[str, str | None]] = []


def processar_falso(conteudo: bytes, nome: str, idioma: str, tipo_forcado: str | None) -> dict:
    assert conteudo
    assert idioma == "pt"
    CHAMADAS.append((nome, tipo_forcado))
    return resultado_falso(nome, tipo_forcado)


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


def esperar_leitura(cliente: TestClient, caso_id: str, limite_s: float = 20.0) -> dict:
    """Devolve a situação do caso já com todas as leituras terminadas.

    O upload responde ANTES do OCR: a rota grava a entrega como 'processando' e
    devolve 201 em milissegundos. Sem esperar aqui, o teste conferiria o status
    do item antes de existir resultado — e passaria ou falharia conforme a
    máquina estivesse mais ou menos ocupada, que é o pior tipo de teste.
    """
    limite = time.monotonic() + limite_s
    while True:
        situacao = cliente.get(f"/api/casos/{caso_id}").json()
        lendo = [
            entrega
            for item in situacao["itens"]
            for entrega in item["entregas"]
            if entrega.get("status_proc") == "processando"
        ]
        if not lendo:
            return situacao
        if time.monotonic() > limite:
            raise AssertionError(f"{len(lendo)} entrega(s) ainda em leitura após {limite_s}s")
        time.sleep(0.05)


def main_teste() -> int:
    temporario = Path(tempfile.mkdtemp(prefix="ocr-upload-api-"))
    armazenamento.DIR_DADOS = temporario
    armazenamento.DIR_ARQUIVOS = temporario / "casos"
    armazenamento.CAMINHO_BANCO = temporario / "casos.db"
    armazenamento.inicializar()

    processador_original = pipeline.processar
    pipeline.processar = processar_falso

    # `task_eager_propagates` fica FALSO de propósito: `processar_entrega` já
    # registra a falha com `falhar_entrega` e relança, e propagar aqui faria a
    # exceção subir pelo `apply_async` até a rota — que devolveria 503 e esconderia
    # o estado da entrega, justamente o que estes testes conferem.
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
            # Botão "Extrair dados" do painel de análise avulsa.
            avulso = cliente.post(
                "/api/extrair",
                data={"idioma": "pt", "tipo": "auto"},
                files={"arquivo": ("documento.pdf", b"%PDF-1.7 teste", "application/pdf")},
            )
            falhas += not checar(avulso.status_code == 200, "análise avulsa envia PDF para /api/extrair")

            novo_caso = cliente.post(
                "/api/casos",
                data={"cliente": "Maria dos Uploads", "categoria": "acidente_trabalho_correios"},
            )
            caso_id = novo_caso.json()["id"]

            # Botões "Enviar" e "Enviar outro" chamam a mesma rota, uma vez por arquivo.
            for nome in ("rg-frente.pdf", "rg-verso.pdf"):
                resposta = cliente.post(
                    f"/api/casos/{caso_id}/documentos",
                    data={"item": "DOC.03", "idioma": "pt", "usar_para_rg_e_cpf": "false"},
                    files={"arquivo": (nome, b"%PDF-1.7 teste", "application/pdf")},
                )
                falhas += not checar(resposta.status_code == 201, f"{nome} chega à rota de checklist")

            situacao = esperar_leitura(cliente, caso_id)
            rg = next(item for item in situacao["itens"] if item["codigo"] == "DOC.03")
            falhas += not checar(len(rg["entregas"]) == 2, "os dois envios ficam registrados no RG")
            falhas += not checar(
                all(e["status_proc"] == "pronto" for e in rg["entregas"]),
                "as duas leituras terminam sem erro",
            )
            falhas += not checar(rg["status"] == "entregue", "o item enviado fica concluído")

            # O item do checklist manda o tipo esperado ("rg") para orientar QUAIS
            # campos extrair. Isso não cega a conferência de arquivo trocado: o
            # `pipeline.processar` roda o classificador SEMPRE, mesmo com tipo
            # forçado, e guarda o palpite dele em `tipo.detectado` — que é o campo
            # lido por `casos.tipo_confere`. Já a análise avulsa vai com `tipo=auto`,
            # e por isso chega como `None`.
            falhas += not checar(
                CHAMADAS
                == [("documento.pdf", None), ("rg-frente.pdf", "rg"), ("rg-verso.pdf", "rg")],
                "nome e tipo esperado chegam ao processador",
            )

            # Rota de dados de teste: desligada por padrão, liga só com a env var.
            sem_flag = cliente.post(
                f"/api/casos/{caso_id}/documentos/teste", data={"item": "DOC.04"}
            )
            falhas += not checar(sem_flag.status_code == 404, "sem a flag, a rota de teste não responde")

            os.environ["PERMITIR_DADOS_TESTE"] = "true"
            try:
                com_flag = cliente.post(
                    f"/api/casos/{caso_id}/documentos/teste", data={"item": "DOC.04"}
                )
                falhas += not checar(com_flag.status_code == 201, "com a flag, cria a entrega falsa")

                situacao = cliente.get(f"/api/casos/{caso_id}").json()
                cpf = next(item for item in situacao["itens"] if item["codigo"] == "DOC.04")
                falhas += not checar(
                    cpf["status"] == "entregue" and cpf["entregas"][0]["status_proc"] == "pronto",
                    "o item de teste fica entregue sem passar pelo OCR",
                )
            finally:
                del os.environ["PERMITIR_DADOS_TESTE"]
    finally:
        pipeline.processar = processador_original
        celery_app.conf.task_always_eager = eager_original
        celery_app.conf.task_eager_propagates = propaga_original

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
