"""Análise documental pela skill: carga, contrato, proveniência, fluxo, organização e peça.

Sem banco e sem modelo: armazenamento em memória e um "modelo" que devolve JSON fixo.
"""

import io
import shutil

import pytest
from PIL import Image

from app import analise_documental as ad
from app import armazenamento, organizacao_documental as org, peticao_local as pl, skill_de_arquivo as sk

RG = "REGISTRO GERAL 2875340 PAULO SERGIO LEANDRO BURCAOS CPF 152.815.582-34 FILIACAO MARIA"
COMP = "Fatura de agua titular MARIA DAS DORES SILVA Rua das Flores 10 Belem PA vencimento 10/08/2026"
CAT = "CAT numero 54234206 acidente tipico assalto a mao armada CID F43.1 empregado PAULO SERGIO LEANDRO BURCAOS"
LAUDO = "Laudo medico de 12/03/2019 transtorno psiquiatrico F43.1 Dr Fulano CRM 123"

DOCS = [
    {"id": "d1", "arquivo": "rg.pdf", "texto": RG},
    {"id": "d2", "arquivo": "cpf.pdf", "texto": "CADASTRO DE PESSOAS FISICAS 152.815.582-34"},
    {"id": "d3", "arquivo": "comprovante.pdf", "texto": COMP},
    {"id": "d4", "arquivo": "cat.pdf", "texto": CAT},
    {"id": "d5", "arquivo": "laudo.pdf", "texto": LAUDO},
    {"id": "d6", "arquivo": "rg_copia.pdf", "texto": RG},
    {"id": "d7", "arquivo": "foto_borrada.jpg", "texto": ""},
]


def _doc(id_, tipo, nome, pessoal=False, data="", **k):
    base = {"documento_id": id_, "tipo": tipo, "nome_sugerido": nome, "pessoal": pessoal, "data": data, "paginas": 1,
            "dados_principais": [], "pontos_fortes": [], "vulnerabilidades": [], "inconsistencias": [],
            "atualizacao": "NAO_SE_APLICA", "pode_melhorar": None, "legivel": True, "duplicado_de": "", "relacao_com_teses": []}
    base.update(k)
    return base


MODELO = {
    "resumo_do_caso": {"questao_central": "Assalto em serviço", "objetivo_do_cliente": "Indenização", "partes": [], "fatos_cronologicos": []},
    "documentos": [
        _doc("d1", "RG", "RG", True, dados_principais=[{"campo": "CPF", "valor": "152.815.582-34", "citacao": "CPF 152.815.582-34"}]),
        _doc("d2", "CPF", "CPF", True),
        _doc("d3", "Comprovante de residência", "comprovante de residência", True, data="2026-08-10"),
        _doc("d4", "CAT", "CAT", data="2024-12-05"),
        _doc("d5", "Laudo médico", "Laudo Médico", data="2019-03-12", atualizacao="DESATUALIZADO", pode_melhorar=True,
             motivo_atualizacao="laudo de 2019 é velho para a tese"),
        _doc("d6", "RG", "RG", True, duplicado_de="d1"),
        _doc("d7", "Foto", "Foto", legivel=False, problema="borrada"),
    ],
    "fatos_extraidos": [
        {"fato": "Acidente típico com CID F43.1", "documento_id": "d4", "citacao": "acidente tipico assalto a mao armada CID F43.1", "confianca": "alta"},
        {"fato": "Fato inventado", "documento_id": "d4", "citacao": "o gerente confessou tudo", "confianca": "alta"},
    ],
    "inconsistencias": [
        {"titulo": "Comprovante em nome de terceiro", "tipo": "NOME", "impacto": "não comprova residência do cliente",
         "acao_sugerida": "Quem é Maria das Dores?",
         "fontes": [{"documento_id": "d3", "citacao": "titular MARIA DAS DORES SILVA", "valor": "MARIA DAS DORES SILVA"},
                    {"documento_id": "cadastro", "citacao": "cliente: PAULO SERGIO LEANDRO BURCAOS", "valor": "PAULO SERGIO LEANDRO BURCAOS"}]},
        {"titulo": "Uma fonte só", "tipo": "OUTRA", "impacto": "", "fontes": [{"documento_id": "d4", "citacao": "CAT numero 54234206"}]},
    ],
    "provas": [{"fato": "Assalto em serviço", "status": "SUFICIENTE", "documento_ids": ["d4"], "observacao": ""},
               {"fato": "Sem documento", "status": "FRACA", "documento_ids": ["zzz"]}],
    "documentos_faltantes": [
        {"documento": "PPP", "hipotese": "Doença ocupacional", "classificacao": "COMPROMETE",
         "como_obter": "requerer ao empregador (art. 58, §4º, Lei 8.213/91)", "responsavel": "escritório", "prazo_ou_dificuldade": "15 dias"},
        {"documento": "Falta solta", "hipotese": "", "classificacao": "COMPROMETE", "como_obter": ""},
    ],
    "hipoteses_juridicas": [{"hipotese": "Dano moral por assalto", "objeto": "indenização", "fundamento_legal": "art. 927, parágrafo único, CC",
                             "riscos": [{"risco": "prescrição", "nivel": "BAIXO"}], "documento_ids": ["d4"]}],
    "perguntas": [{"pergunta": "Quem é Maria das Dores e qual a relação com o cliente?", "motivo": "titular do comprovante", "fontes": []}],
    "proximos_passos": ["Pedir PPP"],
}


