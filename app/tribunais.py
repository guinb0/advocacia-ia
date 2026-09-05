"""De qual TRT é cada estado — e os vizinhos, para quando o acervo do estado é raro.

A Justiça do Trabalho tem 24 regionais. Cada UF pertence a um TRT (São Paulo a
dois: a capital ao TRT2, o interior ao TRT15). Quando a análise é sobre um estado,
o precedente do PRÓPRIO TRT vale mais — mesma lei aplicada pelo mesmo tribunal.
Faltando amostra ali, cai para os TRTs da MESMA REGIÃO (realidade parecida) e, por
fim, para o país inteiro. É o que `tribunais_por_prioridade` devolve, em camadas.
"""

from __future__ import annotations

#: UF → TRT(s) que a julgam. São Paulo tem dois: capital/metro (TRT2) e interior (TRT15).
UF_PARA_TRT: dict[str, list[str]] = {
    "AC": ["TRT14"], "AL": ["TRT19"], "AM": ["TRT11"], "AP": ["TRT8"],
    "BA": ["TRT5"], "CE": ["TRT7"], "DF": ["TRT10"], "ES": ["TRT17"],
    "GO": ["TRT18"], "MA": ["TRT16"], "MG": ["TRT3"], "MS": ["TRT24"],
    "MT": ["TRT23"], "PA": ["TRT8"], "PB": ["TRT13"], "PE": ["TRT6"],
    "PI": ["TRT22"], "PR": ["TRT9"], "RJ": ["TRT1"], "RN": ["TRT21"],
    "RO": ["TRT14"], "RR": ["TRT11"], "RS": ["TRT4"], "SC": ["TRT12"],
    "SE": ["TRT20"], "SP": ["TRT2", "TRT15"], "TO": ["TRT10"],
}

#: Macrorregião de cada UF — a vizinhança usada como primeiro fallback.
_REGIAO: dict[str, tuple[str, ...]] = {
    "Norte": ("AC", "AP", "AM", "PA", "RO", "RR", "TO"),
    "Nordeste": ("AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"),
    "Centro-Oeste": ("DF", "GO", "MS", "MT"),
    "Sudeste": ("ES", "MG", "RJ", "SP"),
    "Sul": ("PR", "RS", "SC"),
}

UF_PARA_REGIAO: dict[str, str] = {uf: reg for reg, ufs in _REGIAO.items() for uf in ufs}


def normalizar_uf(bruto: object) -> str:
    """Aceita 'sp', 'SP', 'São Paulo'… e devolve a sigla, ou '' se não reconhecer."""
    texto = str(bruto or "").strip().upper()
    if texto in UF_PARA_TRT:
        return texto
    # Nome por extenso → sigla (o essencial; a entrevista guarda a sigla em geral).
    por_nome = {
        "ACRE": "AC", "ALAGOAS": "AL", "AMAPA": "AP", "AMAZONAS": "AM", "BAHIA": "BA",
        "CEARA": "CE", "DISTRITO FEDERAL": "DF", "ESPIRITO SANTO": "ES", "GOIAS": "GO",
        "MARANHAO": "MA", "MATO GROSSO": "MT", "MATO GROSSO DO SUL": "MS", "MINAS GERAIS": "MG",
        "PARA": "PA", "PARAIBA": "PB", "PARANA": "PR", "PERNAMBUCO": "PE", "PIAUI": "PI",
        "RIO DE JANEIRO": "RJ", "RIO GRANDE DO NORTE": "RN", "RIO GRANDE DO SUL": "RS",
        "RONDONIA": "RO", "RORAIMA": "RR", "SANTA CATARINA": "SC", "SAO PAULO": "SP",
        "SERGIPE": "SE", "TOCANTINS": "TO",
    }
    sem_acento = (
        texto.replace("Á", "A").replace("Â", "A").replace("Ã", "A").replace("É", "E")
        .replace("Ê", "E").replace("Í", "I").replace("Ó", "O").replace("Ô", "O").replace("Ú", "U")
    )
    return por_nome.get(sem_acento, "")


def tribunais_por_prioridade(uf: object) -> list[list[str]]:
    """Camadas de TRTs para a busca: o(s) do estado, depois a região, depois país.

    Devolve `[[trts_do_estado], [trts_da_regiao], []]`. A lista vazia final é o
    "sem filtro": o chamador tenta cada camada e para quando tiver amostra
    suficiente. Estado desconhecido devolve só `[[]]` (busca nacional direta).
    """
    sigla = normalizar_uf(uf)
    if not sigla:
        return [[]]
    do_estado = UF_PARA_TRT.get(sigla, [])
    regiao = UF_PARA_REGIAO.get(sigla, "")
    da_regiao: list[str] = []
    for u in _REGIAO.get(regiao, ()):
        for trt in UF_PARA_TRT.get(u, []):
            if trt not in do_estado and trt not in da_regiao:
                da_regiao.append(trt)
    camadas: list[list[str]] = []
    if do_estado:
        camadas.append(do_estado)
    if da_regiao:
        camadas.append(da_regiao)
    camadas.append([])  # nacional, sempre por último
    return camadas
