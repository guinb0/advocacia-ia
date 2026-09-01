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


def classificar(
    extracao: dict[str, Any], categoria: str = "",
    pendencias: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Usa o texto integral do OCR para identificar o documento via DeepSeek."""
    analise = valor_documento.ler(extracao, pendencias or [], categoria)
    tipo = str(analise.get("documento") or "indefinido").strip()
    return {**analise, "classificador": "deepseek", "tipo_semantico": tipo}


def aplicar_interpretacao(extracao: dict[str, Any], semantica: dict[str, Any]) -> dict[str, Any]:
    """Preenche tipo e achados da DeepSeek sem substituir campos validados."""
    tipo = extracao.setdefault("tipo", {})
    codigo = str(semantica.get("codigo_documento") or "nao_estruturado")
    descricao = str(semantica.get("tipo_semantico") or "Documento não identificado")
    tipo["descricao_detectado"] = descricao
    # Uma identificação determinística já reconhecida não é rebaixada por uma
    # opinião do modelo. A DeepSeek resolve justamente o caso antes desconhecido.
    if codigo != "nao_estruturado" and tipo.get("detectado") in (None, "", "desconhecido"):
        tipo["detectado"] = codigo

    campos = list(extracao.get("campos") or [])
    existentes = {
        re.sub(r"[^a-z0-9]+", "_", str(c.get("nome") or "").lower()).strip("_")
        for c in campos if isinstance(c, dict)
    }
    for achado in semantica.get("achados") or []:
        if not isinstance(achado, dict):
            continue
        rotulo = re.sub(r"\s+", " ", str(achado.get("campo") or "")).strip()[:60]
        valor = re.sub(r"\s+", " ", str(achado.get("valor") or "")).strip()[:300]
        nome = re.sub(r"[^a-z0-9]+", "_", rotulo.lower()).strip("_")
        if not nome or not valor or nome in existentes:
            continue
        # CPF e nº da CNH só vêm do OCR da foto do documento correspondente —
        # achado semântico em laudo/comprovante não pode inventar esses campos.
        if nome in {"cpf", "cnh", "numero_cnh", "n_registro", "registro_cnh"}:
            continue
        campos.append({
            "nome": nome, "rotulo": rotulo, "valor": valor, "valor_bruto": valor,
            "confianca": 0.0, "valido": None,
            "observacao": "Interpretado pela DeepSeek a partir do texto integral; confira no documento.",
            "origem": "deepseek",
        })
        existentes.add(nome)
    extracao["campos"] = campos
    return extracao


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
