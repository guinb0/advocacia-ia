"""As críticas do escritório no fluxo LEGADO (o que roda em produção) e a atualização semanal da CLT.

- memória de cálculo discriminada, montada do ledger, em toda renderização dos pedidos;
- pedido de pagamento sem valor bloqueia e vai ao revisor do ledger (que calcula ou retira);
- verba rescisória com o contrato ativo sai do ledger de forma determinística, com pendência;
- a agenda do Acervo sincroniza a CLT toda semana e garante a primeira carga após o deploy.

Dados fictícios; nada vai à rede, ao banco nem ao pgvector.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

from app import auditor_final, auditoria_estrutural as ae, plano_da_peticao as pp
from app.acervo import agenda
from app.acervo.armazenamento import Memoria

T0 = datetime(2026, 10, 4, 3, tzinfo=UTC)


def _pedido(id_, tipo, objeto, *, valor=None, metodo=None, natureza="cumulativo", tipo_de_item="autonomo", de_praxe=False, tese="T01", **extra):
    return {"id": id_, "tipo": tipo, "objeto": objeto, "fundamento": "", "valor_ou_base": "", "de_praxe": de_praxe, "tese_origem": tese,
            "causa_de_pedir": "", "natureza": natureza, "subsidiario_de": "", "dependencias": [], "valor": valor,
            "metodo_calculo": metodo or {}, "tipo_de_item": tipo_de_item, "agrava": "", "bem_juridico": "", "evento_causador": "",
            "dano": "", "objeto_economico": "", **extra}


def _plano(pedidos, fatos=None, teses=None):
    return {"partes": {"autor": {"nome": "Trabalhadora Fictícia"}, "reu": {"nome": "Comércio Exemplo Ltda"}},
            "fatos": fatos if fatos is not None else [{"id": "F01", "fato": "Admissão em 03/03/2020, salário de R$ 2.000,00 (contracheque)"}],
            "teses": teses if teses is not None else [{"id": "T01", "titulo": "Danos morais por assédio", "pedidos_ids": ["P01"]}],
            "pedidos": pedidos}


def _sem_redacao(itens):
    return {}


# ------------------------------------------------------------------ memória de cálculo do ledger

def test_memoria_de_calculo_sai_do_ledger_com_criterio_conta_e_total_dos_cumulativos():
    pedidos = [
        _pedido("P01", "Danos morais", "indenização por assédio moral", valor=20000.0,
                metodo={"base": 2000, "multiplicador": 10, "resultado": 20000, "criterio": "salário do contracheque de 08/2026"}),
        _pedido("P02", "Horas extras", "horas extras com adicional de 50%", valor=1312.5,
                metodo={"base": 13.125, "multiplicador": 100, "resultado": 1312.5, "criterio": "valor-hora × 100 horas (cartões de ponto)"}),
        _pedido("P03", "Danos morais", "indenização reduzida", valor=10000.0, natureza="subsidiario"),
        _pedido("P04", "Honorários advocatícios", "honorários de 15%", de_praxe=True, tipo_de_item="acessorio"),
    ]
    texto, rel = pp.renderizar_pedidos(_plano(pedidos), _sem_redacao)
    assert rel["memoria_de_calculo"] is True
    assert pp.TITULO_MEMORIA in texto
    assert "| Pedido | Critério e base | Conta | Resultado |" in texto
    assert "| a) Danos morais | salário do contracheque de 08/2026 | R$ 2.000,00 × 10 | R$ 20.000,00 |" in texto
    assert "R$ 13,13 × 100" in texto and "R$ 1.312,50" in texto
    assert "| c) Danos morais (subsidiario) | valor atribuído ao pedido | valor atribuído | R$ 10.000,00 |" in texto
    assert "| Total dos pedidos cumulativos |  |  | R$ 21.312,50 |" in texto, "subsidiário não soma"
    assert "d) honorários" in texto and "| d)" not in texto, "acessório sem valor não entra na memória"
    assert texto.index("d) honorários") < texto.index(pp.TITULO_MEMORIA), "a memória vem depois da lista de pedidos"
    assert "valor da causa" not in texto.split(pp.TITULO_MEMORIA)[1].lower(), "não duplica a linha do valor da causa"


def test_memoria_de_calculo_some_quando_nenhum_pedido_tem_valor_e_nao_quebra_a_tabela():
    texto, rel = pp.renderizar_pedidos(_plano([_pedido("P01", "Anotação na CTPS", "retificação da CTPS")]), _sem_redacao)
    assert rel["memoria_de_calculo"] is False and pp.TITULO_MEMORIA not in texto
    pipe = pp.memoria_de_calculo([_pedido("P01", "Diferenças | salariais", "x", valor=100.0, metodo={"criterio": "base a | b"})])
    linha = next(l for l in pipe.splitlines() if l.startswith("| a)"))
    assert linha.count("|") == 5, linha


def test_memoria_de_calculo_vira_tabela_word_compacta_e_nao_conta_como_pedido():
    from app import peticao_local, petition_linter

    pedidos = [_pedido("P01", "Danos morais", "indenização por assédio moral", valor=20000.0,
                       metodo={"base": 2000, "multiplicador": 10, "resultado": 20000, "criterio": "salário do contracheque"})]
    texto, _ = pp.renderizar_pedidos(_plano(pedidos), _sem_redacao)
    xml = peticao_local._conteudo_com_tabelas_xml(texto, visual={})
    assert xml.count("<w:tbl>") == 1 and "<w:tblHeader/>" in xml
    secoes = [{"code": "CLAIMS", "content": texto}]
    assert petition_linter._itens_de_pedidos(secoes) == [next(l for l in texto.splitlines() if l.startswith("a)"))[3:]]
    codigos = {v.codigo for v in ae.pressupostos_e_atualidade(secoes, _plano(pedidos))}
    assert "MEMORIA_DE_CALCULO_AUSENTE" not in codigos


def test_valor_da_causa_do_legado_e_a_soma_do_ledger_e_nao_soma_a_memoria_de_calculo():
    from app import documento_final

    pedidos = [
        _pedido("P01", "Danos morais", "indenização por assédio moral", valor=20000.0,
                metodo={"base": 2000, "multiplicador": 10, "resultado": 20000, "criterio": "salário do contracheque"}),
        _pedido("P02", "Horas extras", "horas extras com adicional de 50%", valor=1312.5,
                metodo={"base": 13.125, "multiplicador": 100, "resultado": 1312.5, "criterio": "valor-hora × 100 horas"}),
        _pedido("P03", "Danos morais", "indenização reduzida", valor=10000.0, natureza="subsidiario"),
    ]
    plano = _plano(pedidos)
    texto, _ = pp.renderizar_pedidos(plano, _sem_redacao)
    secoes = [{"code": "FACTS", "label": "Dos fatos", "content": "A reclamante foi admitida em 03/03/2020."},
              {"code": "CLAIMS", "label": "Dos pedidos", "content": texto},
              {"code": "CLOSING", "label": "", "content": "Dá-se à causa o valor de R$ 1,00.\n\nNestes termos, pede deferimento."}]
    assert "_juridico_estrito" not in plano and "valor_da_causa_calculado" not in plano
    finais, _ = documento_final.higienizar(secoes, plano, {})
    fecho = next(s["content"] for s in finais if s["code"] == "CLOSING")
    assert "R$ 21.312,50" in fecho, fecho
    assert not any(v.codigo == "VALOR_DA_CAUSA_NAO_FECHA" for v in ae.valor_da_causa(finais, plano))


def test_valor_da_causa_do_legado_sem_valor_no_ledger_nao_e_reescrito():
    from app import documento_final

    plano = _plano([_pedido("P01", "Danos morais", "indenização por assédio")])
    secoes = [{"code": "CLAIMS", "label": "Dos pedidos", "content": "a) indenização de R$ 5.000,00;\nb) multa de R$ 700,00."},
              {"code": "CLOSING", "label": "", "content": "Dá-se à causa o valor de R$ 1,00."}]
    finais, _ = documento_final.higienizar(secoes, plano, {})
    assert "R$ 1,00" in next(s["content"] for s in finais if s["code"] == "CLOSING")


# ------------------------------------------------------------------ pedido de pagamento sem valor

def _plano_sem_valor():
    return _plano([
        _pedido("P01", "Horas extras", "pagamento das horas extras e reflexos"),
        _pedido("P02", "Anotação na CTPS", "retificação da data de admissão"),
        _pedido("P03", "Honorários advocatícios", "honorários de sucumbência", de_praxe=True, tipo_de_item="acessorio"),
        _pedido("P04", "Danos morais", "indenização por assédio", valor=20000.0,
                metodo={"base": 2000, "multiplicador": 10, "resultado": 20000, "criterio": "salário"}),
    ], fatos=[{"id": "F01", "fato": "Dispensada em 05/03/2026; jornada de 10 horas diárias; salário de R$ 2.000,00"}],
        teses=[{"id": "T01", "titulo": "Horas extras", "pedidos_ids": ["P01"]}])


def test_pedido_de_pagamento_sem_valor_bloqueia_no_ledger_e_obrigacao_de_fazer_nao():
    plano = _plano_sem_valor()
    assert [p["id"] for p in ae.pedidos_de_pagamento_sem_valor(plano)] == ["P01"]
    secoes = [{"code": "FACTS", "content": "A reclamante foi dispensada em 05/03/2026."}, {"code": "CLAIMS", "content": "a) horas extras."}]
    achados = [v for v in ae.pressupostos_e_atualidade(secoes, plano) if v.codigo == "PEDIDO_DE_PAGAMENTO_SEM_VALOR"]
    assert len(achados) == 1 and achados[0].bloqueia and achados[0].secao == "LEDGER" and achados[0].trecho.startswith("P01")
    assert "840" in achados[0].motivo


def test_revisor_do_ledger_so_aceita_quando_o_pedido_ganha_valor_sem_perder_os_outros():
    plano = _plano_sem_valor()
    problema = [ae._v("PEDIDO_DE_PAGAMENTO_SEM_VALOR", "LEDGER", "P01", "sem valor", "calcule")]
    corrigido = copy.deepcopy(plano["pedidos"])
    corrigido[0].update(valor=1500.0, metodo_calculo={"base": 15, "multiplicador": 100, "resultado": 1500, "criterio": "valor-hora do contracheque"})
    novos = auditor_final.revisar_ledger(lambda i, e: {"pedidos": corrigido}, plano, problema)
    assert novos and novos[0]["valor"] == 1500.0 and len(novos) == 4

    ainda_sem = copy.deepcopy(plano["pedidos"])
    assert auditor_final.revisar_ledger(lambda i, e: {"pedidos": ainda_sem}, plano, problema) is None
    so_um = [corrigido[0]]
    assert auditor_final.revisar_ledger(lambda i, e: {"pedidos": so_um}, plano, problema) is None, "não pode sumir com o resto do ledger"
    sem_o_iliquido = copy.deepcopy(plano["pedidos"][1:])
    assert auditor_final.revisar_ledger(lambda i, e: {"pedidos": sem_o_iliquido}, plano, problema), "retirar só o pedido sem dado vale"

    entradas = []
    auditor_final.revisar_ledger(lambda i, e: entradas.append((i, e)) or {}, plano, problema)
    assert "a apurar em liquidação" in entradas[0][0] and "jornada de 10 horas" in entradas[0][1], "o revisor recebe os fatos para calcular"


# ------------------------------------------------------------------ verba rescisória com vínculo ativo

def _caso_ativo():
    pedidos = [
        _pedido("P01", "Danos morais", "indenização por assédio moral", valor=20000.0,
                metodo={"base": 2000, "multiplicador": 10, "resultado": 20000, "criterio": "salário do contracheque"}),
        _pedido("P02", "Multa do art. 477 da CLT", "pagamento da multa do art. 477 por atraso nas verbas rescisórias", valor=2000.0, tese="T02"),
        _pedido("P03", "Atraso prolongado", "agravamento", tipo_de_item="agravante", agrava_id="P02", tese="T02"),
        _pedido("P04", "Horas extras", "horas extras com reflexos em aviso prévio e FGTS", valor=1500.0,
                metodo={"base": 15, "multiplicador": 100, "resultado": 1500, "criterio": "cartões de ponto"}, tese="T03"),
    ]
    teses = [{"id": "T01", "titulo": "Assédio moral", "pedidos_ids": ["P01"]},
             {"id": "T02", "titulo": "Multa do art. 477", "pedidos_ids": ["P02", "P03"]},
             {"id": "T03", "titulo": "Horas extras", "pedidos_ids": ["P04"]}]
    fatos = [{"id": "F01", "fato": "A reclamante continua trabalhando para a reclamada"},
             {"id": "F02", "fato": "Salário de R$ 2.000,00 conforme contracheque"}]
    return _plano(pedidos, fatos=fatos, teses=teses)


def _renderizar(secoes, plano):
    texto, _ = pp.renderizar_pedidos(plano, _sem_redacao)
    return [{**s, "content": texto} if s["code"] == "CLAIMS" else s for s in secoes]


def test_vinculo_ativo_retira_verba_rescisoria_do_ledger_sem_depender_do_modelo():
    plano = _caso_ativo()
    secoes = _renderizar([{"code": "FACTS", "content": "A reclamante continua trabalhando para a reclamada."},
                          {"code": "CLAIMS", "content": ""}], plano)
    assert "477" in secoes[1]["content"]
    chamadas = []
    secoes, achados, rel = auditor_final.executar(
        secoes, plano, {}, params={}, verificacoes=lambda s, p: ae.pressupostos_e_atualidade(s, p),
        chamar=lambda i, e: chamadas.append(i) or {}, reescrever=lambda s, o: None, rerenderizar_pedidos=_renderizar, max_iteracoes=2)
    assert [p["id"] for p in plano["pedidos"]] == ["P01", "P02"]
    assert [p["tipo"] for p in plano["pedidos"]] == ["Danos morais", "Horas extras"], "o agravante da multa sai junto; reflexo fica"
    assert [t["pedidos_ids"] for t in plano["teses"]] == [["P01"], [], ["P02"]]
    claims = secoes[1]["content"]
    assert "477" not in claims and "R$ 21.500,00" in claims, "memória refeita sem a multa"
    assert rel["pedidos_retirados"] == ["Multa do art. 477 da CLT"] and rel["liberada"] is True
    assert not [a for a in achados if a.codigo == "VERBA_RESCISORIA_COM_VINCULO_ATIVO"]


def test_rescisao_indireta_ou_contrato_encerrado_mantem_a_verba_rescisoria():
    plano = _caso_ativo()
    secoes = [{"code": "FACTS", "content": "A reclamante continua trabalhando para a reclamada."},
              {"code": "LEGAL_GROUNDS", "content": "Requer-se a rescisão indireta do contrato, nos termos do art. 483 da CLT."}]
    assert ae.pedidos_rescisorios_com_vinculo_ativo(secoes, plano) == []
    plano["fatos"] = [{"id": "F01", "fato": "A reclamante foi dispensada sem justa causa em 05/03/2026 (TRCT)"}]
    assert ae.pedidos_rescisorios_com_vinculo_ativo([{"code": "FACTS", "content": "Dispensada em 05/03/2026."}], plano) == []


def test_pedido_retirado_vira_pendencia_para_o_advogado():
    from app import peticao_local

    pend = peticao_local._pendencias_do_auditor({"pedidos_retirados": ["Multa do art. 477 da CLT"]})
    assert pend and pend[0].startswith("Pedido retirado: «Multa do art. 477 da CLT»") and "contrato ativo" in pend[0]
    assert peticao_local._pendencias_do_auditor(None) == [] and peticao_local._pendencias_do_auditor({}) == []


# ------------------------------------------------------------------ CLT atualizada toda semana

MANIFESTO = ({"id": "cf-1988", "categoria": "legislacao"}, {"id": "clt-1943", "categoria": "legislacao"},
             {"id": "cpc-2015", "categoria": "legislacao"}, {"id": "sumulas", "categoria": "jurisprudencia"})


def test_ronda_automatica_sincroniza_a_clt_por_padrao(monkeypatch):
    monkeypatch.delenv("ACERVO_DOCUMENTOS_AGENDADOS", raising=False)
    assert agenda.documentos_agendados(MANIFESTO) == ["clt-1943"]
    monkeypatch.setenv("ACERVO_DOCUMENTOS_AGENDADOS", "todos")
    assert agenda.documentos_agendados(MANIFESTO) == ["cf-1988", "clt-1943", "cpc-2015"]
    monkeypatch.setenv("ACERVO_DOCUMENTOS_AGENDADOS", "clt-1943, cpc-2015, sumulas, inexistente")
    assert agenda.documentos_agendados(MANIFESTO) == ["clt-1943", "cpc-2015"]
    from app.acervo import sincronizacao
    monkeypatch.delenv("ACERVO_DOCUMENTOS_AGENDADOS", raising=False)
    assert agenda.documentos_agendados() == ["clt-1943"] and sincronizacao.item_do_manifesto("clt-1943")


def _store_com(status, inicio):
    store = Memoria()
    sid = store.abrir_sincronizacao("clt-1943", origem="agendada", solicitado_por="", agora=inicio)
    store.fechar_sincronizacao(sid, {"status": status})
    return store


def test_garantia_sincroniza_o_que_nunca_rodou_venceu_ou_falhou_ha_tempo():
    assert agenda.documentos_atrasados(Memoria(), ["clt-1943"], T0) == ["clt-1943"], "primeira carga após o deploy"
    assert agenda.documentos_atrasados(_store_com("SEM_ALTERACAO", T0 - timedelta(days=3)), ["clt-1943"], T0) == []
    assert agenda.documentos_atrasados(_store_com("ATUALIZADO", T0 - timedelta(days=9)), ["clt-1943"], T0) == ["clt-1943"]
    assert agenda.documentos_atrasados(_store_com("ERRO", T0 - timedelta(hours=1)), ["clt-1943"], T0) == []
    assert agenda.documentos_atrasados(_store_com("ERRO", T0 - timedelta(hours=7)), ["clt-1943"], T0) == ["clt-1943"]
    assert agenda.documentos_atrasados(_store_com("EM_ANDAMENTO", T0 - timedelta(minutes=20)), ["clt-1943"], T0) == []
    assert agenda.documentos_atrasados(_store_com("EM_ANDAMENTO", T0 - timedelta(hours=3)), ["clt-1943"], T0) == ["clt-1943"]
    assert agenda.sincronizada_agora_pouco(_store_com("EM_ANDAMENTO", T0 - timedelta(minutes=20)), "clt-1943", T0)
    assert not agenda.sincronizada_agora_pouco(_store_com("ERRO", T0 - timedelta(minutes=20)), "clt-1943", T0)
    assert not agenda.sincronizada_agora_pouco(Memoria(), "clt-1943", T0)


def test_beat_semanal_e_garantia_de_meia_hora():
    from app.celery_app import celery_app

    agenda_beat = celery_app.conf.beat_schedule
    semanal = agenda_beat[agenda.ENTRADA]["schedule"]
    assert semanal.day_of_week == {0} and semanal.hour == {3} and semanal.minute == {0}
    assert agenda.descricao(semanal) == "semanalmente (domingo) às 03:00 (America/Sao_Paulo)"
    garantia = agenda_beat["acervo-garantir-sincronizacao"]
    assert garantia["task"] == "app.tasks.acervo.garantir_sincronizacao" and float(garantia["schedule"]) == 1800.0
    assert garantia["options"]["queue"] == "low"


def _tarefas(monkeypatch, store, *, embeddings=True):
    from app.acervo import armazenamento, sincronizacao
    from app.tasks import acervo as tarefas

    monkeypatch.setenv("ACERVO_SINCRONIZACAO_ATIVA", "1")
    monkeypatch.delenv("ACERVO_DOCUMENTOS_AGENDADOS", raising=False)
    monkeypatch.setattr(armazenamento, "padrao", lambda: store)
    monkeypatch.setattr(sincronizacao, "embeddings_configurados", lambda: embeddings)
    filas = []
    monkeypatch.setattr(tarefas.sincronizar_documento, "apply_async", lambda args=None, kwargs=None, **kw: filas.append((args, kwargs, kw)))
    monkeypatch.setattr(tarefas.finalizar_ronda, "apply_async", lambda **kw: filas.append(("finalizar", kw)))
    return tarefas, filas


def test_garantia_enfileira_a_primeira_carga_da_clt_e_nao_repete(monkeypatch):
    store = Memoria()
    tarefas, filas = _tarefas(monkeypatch, store)
    assert tarefas.garantir_sincronizacao() == {"executado": True, "enfileirados": ["clt-1943"]}
    assert filas[0] == (["clt-1943"], {"origem": "garantia"}, {"queue": "low"}) and filas[1][0] == "finalizar"
    store.abrir_sincronizacao("clt-1943", origem="garantia", solicitado_por="", agora=datetime.now(UTC))
    filas.clear()
    assert tarefas.garantir_sincronizacao() == {"executado": False, "enfileirados": []} and filas == []


def test_rodada_automatica_nao_roda_sem_embeddings_nem_desligada(monkeypatch):
    tarefas, filas = _tarefas(monkeypatch, Memoria(), embeddings=False)
    assert "EMBEDDINGS" in tarefas.sincronizar_acervo()["motivo"] and "EMBEDDINGS" in tarefas.garantir_sincronizacao()["motivo"]
    monkeypatch.setenv("ACERVO_SINCRONIZACAO_ATIVA", "0")
    assert tarefas.garantir_sincronizacao()["executado"] is False and filas == []


def test_semanal_enfileira_so_a_clt_e_copia_duplicada_nao_roda(monkeypatch):
    store = Memoria()
    tarefas, filas = _tarefas(monkeypatch, store)
    assert tarefas.sincronizar_acervo() == {"executado": True, "enfileirados": ["clt-1943"]}
    assert filas[0][0] == ["clt-1943"] and filas[0][1] == {"origem": "agendada"}
    store.abrir_sincronizacao("clt-1943", origem="agendada", solicitado_por="", agora=datetime.now(UTC))
    rel = tarefas.sincronizar_documento.run("clt-1943", origem="garantia")
    assert rel == {"executado": False, "motivo": "clt-1943 já sincronizada ou em andamento"}


def test_planejador_exige_pedido_liquido_e_veda_rescisoria_com_vinculo_ativo():
    import inspect

    from app import peticao_local

    fonte = inspect.getsource(peticao_local)
    assert "nunca «a apurar em liquidação»" in fonte and "vínculo ativo, não peça" in fonte
