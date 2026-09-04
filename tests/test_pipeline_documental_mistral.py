from __future__ import annotations

import json
from pathlib import Path

from app import documentos_juridicos


FIXTURES = Path(__file__).parent / "fixtures" / "documentos_ouro.json"


def _ocr(texto: str, anotacao: dict | None = None) -> dict:
    return {
        "texto_completo": texto,
        "paginas": [{
            "numero": 1,
            "markdown": texto,
            "confianca": 0.96,
            "blocos": [{"texto": texto, "confianca": 0.96, "bbox": [0, 0, 100, 100]}],
        }],
        "anotacao": anotacao or {},
    }


def test_conjunto_ouro_tem_cobertura_minima():
    casos = json.loads(FIXTURES.read_text(encoding="utf-8"))
    assert {caso["esperado"]["tipo"] for caso in casos} >= {
        "certidao_ocorrencia_policial", "atestado_medico", "cat"
    }


def test_certidao_policial_nao_vira_certidao_civil():
    caso = json.loads(FIXTURES.read_text(encoding="utf-8"))[0]
    ocr = _ocr(caso["texto"], {"tipo_documento": "certidao_nascimento"})
    resultado = documentos_juridicos.classificar(ocr)
    assert resultado["tipo"] == "certidao_ocorrencia_policial"
    assert resultado["conflito"] is True


def test_instituicao_nao_vira_pessoa_e_citacao_inventada_e_rejeitada():
    texto = "SUPERINTENDÊNCIA REGIONAL. Compareceu o senhor Tarzan Sales Galvão."
    ocr = _ocr(texto, {
        "pessoas": [
            {"nome": "SUPERINTENDÊNCIA REGIONAL", "papel": "titular", "citacao": "SUPERINTENDÊNCIA REGIONAL", "pagina": 1},
            {"nome": "Tarzan Sales Galvão", "papel": "declarante", "citacao": "Tarzan Sales Galvão", "pagina": 1},
            {"nome": "Pessoa Inventada", "papel": "vítima", "citacao": "Pessoa que não está no arquivo", "pagina": 1},
        ],
        "organizacoes": [], "campos": [], "eventos": [], "itens_checklist": [],
        "dados_sensiveis": [], "alertas": [],
    })
    extracao = documentos_juridicos.extrair(
        ocr, {"tipo": "certidao_ocorrencia_policial", "rotulo": "Certidão policial"}
    )
    assert [p["nome"] for p in extracao["pessoas"]] == ["Tarzan Sales Galvão"]
    assert "SUPERINTENDÊNCIA REGIONAL" in [o["nome"] for o in extracao["organizacoes"]]
    assert any(r["motivo"] == "citação não encontrada" for r in extracao["recusados"])


def test_validacao_roteia_tipo_confirmado_e_extrai_evidencia_citada():
    texto = (
        "CERTIDÃO DE OCORRÊNCIA POLICIAL. OCORRÊNCIA Nº 2024.0913.080700.0049. "
        "REGISTRO DO HISTÓRICO DE PLANTÃO de 13/09/2024. SUPERINTENDÊNCIA REGIONAL."
    )
    ocr = _ocr(texto, {"campos": [], "pessoas": [], "organizacoes": [], "eventos": [], "itens_checklist": [], "dados_sensiveis": [], "alertas": []})
    classificacao = documentos_juridicos.classificar(ocr)
    extracao = documentos_juridicos.extrair(ocr, classificacao)
    validacao = documentos_juridicos.validar(
        ocr, classificacao, extracao, cliente="",
        checklist=[{"codigo": "DOC.11", "nome": "Boletim de ocorrência", "tipo_ocr": ""}],
        item_escolhido=None,
    )
    evidencias = documentos_juridicos.extrair_evidencias(ocr, extracao, validacao)
    assert validacao["itens_atendidos"] == ["DOC.11"]
    assert validacao["estados"]["arquivo_legivel"] is True
    assert evidencias["quantidade"] >= 2
    assert all(e["citacao"] in texto for e in evidencias["evidencias"])


def test_documento_de_terceiro_nao_vira_erro_e_expoe_o_vinculo():
    """O documento de OUTRA parte é informação, não reprovação.

    Trava a regressão que motivou a mudança: um resumo de alta em nome do filho
    do cliente saía com "o nome não coincide com o cliente do caso" em vermelho,
    na lista de erros — como se o arquivo estivesse errado. Num acidente de
    trabalho o normal é haver vítima, agressor, empregador e perito, todos com
    documento próprio. O nome divergente agora sai como aviso, com o vínculo que
    o DOCUMENTO declara, e nunca em `erros`.
    """
    texto = (
        "HOSPITAL X - RESUMO DE ALTA. Paciente: Hildebrando Almeida de Andrade. "
        "Filho de Maria Aparecida Santos. Diagnóstico: fratura de tíbia."
    )
    ocr = _ocr(texto, {
        "pessoas": [{
            "nome": "Hildebrando Almeida de Andrade",
            "papel": "paciente",
            "relacao_com_cliente": "filho",
            "citacao": "Paciente: Hildebrando Almeida de Andrade",
            "pagina": 1,
        }],
        "organizacoes": [], "campos": [], "eventos": [], "itens_checklist": [],
        "dados_sensiveis": [], "alertas": [],
    })
    classificacao = documentos_juridicos.classificar(ocr)
    extracao = documentos_juridicos.extrair(ocr, classificacao)
    validacao = documentos_juridicos.validar(
        ocr, classificacao, extracao,
        cliente="Maria Aparecida Santos",
        checklist=[{"codigo": "DOC.1", "nome": "Atestado médico", "tipo_ocr": ""}],
        item_escolhido=None,
    )

    assert validacao["pessoa_principal"]["nome"] == "Hildebrando Almeida de Andrade"
    # Nome diferente do cliente: sinalizado, e é ISSO que a tela pinta de amarelo.
    assert validacao["pessoa_principal_confere"] is False
    # O vínculo declarado no documento chega à tela junto do nome.
    assert validacao["pessoa_principal"]["relacao_com_cliente"] == "filho"
    assert validacao["partes"][0]["relacao_com_cliente"] == "filho"
    # E em nenhuma hipótese vira erro: o arquivo não está errado.
    assert not any("coincide" in e or "cliente" in e for e in validacao["erros"])
    assert validacao["divergencias"] == []


