"""Painel analítico do caso: o que ele mede e o que ele se recusa a inventar.

Exercita `painel.compor`, que é pura — recebe os registros já lidos e devolve o payload.
Nada de banco e nada de rede: o que precisa de prova aqui é a regra, não a leitura.

    .venv\\Scripts\\python.exe -m tests.test_painel
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import painel  # noqa: E402

falhas = 0

AGORA = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
ABERTURA = AGORA - timedelta(days=10)


def checar(condicao: bool, descricao: str, detalhe: str = "") -> None:
    global falhas
    if condicao:
        print(f"  PASS  {descricao}")
    else:
        falhas += 1
        print(f"  FALHA {descricao}" + (f"\n          {detalhe}" if detalhe else ""))


def iso(instante: datetime) -> str:
    return instante.isoformat()


def caso_base() -> dict:
    return {
        "id": "caso-1",
        "cliente": "Maria da Silva",
        "categoria": "doenca_ocupacional",
        "observacao": "",
        "criado_em": iso(ABERTURA),
        "atualizado_em": iso(ABERTURA + timedelta(hours=2)),
        "portal_criado_em": iso(ABERTURA + timedelta(hours=1)),
        "portal_ativo": True,
    }


def entrega(
    item: str,
    horas: float,
    *,
    utilizaveis: bool = True,
    confere: bool | None = True,
    score: int | None = 90,
    status_proc: str = "pronto",
    erro: str | None = None,
) -> dict:
    return {
        "id": f"entrega-{item}-{horas}",
        "caso_id": "caso-1",
        "item_codigo": item,
        "itens_atendidos": [item],
        "arquivo": f"{item}.jpg",
        "tipo_detectado": "rg",
        "tipo_confere": confere,
        "veredito": "APROVADO" if utilizaveis else "REPROVADO",
        "dados_utilizaveis": utilizaveis,
        "confirmado_manual": False,
        "score_legibilidade": score,
        "status_proc": status_proc,
        "erro_proc": erro,
        "criado_em": iso(ABERTURA + timedelta(hours=horas)),
    }


def situacao(entregues: int, total: int, a_conferir: int = 0, pronto: bool = False) -> dict:
    itens = []
    for numero in range(total):
        codigo = f"DOC.{numero:02d}"
        if numero < entregues:
            estado = "entregue"
        elif numero < entregues + a_conferir:
            estado = "conferir"
        else:
            estado = "pendente"
        itens.append(
            {"codigo": codigo, "nome": f"Documento {numero}", "obrigatorio": True, "status": estado}
        )
    return {
        "categoria": {"codigo": "doenca_ocupacional", "nome": "Doença ocupacional"},
        "itens": itens,
        "progresso": {
            "obrigatorios_total": total,
            "obrigatorios_entregues": entregues,
            "obrigatorios_pendentes": total - entregues - a_conferir,
            "itens_a_conferir": a_conferir,
            "percentual_obrigatorios": round(entregues / total * 100) if total else 100,
            "pronto": pronto,
        },
    }


AGENTE_FORA = {
    "ligado": True,
    "disponivel": False,
    "vinculado": True,
    "motivo": "O agente jurídico não respondeu.",
    "fatos": [],
    "classificacoes": [],
    "pendencias": [],
    "contradicoes": [],
    "pesquisas": [],
    "peticoes": [],
    "estrategia": None,
}


def agente_no_ar(**ajustes) -> dict:
    bloco = {
        "ligado": True,
        "disponivel": True,
        "vinculado": True,
        "motivo": None,
        "fatos": [
            {
                "id": "fato-1",
                "type": "PERSON.CPF",
                "value": {"digits": "12345678900"},
                "status": "EXTRACTED",
                "confidence": 0.98,
                "legal_relevance": "MEDIUM",
                "sources": [{"source_type": "OCR_DOCUMENT", "page": 1, "ocr_field": "cpf"}],
                "created_at": iso(ABERTURA + timedelta(hours=5)),
            },
            {
                "id": "fato-2",
                "type": "EMPLOYMENT.ADMISSION_DATE",
                "value": {"date": "2015-02-03"},
                "status": "ALLEGED",
                "confidence": 1.0,
                "legal_relevance": "HIGH",
                "sources": [{"source_type": "INTERVIEW"}],
                "created_at": iso(ABERTURA + timedelta(hours=5)),
            },
            {
                "id": "fato-3",
                "type": "PERSON.NAME",
                "value": {"full_name": "Maria da Silva"},
                "status": "SUPERSEDED",
                "confidence": 0.7,
                "legal_relevance": "LOW",
                "sources": [{"source_type": "INTERVIEW"}],
                "created_at": iso(ABERTURA + timedelta(hours=5)),
            },
            {
                "id": "fato-4",
                "type": "EMPLOYMENT.MONTHLY_SALARY",
                "value": {"amount": 2850.0, "currency": "BRL"},
                "status": "ALLEGED",
                "confidence": 0.9,
                "legal_relevance": "HIGH",
                "sources": [],
                "created_at": iso(ABERTURA + timedelta(hours=5)),
            },
        ],
        "classificacoes": [
            {
                "code": "LABOR.OCCUPATIONAL_DISEASE",
                "label": "Doença ocupacional",
                "confidence": 0.9,
                "created_at": iso(ABERTURA + timedelta(hours=6)),
            }
        ],
        "pendencias": [
            {
                "id": "m1",
                "code": "DOC.CAT",
                "label": "CAT",
                "kind": "DOCUMENT",
                "severity": "BLOCKING",
                "status": "OPEN",
                "required_by": [],
                "question": None,
                "satisfied_at": None,
            },
            {
                "id": "m2",
                "code": "FACT.SALARY",
                "label": "Salário",
                "kind": "FACT",
                "severity": "RECOMMENDED",
                "status": "SATISFIED",
                "required_by": [],
                "question": None,
                "satisfied_at": iso(ABERTURA + timedelta(hours=7)),
            },
        ],
        "contradicoes": [],
        "pesquisas": [],
        "peticoes": [],
        "estrategia": None,
    }
    bloco.update(ajustes)
    return bloco


def compor(**ajustes):
    argumentos = {
        "caso": caso_base(),
        "situacao": situacao(3, 10),
        "entregas": [entrega("DOC.00", 2), entrega("DOC.01", 4), entrega("DOC.02", 30)],
        "entrevistas": [],
        "assinaturas": [],
        "vinculo": None,
        "agente": AGENTE_FORA,
        "etapas_dossie": [],
        "referencia": {"amostra": 0, "suficiente": False, "motivo": "Sem casos.", "etapas": {}},
        "agora": AGORA,
    }
    argumentos.update(ajustes)
    return painel.compor(**argumentos)


def secao(payload: dict, chave: str):
    return payload[chave]


def main() -> int:
    print("\n== marcos e etapas ==")
    payload = compor()
    etapas = {e["codigo"]: e for e in payload["etapas_medidas"]}
    checar(
        etapas["coleta"]["horas"] is not None and etapas["coleta"]["em_curso"],
        "coleta com obrigatórios faltando conta até agora e se declara em curso",
        str(etapas["coleta"]),
    )
    esperado = round((AGORA - (ABERTURA + timedelta(hours=2))).total_seconds() / 3600, 1)
    checar(
        etapas["coleta"]["horas"] == esperado,
        "coleta em curso mede da primeira entrega até agora",
        f"{etapas['coleta']['horas']} != {esperado}",
    )
    checar(
        etapas["contrato"]["iniciada"] is False and etapas["contrato"]["horas"] is None,
        "etapa sem marco de início sai como não iniciada, e não como zero",
    )
    checar(
        etapas["atendimento"]["em_curso"] and etapas["atendimento"]["fim"] is None,
        "sem entrevista anexada, o atendimento segue em curso — e a tela diz isso",
        str(etapas["atendimento"]),
    )

    pronta = compor(situacao=situacao(10, 10, pronto=True))
    coleta_pronta = next(e for e in pronta["etapas_medidas"] if e["codigo"] == "coleta")
    checar(
        coleta_pronta["em_curso"] is False and coleta_pronta["horas"] == 28.0,
        "checklist completo fecha a coleta na última entrega",
        str(coleta_pronta),
    )

    print("\n== nada é inventado ==")
    campos_ausentes = {a["campo"] for a in payload["ausencias"]}
    checar(
        {"Prioridade", "Prazo e SLA contratado", "Responsável pelo caso"} <= campos_ausentes,
        "prioridade, prazo/SLA e responsável saem declarados como ausentes",
        str(campos_ausentes),
    )
    linhas = {c["codigo"]: c for c in payload["comparacao_historica"]["linhas"]}
    checar(
        all(linha["previsto_horas"] is None and linha["motivo"] for linha in linhas.values()),
        "sem amostra histórica, o previsto é nulo e o motivo vem escrito",
    )
    checar(
        all(i["valor"] is None for i in payload["indicadores"] if i["codigo"] == "pendencias"),
        "agente fora do ar deixa o indicador de pendências nulo, nunca zero",
    )
    pend = payload["pendencias"]
    checar(
        pend["disponivel"] is False and "não respondeu" in str(pend["motivo"]),
        "bloco de pendências carrega o motivo da indisponibilidade",
    )

    print("\n== referência histórica ==")
    referencia = {
        "amostra": 4,
        "suficiente": True,
        "motivo": None,
        "etapas": {
            "coleta": {"mediana_horas": 10.0, "amostra": 4},
            "ciclo": {"mediana_horas": 100.0, "amostra": 4},
            "atendimento": {"mediana_horas": 5.0, "amostra": 2},
        },
    }
    comparado = compor(referencia=referencia)
    linhas = {c["codigo"]: c for c in comparado["comparacao_historica"]["linhas"]}
    checar(
        linhas["coleta"]["previsto_horas"] == 10.0
        and linhas["coleta"]["desvio_percentual"] is not None,
        "etapa com amostra suficiente ganha previsto e desvio",
        str(linhas["coleta"]),
    )
    checar(
        linhas["atendimento"]["previsto_horas"] is None,
        "etapa cuja amostra própria é pequena não recebe referência, mesmo com o total alto",
        str(linhas["atendimento"]),
    )
    ciclo = linhas["ciclo"]
    checar(
        ciclo["desvio_percentual"] is not None
        and any("tempo mediano" in i["texto"] for i in comparado["insights"]),
        "desvio do ciclo vira insight com a base do cálculo",
        str([i["texto"] for i in comparado["insights"]]),
    )

    print("\n== linha do tempo ==")
    com_entrevista = compor(
        entrevistas=[
            {
                "id": "e1",
                "arquivo": "entrevista.txt",
                "entrevistador": "Dra. Helena Prado",
                "fatos_gerados": 11,
                "criado_em": iso(ABERTURA + timedelta(hours=1)),
                "enviada_em": iso(ABERTURA + timedelta(hours=3)),
            }
        ],
        vinculo={
            "caso_ref": "case_X",
            "criado_em": iso(ABERTURA + timedelta(hours=4)),
            "atualizado_em": iso(ABERTURA + timedelta(hours=4)),
            "ultimo_erro": None,
        },
        agente=agente_no_ar(),
    )
    eventos = com_entrevista["eventos"]
    quandos = [e["quando"] for e in eventos]
    checar(quandos == sorted(quandos), "eventos saem em ordem cronológica")
    titulos = [e["titulo"] for e in eventos]
    checar(
        "Entrevista lida pelo agente" in titulos and "Caso enviado ao agente jurídico" in titulos,
        "a linha do tempo junta os dois lados (Acervo e agente)",
        str(titulos),
    )
    fatos_em_lote = [e for e in eventos if e["titulo"] == "Fatos apurados"]
    checar(
        len(fatos_em_lote) == 1 and "4 fato" in fatos_em_lote[0]["detalhe"],
        "fatos extraídos no mesmo minuto viram um evento agrupado",
        str(fatos_em_lote),
    )
    checar(
        com_entrevista["resumo"]["responsaveis"][0]["nome"] == "Dra. Helena Prado",
        "o entrevistador aparece como quem conduziu — o mais perto de responsável que existe",
    )

    print("\n== fatos do caso ==")
    com_agente = compor(agente=agente_no_ar())
    fatos = com_agente["fatos"]
    checar(
        fatos["total"] == 4 and fatos["vigentes"] == 3,
        "fato substituido continua na lista, mas fora da contagem de vigentes",
        str({k: v for k, v in fatos.items() if k != "itens"}),
    )
    checar(
        fatos["apenas_relatados"] == 2,
        "fato relatado sem documento que o sustente e contado a parte",
        str(fatos["por_status"]),
    )
    checar(fatos["sem_origem"] == 1, "fato sem fonte aparece contado, nao escondido")
    checar(
        any(i["origens"] and "gina 1" in i["origens"][0] for i in fatos["itens"]),
        "a proveniencia do fato (documento, pagina, campo) viaja para a tela",
        str([i["origens"] for i in fatos["itens"]]),
    )
    checar(
        any("relato" in i["texto"] for i in com_agente["insights"]),
        "a diferenca entre relatado e comprovado vira insight",
        str([i["texto"] for i in com_agente["insights"]]),
    )
    checar(
        payload["fatos"]["disponivel"] is False and bool(payload["fatos"]["motivo"]),
        "agente fora do ar deixa o bloco de fatos indisponivel com o motivo",
    )

    print("\n== ocorrências ==")
    # DOC.00 foi entregue depois (está entre os três entregues da situação); os
    # problemas em DOC.03/04/05 continuam abertos, porque nenhum item foi atendido.
    com_problema = compor(
        entregas=[
            entrega("DOC.00", 2, utilizaveis=False, score=40),
            entrega("DOC.03", 3, confere=False),
            entrega("DOC.04", 4, utilizaveis=False, score=35),
            entrega("DOC.05", 5, status_proc="erro", erro="arquivo corrompido"),
        ],
        situacao=situacao(3, 10, a_conferir=1),
    )
    ocorrencias = com_problema["ocorrencias"]
    tipos = {o["tipo"] for o in ocorrencias["itens"]}
    checar(
        ocorrencias["abertas"] >= 3 and "documento" in tipos and "checklist" in tipos,
        "arquivo trocado, ilegível e falha de leitura viram ocorrências",
        str(ocorrencias),
    )
    resolvidas = [o for o in ocorrencias["itens"] if o["estado"] == "resolvida"]
    checar(
        any(o["referencia"] == "DOC.00" for o in resolvidas),
        "ocorrência de item que depois foi entregue conta como resolvida, não some do histórico",
        str(ocorrencias["itens"]),
    )

    print("\n== saúde e radar ==")
    saude = com_problema["saude"]
    checar(
        saude["pontuacao"] is not None and all(c["base"] for c in saude["componentes"]),
        "toda componente da saúde publica a fórmula que a produziu",
    )
    sem_agente = {c["codigo"]: c for c in payload["saude"]["componentes"]}
    checar(
        sem_agente["playbook"]["valor"] is None
        and payload["saude"]["peso_medido"] < 100,
        "componente sem dado sai nulo e o peso dele é redistribuído",
        str(payload["saude"]),
    )
    radar_sem_score = compor(
        entregas=[entrega("DOC.00", 2, score=None), entrega("DOC.01", 3, score=None)]
    )["radar"]
    qualidade = next(e for e in radar_sem_score if e["eixo"] == "Qualidade da leitura")
    checar(
        qualidade["valor"] is None,
        "leitura sem nota de legibilidade não vira zero no radar",
        str(qualidade),
    )

    print("\n== insights ==")
    parado = compor(
        caso={**caso_base(), "criado_em": iso(AGORA - timedelta(days=40))},
        entregas=[entrega("DOC.00", -600)],
    )
    textos = [i["texto"] for i in parado["insights"]]
    checar(
        any("Sem movimentações há" in t for t in textos),
        "caso parado gera o insight de inatividade",
        str(textos),
    )
    checar(
        all(i["base"] for i in parado["insights"]),
        "todo insight carrega a base numérica que o sustenta",
    )
    completo = compor(situacao=situacao(10, 10, pronto=True))
    checar(
        any("Checklist obrigatório completo" in i["texto"] for i in completo["insights"]),
        "checklist completo também produz insight — a seção não fica só com o que deu errado",
    )

    print("\n== distribuição do tempo ==")
    distribuicao = com_entrevista["distribuicao_do_tempo"]
    soma = sum(d["percentual"] for d in distribuicao if d["percentual"])
    checar(
        99.0 <= soma <= 101.0,
        "os percentuais das etapas medidas somam 100",
        f"soma={soma}",
    )
    checar(
        all(d["codigo"] != "ciclo" for d in distribuicao),
        "o ciclo total fica fora da distribuição — ele contém as outras etapas",
    )

    print("\n== caso recém-aberto (tela vazia honesta) ==")
    vazio = compor(
        situacao=situacao(0, 10),
        entregas=[],
        agente={"ligado": False, "disponivel": False, "vinculado": False, "motivo": "Não configurado."},
    )
    checar(vazio["eventos"] and len(vazio["eventos"]) >= 1, "caso novo ainda tem a abertura na linha do tempo")
    checar(
        all(d["horas"] for d in vazio["distribuicao_do_tempo"]) is not False,
        "sem etapa medida, a distribuição sai vazia em vez de fatiar o nada",
    )
    checar(
        vazio["saude"]["pontuacao"] is not None,
        "saúde do caso novo continua calculável com os componentes que existem",
    )

    print()
    if falhas:
        print(f"{falhas} FALHA(S)")
    else:
        print("Tudo certo.")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
