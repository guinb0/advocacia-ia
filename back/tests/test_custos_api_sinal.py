"""O sinal de recarga segue o saldo que o provedor informa, sem inventar restante."""

from decimal import Decimal

from app.custos_api import classificar_saldo


def test_saldo_zerado_pede_recarga_agora():
    sinal, mensagem = classificar_saldo(Decimal("0"), Decimal("50"))
    assert sinal == "critico"
    assert "Recarregue" in mensagem


def test_menos_de_dez_por_cento_pede_recarga_agora():
    sinal, _ = classificar_saldo(Decimal("5"), Decimal("100"))
    assert sinal == "critico"


def test_menos_de_vinte_e_cinco_por_cento_avisa():
    sinal, _ = classificar_saldo(Decimal("20"), Decimal("100"))
    assert sinal == "atencao"


def test_credito_folgado_pode_seguir():
    sinal, _ = classificar_saldo(Decimal("80"), Decimal("100"))
    assert sinal == "ok"


def test_sem_teto_saldo_baixo_em_dolar_avisa():
    assert classificar_saldo(Decimal("3"), None, moeda="USD")[0] == "atencao"
    assert classificar_saldo(Decimal("0.50"), None, moeda="USD")[0] == "critico"


def test_provedor_sem_saldo_nao_inventa_restante():
    sinal, mensagem = classificar_saldo(None, None)
    assert sinal == "desconhecido"
    assert "não informou" in mensagem
