"""Recuperação vetorial e sugestões estratégicas fundadas em precedentes reais."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

BASE = Path(__file__).resolve().parent.parent


def carregar_env() -> None:
    """Carrega apenas variáveis ausentes; o ambiente do processo sempre prevalece."""
    caminho = BASE / ".env"
    if not caminho.is_file():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


carregar_env()


class ErroRAG(RuntimeError):
    pass


def _obrigatoria(nome: str) -> str:
    valor = os.getenv(nome, "").strip()
    if not valor:
        raise ErroRAG(f"variável {nome} não configurada")
    return valor


def vetor_literal(vetor: list[float]) -> str:
    return "[" + ",".join(f"{valor:.9g}" for valor in vetor) + "]"


def gerar_embeddings(textos: list[str], *, timeout: float = 120) -> list[list[float]]:
    """`timeout` é parâmetro porque há dois usos com prazos opostos.

    A ingestão em lote pode esperar dois minutos — ninguém está olhando. Já a
    análise de uma resposta acontece com o cliente na frente, entre uma pergunta
    e a seguinte: lá, esperar mais que alguns segundos é pior que não analisar.
    """
    if not textos:
        return []
    dimensoes = int(os.getenv("EMBEDDINGS_DIMENSIONS", "1536"))
    resposta = httpx.post(
        _obrigatoria("EMBEDDINGS_BASE_URL").rstrip("/") + "/embeddings",
        headers={"Authorization": f"Bearer {_obrigatoria('EMBEDDINGS_API_KEY')}"},
        json={
            "model": _obrigatoria("EMBEDDINGS_MODEL_NAME"),
            "input": textos,
            "dimensions": dimensoes,
        },
        timeout=timeout,
    )
    resposta.raise_for_status()
    dados = sorted(resposta.json()["data"], key=lambda item: item["index"])
    vetores = [item["embedding"] for item in dados]
    if len(vetores) != len(textos) or any(len(v) != dimensoes for v in vetores):
        raise ErroRAG("serviço de embeddings devolveu quantidade ou dimensão inesperada")
    return vetores


@dataclass(frozen=True)
class TrechoSimilar:
    texto: str
    similaridade: float
    titulo: str
    identificador: str | None
    url: str | None
    metadados: dict[str, Any]

    def referencia(self) -> dict[str, Any]:
        return {
            "processo": self.metadados.get("numero_processo"),
            "resultado": self.metadados.get("rotulo"),
            "vara": self.metadados.get("orgao_julgador"),
            "relator": self.metadados.get("relator"),
            "magistrados": self.metadados.get("magistrados", []),
            "fonte": self.metadados.get("origem"),
            "tipo_documento": self.metadados.get("tipo_documento"),
            "titulo": self.titulo,
            "identificador": self.identificador,
            "url": self.url,
            "similaridade": round(self.similaridade, 4),
        }


def buscar_similares(
    consulta: str, *, limite: int = 8, timeout: float = 120, connect_timeout: int = 10
) -> list[TrechoSimilar]:
    """`timeout`/`connect_timeout` curtos para quem chama durante a entrevista.

    O servidor pgvector é remoto e compartilhado, e já ficou fora do ar (ver
    CONTEXTO.md). Com os prazos longos da ingestão, cada resposta analisada
    pagaria 10s parada antes de descobrir que o banco não responde — com o
    cliente esperando do outro lado da mesa.
    """
    if not consulta.strip():
        return []
    embedding = vetor_literal(gerar_embeddings([consulta[:12000]], timeout=timeout)[0])
    sql = """
        SELECT k.texto, 1 - (k.embedding <=> %s::vector) AS similaridade,
               f.titulo, f.identificador, f.url, k.metadados
          FROM knowledge_chunks k
          JOIN fontes f ON f.id = k.fonte_id
         WHERE k.embedding IS NOT NULL
           AND f.tipo = 'jurisprudencia'
         ORDER BY k.embedding <=> %s::vector
         LIMIT %s
    """
    with psycopg.connect(
        _obrigatoria("DATABASE_URL"), connect_timeout=connect_timeout, row_factory=dict_row
    ) as conexao:
        linhas = conexao.execute(sql, (embedding, embedding, limite * 12)).fetchall()
    candidatos = [
        TrechoSimilar(
            texto=linha["texto"],
            similaridade=float(linha["similaridade"]),
            titulo=linha["titulo"],
            identificador=linha["identificador"],
            url=linha["url"],
            metadados=linha["metadados"],
        )
        for linha in linhas
    ]
    # Um documento longo rende vários chunks. Para estratégia, diversidade de
    # processos vale mais que devolver oito pedaços da mesma sentença.
    escolhidos: list[TrechoSimilar] = []
    processos: set[str] = set()
    for trecho in candidatos:
        numero = str(trecho.metadados.get("numero_processo") or "")
        if numero and numero in processos:
            continue
        escolhidos.append(trecho)
        processos.add(numero)
        if len(escolhidos) >= limite:
            break
    return escolhidos


def _estatisticas_amostra(similares: list[TrechoSimilar]) -> dict[str, Any]:
    """Resume somente os processos recuperados, sem vender correlação como previsão."""
    resultados = Counter(
        str(t.metadados.get("rotulo"))
        for t in similares
        if t.metadados.get("rotulo")
    )
    varas = Counter(
        str(t.metadados.get("orgao_julgador"))
        for t in similares
        if t.metadados.get("orgao_julgador")
    )
    magistrados: Counter[str] = Counter()
    for trecho in similares:
        nomes = trecho.metadados.get("magistrados") or []
        if isinstance(nomes, str):
            nomes = [nomes]
        magistrados.update(str(nome) for nome in nomes if nome)
    total_resultados = sum(resultados.values())

    def itens(contagem: Counter[str], limite: int = 6) -> list[dict[str, Any]]:
        return [
            {
                "nome": nome,
                "quantidade": quantidade,
                "percentual": round(quantidade * 100 / sum(contagem.values()), 1),
            }
            for nome, quantidade in contagem.most_common(limite)
        ] if contagem else []

    favoraveis = sum(resultados.get(r, 0) for r in ("PROCEDENTE", "PARCIAL", "ACORDO"))
    return {
        "processos_analisados": len(similares),
        "resultados": itens(resultados),
        "varas": itens(varas),
        "magistrados": itens(magistrados),
        "desfechos_favoraveis_amplos": {
            "quantidade": favoraveis,
            "percentual": round(favoraveis * 100 / total_resultados, 1) if total_resultados else 0,
            "criterio": "PROCEDENTE + PARCIAL + ACORDO",
        },
        "aviso": (
            "Estatística descritiva da amostra semanticamente semelhante; "
            "não mede causalidade nem probabilidade de êxito do novo caso."
        ),
    }


INSTRUCAO_ESTRATEGIA = """Você auxilia um advogado trabalhista brasileiro.
Sugira ações de investigação e preparação do caso usando SOMENTE o relato e os
precedentes fornecidos. Não invente fatos, não prometa resultado e não trate
correlação como causalidade. Distinga: fatos a confirmar, documentos a obter,
teses a investigar, riscos e próximos atos. Cada sugestão deve citar pelo menos
um índice de precedente [P1], [P2] etc. Se os precedentes forem insuficientes,
diga isso. A decisão final é sempre do advogado.