@pytest.fixture()
def caso(monkeypatch, tmp_path):
    store = ad.ArmazenamentoMemoria()
    ad.usar_armazenamento(store)
    monkeypatch.setattr(armazenamento, "obter_caso", lambda c: {"id": c, "cliente": "PAULO SERGIO LEANDRO BURCAOS", "categoria": "x"})
    monkeypatch.setattr(armazenamento, "obter_qualificacao", lambda c: {})
    monkeypatch.setattr(armazenamento, "listar_entrevistas", lambda c: [{"texto": "Fui assaltado na agência em 05/12/2024."}])
    monkeypatch.setattr(armazenamento, "listar_extracoes_do_caso",
                        lambda c: [{"id": d["id"], "arquivo": d["arquivo"], "status_proc": "pronto",
                                    "extracao": {"texto_completo": d["texto"]}} for d in DOCS])
    monkeypatch.setattr(org, "DIR_ORGANIZADO", tmp_path / "organizado")
    yield store
    ad.usar_armazenamento(None)


def _rodar(store, modelo=MODELO):
    chamadas = []

    def falso(mensagem, *, instrucao=None, max_tokens=None):
        chamadas.append((mensagem, instrucao))
        return modelo

    return ad.iniciar("c1", chamar_modelo=falso, store=store, sincrono=True), chamadas


# ------------------------------------------------------------------ skill em tempo de execução
def test_skill_e_carregada_do_disco_com_hash():
    skill = sk.carregar(ad.NOME_DA_SKILL)
    assert skill.frontmatter()["name"] == ad.NOME_DA_SKILL and len(skill.sha256()) == 64
    assert "scripts/montar.py" in skill.arquivos() and "references/nomenclatura.md" in skill.arquivos()


def test_instrucao_vem_da_skill_nao_do_codigo(tmp_path):
    instrucao, resumo = ad.instrucao_da_skill()
    assert "1 documento = 1 arquivo PDF" in instrucao and "COMPROMETE" in instrucao  # texto que só existe no SKILL.md
    assert resumo["skill_sha256"] == sk.carregar(ad.NOME_DA_SKILL).sha256()
    # trocar a skill muda o texto e o hash, sem tocar no código
    copia = tmp_path / "skills"
    shutil.copytree(sk.RAIZ_DAS_SKILLS / ad.NOME_DA_SKILL, copia / ad.NOME_DA_SKILL)
    md = copia / ad.NOME_DA_SKILL / "SKILL.md"
    md.write_text(md.read_text(encoding="utf-8").replace("1 documento = 1 arquivo PDF", "REGRA ALTERADA NO TESTE"), encoding="utf-8")
    alterada = sk.SkillDeArquivo(ad.NOME_DA_SKILL, copia)
    assert alterada.sha256() != sk.carregar(ad.NOME_DA_SKILL).sha256()
    assert "REGRA ALTERADA NO TESTE" in alterada.secao(r"^Regra de ouro")


