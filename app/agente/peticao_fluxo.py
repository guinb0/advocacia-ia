"""Fluxo de petição — entrevista + documentos → estratégia → redação.

1. Sincroniza entrevista e anexos com o agente.
2. Cruza transcrição, fatos do agente e achados dos documentos (LLM).
3. Propõe duas estratégias com base no caso inteiro.
4. Redige com embeddings de Modelos de Petição e dos documentos do caso.

Estado em `dados/{caso_id}/peticao_fluxo.json`.
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
        "enviada": bool(ultima.get("enviada")),
    }


def _preparar_caso(caso_id: str) -> dict[str, Any]:
    """Sincroniza com o agente e monta o material de entrevista + documentos."""
    sync = espelho.sincronizar(caso_id)
    from . import dossie as dossie_mod

    dossie = dossie_mod.montar(caso_id, recuperar=False)
    achados: dict[str, Any] = {"achados": [], "documentos_lidos": 0}
    try:
        from .. import analise_documentos

        achados = analise_documentos.analisar(caso_id)
    except Exception as erro:
        log.warning("fluxo petição: análise de documentos indisponível: %s", erro)
        achados["aviso"] = str(erro)

    agente = (dossie or {}).get("agente") or {}
    checklist = (dossie or {}).get("checklist") or {}
    progresso = checklist.get("progresso") or {}
    return {
        "sync": sync,
        "dossie": dossie,
        "achados_documentos": achados,
        "resumo_preparacao": {
            "fatos_no_agente": len(agente.get("fatos") or []),
            "documentos_lidos": achados.get("documentos_lidos", 0),
            "achados_documentos": len(achados.get("achados") or []),
            "entrevistas_enviadas": sync.get("entrevistas_enviadas", 0),
            "documentos_enviados": sync.get("documentos_enviados", 0),
            "checklist_obrigatorios": progresso.get("obrigatorios_total"),
            "checklist_entregues": progresso.get("obrigatorios_entregues"),
        },
    }


def _valor_fato(fato: dict[str, Any]) -> str:
    valor = fato.get("value")
    if isinstance(valor, dict):
        partes = [str(v).strip() for v in valor.values() if v]
        return " · ".join(partes)
    return str(valor or "").strip()


def _contexto_unificado(caso_id: str, ent: dict[str, Any], preparo: dict[str, Any]) -> str:
    """Texto único para o LLM: entrevista + fatos + documentos + checklist."""
    caso = armazenamento.obter_caso(caso_id) or {}
    dossie = preparo.get("dossie") or {}
    agente = dossie.get("agente") or {}
    checklist = dossie.get("checklist") or {}
    progresso = checklist.get("progresso") or {}

    linhas = [
        f"CLIENTE: {caso.get('cliente', '')}",
        f"CATEGORIA: {checklist.get('categoria') or caso.get('categoria', '')}",
        "",
        "=== ENTREVISTA (transcrição — relato do cliente) ===",
        ent["texto"][:55_000],
    ]

    fatos = agente.get("fatos") or []
    if fatos:
        linhas.append("\n=== FATOS APURADOS NO AGENTE ===")
        for fato in fatos[:45]:
            tipo = str(fato.get("type") or "FATO")
            status = str(fato.get("status") or "")
            valor = _valor_fato(fato)
            if valor:
                linhas.append(f"- [{status}] {tipo}: {valor}")

    classificacoes = agente.get("classificacoes") or []
    if classificacoes:
        linhas.append("\n=== CLASSIFICAÇÃO JURÍDICA (agente) ===")
        for item in classificacoes[:5]:
            linhas.append(
                f"- {item.get('taxonomy_code', '')}: {item.get('rationale', '')[:300]}"
            )

    achados = preparo.get("achados_documentos", {}).get("achados") or []
    if achados:
        linhas.append("\n=== ACHADOS NOS DOCUMENTOS (além ou contra a entrevista) ===")
        for achado in achados[:12]:
            marca = "CONTRADIZ entrevista — " if achado.get("contradiz") else ""
            linhas.append(
                f"- {marca}{achado.get('informacao', '')} "
                f"({achado.get('documento', '')}): \"{str(achado.get('citacao', ''))[:220]}\""
            )

    pendencias = [p for p in agente.get("pendencias") or [] if p.get("status") == "OPEN"]
    if pendencias:
        linhas.append("\n=== PENDÊNCIAS DO PLAYBOOK ===")
        for item in pendencias[:15]:
            linhas.append(f"- [{item.get('severity', '')}] {item.get('description', '')}")

    contradicoes = agente.get("contradicoes") or []
    abertas = [c for c in contradicoes if str(c.get("status", "")).upper() != "RESOLVED"]
    if abertas:
        linhas.append("\n=== CONTRADIÇÕES EM ABERTO ===")
        for item in abertas[:8]:
            linhas.append(f"- {item.get('description', item.get('statement', ''))[:240]}")

    obrig = progresso.get("obrigatorios_total")
    entregues = progresso.get("obrigatorios_entregues")
    if obrig is not None:
        linhas.append(f"\n=== CHECKLIST ===\n{entregues}/{obrig} itens obrigatórios entregues")

    itens_pendentes = [
        str(i.get("rotulo") or i.get("nome") or i.get("codigo"))
        for i in checklist.get("itens") or []
        if i.get("obrigatorio") and i.get("status") != "entregue"
    ][:12]
    if itens_pendentes:
        linhas.append("Ainda faltam: " + ", ".join(itens_pendentes))

    return "\n".join(linhas)[:110_000]


def estado(caso_id: str) -> dict[str, Any]:
    """Estado salvo + prévia da entrevista e última preparação."""
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
        "preparacao": salvo.get("preparacao"),
        "categoria": caso.get("categoria"),
        "taxonomy_code": salvo.get("taxonomy_code")
        or _TAXONOMIA.get(str(caso.get("categoria") or ""), ""),
    }


def _llm_json(instrucao: str, entrada: str) -> dict[str, Any]:
    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not chave:
        raise ErroDoAgente("DEEPSEEK_API_KEY ausente — não é possível analisar o caso.")
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
            timeout=120.0,
        )
        resposta.raise_for_status()
        bruto = resposta.json()["choices"][0]["message"]["content"]
        return json.loads(bruto)
    except (httpx.HTTPError, json.JSONDecodeError, KeyError) as erro:
        log.warning("petição fluxo: LLM falhou: %s", erro)
        raise ErroDoAgente("O modelo não respondeu à análise do caso.") from erro


def analisar_entrevista(caso_id: str) -> dict[str, Any]:
    """Análise unificada: entrevista + fatos do agente + achados dos documentos."""
    ent = transcricao(caso_id)
    preparo = _preparar_caso(caso_id)
    contexto = _contexto_unificado(caso_id, ent, preparo)
    caso = armazenamento.obter_caso(caso_id) or {}
    categoria = str(caso.get("categoria") or "")
    taxonomy = _TAXONOMIA.get(categoria, "")

    achados_brutos = preparo.get("achados_documentos", {}).get("achados") or []
    achados_resumo = [
        {
            "informacao": str(a.get("informacao") or ""),
            "documento": str(a.get("documento") or ""),
            "citacao": str(a.get("citacao") or ""),
            "relevancia": str(a.get("relevancia") or ""),
            "contradiz": bool(a.get("contradiz")),
        }
        for a in achados_brutos[:12]
    ]

    saida = _llm_json(
        """Você é advogado trabalhista. Cruze a ENTREVISTA com os FATOS DOS DOCUMENTOS
