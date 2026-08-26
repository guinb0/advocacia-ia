"""Classificação e indexação de documentos não estruturados do cliente."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import psycopg

from . import rag, valor_documento

log = logging.getLogger("indexacao-documento")


def classificar(extracao: dict[str, Any], categoria: str = "") -> dict[str, Any]:
    """Usa o texto integral do OCR para identificar o documento via DeepSeek."""
    analise = valor_documento.ler(extracao, [], categoria)
    tipo = str(analise.get("documento") or "indefinido").strip()
    return {**analise, "classificador": "deepseek", "tipo_semantico": tipo}


def _fragmentar(texto: str, tamanho: int = 1800, sobreposicao: int = 240) -> list[str]:
    texto = re.sub(r"[ \t]+", " ", texto).strip()
    if not texto:
        return []
    partes: list[str] = []
    inicio = 0
    while inicio < len(texto):
        fim = min(len(texto), inicio + tamanho)
        if fim < len(texto):
            quebra = texto.rfind("\n", inicio, fim)
            if quebra > inicio + tamanho // 2:
                fim = quebra
        partes.append(texto[inicio:fim].strip())
        if fim >= len(texto):
            break
        inicio = max(inicio + 1, fim - sobreposicao)
    return [parte for parte in partes if parte]


def indexar(entrega_id: str, caso_id: str, arquivo: str, extracao: dict[str, Any]) -> dict[str, int]:
    """Gera embeddings no OpenRouter e grava no PGVector de forma idempotente."""
    texto = str(extracao.get("texto_completo") or "").strip()
    chunks = _fragmentar(texto)
    if not chunks:
        return {"chunks": 0}
    vetores = rag.gerar_embeddings(chunks, timeout=180)
    semantica = extracao.get("classificacao_semantica") or {}
    tipo = str(semantica.get("tipo_semantico") or "documento não identificado")
    identificador = f"entrega:{entrega_id}"
    metadados = {
        "origem": "documento_cliente",
        "entrega_id": entrega_id,
        "caso_id": caso_id,
        "arquivo": arquivo,
        "tipo_documento": tipo,
        "sha256": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
        "indexado_em": datetime.now(timezone.utc).isoformat(),
    }
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=15) as banco:
        existente = banco.execute(
            "SELECT id FROM fontes WHERE tipo='interno' AND identificador=%s FOR UPDATE",
            (identificador,),
        ).fetchone()
        if existente:
            fonte_id = existente[0]
            banco.execute("DELETE FROM knowledge_chunks WHERE fonte_id=%s", (fonte_id,))
            banco.execute("UPDATE fontes SET titulo=%s WHERE id=%s", (arquivo, fonte_id))
        else:
            fonte_id = banco.execute(
                "INSERT INTO fontes(tipo,titulo,identificador) VALUES ('interno',%s,%s) RETURNING id",
                (arquivo, identificador),
            ).fetchone()[0]
        with banco.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO knowledge_chunks(fonte_id,ordem,texto,metadados,embedding)
                   VALUES (%s,%s,%s,%s::jsonb,%s::vector)""",
                [
                    (fonte_id, i, chunk, json.dumps(metadados, ensure_ascii=False), rag.vetor_literal(vetor))
                    for i, (chunk, vetor) in enumerate(zip(chunks, vetores, strict=True))
                ],
            )
    return {"chunks": len(chunks)}