# ------------------------------------------------------------------ contrato e proveniência
def test_analise_persiste_com_versao_da_skill(caso):
    r, chamadas = _rodar(caso)
    assert r["status"] == "ready" and r["skill_name"] == ad.NOME_DA_SKILL and len(r["skill_sha256"]) == 64
    assert r["versao"] == 1 and r["modelo"] and r["concluida_em"]
    assert "SKILL DOCUMENTAL" in chamadas[0][1] and "documento_id=d4" in chamadas[0][0]


def test_fato_sem_citacao_conferivel_e_descartado_e_o_valido_tem_proveniencia(caso):
    res = _rodar(caso)[0]["resultado"]
    assert [f["fato"] for f in res["fatos_extraidos"]] == ["Acidente típico com CID F43.1"]
    assert res["descartados"]["fatos_sem_proveniencia"] == 1
    prov = res["fatos_extraidos"][0]["proveniencia"]
    assert prov["documento_id"] == "d4" and prov["arquivo"] == "cat.pdf" and prov["tipo_documento"] == "CAT"
    assert "CID F43.1" in prov["citacao"]


def test_divergencia_de_nome_com_duas_fontes_passa_e_uma_fonte_so_e_descartada(caso):
    inc = _rodar(caso)[0]["resultado"]["inconsistencias"]
    assert [i["titulo"] for i in inc] == ["Comprovante em nome de terceiro"]
    assert {f.get("arquivo") or f["origem"] for f in inc[0]["fontes"]} == {"comprovante.pdf", "cadastro"}


def test_divergencia_de_cpf_com_citacao_inventada_nao_passa(caso):
    modelo = dict(MODELO, inconsistencias=[{"titulo": "CPF divergente", "tipo": "CPF", "impacto": "", "acao_sugerida": "",
        "fontes": [{"documento_id": "d1", "citacao": "CPF 111.111.111-11"}, {"documento_id": "d2", "citacao": "152.815.582-34"}]}])
    res = _rodar(caso, modelo)[0]["resultado"]
    assert res["inconsistencias"] == [] and res["descartados"]["inconsistencias_sem_duas_fontes"] == 1


def test_divergencia_de_cpf_real_entre_dois_documentos_passa(caso):
    docs = [dict(d) for d in DOCS]
    docs[1] = {**docs[1], "texto": "CADASTRO DE PESSOAS FISICAS 999.888.777-66"}
    modelo = dict(MODELO, inconsistencias=[{"titulo": "CPF divergente", "tipo": "CPF", "impacto": "i", "acao_sugerida": "a",
        "fontes": [{"documento_id": "d1", "citacao": "CPF 152.815.582-34"}, {"documento_id": "d2", "citacao": "999.888.777-66"}]}])
    res = ad.validar_contrato(modelo, [{"id": d["id"], "arquivo": d["arquivo"], "texto": d["texto"]} for d in docs])
    assert [i["tipo"] for i in res["inconsistencias"]] == ["CPF"]


def test_documento_desatualizado_ilegivel_e_duplicado(caso):
    docs = {d["documento_id"]: d for d in _rodar(caso)[0]["resultado"]["documentos"]}
    assert docs["d5"]["atualizacao"] == "DESATUALIZADO" and docs["d5"]["pode_melhorar"] is True
    assert docs["d7"]["legivel"] is False and docs["d7"]["problema"]
    assert docs["d6"]["duplicado_de"] == "d1"
    assert len(docs) == len(DOCS)  # nenhum documento some


def test_documento_nao_coberto_pelo_modelo_entra_como_nao_identificado(caso):
    modelo = dict(MODELO, documentos=MODELO["documentos"][:2])
    docs = {d["documento_id"]: d for d in _rodar(caso, modelo)[0]["resultado"]["documentos"]}
    assert len(docs) == len(DOCS) and docs["d4"]["tipo"] == "NÃO IDENTIFICADO"