e os ACHADOS listados. Devolva JSON:
{
  "resumo": "síntese jurídica em 4-8 frases",
  "cruzamento_entrevista_documentos": "o que a entrevista diz vs. o que os documentos confirmam ou contradizem",
  "pontos_fortes": ["pontos com prova ou relato consistente"],
  "lacunas": ["o que falta provar ou documentar"],
  "fatos_confirmados": ["fatos sustentados por documento"],
  "fatos_so_na_entrevista": ["alegações ainda sem prova documental"],
  "observacoes": "alertas ao advogado"
}
Não invente fatos. Diferencie alegação (entrevista) de fato documentado.""",
        contexto,
    )
    analise = {
        "resumo": str(saida.get("resumo") or "").strip(),
        "cruzamento_entrevista_documentos": str(
            saida.get("cruzamento_entrevista_documentos") or ""
        ).strip(),
        "pontos_fortes": [str(x) for x in (saida.get("pontos_fortes") or []) if str(x).strip()],
        "lacunas": [str(x) for x in (saida.get("lacunas") or []) if str(x).strip()],
        "fatos_confirmados": [
            str(x) for x in (saida.get("fatos_confirmados") or []) if str(x).strip()
        ],
        "fatos_so_na_entrevista": [
            str(x) for x in (saida.get("fatos_so_na_entrevista") or []) if str(x).strip()
        ],
        "achados_documentos": achados_resumo,
        "observacoes": str(saida.get("observacoes") or "").strip(),
    }
    salvo = _carregar_estado(caso_id)
    salvo.update(
        {
            "entrevista_id": ent["entrevista_id"],
            "analise": analise,
            "taxonomy_code": taxonomy,
            "preparacao": preparo.get("resumo_preparacao"),
            "contexto_llm": contexto[:80_000],
        }
    )
    _salvar_estado(caso_id, salvo)
    return {
        "entrevista_id": ent["entrevista_id"],
        "analise": analise,
        "taxonomy_code": taxonomy,
        "preparacao": preparo.get("resumo_preparacao"),
    }


def propor_estrategias(caso_id: str) -> dict[str, Any]:
    """Duas estratégias com base no caso inteiro (entrevista + documentos)."""
    salvo = _carregar_estado(caso_id)
    if not salvo.get("analise"):
        analisar_entrevista(caso_id)
        salvo = _carregar_estado(caso_id)
    ent = transcricao(caso_id)
    analise = salvo["analise"]
    contexto = salvo.get("contexto_llm")
    if not contexto:
        preparo = _preparar_caso(caso_id)
        contexto = _contexto_unificado(caso_id, ent, preparo)

    saida = _llm_json(
        """Proponha exatamente DUAS estratégias jurídicas DISTINTAS para este caso,
