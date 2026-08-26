"""Triagem da entrevista: sugere a categoria do caso a partir do relato.

Escolher a categoria errada é escolher o checklist errado — o advogado passa a
cobrar documentos que não servem e deixa de cobrar os que a ação exige. Por isso
aqui nada é decidido sozinho: a função devolve um ranking com a evidência que
sustentou cada pontuação, e quem confirma é a pessoa.

O método é o mesmo já usado para classificar o tipo de documento em
`extractors.classificar`: pistas com peso, somadas sobre o texto normalizado.
Sem chamada a modelo externo — o projeto roda offline, e um relato de acidente
com CPF e histórico médico não deve sair da máquina do escritório.

As quatro primeiras categorias são vizinhas e se confundem:
  - acidente do trabalho nos Correios x acidente do trabalho em geral
    → o que separa é o empregador (ECT/Correios);
  - assalto a carteiro x acidente nos Correios
    → o que separa é a natureza do evento (violência x acidente);
  - doença ocupacional x acidente
    → o que separa é o tempo (instalação gradual x evento súbito).
Daí os sinais de desempate no fim do arquivo, que valem mais que palavra solta.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from . import categorias

# --------------------------------------------------------------- pistas


# (expressão normalizada, peso). Peso alto = a expressão praticamente decide.
PISTAS: dict[str, list[tuple[str, int]]] = {
    # Vocabulário ampliado pela avaliação com relatos gerados por LLM: o cliente
    # raramente diz "Correios". Diz "entregador de correspondência", "operadora
    # de triagem", "agência". Sem esses termos, o caso caía em acidente geral.
    "acidente_trabalho_correios": [
        ("CORREIOS", 12), ("ECT", 8), ("EMPRESA BRASILEIRA DE CORREIOS", 14),
        ("CARTEIRO", 12), ("AGENCIA DOS CORREIOS", 9), ("CENTRO DE DISTRIBUICAO", 9),
        ("ENTREGA DE ENCOMENDA", 5), ("MOTOCICLETA DOS CORREIOS", 8),
        ("OPERADOR DE TRIAGEM", 9), ("OPERADORA DE TRIAGEM", 9),
        ("ENTREGADOR DE CORRESPONDENCIA", 12), ("ENTREGA DE CORRESPONDENCIA", 9),
        ("CORRESPONDENCIA", 5), ("ENTREGANDO CARTA", 7), ("MALOTE", 5),
        ("CTC", 4), ("SEDEX", 6), ("ROTA DE ENTREGA", 5), ("BOLSA DE ENTREGA", 6),
    ],
    "acidente_trabalho_geral": [
        ("ACIDENTE DE TRABALHO", 10), ("ACIDENTE DO TRABALHO", 10),
        ("CAT", 5), ("COMUNICACAO DE ACIDENTE", 8),
        ("CAI", 3), ("QUEDA", 5), ("FRATURA", 6), ("FRATUROU", 6),
        ("MAQUINA", 5), ("ESMAGOU", 6), ("CORTOU", 4), ("AMPUTACAO", 8),
        ("ANDAIME", 6), ("EMPILHADEIRA", 6), ("OBRA", 3),
        ("AFASTADO PELO INSS", 5), ("EPI", 4), ("SEM EQUIPAMENTO", 5),
        ("NO EXERCICIO DA FUNCAO", 5), ("DURANTE O EXPEDIENTE", 5),
        ("ACIDENTE DE TRAJETO", 7),
    ],
    "doenca_ocupacional": [
        ("DOENCA OCUPACIONAL", 12), ("DOENCA DO TRABALHO", 10),
        ("LER", 8), ("DORT", 10), ("TENDINITE", 8), ("BURSITE", 8),
        ("SINDROME DO TUNEL DO CARPO", 10), ("HERNIA DE DISCO", 7),
        ("LOMBALGIA", 6), ("MOVIMENTOS REPETITIVOS", 10), ("ESFORCO REPETITIVO", 10),
        ("AO LONGO DOS ANOS", 6), ("COM O TEMPO", 5), ("FOI PIORANDO", 7),
        ("GRADUAL", 6), ("PERDA AUDITIVA", 8), ("PAIR", 6), ("RUIDO", 5),
        ("NEXO CAUSAL", 6), ("PRODUTO QUIMICO", 6), ("INSALUBRIDADE", 5),
        ("DEPRESSAO", 5), ("BURNOUT", 7), ("ASSEDIO MORAL", 5),
        ("POSTURA", 4), ("ESFORCO FISICO REPETIDO", 8),
    ],
    "assalto_carteiro": [
        ("ASSALTO", 12), ("ASSALTADO", 12), ("ROUBO", 9), ("ROUBADO", 9),
        ("ARMA DE FOGO", 10), ("ARMA BRANCA", 8), ("REVOLVER", 8), ("PISTOLA", 8),
        ("RENDIDO", 9), ("BOLETIM DE OCORRENCIA", 7), ("BO", 3),
        ("VIOLENCIA", 6), ("AMEACA", 5), ("LEVARAM", 5),
        ("ESTRESSE POS TRAUMATICO", 8), ("TEPT", 8), ("MEDO DE VOLTAR", 6),
    ],
    "auxilio_acidente": [
        ("AUXILIO ACIDENTE", 14), ("AUXILIO-ACIDENTE", 14),
        ("SEQUELA", 9), ("SEQUELAS", 9), ("REDUCAO DA CAPACIDADE", 10),
        ("CAPACIDADE LABORATIVA", 8), ("ALTA DO INSS", 7),
        ("INDEFERIDO", 6), ("INDEFERIMENTO", 6), ("PERICIA", 5),
        ("BENEFICIO", 5), ("AUXILIO DOENCA", 6), ("B91", 7), ("B94", 8),
        ("CESSOU O BENEFICIO", 8), ("VOLTOU A TRABALHAR COM LIMITACAO", 8),
    ],
}

# Como o cliente se identifica como trabalhador dos Correios. A avaliação mostrou
# que "Correios" quase nunca aparece: vem "carteiro", "entregador de
# correspondência", "operadora de triagem", "agência".
_ECT = r"(CORREIOS|CARTEIR[OA]|\bECT\b|CORRESPONDENCIA|TRIAGEM|CENTRO DE DISTRIBUICAO|MALOTE|SEDEX)"


# Sinais que valem mais que palavra isolada porque combinam dois fatos. Cada um
# some/subtrai pontos de uma categoria quando o padrão casa no texto inteiro.
#: Palavras que viram o sentido do que vem depois. Medido na entrevista real do
#: dia 26/08: "não teve via acidente de trabalho" somava +10 para Acidente Geral,
#: e "não sei que que é a CAT" somava +5 — a categoria venceu com 18 pontos dos
#: quais 18 eram negação ou pedaço de palavra.
NEGACOES = ("NAO", "NUNCA", "NENHUM", "NENHUMA", "JAMAIS", "SEM")

#: Conectivo de CAUSA entre a negação e o termo desfaz a negação: em "não
#: consigo trabalhar POR CAUSA do acidente", o acidente é real e deve pontuar.
#: Sem esta ressalva, a correção da negação apagaria caso verdadeiro — que é
#: erro pior que o que ela conserta.
CONECTIVOS_DE_CAUSA = ("POR CAUSA", "DEVIDO", "POR CONTA", "EM RAZAO", "DECORRENTE")

#: Quanto texto antes do termo conta como contexto da negação. Três ou quatro
#: palavras: "não teve via acidente" cabe, "não consigo dormir direito desde o
#: acidente" não — e não deve caber mesmo, ali o acidente existe.
JANELA_NEGACAO = 28


def _negado(norm: str, inicio: int) -> bool:
    """A menção logo antes do termo o nega?"""
    janela = norm[max(0, inicio - JANELA_NEGACAO) : inicio]
    if not any(re.search(rf"\b{n}\b", janela) for n in NEGACOES):
        return False
    # A negação existe, mas há uma causa entre ela e o termo: o fato é real.
    return not any(c in janela for c in CONECTIVOS_DE_CAUSA)


def _ocorrencias(norm: str, termo: str):
    """Onde o termo aparece como PALAVRA, e não como pedaço de outra.

    O `in` solto casava "CAI" dentro de "enCAIxa" e "BO" dentro de "BOm dia" —
    os dois medidos na mesma entrevista. Termo de uma sílaba é comum dentro de
    palavra comprida, e cada falso positivo desses empurra a categoria errada.
    """
    return re.finditer(rf"\b{re.escape(termo)}\b", norm)


@dataclass
class Desempate:
    padrao: str
    categoria: str
    peso: int
    porque: str


DESEMPATES: list[Desempate] = [
    # Correios só é "acidente nos Correios" se não for assalto: o assalto tem
    # categoria própria e um checklist diferente (BO, laudo psicológico).
    Desempate(rf"{_ECT}.{{0,500}}(ASSALT|ROUB|ARMA|REND|BANDID|LADR)",
              "assalto_carteiro", 16, "relato de violência contra trabalhador dos Correios"),
    Desempate(rf"(ASSALT|ROUB|ARMA|REND|BANDID|LADR).{{0,500}}{_ECT}",
              "assalto_carteiro", 16, "relato de violência contra trabalhador dos Correios"),
    # Empregado dos Correios que sofre acidente pertence à categoria própria,
    # não à geral — sem isto, as palavras de acidente ("queda", "fratura")
    # somavam mais em "geral" do que o vínculo empregatício somava aqui.
    Desempate(rf"{_ECT}.{{0,600}}(ACIDENT|CAI\b|QUEDA|FRATUR|DERRAPO|BATE|ATROPEL|MACHUC)",
              "acidente_trabalho_correios", 14, "acidente sofrido por trabalhador dos Correios"),
    Desempate(rf"(ACIDENT|CAI\b|QUEDA|FRATUR|DERRAPO|BATE|ATROPEL|MACHUC).{{0,600}}{_ECT}",
              "acidente_trabalho_correios", 14, "acidente sofrido por trabalhador dos Correios"),
    # Auxílio-acidente é o PEDIDO, não o evento: o relato conta o acidente antigo
    # e termina na sequela. Sem isto, as palavras do acidente venciam o pedido.
    Desempate(r"(SEQUELA|LIMITACAO|NAO CONSIGO MAIS|PERDI (A |O )?(MOVIMENT|FORCA))"
              r".{0,400}(AUXILIO|BENEFICIO|INSS|PERICIA)",
              "auxilio_acidente", 14, "sequela permanente com pedido de benefício"),
    Desempate(r"(AUXILIO|BENEFICIO|INSS|PERICIA).{0,400}"
              r"(SEQUELA|LIMITACAO|NAO CONSIGO MAIS|REDUCAO DA CAPACIDADE)",
              "auxilio_acidente", 14, "sequela permanente com pedido de benefício"),
    # Doença é processo, não evento: expressões de duração afastam "acidente".
    Desempate(r"(HA|DURANTE|FAZ)\s+\d+\s+(ANOS?|MESES)",
              "doenca_ocupacional", 8, "queixa que se instala ao longo do tempo"),
    Desempate(r"(NAO|SEM)\s+(HOUVE|TEVE)\s+ACIDENTE",
              "doenca_ocupacional", 10, "o próprio relato nega evento acidental"),
    # Auxílio-acidente é benefício previdenciário: aparece depois da alta.
    Desempate(r"(APOS|DEPOIS D[AE]).{0,80}(ALTA|CESSA)",
              "auxilio_acidente", 8, "pedido posterior à alta previdenciária"),
    # Empregador explícito diferente dos Correios derruba a hipótese Correios.
    Desempate(r"(TRABALHAVA|TRABALHA|EMPREGAD[OA])\s+(NA|NO|PARA A?)\s+(?!CORREIOS|ECT)[A-Z]{3,}",
              "acidente_trabalho_geral", 5, "empregador citado não é os Correios"),
]

MIN_PONTOS = 12          # abaixo disso não há sinal suficiente para sugerir
MARGEM_SEGURA = 8        # diferença mínima para a 1ª opção ser "confiante"


def normalizar(texto: str) -> str:
    """Maiúsculas, sem acento e sem pontuação — igual ao resto do projeto."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^A-Z0-9\s]", " ", sem_acento.upper())


