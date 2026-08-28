"""Fluxo de petição a partir da entrevista em TXT.

Passos lineares, sem pesquisa automática nem loop de recriação de caso:

1. Lê a transcrição da entrevista (arquivo TXT ou texto salvo).
2. Análise jurídica resumida (LLM).
3. Duas opções de estratégia (LLM).
4. Redação no agente com embeddings de **style** (Modelos de Petição) e de
   **documentos do caso** já sincronizados.

O estado intermediário fica em `dados/{caso_id}/peticao_fluxo.json`.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from .. import armazenamento
from . import espelho
from .cliente import Cliente, ErroDoAgente

log = logging.getLogger("agente")

__all__ = [
    "analisar_entrevista",
    "estado",
    "gerar_peticao",
    "propor_estrategias",
    "transcricao",
]

# Categoria do Acervo → código da taxonomia do agente (template + style).
_TAXONOMIA = {
    "acidente_trabalho_correios": "LABOR.OCCUPATIONAL_HEALTH.WORK_ACCIDENT.CORREIOS",
    "acidente_trabalho_geral": "LABOR.OCCUPATIONAL_HEALTH.WORK_ACCIDENT",
}


def _caminho_estado(caso_id: str) -> Path:
    return armazenamento.DIR_ARQUIVOS / caso_id / "peticao_fluxo.json"


def _carregar_estado(caso_id: str) -> dict[str, Any]:
    caminho = _caminho_estado(caso_id)
    if not caminho.exists():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _salvar_estado(caso_id: str, estado: dict[str, Any]) -> dict[str, Any]:
    caminho = _caminho_estado(caso_id)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    return estado


def transcricao(caso_id: str) -> dict[str, Any]:
    """Última entrevista com texto — fonte do fluxo."""
    entrevistas = armazenamento.listar_entrevistas(caso_id)
    com_texto = [e for e in entrevistas if (e.get("texto") or "").strip()]
    if not com_texto:
        raise ErroDoAgente("Nenhuma entrevista com transcrição encontrada para este caso.")
    ultima = sorted(com_texto, key=lambda e: e.get("criado_em") or "", reverse=True)[0]
    texto = str(ultima.get("texto") or "").strip()
    return {
        "entrevista_id": ultima["id"],
        "arquivo": ultima.get("arquivo"),
        "caracteres": len(texto),
        "previa": texto[:2000],
        "texto": texto,
    }


def estado(caso_id: str) -> dict[str, Any]:
    """Estado salvo + prévia da entrevista."""
    ent = None
    try:
        ent = transcricao(caso_id)
    except ErroDoAgente:
        pass
    salvo = _carregar_estado(caso_id)
    caso = armazenamento.obter_caso(caso_id) or {}
    return {
        "entrevista": ent,
        "analise": salvo.get("analise"),
        "estrategias": salvo.get("estrategias"),
        "escolha": salvo.get("escolha"),
        "categoria": caso.get("categoria"),
        "taxonomy_code": salvo.get("taxonomy_code")
        or _TAXONOMIA.get(str(caso.get("categoria") or ""), ""),
    }


def _llm_json(instrucao: str, entrada: str) -> dict[str, Any]:
    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not chave:
        raise ErroDoAgente("DEEPSEEK_API_KEY ausente — não é possível analisar a entrevista.")
    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    modelo = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    try:
        resposta = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {chave}"},
            json={
                "model": modelo,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": instrucao},
                    {"role": "user", "content": entrada[:120_000]},
                ],
            },
            timeout=90.0,
        )
        resposta.raise_for_status()
        bruto = resposta.json()["choices"][0]["message"]["content"]
        return json.loads(bruto)
    except (httpx.HTTPError, json.JSONDecodeError, KeyError) as erro:
        log.warning("petição fluxo: LLM falhou: %s", erro)
        raise ErroDoAgente("O modelo não respondeu à análise da entrevista.") from erro


def analisar_entrevista(caso_id: str) -> dict[str, Any]:
    """Análise jurídica resumida a partir do TXT da entrevista."""
    ent = transcricao(caso_id)
    caso = armazenamento.obter_caso(caso_id) or {}
    categoria = str(caso.get("categoria") or "")
    taxonomy = _TAXONOMIA.get(categoria, "")

    saida = _llm_json(
        """Você é advogado trabalhista. Leia a transcrição da entrevista e devolva JSON:
{
  "resumo": "análise jurídica em 3-6 frases, objetiva",
  "pontos_fortes": ["..."],
  "lacunas": ["documentos ou fatos que faltam"],
  "classificacao_sugerida": "código curto da matéria, ex: acidente_trabalho",
  "observacoes": "alertas ao advogado, se houver"
}
Não invente fatos que não estejam na transcrição. Relatos do cliente são alegações.""",
        f"Cliente: {caso.get('cliente', '')}\nCategoria OCR: {categoria}\n\n{ent['texto']}",
    )
    analise = {
        "resumo": str(saida.get("resumo") or "").strip(),
        "pontos_fortes": [str(x) for x in (saida.get("pontos_fortes") or []) if str(x).strip()],
        "lacunas": [str(x) for x in (saida.get("lacunas") or []) if str(x).strip()],
        "observacoes": str(saida.get("observacoes") or "").strip(),
    }
    salvo = _carregar_estado(caso_id)
    salvo.update(
        {
            "entrevista_id": ent["entrevista_id"],
            "analise": analise,
            "taxonomy_code": taxonomy,
        }
    )
    _salvar_estado(caso_id, salvo)
    return {"entrevista_id": ent["entrevista_id"], "analise": analise, "taxonomy_code": taxonomy}


def propor_estrategias(caso_id: str) -> dict[str, Any]:
    """Duas opções de estratégia para o advogado escolher."""
    salvo = _carregar_estado(caso_id)
    if not salvo.get("analise"):
        analisar_entrevista(caso_id)
        salvo = _carregar_estado(caso_id)
    ent = transcricao(caso_id)
    analise = salvo["analise"]
    caso = armazenamento.obter_caso(caso_id) or {}

    saida = _llm_json(
        """Proponha exatamente DUAS estratégias jurídicas distintas para o caso.
