r"""Conecta a instância do WhatsApp na Evolution API e mostra o QR Code.

O envio do link de avaliação (`app/whatsapp.py`) só funciona depois que alguém
apontou a câmera do celular do escritório para um QR Code e a Evolution API
guardou aquela sessão. Esse pareamento não é código: é um ato humano, com prazo
de validade curto — o QR expira em cerca de 40 segundos e precisa ser gerado de
novo. Por isso ele mora aqui, num script que se roda na hora em que o celular
está na mão, e não numa rotina de inicialização.

O script cria a instância se ela ainda não existir, pede o QR e grava em
`tmp/evolution-qrcode.png` (a imagem é aberta no visualizador padrão do Windows).
Se a instância já estiver pareada, ele diz isso e não gera QR nenhum.

    .venv\Scripts\python.exe -m scripts.evolution_qrcode

Lê `EVOLUTION_API_URL`, `EVOLUTION_API_KEY` e `EVOLUTION_INSTANCE` do `.env`.
A chave e o corpo de respostas de erro nunca são impressos. Um HTTP 401 confirma
rejeição da requisição, mas não basta para atribuir a causa à chave.
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "tmp" / "evolution-qrcode.png"


def _configuracao() -> tuple[str, str, str]:
    load_dotenv(RAIZ / ".env")
    base = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
    chave = os.getenv("EVOLUTION_API_KEY", "")
    instancia = os.getenv("EVOLUTION_INSTANCE", "")
    faltando = [
        nome
        for nome, valor in (
            ("EVOLUTION_API_URL", base),
            ("EVOLUTION_API_KEY", chave),
            ("EVOLUTION_INSTANCE", instancia),
        )
        if not valor
    ]
    if faltando:
        sys.exit("Falta preencher no .env: " + ", ".join(faltando))
    return base, chave, instancia


def _gravar_qrcode(base64_qr: str) -> None:
    dados = base64_qr.split(",", 1)[-1]
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_bytes(base64.b64decode(dados))
    print(f"QR Code gravado em {DESTINO}")
    if sys.platform == "win32":
        os.startfile(DESTINO)  # noqa: S606 - abre o visualizador de imagens


def main() -> int:
    base, chave, instancia = _configuracao()
    cabecalhos = {"apikey": chave, "Content-Type": "application/json"}

    with httpx.Client(base_url=base, headers=cabecalhos, timeout=30) as cliente:
        estado = cliente.get(f"/instance/connectionState/{instancia}")
        if estado.status_code in (401, 403):
            return _erro(
                f"A consulta de status recebeu HTTP {estado.status_code} [EVO-DIAG-2]. "
                "Confira URL, proxy, instância e autenticação; o código não prova, "
                "sozinho, erro na chave."
            )

        if estado.status_code == 404:
            print(f"Instância '{instancia}' não existe ainda. Criando...")
            criacao = cliente.post(
                "/instance/create",
                json={"instanceName": instancia, "qrcode": True, "integration": "WHATSAPP-BAILEYS"},
            )
            if criacao.status_code >= 400:
                return _erro(
                    f"Não consegui criar a instância (HTTP {criacao.status_code}) [EVO-DIAG-2]."
                )
            corpo = criacao.json()
            qr = (corpo.get("qrcode") or {}).get("base64")
            if qr:
                _gravar_qrcode(qr)
                print("Escaneie pelo WhatsApp > Aparelhos conectados > Conectar aparelho.")
                return 0

        elif estado.status_code < 400:
            situacao = (estado.json().get("instance") or {}).get("state")
            if situacao == "open":
                print(f"A instância '{instancia}' já está conectada. Nada a escanear.")
                return 0
            print(f"Instância '{instancia}' está em '{situacao}'. Pedindo um QR novo...")

        conexao = cliente.get(f"/instance/connect/{instancia}")
        if conexao.status_code >= 400:
            return _erro(
                f"Não consegui pedir o QR (HTTP {conexao.status_code}) [EVO-DIAG-2]."
            )
        corpo = conexao.json()
        qr = corpo.get("base64") or (corpo.get("qrcode") or {}).get("base64")
        if not qr:
            return _erro("A Evolution API respondeu sem QR Code [EVO-DIAG-2-QR-EMPTY].")
        _gravar_qrcode(qr)
        print("Escaneie pelo WhatsApp > Aparelhos conectados > Conectar aparelho.")
        print("O código vale ~40 segundos; rode de novo se expirar.")
    return 0


def _erro(mensagem: str) -> int:
    print(mensagem, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
