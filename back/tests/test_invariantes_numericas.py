from __future__ import annotations

from datetime import date

from app import invariantes_numericas as inv


def test_valor_por_extenso():
    assert inv.reais_por_extenso(3096207.18) == "três milhões, noventa e seis mil, duzentos e sete reais e dezoito centavos"
    assert inv.reais_por_extenso(100000) == "cem mil reais"
    assert inv.reais_por_extenso(1) == "um real"
    assert inv.reais_por_extenso(1500) == "mil e quinhentos reais"
    assert inv.reais_por_extenso(2000000) == "dois milhões de reais"
    assert inv.reais_por_extenso(0.01) == "um centavo"
    assert inv.reais_por_extenso(6121.61) == "seis mil, cento e vinte e um reais e sessenta e um centavos"
    assert inv.reais_por_extenso(101000) == "cento e um mil reais"


def test_extenso_e_regerado_a_partir_do_numero():
    secoes = [{"content": "Dá-se à causa o valor de R$ 3.096.207,18 (três milhões, quinze mil reais e trinta e seis centavos)."}]
    novas, trocas = inv.sincronizar_extenso(secoes)
    assert trocas == 1 and "noventa e seis mil" in novas[0]["content"]
    _, de_novo = inv.sincronizar_extenso(novas)
    assert de_novo == 0


def test_digito_verificador_e_recalculado():
    assert inv.cnpj_valido("34.028.316/2623-02") and not inv.cnpj_valido("34.028.316/2623-50")
    assert inv.cpf_valido("261.469.322-72")
    novas, corrigidos = inv.corrigir_digitos_verificadores([{"content": "CNPJ 34.028.316/2623-50 e CPF 261.469.322-72"}])
    assert "34.028.316/2623-02" in novas[0]["content"] and "261.469.322-72" in novas[0]["content"]
    assert len(corrigidos) == 1 and corrigidos[0]["tipo"] == "CNPJ"


def test_data_do_fecho_e_letras_duplicadas():
    novas, n = inv.preencher_data_do_fecho([{"content": "Termos em que,\nBarcarena/PA, ."}], date(2026, 10, 1))
    assert n == 1 and novas[0]["content"].endswith("Barcarena/PA, 1º de outubro de 2026.")
    novas, n = inv.sem_letra_duplicada([{"content": "a) a) a condenação\nb) b) o FGTS"}])
    assert n == 2 and novas[0]["content"] == "a) a condenação\nb) o FGTS"


def test_verificacoes_que_bloqueiam():
    assert inv.contas_que_nao_fecham("| R$ 6.121,61 × 475,2 | R$ 2.909.673,75 |")
    assert not inv.contas_que_nao_fecham("| R$ 695,25 × 10 | R$ 6.952,50 |")
    assert inv.sobrevida_impossivel("expectativa de sobrevida aos 61 anos; período de pensionamento estimado em 38,2 anos")
    assert not inv.sobrevida_impossivel("sobrevida aos 40 anos; período de pensionamento estimado em 30 anos")
    assert inv.identificadores_divergentes("NB 732.342.882-4 e depois NB 732.343.882-4") == ["7323428824", "7323438824"]
    assert not inv.identificadores_divergentes("NB 732.342.882-4 e NB 732.342.882-4")
    assert not inv.identificadores_divergentes("NB 732.342.882-4 e outro benefício NB 728.038.320-4")


def test_indenizacao_de_estabilidade_com_contrato_ativo_sai_do_ledger():
    from app import auditoria_estrutural as ae

    plano = {
        "fatos": [{"descricao": "O reclamante segue trabalhando na empresa; o contrato permanece ativo."}],
        "pedidos": [
            {"id": "P01", "tipo": "dano moral", "objeto": "indenização por dano moral"},
            {"id": "P02", "tipo": "estabilidade acidentária", "objeto": "indenização substitutiva da estabilidade provisória"},
            {"id": "P03", "tipo": "declaração de estabilidade", "objeto": "declarar a estabilidade provisória"},
        ],
    }
    secoes = [{"code": "FACTS", "content": "O contrato permanece ativo."}, {"code": "CLAIMS", "content": "a) dano moral"}]
    retirar = ae.pedidos_rescisorios_com_vinculo_ativo(secoes, plano)
    assert [p["id"] for p in retirar] == ["P02"]


def test_nb_andaimes_e_rotulo_de_documento():
    novas, n = inv.normalizar_nb([{"content": "NB 728038320-4 e NB 728.038.320-4"}])
    assert novas[0]["content"] == "NB 728.038.320-4 e NB 728.038.320-4" and n == 1
    novas, n = inv.sem_andaimes_internos([{"content": "O INSS indeferiu (evento-1 do brief) e depois (fato-3). Prova: M023, M029."}])
    assert "brief" not in novas[0]["content"] and "fato-3" not in novas[0]["content"] and "M023" not in novas[0]["content"]
    from app.juridico import tabelas

    assert tabelas.rotulo_documento("Doc 6. CTPS Digital.pdf") == "Documento 6 — CTPS Digital"
    assert tabelas.rotulo_documento("calculado pelo sistema") == "memória de cálculo desta peça"
    assert ".pdf" not in tabelas._rotulos("Doc 10. Declaracao De Afastamentos - Correios.pdf, Doc 11. Contracheques.pdf")


def test_reintegracao_com_vinculo_ativo_bloqueia():
    from app import documento_final as df

    final = [{"code": "FACTS", "content": "O vínculo permanece ativo."}, {"code": "CLAIMS", "content": "requer a reintegração do autor"}]
    assert "REINTEGRACAO_COM_VINCULO_ATIVO" in [v.codigo for v in df.invariantes_numericas_do_documento(final)]
    assert "REINTEGRACAO_COM_VINCULO_ATIVO" not in [v.codigo for v in df.invariantes_numericas_do_documento([{"code": "CLAIMS", "content": "requer a reintegração"}])]
