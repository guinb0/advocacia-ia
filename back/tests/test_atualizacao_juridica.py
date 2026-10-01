"""Atualização jurídica por tese: pesquisa em fonte oficial vira pendência e alerta (nunca citação), e o Acervo
verificado vai ao prompt com os critérios superados. Sem rede: o pesquisador é falso."""

from __future__ import annotations

import json
from concurrent.futures import Future
from datetime import UTC, date, datetime

from app.acervo.armazenamento import Memoria
from app.juridico import atualizacao as atu
from app.juridico import autoridades as aut

HOJE = date(2026, 10, 1)
URL_STF = "https://noticias.stf.jus.br/postsnoticias/stf-define-criterios-para-concessao-da-justica-gratuita-em-todo-o-judiciario/"
URL_TST = "https://www.tst.jus.br/web/guest/-/tst-aprova-nova-sumula"


def _resposta(achados, fontes):
    return {"resposta": "```json\n" + json.dumps({"achados": achados}, ensure_ascii=False) + "\n```", "fontes": fontes,
            "tem_fonte_oficial": any(f["confianca"] in ("OFICIAL", "TRIBUNAL") for f in fontes)}


def _pesquisador(pergunta: str) -> dict:
    if "gratuita" in pergunta.lower() or "gratuidade" in pergunta.lower():
        return _resposta(
            [{"referencia": "ADC 80 do STF", "tribunal": "STF", "data": "2026-09-03", "efeito": "presunção de insuficiência até R$ 5.000", "url": URL_STF},
             {"referencia": "ADI 9999 do STF", "tribunal": "STF", "data": "2026-08-01", "efeito": "inventado", "url": "https://portal.stf.jus.br/inventado"},
             {"referencia": "Artigo de blog", "tribunal": "", "data": "", "efeito": "x", "url": "https://blogjuridico.com.br/gratuidade"}],
            [{"url": URL_STF, "titulo": "STF define critérios", "confianca": "TRIBUNAL"},
             {"url": "https://blogjuridico.com.br/gratuidade", "titulo": "blog", "confianca": "SECUNDARIA"}])
    if "horas extras" in pergunta.lower():
        return _resposta([{"referencia": "Súmula 999 do TST", "tribunal": "TST", "data": "2026-06-10", "efeito": "novo critério", "url": URL_TST + "/"}],
                         [{"url": URL_TST, "titulo": "TST aprova", "confianca": "TRIBUNAL"}])
    raise RuntimeError("serviço de pesquisa fora do ar")


def _adc80(verificada=False):
    return aut.Autoridade(id="acervo:adc:stf:80", tipo="controle_concentrado", chave="", tribunal="STF", classe="ADC", numero="80",
                          titulo="ADC 80 do STF", texto="Justiça gratuita: presunção de insuficiência para renda até R$ 5.000.",
                          status="vigente", vigencia_inicio="2026-09-03", verificada=verificada, url=URL_STF)


def _tema21(verificada=True):
    return aut.Autoridade(id="acervo:tema:tst:21", tipo="tema", chave="", tribunal="TST", numero="21", titulo="Tema 21 do TST",
                          texto="Justiça gratuita: critério de 40% do teto do RGPS.", status="superado", superado_por="acervo:adc:stf:80",
                          vigencia_inicio="2024-12-16", vigencia_fim="2026-09-02", verificada=verificada)


def test_teses_do_plano_sem_repeticao_e_com_limite():
    plano_est = {"teses": [{"titulo": "Horas extras"}, {"titulo": "horas  extras"}, {"titulo": "Justiça gratuita"}], "pedidos": []}
    assert atu.teses_do_plano(plano_est, {"teses": [{"tese": "Danos morais"}]}) == ["Horas extras", "Justiça gratuita", "Danos morais"]
    assert atu.teses_do_plano(plano_est, None, limite=1) == ["Horas extras"]
    assert atu.teses_do_plano({"teses": [], "pedidos": [{"tipo": "Multa do art. 467"}]}) == ["Multa do art. 467"]