def test_faltante_exige_hipotese_classificacao_e_caminho(caso):
    f = _rodar(caso)[0]["resultado"]["documentos_faltantes"]
    assert [x["documento"] for x in f] == ["PPP"] and f[0]["classificacao"] == "COMPROMETE" and f[0]["hipotese"]


def test_hipotese_relacionada_e_fundamento_nao_verificado(caso):
    h = _rodar(caso)[0]["resultado"]["hipoteses_juridicas"]
    assert h[0]["hipotese"] == "Dano moral por assalto" and h[0]["documento_ids"] == ["d4"]
    assert h[0]["fundamento_verificado"] is False


# ------------------------------------------------------------------ nomes e ordem pelos scripts da skill
def test_rg_frente_e_verso_sao_um_documento_rg_e_cpf_sao_dois_e_duplicado_nao_consome_numero(caso):
    _rodar(caso)
    nomes = [i["nome_final"] for i in org.preparar("c1", store=caso)["plano"]["resumo"]["documentos"]]
    assert nomes[:2] == ["Doc 1. RG.pdf", "Doc 1. RG (Duplicado).pdf"]  # duplicado herda o número
    assert "Doc 2. CPF.pdf" in nomes and "Doc 3. Comprovante De Residência.pdf" in nomes
    assert all(n.startswith("Doc ") and n.endswith(".pdf") for n in nomes)


# ------------------------------------------------------------------ pergunta → resposta → peça
def test_resposta_humana_e_fato_chegam_ao_contexto_da_peca(caso):
    _rodar(caso)
    ctx0 = ad.contexto_para_peticao("c1", store=caso)
    assert "Acidente típico com CID F43.1" in ctx0 and "cat.pdf" in ctx0 and "Dúvidas AINDA SEM RESPOSTA" in ctx0
    ad.responder("c1", "dperg-1", "Maria é a mãe do cliente e mora com ele.", "bia", store=caso)
    ctx1 = ad.contexto_para_peticao("c1", store=caso)
    assert "Maria é a mãe do cliente" in ctx1 and "RESPOSTAS DO ESCRITÓRIO" in ctx1
    assert "Comprovante em nome de terceiro" in ctx1 and "PPP" in ctx1 and "sha256=" in ctx1


def test_contexto_documental_entra_na_geracao_da_peticao(caso, monkeypatch):
    _rodar(caso)
    ad.responder("c1", "dperg-1", "Maria é a mãe do cliente.", "bia", store=caso)
    monkeypatch.setattr(pl, "documentos_ocr", lambda c: [])
    monkeypatch.setattr(pl.case_brief, "montar", lambda c: {})
    monkeypatch.setattr(pl.case_brief, "para_prompt", lambda b: "")
    contexto = pl._montar_contexto("c1", "entrevista")
    assert "ANÁLISE DOCUMENTAL" in contexto and "Acidente típico com CID F43.1" in contexto
    assert "Maria é a mãe do cliente" in contexto


def test_sem_analise_a_peca_segue_como_antes(caso):
    assert ad.contexto_para_peticao("c1", store=caso) == ""


def test_falha_do_modelo_vira_status_error_observavel(caso):
    def quebra(m, **k):
        raise RuntimeError("modelo fora")

    r = ad.iniciar("c1", chamar_modelo=quebra, store=caso, sincrono=True)
    assert r["status"] == "error" and "modelo fora" in r["erro"]


# ------------------------------------------------------------------ organização com parada obrigatória
def _originais(monkeypatch):
    pdf = io.BytesIO()
    Image.new("RGB", (800, 1100), "white").save(pdf, "PDF")
    png = io.BytesIO()
    Image.new("RGB", (800, 1100), "white").save(png, "PNG")
    conteudos = {d["id"]: (pdf.getvalue() if d["arquivo"].endswith(".pdf") else png.getvalue()) for d in DOCS}
    monkeypatch.setattr(org, "_bytes_do_original", lambda eid: (conteudos[eid], next(d["arquivo"] for d in DOCS if d["id"] == eid)))
    return conteudos


