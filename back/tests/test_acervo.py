"""Acervo Jurídico sem banco: sincronização incremental, versionamento, embeddings por hash, encoding,
fonte fora do ar, agenda, parser hierárquico, alertas de skill e o Citation Gate lendo as versões.

Norma FICTÍCIA (Lei 9.999 / 9.998) servida por um `baixar` falso; nada sai para a rede nem para o pgvector.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.acervo import agenda, armazenamento as arm, consulta, encoding, parser, skills, status as st
from app.acervo import sincronizacao as s
from app.juridico import citacao

T0 = datetime(2026, 9, 1, 3, tzinfo=UTC)
V1 = """<html><head><meta charset="utf-8"></head><body>
<p>CAPÍTULO I</p><p>DAS DISPOSIÇÕES GERAIS</p>
<p>Art. 1º Esta lei regula o trabalho em condições especiais.</p>
<p>Art. 2º Considera-se empregador a empresa que assume os riscos da atividade.</p>
<p>§ 1º Equiparam-se ao empregador os profissionais liberais.</p>
<p>Art. 3º Considera-se empregado toda pessoa física que preste serviço.</p>
<p>I - de natureza não eventual;</p><p>II - sob dependência.</p>
<p>Art. 4º O tempo de serviço é contado desde a admissão.</p>
</body></html>"""
V2 = (V1.replace("que assume os riscos da atividade.", "individual ou coletiva, que assume os riscos da atividade.")
        .replace("Art. 4º O tempo de serviço é contado desde a admissão.", "Art. 4º (Revogado pela Lei nº 9.990, de 2026)"))
ITEM = {"id": "teste", "nome": "Lei de Teste", "url": "https://exemplo.invalid/teste", "chave_norma": "lei9999", "categoria": "legislacao"}
OUTRA = {"id": "outra", "nome": "Outra Lei", "url": "https://exemplo.invalid/outra", "chave_norma": "lei9998", "categoria": "legislacao"}


def _baixar(html: str, ct: str = "text/html; charset=utf-8"):
    return lambda url: s.Resposta(html.encode("utf-8"), ct)


def _emb(textos):
    return [[0.1] * 8 for _ in textos]


def _sinc(m, html, dias=0, item=ITEM, **kw):
    kw.setdefault("gerar_embeddings", _emb)
    return s.sincronizar_documento(item, armazenamento=m, baixar=_baixar(html) if isinstance(html, str) else html, agora=T0 + timedelta(days=dias), **kw)


@pytest.fixture(autouse=True)
def _sem_sincronizacao_automatica(monkeypatch):
    monkeypatch.delenv("ACERVO_SINCRONIZACAO_ATIVA", raising=False)


# ------------------------------------------------------------------ encoding / mojibake

def test_encoding_decodifica_declarado_repara_dupla_codificacao_e_recusa_lixo():
    texto = "Art. 1º A ação trabalhista prescreve em dois anos após a extinção do contrato."
    assert encoding.decodificar(texto.encode("cp1252"), "text/html; charset=iso-8859-1") == (texto, "windows-1252")
    assert encoding.decodificar(texto.encode("utf-8"), None)[0] == texto
    dupla = texto.encode("utf-8").decode("cp1252").encode("utf-8")
    reparado, nome = encoding.decodificar(dupla, "text/html; charset=utf-8")
    assert reparado == texto and nome.endswith("+reparo-dupla-codificacao")
    assert encoding.corrompido("aÃ§Ã£o") and not encoding.corrompido(texto)
    with pytest.raises(encoding.ErroEncoding):
        encoding.normalizar("ação e aÃ§Ã£o misturados \ufffd")


def test_mojibake_na_fonte_vira_erro_e_nao_grava_texto_corrompido():
    m = arm.Memoria()
    _sinc(m, V1)
    antes = [dict(v) for v in m.versoes_]
    corrompido = V1.replace("regula", "regula aÃ§Ã£o \ufffd")
    r = _sinc(m, corrompido, dias=1)
    assert r["status"] == st.ERRO and "ENCODING_CORROMPIDO" in r["erro"]
    assert m.versoes_ == antes, "nenhuma versão nova com texto corrompido"
    assert any(a["tipo"] == "ENCODING_CORROMPIDO" for a in m.alertas())


# ------------------------------------------------------------------ versionamento

def test_primeira_carga_e_sincronizacao_sem_mudanca():
    m = arm.Memoria()
    r1 = _sinc(m, V1)
    assert r1["status"] == "ATUALIZADO" and r1["dispositivos_novos"] == r1["dispositivos_total"] > 4
    assert r1["embeddings_gerados"] == 4 and r1["tokens_embeddings_aprox"] > 0
    assert not m.alertas(), "primeira carga não gera alerta de dispositivo incluído"
    r2 = _sinc(m, V1, dias=1)
    assert r2["status"] == "SEM_ALTERACAO" and r2["embeddings_mantidos"] == 4 and r2["embeddings_gerados"] == 0
    assert m.documento("teste")["sync_status"] == st.ATUALIZADO


def test_artigo_alterado_gera_nova_versao_e_revogado_fica_no_historico():
    m = arm.Memoria()
    _sinc(m, V1)
    r = _sinc(m, V2, dias=2)
    assert "art-2" in r["alterados"] and r["revogados"] == ["art-4"]
    art2 = m.versoes("teste", dispositivo_id="art-2")
    assert [(v["version"], v["valid_until"] is None) for v in art2] == [(2, True), (1, False)]
    assert art2[1]["status"] == st.ALTERADA and "individual ou coletiva" in art2[0]["text"]
    assert art2[1]["valid_until"] == (T0 + timedelta(days=2)).date()
    art4 = m.versoes("teste", dispositivo_id="art-4")
    assert art4[0]["status"] == st.REVOGADA and art4[0]["version"] == 2 and "tempo de serviço" in art4[1]["text"]
    tipos = sorted(a["tipo"] for a in m.alertas())
    assert tipos == ["DISPOSITIVO_ALTERADO", "DISPOSITIVO_REVOGADO"]
    det = consulta.dispositivo(m, art4[0]["id"])
    assert det and det["como_o_gate_ve"]


def test_embedding_so_do_que_mudou_invalida_o_antigo_e_mantem_o_resto():
    m = arm.Memoria()
    _sinc(m, V1)
    r = _sinc(m, V2, dias=2)
    assert r["embeddings_gerados"] == 1, "só o art. 2 (alterado) re-embeda"
    assert r["embeddings_mantidos"] == 2, "arts. 1 e 3 ficam com o vetor de antes"
    assert r["embeddings_invalidados"] == 2, "o vetor velho do art. 2 e o do art. 4 (revogado, sai da busca)"
    ativos = sorted(c["metadados"]["dispositivo"] for c in m.chunks("teste") if c["tem_embedding"] and not c.get("invalidado_em"))
    assert ativos == ["art-1", "art-2", "art-3"]


def test_atualizacao_parcial_com_provedor_de_embedding_fora_fica_pendente_e_completa_depois():
    m = arm.Memoria()
    _sinc(m, V1)
    v3 = V1.replace("toda pessoa física", "toda pessoa natural")

    def fora(textos):
        raise RuntimeError("provedor de embeddings fora do ar")
    r = _sinc(m, v3, dias=1, gerar_embeddings=fora)
    assert r["status"] == "ATUALIZADO" and r["embeddings_pendentes"] == 1
    assert m.documento("teste")["sync_status"] == st.PENDENTE
    assert "toda pessoa natural" in m.versoes("teste", dispositivo_id="art-3", atuais=True)[0]["text"], "o texto novo entra mesmo sem vetor"
    assert any(a["tipo"] == "EMBEDDING_FALHOU" for a in m.alertas())
    r2 = _sinc(m, v3, dias=2)
    assert r2["embeddings_gerados"] == 1 and m.documento("teste")["sync_status"] == st.ATUALIZADO


def test_fonte_fora_do_ar_mantem_o_texto_anterior():
    m = arm.Memoria()
    _sinc(m, V1)
    antes = [dict(v) for v in m.versoes_]

    def falha(url):
        raise RuntimeError("timeout ao acessar a fonte oficial")
    r = _sinc(m, falha, dias=1)
    assert r["status"] == st.ERRO and "timeout" in r["erro"]
    assert m.versoes_ == antes
    doc = m.documento("teste")
    assert doc["sync_status"] == st.ERRO and doc["ultimo_erro"]
    assert any(a["tipo"] == "FONTE_INDISPONIVEL" for a in m.alertas())


def test_pagina_truncada_nao_apaga_dispositivos():
    m = arm.Memoria()
    _sinc(m, V1)
    r = _sinc(m, "<p>Art. 1º Só um artigo.</p>", dias=1)
    assert r["status"] == st.ERRO and "PARSER_QUEDA_DE_DISPOSITIVOS" in r["erro"]
    assert len(m.versoes_abertas("teste")) > 4


def test_simulacao_nao_grava():
    m = arm.Memoria()
    _sinc(m, V1)
    antes = len(m.versoes_)
    r = _sinc(m, V2, dias=1, simular=True)
    assert r["status"] == "SIMULADO" and r["alterados"] and len(m.versoes_) == antes


def test_sem_migracao_nao_sincroniza():
    with pytest.raises(arm.MigracaoNaoAplicada):
        _sinc(arm.Memoria(migrada=False), V1)


# ------------------------------------------------------------------ agenda / next_check_at

def test_agenda_desligada_por_padrao_sem_next_check_at():
    assert agenda.ativa() is False and agenda.proxima_execucao(T0, agendamento=3600) is None
    m = arm.Memoria()
    _sinc(m, V1)
    assert m.documento("teste")["next_check_at"] is None


def test_agenda_ligada_calcula_next_check_at(monkeypatch):
    monkeypatch.setenv("ACERVO_SINCRONIZACAO_ATIVA", "1")
    assert agenda.proxima_execucao(T0, agendamento=3600) == T0 + timedelta(hours=1)
    monkeypatch.setattr(agenda, "_agendamento", lambda: 86400)
    m = arm.Memoria()
    _sinc(m, V1)
    assert m.documento("teste")["next_check_at"] == T0 + timedelta(days=1)


def test_tarefa_do_acervo_esta_no_beat():
    from app.celery_app import celery_app
    entrada = (celery_app.conf.beat_schedule or {}).get(agenda.ENTRADA)
    assert entrada and entrada["task"] == agenda.TAREFA
    assert "diariamente" in agenda.descricao(entrada["schedule"]) or agenda.descricao(entrada["schedule"])


# ------------------------------------------------------------------ parser: cabeçalho de estrutura não vaza para o artigo anterior

def test_titulo_de_secao_nao_vaza_para_o_artigo_anterior():
    texto = "\n".join([
        "CAPÍTULO I", "DAS DISPOSIÇÕES GERAIS",
        "Seção I", "Dos Princípios",
        "Art. 4º A assistência social rege-se pelos seguintes princípios fundamentais:",
        "I - supremacia do atendimento às necessidades sociais;",
        "II - universalização dos direitos sociais.",
        "Seção II", "Das Diretrizes",
        "Art. 5º A organização da assistência social tem como base as seguintes diretrizes:",
        "I - descentralização político-administrativa.",
    ])
    nos = {n.dispositivo_id: n for n in parser.arvore(texto, nome_documento="Lei de Teste")}
    art4 = nos["art-4"]
    assert "Diretrizes" not in art4.texto and not art4.texto.rstrip().endswith("Seção II")
    assert any("Diretrizes" in c for c in nos["art-5"].contexto)
    assert any("Princípios" in c for c in art4.contexto)
    inciso = nos["art-4.inc-ii"]
    assert "Seção" not in inciso.texto, "o cabeçalho também não pode grudar no último inciso"


# ------------------------------------------------------------------ alertas de skill: artigo alterado só na norma certa

def test_chaves_alteradas_incluem_a_norma():
    normas = {"teste": "lei9999", "outra": "lei9998"}
    assert skills.chaves_alteradas({("teste", "art-2"), ("teste", "art-3.I"), ("teste", "art-17~2"), ("teste", "cap-1")}, normas) == {
        "art:lei9999:2", "art:lei9999:3", "art:lei9999:17"}
    assert skills.chaves_alteradas({("sem-manifesto", "art-2")}, normas) == set()


def test_skill_que_cita_o_mesmo_artigo_de_outra_lei_nao_recebe_alerta(tmp_path):
    m = arm.Memoria()
    _sinc(m, V1)
    _sinc(m, V1, item=OUTRA)
    r = _sinc(m, V2, dias=2)
    (tmp_path / "skill.md").write_text("Fundamento: art. 2º da Lei 9.999. Ver também o art. 2º da Lei 9.998.", encoding="utf-8")
    alterados = {("teste", d) for d in r["alterados"]}
    gerados = skills.varrer(m, alterados=alterados, raiz=tmp_path, agora=T0 + timedelta(days=2),
                            normas={"teste": "lei9999", "outra": "lei9998"})
    assert [(g["tipo"], g["dados"]["chave"]) for g in gerados] == [("SKILL_CITA_ALTERADA", "art:lei9999:2")]


# ------------------------------------------------------------------ Citation Gate lendo as versões do Acervo

def _registro_do_acervo(dias_da_consulta: int = 3):
    m = arm.Memoria()
    _sinc(m, V1)
    _sinc(m, V2, dias=2)
    return skills.registro(m, {"art:lei9999:2", "art:lei9999:4"}, agora=T0 + timedelta(days=dias_da_consulta))


def test_citation_gate_reprova_artigo_revogado_no_acervo():
    citacao.limpar_cache()
    reg = _registro_do_acervo()
    secoes = [{"code": "LEGAL_GROUNDS", "content": "O tempo de serviço é contado desde a admissão, nos termos do art. 4º da Lei 9.999."}]
    r = citacao.verificar(secoes, reg, date(2026, 9, 4), llm=lambda i, e: {"itens": []})
    assert r["citacoes"][0]["classificacao"] == citacao.SUPERSEDED and not r["citacoes"][0]["aprovada"]
    assert [a["codigo"] for a in r["achados"]] == ["AUTORIDADE_SUPERADA"]


def test_citation_gate_reprova_citacao_que_nao_sustenta_e_aprova_a_que_sustenta():
    citacao.limpar_cache()
    reg = _registro_do_acervo()
    texto = "A empresa individual ou coletiva que assume os riscos da atividade é empregadora, conforme o art. 2º da Lei 9.999."
    secoes = [{"code": "LEGAL_GROUNDS", "content": texto}]
    inventado = lambda i, e: {"itens": [{"id": "C1", "classificacao": "EXACT_SUPPORT", "trecho_oficial": "o empregador responde por tudo sem limite"}]}  # noqa: E731
    r = citacao.verificar(secoes, reg, date(2026, 9, 4), llm=inventado)
    assert r["citacoes"][0]["classificacao"] == citacao.NO_SUPPORT
    assert [a["codigo"] for a in r["achados"]] == ["CITACAO_NAO_SUSTENTA_A_AFIRMACAO"]
    contradiz = lambda i, e: {"itens": [{"id": "C1", "classificacao": "CONTRADICTS", "justificativa": "o texto diz o oposto"}]}  # noqa: E731
    assert [a["codigo"] for a in citacao.verificar(secoes, reg, date(2026, 9, 4), llm=contradiz)["achados"]] == ["CITACAO_CONTRADIZ_A_AFIRMACAO"]
    citacao.limpar_cache()
    ok = lambda i, e: {"itens": [{"id": "C1", "classificacao": "EXACT_SUPPORT", "trecho_oficial": "individual ou coletiva, que assume os riscos da atividade"}]}  # noqa: E731
    r = citacao.verificar(secoes, reg, date(2026, 9, 4), llm=ok)
    assert r["achados"] == [] and r["citacoes"][0]["aprovada"]

    def nao_chama(i, e):
        raise AssertionError("resultado aprovado tem de vir do cache")
    assert citacao.verificar(secoes, reg, date(2026, 9, 4), llm=nao_chama)["citacoes"][0]["cache"] is True


def test_citation_gate_sem_verificador_ou_com_verificacao_vencida_nao_aprova():
    citacao.limpar_cache()
    secoes = [{"code": "LEGAL_GROUNDS", "content": "A empresa que assume os riscos da atividade é empregadora (art. 2º da Lei 9.999)."}]
    r = citacao.verificar(secoes, _registro_do_acervo(), date(2026, 9, 4), llm=None)
    assert [a["codigo"] for a in r["achados"]] == ["SUSTENTACAO_NAO_VERIFICADA"]
    vencido = _registro_do_acervo(dias_da_consulta=st.validade_dias() + 30)
    r = citacao.verificar(secoes, vencido, date(2026, 9, 4), llm=None)
    assert "VIGENCIA_NAO_COMPROVADA" in [a["codigo"] for a in r["achados"]], "versão sem verificação recente não comprova vigência"
