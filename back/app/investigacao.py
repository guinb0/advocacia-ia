"""Dossiê investigativo rastreável para casos trabalhistas.

Coleta apenas fontes públicas estruturadas. Cada achado é evidência a conferir,
nunca uma conclusão automática, e fica isolado por CNPJ/número de processo.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx
import psycopg
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from .rag import _consultar_pgvector, gerar_embeddings, vetor_literal
from scripts.ingerir_jurimetria import dividir, limpar_texto

roteador = APIRouter(prefix="/api/investigacao", tags=["investigacao"])
DATAJUD = "https://api-publica.datajud.cnj.jus.br"
DJEN = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
BRASIL_API = "https://brasilapi.com.br/api/cnpj/v1"
CNPJA_ABERTA = "https://open.cnpja.com/office"


def _digitos(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


class PedidoInvestigacao(BaseModel):
    cnpj: str | None = None
    numero_processo: str | None = None
    tribunal: str = Field("trt8", pattern=r"^(tst|trt(?:[1-9]|1[0-9]|2[0-4]))$")

    @field_validator("cnpj")
    @classmethod
    def cnpj_valido(cls, valor: str | None) -> str | None:
        if valor is None or not valor.strip():
            return None
        digitos = _digitos(valor)
        if len(digitos) != 14:
            raise ValueError("CNPJ deve conter 14 dígitos")
        return digitos

    @field_validator("numero_processo")
    @classmethod
    def processo_valido(cls, valor: str | None) -> str | None:
        if valor is None or not valor.strip():
            return None
        digitos = _digitos(valor)
        if len(digitos) != 20:
            raise ValueError("número CNJ deve conter 20 dígitos")
        return digitos


class PedidoAnalise(PedidoInvestigacao):
    relato: str = Field(min_length=20, max_length=12000)


class Evidencia(BaseModel):
    identificador: str
    categoria: str
    titulo: str
    texto: str
    url: str
    fonte: str
    confianca: str = "alta"
    metadados: dict[str, Any] = Field(default_factory=dict)


def _texto_json(dados: Any) -> str:
    def percorrer(valor: Any, prefixo: str = "") -> list[str]:
        linhas: list[str] = []
        if isinstance(valor, dict):
            for chave, item in valor.items():
                linhas.extend(percorrer(item, f"{prefixo}{chave}: "))
        elif isinstance(valor, list):
            for item in valor[:500]:
                linhas.extend(percorrer(item, prefixo))
        elif valor not in (None, "", [], {}):
            linhas.append(f"{prefixo}{valor}")
        return linhas
    return limpar_texto("\n".join(percorrer(dados)))


async def _get_publico(
    http: httpx.AsyncClient, url: str, *, params: dict[str, Any] | None = None
) -> httpx.Response:
    """Repete limites transitórios sem transformar 429 em falha de toda a coleta."""
    resposta: httpx.Response | None = None
    for tentativa in range(3):
        resposta = await http.get(url, params=params)
        if resposta.status_code != 429:
            return resposta
        if tentativa < 2:
            espera = min(float(resposta.headers.get("Retry-After", "2") or 2), 5)
            await asyncio.sleep(max(0.5, espera))
    assert resposta is not None
    return resposta


async def _coletar_cnpj(http: httpx.AsyncClient, cnpj: str) -> list[Evidencia]:
    resposta = await _get_publico(http, f"{BRASIL_API}/{cnpj}")
    fonte = "BrasilAPI/CNPJ"
    url = f"{BRASIL_API}/{cnpj}"
    formato_cnpja = False
    if resposta.status_code == 429:
        url = f"{CNPJA_ABERTA}/{cnpj}"
        resposta = await _get_publico(http, url)
        fonte = "CNPJÁ Aberta"
        formato_cnpja = True
    if resposta.status_code == 404:
        return []
    resposta.raise_for_status()
    dados = resposta.json()
    if formato_cnpja:
        campos = {chave: dados.get(chave) for chave in (
            "taxId", "alias", "founded", "status", "statusDate", "company",
            "address", "mainActivity", "sideActivities",
        )}
        razao = (dados.get("company") or {}).get("name")
    else:
        campos = {chave: dados.get(chave) for chave in (
            "cnpj", "razao_social", "nome_fantasia", "descricao_situacao_cadastral",
            "data_inicio_atividade", "cnae_fiscal_descricao", "descricao_tipo_de_logradouro",
            "logradouro", "numero", "complemento", "bairro", "municipio", "uf",
            "capital_social", "qsa", "cnaes_secundarios",
        )}
        razao = dados.get("razao_social")
    return [Evidencia(
        identificador=f"investigacao:cnpj:{cnpj}", categoria="cadastro_empresa",
        titulo=f"Cadastro CNPJ — {razao or cnpj}",
        texto=_texto_json(campos), url=url, fonte=fonte,
        confianca="media", metadados={"cnpj": cnpj, "origem_primaria": "Receita Federal"},
    )]


async def _coletar_datajud(
    http: httpx.AsyncClient, numero: str, tribunal: str
) -> list[Evidencia]:
    chave = os.getenv("DATAJUD_API_KEY", "").strip()
    if not chave:
        return []
    resposta = await http.post(
        f"{DATAJUD}/api_publica_{tribunal}/_search",
        headers={"Authorization": chave if chave.startswith("APIKey ") else f"APIKey {chave}"},
        json={"size": 20, "query": {"match": {"numeroProcesso": numero}}},
    )
    resposta.raise_for_status()
    hits = resposta.json().get("hits", {}).get("hits", [])
    evidencias: list[Evidencia] = []
    for indice, hit in enumerate(hits):
        dados = hit.get("_source", {})
        evidencias.append(Evidencia(
            identificador=f"investigacao:datajud:{tribunal}:{numero}:{indice}",
            categoria="metadados_processuais", titulo=f"DataJud {tribunal.upper()} — {numero}",
            texto=_texto_json(dados),
            url=f"{DATAJUD}/api_publica_{tribunal}/_search", fonte="CNJ/DataJud",
            metadados={"numero_processo": numero, "tribunal": tribunal},
        ))
    return evidencias


async def _coletar_djen(http: httpx.AsyncClient, numero: str, tribunal: str) -> list[Evidencia]:
    resposta = await _get_publico(
        http,
        DJEN,
        params={"numeroProcesso": numero, "siglaTribunal": tribunal.upper(),
                "pagina": 1, "itensPorPagina": 100},
    )
    resposta.raise_for_status()
    corpo = resposta.json()
    itens = corpo.get("items") or corpo.get("data") or corpo.get("comunicacoes") or []
    if isinstance(itens, dict):
        itens = itens.get("items") or itens.get("data") or []
    evidencias: list[Evidencia] = []
    for indice, item in enumerate(itens if isinstance(itens, list) else []):
        token = item.get("id") or item.get("hash") or indice
        evidencias.append(Evidencia(
            identificador=f"investigacao:djen:{tribunal}:{numero}:{token}",
            categoria="publicacao_processual", titulo=f"Publicação DJEN — {numero}",
            texto=_texto_json(item), url=str(item.get("link") or DJEN), fonte="CNJ/Comunica PJe",
            metadados={"numero_processo": numero, "tribunal": tribunal,
                       "data_disponibilizacao": item.get("data_disponibilizacao")},
        ))
    return evidencias


def _conectar() -> psycopg.Connection:
    ultimo: Exception | None = None
    for tentativa in range(4):
        try:
            return psycopg.connect(
                os.environ["DATABASE_URL"], connect_timeout=10, keepalives=1,
                keepalives_idle=15, keepalives_interval=5, keepalives_count=3,
                tcp_user_timeout=30_000,
            )
        except psycopg.OperationalError as exc:
            ultimo = exc
            if tentativa < 3:
                import time
                time.sleep(0.4 * (2 ** tentativa))
    assert ultimo is not None
    raise ultimo


def _gravar_evidencias(evidencias: list[Evidencia]) -> dict[str, int]:
    if not evidencias:
        return {"fontes": 0, "chunks": 0}
    total_chunks = 0
    for evidencia in evidencias:
        chunks = dividir(evidencia.texto, tamanho=1800, sobreposicao=240)
        if not chunks:
            continue
        vetores = gerar_embeddings(chunks, timeout=180)
        coletado_em = datetime.now(timezone.utc).isoformat()
        sha = hashlib.sha256(evidencia.texto.encode("utf-8")).hexdigest()
        metadados = {
            **evidencia.metadados, "origem": evidencia.fonte,
            "dominio": "investigacao_trabalhista", "categoria": evidencia.categoria,
            "confianca": evidencia.confianca, "coletado_em": coletado_em, "sha256": sha,
        }
        with _conectar() as banco:
            existente = banco.execute(
                "SELECT id FROM fontes WHERE tipo='outro' AND identificador=%s FOR UPDATE",
                (evidencia.identificador,),
            ).fetchone()
            if existente:
                fonte_id = existente[0]
                banco.execute("DELETE FROM knowledge_chunks WHERE fonte_id=%s", (fonte_id,))
                banco.execute(
                    "UPDATE fontes SET titulo=%s,url=%s WHERE id=%s",
                    (evidencia.titulo, evidencia.url, fonte_id),
                )
            else:
                fonte_id = banco.execute(
                    """INSERT INTO fontes(tipo,titulo,identificador,url)
                       VALUES ('outro',%s,%s,%s) RETURNING id""",
                    (evidencia.titulo, evidencia.identificador, evidencia.url),
                ).fetchone()[0]
            with banco.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO knowledge_chunks(fonte_id,ordem,texto,metadados,embedding)
                       VALUES (%s,%s,%s,%s::jsonb,%s::vector)""",
                    [(fonte_id, i, chunk, json.dumps(metadados, ensure_ascii=False),
                      vetor_literal(vetor)) for i, (chunk, vetor) in
                     enumerate(zip(chunks, vetores, strict=True))],
                )
        total_chunks += len(chunks)
    return {"fontes": len(evidencias), "chunks": total_chunks}


