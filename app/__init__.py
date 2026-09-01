"""Extrator de documentos brasileiros com Mistral Document AI."""

# Também funciona quando a API é aberta diretamente com ``uvicorn app.main:app``.
# Nesse caminho não há o iniciar.ps1 para exportar o .env; sem carregá-lo aqui,
# JWT_SECRET fica invisível e o login só falha ao tentar emitir a sessão.
from __future__ import annotations

import os
from pathlib import Path


def _carregar_env_local() -> None:
    arquivo = Path(__file__).resolve().parent.parent / ".env"
    if not arquivo.is_file():
        return

    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        nome, valor = linha.split("=", 1)
        nome = nome.strip()
        if not nome or not nome.replace("_", "").isalnum():
            continue
        # O ambiente do processo vence o .env, como em uma implantação.
        os.environ.setdefault(nome, valor.strip().strip('"').strip("'"))


_carregar_env_local()

__version__ = "1.0.0"
