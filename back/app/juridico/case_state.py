"""Estado canônico e imutável da petição após o planejamento jurídico.

Este módulo deliberadamente não conhece LLM, DOCX ou PDF. Ele é a fronteira
entre decisão jurídica e redação: tudo que muda o mérito precisa ocorrer antes
de ``finalizar``; depois disso somente ``prose_sections`` pode ser produzido.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any


ESTAGIOS = (
    "SNAPSHOT_FACTS", "SNAPSHOT_ISSUES", "SNAPSHOT_AUTHORITIES",
    "SNAPSHOT_CALCULATIONS", "SNAPSHOT_REQUESTS", "SNAPSHOT_PLAN_FINALIZED",
    "SNAPSHOT_PROSE", "SNAPSHOT_RENDER_INPUT", "SNAPSHOT_FINAL",
)
_CAMPOS_CONGELADOS = ("facts", "issues", "authorities", "calculations", "requests", "tables", "metadata")
# Somente identificadores técnicos inequívocos. Termos normais da língua como
# "caminho" não são trace e não podem barrar fundamentação jurídica válida.
_MARCADORES_INTERNOS = ("autor.cpf", "internal_trace", "generation_id", "source_document_id", "source_location")
_PADRAO_ID_INTERNO = re.compile(r"\b(?:fato|evento)-\d+\b", re.I)
_PADRAO_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I)


class MutacaoDoCaseState(RuntimeError):
    pass


def _normalizar(valor: Any) -> Any:
    if isinstance(valor, dict):
        return {str(k): _normalizar(v) for k, v in sorted(valor.items(), key=lambda x: str(x[0])) if not str(k).startswith("_")}
    if isinstance(valor, (list, tuple)):
        return [_normalizar(v) for v in valor]
    return valor


def _hash(valor: Any) -> str:
    bruto = json.dumps(_normalizar(valor), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(bruto.encode()).hexdigest()


def do_prep(prep: dict[str, Any]) -> dict[str, Any]:
    """Projeta o plano jurídico já decidido na única representação canônica."""
    plano = prep["plano_est"]
    return {
        "facts": copy.deepcopy(prep.get("matriz", {}).get("fatos") or []),
        "issues": copy.deepcopy(prep.get("issues", {}).get("teses") or []),
        "authorities": [
            {"issue_id": tid, "authority_ids": [a.id for a in autoridades]}
            for tid, autoridades in (prep.get("autoridades_por_tese") or {}).items()
        ],
        "calculations": copy.deepcopy(prep.get("calculos") or []),
        "requests": copy.deepcopy(plano.get("pedidos") or []),
        "tables": copy.deepcopy(prep.get("tabelas") or {}),
        "metadata": {
            "petition_date": str(plano.get("petition_date") or prep["data_referencia"].isoformat()),
            "case_value": copy.deepcopy(plano.get("valor_da_causa_calculado") or {}),
        },
        "internal_trace": {},
        "prose_sections": [],
    }


def congelar(state: dict[str, Any]) -> dict[str, Any]:
    return {campo: _normalizar(copy.deepcopy(state.get(campo))) for campo in _CAMPOS_CONGELADOS}


def verificar(snapshot: dict[str, Any], state: dict[str, Any], *, etapa: str) -> None:
    atual = congelar(state)
    if atual != snapshot:
        campos = [c for c in _CAMPOS_CONGELADOS if snapshot.get(c) != atual.get(c)]
        raise MutacaoDoCaseState(f"CaseState finalizado foi alterado em {etapa}: {', '.join(campos)}")


def snapshot(generation_id: str, stage: str, payload: Any) -> dict[str, Any]:
    if stage not in ESTAGIOS:
        raise ValueError(f"estágio inválido: {stage}")
    limpo = _normalizar(copy.deepcopy(payload))
    return {"generation_id": generation_id, "stage": stage, "hash": _hash(limpo),
            "timestamp": datetime.now(timezone.utc).isoformat(), "payload": limpo}


def validar(state: dict[str, Any]) -> list[str]:
    erros: list[str] = []
    calculos = {str(c.get("calculation_id") or ""): c for c in state.get("calculations") or []}
    vistos: set[str] = set()
    semanticos: set[str] = set()
    for r in state.get("requests") or []:
        rid = str(r.get("request_id") or r.get("id") or "")
        if not rid or rid in vistos:
            erros.append(f"request_id ausente ou duplicado: {rid or '<vazio>'}")
        vistos.add(rid)
        chave = str(r.get("semantic_key") or r.get("tipo") or r.get("title") or r.get("objeto") or "").strip().casefold()
        if chave and chave in semanticos:
            erros.append(f"pedido semanticamente duplicado: {chave}")
        semanticos.add(chave)
        praxe = bool(r.get("de_praxe"))
        if not praxe and not r.get("factual_support"):
            erros.append(f"{rid}: pedido sem factual_support")
        if not praxe and not r.get("authority_ids") and not r.get("no_request_reason"):
            erros.append(f"{rid}: pedido sem authority_ids")
        if (r.get("value") not in (None, "") or r.get("valor") not in (None, "")) and not r.get("calculation_id"):
            erros.append(f"{rid}: pedido monetário sem calculation_id")
        cid = str(r.get("calculation_id") or "")
        valor = r.get("value") if r.get("value") not in (None, "") else r.get("valor")
        if cid and valor not in (None, ""):
            calculo = calculos.get(cid)
            if not calculo:
                erros.append(f"{rid}: calculation_id inexistente: {cid}")
            elif str(calculo.get("valor")) != str(valor):
                erros.append(f"{rid}: valor diverge de {cid}")
    por_issue = {str(r.get("issue_id") or r.get("tese_origem") or "") for r in state.get("requests") or []}
    for issue in state.get("issues") or []:
        suportada = str(issue.get("decisao") or issue.get("status") or "").upper() in {"INCLUIR", "SUPPORTED"}
        iid = str(issue.get("id") or issue.get("issue_id") or "")
        chaves_issue = {iid, str(issue.get("tese_plano_id") or "")}
        if suportada and iid and not (chaves_issue & por_issue) and not issue.get("no_request_reason"):
            erros.append(f"{iid}: issue suportada sem request ou no_request_reason")
    return erros


def trace_em_prosa(secoes: list[dict[str, Any]]) -> list[str]:
    achados: list[str] = []
    for secao in secoes:
        texto = str(secao.get("content") or "").casefold()
        for marcador in _MARCADORES_INTERNOS:
            if marcador in texto:
                achados.append(f"{secao.get('code') or '?'}:{marcador}")
        if _PADRAO_ID_INTERNO.search(texto):
            achados.append(f"{secao.get('code') or '?'}:id_interno")
        if _PADRAO_UUID.search(texto):
            achados.append(f"{secao.get('code') or '?'}:uuid")
    return achados
