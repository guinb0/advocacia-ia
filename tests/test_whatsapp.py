"""Envio de mensagens operacionais pela Evolution API.

Nada aqui fala com a Evolution de verdade: `_enviar_texto` é trocado por um
gravador. Bater na API real mandaria WhatsApp para número de gente a cada
execução da suíte — e o número que está no fixture é fictício justamente porque
um teste que dispara mensagem é um teste que ninguém roda duas vezes.

O que está coberto é o que dói: reenviar link para quem já assinou, mandar um
link que não existe, e — o motivo de o endpoint receber identificadores em vez
da URL — a tela não conseguir escolher para onde a mensagem vai.

Rodar: .venv\Scripts\python.exe -m tests.test_whatsapp
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import whatsapp


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


CLIENTE = {
    "token": "sig-cliente",
    "nome": "Maria Aparecida da Silva",
    "telefone": "91988887777",
    "estado": "pendente",
    "url_assinatura": "https://app.zapsign.com.br/verificar/sig-cliente",
}
ESCRITORIO = {
    "token": "sig-escritorio",
    "nome": "Lara & Melo Advocacia",
    "telefone": "",
    "estado": "assinou",
    "url_assinatura": "https://app.zapsign.com.br/verificar/sig-escritorio",
}
REGISTRO = {
    "id": "abc",
    "nome": "Procuração — Maria Aparecida da Silva",
    "signatarios": [CLIENTE, ESCRITORIO],
}


def montar(registro: dict[str, Any] | None) -> tuple[TestClient, list[tuple[str, str]]]:
    """App só com o roteador do WhatsApp, com o transporte gravado."""
    enviadas: list[tuple[str, str]] = []

    async def gravar(numero: str, texto: str) -> None:
        enviadas.append((numero, texto))

    whatsapp._enviar_texto = gravar  # type: ignore[assignment]
    whatsapp.armazenamento.obter_assinatura = lambda _id: registro  # type: ignore[assignment]

    app = FastAPI()
    app.include_router(whatsapp.roteador)
    return TestClient(app), enviadas


def testar_numero() -> int:
    falhas = 0
    falhas += not checar(whatsapp._numero_brasileiro("(91) 98888-7777") == "5591988887777", "DDD vira 55+DDD")
    falhas += not checar(whatsapp._numero_brasileiro("5591988887777") == "5591988887777", "com DDI passa direto")
    for ruim in ("123", "", "999999999999999"):
        try:
            whatsapp._numero_brasileiro(ruim)
            falhas += not checar(False, f"{ruim!r} devia ser recusado")
        except Exception:
            falhas += not checar(True, f"{ruim!r} recusado")
    return falhas


def testar_texto() -> int:
    falhas = 0
    falhas += not checar(
        whatsapp._rotulo_do_documento("Procuração — Maria Aparecida da Silva") == "procuração",
        "o nome do cliente sai do texto que vai para o cliente",
    )
    falhas += not checar(whatsapp._rotulo_do_documento("") == "o documento", "sem nome, texto genérico")
    falhas += not checar(whatsapp._primeiro_nome("Maria Aparecida da Silva") == "Maria", "só o primeiro nome")
    falhas += not checar(whatsapp._primeiro_nome("") == "você", "sem nome, sem saudação quebrada")
    return falhas


def testar_link_assinatura() -> int:
    falhas = 0
    cliente, enviadas = montar(REGISTRO)

    r = cliente.post("/api/whatsapp/link-assinatura", json={"assinatura_id": "abc", "signatario_token": "sig-cliente"})
    falhas += not checar(r.status_code == 200 and r.json() == {"enviado": True}, "envio ao cliente aceito")
    falhas += not checar(len(enviadas) == 1, "uma mensagem, uma só")
    if enviadas:
        numero, texto = enviadas[0]
        falhas += not checar(numero == "5591988887777", "vai para o telefone do REGISTRO, não do pedido")
        falhas += not checar(CLIENTE["url_assinatura"] in texto, "o link vai no texto")
        falhas += not checar("procuração" in texto and "Maria" in texto, "diz qual documento e para quem")

    r = cliente.post("/api/whatsapp/link-assinatura", json={"assinatura_id": "abc", "signatario_token": "sig-escritorio"})
    falhas += not checar(r.status_code == 409, "quem já assinou não recebe link de novo")

    r = cliente.post("/api/whatsapp/link-assinatura", json={"assinatura_id": "abc", "signatario_token": "nao-existe"})
    falhas += not checar(r.status_code == 404, "signatário inexistente é 404")

    falhas += not checar(len(enviadas) == 1, "nenhuma recusa virou mensagem enviada")

    vazio, _ = montar(None)
    r = vazio.post("/api/whatsapp/link-assinatura", json={"assinatura_id": "sumiu", "signatario_token": "x"})
    falhas += not checar(r.status_code == 404, "documento inexistente é 404")
    return falhas


def testar_sem_telefone() -> int:
    registro = dict(REGISTRO, signatarios=[dict(CLIENTE, telefone="")])
    cliente, enviadas = montar(registro)
    r = cliente.post("/api/whatsapp/link-assinatura", json={"assinatura_id": "abc", "signatario_token": "sig-cliente"})
    falhas = not checar(r.status_code == 422, "signatário sem telefone é erro do dado, não da Evolution")

    registro = dict(REGISTRO, signatarios=[dict(CLIENTE, url_assinatura="")])
    cliente, _ = montar(registro)
    r = cliente.post("/api/whatsapp/link-assinatura", json={"assinatura_id": "abc", "signatario_token": "sig-cliente"})
    falhas += not checar(r.status_code == 409, "sem link guardado, manda conferir o e-mail da ZapSign")
    falhas += not checar(not enviadas, "nada foi enviado")
    return falhas


def testar_desconfigurado() -> int:
    """Sem `.env` preenchido a resposta é 503, e não um 500 sem explicação."""
    guardado = {c: os.environ.pop(c, None) for c in ("EVOLUTION_API_URL", "EVOLUTION_API_KEY", "EVOLUTION_INSTANCE")}
    # Recarrega o módulo para desfazer o `_enviar_texto` gravado dos outros
    # testes: aqui quem precisa rodar é o verdadeiro, porque o 503 é dele.
    import importlib

    modulo = importlib.reload(whatsapp)
    app = FastAPI()
    app.include_router(modulo.roteador)
    r = TestClient(app).post("/api/whatsapp/avaliacao-google", json={"telefone": "91988887777"})
    falhas = not checar(r.status_code == 503, "WhatsApp desligado responde 503")
    for chave, valor in guardado.items():
        if valor is not None:
            os.environ[chave] = valor
    return falhas


def main_teste() -> int:
    falhas = 0
    for titulo, teste in (
        ("telefone brasileiro", testar_numero),
        ("o texto que o cliente lê", testar_texto),
        ("link de assinatura por WhatsApp", testar_link_assinatura),
        ("dado faltando no signatário", testar_sem_telefone),
        ("Evolution não configurada", testar_desconfigurado),
    ):
        print(f"\n{titulo}")
        falhas += teste()
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