def test_organizacao_para_antes_de_gerar_e_so_gera_apos_confirmacao(caso, monkeypatch):
    _originais(monkeypatch)
    _rodar(caso)
    plano = org.preparar("c1", store=caso)
    assert plano["status"] == "aguardando_confirmacao" and not (org.DIR_ORGANIZADO / "c1").exists()
    assert plano["plano"]["resumo"]["duplicados"] and plano["plano"]["resumo"]["problemas"]
    assert "Nenhum documento será excluído" in plano["plano"]["resumo"]["exclusoes"]
    feito = org.confirmar("c1", "bia", store=caso)
    gerados = sorted(p.name for p in (org.DIR_ORGANIZADO / "c1").glob("*.pdf"))
    assert feito["status"] == "concluida" and feito["confirmada_por"] == "bia"
    assert "Doc 1. RG.pdf" in gerados and "Doc 1. RG (Duplicado).pdf" in gerados  # duplicado NÃO foi descartado
    assert "Entrevista.pdf" in gerados and "Checklist.pdf" in gerados
    assert feito["resultado"]["originais_preservados"] is True


def test_confirmar_sem_plano_e_recusado(caso):
    with pytest.raises(ValueError):
        org.confirmar("c1", "bia", store=caso)


# ------------------------------------------------------------------ API: fluxo ponta a ponta
def test_fluxo_pela_api_zip_ocr_analise_revisao_confirmacao_organizacao_continuidade(caso, monkeypatch):
    import time

    from fastapi.testclient import TestClient

    from app import analise_documentos, auth, case_brief_estado, main

    monkeypatch.setattr(auth, "ATIVA", False)  # rotas abertas (sem sessão) neste teste
    monkeypatch.setattr(case_brief_estado, "estados_do_caso", lambda c: {})

    _originais(monkeypatch)
    monkeypatch.setattr(analise_documentos, "_chamar_modelo", lambda mensagem, **k: MODELO)
    cliente = TestClient(main.app)

    inicial = cliente.get("/api/casos/c1/analise-documental")
    assert inicial.json().get("status") == "none", (inicial.status_code, inicial.text[:300])
    assert cliente.post("/api/casos/c1/analise-documental").status_code == 202
    for _ in range(50):  # queued → processing → analyzing → ready
        corpo = cliente.get("/api/casos/c1/analise-documental").json()
        if corpo["status"] in ("ready", "error"):
            break
        time.sleep(0.1)
    assert corpo["status"] == "ready" and corpo["skill_sha256"]
    assert corpo["resultado"]["inconsistencias"][0]["fontes"][0]["citacao"]

    # revisão: responde a pergunta e confirma um fato (estado humano) — o gate da peça enxerga isso
    assert cliente.post("/api/casos/c1/analise-documental/perguntas/dperg-1/resposta", json={"resposta": "É a mãe do cliente."}).status_code == 200
    continuar = cliente.post("/api/casos/c1/analise-documental/continuar").json()
    assert continuar == {"proximo": "peticao", "perguntas_sem_resposta": 0, "contexto_da_peca": True}

    # organização: o plano PARA; só a confirmação gera os PDFs
    plano = cliente.post("/api/casos/c1/organizacao/plano").json()
    assert plano["status"] == "aguardando_confirmacao" and not (org.DIR_ORGANIZADO / "c1").exists()
    feito = cliente.post("/api/casos/c1/organizacao/confirmar").json()
    assert feito["status"] == "concluida" and (org.DIR_ORGANIZADO / "c1" / "Doc 1. RG.pdf").exists()

    # e a peça recebe o que foi apurado e respondido
    monkeypatch.setattr(pl, "documentos_ocr", lambda c: [])
    monkeypatch.setattr(pl.case_brief, "montar", lambda c: {})
    monkeypatch.setattr(pl.case_brief, "para_prompt", lambda b: "")
    contexto = pl._montar_contexto("c1", "entrevista")
    assert "É a mãe do cliente." in contexto and "cat.pdf" in contexto
