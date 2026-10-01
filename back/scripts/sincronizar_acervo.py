"""Sincroniza o Acervo Jurídico com as fontes oficiais.

Padrão é SIMULAÇÃO: lê o banco, baixa as normas, calcula o que mudaria e não grava nada.

De `back/`:

    python -m scripts.sincronizar_acervo                        # simula todas as normas
    python -m scripts.sincronizar_acervo --documento clt-1943   # simula uma
    python -m scripts.sincronizar_acervo --executar             # grava (exige a migration 011)
    python -m scripts.sincronizar_acervo --executar --sem-embeddings
    python -m scripts.sincronizar_acervo --executar --importar-jurisprudencia caminho/tst.json
    python -m scripts.sincronizar_acervo --local tmp/acervo.json --executar   # sem pgvector: grava num JSON

Conexão: a mesma do RAG (`JURISPRUDENCE_DATABASE_URL`, `PGVECTOR_*` ou `DATABASE_URL`).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.acervo import armazenamento, jurisprudencia, sincronizacao  # noqa: E402
from app.acervo.armazenamento import MigracaoNaoAplicada  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--executar", action="store_true", help="grava no banco (sem isto, só simula)")
    ap.add_argument("--documento", action="append", help="id do manifesto (repita para mais de um)")
    ap.add_argument("--sem-embeddings", action="store_true", help="grava texto e versões; trechos ficam pendentes de vetor")
    ap.add_argument("--reindexar", action="store_true", help="refaz o embedding de todos os artigos das normas escolhidas")
    ap.add_argument("--importar-jurisprudencia", type=Path, help="arquivo JSON de súmulas/OJs (ver app/acervo/jurisprudencia.py)")
    ap.add_argument("--local", type=Path, help="armazena num JSON local em vez do pgvector (desenvolvimento)")
    ap.add_argument("--html", type=Path, help="pasta com <document_id>.html já baixados (não acessa a internet)")
    a = ap.parse_args()

    store = armazenamento.Memoria(a.local) if a.local else armazenamento.Postgres()
    simular = not a.executar
    baixar = sincronizacao.baixar_http
    if a.html:
        pasta = a.html
        def baixar(url: str) -> sincronizacao.Resposta:  # noqa: E306
            item = next(i for i in sincronizacao.manifesto() if i["url"] == url)
            return sincronizacao.Resposta((pasta / f"{item['id']}.html").read_bytes(), "text/html")
    gerar = None if a.sem_embeddings or not sincronizacao.embeddings_configurados() else sincronizacao.gerar_embeddings_padrao
    if a.executar and gerar is None and not a.sem_embeddings:
        print("Aviso: EMBEDDINGS_* não configurado; os trechos alterados ficarão pendentes de vetor.")

    try:
        if a.importar_jurisprudencia:
            if simular:
                linhas = jurisprudencia.carregar_arquivo(a.importar_jurisprudencia)
                validos = invalidos = 0
                for i, l in enumerate(linhas):
                    try:
                        jurisprudencia.normalizar(l)
                        validos += 1
                    except jurisprudencia.ItemInvalido as erro:
                        invalidos += 1
                        print(f"  item {i + 1}: {erro}")
                print(f"Simulação da importação: {validos} válidos, {invalidos} inválidos. Use --executar para gravar.")
            else:
                rel = jurisprudencia.importar(jurisprudencia.carregar_arquivo(a.importar_jurisprudencia), armazenamento=store,
                                              agora=datetime.now(UTC), origem=a.importar_jurisprudencia.name)
                print(json.dumps(rel, ensure_ascii=False, indent=2))
            if not a.documento:
                return 0
        if a.reindexar:
            relatorios = [sincronizacao.sincronizar_documento(dict(i), armazenamento=store, baixar=baixar, gerar_embeddings=gerar, origem="script",
                                                              simular=simular, forcar_reindexacao=True)
                          for i in sincronizacao.manifesto() if (not a.documento or i["id"] in a.documento) and i.get("categoria", "legislacao") == "legislacao"]
            resultado = {"documentos": relatorios}
        else:
            resultado = sincronizacao.sincronizar_tudo(armazenamento=store, baixar=baixar, gerar_embeddings=gerar, documentos=a.documento,
                                                       origem="script", simular=simular)
    except MigracaoNaoAplicada as erro:
        print(f"ERRO: {erro}. Aplique back/sql/011_acervo_juridico.sql no PostgreSQL do RAG e rode de novo.")
        return 2

    print(f"{'SIMULAÇÃO — nada foi gravado' if simular else 'GRAVADO'}\n")
    for r in resultado["documentos"]:
        if r.get("status") == "ERRO":
            print(f"[ERRO] {r['document_id']}: {r.get('erro')}")
            continue
        print(f"[{r['status']}] {r['document_id']}: {r['dispositivos_total']} dispositivos | novos {r['dispositivos_novos']} | "
              f"alterados {r['dispositivos_alterados']} | revogados {r['dispositivos_revogados']} | removidos {r['dispositivos_removidos']} | "
              f"legado associado {r['legado_associado']} / reprocessado {r['legado_reprocessado']} / encerrado {r['legado_encerrado']} | "
              f"embeddings gerados {r['embeddings_gerados']} mantidos {r['embeddings_mantidos']} invalidados {r['embeddings_invalidados']} "
              f"pendentes {r['embeddings_pendentes']} | ~{r.get('tokens_embeddings_aprox', 0)} tokens | {r.get('duracao_ms', '—')} ms")
    if resultado.get("jurisprudencia"):
        print("\nJurisprudência:", json.dumps(resultado["jurisprudencia"], ensure_ascii=False))
    if "alertas_de_skill" in resultado:
        print(f"Alertas de skill novos: {resultado['alertas_de_skill']}")
    return 1 if any(r.get("status") == "ERRO" for r in resultado["documentos"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
