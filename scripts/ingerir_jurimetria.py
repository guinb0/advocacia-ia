"""Vetoriza decisões/publicações da jurimetria TRT8 no banco do agente.

Uso:
  .venv\Scripts\python.exe -m scripts.ingerir_jurimetria
  .venv\Scripts\python.exe -m scripts.ingerir_jurimetria --limite 20
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.rag import BASE, carregar_env, gerar_embeddings, vetor_literal

RE_CPF = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
RE_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
RE_ESPACO = re.compile(r"[ \t\r\f\v]+")


class _TextoHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.partes: list[str] = []

    def handle_data(self, data: str) -> None:
        self.partes.append(data)


def limpar_texto(valor: str) -> str:
    parser = _TextoHTML()
    parser.feed(html.unescape(valor))
    texto = " ".join(parser.partes) if parser.partes else valor
    texto = RE_CPF.sub("[CPF REDIGIDO]", texto)
    texto = RE_EMAIL.sub("[EMAIL REDIGIDO]", texto)
    linhas = [RE_ESPACO.sub(" ", linha).strip() for linha in texto.splitlines()]
    return "\n".join(linha for linha in linhas if linha).strip()


def _strings_longas(valor: Any) -> Iterator[str]:
    if isinstance(valor, str) and len(valor) >= 100:
        yield valor
    elif isinstance(valor, dict):
        for item in valor.values():
            yield from _strings_longas(item)
    elif isinstance(valor, list):
        for item in valor:
            yield from _strings_longas(item)


def texto_do_payload(payload: Any) -> str:
    partes: list[str] = []
    vistos: set[str] = set()
    for valor in _strings_longas(payload):
        texto = limpar_texto(valor)
        assinatura = hashlib.sha256(texto.encode()).hexdigest()
        if len(texto) >= 100 and assinatura not in vistos:
            partes.append(texto)
            vistos.add(assinatura)
    return "\n\n".join(partes)


def magistrados_do_payload(payload: Any) -> list[str]:
    nomes: set[str] = set()
    if isinstance(payload, dict):
        for chave, valor in payload.items():
            if chave.lower() in {"magistrado", "magistrados", "relator"}:
                valores = valor if isinstance(valor, list) else [valor]
                nomes.update(str(item).strip() for item in valores if str(item).strip())
            nomes.update(magistrados_do_payload(valor))
    elif isinstance(payload, list):
        for item in payload:
            nomes.update(magistrados_do_payload(item))
    return sorted(nomes)


def dividir(texto: str, *, tamanho: int = 1800, sobreposicao: int = 250) -> list[str]:
    if tamanho <= sobreposicao:
        raise ValueError("tamanho deve ser maior que a sobreposição")
    texto = texto.strip()
    if not texto:
        return []
    pedacos: list[str] = []
    inicio = 0
    while inicio < len(texto):
        fim = min(inicio + tamanho, len(texto))
        if fim < len(texto):
            corte = max(texto.rfind("\n", inicio + tamanho // 2, fim), texto.rfind(". ", inicio + tamanho // 2, fim))
            if corte > inicio:
                fim = corte + 1
        pedacos.append(texto[inicio:fim].strip())
        if fim >= len(texto):
            break
        inicio = fim - sobreposicao
    return [p for p in pedacos if len(p) >= 80]


@dataclass(frozen=True)
class Documento:
    identificador: str
    numero: str
    origem: str
    tipo: str | None
    rotulo: str
    data: str | None
    orgao: str | None
    relator: str | None
    magistrados: list[str]
    classe: str | None
    assuntos: list[str]
    texto: str


CONSULTAS = {
    "trt8_juris": """
        SELECT d.sha256 AS chave, d.numero_processo, d.tipo_documento,
               d.payload_detalhe AS conteudo, NULL::text AS texto,
               p.rotulo::text, p.orgao_julgador_nome, p.relator, p.classe_nome,
               p.assuntos_nome, p.data_ajuizamento::text AS data
          FROM documento_raw d JOIN processo p USING (numero_processo)
         ORDER BY d.numero_processo, d.id
    """,
    "djen": """
        SELECT d.sha256 AS chave, d.numero_processo, d.tipo_documento,
               d.payload AS conteudo, d.payload->>'texto' AS texto,
               p.rotulo::text, p.orgao_julgador_nome, p.relator, p.classe_nome,
               p.assuntos_nome, d.data_disponibilizacao::text AS data
          FROM comunicacao_raw d JOIN processo p USING (numero_processo)
         ORDER BY d.numero_processo, d.id
    """,
    "dejt": """
        SELECT d.sha256 AS chave, d.numero_processo, 'PUBLICACAO' AS tipo_documento,
               NULL::jsonb AS conteudo, d.texto_pagina AS texto,
               p.rotulo::text, p.orgao_julgador_nome, p.relator, p.classe_nome,
               p.assuntos_nome, d.data_disponibilizacao::text AS data
          FROM publicacao_dejt_raw d JOIN processo p USING (numero_processo)
         ORDER BY d.numero_processo, d.id
    """,
    "tst": """
        SELECT d.sha256 AS chave, d.numero_processo, d.tipo_documento,
               d.payload AS conteudo, d.inteiro_teor_html AS texto,
               p.rotulo::text, p.orgao_julgador_nome, p.relator, p.classe_nome,
               p.assuntos_nome, d.data_publicacao::text AS data
          FROM documento_tst_raw d JOIN processo p USING (numero_processo)
         ORDER BY d.numero_processo, d.id
    """,
}


def documentos(
    conexao: psycopg.Connection[Any],
    limite: int | None,
    ignorar: set[str] | None = None,
) -> Iterator[Documento]:
    emitidos = 0
    for origem, sql in CONSULTAS.items():
        with conexao.cursor(name=f"ingestao_{origem}", row_factory=dict_row) as cursor:
            cursor.execute(sql)
            for linha in cursor:
                identificador = f"trt8:{origem}:{linha['chave']}"
                # Evita limpar/dividir JSONs e HTMLs grandes que já entraram em
                # execução anterior. Na retomada, o salto é quase imediato.
                if ignorar is not None and identificador in ignorar:
                    continue
                bruto = linha["texto"] or texto_do_payload(linha["conteudo"])
                texto = limpar_texto(bruto)
                if len(texto) < 100:
                    continue
                yield Documento(
                    identificador=identificador,
                    numero=linha["numero_processo"],
                    origem=origem,
                    tipo=linha["tipo_documento"],
                    rotulo=linha["rotulo"],
                    data=linha["data"],
                    orgao=linha["orgao_julgador_nome"],
                    relator=linha["relator"],
                    magistrados=magistrados_do_payload(linha["conteudo"]),
                    classe=linha["classe_nome"],
                    assuntos=list(linha["assuntos_nome"] or []),
                    texto=texto,
                )
                emitidos += 1
                if limite is not None and emitidos >= limite:
                    return


DDL = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_fontes_tipo_identificador
    ON fontes (tipo, identificador) WHERE identificador IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_chunks_fonte_ordem
    ON knowledge_chunks (fonte_id, ordem);
"""