@roteador.post("/coletar")
async def coletar(pedido: PedidoInvestigacao) -> dict[str, Any]:
    if not pedido.cnpj and not pedido.numero_processo:
        raise HTTPException(422, "Informe ao menos um CNPJ ou número de processo.")
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as http:
            tarefas = []
            if pedido.cnpj:
                tarefas.append(_coletar_cnpj(http, pedido.cnpj))
            if pedido.numero_processo:
                tarefas.extend([
                    _coletar_datajud(http, pedido.numero_processo, pedido.tribunal),
                    _coletar_djen(http, pedido.numero_processo, pedido.tribunal),
                ])
            resultados = await asyncio.gather(*tarefas, return_exceptions=True)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Falha ao consultar as fontes públicas.") from exc
    evidencias: list[Evidencia] = []
    avisos: list[str] = []
    for resultado in resultados:
        if isinstance(resultado, Exception):
            avisos.append(f"{type(resultado).__name__}: fonte temporariamente indisponível")
        else:
            evidencias.extend(resultado)
    gravacao = await asyncio.to_thread(_gravar_evidencias, evidencias)
    return {**gravacao, "evidencias": [e.model_dump(exclude={"texto"}) for e in evidencias],
            "avisos": avisos}


@roteador.get("/buscar")
async def buscar(
    consulta: str = Query(min_length=3, max_length=2000),
    cnpj: str | None = None,
    numero_processo: str | None = None,
    limite: int = Query(10, ge=1, le=30),
) -> dict[str, Any]:
    cnpj_digitos = _digitos(cnpj) or None
    processo_digitos = _digitos(numero_processo) or None
    if not cnpj_digitos and not processo_digitos:
        raise HTTPException(422, "Filtre por CNPJ ou número de processo.")
    filtros = ["k.metadados->>'dominio'='investigacao_trabalhista'"]
    params_filtro: list[Any] = []
    if cnpj_digitos:
        filtros.append("k.metadados->>'cnpj'=%s")
        params_filtro.append(cnpj_digitos)
    if processo_digitos:
        filtros.append("k.metadados->>'numero_processo'=%s")
        params_filtro.append(processo_digitos)
    try:
        embedding = vetor_literal(
            (await asyncio.to_thread(gerar_embeddings, [consulta], timeout=35))[0]
        )
        params: list[Any] = [embedding, *params_filtro, embedding, limite]
        sql = f"""SELECT k.texto,1-(k.embedding <=> %s::vector) similaridade,
                         k.metadados,f.titulo,f.url
                    FROM knowledge_chunks k JOIN fontes f ON f.id=k.fonte_id
                   WHERE {' AND '.join(filtros)} AND k.embedding IS NOT NULL
                   ORDER BY k.embedding <=> %s::vector LIMIT %s"""
    except (httpx.HTTPError, TimeoutError):
        # Rede do modelo fora: busca lexical mantém a ferramenta utilizável e
        # continua respeitando rigorosamente o isolamento por alvo.
        termos = " ".join(re.findall(r"[\wÀ-ÿ]{4,}", consulta)[:12])
        params = [termos, *params_filtro, termos, limite]
        sql = f"""SELECT k.texto,similarity(k.texto,%s) similaridade,
                         k.metadados,f.titulo,f.url
                    FROM knowledge_chunks k JOIN fontes f ON f.id=k.fonte_id
                   WHERE {' AND '.join(filtros)}
                   ORDER BY similarity(k.texto,%s) DESC LIMIT %s"""
    itens = await asyncio.to_thread(
        _consultar_pgvector, sql, tuple(params), connect_timeout=10
    )
    for item in itens:
        item["similaridade"] = round(float(item["similaridade"]), 4)
    return {"consulta": consulta, "resultados": itens,
            "aviso": "Indícios para conferência; não constituem prova ou previsão de resultado."}


