"""Copia anexos antigos ainda existentes para o armazenamento durável do SQL Server."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import armazenamento  # noqa: E402
from app.banco import conectar  # noqa: E402


def main() -> int:
    armazenamento.inicializar()
    with conectar() as con:
        linhas = con.execute(
            "SELECT id, caso_id, caminho FROM entregas WHERE conteudo IS NULL"
        ).fetchall()

    copiados = 0
    ausentes: list[str] = []
    for linha in linhas:
        original = Path(str(linha["caminho"]))
        canonico = armazenamento.DIR_ARQUIVOS / str(linha["caso_id"]) / original.name
        fonte = canonico if canonico.is_file() else original
        if not fonte.is_file():
            ausentes.append(str(linha["id"]))
            continue
        conteudo = fonte.read_bytes()
        with conectar() as con:
            con.execute(
                "UPDATE entregas SET conteudo = ?, conteudo_sha256 = ? WHERE id = ?",
                (conteudo, hashlib.sha256(conteudo).hexdigest(), linha["id"]),
            )
        copiados += 1

    print(f"{copiados} anexo(s) protegido(s) no banco; {len(ausentes)} ausente(s).")
    for entrega_id in ausentes:
        print(f"AUSENTE {entrega_id}")
    return 1 if ausentes else 0


if __name__ == "__main__":
    raise SystemExit(main())