def test_so_achado_com_endereco_oficial_devolvido_pela_busca_vira_candidato():
    registro = aut.Registro([_adc80(verificada=False)])
    r = atu.pesquisar(["Justiça gratuita", "Horas extras", "Danos morais"], HOJE, registro=registro, pesquisador=_pesquisador)
    assert r["executada"]
    por_ref = {c["referencia"]: c for c in r["candidatos"]}
    assert set(por_ref) == {"ADC 80 do STF", "Súmula 999 do TST"}, "link inventado e blog ficam de fora"
    assert r["descartados_sem_fonte_oficial"] == 2
    assert por_ref["ADC 80 do STF"]["chave"] == "adc:stf:80" and por_ref["ADC 80 do STF"]["situacao"] == atu.AGUARDANDO_VERIFICACAO
    assert por_ref["Súmula 999 do TST"]["situacao"] == atu.NOVA and por_ref["Súmula 999 do TST"]["url"] == URL_TST
    assert len(r["pendencias"]) == 2 and all("Não foi citada na peça" in p for p in r["pendencias"])
    falhou = next(t for t in r["teses"] if t["tese"] == "Danos morais")
    assert falhou["falhou"] and "fora do ar" in falhou["motivo"]


def test_autoridade_ja_verificada_nao_vira_pendencia_e_divergencia_com_o_acervo_e_avisada():
    r = atu.pesquisar(["Justiça gratuita"], HOJE, registro=aut.Registro([_adc80(verificada=True)]), pesquisador=_pesquisador)
    assert r["candidatos"][0]["situacao"] == atu.JA_VERIFICADA and r["pendencias"] == []

    def diz_que_tema_21_vale(_):
        return _resposta([{"referencia": "Tema 21 do TST", "tribunal": "TST", "data": "2024-12-16", "efeito": "40% do teto", "url": URL_TST}],
                         [{"url": URL_TST, "confianca": "TRIBUNAL"}])
    r = atu.pesquisar(["Justiça gratuita"], HOJE, registro=aut.Registro([_tema21()]), pesquisador=diz_que_tema_21_vale)
    assert r["candidatos"][0]["situacao"] == atu.ACERVO_DIVERGE and "fora de vigência" in r["pendencias"][0]


def test_sem_busca_concluida_nao_executa_e_diz_o_motivo(monkeypatch):
    r = atu.pesquisar(["Danos morais"], HOJE, pesquisador=_pesquisador)
    assert not r["executada"] and "fora do ar" in r["motivo"] and r["pendencias"] == []
    from app import pesquisa_web
    monkeypatch.setattr(pesquisa_web, "configurada", lambda: False)
    r = atu.pesquisar(["Danos morais"], HOJE)
    assert not r["executada"] and "OPENROUTER_API_KEY" in r["motivo"]
    assert atu.pesquisar([], HOJE, pesquisador=_pesquisador)["motivo"] == "sem teses no plano"


def test_resposta_sem_json_nao_gera_candidato():
    r = atu.pesquisar(["Justiça gratuita"], HOJE, pesquisador=lambda _: {"resposta": "Não encontrei nada.", "fontes": []})
    assert r["executada"] and r["candidatos"] == []


