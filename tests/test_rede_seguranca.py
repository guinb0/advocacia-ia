"""A rede de segurança do app: falha inesperada vira 503 legível, nunca 500 cru.

Roda como script (convenção deste repositório):

    PYTHONPATH=. .venv/Scripts/python.exe tests/test_rede_seguranca.py
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import main


def _cliente() -> TestClient:
    @main.app.get("/api/_teste_estouro")
    def _estouro():  # pragma: no cover - existe só para estourar
        raise RuntimeError("estouro proposital do teste")

    # raise_server_exceptions=False para o TestClient devolver a resposta em vez
    # de propagar — é assim que o navegador real vê a rota.
    return TestClient(main.app, raise_server_exceptions=False)


def checar(condicao: bool, descricao: str) -> int:
    print(f"  {'PASS' if condicao else '>> FALHA'} {descricao}")
    return 0 if condicao else 1


def main_teste() -> int:
    cliente = _cliente()
    resposta = cliente.get("/api/_teste_estouro")
    falhas = 0
    falhas += checar(resposta.status_code == 503, "erro imprevisto vira 503, não 500")
    corpo = resposta.json()
    falhas += checar(
        "detail" in corpo and "traceback" not in resposta.text.lower(),
        "a resposta é uma mensagem legível, sem traceback cru",
    )
    falhas += checar(
        "indisponível" in corpo.get("detail", "") or "instantes" in corpo.get("detail", ""),
        "a mensagem tranquiliza o usuário de que nada foi perdido",
    )
    print("TODOS OS TESTES PASSARAM" if not falhas else f"{falhas} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
