"""Regressão: campos no banco nunca podem sobreviver sozinhos ao anexo."""

from __future__ import annotations

import hashlib
import tempfile
from contextlib import contextmanager
from pathlib import Path

from app import armazenamento


class Resultado:
    def __init__(self, linha):
        self.linha = linha

    def fetchone(self):
        return self.linha


class Conexao:
    def __init__(self, linha):
        self.linha = linha

    def execute(self, *_args, **_kwargs):
        return Resultado(self.linha)


def test_restaura_anexo_ausente_do_banco(monkeypatch) -> None:
    raiz = Path(tempfile.mkdtemp(prefix="anexo-duravel-"))
    conteudo = b"documento que nao pode desaparecer"
    linha = {
        "caso_id": "caso-1",
        "caminho": str(raiz / "pasta-antiga" / "documento.pdf"),
        "conteudo": conteudo,
        "conteudo_sha256": hashlib.sha256(conteudo).hexdigest(),
    }

    @contextmanager
    def conectar_falso():
        yield Conexao(linha)

    monkeypatch.setattr(armazenamento, "DIR_ARQUIVOS", raiz / "casos")
    monkeypatch.setattr(armazenamento, "conectar", conectar_falso)

    restaurado = armazenamento.caminho_duravel_da_entrega("entrega-1")
    assert restaurado == (raiz / "casos" / "caso-1" / "documento.pdf").resolve()
    assert restaurado.read_bytes() == conteudo


def test_recusa_copia_duravel_corrompida(monkeypatch) -> None:
    raiz = Path(tempfile.mkdtemp(prefix="anexo-corrompido-"))
    linha = {
        "caso_id": "caso-1",
        "caminho": str(raiz / "sumiu.pdf"),
        "conteudo": b"outro conteudo",
        "conteudo_sha256": hashlib.sha256(b"conteudo correto").hexdigest(),
    }

    @contextmanager
    def conectar_falso():
        yield Conexao(linha)

    monkeypatch.setattr(armazenamento, "DIR_ARQUIVOS", raiz / "casos")
    monkeypatch.setattr(armazenamento, "conectar", conectar_falso)
    assert armazenamento.caminho_duravel_da_entrega("entrega-1") is None
