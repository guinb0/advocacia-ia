"""Indexa o conteúdo textual de peças externas no acervo semântico.

Não importa fonte, margens, logotipo ou qualquer outro estilo visual. Cada arquivo
fica rastreável pela origem, para que possa ser removido ou reindexado depois.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import psycopg

from app import ambiente, rag
from app.indexacao_documento import _fragmentar

_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _normalizar(texto: str) -> str:
    return re.sub(r"[ \t]+", " ", texto).replace("\u00a0", " ").strip()


def extrair_docx(caminho: Path) -> str:
    """Extrai apenas os parágrafos do corpo do DOCX, sem elementos de estilo."""
    with zipfile.ZipFile(caminho) as arquivo:
        documento = arquivo.read("word/document.xml")
    raiz = ElementTree.fromstring(documento)
    paragrafos: list[str] = []
    for paragrafo in raiz.findall(".//w:body/w:p", _NS):
        texto = "".join(no.text or "" for no in paragrafo.findall(".//w:t", _NS))
        texto = _normalizar(texto)
        if texto:
            paragrafos.append(texto)
    return "\n\n".join(paragrafos)


def extrair_texto(caminho: Path) -> str:
    if caminho.suffix.lower() == ".docx":
        return extrair_docx(caminho)
    return caminho.read_text(encoding="utf-8", errors="replace").strip()


def _origem_id(caminho: Path) -> str:
    chave = str(caminho.resolve()).lower().encode("utf-8")
    return f"arquivo-peca:{hashlib.sha256(chave).hexdigest()}"


def indexar_pasta(pasta: Path, categoria: str) -> None:
    arquivos = sorted(
        arquivo for arquivo in pasta.rglob("*")
        if arquivo.is_file() and arquivo.suffix.lower() in {".docx", ".txt"}
    )
    if not arquivos:
        raise SystemExit("Nenhum DOCX ou TXT encontrado na pasta informada.")

    ambiente.carregar()
    total_pecas = total_chunks = ignorados = 0
    with psycopg.connect(os.environ["DATABASE_URL"]) as banco:
        for indice, arquivo in enumerate(arquivos, start=1):
            try:
                corpo = extrair_texto(arquivo)
                if len(corpo) < 120:
                    ignorados += 1
                    print(f"[{indice}/{len(arquivos)}] ignorado (sem texto útil): {arquivo.name}", flush=True)
                    continue
                partes = _fragmentar(corpo)
                vetores = rag.gerar_embeddings(partes, timeout=180)
                if len(vetores) != len(partes):
                    raise RuntimeError("A API retornou quantidade de vetores diferente dos trechos.")
                origem_id = _origem_id(arquivo)
                digest = hashlib.sha256(corpo.encode("utf-8")).hexdigest()
                metadados = json.dumps({
                    "origem": "pasta_pecas",
                    "caminho_original": str(arquivo.resolve()),
                    "extensao": arquivo.suffix.lower(),
                }, ensure_ascii=False)
                registro = banco.execute(
                    """INSERT INTO pecas_conteudo
                       (origem_id, nome_arquivo, tipo_peca, categoria, texto_integral, hash_conteudo, metadados)
                       VALUES (%s, %s, 'PECA_JURIDICA', %s, %s, %s, %s::jsonb)
                       ON CONFLICT (origem_id) DO UPDATE SET
                         nome_arquivo = EXCLUDED.nome_arquivo,
                         categoria = EXCLUDED.categoria,
                         texto_integral = EXCLUDED.texto_integral,
                         hash_conteudo = EXCLUDED.hash_conteudo,
                         metadados = EXCLUDED.metadados,
                         atualizado_em = now()
                       RETURNING id""",
                    (origem_id, arquivo.name, categoria, corpo, digest, metadados),
                ).fetchone()[0]
                banco.execute("DELETE FROM pecas_conteudo_chunks WHERE peca_id = %s", (registro,))
                with banco.cursor() as cursor:
                    cursor.executemany(
                        """INSERT INTO pecas_conteudo_chunks (peca_id, ordem, texto, metadados, embedding)
                           VALUES (%s, %s, %s, %s::jsonb, %s::vector)""",
                        [
                            (registro, ordem, trecho, metadados, rag.vetor_literal(vetor))
                            for ordem, (trecho, vetor) in enumerate(zip(partes, vetores))
                        ],
                    )
                banco.commit()
                total_pecas += 1
                total_chunks += len(partes)
                print(f"[{indice}/{len(arquivos)}] {arquivo.name}: {len(partes)} trecho(s)", flush=True)
            except Exception as erro:
                banco.rollback()
                ignorados += 1
                print(f"[{indice}/{len(arquivos)}] falhou: {arquivo.name}: {erro}", flush=True)
    print(
        f"Concluído: {total_pecas} peça(s), {total_chunks} trecho(s), {ignorados} arquivo(s) não indexado(s).",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pasta", required=True, type=Path)
    parser.add_argument("--categoria", default="pecas_externas")
    args = parser.parse_args()
    if not args.pasta.is_dir():
        raise SystemExit(f"Pasta não encontrada: {args.pasta}")
    indexar_pasta(args.pasta, args.categoria)


if __name__ == "__main__":
    main()
