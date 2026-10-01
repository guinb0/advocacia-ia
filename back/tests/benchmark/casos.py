"""Casos sintéticos DIFÍCEIS do motor jurídico, com gabarito. Nomes, números de norma e de precedente são fictícios
(9xxx): o que se mede é o mecanismo — requisito sem prova, defesa sem resposta, conflito de precedentes, linguagem
absoluta em tema controvertido, perícia necessária — e a ausência de falso positivo num caso limpo.

O gabarito é a expectativa jurídica escrita aqui, não a saída do código: se o código mudar e errar, a métrica cai.
"""

from __future__ import annotations

from typing import Any

from app.juridico.autoridades import Autoridade
from app.juridico.fatos import ALEGADO, CONFIRMADO

SUPPORTED = "SUPPORTED"


def fato(id_: str, texto: str, *, estado: str = CONFIRMADO, documento: str = "", contradicoes: list[str] | None = None) -> dict[str, Any]:
    return {"id": id_, "fato": texto, "chave": "", "valor": "", "fonte": documento or "entrevista", "documento": documento,
            "pagina": None, "confianca": 0.9, "estado": estado, "contradicoes": contradicoes or [], "origem": "benchmark"}


def tese(id_: str, nome: str, *, fatos: list[str], decisao: str = SUPPORTED, **extra: Any) -> dict[str, Any]:
    return {"id": id_, "tese": nome, "decisao": decisao, "fatos_que_suportam": fatos, "fatos_necessarios": [], "requisitos": [],
            "proposicoes": [], "base_legal_a_pesquisar": [], "jurisprudencia_a_pesquisar": [], "pedido": extra.pop("pedido", nome),
            "reflexos": [], "exige_pericia": False, **extra}