@dataclass
class Sugestao:
    codigo: str
    nome: str
    pontos: int
    confianca: float
    evidencias: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "codigo": self.codigo,
            "nome": self.nome,
            "pontos": self.pontos,
            "confianca": round(self.confianca, 3),
            "evidencias": self.evidencias,
        }


def _trecho_ao_redor(texto: str, termo: str, janela: int = 60) -> str:
    """Devolve o pedaço do relato que gerou a pontuação, para o advogado conferir."""
    i = texto.find(termo)
    if i < 0:
        return termo
    ini = max(0, i - janela // 2)
    fim = min(len(texto), i + len(termo) + janela // 2)
    # O texto normalizado guarda as quebras de linha do relato; exibi-las cruas
    # quebraria o trecho no meio na tela.
    miolo = " ".join(texto[ini:fim].split())
    return ("…" if ini > 0 else "") + miolo + ("…" if fim < len(texto) else "")


def classificar_entrevista(texto: str) -> dict[str, Any]:
    """Ranking de categorias para o relato, com a evidência de cada uma."""
    if not texto or not texto.strip():
        return {"sugestoes": [], "confiante": False, "motivo": "Nenhum texto informado."}

    norm = normalizar(texto)
    pontos: dict[str, int] = {}
    evidencias: dict[str, list[str]] = {}

    for codigo, pistas in PISTAS.items():
        for termo, peso in pistas:
            # Uma vez por termo, como antes: repetir a mesma expressão não é
            # mais evidência, é a pessoa repetindo a mesma coisa.
            for achado in _ocorrencias(norm, termo):
                if _negado(norm, achado.start()):
                    continue
                pontos[codigo] = pontos.get(codigo, 0) + peso
                evidencias.setdefault(codigo, []).append(_trecho_ao_redor(norm, termo))
                break

    for d in DESEMPATES:
        if re.search(d.padrao, norm, re.S):
            pontos[d.categoria] = pontos.get(d.categoria, 0) + d.peso
            evidencias.setdefault(d.categoria, []).append(d.porque)

    if not pontos:
        return {
            "sugestoes": [],
            "confiante": False,
            "motivo": "O texto não menciona nada que aponte para uma das categorias.",
        }

    nomes = {c.codigo: c.nome for c in categorias.listar()}
    total = sum(pontos.values()) or 1

    ranking = sorted(pontos.items(), key=lambda kv: kv[1], reverse=True)
    sugestoes = [
        Sugestao(
            codigo=cod,
            nome=nomes.get(cod, cod),
            pontos=p,
            confianca=p / total,
            # Poucas evidências e sem repetir: é para conferir, não para auditar.
            evidencias=list(dict.fromkeys(evidencias.get(cod, [])))[:4],
        )
        for cod, p in ranking
        if cod in nomes
    ]

    if not sugestoes:
        return {"sugestoes": [], "confiante": False, "motivo": "Nenhuma categoria reconhecida."}

    melhor = sugestoes[0]
    segundo = sugestoes[1].pontos if len(sugestoes) > 1 else 0
    margem = melhor.pontos - segundo

    if melhor.pontos < MIN_PONTOS:
        motivo = "Sinal fraco no relato — confira a categoria antes de criar o caso."
        confiante = False
    elif margem < MARGEM_SEGURA:
        motivo = (
            f"'{melhor.nome}' e '{sugestoes[1].nome}' ficaram próximos "
            f"({melhor.pontos} x {segundo}) — confirme qual descreve o caso."
        )
        confiante = False
    else:
        motivo = f"O relato aponta para '{melhor.nome}' com folga sobre as demais."
        confiante = True

    return {
        "sugestoes": [s.to_dict() for s in sugestoes],
        "confiante": confiante,
        "motivo": motivo,
    }


# ------------------------------------------------- classificação por LLM


"""O modelo lê o relato e decide a categoria.

Diferença para as pistas acima: o modelo interpreta a situação em vez de casar
palavra. Um relato que diga "entrego correspondência para a estatal" sem nunca
escrever "Correios" o modelo entende; a lista de pistas, não.

ATENÇÃO — dado sensível sai da máquina. O relato tem CPF, nome e histórico
médico, e vai para a API do DeepSeek. Foi decisão do escritório usar o modelo;
sem chave configurada nada é enviado e a triagem cai nas pistas locais.
"""

URL_LLM = "https://api.deepseek.com/chat/completions"
MODELO_LLM = "deepseek-chat"
TIMEOUT_LLM = 60

INSTRUCAO = """Você é um advogado trabalhista brasileiro fazendo a triagem de uma
entrevista inicial. Leia o relato e decida em qual categoria de ação ele se encaixa.

CATEGORIAS:

1. acidente_trabalho_correios — Acidente do Trabalho (Correios)
   Evento súbito que feriu um empregado dos CORREIOS/ECT (carteiro, operador de
   triagem, entregador de correspondência, funcionário de agência ou centro de
   distribuição). Use esta, e não a geral, sempre que o empregador for os Correios.

2. acidente_trabalho_geral — Acidente de Trabalho Geral
   Evento súbito que feriu o trabalhador em QUALQUER OUTRO empregador.

3. doenca_ocupacional — Doença Ocupacional
   Problema de saúde que se instalou GRADUALMENTE pelo trabalho: esforço
   repetitivo, LER/DORT, tendinite, perda auditiva, coluna, doença por exposição
   química, adoecimento mental. Não há evento súbito.

4. assalto_carteiro — Assalto a Carteiro
   VIOLÊNCIA (assalto, roubo, ameaça, arma) sofrida por trabalhador dos Correios
   durante a jornada. Tem prioridade sobre a categoria 1 quando houver crime.

5. auxilio_acidente — Auxílio-Acidente
   O pedido é o BENEFÍCIO previdenciário por SEQUELA que reduz a capacidade de
   trabalho, geralmente após alta do INSS ou indeferimento. O acidente já ocorreu
   e o foco do relato é a limitação que ficou e o pedido ao INSS.

COMO DECIDIR:
- Correios + acidente -> categoria 1 (não a 2).
- Correios + violência -> categoria 4 (não a 1).
- Gradual, sem evento único -> categoria 3.
- O foco é a sequela e o benefício do INSS -> categoria 5.

REGRAS DESTE ESCRITÓRIO (prevalecem sobre o critério geral):
- TERCEIRIZADO acidentado trabalhando dentro dos Correios (centro de
  distribuição, agência, operação da ECT) -> categoria 1, mesmo que o
  empregador formal seja a prestadora. A ECT entra na ação como tomadora.
- ACIDENTE DE TRAJETO (indo ou voltando do trabalho) -> mesma categoria de um
  acidente comum: 1 se for dos Correios, 2 nos demais casos.
- Se o relato trouxer AO MESMO TEMPO uma doença crônica ligada ao trabalho E um
  acidente súbito, não escolha sozinho: responda com "duvida": true, aponte a
  categoria do acidente em "categoria" e a doença ocupacional em "alternativa".
  São potencialmente duas ações, e quem decide isso é o advogado.

Marque "duvida": true sempre que o relato não deixar claro o empregador, a
natureza do evento, ou quando duas categorias forem defensáveis.

Responda APENAS JSON:
{"categoria": "<código>", "confianca": <0.0 a 1.0>,
 "justificativa": "<uma frase citando o que no relato levou à decisão>",
 "alternativa": "<código da segunda hipótese ou null>",
 "duvida": <true se o relato for ambíguo ou insuficiente>}"""


def _chave_llm() -> str:
    """Chave do ambiente ou de `dados/.env.local` (fora do versionamento)."""
    import os
    from pathlib import Path

    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if chave:
        return chave
    env = Path(__file__).resolve().parent.parent / "dados" / ".env.local"
    if env.is_file():
        for linha in env.read_text(encoding="utf-8").splitlines():
            if linha.startswith("DEEPSEEK_API_KEY="):
                return linha.split("=", 1)[1].strip()
    return ""


def llm_disponivel() -> bool:
    return bool(_chave_llm())


def classificar_com_llm(texto: str) -> dict[str, Any] | None:
    """Classifica pelo modelo. Devolve `None` se não der — quem chama cai nas pistas."""
    chave = _chave_llm()
    if not chave or not texto.strip():
        return None

    import json

    import httpx

    try:
        r = httpx.post(
            URL_LLM,
            headers={"Authorization": f"Bearer {chave}", "Content-Type": "application/json"},
            json={
                "model": MODELO_LLM,
                "messages": [
                    {"role": "system", "content": INSTRUCAO},
                    {"role": "user", "content": texto[:12000]},
                ],
                # Triagem precisa ser reproduzível: o mesmo relato deve dar a
                # mesma categoria em duas leituras seguidas.
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=TIMEOUT_LLM,
        )
        r.raise_for_status()
        bruto = json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as exc:
        log_erro = f"{type(exc).__name__}: {exc}"
        return {"_erro": log_erro}

    nomes = {c.codigo: c.nome for c in categorias.listar()}
    codigo = str(bruto.get("categoria", "")).strip()
    if codigo not in nomes:
        return None

    confianca = float(bruto.get("confianca") or 0)
    duvida = bool(bruto.get("duvida"))
    justificativa = str(bruto.get("justificativa", "")).strip()
    alternativa = bruto.get("alternativa")

    sugestoes = [
        {
            "codigo": codigo,
            "nome": nomes[codigo],
            "pontos": int(confianca * 100),
            "confianca": confianca,
            "evidencias": [justificativa] if justificativa else [],
        }
    ]
    if alternativa in nomes and alternativa != codigo:
        sugestoes.append(
            {
                "codigo": alternativa,
                "nome": nomes[alternativa],
                "pontos": int((1 - confianca) * 100),
                "confianca": round(1 - confianca, 3),
                "evidencias": ["segunda hipótese levantada na leitura"],
            }
        )

    # Trava independente do modelo: acidente com doença ocupacional como segunda
    # hipótese é o caso em que podem existir DUAS ações. A instrução manda marcar
    # dúvida, mas o modelo ignorou isso no teste — respondeu com a alternativa
    # correta e `duvida: false`. Prompt é melhor-esforço; esta regra não é.
    ACIDENTES = {"acidente_trabalho_correios", "acidente_trabalho_geral"}
    concorrentes = (
        (codigo in ACIDENTES and alternativa == "doenca_ocupacional")
        or (codigo == "doenca_ocupacional" and alternativa in ACIDENTES)
    )
    if concorrentes:
        duvida = True
        justificativa = (
            (justificativa + " ") if justificativa else ""
        ) + "O relato traz doença crônica e acidente súbito — podem ser duas ações."

    # Confia só quando o modelo não sinaliza dúvida E se diz seguro.
    confiante = (not duvida) and confianca >= 0.75
    motivo = justificativa or "Classificado pela leitura do relato."
    if not confiante:
        motivo += " — confirme antes de criar o caso."

    return {
        "sugestoes": sugestoes,
        "confiante": confiante,
        "motivo": motivo,
        "metodo": "llm",
    }


def triar(texto: str) -> dict[str, Any]:
    """Entrada única. Usa o modelo e confere o resultado contra as pistas locais.

    Os dois métodos são independentes: um interpreta a situação, o outro casa
    termos. Quando concordam, a chance de estarem os dois errados é pequena e a
    sugestão vale como confiante.

    Quando discordam, é o sinal de incerteza mais confiável que existe aqui —
    melhor que perguntar ao próprio modelo se ele está em dúvida, que foi o que
    tentei antes: ele respondia `duvida: false` em relato que trazia doença
    crônica E acidente súbito ao mesmo tempo. Discordância não depende de ele
    admitir nada.
    """
    resultado = classificar_com_llm(texto)

    if not resultado or "_erro" in resultado:
        local = classificar_entrevista(texto)
        local["metodo"] = "pistas"
        if resultado and "_erro" in resultado:
            local["motivo"] += f" (modelo indisponível: {resultado['_erro'][:80]})"
        return local

    local = classificar_entrevista(texto)
    cod_llm = resultado["sugestoes"][0]["codigo"] if resultado["sugestoes"] else ""
    cod_local = local["sugestoes"][0]["codigo"] if local["sugestoes"] else ""

    if cod_local and cod_llm and cod_local != cod_llm:
        resultado["confiante"] = False
        resultado["motivo"] += (
            f" A checagem por termos apontou '{local['sugestoes'][0]['nome']}' —"
            " as duas leituras divergiram, confirme antes de criar o caso."
        )
        # A divergente entra como segunda opção clicável, se ainda não estiver.
        ja = {s["codigo"] for s in resultado["sugestoes"]}
        if cod_local not in ja:
            resultado["sugestoes"].append(
                {**local["sugestoes"][0], "evidencias": local["sugestoes"][0]["evidencias"][:2]}
            )

    resultado["divergiu"] = bool(cod_local and cod_llm and cod_local != cod_llm)

    # Doença crônica E acidente súbito no mesmo relato podem ser duas ações.
    # Nem o modelo nem a divergência pegam isto: os dois métodos concordam em
    # "acidente", porque ambos enxergam as palavras do evento. A checagem tem de
    # ser direta — os dois quadros pontuando forte ao mesmo tempo no texto.
    pontos = {s["codigo"]: s["pontos"] for s in local["sugestoes"]}
    doenca = pontos.get("doenca_ocupacional", 0)
    acidente = max(
        pontos.get("acidente_trabalho_correios", 0),
        pontos.get("acidente_trabalho_geral", 0),
    )
    if doenca >= 15 and acidente >= 15:
        resultado["confiante"] = False
        resultado["concorrentes"] = True
        resultado["motivo"] += (
            " O relato descreve um quadro crônico e um acidente súbito —"
            " confira se não são duas ações."
        )
        ja = {s["codigo"] for s in resultado["sugestoes"]}
        if "doenca_ocupacional" not in ja:
            alvo = next(
                (s for s in local["sugestoes"] if s["codigo"] == "doenca_ocupacional"), None
            )
            if alvo:
                resultado["sugestoes"].append(alvo)

    return resultado


# ------------------------------------------------------- dados do cliente


# Para em pontuação de fim de frase, não só na quebra de linha: numa entrevista
# digitada em parágrafo corrido ("Cliente: Maria da Silva. Trabalha na...") o
# corte por linha engolia o relato inteiro como se fosse o nome.
RE_NOME = re.compile(
    r"(?:NOME(?:\s+DO\s+CLIENTE|\s+COMPLETO)?|CLIENTE|ENTREVISTAD[OA])\s*[:\-]\s*"
    r"([A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ][^\n\r,;.]{3,79})",
    re.I,
)
RE_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")


def extrair_dados_do_cliente(texto: str) -> dict[str, str]:
    """Puxa nome e CPF do cabeçalho da entrevista, quando houver.

    Só preenche o formulário — nada aqui cria caso sozinho.
    """
    dados: dict[str, str] = {}

    m = RE_NOME.search(texto)
    if m:
        nome = " ".join(m.group(1).split()).strip(" .:-")
        if len(nome) >= 4:
            dados["cliente"] = nome

    m = RE_CPF.search(texto)
    if m:
        dados["cpf"] = m.group(0)

    return dados
