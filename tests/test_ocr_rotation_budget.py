from unittest.mock import patch

import numpy as np

from app import pipeline
from app.extractors import Linha


def _linha(texto: str) -> Linha:
    return Linha(texto=texto, confianca=1.0, y=0, x=0, largura=10, altura=10)


def test_rotacoes_param_ao_atingir_orcamento(monkeypatch):
    monkeypatch.setenv("OCR_ORIENTATION_FALLBACK_BUDGET_S", "45")
    relogio = iter((0.0, 50.0))

    with (
        patch.object(pipeline.time, "perf_counter", side_effect=lambda: next(relogio)),
        patch.object(pipeline, "rodar_ocr_com_tempo", return_value=([], {"total_s": 50.0})),
    ):
        _, _, tentativas, passadas = pipeline.ocr_com_rotacao_medido(
            np.zeros((10, 10, 3), dtype=np.uint8), "pt"
        )

    assert passadas == 1
    assert len(tentativas) == 1


def test_documento_legivel_nao_tenta_rotacao(monkeypatch):
    monkeypatch.setenv("OCR_ORIENTATION_FALLBACK_BUDGET_S", "45")
    with patch.object(
        pipeline,
        "rodar_ocr_com_tempo",
        return_value=([_linha("documento suficientemente legivel para seguir sem precisar de outra leitura")], {"total_s": 1.0}),
    ) as executar:
        _, rotacao, _, passadas = pipeline.ocr_com_rotacao_medido(
            np.zeros((10, 10, 3), dtype=np.uint8), "pt"
        )

    assert rotacao == 0
    assert passadas == 1
    executar.assert_called_once()
