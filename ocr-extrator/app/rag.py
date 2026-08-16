"""Recuperação vetorial e sugestões estratégicas fundadas em precedentes reais."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from collections import Counter
from statistics import median
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
        linhas = conexao.execute(sql, (embedding, embedding, limite * 24)).fetchall()
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
    def qualidade(trecho: TrechoSimilar) -> float:
        tipo = str(trecho.metadados.get("tipo_documento") or "").casefold()
        origem = str(trecho.metadados.get("origem") or "").casefold()
        ajuste = 0.0
        if any(nome in tipo for nome in ("sentença", "sentenca", "acórdão", "acordao", "decisão", "decisao")):
            ajuste += 0.025
        if any(nome in tipo for nome in ("notificação", "notificacao", "distribuição", "distribuicao", "pauta", "edital")):
            ajuste -= 0.035
        if "despacho" in tipo:
            ajuste -= 0.02
        if origem in {"trt8_juris", "tst"}:
            ajuste += 0.01
        return trecho.similaridade + ajuste

    # Um processo pode render muitos chunks e expedientes. Mantém seu melhor
    # trecho, priorizando conteúdo decisório sobre notificação ou despacho.
    por_processo: dict[str, TrechoSimilar] = {}
    for trecho in candidatos:
        numero = str(trecho.metadados.get("numero_processo") or trecho.identificador or "")
        anterior = por_processo.get(numero)
        if anterior is None or qualidade(trecho) > qualidade(anterior):
            por_processo[numero] = trecho
    ordenados = sorted(por_processo.values(), key=qualidade, reverse=True)
    if not ordenados:
        return []

    # Evita contaminar a amostra com o 30º "menos distante" quando ele já não é
    # comparável ao relato. O piso de seis mantém contexto mínimo para divergência.
    corte = max(0.35, ordenados[0].similaridade - 0.12)
    comparaveis = [trecho for trecho in ordenados if trecho.similaridade >= corte]
    if len(comparaveis) < min(6, limite):
        comparaveis = ordenados[: min(6, limite)]
    return comparaveis[:limite]


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
    merito_total = sum(resultados.get(r, 0) for r in ("PROCEDENTE", "PARCIAL", "IMPROCEDENTE"))
    merito_favoravel = sum(resultados.get(r, 0) for r in ("PROCEDENTE", "PARCIAL"))
    similaridades = [trecho.similaridade for trecho in similares]
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
        "desfechos_merito": {
            "processos": merito_total,
            "favoraveis": merito_favoravel,
            "percentual": round(merito_favoravel * 100 / merito_total, 1) if merito_total else 0,
            "criterio": "PROCEDENTE + PARCIAL, excluindo acordo, extinção e indefinido",
        },
        "similaridade_amostra": {
            "maxima": round(max(similaridades), 4) if similaridades else 0,
            "mediana": round(median(similaridades), 4) if similaridades else 0,
            "minima": round(min(similaridades), 4) if similaridades else 0,
        },
        "aviso": (
            "Estatística descritiva da amostra semanticamente semelhante; "
            "não mede causalidade nem probabilidade de êxito do novo caso."
        ),
    }


INSTRUCAO_ESTRATEGIA = """Você auxilia um advogado trabalhista brasileiro.
Use SOMENTE o relato e os trechos fornecidos. Compare fatos, prova, pedido e
fundamento; coincidência de palavras não basta. O resultado rotulado pertence ao
PROCESSO, não necessariamente ao trecho, então não atribua causalidade sem apoio
textual. Não invente fatos, artigos, valores, juiz ou conclusão.

Para cada ação ou risco: cite precedente existente; informe os fatos que tornam a
comparação aplicável; registre diferenças que podem afastá-la; classifique a força
como alta, média ou baixa. Um único precedente nunca tem força alta. Exponha
precedentes divergentes. Priorize perguntas, provas e providências concretas.
A decisão final é sempre do advogado.

Responda apenas JSON no formato:
{"resumo":"...","acoes":[{"acao":"...","porque":"...","aplicabilidade":"...","contrapontos":"...","forca":"alta|media|baixa","precedentes":["P1"]}],
"riscos":[{"risco":"...","aplicabilidade":"...","contrapontos":"...","forca":"alta|media|baixa","precedentes":["P2"]}],
"divergencias":[{"ponto":"...","precedentes_favoraveis":["P1"],"precedentes_contrarios":["P2"]}],
"lacunas":["..."],"perguntas_criticas":["..."],
"aviso":"Análise assistiva; requer revisão do advogado."}
"""


def _normalizar_resultado(resultado: dict[str, Any], validos: set[str]) -> dict[str, Any]:
    """Descarta referências inventadas e recomendações sem precedente verificável."""
    for chave in ("acoes", "riscos"):
        limpos = []
        for item in resultado.get(chave) or []:
            if not isinstance(item, dict):
                continue
            refs = [str(r) for r in (item.get("precedentes") or []) if str(r) in validos]
            if not refs:
                continue
            item["precedentes"] = refs
            forca = str(item.get("forca") or "baixa").casefold()
            item["forca"] = forca if forca in {"alta", "media", "média", "baixa"} else "baixa"
            if item["forca"] == "alta" and len(set(refs)) < 2:
                item["forca"] = "media"
            limpos.append(item)
        resultado[chave] = limpos[:6]
    divergencias = []
    for item in resultado.get("divergencias") or []:
        if not isinstance(item, dict):
            continue
        item["precedentes_favoraveis"] = [str(r) for r in item.get("precedentes_favoraveis", []) if str(r) in validos]
        item["precedentes_contrarios"] = [str(r) for r in item.get("precedentes_contrarios", []) if str(r) in validos]
        if item["precedentes_favoraveis"] or item["precedentes_contrarios"]:
            divergencias.append(item)
    resultado["divergencias"] = divergencias[:4]
    resultado["lacunas"] = [str(x).strip() for x in (resultado.get("lacunas") or []) if str(x).strip()][:8]
    resultado["perguntas_criticas"] = [str(x).strip() for x in (resultado.get("perguntas_criticas") or []) if str(x).strip()][:8]
    return resultado


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
    resultado = _normalizar_resultado(
        resultado, {f"P{i}" for i in range(1, len(contexto_modelo) + 1)}
    )
    resultado["precedentes"] = [
        {"indice": f"P{i}", **trecho.referencia()}
        for i, trecho in enumerate(contexto_modelo, 1)
    ]
    resultado["estatisticas"] = _estatisticas_amostra(similares)
    resultado["metodologia"] = (
        "Busca vetorial com corte relativo de similaridade, um trecho por processo "
        "e prioridade para sentenças/acórdãos do TRT8/TST/DJEN/DEJT; referências "
        "inexistentes são descartadas antes da resposta."
    )
    return resultado