Responda apenas JSON no formato:
{"resumo":"...","acoes":[{"acao":"...","porque":"...","precedentes":["P1"]}],
"riscos":[{"risco":"...","precedentes":["P2"]}],"lacunas":["..."],
"aviso":"Análise assistiva; requer revisão do advogado."}
"""


def sugerir_acoes(relato: str, *, limite: int = 8) -> dict[str, Any]:
    # Uma amostra maior sustenta os padrões descritivos. Apenas os precedentes
    # mais próximos entram no contexto do modelo para limitar custo e ruído.
    similares = buscar_similares(relato, limite=max(limite, 30))
    if not similares:
        raise ErroRAG("nenhum precedente vetorizado foi localizado")
    contexto_modelo = similares[:limite]
    contexto = []
    for indice, trecho in enumerate(contexto_modelo, 1):
        ref = trecho.referencia()
        contexto.append(
            f"[P{indice}] processo={ref['processo']} resultado={ref['resultado']} "
            f"fonte={ref['fonte']} tipo={ref['tipo_documento']} "
            f"similaridade={ref['similaridade']}\n{trecho.texto[:3500]}"
        )
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    resposta = httpx.post(
        base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {_obrigatoria('DEEPSEEK_API_KEY')}"},
        json={
            "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": INSTRUCAO_ESTRATEGIA},
                {
                    "role": "user",
                    "content": f"RELATO:\n{relato[:12000]}\n\nPRECEDENTES:\n" + "\n\n".join(contexto),
                },
            ],
        },
        timeout=120,
    )
    resposta.raise_for_status()
    resultado = json.loads(resposta.json()["choices"][0]["message"]["content"])
    resultado["precedentes"] = [
        {"indice": f"P{i}", **trecho.referencia()}
        for i, trecho in enumerate(contexto_modelo, 1)
    ]
    resultado["estatisticas"] = _estatisticas_amostra(similares)
    resultado["metodologia"] = (
        "Busca vetorial em documentos públicos do TRT8/TST/DJEN/DEJT; "
        "sugestões geradas apenas após recuperação de precedentes."
    )
    return resultado
