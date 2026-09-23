"""O ZIP do caso inteiro leva também o que ainda não foi identificado.

`casos.montar_zip` só percorria `situacao["itens"]`. O arquivo que chegou e não
foi atribuído a nenhum item fica em `situacao["triagem"]` e ficava de fora do
pacote — o escritório levava um ZIP "completo" sem o documento por identificar.

Sem banco: `montar_situacao` e o armazenamento são substituídos, porque o que se
mede é a regra de quem entra no pacote, não a persistência.

Rodar: .venv\\Scripts\\python.exe -m pytest tests/test_zip_caso_triagem.py
"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from app import casos


def _situacao(itens: list[dict], triagem: list[dict]) -> dict:
    return {
        "caso": {"cliente": "Ana"},
        "itens": itens,
        "triagem": triagem,
        "progresso": {"pronto": False},
    }


def test_zip_inclui_documentos_em_triagem_e_em_leitura() -> None:
    pasta = Path(tempfile.mkdtemp(prefix="zip-triagem-"))
    arquivos = {
        "e1": ("rg.pdf", b"conteudo do rg"),
        "e2": ("solto.pdf", b"nao identificado"),
        "e3": ("lendo.pdf", b"ainda sendo lido"),
    }
    caminhos: dict[str, Path] = {}
    for eid, (nome, corpo) in arquivos.items():
        caminhos[eid] = pasta / nome
        caminhos[eid].write_bytes(corpo)

    situacao = _situacao(
        itens=[
            {"numero": 1, "nome": "RG", "entregas": [{"id": "e1"}]},
            # Enviado direto a um item e ainda em leitura: já entra pelo item.
            {"numero": 2, "nome": "CPF", "entregas": [{"id": "e3", "status_proc": "processando"}]},
        ],
        triagem=[{"id": "e2"}],
    )

    destino = pasta / "pacote.zip"
    with (
        patch.object(casos, "montar_situacao", return_value=situacao),
        patch.object(
            casos.armazenamento,
            "obter_entrega",
            side_effect=lambda eid: {"id": eid, "arquivo": arquivos[eid][0]},
        ),
        patch.object(
            casos.armazenamento,
            "caminho_duravel_da_entrega",
            side_effect=lambda eid: caminhos[eid],
        ),
    ):
        resumo = casos.montar_zip("caso-1", destino)

    assert resumo is not None
    assert resumo["arquivos"] == 3
    assert resumo["faltando"] == []
    with zipfile.ZipFile(destino) as pacote:
        # Número dinâmico (último do checklist + 1), não um "99" fixo: uma
        # categoria com mais de 99 itens colidiria com um item real.
        assert sorted(pacote.namelist()) == [
            "01 - RG - rg.pdf",
            "02 - CPF - lendo.pdf",
            "03 - Outros documentos identificados - solto.pdf",
        ]
        assert pacote.read("03 - Outros documentos identificados - solto.pdf") == b"nao identificado"


def test_zip_sem_triagem_continua_igual() -> None:
    """Caso sem arquivo por identificar — inclusive resposta sem a chave
    `triagem` — não muda de comportamento."""
    pasta = Path(tempfile.mkdtemp(prefix="zip-triagem-"))
    arquivo = pasta / "rg.pdf"
    arquivo.write_bytes(b"rg")
    situacao = _situacao(
        itens=[{"numero": 1, "nome": "RG", "entregas": [{"id": "e1"}]}], triagem=[]
    )
    del situacao["triagem"]

    destino = pasta / "pacote.zip"
    with (
        patch.object(casos, "montar_situacao", return_value=situacao),
        patch.object(
            casos.armazenamento, "obter_entrega", return_value={"id": "e1", "arquivo": "rg.pdf"}
        ),
        patch.object(casos.armazenamento, "caminho_duravel_da_entrega", return_value=arquivo),
    ):
        resumo = casos.montar_zip("caso-1", destino)

    assert resumo is not None and resumo["arquivos"] == 1
