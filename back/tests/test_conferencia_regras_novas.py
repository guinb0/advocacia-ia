"""Regras da conferência que barram os defeitos vistos na petição do caso de teste.

Sem banco: só funções puras de `conferencia_peticao`.
"""

from app import conferencia_peticao as c


def _conferir(secoes, validacoes=None):
    """Pelo caminho público: motor genérico + regras declaradas pela skill."""
    fontes = c.Fontes(anexos=[], numerados=[])
    achados = c.conferir([{"code": k, "content": v} for k, v in secoes.items()], fontes, validacoes)
    return [a for a in achados if a.codigo not in {"MISSING_SECTION", "FACTS_TOO_SHORT", "GROUNDS_TOO_SHORT"}]


def _codigos(violacoes):
    return {v.codigo for v in violacoes}


def test_pedido_declaratorio_com_valor_estimado_inventado_e_barrado():
    claims = (
        "a) Aplicar o sistema do Juízo 100% Digital, pedido declaratório, ao qual se atribui "
        "valor estimado de R$ 1.000,00, correspondente ao custo estimado de deslocamento;\n\n"
        "b) Reconhecer a responsabilidade objetiva da reclamada, ao qual se atribui valor "
        "estimado de R$ 1.000,00, correspondente ao custo estimado de prova;\n\n"
        "c) Condenar a reclamada ao pagamento de indenização por dano moral, no valor de "
        "R$ 50.000,00, arbitrado com base na gravidade do evento;"
    )
    violacoes = _conferir({"CLAIMS": claims})
    inventados = [v for v in violacoes if v.codigo == "VALOR_INVENTADO_EM_PEDIDO_SEM_CONTEUDO_ECONOMICO"]
    assert len(inventados) == 2
    assert all(v.trecho.startswith(("a)", "b)")) for v in inventados)


def test_pedido_declaratorio_sem_valor_nao_e_cobrado():
    claims = (
        "a) Aplicar o sistema do Juízo 100% Digital;\n\n"
        "b) Reconhecer a ocorrência de acidente de trabalho típico;\n\n"
        "c) Requerer a oitiva das testemunhas arroladas;"
    )
    assert "PEDIDO_SEM_VALOR" not in _codigos(_conferir({"CLAIMS": claims}))


def test_valor_pendente_de_documento_ausente_nao_vira_pedido_sem_valor():
    claims = (
        "a) Condenar a reclamada ao ressarcimento das despesas médicas, "
        "[PENDENTE: valor a apurar com os comprovantes de despesas];"
    )
    assert "PEDIDO_SEM_VALOR" not in _codigos(_conferir({"CLAIMS": claims}))


def test_capitulo_de_fragilidade_e_barrado():
    fatos = "I – DA ADMISSÃO\n\nTexto.\n\nVIII – DA DIVERGÊNCIA DOCUMENTAL IRRELEVANTE\n\nHá divergência."
    assert _codigos(_conferir({"FACTS": fatos})) == {"TOPICO_DE_FRAGILIDADE"}
    assert not _conferir({"FACTS": "I – DA ADMISSÃO\n\nTexto."})


def test_marcador_quebrado_ou_aninhado_e_barrado():
    quebrado = "[PENDENTE: juntar comprovantes de despesas serão]"
    aninhado = "com base nos [PENDENTE: juntar base nos comprovantes a serem]"
    assert _codigos(c._marcadores_mal_formados({"CLAIMS": quebrado})) == {"MARCADOR_MAL_FORMADO"}
    assert _codigos(c._marcadores_mal_formados({"CLAIMS": aninhado})) == {"MARCADOR_MAL_FORMADO"}
    assert not c._marcadores_mal_formados(
        {"CLAIMS": "[PENDENTE: comprovantes das despesas médicas]"}
    )


def test_sem_validacoes_na_skill_o_motor_nao_aplica_regra_juridica():
    """Nenhuma regra trabalhista mora no motor: sem `validacoes.md`, nada disso é cobrado."""
    claims = "a) Condenar a reclamada ao pagamento de horas extras;\n\nb) Aplicar o Juízo 100% Digital, valor estimado de R$ 1.000,00;"
    fatos = "VIII – DA DIVERGÊNCIA DOCUMENTAL IRRELEVANTE\n\nHá divergência."
    vazio = {"parametros": {}, "regras": []}
    assert not _codigos(_conferir({"CLAIMS": claims, "FACTS": fatos}, vazio)) & {
        "PEDIDO_SEM_VALOR", "VALOR_INVENTADO_EM_PEDIDO_SEM_CONTEUDO_ECONOMICO", "TOPICO_DE_FRAGILIDADE"}
    # e com as regras da skill, as mesmas peças são barradas
    assert {"PEDIDO_SEM_VALOR", "VALOR_INVENTADO_EM_PEDIDO_SEM_CONTEUDO_ECONOMICO"} <= _codigos(_conferir({"CLAIMS": claims}))


def test_regra_declarada_por_outra_skill_e_executada_sem_mudar_o_motor():
    regra = {"id": "x", "tipo": "padrao_proibido", "secoes": "*", "regex": "proibidona", "codigo": "PROIBIDA",
             "mensagem": "não pode", "correcao": "tire", "bloqueia": True}
    achados = _conferir({"FACTS": "texto com PROIBIDONA aqui"}, {"parametros": {}, "regras": [regra]})
    assert "PROIBIDA" in _codigos(achados)
