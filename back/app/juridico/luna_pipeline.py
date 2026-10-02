"""Pipeline cognitivo V2, sempre anterior ao PETITION_PLAN_FINALIZED.

As funções desta camada devolvem artefatos e telemetria; jamais mutam
``CaseState`` finalizado. O orquestrador escolhe, por feature flag, se usa a
descoberta em duas passagens ou o issue spotter anterior.
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable


def ativo() -> bool:
    return os.getenv("LUNA_PIPELINE_V2", "0").strip().lower() in {"1", "true", "sim", "on"}


def _tokens(texto: str) -> int:
    return max(0, len(texto) // 4)


def skill_context(textos_skill: dict[str, str], *, secoes: list[str] | None = None) -> tuple[str, dict[str, Any]]:
    """Seleciona a skill explicitamente e deixa truncamento auditável."""
    usar = secoes or sorted(textos_skill)
    partes = [(nome, str(textos_skill.get(nome) or "")) for nome in usar if textos_skill.get(nome)]
    texto = "\n\n".join(f"=== {nome} ===\n{valor}" for nome, valor in partes)
    limite = 30_000
    truncado = len(texto) > limite
    return texto[:limite], {
        "skill_id": "skill_do_escritorio", "skill_version": str(textos_skill.get("_version") or ""),
        "files_loaded": [n for n, _ in partes], "characters_loaded": min(len(texto), limite),
        "tokens_loaded": _tokens(texto[:limite]), "sections_used": usar,
        "SKILL_CONTEXT_TRUNCATED": truncado,
    }


def _chamar(stage: str, llm: Callable[[str, str], dict[str, Any]], instrucao: str, entrada: str) -> tuple[dict[str, Any], dict[str, Any]]:
    inicio = time.monotonic()
    saida = llm(instrucao, entrada)
    return (saida if isinstance(saida, dict) else {}), {
        "stage": stage, "input_tokens": _tokens(instrucao + entrada),
        "output_tokens": _tokens(str(saida)), "latency_ms": round((time.monotonic() - inicio) * 1000),
    }


def issue_spotting_duplo(llm: Callable[[str, str], dict[str, Any]], *, matriz: dict[str, Any], catalogo: list[dict[str, Any]],
                         textos_skill: dict[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Passes independentes: maximiza recall antes do filtro jurídico posterior."""
    fatos = [{k: f.get(k) for k in ("id", "fato", "estado", "fonte", "documento", "pagina")} for f in matriz.get("fatos") or []]
    catalogo_min = [{k: x.get(k) for k in ("id", "tema", "assunto", "descricao")} for x in catalogo]
    skill, meta_skill = skill_context(textos_skill, secoes=["SKILL.md", "regras_de_geracao.md", "validacoes.md"])
    base = {"facts": fatos, "catalog": catalogo_min, "skill": skill}
    contrato = ("Retorne JSON com facts_extraidos e teses. Para cada tese informe catalogo_id, tese, decisao "
                "(SUPPORTED|POTENTIAL_NEEDS_CONFIRMATION|REJECTED_NO_FACTUAL_BASIS), motivo, fatos_que_suportam, "
                "fatos_necessarios, prova, proposicoes, pedido, reflexos, exige_pericia, calculo. Não cite lei de memória.")
    a, ta = _chamar("LUNA_ISSUE_SPOTTER_PASS_A", llm, "Identifique todas as teses positivas com alto recall. " + contrato, str(base))
    b, tb = _chamar("LUNA_ISSUE_SPOTTER_PASS_B", llm, "Revise independentemente: o que outro advogado poderia ter esquecido? " + contrato, str(base))
    brutas = [x for resposta in (a, b) for x in resposta.get("teses") or [] if isinstance(x, dict)]
    unicas: dict[str, dict[str, Any]] = {}
    for item in brutas:
        chave = str(item.get("catalogo_id") or item.get("tese") or "").strip().casefold()
        if not chave:
            continue
        anterior = unicas.get(chave)
        # preferência determinística pelo item que tem fatos e decisão suportada.
        if anterior is None or (str(item.get("decisao")) == "SUPPORTED" and str(anterior.get("decisao")) != "SUPPORTED"):
            unicas[chave] = item
    return {"fatos_extraidos": [*a.get("fatos_extraidos", []), *b.get("fatos_extraidos", [])], "teses": list(unicas.values())}, [ta, tb], meta_skill


