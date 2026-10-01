"""Gate do CI: o motor jurídico não pode piorar nos casos sintéticos difíceis em relação à linha de base."""

from __future__ import annotations

import json

from . import sintetico


def test_motor_nao_regride_nos_casos_sinteticos():
    atual = sintetico.rodar()
    base = json.loads(sintetico.ARQUIVO_BASE.read_text(encoding="utf-8"))
    assert atual["casos"] >= base["casos"], "casos sintéticos foram removidos"
    erros = sintetico.regressoes(atual, base)
    assert not erros, "regressão no benchmark sintético:\n" + "\n".join(erros) + "\n" + json.dumps(atual["por_caso"], ensure_ascii=False, indent=1)


def test_caso_limpo_nao_gera_ruido():
    atual = sintetico.rodar()
    assert atual["metricas"]["falsos_positivos_caso_limpo"] == 0, atual["por_caso"]
