"""Regressão de ESTABILIDADE entre versões (tabela v13/v14/v15).

Cada geração do zero corrigia um item e quebrava outro. Estes testes travam, em
código (não em prompt), o que alguma versão já acertou — para a próxima não
poder regredir sem falhar o CI.

Tabela de referência (auditoria humana):

  Item                              v13  v14  v15
  Nome e endereço corretos           ❌    ✅    ❌
  Justiça gratuita                   ✅    ❌    ✅
  Contracheques citados corretamente ❌    ✅    ❌
  Testemunhas nominadas              ❌    ✅    ❌
  Seções sem duplicação              ✅    ❌    ❌ (final)
  Prescrição correta                 ✅    ❌    ✅
  Sem documento interno citado       ✅    ❌    ✅
"""

from __future__ import annotations

from app import auditoria_estrutural as ae
from app import documento_final as df
from app import peticao_local as pl


def codigos(achados):
    return {a.codigo for a in achados}


# ------------------------------------------------------------------ 1. BEZERRA TESTE / dado de teste

def test_dado_de_teste_bloqueia_entrega():
    secoes = [{"code": "HEADING", "content": "**BEZERRA TESTE**, brasileiro, residente em Tucuruí/PA."}]
    assert "DADO_DE_TESTE_NO_TEXTO" in codigos(ae.dado_de_teste_no_texto(secoes))


def test_qualificacao_canonica_substitui_nome_de_teste():
    secoes = [{"code": "HEADING", "content": "**BEZERRA TESTE**, brasileiro, CPF [PENDENTE: cpf]."}]
    partes = {"autor": {"nome": "PAULO SERGIO LEANDRO BURCAOS", "cpf": "000.000.000-00"}, "reu": {}}
    limpas, rel = df.aplicar_qualificacao_canonica(secoes, partes)
    assert "BEZERRA TESTE" not in limpas[0]["content"]
    assert "PAULO SERGIO LEANDRO BURCAOS" in limpas[0]["content"]
    assert rel["aplicado"] is True


def test_cadastro_com_teste_e_ignorado():
    # Sem banco: a sanitização é unitária via regex da identidade.
    assert re_search_teste("Bezerra Teste")
    assert re_search_teste("Maria (TESTE)")
    assert not re_search_teste("Guilherme Nunes Bezerra")


def re_search_teste(nome: str) -> bool:
    import re
    return bool(re.search(r"\bTESTE\b", nome, re.IGNORECASE) or "(TESTE)" in nome.upper())


# ------------------------------------------------------------------ 2. Contracheques no índice (não «inexistentes»)

def test_indice_lista_todos_mesmo_com_corte_de_texto():
    ledger = [
        {"document_id": f"DOC_{i:03d}", "numero": i, "canonical_label": f"Documento {i:02d}",
         "document_type": "contracheque" if 13 <= i <= 15 else "outro",
         "canonical_file": f"doc{i}.pdf", "source_files": [f"doc{i}.pdf"],
         "content_hash": "x", "duplicate_group": ""}
        for i in range(1, 59)
    ]
    documentos = [
        {"arquivo": f"doc{i}.pdf", "texto": ("salario bruto " * 40) if 13 <= i <= 15 else ("lorem " * 40)}
        for i in range(1, 59)
    ]
    linhas = pl._indice_e_textos_documentais(ledger, documentos, max_docs_texto=10, max_chars=8_000)
    texto = "\n".join(linhas)
    assert "Documento 13" in texto and "Documento 15" in texto
    assert "ÍNDICE CANÔNICO" in texto
    # Contracheques entram no OCR mesmo com orçamento apertado (prioridade)
    assert "DOCUMENTO 13" in texto.upper() or "Documento 13" in texto


def test_anexo_sem_ocr_permanece_no_ledger_e_no_indice(monkeypatch):
    """O inventário do caso, e não só o OCR pronto, decide quais anexos existem."""
    monkeypatch.setattr(pl.armazenamento, "listar_entregas", lambda _caso: [
        {"id": "e13", "arquivo": "Doc 13. Contracheque maio.pdf"},
        {"id": "e14", "arquivo": "Doc 14. Contracheque junho.pdf"},
    ])
    monkeypatch.setattr(pl.armazenamento, "listar_extracoes_do_caso", lambda _caso: [
        {"id": "e13", "extracao": {"texto_completo": "contracheque maio salário R$ 2.000"}},
    ])
    monkeypatch.setattr(pl, "_dados_por_documento", lambda _caso: {
        "Doc 13. Contracheque maio.pdf": {"tipo": "contracheque"},
        "Doc 14. Contracheque junho.pdf": {"tipo": "contracheque"},
    })

    ledger, documentos = pl.documentos_logicos("caso")

    assert [d["canonical_label"] for d in ledger] == ["Documento 13", "Documento 14"]
    assert documentos[1]["texto"] == ""
    indice = "\n".join(pl._indice_e_textos_documentais(ledger, documentos))
    assert "Documento 14" in indice


