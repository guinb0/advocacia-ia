"""Configuração comum dos testes.

O diretório temporário padrão do pytest (`%TEMP%\\pytest-of-<usuário>`) é
inacessível nesta instalação do Windows: qualquer teste que peça `tmp_path`
morre com `PermissionError: [WinError 5] Acesso negado` ANTES de rodar. O efeito
colateral é pior que a falha em si — o erro de permissão mascarava falhas reais
de asserção nos mesmos testes, que só apareceram quando o temp passou a
funcionar. Ancorar a base dentro do projeto tira essa variável do caminho.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

BASE_TMP = Path(__file__).resolve().parent.parent / "tmp" / "pytest"


def pytest_configure(config: pytest.Config) -> None:
    if config.option.basetemp:
        return
    BASE_TMP.mkdir(parents=True, exist_ok=True)
    # `tmp_path` versiona os diretórios (`.../pytest-0`, `-1`, ...) e guarda os
    # três últimos. Numa base fixa dentro do projeto isso acumula entre execuções,
    # então a limpeza é feita na entrada, não na saída: assim o diretório da última
    # execução continua disponível para inspeção quando um teste falha.
    for antigo in BASE_TMP.glob("pytest-*"):
        shutil.rmtree(antigo, ignore_errors=True)
    config.option.basetemp = BASE_TMP
