from datetime import date

import pytest

from app.juridico import case_state


def _state():
    return {
        "facts": [{"id": "F01", "fonte": "doc.pdf", "data": "2026-01-01"}],
        "issues": [{"id": "I01", "decisao": "INCLUIR"}],
        "authorities": [{"issue_id": "I01", "authority_ids": ["A01"]}],
        "calculations": [{"calculation_id": "C01", "valor": 50000}],
        "requests": [{"request_id": "R01", "issue_id": "I01", "semantic_key": "DANO_MORAL", "factual_support": ["F01"], "authority_ids": ["A01"], "calculation_id": "C01", "value": 50000}],
        "tables": {}, "metadata": {"petition_date": "2026-02-01", "case_value": {"valor": 50000}},
        "internal_trace": {}, "prose_sections": [],
    }


def test_request_value_is_immutable():
    state = _state(); frozen = case_state.congelar(state); state["requests"][0]["value"] = 2579.16
    with pytest.raises(case_state.MutacaoDoCaseState): case_state.verificar(frozen, state, etapa="teste")


def test_request_cannot_be_added_or_removed_after_finalize():
    state = _state(); frozen = case_state.congelar(state); state["requests"].append(dict(state["requests"][0], request_id="R02"))
    with pytest.raises(case_state.MutacaoDoCaseState): case_state.verificar(frozen, state, etapa="teste")
    state = _state(); frozen = case_state.congelar(state); state["requests"] = []
    with pytest.raises(case_state.MutacaoDoCaseState): case_state.verificar(frozen, state, etapa="teste")


def test_calculation_cannot_change_after_finalize():
    state = _state(); frozen = case_state.congelar(state); state["calculations"][0]["valor"] = 1
    with pytest.raises(case_state.MutacaoDoCaseState): case_state.verificar(frozen, state, etapa="teste")


def test_supported_issue_requires_request_or_reason():
    state = _state(); state["requests"] = []
    assert "I01: issue suportada sem request ou no_request_reason" in case_state.validar(state)


def test_duplicate_semantic_request_is_rejected():
    state = _state(); state["requests"].append(dict(state["requests"][0], request_id="R02"))
    assert any("semanticamente duplicado" in e for e in case_state.validar(state))


def test_request_value_must_match_its_calculation():
    state = _state(); state["requests"][0]["value"] = 2579.16
    assert "R01: valor diverge de C01" in case_state.validar(state)


def test_trace_cannot_enter_prose():
    assert case_state.trace_em_prosa([{"code": "FACTS", "content": "evento-5 autor.cpf"}])


def test_request_without_fact_or_authority_is_invalid():
    state = _state(); state["requests"][0]["factual_support"] = []; state["requests"][0]["authority_ids"] = []
    errors = case_state.validar(state)
    assert any("factual_support" in e for e in errors) and any("authority_ids" in e for e in errors)


def test_snapshot_identifies_stage_and_is_stable():
    snap = case_state.snapshot("g1", "SNAPSHOT_PLAN_FINALIZED", _state())
    assert snap["generation_id"] == "g1" and snap["stage"] == "SNAPSHOT_PLAN_FINALIZED" and len(snap["hash"]) == 64