JSON:
{
  "opcoes": [
    {
      "titulo": "nome curto da opção",
      "tese": "tese em uma frase",
      "fundamentacao": "por que esta via, 2-4 frases",
      "pedidos": ["pedido 1", "pedido 2"],
      "riscos": ["risco 1"],
      "quando_usar": "em que situação esta opção é melhor"
    }
  ]
}
Devem ser caminhos diferentes (ex.: acidente vs. doença ocupacional), não variações de redação.""",
        (
            f"Cliente: {caso.get('cliente', '')}\n"
            f"Análise: {analise.get('resumo', '')}\n"
            f"Lacunas: {', '.join(analise.get('lacunas') or [])}\n\n"
            f"Transcrição:\n{ent['texto'][:80_000]}"
        ),
    )
    opcoes = saida.get("opcoes") or []
    if len(opcoes) < 2:
        raise ErroDoAgente("O modelo não devolveu duas estratégias — tente novamente.")
    opcoes = opcoes[:2]
    salvo["estrategias"] = opcoes
    _salvar_estado(caso_id, salvo)
    return {"estrategias": opcoes}


def gerar_peticao(caso_id: str, *, opcao: int = 0) -> dict[str, Any]:
    """Sincroniza documentos (embeddings) e enfileira redação com style + docs."""
    salvo = _carregar_estado(caso_id)
    if not salvo.get("estrategias"):
        propor_estrategias(caso_id)
        salvo = _carregar_estado(caso_id)
    opcoes = salvo.get("estrategias") or []
    if opcao < 0 or opcao >= len(opcoes):
        raise ErroDoAgente(f"Opção de estratégia inválida: {opcao}.")
    escolhida = opcoes[opcao]
    salvo["escolha"] = opcao
    _salvar_estado(caso_id, salvo)

    ent = transcricao(caso_id)
    caso = armazenamento.obter_caso(caso_id) or {}
    taxonomy = salvo.get("taxonomy_code") or _TAXONOMIA.get(str(caso.get("categoria") or ""), "")
    if not taxonomy:
        raise ErroDoAgente(
            "Categoria do caso sem mapeamento para taxonomia do agente — "
            "configure a categoria ou informe taxonomy_code."
        )

    # Documentos e entrevista sobem aqui; o worker do agente gera embeddings dos anexos.
    sync = espelho.sincronizar(caso_id)
    caso_ref = sync["caso_ref"]
    vinculo = armazenamento.obter_vinculo_agente(caso_id) or {}
    caso_ref = vinculo.get("caso_ref") or caso_ref

    analise = salvo.get("analise") or {}
    cliente = Cliente()
    resposta = cliente.gerar_peticao_entrevista(
        caso_ref,
        interview_id=ent["entrevista_id"],
        transcript=ent["texto"],
        analysis_summary=analise.get("resumo", ""),
        taxonomy_code=taxonomy,
        strategy_title=str(escolhida.get("titulo") or f"Opção {opcao + 1}"),
        strategy_thesis=str(escolhida.get("tese") or ""),
        strategy_claims=[str(p) for p in (escolhida.get("pedidos") or []) if str(p).strip()],
        strategy_risks=[str(r) for r in (escolhida.get("riscos") or []) if str(r).strip()],
    )
    resposta["caso_ref"] = caso_ref
    resposta["estrategia_escolhida"] = escolhida
    resposta["sincronizacao"] = {
        "documentos_enviados": sync.get("documentos_enviados"),
        "entrevistas_enviadas": sync.get("entrevistas_enviadas"),
    }
    return resposta