def test_vinculo_nao_declarado_fica_vazio_em_vez_de_inventado():
    """Sem o vínculo escrito no documento, o campo fica vazio — quem infere é o parecer.

    A regra de citação literal do pipeline vale aqui igual: um resumo de alta não
    diz de quem o paciente é parente. Preencher isso na leitura do documento seria
    afirmar parentesco sem prova.
    """
    texto = "HOSPITAL X - RESUMO DE ALTA. Paciente: Hildebrando Almeida de Andrade."
    ocr = _ocr(texto, {
        "pessoas": [{
            "nome": "Hildebrando Almeida de Andrade",
            "papel": "paciente",
            "relacao_com_cliente": "",
            "citacao": "Paciente: Hildebrando Almeida de Andrade",
            "pagina": 1,
        }],
        "organizacoes": [], "campos": [], "eventos": [], "itens_checklist": [],
        "dados_sensiveis": [], "alertas": [],
    })
    classificacao = documentos_juridicos.classificar(ocr)
    extracao = documentos_juridicos.extrair(ocr, classificacao)
    validacao = documentos_juridicos.validar(
        ocr, classificacao, extracao, cliente="Maria Aparecida Santos",
        checklist=[{"codigo": "DOC.1", "nome": "Atestado médico", "tipo_ocr": ""}],
        item_escolhido=None,
    )
    assert validacao["pessoa_principal"]["relacao_com_cliente"] == ""


def _ocr_com_campo(texto, campo, valor):
    return _ocr(texto, {
        "campos": [{"campo": campo, "valor": valor, "citacao": texto[:80], "pagina": 1}],
        "pessoas": [], "organizacoes": [], "eventos": [], "itens_checklist": [],
        "dados_sensiveis": [], "alertas": [],
    })


def test_cpf_com_digito_errado_nao_passa_como_valido():
    """O "✓ válido" da tela precisa falar do VALOR, não só da citação.

    Antes de `validators.py` entrar no pipeline Mistral, `valido` vinha de
    `evidencia_verificada` — ou seja, "a citação existe no OCR", que só prova que o
    modelo não inventou o trecho. Um CPF com dígito trocado exibia o mesmo selo
    verde de um CPF correto. O módulo 11 pega isso sem custar chamada.
    """
    texto = "CADASTRO DE PESSOA FISICA. CPF: 111.444.777-00 emitido em 2020."
    ocr = _ocr_com_campo(texto, "cpf", "111.444.777-00")  # DV correto seria 35
    classificacao = documentos_juridicos.classificar(ocr)
    extracao = documentos_juridicos.extrair(ocr, classificacao)
    validacao = documentos_juridicos.validar(
        ocr, classificacao, extracao, cliente="",
        checklist=[{"codigo": "DOC.1", "nome": "CPF", "tipo_ocr": "cpf"}],
        item_escolhido=None,
    )

    assert "cpf" in validacao["campos_invalidos"]
    assert validacao["estados"]["campos_validados"] is False
    assert validacao["dados_utilizaveis"] is False
    assert any("dígito verificador" in m for m in validacao["motivos_revisao"])


def test_cpf_correto_passa_e_nao_gera_ressalva():
    texto = "CADASTRO DE PESSOA FISICA. CPF: 111.444.777-35 emitido em 2020."
    ocr = _ocr_com_campo(texto, "cpf", "111.444.777-35")
    classificacao = documentos_juridicos.classificar(ocr)
    extracao = documentos_juridicos.extrair(ocr, classificacao)
    validacao = documentos_juridicos.validar(
        ocr, classificacao, extracao, cliente="",
        checklist=[{"codigo": "DOC.1", "nome": "CPF", "tipo_ocr": "cpf"}],
        item_escolhido=None,
    )

    assert validacao["campos_invalidos"] == []
    assert extracao["campos"][0]["valido_regra"] is True


def test_campo_sem_regra_nacional_fica_indefinido_e_nao_reprova():
    """Nome não tem dígito verificador — `None`, não `False`.

    Colapsar "não há regra" em "inválido" faria toda certidão com nome de mãe cair
    em revisão humana, que é o oposto de aumentar a assertividade.
    """
    assert documentos_juridicos.conferir_campo("nome_mae", "Maria Aparecida") == (
        None, "Sem regra de verificação automática — confira manualmente."
    )
    assert documentos_juridicos.conferir_campo("cpf", "111.444.777-35")[0] is True
    assert documentos_juridicos.conferir_campo("cpf", "111.444.777-00")[0] is False
    # Campo que ninguém mapeou também não vira reprovação.
    assert documentos_juridicos.conferir_campo("campo_exotico", "x") == (None, "")


def test_nit_do_cnis_usa_o_validador_do_pis():
    """O mesmo número tem nome diferente por documento; o validador é o mesmo."""
    assert documentos_juridicos.conferir_campo("nit", "120.6448.926-8")[0] is True
    assert documentos_juridicos.conferir_campo("pis", "120.6448.926-8")[0] is True
    assert documentos_juridicos.conferir_campo("nit", "120.6448.926-2")[0] is False