INSTRUCAO_ANALISE = """Você auxilia um advogado trabalhista a investigar fatos.
Use SOMENTE o relato e as evidências numeradas. Não invente fato, causalidade,
ilicitude ou conteúdo ausente. Cada insight e cada contradição deve citar pelo
menos uma evidência existente. Diferencie fato observado, inferência e pergunta.
Não estime probabilidade de vitória. Responda apenas JSON:
{"resumo":"...","insights":[{"achado":"...","tipo":"fato|inferencia",
"impacto":"...","confianca":"alta|media|baixa","evidencias":["E1"],
"como_verificar":"..."}],"contradicoes":[{"ponto":"...","evidencias":["E1"],
"pergunta":"..."}],"provas_a_buscar":["..."],"perguntas_entrevista":["..."],
"alertas":["..."]} """


def _analisar_com_modelo(relato: str, itens: list[dict[str, Any]]) -> dict[str, Any]:
    contexto = "\n\n".join(
        f"[E{i}] fonte={item['titulo']} url={item['url']} "
        f"confianca={item['metadados'].get('confianca')}\n{item['texto'][:3500]}"
        for i, item in enumerate(itens, 1)
    )
    resposta = httpx.post(
        os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}"},
        json={"model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"), "temperature": 0,
              "response_format": {"type": "json_object"}, "messages": [
                  {"role": "system", "content": INSTRUCAO_ANALISE},
                  {"role": "user", "content": f"RELATO:\n{relato}\n\nEVIDÊNCIAS:\n{contexto}"},
              ]}, timeout=120,
    )
    resposta.raise_for_status()
    resultado = json.loads(resposta.json()["choices"][0]["message"]["content"])
    validas = {f"E{i}" for i in range(1, len(itens) + 1)}
    for chave in ("insights", "contradicoes"):
        resultado[chave] = [
            {**item, "evidencias": [ref for ref in item.get("evidencias", []) if ref in validas]}
            for item in resultado.get(chave, []) if isinstance(item, dict)
            and any(ref in validas for ref in item.get("evidencias", []))
        ][:8]
    resultado["fontes"] = [
        {"indice": f"E{i}", "titulo": item["titulo"], "url": item["url"],
         "similaridade": item["similaridade"], "metadados": item["metadados"]}
        for i, item in enumerate(itens, 1)
    ]
    resultado["aviso"] = "Análise assistiva de indícios públicos; exige conferência e prova admissível."
    return resultado


@roteador.post("/analisar")
async def analisar(pedido: PedidoAnalise) -> dict[str, Any]:
    consulta = f"{pedido.relato}\ncontradições fatos jornada grupo econômico prova"
    recuperados = await buscar(
        consulta=consulta, cnpj=pedido.cnpj,
        numero_processo=pedido.numero_processo, limite=12,
    )
    itens = recuperados["resultados"]
    if not itens:
        raise HTTPException(404, "Colete as fontes deste alvo antes de analisar.")
    try:
        return await asyncio.to_thread(_analisar_com_modelo, pedido.relato, itens)
    except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(502, "Não foi possível gerar a análise fundamentada.") from exc
