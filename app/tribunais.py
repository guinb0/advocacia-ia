"""De qual TRT é cada estado — e os vizinhos, para quando o acervo do estado é raro.

A Justiça do Trabalho tem 24 regionais. Cada UF pertence a um TRT (São Paulo a
dois: a capital ao TRT2, o interior ao TRT15). Quando a análise é sobre um estado,
o precedente do PRÓPRIO TRT vale mais — mesma lei aplicada pelo mesmo tribunal.
Faltando amostra ali, cai para os TRTs da MESMA REGIÃO (realidade parecida) e, por
fim, para o país inteiro. É o que `tribunais_por_prioridade` devolve, em camadas.
"""

from __future__ import annotations

import re

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


# --------------------------------------------------- abrir o processo no PJe
#
# O advogado quer ABRIR o processo que a jurimetria usou como base, e até aqui a
# tela mostrava só o número. O campo `url` existe de ponta a ponta (coluna
# `fontes.url` no pgvector, `referencia()` em `app/rag.py`, o tipo no frontend),
# mas está vazio: medido no acervo, 7566 fontes e 2 com url — as duas de consulta
# de CNPJ, nenhuma de processo. O coletor do DJEN não guarda link porque a API de
# comunicações não devolve um.
#
# Então o link é DERIVADO do número, que é o que o padrão CNJ permite fazer sem
# adivinhar nada: `NNNNNNN-DD.AAAA.J.TR.OOOO`, onde `J` é o segmento da Justiça,
# `TR` o tribunal e `OOOO` a unidade de origem. Com isso monta-se a consulta
# processual pública do PJe do PRÓPRIO regional.
#
# Conferido contra os tribunais de verdade antes de entrar na tela: TRT8 (1º e 2º
# grau) e TRT2 responderam 200 no caminho abaixo; o TRT1 devolve 403 para `curl`,
# que é proteção anti-robô e não ausência da página — do navegador do advogado,
# com sessão e user-agent normais, abre.

#: Só Justiça do Trabalho. O acervo é trabalhista, e montar link de outro segmento
#: seria mandar o advogado para um endereço que ninguém verificou.
_SEGMENTO_TRABALHO = "5"

#: `0000` na unidade de origem é o próprio tribunal — processo de 2º grau.
_UNIDADE_DO_TRIBUNAL = "0000"


def partes_do_numero_cnj(bruto: object) -> tuple[str, str, str, str, str, str] | None:
    """Os seis campos do número CNJ, ou `None` se não for um número CNJ.

    Aceita com ou sem pontuação: no acervo ele vem cru (`00009437220255080105`),
    e na petição aparece formatado.
    """
    digitos = re.sub(r"\D", "", str(bruto or ""))
    if len(digitos) != 20:
        return None
    return (
        digitos[0:7],    # sequencial
        digitos[7:9],    # dígito verificador
        digitos[9:13],   # ano
        digitos[13:14],  # segmento da Justiça
        digitos[14:16],  # tribunal
        digitos[16:20],  # unidade de origem
    )


def numero_processo_formatado(bruto: object) -> str:
    """`00009437220255080105` → `0000943-72.2025.5.08.0105`.

    O número cru tem 20 dígitos seguidos, e é assim que ele estava indo para a
    tela e para o texto da peça. Advogado não lê processo nesse formato, e
    conferir contra o PJe exige a pontuação.
    """
    partes = partes_do_numero_cnj(bruto)
    if partes is None:
        return str(bruto or "")
    sequencial, dv, ano, segmento, tribunal, unidade = partes
    return f"{sequencial}-{dv}.{ano}.{segmento}.{tribunal}.{unidade}"


def link_do_processo(bruto: object) -> str:
    """A consulta processual pública do PJe daquele TRT, ou "" quando não dá.

    Devolve vazio — e a tela não desenha link — quando o número não é CNJ, quando
    não é da Justiça do Trabalho, ou quando o regional está fora da faixa 1–24.
    Link errado é pior que link ausente: manda o advogado conferir no lugar errado.
    """
    partes = partes_do_numero_cnj(bruto)
    if partes is None:
        return ""
    sequencial, dv, ano, segmento, tribunal, unidade = partes
    if segmento != _SEGMENTO_TRABALHO:
        return ""
    try:
        regional = int(tribunal)
    except ValueError:
        return ""
    if not 1 <= regional <= 24:
        return ""
    grau = "2" if unidade == _UNIDADE_DO_TRIBUNAL else "1"
    formatado = f"{sequencial}-{dv}.{ano}.{segmento}.{tribunal}.{unidade}"
    return (
        f"https://pje.trt{regional}.jus.br/consultaprocessual/detalhe-processo/"
        f"{formatado}/{grau}"
    )


def tribunal_do_processo(bruto: object) -> str:
    """`TRT8` a partir do número, para a tela dizer para onde o link vai."""
    partes = partes_do_numero_cnj(bruto)
    if partes is None or partes[3] != _SEGMENTO_TRABALHO:
        return ""
    try:
        regional = int(partes[4])
    except ValueError:
        return ""
    return f"TRT{regional}" if 1 <= regional <= 24 else ""
