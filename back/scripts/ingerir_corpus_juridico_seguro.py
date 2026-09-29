"""Carga resiliente do corpus jurídico: não mantém o banco aberto ao gerar vetores."""
from __future__ import annotations

import argparse
import json
import os

import psycopg

from app.rag import carregar_env
from scripts import ingerir_corpus_juridico as corpus


def persistir(item: dict, texto: str, *, com_embeddings: bool) -> int:
    """Calcula vetores antes da transação e reaproveita a persistência auditável."""
    documentos = corpus.dispositivos(item, texto)
    vetores = corpus.gerar_em_lotes([documento[3] for documento in documentos]) if com_embeddings else []
    gerador_original = corpus.gerar_em_lotes
    corpus.gerar_em_lotes = lambda _textos: vetores  # type: ignore[assignment]
    try:
        with psycopg.connect(os.environ["DATABASE_URL"]) as banco:
            return corpus.persistir(banco, item, texto, item["url"], com_embeddings)
    finally:
        corpus.gerar_em_lotes = gerador_original  # type: ignore[assignment]


def main() -> None:
    argumentos = argparse.ArgumentParser()
    argumentos.add_argument("--coletar", action="store_true")
    argumentos.add_argument("--com-embeddings", action="store_true")
    argumentos.add_argument("--limite", type=int)
    opcoes = argumentos.parse_args()
    carregar_env()
    for pasta in (corpus.RAW, corpus.PROCESSADOS, corpus.RELATORIOS, corpus.ERROS):
        pasta.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(os.environ["DATABASE_URL"]) as banco:
        corpus.aplicar_schema(banco)
    itens = json.loads(corpus.MANIFESTO.read_text(encoding="utf-8"))[:opcoes.limite]
    for item in itens:
        arquivo = corpus.RAW / f"{item['id']}.html"
        relatorio_arquivo = corpus.RELATORIOS / f"{item['id']}.json"
        # Retomada idempotente: uma fonte já concluída não consome novamente
        # créditos de embeddings nem substitui o material auditável.
        if opcoes.com_embeddings and relatorio_arquivo.exists():
            try:
                anterior = json.loads(relatorio_arquivo.read_text(encoding="utf-8"))
                if anterior.get("status") == "COMPLETE":
                    print(f"{item['id']}: já concluído", flush=True)
                    continue
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        try:
            if opcoes.coletar or not arquivo.exists():
                bruto, _ = corpus.baixar(item["url"])
                arquivo.write_bytes(bruto)
            html, codec = corpus.decodificar(arquivo.read_bytes())
            texto = corpus.extrair(html)
            (corpus.PROCESSADOS / f"{item['id']}.txt").write_text(texto, encoding="utf-8", newline="\n")
            quantidade = persistir(item, texto, com_embeddings=opcoes.com_embeddings)
            relatorio = {"documento": item["nome"], "status": "COMPLETE" if opcoes.com_embeddings else "VALIDATED_PENDING_EMBEDDINGS", "artigos": quantidade, "encoding": codec, "fonte": item["url"]}
            (corpus.RELATORIOS / f"{item['id']}.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{item['id']}: {quantidade} artigos validados", flush=True)
        except Exception as erro:
            relatorio = {"documento": item["nome"], "status": "SOURCE_REQUIRES_MANUAL_ACQUISITION", "fonte": item["url"], "erro": str(erro)}
            (corpus.ERROS / f"{item['id']}.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{item['id']}: falhou — {erro}", flush=True)


if __name__ == "__main__":
    main()