def contratos_de_capitulo(prep: dict[str, Any]) -> list[dict[str, Any]]:
    """Contratos mínimos para o escritor por capítulo; IDs, nunca texto livre."""
    pedidos = prep["plano_est"].get("pedidos") or []
    contratos = []
    for issue in prep["issues"].get("teses") or []:
        if issue.get("decisao") != "INCLUIR":
            continue
        iid = str(issue.get("id") or "")
        autoridades = [a.id for a in prep.get("autoridades_por_tese", {}).get(iid, [])]
        ligados = [str(p.get("request_id") or p.get("id")) for p in pedidos if str(p.get("issue_id") or "") == iid]
        contratos.append({"chapter_id": f"CH_{iid}", "issue_id": iid,
                          "allowed_fact_ids": list(issue.get("fatos_que_suportam") or []),
                          "allowed_authority_ids": autoridades, "allowed_evidence_ids": list(issue.get("prova") or []),
                          "linked_request_ids": ligados, "style_rules": ["fato→prova→regra→subsunção→consequência"], "max_length": 3000})
    return contratos


def plano_argumentativo(issue: dict[str, Any], contrato: dict[str, Any]) -> dict[str, Any]:
    return {"issue_id": contrato["issue_id"], "thesis": issue.get("tese"), "factual_premise": contrato["allowed_fact_ids"],
            "evidence": contrato["allowed_evidence_ids"], "authorities": contrato["allowed_authority_ids"],
            "counterarguments": list(issue.get("contrateses") or [])[:3], "linked_requests": contrato["linked_request_ids"]}


def prompt_capitulo(contrato: dict[str, Any], plano: dict[str, Any], *, resumo_global: str = "", resumo_anterior: str = "") -> str:
    """Contrato de redação: o escritor vê somente IDs e material autorizado."""
    return (
        "Você é LUNA_CHAPTER_WRITER. NAO_CRIAR_REQUESTS. Redija somente este capítulo. Não crie pedidos, fatos, datas, valores ou autoridades. "
        "Use a linguagem de certeza indicada pelas provas; perícia pendente deve ser redigida como pendência. "
        "Estrutura natural: fato concreto → prova → regra → subsunção → consequência. Evite doutrina abstrata.\n"
        f"RESUMO GLOBAL: {resumo_global[:1200]}\nRESUMO ANTERIOR: {resumo_anterior[:800]}\n"
        f"CHAPTER_CONTRACT: {contrato}\nARGUMENT_PLAN: {plano}\n"
        "Devolva JSON {'chapter_id': ..., 'content': ...}."
    )


def prompts_de_revisao(secoes: list[dict[str, Any]], case_state: dict[str, Any]) -> list[dict[str, str]]:
    """Revisores adversariais são read-only e devolvem findings estruturados."""
    resumo = str(secoes)[:35_000]
    contrato = str({k: case_state.get(k) for k in ("facts", "issues", "authorities", "requests", "calculations")})[:35_000]
    base = "NAO_ALTERE_DOCUMENTO. Devolva apenas JSON {'findings':[{'severity':'BLOCKING|WARNING','code':'','message':'','responsible_stage':''}]}. "
    return [
        {"stage": "LUNA_ADVERSARIAL_REVIEWER", "prompt": base + "Você representa a reclamada. Localize salto lógico, fato sem prova, citação inadequada, contradição e pedido sem conexão. Não altere texto.\n" + resumo + "\nSTATE:" + contrato},
        {"stage": "LUNA_AUTHOR_REVIEWER", "prompt": base + "Você é advogado do autor antes do protocolo. Localize tese/prova/pedido omitido e alternativas úteis; não crie fatos nem altere o documento.\n" + resumo + "\nSTATE:" + contrato},
        {"stage": "LUNA_REDUNDANCY_REVIEWER", "prompt": base + "Marque somente redundância argumentativa ou citação repetida; não altere o documento.\n" + resumo},
    ]