def ingerir(*, limite: int | None = None, sem_embeddings: bool = False) -> dict[str, int]:
    carregar_env()
    origem_url = os.getenv("JURIMETRIA_DATABASE_URL", "postgresql://juri:juri@localhost:5433/juri")
    destino_url = os.environ["DATABASE_URL"]
    stats = {"documentos": 0, "ignorados": 0, "chunks": 0}
    with psycopg.connect(origem_url, connect_timeout=10) as origem, psycopg.connect(
        destino_url, connect_timeout=10
    ) as destino:
        destino.execute(DDL)
        destino.commit()
        identificadores = {
            linha[0]
            for linha in destino.execute(
                "SELECT identificador FROM fontes WHERE tipo='jurisprudencia'"
            )
        }
        for doc in documentos(origem, limite, identificadores):
            if doc.identificador in identificadores:
                stats["ignorados"] += 1
                continue
            chunks = dividir(doc.texto)
            if not chunks:
                stats["ignorados"] += 1
                continue
            vetores = [None] * len(chunks) if sem_embeddings else gerar_embeddings(chunks)
            fonte_id = destino.execute(
                """INSERT INTO fontes(tipo,titulo,identificador,publicado_em)
                   VALUES ('jurisprudencia',%s,%s,%s::date) RETURNING id""",
                (f"{doc.origem.upper()} — processo {doc.numero}", doc.identificador, doc.data[:10] if doc.data else None),
            ).fetchone()[0]
            metadados = {
                "numero_processo": doc.numero,
                "origem": doc.origem,
                "tipo_documento": doc.tipo,
                "rotulo": doc.rotulo,
                "data": doc.data,
                "orgao_julgador": doc.orgao,
                "relator": doc.relator,
                "magistrados": doc.magistrados,
                "classe": doc.classe,
                "assuntos": doc.assuntos,
            }
            parametros = [
                (
                    fonte_id,
                    ordem,
                    chunk,
                    json.dumps(metadados, ensure_ascii=False),
                    vetor_literal(vetor) if vetor else None,
                )
                for ordem, (chunk, vetor) in enumerate(zip(chunks, vetores, strict=True))
            ]
            with destino.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO knowledge_chunks(fonte_id,ordem,texto,metadados,embedding)
                       VALUES (%s,%s,%s,%s::jsonb,%s::vector)""",
                    parametros,
                )
            destino.commit()
            identificadores.add(doc.identificador)
            stats["documentos"] += 1
            stats["chunks"] += len(chunks)
            print(f"\r{stats}", end="", flush=True)
    print()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limite", type=int)
    parser.add_argument("--sem-embeddings", action="store_true")
    args = parser.parse_args()
    print(ingerir(limite=args.limite, sem_embeddings=args.sem_embeddings))


if __name__ == "__main__":
    main()
