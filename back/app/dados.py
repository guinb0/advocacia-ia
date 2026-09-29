"""O que foi alimentado no acervo vetorial — para consultar e auditar.

PARA QUE EXISTE

A recomendação e a análise por precedentes dizem "destes N processos parecidos,
tantos foram favoráveis". Quem lê isso precisa poder perguntar: N processos de
onde? De que tribunal, de que vara, de quando? Sem essa tela a resposta era abrir
o Postgres na mão — então ninguém auditava, e a estatística virava um número em
que se acredita ou não.

O CAMINHO É PANORAMA -> LISTA -> DOCUMENTO

Três rotas, na ordem das perguntas que se faz de verdade: quanto tem e de onde →
quais são → o que exatamente foi indexado deste aqui. O último nível mostra os
TRECHOS como o buscador os vê, porque é o que a busca compara — auditar o
documento original não diria se ele foi bem fatiado.

CONTAGENS SAEM DO BANCO, NÃO DE AMOSTRA

Tudo é `COUNT`/`GROUP BY` no pgvector. Estimar em cima de amostra numa tela cuja
função é auditar seria contraditório.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from . import rag
from .auth import exigir_modulo

log = logging.getLogger("dados")

roteador = APIRouter(prefix="/api/dados", tags=["dados"])

# Quem audita o acervo e definido pela matriz relacional. O modulo `metricas`
# cobre o panorama e estes detalhamentos de dados.
PodeAuditar = Depends(exigir_modulo("metricas"))

TEMPO_S = 30


def _q(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        return rag._consultar_pgvector(sql, params, connect_timeout=TEMPO_S)
    except rag.ErroRAG as exc:
        raise HTTPException(
            503,
            "O acervo de precedentes não respondeu (ele fica atrás da VPN). "
            "Confira a conexão e tente de novo.",
        ) from exc


def _grupo(campo: str, limite: int = 30) -> list[dict[str, Any]]:
    """Contagem por um campo do metadado, do maior para o menor."""
    linhas = _q(
        f"""SELECT metadados->>'{campo}' AS nome, COUNT(*) AS trechos,
                   COUNT(DISTINCT fonte_id) AS documentos
              FROM knowledge_chunks
             WHERE metadados->>'{campo}' IS NOT NULL
             GROUP BY 1 ORDER BY 2 DESC LIMIT {int(limite)}"""
    )
    return [
        {"nome": l["nome"], "trechos": l["trechos"], "documentos": l["documentos"]}
        for l in linhas
    ]


@roteador.get("", dependencies=[PodeAuditar])
def panorama() -> dict[str, Any]:
    """Quanto há no acervo, e de onde veio."""
    totais = _q(
        """SELECT (SELECT COUNT(*) FROM fontes) AS fontes,
                  (SELECT COUNT(*) FROM knowledge_chunks) AS trechos,
                  (SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NOT NULL)
                    AS vetorizados"""
    )[0]
    periodo = _q(
        """SELECT MIN(metadados->>'data') AS mais_antigo,
                  MAX(metadados->>'data') AS mais_recente
             FROM knowledge_chunks WHERE metadados->>'data' IS NOT NULL"""
    )[0]
    por_tipo = _q(
        "SELECT tipo AS nome, COUNT(*) AS documentos FROM fontes GROUP BY 1 ORDER BY 2 DESC"
    )
    return {
        "fontes": totais["fontes"],
        "trechos": totais["trechos"],
        # Trecho sem embedding não é achável pela busca. Mostrar o número separado
        # é o que revela ingestão que parou no meio.
        "vetorizados": totais["vetorizados"],
        "sem_vetor": totais["trechos"] - totais["vetorizados"],
        "periodo": {"de": periodo["mais_antigo"], "ate": periodo["mais_recente"]},
        "por_tipo_de_fonte": por_tipo,
        "por_origem": _grupo("origem"),
        "por_tribunal": _grupo("orgao_julgador", 40),
        "por_resultado": _grupo("rotulo"),
        "por_tipo_documento": _grupo("tipo_documento", 15),
        "por_classe": _grupo("classe", 15),
    }


@roteador.get("/documentos", dependencies=[PodeAuditar])
def documentos(
    origem: str = Query("", max_length=80),
    tribunal: str = Query("", max_length=200),
    busca: str = Query("", max_length=200),
    limite: int = Query(60, ge=1, le=300),
) -> dict[str, Any]:
    """Os documentos indexados, filtráveis pelo que a tela mostra no panorama."""
    onde = ["1=1"]
    params: list[Any] = []
    if origem:
        onde.append("k.metadados->>'origem' = %s")
        params.append(origem)
    if tribunal:
        onde.append("k.metadados->>'orgao_julgador' = %s")
        params.append(tribunal)
    if busca:
        onde.append("(f.titulo ILIKE %s OR f.identificador ILIKE %s)")
        params += [f"%{busca}%", f"%{busca}%"]

    linhas = _q(
        f"""SELECT f.id, f.tipo, f.titulo, f.identificador, f.url, f.publicado_em,
                   COUNT(k.id) AS trechos,
                   MIN(k.metadados->>'orgao_julgador') AS tribunal,
                   MIN(k.metadados->>'rotulo') AS resultado,
                   MIN(k.metadados->>'origem') AS origem,
                   MIN(k.metadados->>'numero_processo') AS processo
              FROM fontes f JOIN knowledge_chunks k ON k.fonte_id = f.id
             WHERE {' AND '.join(onde)}
             GROUP BY f.id, f.tipo, f.titulo, f.identificador, f.url, f.publicado_em
             ORDER BY f.publicado_em DESC NULLS LAST
             LIMIT {int(limite)}""",
        tuple(params),
    )
    return {"itens": linhas, "total": len(linhas), "limite": limite}


@roteador.get("/documentos/{fonte_id}", dependencies=[PodeAuditar])
def documento(fonte_id: str) -> dict[str, Any]:
    """Os TRECHOS de um documento, na ordem — é o que a busca compara.

    Auditar aqui, e não o arquivo original, é o ponto: se a fatia ficou grande
    demais, cortou no meio de uma frase ou entrou sem embedding, é isto que a
    recomendação está usando, e é isto que precisa estar à vista.
    """
    cabeca = _q("SELECT id, tipo, titulo, identificador, url, publicado_em FROM fontes WHERE id = %s", (fonte_id,))
    if not cabeca:
        raise HTTPException(404, "Documento não encontrado no acervo.")
    trechos = _q(
        """SELECT ordem, texto, metadados, (embedding IS NOT NULL) AS vetorizado
             FROM knowledge_chunks WHERE fonte_id = %s ORDER BY ordem""",
        (fonte_id,),
    )
    return {
        "fonte": cabeca[0],
        "trechos": [
            {
                "ordem": t["ordem"],
                "texto": t["texto"],
                "caracteres": len(str(t["texto"] or "")),
                "vetorizado": bool(t["vetorizado"]),
                "metadados": t["metadados"],
            }
            for t in trechos
        ],
        "total_trechos": len(trechos),
    }


# ---------------------------------------------------------------- prazos
#
# POR QUE ISTO É TÃO MAGRO
#
# O pedido era "tempo médio de cada etapa". O acervo não sustenta: medir etapa
# exige dois eventos datados do MESMO processo, e de 1.745 processos só 352 (20%)
# têm mais de uma data. Pior, o viés não é neutro — processo com vários
# documentos registrados é justamente o que recorreu, ou seja, o mais longo. A
# média sairia inflada, e o atendente diria ao cliente um prazo maior que o real.
#
# Então aqui vai só o que se sustenta: a taxa de recurso, e o intervalo entre o
# primeiro e o último evento, SEMPRE com o tamanho da amostra ao lado. Ver
# `docs/PRAZOS.md` para o que falta ingerir e transformar isto em medição de
# etapa de verdade.

#: Sinais de que o processo subiu. `tst`/`dejt` são tribunais superiores; acórdão
#: e decisão monocrática são peça de segunda instância.
_SEGUNDA = ("%ACORD%", "%MONOCR%")


@roteador.get("/prazos", dependencies=[PodeAuditar])
def prazos() -> dict[str, Any]:
    """Taxa de recurso e duração observada — com a amostra à vista."""
    r = _q(
        """SELECT COUNT(DISTINCT metadados->>%s) AS total,
                  COUNT(DISTINCT CASE WHEN metadados->>%s IN (%s,%s)
                        OR upper(metadados->>%s) LIKE %s
                        OR upper(metadados->>%s) LIKE %s
                        THEN metadados->>%s END) AS segunda
             FROM knowledge_chunks WHERE metadados->>%s IS NOT NULL""",
        (
            "numero_processo", "origem", "tst", "dejt",
            "tipo_documento", _SEGUNDA[0], "tipo_documento", _SEGUNDA[1],
            "numero_processo", "numero_processo",
        ),
    )[0]

    # Duração só de quem TEM dois eventos. O `n` vai junto para a tela poder
    # dizer sobre quantos processos a mediana fala — sem isso vira "o processo
    # demora X", que é exatamente a afirmação que o dado não autoriza.
    dur = _q(
        """SELECT COUNT(*) AS n,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY dias) AS mediana,
                  percentile_cont(0.9) WITHIN GROUP (ORDER BY dias) AS p90
             FROM (SELECT metadados->>%s AS p,
                          EXTRACT(EPOCH FROM (MAX((metadados->>%s)::timestamptz)
                                            - MIN((metadados->>%s)::timestamptz)))/86400 AS dias
                     FROM knowledge_chunks
                    WHERE metadados->>%s IS NOT NULL AND metadados->>%s IS NOT NULL
                    GROUP BY 1 HAVING COUNT(DISTINCT metadados->>%s) > 1) x""",
        ("numero_processo", "data", "data", "data", "numero_processo", "data"),
    )[0]

    total = int(r["total"] or 0)
    segunda = int(r["segunda"] or 0)
    return {
        "processos": total,
        "segunda_instancia": segunda,
        "percentual_recurso": round(100 * segunda / total, 1) if total else 0.0,
        "duracao": {
            "processos_medidos": int(dur["n"] or 0),
            "mediana_dias": round(float(dur["mediana"]), 0) if dur["mediana"] else None,
            "p90_dias": round(float(dur["p90"]), 0) if dur["p90"] else None,
        },
        "aviso": (
            "Duração observada entre o primeiro e o último documento registrado, "
            "e não tempo de etapa. Só processos com mais de um evento entram na "
            "conta — e esses tendem a ser os que recorreram, ou seja, os mais "
            "longos. Serve de referência, não de prazo prometido ao cliente."
        ),
    }
