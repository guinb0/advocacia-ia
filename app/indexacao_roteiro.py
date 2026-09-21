"""Índice vetorial dos roteiros de entrevista salvos no catálogo.

O roteiro continua sendo a fonte de verdade da revisão: ela recebe todas as
perguntas. Este índice persistente é complementar e permite recuperar, por
semelhança, a expectativa e a orientação ligadas a um tema da entrevista.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

import psycopg

from . import rag, roteiros


def _trechos(roteiro: roteiros.Roteiro) -> list[str]:
    """Um trecho por pergunta, sempre com o contexto da seção."""
    cabecalho = f"ROTEIRO: {roteiro.nome}\nDESCRIÇÃO: {roteiro.descricao}".strip()
    trechos: list[str] = []
    for bloco in roteiro.blocos:
        if bloco.delegado_a:
            continue
        contexto = "\n".join(
            parte
            for parte in (
                cabecalho,
                f"SEÇÃO: {bloco.titulo}",
                f"OBJETIVO: {bloco.objetivo}" if bloco.objetivo else "",
                f"ORIENTAÇÃO À ATENDENTE: {bloco.instrucao}" if bloco.instrucao else "",
            )
            if parte
        )
        for pergunta in bloco.perguntas:
            trechos.append(
                f"{contexto}\nPERGUNTA [{pergunta.id}]: {pergunta.texto}\n"
                "EXPECTATIVA DA REVISÃO: confirmar se este assunto foi tratado na entrevista."
            )
    return trechos


def indexar(roteiro: roteiros.Roteiro) -> dict[str, int]:
    """Substitui idempotentemente os vetores da versão atual do roteiro."""
    trechos = _trechos(roteiro)
    if not trechos:
        return {"chunks": 0}

    vetores = rag.gerar_embeddings(trechos, timeout=180)
    identificador = f"roteiro:{roteiro.codigo}"
    corpo = "\n\n".join(trechos)
    metadados: dict[str, Any] = {
        "origem": "roteiro_entrevista",
        "codigo_roteiro": roteiro.codigo,
        "nome_roteiro": roteiro.nome,
        "sha256": hashlib.sha256(corpo.encode("utf-8")).hexdigest(),
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
            banco.execute("UPDATE fontes SET titulo=%s WHERE id=%s", (roteiro.nome, fonte_id))
        else:
            fonte_id = banco.execute(
                "INSERT INTO fontes(tipo,titulo,identificador) VALUES ('interno',%s,%s) RETURNING id",
                (roteiro.nome, identificador),
            ).fetchone()[0]
        banco.executemany(
            """INSERT INTO knowledge_chunks(fonte_id,ordem,texto,metadados,embedding)
               VALUES (%s,%s,%s,%s::jsonb,%s::vector)""",
            [
                (fonte_id, indice, trecho, json.dumps(metadados, ensure_ascii=False), rag.vetor_literal(vetor))
                for indice, (trecho, vetor) in enumerate(zip(trechos, vetores, strict=True))
            ],
        )
    return {"chunks": len(trechos)}


def remover(codigo: str) -> None:
    """Remove vetores de roteiro excluído; `CASCADE` apaga seus trechos."""
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=15) as banco:
        banco.execute(
            "DELETE FROM fontes WHERE tipo='interno' AND identificador=%s",
            (f"roteiro:{codigo}",),
        )
