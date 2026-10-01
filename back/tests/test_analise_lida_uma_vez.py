"""Os mesmos documentos são lidos pelo modelo UMA vez; o resultado fica guardado com o contexto do caso."""

from __future__ import annotations

import pytest

ad = pytest.importorskip("app.analise_documentos", reason="exige as dependências do backend")


@pytest.fixture
def ambiente(monkeypatch):
    from app.agente import contexto_caso

    guardado: dict = {}
    chamadas: list = []
    docs = [{"id": "d1", "arquivo": "ctps.pdf", "texto": "texto da ctps"}]
    fatos = ["Função: carteiro"]
    monkeypatch.setattr(ad, "_documentos_do_caso", lambda caso_id: docs)
    monkeypatch.setattr(ad, "_fatos_conhecidos", lambda caso_id: fatos)
    monkeypatch.setattr(contexto_caso, "_ler", lambda caso_id: dict(guardado.get(caso_id, {})))
    monkeypatch.setattr(contexto_caso, "_gravar", lambda caso_id, dados: guardado.__setitem__(caso_id, dict(dados)))

    def computar(caso_id, assinatura):
        chamadas.append(assinatura)
        return {"achados": [{"informacao": "x"}], "documentos_lidos": len(docs)}

    monkeypatch.setattr(ad, "_analisar_cacheado", computar)
    return docs, fatos, chamadas


def test_mesmos_documentos_nao_chamam_o_modelo_de_novo(ambiente):
    _, _, chamadas = ambiente
    primeira = ad.analisar("c1")
    segunda = ad.analisar("c1")
    terceira = ad.analisar("c1")
    assert len(chamadas) == 1
    assert not primeira.get("reaproveitada")
    assert segunda["reaproveitada"] and terceira["reaproveitada"]
    assert segunda["achados"] == primeira["achados"]


def test_documento_novo_ou_resposta_nova_leem_de_novo(ambiente):
    docs, fatos, chamadas = ambiente
    ad.analisar("c1")
    docs.append({"id": "d2", "arquivo": "rg.pdf", "texto": "texto do rg"})
    ad.analisar("c1")
    fatos.append("Sofreu assalto: sim")
    ad.analisar("c1")
    assert len(chamadas) == 3


def test_sem_documentos_nada_e_guardado(ambiente, monkeypatch):
    docs, _, chamadas = ambiente
    docs.clear()
    monkeypatch.setattr(ad, "_analisar_cacheado", lambda c, a: chamadas.append(1) or {"achados": [], "documentos_lidos": 0, "aviso": "sem texto"})
    ad.analisar("c1")
    ad.analisar("c1")
    assert len(chamadas) == 2
