"""Séries dos gráficos de uso: dia do escritório, dias vazios zerados e alerta de pico."""

from datetime import datetime, timezone

from app import custos_api

AGORA = datetime(2026, 9, 28, 19, 30, tzinfo=timezone.utc)  # 16h30 em Brasília


def _linha(hora, fornecedor="openrouter", operacao="ocr", tokens=1000, custo=0.01, chamadas=1, status="SUCCESS"):
    return {"hora": hora, "fornecedor": fornecedor, "operacao": operacao, "status": status,
            "chamadas": chamadas, "tokens": tokens, "custo_usd": custo}


def test_dia_e_hora_seguem_o_fuso_do_escritorio():
    # 01h UTC do dia 28 ainda é 22h do dia 27 em Brasília.
    uso = custos_api.agregar_uso([_linha("2026-09-28T01")], dias=7, agora=AGORA)
    dias = {d["dia"]: d for d in uso["por_dia"]}
    assert dias["2026-09-27"]["tokens"] == 1000 and dias["2026-09-28"]["tokens"] == 0
    assert [d["dia"] for d in uso["por_dia"]][-1] == "2026-09-28" and len(uso["por_dia"]) == 7
    assert len(uso["por_hora"]) == 24 and uso["por_hora"][-1]["hora"] == "2026-09-28T16"


def test_pico_de_hoje_vira_alerta_e_aponta_a_operacao():
    linhas = [_linha(f"2026-09-{d:02d}T15", custo=1.0) for d in range(21, 28)]
    linhas.append(_linha("2026-09-28T15", operacao="analise_documentos", custo=4.0, tokens=90_000))
    uso = custos_api.agregar_uso(linhas, dias=30, agora=AGORA)
    assert uso["alerta"]["nivel"] == "critico" and uso["alerta"]["medida"] == "custo"
    assert "4,0 vezes" in uso["alerta"]["mensagem"]
    assert uso["alerta"]["principal_hoje"] == {"operacao": "analise_documentos", "fornecedor": "openrouter", "valor": 4.0}
    assert uso["por_operacao"][0]["operacao"] == "ocr", "a lista do período segue o gasto do período inteiro"


def test_sem_custo_informado_compara_por_tokens_e_avisa_o_fornecedor():
    linhas = [_linha(f"2026-09-{d:02d}T15", fornecedor="deepseek", custo=0, tokens=1000) for d in range(21, 28)]
    linhas.append(_linha("2026-09-28T15", fornecedor="deepseek", custo=0, tokens=2000))
    uso = custos_api.agregar_uso(linhas, dias=30, agora=AGORA)
    assert uso["alerta"]["medida"] == "tokens" and uso["alerta"]["nivel"] == "atencao"
    assert uso["fornecedores_sem_custo"] == ["deepseek"]


def test_sem_historico_nao_inventa_alerta():
    uso = custos_api.agregar_uso([_linha("2026-09-28T15")], dias=7, agora=AGORA)
    assert uso["alerta"]["nivel"] == "ok" and uso["alerta"]["vezes"] is None
    assert uso["totais"]["chamadas"] == 1
