"""Pipeline V2: sete etapas, uma direção e uma fonte de verdade.

O arquivo é propositalmente linear. A leitura de ``run`` explica a geração:
documentos → fatos → issues → fundamento → plano → capítulos → revisão → render.
Nenhuma etapa posterior recebe permissão de alterar o ledger do plano.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from .. import armazenamento, peticao_local
from ..juridico import repositorio as repositorio_juridico
from .state import CaseStateV2, finalizar_plano


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _call(stage: str, prompt: str, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    started = datetime.now(timezone.utc)
    try:
        response = peticao_local._llm_json(prompt, str(payload), timeout=180.0, max_tokens=12_000)  # noqa: SLF001
        return response if isinstance(response, dict) else {}, {"stage": stage, "ok": True, "at": _now(), "input_chars": len(str(payload))}
    except Exception as exc:  # A minuta continua possível; a falha vira finding.
        return {}, {"stage": stage, "ok": False, "at": _now(), "error": str(exc)[:500], "latency_ms": round((datetime.now(timezone.utc) - started).total_seconds() * 1000)}


def ingestion_and_fact_matrix(caso_id: str, interview: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """1. Só transforma material do caso em fatos e eventos tipados."""
    facts: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for raw in peticao_local._fatos_documentais(caso_id):  # noqa: SLF001 - adaptador de OCR já persistido
        text = str(raw.get("fato") or "").strip()
        if not text:
            continue
        provenance = raw.get("proveniencia") or {}
        fact_id = f"F{len(facts) + 1:03d}"
        facts.append({
            "fact_id": fact_id, "subject": "autor", "type": "DOCUMENTED_FACT", "text": text,
            "value": raw.get("valor"), "certainty": "CONFIRMED" if provenance else "INFERRED",
            "source": {"document_id": provenance.get("arquivo"), "page": provenance.get("pagina"), "excerpt": provenance.get("citacao")},
        })
        for match in re.finditer(r"\b(\d{2}/\d{2}/\d{4})\b", text):
            events.append({"event_id": f"EV{len(events) + 1:03d}", "event_type": "DOCUMENT_EVENT", "date": match.group(1),
                           "subject": "autor", "related_entity": None, "source_fact_id": fact_id})
    if interview.strip():
        facts.append({"fact_id": f"F{len(facts) + 1:03d}", "subject": "autor", "type": "INTERVIEW_REPORT",
                      "text": interview.strip()[:8_000], "value": None, "certainty": "ALLEGED",
                      "source": {"document_id": "INTERVIEW", "page": None, "excerpt": interview.strip()[:500]}})
    events.append({"event_id": f"EV{len(events) + 1:03d}", "event_type": "PETITION_DATE", "date": date.today().isoformat(),
                   "subject": "petition", "related_entity": None, "source_fact_id": None})
    return facts, events, {"stage": "INGESTION_AND_FACT_MATRIX", "facts": len(facts), "events": len(events)}


def issue_matrix(facts: list[dict[str, Any]], interview: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """2. Descoberta jurídica em duas passagens; não cria pedidos nem texto."""
    contract = (
        "Você é LUNA_ISSUE_SPOTTER. Retorne JSON {issues:[...]}. Cada issue deve conter name, status "
        "(DISCOVERED|SUPPORTED|NEEDS_CONFIRMATION|REJECTED), classification, triggering_fact_ids, "
        "supporting_fact_ids, missing_fact_questions, required_evidence, possible_requests, counterarguments e confidence. "
        "Não crie fatos, valores, artigos, autoridades ou pedidos finais."
    )
    base = {"facts": facts, "interview": interview[:12_000]}
    first, trace_a = _call("ISSUE_MATRIX_PASS_A", contract + " Descubra todas as teses positivas.", base)
    second, trace_b = _call("ISSUE_MATRIX_PASS_B", contract + " Procure teses esquecidas pela primeira análise.", base)
    unique: dict[str, dict[str, Any]] = {}
    for item in [*(first.get("issues") or []), *(second.get("issues") or [])]:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            continue
        key = str(item["name"]).strip().casefold()
        unique.setdefault(key, {**item, "issue_id": f"I{len(unique) + 1:03d}"})
    return list(unique.values()), {"stage": "ISSUE_MATRIX", "passes": [trace_a, trace_b], "issues": len(unique)}


def legal_support(issues: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """3. Recupera somente autoridades existentes; sem completar Direito por memória."""
    catalog, error = repositorio_juridico.carregar_autoridades()
    index = [{"authority_id": a.id, "type": a.tipo, "title": a.titulo, "valid_from": str(a.data or "")} for a in catalog[:500]]
    authorities: list[dict[str, Any]] = []
    for issue in issues:
        if str(issue.get("status") or "").upper() != "SUPPORTED":
            continue
        result, trace = _call("LEGAL_SUPPORT", (
            "Você é LEGAL_SUPPORT. Retorne JSON {claims:[{text,claim_type,required_authority_type,authority_ids}]}. "
            "Use apenas authority_ids existentes no catálogo; se não houver suporte, devolva authority_ids vazio."
        ), {"issue": issue, "authority_catalog": index})
        authorities.append({"issue_id": issue["issue_id"], "claims": result.get("claims") or [], "trace": trace})
    return authorities, {"stage": "LEGAL_SUPPORT", "catalog_error": error, "authority_sets": len(authorities)}


def petition_plan(state: CaseStateV2) -> dict[str, Any]:
    """4. Único ponto que cria capítulos, pedidos, cálculos e valor da causa."""
    chapters: list[dict[str, Any]] = []
    seen_requests: set[str] = set()
    for issue in state.issues:
        if str(issue.get("status") or "").upper() != "SUPPORTED":
            continue
        iid = str(issue["issue_id"])
        support = next((a for a in state.authorities if a["issue_id"] == iid), {})
        authority_ids = [aid for claim in support.get("claims") or [] for aid in claim.get("authority_ids") or []]
        request_ids: list[str] = []
        # A issue pode sugerir consequências processuais; somente esta etapa
        # materializa cada uma em request. Texto posterior jamais infere pedido
        # a partir de título, capítulo ou regex.
        for candidate in issue.get("possible_requests") or []:
            title = str(candidate.get("title") if isinstance(candidate, dict) else candidate or "").strip()
            if not title:
                continue
            semantic_key = re.sub(r"[^A-Z0-9]+", "_", title.upper()).strip("_")[:80]
            if not semantic_key or semantic_key in seen_requests:
                continue
            seen_requests.add(semantic_key)
            request_id = f"R{len(state.requests) + 1:03d}"
            requested_type = str(candidate.get("type") if isinstance(candidate, dict) else "").upper()
            monetary = requested_type == "MONETARY"
            # Sem parâmetros completos não há valor, cálculo ou liquidação
            # artificial. O request continua rastreável e pede revisão humana.
            request = {
                "request_id": request_id, "semantic_key": semantic_key,
                "type": "MONETARY" if monetary else (requested_type or "DECLARATORY"),
                "title": title, "issue_id": iid,
                "fact_ids": list(dict.fromkeys([*(issue.get("triggering_fact_ids") or []), *(issue.get("supporting_fact_ids") or [])])),
                "authority_ids": list(dict.fromkeys(authority_ids)), "calculation_id": None,
                "value": None, "status": "NEEDS_INPUT" if monetary else "SUPPORTED",
            }
            state.requests.append(request)
            request_ids.append(request_id)
        chapters.append({"chapter_id": f"CH_{iid}", "issue_id": iid,
                         "allowed_fact_ids": list(dict.fromkeys([*(issue.get("triggering_fact_ids") or []), *(issue.get("supporting_fact_ids") or [])])),
                         "allowed_authority_ids": list(dict.fromkeys(authority_ids)), "allowed_evidence_ids": [],
                         "linked_request_ids": request_ids, "title": str(issue.get("name") or "")})
    state.metadata["petition_date"] = date.today().isoformat()
    state.metadata["case_value"] = "0.00"
    return {"stage": "PETITION_PLAN", "chapters": len(chapters), "requests": len(state.requests),
            "calculations": len(state.calculations), "chapters_data": chapters}


def chapter_writing(state: CaseStateV2, plan: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """5. Um contrato por capítulo. O modelo escreve apenas prosa autorizada."""
    by_id = {f["fact_id"]: f for f in state.facts}
    sections: list[dict[str, Any]] = []
    for chapter in plan["chapters_data"]:
        allowed = [by_id[f] for f in chapter["allowed_fact_ids"] if f in by_id]
        result, trace = _call("CHAPTER_WRITING", (
            "Você é LUNA_CHAPTER_WRITER. Redija somente prosa jurídica para o contrato fornecido. "
            "Não crie fatos, datas, valores, pedidos ou autoridades. Respeite certainty: EXPERT_DEPENDENT exige linguagem condicional. "
            "Estruture fato → prova → regra → subsunção → consequência. Retorne JSON {content}."
        ), {"chapter_contract": chapter, "facts": allowed})
        content = str(result.get("content") or "").strip()
        if content:
            sections.append({"code": chapter["chapter_id"], "label": chapter["title"], "content": content, "written_by": "LUNA_CHAPTER_WRITER"})
        state.internal_trace.setdefault("chapter_calls", []).append(trace)
    return sections, {"stage": "CHAPTER_WRITING", "chapters_written": len(sections)}


def review_and_repair(state: CaseStateV2) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """6. Um reviewer read-only. Reparos futuros podem tocar apenas prose_sections."""
    result, trace = _call("REVIEW_AND_REPAIR", (
        "Você é o único revisor da petição. Não altere nada. Retorne JSON {findings:[{kind:REPAIRABLE|NEEDS_REVIEW|CRITICAL,code,message,chapter_id}]}. "
        "Procure contradição, excesso de certeza, fato sem suporte, citação inadequada, pedido/fundamento desconectado e repetição."
    ), {"facts": state.facts, "issues": state.issues, "authorities": state.authorities, "sections": state.prose_sections})
    return [x for x in result.get("findings") or [] if isinstance(x, dict)], {"stage": "REVIEW_AND_REPAIR", "review": trace}


def final_render(state: CaseStateV2) -> list[dict[str, Any]]:
    """7. Montagem determinística; não interpreta fatos ou Direito."""
    sections = list(state.prose_sections)
    requests = [r for r in state.requests if r.get("status") == "SUPPORTED"]
    if requests:
        lines = ["Diante do exposto, requer:"]
        for index, request in enumerate(requests):
            lines.append(f"{chr(97 + index)}) {request['title'].rstrip('.')}.")
        sections.append({"code": "CLAIMS", "label": "Dos pedidos", "content": "\n\n".join(lines), "written_by": "FINAL_RENDER"})
    return sections


def run(caso_id: str, *, interview: str) -> dict[str, Any]:
    """Entrada única da V2. Toda etapa fica registrada no trace administrativo."""
    generation_id = str(uuid.uuid4())
    facts, events, trace_facts = ingestion_and_fact_matrix(caso_id, interview)
    issues, trace_issues = issue_matrix(facts, interview)
    authorities, trace_legal = legal_support(issues)
    state = CaseStateV2(facts=facts, events=events, issues=issues, authorities=authorities,
                        metadata={"generation_id": generation_id})
    plan = petition_plan(state)
    finalizar_plano(state)
    sections, trace_write = chapter_writing(state, plan)
    state.prose_sections = sections
    findings, trace_review = review_and_repair(state)
    immutable_findings = state.verify_immutable()
    sections = final_render(state)
    critical = [f for f in findings if str(f.get("kind") or "") == "CRITICAL"] + [{"code": x} for x in immutable_findings]
    status = "READY" if sections and not critical else ("NEEDS_REVIEW" if sections else "DRAFT")
    return {"generation_id": generation_id, "status": status, "sections": sections, "findings": findings,
            "case_state": state.as_dict(), "trace": {"stages": [trace_facts, trace_issues, trace_legal, plan, trace_write, trace_review]},
            "protocolable": status == "READY", "can_save": True}