def test_candidatos_viram_alerta_no_acervo_sem_repetir_e_sem_tocar_nas_autoridades():
    store = Memoria()
    r = atu.pesquisar(["Justiça gratuita", "Horas extras"], HOJE, registro=aut.Registro([_adc80()]), pesquisador=_pesquisador)
    agora = datetime(2026, 10, 1, tzinfo=UTC)
    assert atu.registrar_alertas(r["candidatos"], store, agora=agora) == 2
    assert atu.registrar_alertas(r["candidatos"], store, agora=agora) == 0, "alerta aberto não se repete"
    alertas = store.alertas()
    assert {a["tipo"] for a in alertas} == {atu.TIPO_ALERTA}
    assert {a["authority_id"] for a in alertas} == {"candidato:adc:stf:80", "candidato:sumula:tst:999"}
    assert all(a["dados"]["url"].startswith("https://") for a in alertas)
    assert store.autoridades() == [], "candidato não entra em autoridades_juridicas (lá ele passaria no Citation Gate)"

    class Quebrado:
        def alertar(self, *a, **k):
            raise RuntimeError("relation acervo_alertas does not exist")
    assert atu.registrar_alertas(r["candidatos"], Quebrado(), agora=agora) == 0


def test_bloco_verificado_traz_precedente_vigente_e_avisa_criterio_superado():
    registro = aut.Registro([_adc80(verificada=True), _tema21()])
    bloco = atu.bloco_verificado(["Benefício da justiça gratuita"], registro, HOJE)
    assert "ATUALIZAÇÃO JURÍDICA VERIFICADA" in bloco and "ADC 80 do STF" in bloco and URL_STF in bloco
    assert "NÃO USE" in bloco and "Tema 21 do TST — superado; substituído por ADC 80 do STF" in bloco
    nao_verificada = aut.Registro([_adc80(verificada=False)])
    assert atu.bloco_verificado(["Benefício da justiça gratuita"], nao_verificada, HOJE) == ""
    assert atu.bloco_verificado(["Adicional noturno"], registro, HOJE) == ""


def test_peticao_local_integra_a_etapa_sem_bloquear_a_peca(monkeypatch, tmp_path):
    from app import peticao_local
    plano_est = {"teses": [{"titulo": "Benefício da justiça gratuita"}]}

    # A checagem de atualidade não pode ser desligada por ambiente: quando a
    # web estiver indisponível, a geração registra a pendência em vez de fingir
    # que a jurisprudência foi pesquisada.
    monkeypatch.setenv("PETICAO_ATUALIZACAO_JURIDICA", "0")
    monkeypatch.setenv("ACERVO_ARMAZENAMENTO_JSON", str(tmp_path / "acervo.json"))
    monkeypatch.setattr(peticao_local.juridico_repo, "carregar_autoridades", lambda: ([_adc80(verificada=True), _tema21()], ""))
    original = atu.pesquisar
    monkeypatch.setattr(peticao_local.juridico_atualizacao, "pesquisar",
                        lambda teses, data, registro=None: original(teses, data, registro=registro, pesquisador=_pesquisador))
    futuro, bloco = peticao_local._iniciar_atualizacao_juridica(plano_est, None, HOJE)
    assert "ADC 80 do STF" in bloco
    resultado = peticao_local._resultado_da_atualizacao(futuro)
    assert resultado["executada"] and resultado["pendencias"] == [], "ADC 80 já verificada no Acervo"
    assert peticao_local._avisos_de_atualizacao(resultado) == []

    monkeypatch.setattr(peticao_local.juridico_repo, "carregar_autoridades", lambda: (_ for _ in ()).throw(RuntimeError("pgvector fora")))
    futuro, bloco = peticao_local._iniciar_atualizacao_juridica({"teses": [{"titulo": "Horas extras"}]}, None, HOJE)
    resultado = peticao_local._resultado_da_atualizacao(futuro)
    assert bloco == "" and len(resultado["pendencias"]) == 1 and resultado.get("alertas_gravados") == 1
    assert Memoria(tmp_path / "acervo.json").alertas()[0]["authority_id"] == "candidato:sumula:tst:999"

    quebrado: Future = Future()
    quebrado.set_exception(RuntimeError("x"))
    falha = peticao_local._resultado_da_atualizacao(quebrado)
    assert not falha["executada"] and peticao_local._avisos_de_atualizacao(falha)[0].startswith("Atualização jurídica por tese não foi pesquisada")
