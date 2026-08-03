"""Integração dos fluxos de envio do frontend com a API.

Cobre a rota de análise avulsa e as duas ações do checklist (Enviar e Enviar
outro), usando um processador falso para testar só o transporte multipart e o
registro da entrega, sem carregar o modelo OCR.

Rodar: .venv\\Scripts\\python.exe -m tests.test_uploads_api
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app import armazenamento, main


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


async def processar_falso(conteudo: bytes, nome: str, idioma: str, tipo_forcado: str | None) -> dict:
    assert conteudo
    assert idioma == "pt"
    CHAMADAS.append((nome, tipo_forcado))
    return resultado_falso(nome, tipo_forcado)


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


def main_teste() -> int:
    temporario = Path(tempfile.mkdtemp(prefix="ocr-upload-api-"))
    armazenamento.DIR_DADOS = temporario
    armazenamento.DIR_ARQUIVOS = temporario / "casos"
    armazenamento.CAMINHO_BANCO = temporario / "casos.db"
    armazenamento.inicializar()

    processador_original = main._processar
    main._processar = processar_falso
    falhas = 0
    try:
        with TestClient(main.app) as cliente:
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

            situacao = cliente.get(f"/api/casos/{caso_id}").json()
            rg = next(item for item in situacao["itens"] if item["codigo"] == "DOC.03")
            falhas += not checar(len(rg["entregas"]) == 2, "os dois envios ficam registrados no RG")
            falhas += not checar(rg["status"] == "entregue", "o item enviado fica concluído")
            falhas += not checar(
                CHAMADAS == [("documento.pdf", None), ("rg-frente.pdf", "rg"), ("rg-verso.pdf", "rg")],
                "nomes e tipo esperado chegam ao processador",
            )
    finally:
        main._processar = processador_original

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