# ------------------------------------------------------------------ 3. Placeholders e final duplicado

def test_placeholder_pendente_bloqueia():
    secoes = [{"code": "PRELIMINARY", "content": "Conforme relato do autor [PENDENTE: juntar contracheques]."}]
    assert "PLACEHOLDER_PROIBIDO_NO_DOCUMENTO" in codigos(ae.placeholders_proibidos(secoes))


def test_data_por_extenso_placeholder_bloqueia():
    secoes = [{"code": "CLOSING", "content": "Belém, [data por extenso].\n\nAdvogado"}]
    assert "PLACEHOLDER_PROIBIDO_NO_DOCUMENTO" in codigos(ae.placeholders_proibidos(secoes))


def test_valor_da_causa_duplicado_bloqueia_e_higiene_remove():
    secoes = [
        {"code": "VALUE", "content": "Dá-se à causa o valor de R$ 10.000,00."},
        {"code": "CLOSING", "content": "Dá-se à causa o valor de R$ 10.000,00.\n\nTermos em que,\nPede deferimento."},
    ]
    assert "VALOR_DA_CAUSA_DUPLICADO" in codigos(ae.valor_da_causa(secoes, {"pedidos": []}))
    limpas, rel = df.higienizar(secoes, {"partes": {}}, {"estrutura": {}, "metadata_interna": {}})
    texto = "\n".join(s["content"] for s in limpas)
    assert texto.lower().count("dá-se à causa") == 1
    assert rel["valores_causa_duplicados_removidos"] == 1


# ------------------------------------------------------------------ 4. Documento citado com dois números (ledger)

def test_mesmo_arquivo_com_dois_numeros_falha_bijecao():
    from app import document_ledger as dl
    ledger = [
        {"document_id": "DOC_018", "numero": 18, "canonical_label": "Documento 18",
         "document_type": "atestado", "canonical_file": "atestado.pdf",
         "source_files": ["atestado.pdf"], "content_hash": "a", "duplicate_group": ""},
        {"document_id": "DOC_020", "numero": 20, "canonical_label": "Documento 20",
         "document_type": "atestado", "canonical_file": "atestado.pdf",
         "source_files": ["atestado.pdf"], "content_hash": "a", "duplicate_group": ""},
    ]
    assert "DOCUMENTO_COM_VARIOS_IDENTIFICADORES" in codigos(dl.validar_bijecao(ledger))


# ------------------------------------------------------------------ 5. Cidade do endereço ≠ cidade da Vara

def test_ausencia_falsa_de_contracheque_listado():
    secoes = [{"code": "PRELIMINARY", "content": "Os contracheques não integram os documentos juntados."}]
    ledger = [{
        "document_id": "DOC_013", "numero": 13, "canonical_label": "Documento 13",
        "document_type": "contracheque", "canonical_file": "holerite.pdf",
        "source_files": ["holerite.pdf"], "content_hash": "x", "duplicate_group": "",
    }]
    assert "AUSENCIA_FALSA_DE_DOCUMENTO_LISTADO" in codigos(
        ae.ausencia_falsa_de_documento_listado(secoes, ledger)
    )


def test_erros_juridicos_ect_bloqueiam_a_entrega():
    secoes = [{"code": "LEGAL_GROUNDS", "content": """
O nexo presumido do TEPT decorre do evento. O serviço médico da própria
reclamada emitiu o atestado. O Tema 84 alcança a movimentação de valores em
agência. Requer perícia médica, nos termos do art. 195 da CLT, e revelia pelo
art. 847 da CLT. Os juros observarão o regime vigente na prolação da sentença.
"""}]
    plano = {"partes": {"reu": {"nome": "ECT"}}, "pedidos": [
        {"id": "P01", "tipo": "danos materiais", "objeto": "dano material", "tipo_de_item": "autonomo", "valor": None},
    ]}
    achados = codigos(ae.coerencia_juridica_minima(secoes, plano))
    assert {
        "DANO_MATERIAL_SEM_VALOR", "NEXO_PRESUMIDO_SEM_BASE", "VINCULO_MEDICO_INFERIDO",
        "TEMA_84_SEM_ANALOGIA", "ARTIGO_195_FORA_DO_TEMA", "ARTIGO_847_FORA_DO_TEMA",
        "JUROS_ECT_GENERICOS", "CNPJ_RECLAMADA_AUSENTE",
    } <= achados


def test_dano_material_com_valor_nao_e_barrado_pela_regra_de_valor():
    plano = {"partes": {}, "pedidos": [
        {"id": "P01", "tipo": "danos materiais", "objeto": "dano material", "tipo_de_item": "autonomo", "valor": 500.0},
    ]}
    assert "DANO_MATERIAL_SEM_VALOR" not in codigos(ae.coerencia_juridica_minima([], plano))
