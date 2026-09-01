from app import recomendacao
from app.rag import TrechoSimilar


def trecho(rotulo: str, similaridade: float = 0.74) -> TrechoSimilar:
    return TrechoSimilar(
        texto="fundamentação e prova do processo",
        similaridade=similaridade,
        titulo="Decisão",
        identificador="0000000-00.2026.5.08.0001",
        url="https://example.test/decisao",
        metadados={"rotulo": rotulo, "numero_processo": "0000000-00.2026.5.08.0001"},
    )


def test_recomenda_abrir_com_amostra_favoravel(monkeypatch) -> None:
    amostra = [trecho("PROCEDENTE"), trecho("PARCIAL"), trecho("PROCEDENTE"), trecho("IMPROCEDENTE")]
    monkeypatch.setattr(recomendacao.rag, "buscar_similares", lambda *args, **kwargs: amostra)
    resultado = recomendacao.recomendar("Relato completo do vínculo, prova e acidente.")
    assert resultado["recomendado"] == "sim"
    assert resultado["estatistica"]["desfechos_merito"]["processos"] == 4
    assert resultado["com_precedentes"] is True


def test_lacuna_rebaixa_recomendacao(monkeypatch) -> None:
    amostra = [trecho("PROCEDENTE") for _ in range(4)]
    monkeypatch.setattr(recomendacao.rag, "buscar_similares", lambda *args, **kwargs: amostra)
    resultado = recomendacao.recomendar(
        "Relato completo do vínculo, prova e acidente.",
        lacunas_obrigatorias=["Qual foi a data do acidente?"],
    )
    assert resultado["recomendado"] == "com_ressalva"
    assert resultado["lacunas_obrigatorias"] == ["Qual foi a data do acidente?"]


def test_amostra_fraca_nao_inventa_recomendacao(monkeypatch) -> None:
    monkeypatch.setattr(recomendacao.rag, "buscar_similares", lambda *args, **kwargs: [trecho("PROCEDENTE")])
    resultado = recomendacao.recomendar("Relato completo do vínculo, prova e acidente.")
    assert resultado["recomendado"] == "indefinido"
    assert "pouco" in resultado["motivo"].lower()
