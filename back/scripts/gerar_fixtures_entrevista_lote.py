"""Gera 50 TXT de entrevista + entradas em esperado.json (não sobrescreve 01–06)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "entrevistas"
FUNCOES = [
    "Atendente",
    "OTT",
    "Carteiro motorizado",
    "Carteiro pedestre",
    "Carteiro motociclista",
    "Carteiro ciclista",
]


def _txt(linhas: list[str]) -> str:
    return "\n".join(linhas).rstrip() + "\n"


def caso_base(
    *,
    nome: str,
    funcao: str,
    tempo: str,
    ainda: str,
    rastreio: dict[str, str],
    extras: list[str] | None = None,
) -> str:
    linhas = [
        "Entrevistador: Bom dia. Qual a sua função?",
        f"Entrevistado: {funcao}.",
        "Entrevistador: Há quanto tempo trabalha nos Correios?",
        f"Entrevistado: {tempo}.",
        "Entrevistador: Ainda trabalha na empresa?",
        f"Entrevistado: {ainda}.",
        "Entrevistador: Foi vítima de assalto durante o trabalho?",
        f"Entrevistado: {rastreio['r_assalto']}.",
        "Entrevistador: Sofreu algum acidente de trabalho?",
        f"Entrevistado: {rastreio['r_acidente']}.",
        "Entrevistador: Desenvolveu alguma doença em razão do trabalho?",
        f"Entrevistado: {rastreio['r_doenca']}.",
        "Entrevistador: Sofreu acidente fora do trabalho que deixou sequela permanente?",
        f"Entrevistado: {rastreio['r_sequela']}.",
        "Entrevistador: Já entrou com ação judicial contra os Correios sobre esses assuntos?",
        f"Entrevistado: {rastreio['r_acao']}.",
    ]
    if extras:
        linhas.extend(extras)
    return _txt(linhas)


def main() -> None:
    FIX.mkdir(parents=True, exist_ok=True)
    ouro_path = FIX / "esperado.json"
    ouro = json.loads(ouro_path.read_text(encoding="utf-8")) if ouro_path.is_file() else {}

    cenarios: list[dict] = []

    # --- 07–16: só rastreio limpo (funções e desligamentos variados) ---
    limpos = [
        ("07_limpo_atendente", "Atendente", "dois anos", "Sim, ainda trabalho", "não"),
        ("08_limpo_ott", "OTT", "onze anos", "Sim", "não"),
        ("09_limpo_motorizado", "Carteiro motorizado", "seis anos", "Ainda trabalho", "não"),
        ("10_limpo_pedestre", "Carteiro pedestre", "um ano e meio", "Sim", "não"),
        ("11_limpo_moto", "Carteiro motociclista", "nove anos", "Sim, continuo", "não"),
        ("12_limpo_bike", "Carteiro ciclista", "quatro anos", "Sim", "não"),
        ("13_demitido_sem_fato", "Atendente", "três anos", "Fui demitido em março de 2025", "não"),
        ("14_acordo_sem_fato", "OTT", "oito anos", "Pedi demissão por acordo em 2024", "não"),
        ("15_aposentado_sem_fato", "Carteiro pedestre", "trinta anos", "Aposentei em 2023", "não"),
        ("16_outra_funcao", "Outra", "cinco anos", "Sim, ainda estou", "não"),
    ]
    for key, funcao, tempo, ainda, neg in limpos:
        r = {k: neg for k in ("r_assalto", "r_acidente", "r_doenca", "r_sequela", "r_acao")}
        # "Outra" is escolha option
        f_escolha = funcao if funcao != "Outra" else "Outra"
        cenarios.append(
            {
                "id": key,
                "txt": caso_base(
                    nome=key,
                    funcao=f_escolha if f_escolha != "Outra" else "Sou auxiliar de agência, Outra",
                    tempo=tempo,
                    ainda=ainda,
                    rastreio={k: "Não" for k in r},
                ),
                "iniciais": {"nome": f"Cliente {key.split('_')[0]}", "cpf": "529.982.247-25", "uf": "SP", "municipio": "Campinas"},
                "esperadas": {"funcao": f_escolha if f_escolha != "Outra" else "Outra", **{k: "não" for k in r}},
                "contem": {
                    "tempo_casa": [tempo.split()[0]],
                },
            }
        )
        if "demit" in ainda.casefold():
            cenarios[-1]["contem"]["desligamento"] = ["demit"]
        elif "acordo" in ainda.casefold():
            cenarios[-1]["contem"]["desligamento"] = ["acordo", "demissão", "pedi"]
        elif "aposent" in ainda.casefold():
            cenarios[-1]["contem"]["desligamento"] = ["aposent"]
        else:
            cenarios[-1]["contem"]["desligamento"] = ["ainda", "sim", "continu", "estou"]

    # --- 17–26: assalto na jornada ---
    for i, (ano, vezes, sintomas, cat, inss) in enumerate(
        [
            ("2023", "uma vez", "ansiedade e insônia", "Sim", "Não"),
            ("2024", "duas vezes", "pânico e medo de sair", "Sim", "Sim, três meses"),
            ("2022", "três vezes", "depressão", "Não", "Não"),
            ("2025", "uma vez", "TEPT e não durmo", "Sim", "Não"),
            ("2021", "duas vezes", "ansiedade", "Não", "Sim"),
            ("2024", "uma vez", "insônia", "Sim", "Não"),
            ("2023", "uma vez", "medo e ansiedade", "Sim", "Não"),
            ("2020", "duas vezes", "pânico", "Sim", "Não"),
            ("2024", "uma vez", "ansiedade", "Não", "Não"),
            ("2023", "quatro vezes", "insônia e depressão", "Sim", "Sim"),
        ],
        start=17,
    ):
        key = f"{i:02d}_assalto_jornada"
        funcao = FUNCOES[(i - 17) % len(FUNCOES)]
        extras = [
            "Entrevistador: Quantas vezes e em que anos?",
            f"Entrevistado: Fui assaltado {vezes} em {ano}, na rota de entrega.",
            "Entrevistador: Ocorreu durante a jornada?",
            "Entrevistado: Sim, eu estava trabalhando na entrega.",
            "Entrevistador: Tem acesso às CATs?",
            f"Entrevistado: {cat}.",
            "Entrevistador: Passou a ter sintomas depois?",
            f"Entrevistado: Sim, {sintomas}.",
            "Entrevistador: Procurou atendimento psicológico?",
            "Entrevistado: Sim.",
            "Entrevistador: Afastado pelo INSS por causa do assalto?",
            f"Entrevistado: {inss}.",
            "Entrevistador: Existem testemunhas?",
            "Entrevistado: Sim, um colega de rota.",
        ]
        r = {
            "r_assalto": "sim",
            "r_acidente": "não",
            "r_doenca": "não",
            "r_sequela": "não",
            "r_acao": "não",
            "as_jornada": "sim",
            "as_cat": "sim" if cat.lower().startswith("sim") else "não",
            "as_atendimento": "sim",
            "as_testemunhas": "sim",
            "as_inss": "sim" if inss.lower().startswith("sim") else "não",
        }
        cenarios.append(
            {
                "id": key,
                "txt": caso_base(
                    nome=key,
                    funcao=funcao,
                    tempo=f"{(i % 9) + 2} anos",
                    ainda="Sim, ainda trabalho",
                    rastreio={
                        "r_assalto": "Sim",
                        "r_acidente": "Não",
                        "r_doenca": "Não",
                        "r_sequela": "Não",
                        "r_acao": "Não",
                    },
                    extras=extras,
                ),
                "iniciais": {"nome": f"Assaltado {i}", "cpf": "111.444.777-35", "uf": "RJ", "municipio": "Niterói"},
                "esperadas": {"funcao": funcao, **r},
                "contem": {
                    "as_ocorrencias": [vezes.split()[0], ano],
                    "desligamento": ["ainda", "sim"],
                },
            }
        )
        pistas = []
        low = sintomas.casefold()
        for p in ("ansiedade", "insônia", "insonia", "pânico", "panico", "depressão", "depressao", "medo", "tept", "durmo", "dormir", "insôn"):
            if p in low:
                pistas.append(p)
        if not pistas:
            pistas = [sintomas.split()[0]]
        cenarios[-1]["contem"]["as_sintomas"] = pistas

    # --- 27–31: assalto FORA da jornada → r_assalto não ---
    for i, detalhe in enumerate(
        [
            "Sofri assalto no shopping no domingo, de folga. Não foi no trabalho.",
            "Assaltaram minha esposa. Eu não fui vítima no trabalho.",
            "Fui assaltado voltando pra casa, já fora da jornada. Não conta como trabalho.",
            "Tinha uniforme, mas estava de folga no mercado. Não foi durante o trabalho.",
            "Nunca fui assaltado no trabalho. Só um furto de celular em casa.",
        ],
        start=27,
    ):
        key = f"{i:02d}_assalto_fora"
        cenarios.append(
            {
                "id": key,
                "txt": caso_base(
                    nome=key,
                    funcao=FUNCOES[i % len(FUNCOES)],
                    tempo="sete anos",
                    ainda="Sim",
                    rastreio={
                        "r_assalto": f"Não. {detalhe}",
                        "r_acidente": "Não",
                        "r_doenca": "Não",
                        "r_sequela": "Não",
                        "r_acao": "Não",
                    },
                    extras=[
                        "Entrevistador: O assalto foi na jornada de trabalho?",
                        "Entrevistado: Não.",
                    ],
                ),
                "iniciais": {"nome": f"Fora {i}", "cpf": "390.533.447-05", "uf": "MG", "municipio": "Uberlândia"},
                "esperadas": {
                    "funcao": FUNCOES[i % len(FUNCOES)],
                    "r_assalto": "não",
                    "r_acidente": "não",
                    "r_doenca": "não",
                    "r_sequela": "não",
                    "r_acao": "não",
                },
                "contem": {"desligamento": ["ainda", "sim"]},
            }
        )

    # --- 32–41: acidente de trabalho ---
    acidentes = [
        ("escorreguei na escada do CD", "escada", "CD", "maio de 2024", "Sim", "dois meses", "gesso no tornozelo"),
        ("caí da moto na rota molhada", "moto", "rota", "janeiro de 2025", "Sim", "quarenta dias", "tala no braço"),
        ("bicicleta prendeu no buraco", "buraco", "rua", "março de 2023", "Não", "Não afastaram", "fisioterapia"),
        ("caixa caiu no pé no depósito", "caixa", "depósito", "agosto de 2024", "Sim", "três meses", "cirurgia no pé"),
        ("porteira bateu no ombro", "porteira", "agência", "fevereiro de 2022", "Sim", "um mês", "imobilização"),
        ("tropecei na calçada entregando", "calçada", "entrega", "abril de 2025", "Sim", "quinze dias", "atestado"),
        ("moto derrapou na chuva", "chuva", "avenida", "novembro de 2023", "Sim", "dois meses", "internação um dia"),
        ("caí da escada do caminhão", "caminhão", "centro", "junho de 2024", "Não", "Não", "RX e atestado"),
        ("carrinho de carga bateu em mim", "carrinho", "galpão", "setembro de 2021", "Sim", "seis meses", "cirurgia joelho"),
        ("fio elétrico me deu choque", "choque", "sala", "dezembro de 2024", "Sim", "dez dias", "plantão"),
    ]
    for i, (como, pista1, pista2, data, cat, inss, atend) in enumerate(acidentes, start=32):
        key = f"{i:02d}_acidente"
        funcao = FUNCOES[(i - 32) % len(FUNCOES)]
        extras = [
            "Entrevistador: O que aconteceu, passo a passo?",
            f"Entrevistado: Em {data}, {como}. Eu estava no trabalho.",
            "Entrevistador: Onde ocorreu?",
            f"Entrevistado: No {pista2}, durante o expediente.",
            "Entrevistador: Foi emitida a CAT?",
            f"Entrevistado: {cat}.",
            "Entrevistador: Como foi o atendimento?",
            f"Entrevistado: Sim, no mesmo dia. Precisei de {atend}.",
            "Entrevistador: Tem laudos?",
            "Entrevistado: Sim.",
            "Entrevistador: Afastado pelo INSS?",
            f"Entrevistado: {inss}.",
        ]
        cenarios.append(
            {
                "id": key,
                "txt": caso_base(
                    nome=key,
                    funcao=funcao,
                    tempo=f"{(i % 7) + 3} anos",
                    ainda="Sim, ainda trabalho" if i % 2 == 0 else "Fui demitido depois do acidente",
                    rastreio={
                        "r_assalto": "Não",
                        "r_acidente": "Sim",
                        "r_doenca": "Não",
                        "r_sequela": "Não",
                        "r_acao": "Não",
                    },
                    extras=extras,
                ),
                "iniciais": {"nome": f"Acidentado {i}", "cpf": "153.509.460-56", "uf": "BA", "municipio": "Salvador"},
                "esperadas": {
                    "funcao": funcao,
                    "r_assalto": "não",
                    "r_acidente": "sim",
                    "r_doenca": "não",
                    "r_sequela": "não",
                    "r_acao": "não",
                    "ac_cat": "sim" if cat.lower().startswith("sim") else "não",
                    "ac_laudos": "sim",
                },
                "contem": {
                    "ac_como": [pista1, como.split()[0]],
                    "ac_local": [pista2],
                    "ac_data": [data.split()[0], data.split()[-1] if "de" in data else data],
                    "ac_atendimento": [atend.split()[0]],
                    "desligamento": ["ainda", "demit", "sim"],
                },
            }
        )

    # --- 42–46: doença ocupacional ---
    doencas = [
        ("LER no punho", "M65", "fisioterapia", "quatro meses", "Ortopedista"),
        ("tendinite no ombro", "M75", "fisioterapia e anti-inflamatório", "três meses", "Ortopedista e reumatologista"),
        ("hérnia de disco", "M51", "fisioterapia", "seis meses", "Ortopedista"),
        ("bursite no joelho", "M70", "fisioterapia", "dois meses", "Ortopedista"),
        ("túnel do carpo", "G56", "cirurgia e fisioterapia", "cinco meses", "Neurologista"),
    ]
    for i, (diag, cid, trat, afast, med) in enumerate(doencas, start=42):
        key = f"{i:02d}_doenca"
        extras = [
            "Entrevistador: Quais sintomas e diagnóstico?",
            f"Entrevistado: Tenho {diag} por causa da repetição no trabalho. CID {cid}.",
            "Entrevistador: Quais médicos consultou?",
            f"Entrevistado: {med}.",
            "Entrevistador: Fez tratamento?",
            f"Entrevistado: Fiz {trat}.",
            "Entrevistador: Foi afastado?",
            f"Entrevistado: Sim, pelo INSS por {afast}.",
            "Entrevistador: Tem laudos?",
            "Entrevistado: Sim.",
            "Entrevistador: Já tinha isso antes de entrar nos Correios?",
            "Entrevistado: Não.",
        ]
        cenarios.append(
            {
                "id": key,
                "txt": caso_base(
                    nome=key,
                    funcao=FUNCOES[(i - 42) % len(FUNCOES)],
                    tempo="doze anos",
                    ainda="Sim",
                    rastreio={
                        "r_assalto": "Não",
                        "r_acidente": "Não",
                        "r_doenca": "Sim",
                        "r_sequela": "Não",
                        "r_acao": "Não",
                    },
                    extras=extras,
                ),
                "iniciais": {"nome": f"Doente {i}", "cpf": "529.982.247-25", "uf": "PR", "municipio": "Curitiba"},
                "esperadas": {
                    "funcao": FUNCOES[(i - 42) % len(FUNCOES)],
                    "r_assalto": "não",
                    "r_acidente": "não",
                    "r_doenca": "sim",
                    "r_sequela": "não",
                    "r_acao": "não",
                    "do_cid": cid,
                    "do_preexistente": "não",
                    "sa_laudos": "sim",
                },
                "contem": {
                    "sa_diagnostico": [cid, diag.split()[0]],
                    "sa_tratamento": [trat.split()[0]],
                    "sa_afastamento": [afast.split()[0], "INSS"],
                    "sa_medicos": [med.split()[0]],
                    "desligamento": ["ainda", "sim"],
                },
            }
        )

    # --- 47–51: sequela fora do trabalho ---
    for i, (como, sequela) in enumerate(
        [
            ("acidente de carro em 2021", "sequela permanente no joelho"),
            ("queda de moto de lazer em 2020", "limitação no ombro esquerdo permanente"),
            ("acidente doméstico em 2019", "sequela no tornozelo"),
            ("atropelamento fora do serviço em 2022", "sequela na coluna"),
            ("queda de escada em casa em 2023", "sequela no punho"),
        ],
        start=47,
    ):
        key = f"{i:02d}_sequela_fora"
        extras = [
            "Entrevistador: Conte o que aconteceu.",
            f"Entrevistado: Sofri {como}, fora do horário de trabalho, e fiquei com {sequela}.",
            "Entrevistador: A empresa fornecia EPI?",
            "Entrevistado: Sim, fornecia e era obrigatório.",
        ]
        cenarios.append(
            {
                "id": key,
                "txt": caso_base(
                    nome=key,
                    funcao=FUNCOES[(i - 47) % len(FUNCOES)],
                    tempo="quinze anos",
                    ainda="Sim",
                    rastreio={
                        "r_assalto": "Não",
                        "r_acidente": "Não",
                        "r_doenca": "Não",
                        "r_sequela": "Sim",
                        "r_acao": "Não",
                    },
                    extras=extras,
                ),
                "iniciais": {"nome": f"Sequela {i}", "cpf": "537.639.640-10", "uf": "PE", "municipio": "Recife"},
                "esperadas": {
                    "funcao": FUNCOES[(i - 47) % len(FUNCOES)],
                    "r_assalto": "não",
                    "r_acidente": "não",
                    "r_doenca": "não",
                    "r_sequela": "sim",
                    "r_acao": "não",
                },
                "contem": {
                    "se_quais": [sequela.split()[-1], "sequela", "joel", "ombr", "tornoz", "colun", "punh"],
                    "hl_epi": ["EPI", "obrigat", "fornecia"],
                    "desligamento": ["ainda", "sim"],
                },
            }
        )
        # tighten se_quais pistas
        p = []
        for w in ("joelho", "ombro", "tornozelo", "coluna", "punho", "permanente", "limitação", "sequela"):
            if w in sequela.casefold():
                p.append(w)
        cenarios[-1]["contem"]["se_quais"] = p or ["sequela"]

    # --- 52–56: combinações / armadilhas ---
    cenarios.append(
        {
            "id": "52_assalto_e_acidente",
            "txt": caso_base(
                nome="52",
                funcao="Carteiro motorizado",
                tempo="dez anos",
                ainda="Sim",
                rastreio={
                    "r_assalto": "Sim, na rota em 2024.",
                    "r_acidente": "Sim, caí da moto no mesmo ano.",
                    "r_doenca": "Não",
                    "r_sequela": "Não",
                    "r_acao": "Não",
                },
                extras=[
                    "Entrevistador: Assalto foi na jornada?",
                    "Entrevistado: Sim.",
                    "Entrevistador: Do acidente, o que aconteceu?",
                    "Entrevistado: Em outubro de 2024 a moto derrapou na chuva na avenida Central e eu fraturei o punho.",
                    "Entrevistador: CAT do acidente?",
                    "Entrevistado: Sim.",
                    "Entrevistador: CAT do assalto?",
                    "Entrevistado: Sim.",
                ],
            ),
            "iniciais": {"nome": "Combo 52", "cpf": "111.444.777-35", "uf": "SP", "municipio": "Santos"},
            "esperadas": {
                "funcao": "Carteiro motorizado",
                "r_assalto": "sim",
                "r_acidente": "sim",
                "r_doenca": "não",
                "r_sequela": "não",
                "r_acao": "não",
                "as_jornada": "sim",
                "as_cat": "sim",
                "ac_cat": "sim",
            },
            "contem": {"ac_como": ["moto", "punho", "chuva"], "desligamento": ["ainda", "sim"]},
        }
    )
    cenarios.append(
        {
            "id": "53_entrevistador_empurra_assalto",
            "txt": _txt(
                [
                    "Entrevistador: Função?",
                    "Entrevistado: Carteiro pedestre.",
                    "Entrevistador: Tempo?",
                    "Entrevistado: Cinco anos.",
                    "Entrevistador: Ainda trabalha?",
                    "Entrevistado: Sim.",
                    "Entrevistador: Você sofreu assalto no trabalho, certo?",
                    "Entrevistado: Não. Nunca sofri assalto no trabalho.",
                    "Entrevistador: Acidente de trabalho?",
                    "Entrevistado: Não.",
                    "Entrevistador: Doença?",
                    "Entrevistado: Não.",
                    "Entrevistador: Sequela fora?",
                    "Entrevistado: Não.",
                    "Entrevistador: Ação judicial?",
                    "Entrevistado: Não.",
                ]
            ),
            "iniciais": {"nome": "Corrige 53", "cpf": "390.533.447-05", "uf": "GO", "municipio": "Goiânia"},
            "esperadas": {
                "funcao": "Carteiro pedestre",
                "r_assalto": "não",
                "r_acidente": "não",
                "r_doenca": "não",
                "r_sequela": "não",
                "r_acao": "não",
            },
            "contem": {"desligamento": ["ainda", "sim"], "tempo_casa": ["cinco", "5"]},
        }
    )
    cenarios.append(
        {
            "id": "54_acao_ja_ajuizada",
            "txt": caso_base(
                nome="54",
                funcao="Atendente",
                tempo="vinte anos",
                ainda="Não, saí em 2024",
                rastreio={
                    "r_assalto": "Não",
                    "r_acidente": "Sim, quebrei o braço no trabalho em 2022.",
                    "r_doenca": "Não",
                    "r_sequela": "Não",
                    "r_acao": "Sim, já entrei com ação trabalhista.",
                },
                extras=[
                    "Entrevistador: Qual o número do processo e se já recebeu?",
                    "Entrevistado: Processo 0001234-56.2023.5.01.0001, já transitou e eu já recebi os valores.",
                    "Entrevistador: CAT?",
                    "Entrevistado: Sim.",
                    "Entrevistador: Como foi o acidente?",
                    "Entrevistado: Caí da escada da agência e quebrei o braço direito.",
                ],
            ),
            "iniciais": {"nome": "Acao 54", "cpf": "153.509.460-56", "uf": "RJ", "municipio": "Rio de Janeiro"},
            "esperadas": {
                "funcao": "Atendente",
                "r_assalto": "não",
                "r_acidente": "sim",
                "r_doenca": "não",
                "r_sequela": "não",
                "r_acao": "sim",
                "ac_cat": "sim",
            },
            "contem": {
                "r_acao_quais": ["0001234", "recebi", "transit"],
                "ac_como": ["escada", "braço", "quebr"],
                "desligamento": ["saí", "2024", "nao", "não"],
            },
        }
    )
    cenarios.append(
        {
            "id": "55_doenca_e_pressao",
            "txt": caso_base(
                nome="55",
                funcao="OTT",
                tempo="quatorze anos",
                ainda="Sim",
                rastreio={
                    "r_assalto": "Não",
                    "r_acidente": "Não",
                    "r_doenca": "Sim, LER nos dois punhos.",
                    "r_sequela": "Não",
                    "r_acao": "Não",
                },
                extras=[
                    "Entrevistador: Diagnóstico CID?",
                    "Entrevistado: M65, tendinite.",
                    "Entrevistador: Havia pressão e metas?",
                    "Entrevistado: Sim, metas abusivas e pressão diária do supervisor.",
                    "Entrevistador: EPI?",
                    "Entrevistado: Forneciam luva, mas quase não fiscalizavam.",
                    "Entrevistador: Afastamento?",
                    "Entrevistado: Fiquei afastado quatro meses pelo INSS.",
                    "Entrevistador: Laudos?",
                    "Entrevistado: Sim.",
                ],
            ),
            "iniciais": {"nome": "Pressao 55", "cpf": "529.982.247-25", "uf": "RS", "municipio": "Porto Alegre"},
            "esperadas": {
                "funcao": "OTT",
                "r_assalto": "não",
                "r_acidente": "não",
                "r_doenca": "sim",
                "r_sequela": "não",
                "r_acao": "não",
                "do_cid": "M65",
                "sa_laudos": "sim",
            },
            "contem": {
                "hl_pressao": ["metas", "pressão", "abusiv"],
                "hl_epi": ["luva", "EPI", "fiscaliz"],
                "sa_afastamento": ["quatro", "INSS"],
                "desligamento": ["ainda", "sim"],
            },
        }
    )
    cenarios.append(
        {
            "id": "56_respostas_curtas_sim_nao",
            "txt": _txt(
                [
                    "Entrevistador: Função?",
                    "Entrevistado: Carteiro ciclista.",
                    "Entrevistador: Tempo de casa?",
                    "Entrevistado: Três anos.",
                    "Entrevistador: Ainda trabalha?",
                    "Entrevistado: Sim.",
                    "Entrevistador: Assalto no trabalho?",
                    "Entrevistado: Não.",
                    "Entrevistador: Acidente de trabalho?",
                    "Entrevistado: Sim.",
                    "Entrevistador: O que aconteceu?",
                    "Entrevistado: Cai da bike no buraco na rua das Palmeiras em maio de 2025.",
                    "Entrevistador: CAT?",
                    "Entrevistado: Sim.",
                    "Entrevistador: Laudos?",
                    "Entrevistado: Sim.",
                    "Entrevistador: Doença?",
                    "Entrevistado: Não.",
                    "Entrevistador: Sequela fora?",
                    "Entrevistado: Não.",
                    "Entrevistador: Ação?",
                    "Entrevistado: Não.",
                ]
            ),
            "iniciais": {"nome": "Curto 56", "cpf": "111.444.777-35", "uf": "SC", "municipio": "Florianópolis"},
            "esperadas": {
                "funcao": "Carteiro ciclista",
                "r_assalto": "não",
                "r_acidente": "sim",
                "r_doenca": "não",
                "r_sequela": "não",
                "r_acao": "não",
                "ac_cat": "sim",
                "ac_laudos": "sim",
            },
            "contem": {
                "ac_como": ["bike", "buraco", "Palmeiras"],
                "ac_data": ["maio", "2025"],
                "desligamento": ["ainda", "sim"],
                "tempo_casa": ["três", "3"],
            },
        }
    )

    assert len(cenarios) == 50, len(cenarios)

    for c in cenarios:
        (FIX / f"{c['id']}.txt").write_text(c["txt"], encoding="utf-8")
        ouro[c["id"]] = {
            "iniciais": c["iniciais"],
            "esperadas": c["esperadas"],
            "contem": c["contem"],
        }

    ouro_path.write_text(json.dumps(ouro, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Gerados {len(cenarios)} casos (07–56). Total no ouro: {len(ouro)}")


if __name__ == "__main__":
    main()
