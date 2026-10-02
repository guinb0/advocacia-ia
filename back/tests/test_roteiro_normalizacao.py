"""Roteiro importado de documento: o que é salvo é o que a entrevista recebe, limpo e na mesma ordem."""

from __future__ import annotations

import pytest

roteiros = pytest.importorskip("app.roteiros", reason="exige as dependências do backend")


def _bruto(n_blocos=3, por_bloco=4):
    return {
        "nome": "# ENTREVISTA TESTE",
        "blocos": [
            {
                "titulo": f"## BLOCO {b}",
                "perguntas": [{"texto": f"Pergunta {b}.{q}\tcom tab​"} for q in range(por_bloco)],
            }
            for b in range(n_blocos)
        ],
    }


def _total(ro):
    return sum(len(b.perguntas) for b in ro.blocos)


def test_marcas_de_markdown_e_invisiveis_saem_do_conteudo():
    ro = roteiros.de_dict(_bruto())
    assert ro.nome == "ENTREVISTA TESTE"
    assert all(not b.titulo.startswith("#") for b in ro.blocos)
    assert all("\t" not in p.texto and "​" not in p.texto for b in ro.blocos for p in b.perguntas)


def test_cabecalho_de_secao_nao_vira_pergunta():
    bruto = _bruto(1, 2)
    bruto["blocos"][0]["perguntas"].insert(1, {"texto": "BLOCO 5 — Atendimento Médico e Afastamento"})
    ro = roteiros.de_dict(bruto)
    textos = [p.texto for b in ro.blocos for p in b.perguntas]
    assert not any(roteiros.eh_titulo_de_secao(t) for t in textos)
    assert "Pergunta 0.0 com tab" in textos and "Pergunta 0.1 com tab" in textos


def test_ordem_e_contagem_sobrevivem_ao_ciclo_salvar_e_ler():
    ro = roteiros.de_dict(_bruto())
    de_novo = roteiros.de_dict(ro.to_dict())
    ordem = [p.id for b in ro.blocos for p in b.perguntas]
    assert ordem == [p.id for b in de_novo.blocos for p in b.perguntas]
    assert _total(ro) == _total(de_novo) == len(ordem)


def test_roteiro_sem_perguntas_e_erro_e_nao_lista_vazia():
    bruto = _bruto()
    for b in bruto["blocos"]:
        b["perguntas"] = []
    with pytest.raises(roteiros.RoteiroInvalido):
        roteiros.de_dict(bruto)
