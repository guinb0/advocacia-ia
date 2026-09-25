"""Persistência idempotente de julgados cuja fonte original foi confirmada."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg

from . import rag
from .pesquisa_jurisprudencial import PrecedenteEstruturado, StatusVerificacao


def _hash(precedente: PrecedenteEstruturado, texto: str) -> str:
    base = {"tribunal": precedente.tribunal, "processo": precedente.numero_processo,
            "url": precedente.fonte_url, "ementa": precedente.ementa, "texto": texto}
    return hashlib.sha256(json.dumps(base, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _partes(texto: str, tamanho: int = 1800) -> list[str]:
    texto = " ".join(texto.split())
    return [texto[i:i + tamanho] for i in range(0, len(texto), tamanho) if texto[i:i + tamanho]]


def salvar(precedente: PrecedenteEstruturado, *, texto_original: str,
           organization_id: str = "", gerar_embedding: bool = False) -> int:
    """Promove somente precedente confirmado; reingestão atualiza o mesmo hash."""
    if not precedente.apto_para_citacao():
        raise ValueError("precedente não VERIFIED ou sem metadados/fonte obrigatórios")
    texto = texto_original.strip() or (precedente.ementa or "")
    if not texto:
        raise ValueError("texto original ou ementa é obrigatório")
    hash_conteudo = _hash(precedente, texto)
    chunks = _partes(texto)
    vetores = rag.gerar_embeddings(chunks) if gerar_embedding else [None] * len(chunks)
    with psycopg.connect(rag.url_pgvector(), connect_timeout=10) as banco:
        fonte_id = banco.execute(
            """INSERT INTO fontes(tipo,titulo,identificador,url,publicado_em,organization_id,hash_conteudo,status_verificacao,consultado_em)
               VALUES ('jurisprudencia',%s,%s,%s,%s,%s,%s,'VERIFIED',%s)
               ON CONFLICT (organization_id,hash_conteudo) WHERE hash_conteudo IS NOT NULL
               DO UPDATE SET titulo=EXCLUDED.titulo,url=EXCLUDED.url,publicado_em=EXCLUDED.publicado_em,status_verificacao='VERIFIED',consultado_em=EXCLUDED.consultado_em
               RETURNING id""",
            (f"{precedente.tribunal} — processo {precedente.numero_processo}", precedente.numero_processo,
             precedente.fonte_url, precedente.publicado_em, organization_id, hash_conteudo, precedente.consultado_em),
        ).fetchone()[0]
        banco.execute(
            """INSERT INTO precedentes_verificados(organization_id,fonte_id,tribunal,orgao_julgador,numero_processo,tema,subtema,relator,julgado_em,publicado_em,ementa,trecho_relevante,contexto_fatico,tese_aplicada,resultado,valor_pedido,valor_deferido,fonte_url,consultado_em,status_verificacao,hash_conteudo)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'VERIFIED',%s)
               ON CONFLICT (organization_id,hash_conteudo) DO UPDATE SET fonte_id=EXCLUDED.fonte_id,ementa=EXCLUDED.ementa,trecho_relevante=EXCLUDED.trecho_relevante,resultado=EXCLUDED.resultado,consultado_em=EXCLUDED.consultado_em,status_verificacao='VERIFIED'""",
            (organization_id, fonte_id, precedente.tribunal, precedente.orgao_julgador or "", precedente.numero_processo,
             precedente.tema or "", precedente.subtema or "", precedente.relator or "", precedente.julgado_em,
             precedente.publicado_em, precedente.ementa or "", texto[:1800], precedente.contexto_fatico or "",
             precedente.fundamentos or "", precedente.resultado or "", precedente.valor_pedido, precedente.valor_deferido,
             precedente.fonte_url, precedente.consultado_em, hash_conteudo),
        )
        banco.execute("DELETE FROM knowledge_chunks WHERE fonte_id=%s", (fonte_id,))
        metadados = json.dumps({"numero_processo": precedente.numero_processo, "tribunal": precedente.tribunal,
            "orgao_julgador": precedente.orgao_julgador, "relator": precedente.relator,
            "origem": "precedente_verificado", "tipo_documento": "acordao",
            "status_verificacao": StatusVerificacao.VERIFIED.value, "fonte_url": precedente.fonte_url,
            "classificacao": precedente.classificacao}, ensure_ascii=False)
        banco.cursor().executemany(
            "INSERT INTO knowledge_chunks(fonte_id,ordem,texto,metadados,embedding) VALUES (%s,%s,%s,%s::jsonb,%s::vector)",
            [(fonte_id, i, chunk, metadados, rag.vetor_literal(vetor) if vetor else None)
             for i, (chunk, vetor) in enumerate(zip(chunks, vetores, strict=True))],
        )
        banco.commit()
    return int(fonte_id)


def separar_para_redacao(achados: list[Any] | None) -> tuple[list[Any], list[Any]]:
    """Devolve (citáveis, revisão); o segundo grupo não pode ir ao gerador."""
    citaveis, revisao = [], []
    for achado in achados or []:
        status = str(achado.metadados.get("status_verificacao") or "UNVERIFIED").upper()
        (citaveis if status == StatusVerificacao.VERIFIED.value else revisao).append(achado)
    return citaveis, revisao
