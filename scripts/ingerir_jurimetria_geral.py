"""Ingere as decisões coletadas via DataJud + DJEN (tribunais gerais) no
banco vetorial do Advocacia IA.

Diferença em relação a `scripts.ingerir_jurimetria`: aquele lê de um banco
de origem específico do TRT8 (`JURIMETRIA_DATABASE_URL`); este lê
diretamente do arquivo `decisoes_limpas.json` gerado pelo coletor de
jurimetria geral (DataJud + DJEN, múltiplos tribunais: STJ, TST, TJs,
TRFs, TRTs).

Por padrão insere SEM gerar embeddings (mais rápido, mais robusto contra
queda de rede) — o `scripts.vetorizar_pendentes` (já rodado todo dia pela
tarefa agendada AdvocaciaIA-SincronizarRAG) preenche os vetores depois,
automaticamente. Use --com-embeddings só se quiser gerar na hora.

Uso:
  .venv\\Scripts\\python.exe -m scripts.ingerir_jurimetria_geral
  .venv\\Scripts\\python.exe -m scripts.ingerir_jurimetria_geral --arquivo caminho\\decisoes_limpas.json
  .venv\\Scripts\\python.exe -m scripts.ingerir_jurimetria_geral --limite 50 --com-embeddings
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from app.rag import carregar_env, gerar_embeddings, vetor_literal

#: Mesmos parâmetros de scripts.ingerir_jurimetria, para manter os chunks
#: de todas as fontes de jurisprudência com granularidade comparável.
TAMANHO_CHUNK = 1800
SOBREPOSICAO_CHUNK = 250

#: Identifica esta fonte nos relatórios (scripts.estado_rag "por origem"),
#: distinguindo-a de trt8_juris/tst/djen/dejt já existentes.
ORIGEM = "datajud_djen"

DDL = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_fontes_tipo_identificador
    ON fontes (tipo, identificador) WHERE identificador IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_chunks_fonte_ordem
    ON knowledge_chunks (fonte_id, ordem);
"""


def dividir(texto: str, *, tamanho: int = TAMANHO_CHUNK, sobreposicao: int = SOBREPOSICAO_CHUNK) -> list[str]:
    """Idêntico ao de scripts.ingerir_jurimetria: corta em fronteira de
    frase/linha quando possível, nunca no meio de uma palavra."""
    texto = texto.strip()
    if not texto:
        return []
    pedacos: list[str] = []
    inicio = 0
    while inicio < len(texto):
        fim = min(inicio + tamanho, len(texto))
        if fim < len(texto):
            corte = max(
                texto.rfind("\n", inicio + tamanho // 2, fim),
                texto.rfind(". ", inicio + tamanho // 2, fim),
            )
            if corte > inicio:
                fim = corte + 1
        pedacos.append(texto[inicio:fim].strip())
        if fim >= len(texto):
            break
        inicio = fim - sobreposicao
    return [p for p in pedacos if len(p) >= 80]


@dataclass(frozen=True)
class Decisao:
    identificador: str
    numero_processo: str
    tribunal: str
    tipo_conteudo: str  # "inteiro_teor" ou "ementa_ou_dispositivo"
    data: str | None
    tipo_comunicacao: str | None
    texto: str


def carregar_decisoes(caminho: Path) -> list[Decisao]:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    decisoes = []
    for item in dados:
        texto = (item.get("texto") or "").strip()
        if len(texto) < 100:
            continue
        assinatura = hashlib.sha256(texto.encode()).hexdigest()[:16]
        identificador = f"{ORIGEM}:{item.get('numeroProcesso')}:{assinatura}"
        decisoes.append(
            Decisao(
                identificador=identificador,
                numero_processo=item.get("numeroProcesso") or "",
                tribunal=item.get("tribunal") or "",
                tipo_conteudo=item.get("tipo_conteudo") or "outro",
                data=item.get("dataDisponibilizacao"),
                tipo_comunicacao=item.get("tipoComunicacao"),
                texto=texto,
            )
        )
    return decisoes


def ingerir(
    *,
    arquivo: Path,
    limite: int | None = None,
    com_embeddings: bool = False,
) -> dict[str, int]:
    carregar_env()
    destino_url = os.environ["DATABASE_URL"]
    stats = {"decisoes": 0, "ignoradas": 0, "chunks": 0}

    decisoes = carregar_decisoes(arquivo)
    if limite is not None:
        decisoes = decisoes[:limite]

    with psycopg.connect(destino_url, connect_timeout=10) as destino:
        destino.execute(DDL)
        destino.commit()

        identificadores = {
            linha[0]
            for linha in destino.execute(
                "SELECT identificador FROM fontes WHERE tipo='jurisprudencia'"
            )
        }

        for decisao in decisoes:
            if decisao.identificador in identificadores:
                stats["ignoradas"] += 1
                continue

            chunks = dividir(decisao.texto)
            if not chunks:
                stats["ignoradas"] += 1
                continue

            vetores = gerar_embeddings(chunks) if com_embeddings else [None] * len(chunks)

            fonte_id = destino.execute(
                """INSERT INTO fontes(tipo,titulo,identificador,publicado_em)
                   VALUES ('jurisprudencia',%s,%s,%s::date) RETURNING id""",
                (
                    f"{decisao.tribunal} — processo {decisao.numero_processo}",
                    decisao.identificador,
                    decisao.data[:10] if decisao.data else None,
                ),
            ).fetchone()[0]

            metadados = {
                "numero_processo": decisao.numero_processo,
                "origem": ORIGEM,
                "tribunal": decisao.tribunal,
                "tipo_documento": decisao.tipo_conteudo,
                "tipo_comunicacao": decisao.tipo_comunicacao,
                "rotulo": None,  # não temos classificação de desfecho para esta fonte
                "data": decisao.data,
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

            identificadores.add(decisao.identificador)
            stats["decisoes"] += 1
            stats["chunks"] += len(chunks)
            print(f"\r{stats}", end="", flush=True)

    print()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arquivo",
        type=Path,
        default=Path("decisoes_limpas.json"),
        help="Caminho para o decisoes_limpas.json gerado pelo coletor de jurimetria geral.",
    )
    parser.add_argument("--limite", type=int)
    parser.add_argument(
        "--com-embeddings",
        action="store_true",
        help="Gera embeddings na hora (mais lento; por padrão fica para o vetorizar_pendentes).",
    )
    args = parser.parse_args()

    if not args.arquivo.is_file():
        raise SystemExit(f"Arquivo não encontrado: {args.arquivo}")

    resultado = ingerir(arquivo=args.arquivo, limite=args.limite, com_embeddings=args.com_embeddings)
    print(resultado)


if __name__ == "__main__":
    main()
