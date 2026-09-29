from types import SimpleNamespace

import pytest

from app.pesquisa_jurisprudencial import PrecedenteEstruturado, StatusVerificacao
from app.precedentes_verificados import separar_para_redacao, salvar


def test_separa_material_de_revisao_do_material_citavel():
    ok = SimpleNamespace(metadados={"status_verificacao": "VERIFIED"})
    revisar = SimpleNamespace(metadados={"status_verificacao": "UNVERIFIED"})
    assert separar_para_redacao([ok, revisar]) == ([ok], [revisar])


def test_recusa_promover_sem_confirmacao():
    p = PrecedenteEstruturado(tribunal="TRT8", numero_processo="1", ementa="e", fonte_url="https://oficial")
    with pytest.raises(ValueError):
        salvar(p, texto_original="texto")


def test_precedente_verificado_e_apto():
    p = PrecedenteEstruturado(tribunal="TRT8", numero_processo="1", ementa="e",
                              fonte_url="https://oficial", status_verificacao=StatusVerificacao.VERIFIED)
    assert p.apto_para_citacao()
