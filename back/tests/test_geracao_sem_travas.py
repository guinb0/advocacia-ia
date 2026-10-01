"""O que segurava a geração sem a tela mudar: plano repetido após timeout, documentos relidos, esquema refeito."""

from __future__ import annotations

import httpx
import pytest

pl = pytest.importorskip("app.peticao_local", reason="peticao_local exige as dependências do backend")


def test_plano_nao_repete_chamada_que_esgotou_o_prazo(monkeypatch):
    chamadas = []

    def post(*args, **kwargs):
        chamadas.append(1)
        raise httpx.ReadTimeout("lento")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setattr(pl.httpx, "post", post)
    monkeypatch.setattr(pl.custos_api, "registrar_falha", lambda *a, **k: None)
    with pytest.raises(pl.ErroPeticao):
        pl._llm_json("i", "e", timeout=1.0, repetir_apos_timeout=False)
    assert len(chamadas) == 1
    chamadas.clear()
    with pytest.raises(pl.ErroPeticao):
        pl._llm_json("i", "e", timeout=1.0)
    assert len(chamadas) == 2


def test_documentos_lidos_uma_vez_por_geracao(monkeypatch):
    leituras = []

    def ler(caso_id):
        leituras.append(caso_id)
        return [{"canonical_file": "a.pdf"}], [{"arquivo": "a.pdf", "texto": "x"}]

    monkeypatch.setattr(pl, "_ler_documentos_logicos", ler)

    @pl._com_documentos_da_geracao
    def geracao():
        primeiro = pl.documentos_logicos("c1")
        primeiro[1].append({"arquivo": "intruso"})
        return pl.documentos_logicos("c1")

    assert geracao()[1] == [{"arquivo": "a.pdf", "texto": "x"}]
    assert leituras == ["c1"]
    pl.documentos_logicos("c1")
    assert leituras == ["c1", "c1"]


def test_esquema_do_aprendizado_criado_uma_vez(monkeypatch):
    from app import peticao_aprendizado

    criados = []
    monkeypatch.setattr(peticao_aprendizado, "_ESQUEMA_PRONTO", False)
    monkeypatch.setattr(peticao_aprendizado, "_criar_esquema", lambda: criados.append(1))
    peticao_aprendizado.inicializar()
    peticao_aprendizado.inicializar()
    assert criados == [1]


def test_autoridades_em_cache(monkeypatch):
    from app.juridico import repositorio

    consultas = []
    linha = {"id": "s1", "tipo": "sumula", "tribunal": "TST", "numero": "338", "titulo": "Súmula 338 do TST", "texto": "t"}
    monkeypatch.setattr(repositorio, "_cache_autoridades", {})
    monkeypatch.setattr(repositorio, "_consultar", lambda sql, p: consultas.append(1) or [linha])
    a, _ = repositorio.carregar_autoridades()
    b, _ = repositorio.carregar_autoridades()
    assert len(consultas) == 1 and len(a) == len(b)


def _solicitacao(idade_s, sid="s1"):
    from datetime import datetime, timedelta, timezone
    return {"id": sid, "solicitada_em": (datetime.now(timezone.utc) - timedelta(seconds=idade_s)).isoformat()}


def test_solicitacao_orfa_ou_estourada_e_encerrada(monkeypatch):
    monkeypatch.setattr(pl, "_EM_EXECUCAO", set())
    assert pl._solicitacao_perdida(_solicitacao(5)) == ""
    assert "interrompida" in pl._solicitacao_perdida(_solicitacao(60))
    pl._EM_EXECUCAO.add("s1")
    assert pl._solicitacao_perdida(_solicitacao(60)) == ""
    assert "tempo limite" in pl._solicitacao_perdida(_solicitacao(pl.LIMITE_SOLICITACAO_S + 10))


def test_plano_tem_prazo_total_e_a_geracao_segue_sem_ele(monkeypatch):
    import time
    monkeypatch.setattr(pl, "PRAZO_PLANO_S", 0.3)
    monkeypatch.setattr(pl, "_llm_json", lambda *a, **k: time.sleep(2) or {"teses": [1]})
    inicio = time.monotonic()
    assert pl._outline_juridico("contexto") is None
    assert time.monotonic() - inicio < 1.5
