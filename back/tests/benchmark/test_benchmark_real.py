"""Benchmark real sem banco: a guarda só-SELECT, a anonimização e as métricas ANTES sobre um par fabricado."""

from __future__ import annotations

import json

import pytest

from benchmark_real import extrair_casos, rodar


def _dados(secoes: dict[str, str], *, com_trace: bool) -> str:
    dados = {"sections": [{"code": k, "label": k, "content": v} for k, v in secoes.items()],
             "protocolo": {"numero": "0001234-56.2026.5.01.0001"}}
    if com_trace:
        dados["trace"] = {"pipeline": {"plano_estruturado": {"partes": {"autor": {"nome": "Maria Aparecida Souza"},
                                                                         "reu": {"razao_social": "Transportes Boa Viagem Ltda"}}}},
                          "case_brief": {"facts": ["Maria Aparecida Souza, CPF 123.456.789-09, tel (21) 99876-5432"]}}
    return json.dumps(dados, ensure_ascii=False)


GERADA = {
    "FACTS": "A reclamante Maria Aparecida Souza foi admitida em 01/02/2020 com salário de R$ 2.500,00 e dispensada em 10/03/2024.",
    "LEGAL_GROUNDS": "I - DAS HORAS EXTRAS\nTexto. Art. 59 da CLT e Súmula 338 do TST.\nII - DO DANO MORAL\nTexto. Art. 223-B da CLT.",
    "CLAIMS": "Requer:\na) horas extras com reflexos;\nb) indenização por dano moral;",
    "VALUE": "Dá-se à causa o valor de R$ 50.000,00.",
}
APROVADA = {
    "FACTS": "A reclamante foi admitida em 01/02/2020 com salário de R$ 2.800,00 e dispensada em 10/03/2024.",
    "LEGAL_GROUNDS": "I - DAS HORAS EXTRAS\nTexto. Art. 59 da CLT e Súmula 338 do TST.\nII - DO INTERVALO INTRAJORNADA\nArt. 71 da CLT.",
    "CLAIMS": "Requer:\na) horas extras com reflexos;\nb) intervalo intrajornada suprimido;",
    "VALUE": "Dá-se à causa o valor de R$ 40.000,00.",
}


def _caso() -> dict:
    linha = {"caso_id": "caso-real-42", "dados_json": _dados(APROVADA, com_trace=True), "categoria": "trabalhista",
             "cliente": "Maria Aparecida Souza"}
    return extrair_casos.montar_caso(linha, [{"dados_json": _dados(GERADA, com_trace=True)}])


def test_extrator_recusa_o_que_nao_e_select():
    assert extrair_casos._somente_select(extrair_casos._SQL_APROVADAS)
    for sql in ("UPDATE acervo_peticoes_locais SET status='x'", "SELECT 1; DELETE FROM acervo_casos", "EXEC sp_who"):
        with pytest.raises(RuntimeError):
            extrair_casos._somente_select(sql)


def test_caso_sai_anonimizado_e_sem_id_real():
    caso = _caso()
    bruto = json.dumps(caso, ensure_ascii=False)
    for proibido in ("Maria", "Aparecida", "Souza", "Boa Viagem", "123.456.789-09", "99876-5432", "caso-real-42", "0001234-56"):
        assert proibido not in bruto
    assert caso["id"] != "caso-real-42" and len(caso["id"]) == 16
    assert "[NOME]" in caso["gerada"]["secoes"][0]["content"]
    assert "Súmula 338 do TST" in bruto


def test_sem_versao_arquivada_nao_ha_par_para_medir():
    linha = {"caso_id": "x", "dados_json": _dados(APROVADA, com_trace=True), "categoria": "", "cliente": ""}
    assert extrair_casos.montar_caso(linha, []) is None


def test_metricas_antes_do_par_gerada_aprovada():
    m = rodar.medir_antes(_caso())
    assert m["tese_recall"] == 0.5 and m["tese_precisao"] == 0.5
    assert m["pedidos_faltantes"] == 1 and m["pedidos_excedentes"] == 1
    assert m["autoridades_removidas"] == pytest.approx(1 / 3, abs=0.001)
    assert m["autoridades_acrescentadas"] == 1
    assert m["fatos_corrigidos"] == pytest.approx(1 / 3, abs=0.001)
    assert m["valor_causa_divergencia"] == 0.25
    assert m["reescrita"]["LEGAL_GROUNDS"] > 0


def test_agregado_ignora_campos_nao_numericos():
    por_caso = {"a": {"antes": rodar.medir_antes(_caso())}}
    agregado = rodar.agregar(por_caso, "antes")
    assert agregado["tese_recall"] == 0.5 and "reescrita_media" in agregado and "_topicos_aprovados" not in agregado