CASOS: list[dict[str, Any]] = [
    {
        "id": "horas_extras_sem_controle_de_jornada",
        "descricao": "jornada só alegada; contracheques provam o não pagamento; a peça não enfrenta os cartões de ponto",
        "fatos": [
            fato("M001", "contrato de trabalho de 44 horas semanais", documento="CTPS"),
            fato("M002", "trabalhava das 7h às 19h de segunda a sábado", estado=ALEGADO),
            fato("M003", "horas extras nao pagas nos contracheques do periodo", documento="contracheques"),
        ],
        "teses": [tese("I01", "Horas extras habituais", fatos=["M002", "M003"],
                       requisitos=[{"requisito": "jornada contratual", "fatos": ["M001"]}])],
        "peticao": "Das horas extras habituais\n\nO reclamante cumpria jornada das 7h às 19h, de segunda a sábado, muito além da "
                   "jornada contratual de 44 horas semanais, e os contracheques do período não registram o pagamento de horas extras.",
        "gabarito": {
            "requisitos": {"horas_extras.jornada_contratual": "atendido", "horas_extras.jornada_efetiva": "so_alegado",
                           "horas_extras.sem_pagamento": "atendido"},
            "lacunas": ["horas_extras.jornada_efetiva"],
            "vulneraveis": [["I01", "horas_extras.jornada_efetiva"]],
            "respondidas": {"horas_extras.jornada_efetiva": False},
        },
    },
    {
        "id": "assedio_com_data_contraditoria",
        "descricao": "humilhações só relatadas, início com datas conflitantes; atestado prova o abalo",
        "fatos": [
            fato("M001", "gerente humilhava o reclamante frequentemente na frente dos colegas", estado=ALEGADO),
            fato("M002", "atestado medico com diagnostico de ansiedade e abalo psicologico", documento="atestado médico"),
            fato("M003", "humilhacoes reiteradas desde marco de 2023", documento="e-mail", contradicoes=["M004"]),
            fato("M004", "humilhacoes reiteradas desde marco de 2024", estado=ALEGADO, contradicoes=["M003"]),
        ],
        "teses": [tese("I01", "Dano moral por assédio moral", fatos=["M001", "M002", "M003"])],
        "peticao": "Do assédio moral\n\nO gerente humilhava o reclamante na frente dos colegas, o que lhe causou abalo psicológico "
                   "comprovado por atestado médico.",
        "gabarito": {
            # culpa_ou_risco é None: no assédio por preposto a responsabilidade do empregador é objetiva (não é requisito)
            "requisitos": {"assedio_moral.autoria": "so_alegado", "assedio_moral.dano": "atendido",
                           "responsabilidade_civil.dano": "atendido", "responsabilidade_civil.culpa_ou_risco": None},
            "lacunas": ["assedio_moral.autoria", "assedio_moral.condutas_reiteradas", "responsabilidade_civil.conduta",
                        "responsabilidade_civil.nexo"],
            "risco_minimo": {"I01": 0.2},
        },
    },
    {
        "id": "doenca_ocupacional_nexo_so_alegado",
        "descricao": "doença e afastamento documentados, nexo só no relato; perícia indispensável",
        "fatos": [
            fato("M001", "laudo medico com CID de tendinite no ombro direito", documento="laudo médico"),
            fato("M002", "movimentos repetitivos na linha de producao durante toda a jornada", estado=ALEGADO),
            fato("M003", "afastamento pelo INSS por 90 dias", documento="carta de concessão do INSS"),
        ],
        "teses": [tese("I01", "Doença ocupacional (LER/DORT)", fatos=["M001", "M002", "M003"], exige_pericia=True)],
        "peticao": "Da doença ocupacional\n\nO reclamante desenvolveu tendinite no ombro direito, conforme laudo médico, e foi "
                   "afastado pelo INSS por 90 dias.",
        "gabarito": {
            "requisitos": {"doenca_ocupacional.doenca": "atendido", "doenca_ocupacional.nexo_causal": "so_alegado",
                           "doenca_ocupacional.incapacidade": "atendido"},
            "lacunas": ["doenca_ocupacional.nexo_causal"],
            "vulneraveis": [["I01", "doenca_ocupacional.nexo_causal"]],
            "pericia": ["doenca_ocupacional.nexo_causal"],
            "respondidas": {"doenca_ocupacional.nexo_causal": False},
        },
    },
    {
        "id": "intervalo_com_precedentes_em_conflito",
        "descricao": "súmula do tribunal superior contra, regional a favor; a peça chama o tema de pacífico",
        "fatos": [
            fato("M001", "jornada de 8 horas diarias registrada no contrato", documento="contrato de trabalho"),
            fato("M002", "intervalo de almoco de apenas 30 minutos", estado=ALEGADO),
        ],
        "teses": [tese("I01", "Intervalo intrajornada suprimido", fatos=["M001", "M002"], proposicoes=[
            "A supressão parcial do intervalo intrajornada gera o pagamento do período integral",
            "O intervalo mínimo é de uma hora para jornada superior a seis horas",
        ])],
        "autoridades": [
            Autoridade(id="tst:sum:9020", tipo="sumula", chave="", titulo="Súmula 9020 do TST", tribunal="TST", verificada=True,
                       tese="a supressão parcial do intervalo intrajornada gera o pagamento apenas do período suprimido", data="2019-01-01"),
            Autoridade(id="trt:9021", tipo="precedente", chave="", titulo="RO 9021 do TRT-9", tribunal="TRT9", verificada=True,
                       tese="a supressão parcial do intervalo intrajornada gera o pagamento do período integral", data="2016-01-01"),
            Autoridade(id="lei:9022", tipo="artigo", chave="", titulo="art. 9022 da CLT", norma="clt", artigo="9022", verificada=True,
                       texto="o intervalo mínimo é de uma hora para jornada superior a seis horas", vigencia_inicio="1943-11-10"),
        ],
        "classificacao": {"tst:sum:9020": {"P1": "contraria"}, "trt:9021": {"P1": "sustenta"}, "lei:9022": {"P2": "sustenta"}},
        "peticao": "Do intervalo intrajornada suprimido\n\nÉ pacífico que a supressão parcial do intervalo intrajornada gera o "
                   "pagamento do período integral. O intervalo mínimo é de uma hora para jornada superior a seis horas.",
        "gabarito": {
            "certeza": {"I01.P1": "UNSETTLED", "I01.P2": "BINDING"},
            "linguagem_absoluta": ["I01.P1"],
        },
    },
    {
        "id": "rescisao_indireta_fgts_caso_limpo",
        "descricao": "tudo documentado e a peça enfrenta as defesas: não deve haver lacuna nem alerta",
        "fatos": [
            fato("M001", "extrato do FGTS sem depositos desde marco de 2023", documento="extrato FGTS"),
            fato("M002", "admissao em 01/02/2020 com salario de R$ 2.000,00", documento="CTPS"),
            fato("M003", "ausencia de deposito persiste ate hoje, ha mais de 30 meses", documento="extrato FGTS"),
        ],
        "teses": [tese("I01", "Rescisão indireta por ausência de depósitos do FGTS", fatos=["M001", "M002", "M003"])],
        "peticao": "Da rescisão indireta\n\nA ausência de depósitos do FGTS desde março de 2023, que persiste até hoje, é falta grave "
                   "do empregador, grave o bastante para romper o contrato, e atual: não houve perdão tácito, pois a reclamada "
                   "continua inadimplente há mais de 30 meses, conforme o extrato do FGTS.",
        "gabarito": {
            "requisitos": {"rescisao_indireta.falta_grave": "atendido", "rescisao_indireta.atualidade": "atendido",
                           "fgts.depositos_ausentes": "atendido", "fgts.vinculo": "atendido"},
            "lacunas": [],
            "vulneraveis": [],
            "limpo": True,
        },
    },
]