considerando entrevista, documentos e lacunas.
JSON:
{
  "opcoes": [
    {
      "titulo": "nome curto",
      "tese": "tese em uma frase",
      "fundamentacao": "por que esta via, citando prova documental quando houver",
      "pedidos": ["pedido 1", "pedido 2"],
      "riscos": ["risco 1"],
      "quando_usar": "quando escolher esta opção"
    }
  ]
}
Caminhos diferentes (ex.: acidente vs. doença ocupacional), não variações de redação.""",
        (
            f"ANÁLISE JÁ FEITA:\n{analise.get('resumo', '')}\n"
            f"Cruzamento: {analise.get('cruzamento_entrevista_documentos', '')}\n"
            f"Lacunas: {', '.join(analise.get('lacunas') or [])}\n"
            f"Confirmados: {', '.join(analise.get('fatos_confirmados') or [])}\n\n"
            f"MATERIAL DO CASO:\n{contexto[:85_000]}"
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
    """Enfileira redação com style + embeddings dos documentos."""
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

    vinculo = armazenamento.obter_vinculo_agente(caso_id) or {}
    caso_ref = vinculo.get("caso_ref")
    if not caso_ref:
        preparo = _preparar_caso(caso_id)
        caso_ref = preparo["sync"]["caso_ref"]
        resumo_sync = preparo.get("resumo_preparacao") or {}
    else:
        resumo_sync = {}

    analise = salvo.get("analise") or {}
    resumo_estrategia = (
        f"{analise.get('resumo', '')}\n"
        f"Cruzamento entrevista/documentos: {analise.get('cruzamento_entrevista_documentos', '')}"
    ).strip()

    cliente = Cliente()
    resposta = cliente.gerar_peticao_entrevista(
        caso_ref,
        interview_id=ent["entrevista_id"],
        transcript=ent["texto"],
        analysis_summary=resumo_estrategia[:8000],
        taxonomy_code=taxonomy,
        strategy_title=str(escolhida.get("titulo") or f"Opção {opcao + 1}"),
        strategy_thesis=str(escolhida.get("tese") or ""),
        strategy_claims=[str(p) for p in (escolhida.get("pedidos") or []) if str(p).strip()],
        strategy_risks=[str(r) for r in (escolhida.get("riscos") or []) if str(r).strip()],
    )
    resposta["caso_ref"] = caso_ref
    resposta["estrategia_escolhida"] = escolhida
    if resumo_sync:
        resposta["sincronizacao"] = resumo_sync
    if isinstance(resposta.get("requested_at"), str):
        pass
    elif resposta.get("requested_at"):
        resposta["requested_at"] = str(resposta["requested_at"])
    return resposta
