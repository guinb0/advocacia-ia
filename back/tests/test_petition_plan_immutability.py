"""Regressões estruturais: estes testes não chamam LLM."""

from __future__ import annotations

import pytest

from app.juridico import imutabilidade
from app.juridico import render


def _plano() -> dict:
    pedido = {
        "id": "REQ_001", "request_id": "REQ_001", "title": "Dano moral",
        "tipo": "Dano moral", "objeto": "indenização por dano moral",
        "factual_support": ["FACT_001"], "authority_ids": ["AUTH_001"],
        "valor": 50000.0, "value": 50000.0, "calculation_id": "CALC_001",
        "metodo_calculo": {"base": 50000, "multiplicador": 1, "resultado": 50000},
        "natureza": "cumulativo", "tipo_de_item": "autonomo",
    }
    return {
        "petition_date": "2026-10-01", "fatos": [{"id": "FACT_001", "source_document_id": "DOC_1"}],
        "teses": [{"id": "ISSUE_001", "pedidos_ids": ["REQ_001"]}], "pedidos": [pedido],
        "valor_da_causa_calculado": {"valor": 50000.0, "pedidos_somados": ["REQ_001"]},
    }


def test_request_value_is_immutable_after_plan_finalized():
    plano = _plano()
    snapshot = imutabilidade.congelar(plano)
    plano["pedidos"][0]["valor"] = 2579.16
    with pytest.raises(imutabilidade.MutacaoDoPlano, match="pedidos"):
        imutabilidade.verificar(snapshot, plano, etapa="renderer")


def test_monetary_request_without_calculation_is_invalid_and_unrenderable():
    plano = _plano()
    plano["pedidos"][0]["calculation_id"] = ""
    assert any("sem calculation_id" in erro for erro in imutabilidade.validar(plano))
    with pytest.raises(ValueError, match="sem calculation_id"):
        render.secao_pedidos(plano)


def test_request_without_facts_or_authority_is_invalid():
    plano = _plano()
    plano["pedidos"][0]["factual_support"] = []
    plano["pedidos"][0]["authority_ids"] = []
    erros = imutabilidade.validar(plano)
    assert any("factual_support" in erro for erro in erros)
    assert any("authority_ids" in erro for erro in erros)


def test_case_value_must_equal_canonical_sum():
    plano = _plano()
    plano["valor_da_causa_calculado"]["valor"] = 1.0
    assert "valor_da_causa_calculado diverge da soma canônica dos pedidos" in imutabilidade.validar(plano)


def test_renderer_cannot_create_request_from_text():
    plano = _plano()
    texto = render.secao_pedidos(plano, introducao="Diante do exposto, requer:")
    assert "REQ_001" not in texto
    assert texto.count("indenização por dano moral") == 1
    assert "R$ 50.000,00" in texto
