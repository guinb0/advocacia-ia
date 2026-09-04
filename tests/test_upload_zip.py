"""Enviar um ZIP: o sistema abre e trata cada arquivo de dentro como um envio.

Exercita `_expandir_zips`, que troca cada `.zip` pelos arquivos que contém, pulando
o lixo que todo desktop enfia no pacote (`__MACOSX`, `.DS_Store`) e sem abrir ZIP
dentro de ZIP. Nada aqui toca banco nem OCR.

    PYTHONPATH=. .venv/Scripts/python.exe tests/test_upload_zip.py
"""

from __future__ import annotations

import asyncio
import io
import zipfile

from fastapi import HTTPException

from app import main


def checar(condicao: bool, descricao: str) -> int:
    print(f"  {'PASS' if condicao else '>> FALHA'} {descricao}")
    return 0 if condicao else 1


def _zip(entradas: dict[str, bytes]) -> main._ArquivoEmMemoria:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, dados in entradas.items():
            z.writestr(nome, dados)
    return main._ArquivoEmMemoria("pacote.zip", buf.getvalue())


def _nomes(arquivos: list) -> list[str]:
    return [a.filename for a in arquivos]


def main_teste() -> int:
    falhas = 0

    # ZIP com dois documentos, uma subpasta e lixo de sistema.
    pacote = _zip(
        {
            "rg.jpg": b"\xff\xd8imagem",
            "documentos/contracheque.pdf": b"%PDF-1.4 teste",
            "__MACOSX/._rg.jpg": b"lixo",
            ".DS_Store": b"lixo",
            "dentro.zip": b"PK\x03\x04zipaninhado",
        }
    )
    saida = asyncio.run(main._expandir_zips([pacote]))
    nomes = _nomes(saida)
    falhas += checar("rg.jpg" in nomes, "arquivo solto do ZIP é extraído")
    falhas += checar(
        "documentos/contracheque.pdf" in nomes,
        "arquivo em subpasta mantém o caminho no nome",
    )
    falhas += checar(
        not any(n.startswith("__MACOSX") or n.endswith(".DS_Store") for n in nomes),
        "lixo de sistema é descartado",
    )
    falhas += checar(
        "dentro.zip" not in nomes and len(saida) == 2,
        "ZIP dentro de ZIP não é aberto",
    )

    # Conteúdo dos arquivos extraídos é o original.
    por_nome = {a.filename: asyncio.run(a.read()) for a in saida}
    falhas += checar(por_nome["rg.jpg"] == b"\xff\xd8imagem", "os bytes extraídos são os do ZIP")

    # Arquivo solto (não-zip) passa intacto pela expansão.
    solto = main._ArquivoEmMemoria("foto.png", b"png")
    passou = asyncio.run(main._expandir_zips([solto]))
    falhas += checar(_nomes(passou) == ["foto.png"], "arquivo que não é ZIP passa intacto")

    # Guarda de quantidade: ZIP com itens demais é recusado inteiro.
    grande = _zip({f"f{i:03d}.jpg": b"x" for i in range(main.MAX_ITENS_ZIP + 1)})
    try:
        asyncio.run(main._expandir_zips([grande]))
        falhas += checar(False, "ZIP acima do teto de itens deveria ser recusado")
    except HTTPException as exc:
        falhas += checar(exc.status_code == 400, "ZIP com itens demais recusado com 400")

    print("TODOS OS TESTES PASSARAM" if not falhas else f"{falhas} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
