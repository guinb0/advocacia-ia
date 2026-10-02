"""Conferência da petição contra os autos, ANTES de ela ser salva.

O PROBLEMA QUE ISTO RESOLVE

O contrato de redação (`peticao_local.CONTRATO_DE_REDACAO`) já proibia tudo o que o
teste com caso-gabarito de 18/09/2026 encontrou na peça: "não cite documento que não
esteja no contexto", "é proibido inventar súmula". Mas a única conferência depois da
geração (`peticao_aprendizado.avaliar_documento`) media TAMANHO de seção. A regra
existia só como pedido ao modelo — e o modelo, às vezes, não cumpre:

- citou "declaração de hipossuficiência anexa (Documento 09)" num caso com oito anexos
  e nenhuma declaração;
- criou R$ 6.440,00 de "despesas médicas" num caso sem despesa nenhuma, só para a soma
  dos pedidos fechar em R$ 150.000,00;
- deixou pensão, horas extras e acúmulo "a apurar em liquidação" (art. 840, § 1º, CLT);
- escreveu "DA MULTA DO ART. 477 — não se aplica" dentro da inicial do próprio cliente;
- citou a Súmula 6 do TST (equiparação salarial) para acúmulo de função.

Aqui a regra vira código. Cada verificação devolve uma `Violacao` com o trecho e a
instrução de correção; quem gera (`peticao_local.gerar`) pede UMA rodada de correção
ao modelo com a lista exata e, se ainda sobrar violação, a peça é salva RETIDA, com o
achado na tela — nunca em silêncio.

O QUE AINDA NÃO É CONFERIDO AQUI

Súmula/OJ/tema contra o TEXTO oficial: o acervo não tem catálogo de súmulas (só `lei`,
`jurisprudencia` e `interno`). Até ele existir, citação sem fonte no material recebido
sai MARCADA na peça como não verificada — o advogado vê, o juiz não é enganado.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from dataclasses import field
from typing import Any

from . import peticao_skill_arquivos

__all__ = [
    "Fontes",
    "Violacao",
    "conferir",
    "como_achados",
    "instrucao_de_correcao",
    "marcar_citacoes_nao_verificadas",
    "normalizar",
    "numeros_colados",
]


# --------------------------------------------------------------- normalização


def normalizar(texto: str) -> str:
    """Minúsculo e sem acento: «Declaração» e «declaracao» se acham."""
    sem_acento = unicodedata.normalize("NFKD", str(texto or ""))
    return " ".join("".join(c for c in sem_acento if not unicodedata.combining(c)).lower().split())


def numeros_colados(texto: str) -> str:
    """Tira os separadores DENTRO dos números: «123.456.789-00» vira «12345678900».

    Só o que está entre dígitos: tirar todo não-dígito juntaria a data com o CPF da
    linha de baixo e acharia número que não existe.
    """
    return re.sub(r"(?<=\d)[\s./-](?=\d)", "", str(texto or ""))


def _padrao(termo: str) -> re.Pattern[str]:
    """Sigla curta casa como palavra inteira: «rg» não acha «cargo»."""
    if len(termo) <= 4:
        return re.compile(rf"(?<![a-z0-9]){re.escape(termo)}(?![a-z0-9])")
    return re.compile(re.escape(termo))


# --------------------------------------------------------------------- fontes


@dataclass
class Fontes:
    """Tudo o que a peça pode afirmar. O que não estiver aqui, ela não inventa.

    `numerados` é o bloco DOCUMENTOS exatamente como o modelo o recebeu: a peça cita
    "Documento NN" por esta numeração (`peticao_local._montar_contexto`).
    """

    anexos: list[dict[str, Any]]            # peticao_local.anexos_do_caso
    numerados: list[str]                    # arquivo de cada "DOCUMENTO NN", em ordem
    entrevista: str = ""
    cadastro: str = ""                      # cliente + qualificação, achatados
    material: str = ""                      # o que mais foi ao prompt (acervo, julgados)
    #: Número canônico de cada item de `numerados` (DOCUMENT_LEDGER: o "Doc N." do arquivo). Vazio = 1..n.
    numeros: list[int] = field(default_factory=list)
    #: Grupos de nomes equivalentes de documento — vocabulário do DOMÍNIO, vem da skill.
    sinonimos: tuple[tuple[str, ...], ...] = field(default_factory=lambda: _sinonimos_da_skill())

    def __post_init__(self) -> None:
        blocos = [
            " ".join(
                [
                    str(a.get("arquivo") or ""),
                    str(a.get("tipo") or ""),
                    " ".join(f"{c.get('rotulo', '')} {c.get('valor', '')}" for c in a.get("campos") or []),
                    str(a.get("texto") or ""),
                ]
            )
            for a in self.anexos
        ]
        self._por_anexo = [normalizar(b) for b in blocos]
        tudo = "\n".join([*blocos, self.entrevista, self.cadastro, self.material])
        self._tudo = normalizar(tudo)
        self._digitos = numeros_colados(self._tudo)
        self._datas = {
            _data(m.group(0)) for m in re.finditer(r"\b\d{2}/\d{2}/\d{4}\b", tudo)
        } - {None}

    # O documento de que a peça fala existe entre os anexos?
    def tem_anexo(self, descricao: str) -> bool:
        termos = _termos_do_documento(descricao, self.sinonimos)
        if not termos:
            return True  # só palavras genéricas ("documentos anexos"): nada a conferir
        sinonimos, palavras = termos
        for bloco in self._por_anexo:
            if sinonimos and any(_padrao(s).search(bloco) for s in sinonimos):
                return True
            if palavras and all(_padrao(p).search(bloco) for p in palavras):
                return True
        return False

    def tem_numero(self, numero: str) -> bool:
        digitos = re.sub(r"\D", "", numero)
        return bool(digitos) and digitos in self._digitos

    def tem_data(self, texto: str) -> bool:
        """A data está nos autos, ou é derivada de uma data dos autos.

        "15/09/2025" não está em documento nenhum, mas é a DCB (15/09/2024) mais doze
        meses — o fim da estabilidade. Derivada = mesmo dia E mesmo mês de uma data
        conhecida, PROJETADA para frente por um prazo legal (1, 2 ou 5 anos: estabilidade,
        prescrição bienal e quinquenal), ou o marco prescricional contado de hoje para trás.
        A antiga tolerância de ±5 anos em qualquer direção aceitava data inventada até cinco
        anos antes de qualquer documento; só o mesmo dia também não basta.
        """
        alvo = _data(texto)
        if alvo is None:
            return True
        if alvo in self._datas:
            return True
        hoje = date.today()
        if (alvo.day, alvo.month) == (hoje.day, hoje.month) and hoje.year - alvo.year in _PRAZOS_LEGAIS_ANOS:
            return True
        return any(
            (conhecida.day, conhecida.month) == (alvo.day, alvo.month) and alvo.year - conhecida.year in _PRAZOS_LEGAIS_ANOS
            for conhecida in self._datas
        )

    def tem_citacao(self, tipo: str, numero: str) -> bool:
        """A súmula/OJ/tema aparece no material que o modelo recebeu."""
        return bool(
            re.search(rf"{tipo}\w*\s*(?:n[ºo°.]*\s*)?{re.escape(numero)}\b", self._tudo)
        )


#: Prazos que DERIVAM uma data de outra (estabilidade de 12 meses, prescrição bienal e quinquenal).
_PRAZOS_LEGAIS_ANOS = {1, 2, 5}


def _data(texto: str) -> date | None:
    try:
        dia, mes, ano = (int(p) for p in texto.split("/"))
        return date(ano, mes, dia)
    except (ValueError, TypeError):
        return None


#: Palavras que não dizem QUE documento é.
_GENERICAS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas",
    "um", "uma", "ao", "aos", "que", "conforme", "segue", "seguem", "ora", "presente", "presentes",
    "incluso", "inclusa", "inclusos", "inclusas", "respectivo", "respectiva", "todos", "todas",
    "documento", "documentos", "doc", "docs", "prova", "provas", "copia", "copias", "via", "vias",
    "anexo", "anexa", "anexos", "anexas", "juntado", "juntada", "juntados", "juntadas",
    "acostado", "acostada", "acostados", "acostadas", "autor", "autora", "reclamante", "parte",
    "demais", "outros", "outras", "comprobatorio", "comprobatoria", "comprobatorios",
    "comprobatorias", "pertinente", "pertinentes", "relativos", "relativas", "referente",
    "referentes", "numero", "n", "no", "sob", "ja", "tambem", "bem", "como", "com", "pelo", "pela",
    # verbos de quem junta: "Requer a juntada dos documentos anexos" não nomeia documento
    "cuja", "cujo", "cujas", "cujos", "vez", "para", "oficio", "expedicao", "requisicao", "inss", "requer", "requerem", "requerendo", "junta", "juntar", "juntam", "apresenta", "apresentar",
    "apresentados", "apresentadas", "colaciona", "colacionar", "traz", "trazer",
}


def _sinonimos_da_skill() -> tuple[tuple[str, ...], ...]:
    grupos = peticao_skill_arquivos.validacoes_da_skill()["parametros"].get("sinonimos_de_documento") or []
    return tuple(tuple(g) for g in grupos if g)


def _termos_do_documento(
    descricao: str, sinonimos_conhecidos: tuple[tuple[str, ...], ...] = ()
) -> tuple[list[str], list[str]] | None:
    """Os sinônimos conhecidos e as palavras que identificam o documento citado."""
    texto = normalizar(descricao)
    sinonimos = [s for grupo in sinonimos_conhecidos if any(_padrao(t).search(texto) for t in grupo) for s in grupo]
    palavras = [p for p in re.findall(r"[a-z0-9]+", texto) if p not in _GENERICAS and len(p) >= 3]
    palavras = palavras[-3:]  # o núcleo da expressão fica no fim ("... declaração de hipossuficiência")
    if not sinonimos and not palavras:
        return None
    return sinonimos, palavras


# ------------------------------------------------------------------- violações


@dataclass
class Violacao:
    codigo: str
    secao: str
    trecho: str
    motivo: str
    correcao: str
    bloqueia: bool = True
    #: A citação exata, quando a violação é de súmula/OJ/tema — o `trecho` tem folga
    #: de contexto e pode conter OUTRA citação vizinha.
    citacao: str = ""

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


def _trecho(texto: str, inicio: int, fim: int, folga: int = 70) -> str:
    de, ate = max(0, inicio - folga), min(len(texto), fim + folga)
    return ("…" if de else "") + " ".join(texto[de:ate].split()) + ("…" if ate < len(texto) else "")


def _documentos_citados(secoes: dict[str, str], fontes: Fontes) -> list[Violacao]:
    violacoes = []
    total = len(fontes.numerados)
    validos = set(fontes.numeros) if fontes.numeros else set(range(1, total + 1))
    for codigo, texto in secoes.items():
        for m in re.finditer(r"\bDocumento\s+(?:n[ºo°.]*\s*)?(\d{1,3})\b", texto, re.IGNORECASE):
            numero = int(m.group(1))
            if numero in validos:
                continue
            violacoes.append(
                Violacao(
                    "DOCUMENTO_INEXISTENTE",
                    codigo,
                    _trecho(texto, m.start(), m.end()),
                    f"A peça cita o Documento {numero:02d}, mas o caso tem {total} documento(s) lido(s).",
                    f"Retire a referência ao Documento {numero:02d}. Se o fato precisa de prova que não"
                    " está nos autos, escreva [PENDENTE: juntar <documento>].",
                )
            )
    return violacoes


#: "X anexo/anexa/juntado/em anexo" — X é o documento que a peça diz existir.
_ALEGA_ANEXO = re.compile(
    r"([A-Za-zÀ-ú][A-Za-zÀ-ú0-9ºª\s/-]{2,60}?)\s*,?\s*(?:\(|—|–)?\s*"
    # "encontram-se acostados" e "deverão ser juntados" são construções
    # passivas: o objeto vem depois do verbo e o grupo anterior não identifica
    # um anexo. Referências documentais efetivas já são verificadas pelo ledger.
    r"(?:anex[oa]s?\b|em\s+anexo|inclus[oa]s?\b)",
    re.IGNORECASE,
)
#: "juntada de todos os documentos anexos (CTPS, CAT, declaração de hipossuficiência)".
_LISTA_DE_ANEXOS = re.compile(
    r"(?:documentos?|anexos?)\s+(?:anexos?|juntados?|acostados?)?\s*\(([^)]{3,400})\)", re.IGNORECASE
)


def _anexos_alegados(secoes: dict[str, str], fontes: Fontes) -> list[Violacao]:
    violacoes: list[Violacao] = []
    vistos: set[str] = set()

    def registrar(codigo: str, texto: str, inicio: int, fim: int, descricao: str) -> None:
        chave = normalizar(descricao)
        if chave in vistos or fontes.tem_anexo(descricao):
            return
        vistos.add(chave)
        violacoes.append(
            Violacao(
                "ANEXO_INEXISTENTE",
                codigo,
                _trecho(texto, inicio, fim),
                f"A peça trata «{descricao.strip()}» como anexo, mas nenhum documento do caso é isso.",
                f"Não afirme que «{descricao.strip()}» está anexo. Escreva [PENDENTE: juntar"
                f" {descricao.strip()}] no lugar.",
            )
        )

    for codigo, texto in secoes.items():
        for m in _LISTA_DE_ANEXOS.finditer(texto):
            for item in re.split(r",|;|\be\b", m.group(1)):
                if item.strip():
                    registrar(codigo, texto, m.start(1), m.end(1), item)
        for m in _ALEGA_ANEXO.finditer(texto):
            # só as últimas palavras antes de "anexo": o núcleo do que é alegado — e sem
            # as palavras de ligação da frente ("conforme declaração…" vira "declaração…")
            palavras = m.group(1).split()[-5:]
            while palavras and normalizar(palavras[0]) in _GENERICAS:
                palavras.pop(0)
            if palavras:
                registrar(codigo, texto, m.start(), m.end(), " ".join(palavras))
    return violacoes


def _numeros_sem_origem(
    secoes: dict[str, str], fontes: Fontes, contexto_normativo: re.Pattern[str] | None = None
) -> list[Violacao]:
    violacoes: list[Violacao] = []
    vistos: set[str] = set()
    for codigo, texto in secoes.items():
        for m in re.finditer(r"\b\d{2}/\d{2}/\d{4}\b", texto):
            if m.group(0) in vistos or fontes.tem_data(m.group(0)):
                continue
            vistos.add(m.group(0))
            violacoes.append(
                Violacao(
                    "DATA_SEM_ORIGEM",
                    codigo,
                    _trecho(texto, m.start(), m.end()),
                    f"A data {m.group(0)} não está em documento, entrevista ou cadastro, nem deriva de uma data deles.",
                    f"Confira a data {m.group(0)} nos documentos. Se ela não constar, troque por [PENDENTE: data].",
                )
            )
        # Números de identificação: 5+ dígitos com separadores (CPF, PIS, NB, CAT, CNPJ…)
        for m in re.finditer(r"(?<![\d,])\d[\d./-]{3,}\d(?![\d,])", texto):
            numero = m.group(0)
            if re.fullmatch(r"\d{2}/\d{2}/\d{4}", numero) or len(re.sub(r"\D", "", numero)) < 5:
                continue
            antes = texto[max(0, m.start() - 40) : m.start()]
            depois = texto[m.end() : m.end() + 3]
            if re.search(r"R\$\s*$", antes) or depois.startswith(","):
                continue  # valor em dinheiro: conferido em `_valores`
            if contexto_normativo and contexto_normativo.search(antes):
                continue  # número de norma ou de processo citado como fundamento
            if numero in vistos or fontes.tem_numero(numero):
                continue
            vistos.add(numero)
            violacoes.append(
                Violacao(
                    "NUMERO_SEM_ORIGEM",
                    codigo,
                    _trecho(texto, m.start(), m.end()),
                    f"O número {numero} não aparece em nenhum documento, na entrevista ou no cadastro.",
                    f"Retire o número {numero}. Use só números que estejam nos documentos; se o dado"
                    " faltar, escreva [PENDENTE: <dado>].",
                )
            )
    return violacoes


MARCA_NAO_VERIFICADA = "[CONFERIR: citação não verificada no acervo]"


def _re(padrao: str, multilinha: bool = False) -> re.Pattern[str]:
    return re.compile(padrao, re.IGNORECASE | (re.MULTILINE if multilinha else 0))


def _secoes_da_regra(regra: dict[str, Any], secoes: dict[str, str]) -> list[str]:
    alvo = regra.get("secoes") or ([regra["secao"]] if regra.get("secao") else "*")
    return list(secoes) if alvo == "*" else [c for c in alvo if c in secoes]


def _valor_brl(texto: str) -> float:
    return float(texto.replace(".", "").replace(",", "."))


def _itens_da_secao(regra: dict[str, Any], texto: str) -> list[str]:
    partes = re.split(regra["separador_de_itens"], "\n" + texto)
    inicio = _re(regra["inicio_de_item"])
    return [p.strip() for p in partes if inicio.match(p.strip())]


def _violacao(regra: dict[str, Any], secao: str, trecho: str, **campos: str) -> Violacao:
    return Violacao(
        regra["codigo"], secao, trecho,
        regra["mensagem"].format(**campos) if campos else regra["mensagem"],
        regra["correcao"], bool(regra.get("bloqueia", True)),
        campos.get("citacao", ""),
    )


def _regra_item(regra: dict[str, Any], secoes: dict[str, str]) -> list[Violacao]:
    """Item de lista da seção que satisfaz TODAS as condições de `quando`."""
    saida: list[Violacao] = []
    ignorar = _re(regra["ignorar_item"]) if regra.get("ignorar_item") else None
    pendente = _re(regra["pendente"]) if regra.get("pendente") else None
    for codigo in _secoes_da_regra(regra, secoes):
        for item in _itens_da_secao(regra, secoes[codigo]):
            if ignorar and ignorar.search(item):
                continue
            visoes = {
                "item": item,
                "cabeca": item.split(",")[0][:120],
                "item_sem_pendente": pendente.sub(" ", item) if pendente else item,
            }
            if all(
                (not c.get("casa") or _re(c["casa"]).search(visoes[c["em"]]))
                and (not c.get("nao_casa") or not _re(c["nao_casa"]).search(visoes[c["em"]]))
                for c in (regra.get("quando") or []) if isinstance(c, dict)
            ):
                saida.append(_violacao(regra, codigo, " ".join(item.split())[:220]))
    return saida


def _regra_soma(regra: dict[str, Any], secoes: dict[str, str]) -> list[Violacao]:
    """A soma dos valores dos itens tem de bater com o valor declarado em `total_em`."""
    ignorar = _re(regra["ignorar_item"])
    excluir = _re(regra["excluir_cabeca"])
    valor, resultado, anunciado = regra["valor"], regra["resultado"], regra["anunciado"]
    soma = 0.0
    for item in _itens_da_secao(regra, secoes.get(regra["secao"], "")):
        if ignorar.search(item) or excluir.search(item.split(",")[0][:120]):
            continue
        valores = [_valor_brl(v) for v in re.findall(valor, item)]
        if not valores:
            continue
        # O valor PEDIDO é o resultado da conta escrita, ou o anunciado; o maior valor do
        # item pode ser só a base de cálculo.
        achado = re.findall(resultado, item) or re.findall(anunciado, item, re.IGNORECASE)
        soma += _valor_brl(achado[-1]) if achado else max(valores)
    texto_total = secoes.get(regra["total_em"], "")
    total = [_valor_brl(v) for v in re.findall(valor, texto_total)[:1]]
    if total and soma and abs(total[0] - soma) > 0.01 * max(total[0], 1):
        def brl(x: float) -> str:
            return "R$ " + f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return [_violacao(regra, regra["total_em"], " ".join(texto_total.split())[:220],
                          total=brl(total[0]), soma=brl(soma))]
    return []


def _regra_topico_sem_pedido(regra: dict[str, Any], secoes: dict[str, str]) -> list[Violacao]:
    """Tópico que casa `conclui` e não casa `pede` (fora do trecho que concluiu)."""
    conclui, pede = _re(regra["conclui"]), _re(regra["pede"])
    saida: list[Violacao] = []
    for codigo in _secoes_da_regra(regra, secoes):
        for bloco in re.split(regra["divisor"], "\n" + secoes[codigo]):
            corpo = bloco.strip()
            if not corpo or not conclui.search(corpo):
                continue
            resto = corpo[len(corpo.split("\n", 1)[0]):]
            if pede.search(conclui.sub("", resto)):
                continue
            saida.append(_violacao(regra, codigo, " ".join(corpo.split())[:220]))
    return saida


def _regra_padrao_proibido(regra: dict[str, Any], secoes: dict[str, str]) -> list[Violacao]:
    padrao = _re(regra["regex"], bool(regra.get("multilinha")))
    return [
        _violacao(regra, codigo, " ".join(m.group(0).split())[:220])
        for codigo in _secoes_da_regra(regra, secoes)
        for m in padrao.finditer(secoes[codigo])
    ]


def _regra_citacao_sem_fonte(regra: dict[str, Any], secoes: dict[str, str], fontes: Fontes) -> list[Violacao]:
    """Citação (grupo 1 = espécie, grupo 2 = número) que não consta do material recebido."""
    padrao = _re(regra["regex"])
    equivalentes = regra.get("equivalentes") or {}
    saida: list[Violacao] = []
    vistos: set[tuple[str, str]] = set()
    for codigo in _secoes_da_regra(regra, secoes):
        texto = secoes[codigo]
        for m in padrao.finditer(texto):
            especie = normalizar(m.group(1)).split()[0][:5]
            chave = (especie, m.group(2))
            nomes = equivalentes.get(especie, [especie])
            if chave in vistos or any(fontes.tem_citacao(n, m.group(2)) for n in nomes):
                continue
            vistos.add(chave)
            saida.append(_violacao(
                regra, codigo, _trecho(texto, m.start(), m.end()),
                citacao=re.sub(r"\s+", " ", m.group(0)),
            ))
    return saida


def _regra_tamanho_minimo(regra: dict[str, Any], secoes: dict[str, str]) -> list[Violacao]:
    """Seção que existe mas tem menos de `minimo_chars` caracteres."""
    return [
        _violacao(regra, codigo, f"{len(secoes[codigo].strip())} caracteres")
        for codigo in _secoes_da_regra(regra, secoes)
        if secoes[codigo].strip() and len(secoes[codigo].strip()) < int(regra["minimo_chars"])
    ]


def _regra_secao_obrigatoria(regra: dict[str, Any], secoes: dict[str, str]) -> list[Violacao]:
    """Papéis de seção que a skill exige e que faltam (ou vieram vazios)."""
    return [
        _violacao(regra, codigo, "seção ausente ou vazia")
        for codigo in regra["secoes"]
        if not secoes.get(codigo, "").strip()
    ]


def _regra_citacao_literal_sem_fonte(regra: dict[str, Any], secoes: dict[str, str], fontes: Fontes) -> list[Violacao]:
    """Trecho ENTRE ASPAS que não existe, literalmente, no material recebido.

    Ementa, tese e depoimento transcritos são o ponto onde o modelo mais inventa. Cada trecho
    (separado nos cortes "[...]") de pelo menos `minimo_chars` caracteres tem de aparecer,
    normalizado, no material (documentos, entrevista, julgados, legislação, skill).
    """
    padrao = _re(regra["regex"])
    minimo = int(regra.get("minimo_chars", 40))
    saida: list[Violacao] = []
    for codigo in _secoes_da_regra(regra, secoes):
        texto = secoes[codigo]
        for m in padrao.finditer(texto):
            citado = m.group(1)
            for pedaco in re.split(r"\[\s*(?:\.\.\.|…)\s*\]|\.\.\.|…", citado):
                alvo = normalizar(re.sub(r"\*+", "", pedaco)).strip(" .,;:")
                if len(alvo) >= minimo and alvo not in fontes._tudo:  # noqa: SLF001 - mesmo módulo
                    saida.append(_violacao(regra, codigo, _trecho(texto, m.start(), m.end(), 20)))
                    break
    return saida


def _regra_afirmacao_categorica(regra: dict[str, Any], secoes: dict[str, str]) -> list[Violacao]:
    """Trecho que casa `regex` SEM nenhum `qualificadores` numa janela de `janela` caracteres em volta.

    Serve à regra "ausência de prova não é prova de ausência": afirmar categoricamente que algo não existe
    (ou usar a falta de documento como prova) sem se ancorar em "não consta dos autos", em alegação ou no ônus.
    """
    padrao, qual = _re(regra["regex"]), _re(regra["qualificadores"])
    janela = int(regra.get("janela", 200))
    saida: list[Violacao] = []
    for codigo in _secoes_da_regra(regra, secoes):
        texto = secoes[codigo]
        for m in padrao.finditer(texto):
            contexto = texto[max(0, m.start() - janela): m.end() + janela]
            if not qual.search(contexto):
                saida.append(_violacao(regra, codigo, _trecho(texto, m.start(), m.end(), 40)))
    return saida


_EXECUTORES = {
    "afirmacao_categorica_sem_qualificador": lambda r, s, f: _regra_afirmacao_categorica(r, s),
    "citacao_literal_sem_fonte": _regra_citacao_literal_sem_fonte,
    "tamanho_minimo": lambda r, s, f: _regra_tamanho_minimo(r, s),
    "secao_obrigatoria": lambda r, s, f: _regra_secao_obrigatoria(r, s),
    "item": lambda r, s, f: _regra_item(r, s),
    "soma_coerente": lambda r, s, f: _regra_soma(r, s),
    "topico_sem_pedido": lambda r, s, f: _regra_topico_sem_pedido(r, s),
    "padrao_proibido": lambda r, s, f: _regra_padrao_proibido(r, s),
    "citacao_sem_fonte": _regra_citacao_sem_fonte,
}


def executar_regras(regras: list[dict[str, Any]], secoes: dict[str, str], fontes: Fontes) -> list[Violacao]:
    """Executa as regras DECLARADAS pela skill. Tipo desconhecido é erro alto, não silêncio."""
    saida: list[Violacao] = []
    for regra in regras:
        executor = _EXECUTORES.get(regra.get("tipo"))
        if executor is None:
            raise ValueError(f"validação '{regra.get('id')}': tipo desconhecido '{regra.get('tipo')}'")
        saida.extend(executor(regra, secoes, fontes))
    return saida


# ------------------------------------------------------------------ interface


#: Marcador de pendência quebrado: termina em palavra solta ("serão", "a serem", "de")
#: ou tem outro marcador dentro.
_MARCADOR_QUEBRADO = re.compile(
    r"\[PENDENTE:(?:[^\]]*\[PENDENTE|[^\]]*\b(?:ser[ãa]o|a serem|a ser|base|de|do|da|dos|das|que|e|com|para|nos|nas)\s*\])",
    re.IGNORECASE,
)


def _marcadores_mal_formados(secoes: dict[str, str]) -> list[Violacao]:
    """`[PENDENTE: juntar comprovantes de despesas serão]` é ruído no corpo da peça."""
    violacoes: list[Violacao] = []
    for codigo, texto in secoes.items():
        for m in _MARCADOR_QUEBRADO.finditer(texto):
            violacoes.append(
                Violacao(
                    "MARCADOR_MAL_FORMADO",
                    codigo,
                    _trecho(texto, m.start(), m.end()),
                    "Marcador de pendência quebrado ou aninhado.",
                    "Escreva UMA pendência curta e completa, uma única vez por dado faltante "
                    "(ex.: [PENDENTE: comprovantes das despesas médicas]); não repita o marcador "
                    "na cadeia fato → prova e não o aninhe dentro de outro.",
                )
            )
    return violacoes


def conferir(
    secoes: list[dict[str, Any]], fontes: Fontes, validacoes: dict[str, Any] | None = None
) -> list[Violacao]:
    """Checagens genéricas do motor + as regras que a SKILL declara em `validacoes.md`."""
    por_codigo = {str(s.get("code") or ""): str(s.get("content") or "") for s in secoes}
    declaradas = validacoes if validacoes is not None else peticao_skill_arquivos.validacoes_da_skill()
    contexto = (declaradas.get("parametros") or {}).get("contexto_normativo")
    return [
        *_documentos_citados(por_codigo, fontes),
        *_anexos_alegados(por_codigo, fontes),
        *_numeros_sem_origem(por_codigo, fontes, _re(contexto) if contexto else None),
        *_marcadores_mal_formados(por_codigo),
        *executar_regras(declaradas.get("regras") or [], por_codigo, fontes),
    ]


def instrucao_de_correcao(violacoes: list[Violacao], fontes: Fontes) -> str:
    """A crítica que vai ao revisor: o defeito, onde está, e como corrigir."""
    linhas = [
        "CONFERÊNCIA AUTOMÁTICA CONTRA OS AUTOS. A minuta afirma coisas que os documentos do"
        " caso não sustentam. Corrija EXATAMENTE estes pontos, sem inventar nada no lugar:",
    ]
    for i, v in enumerate([v for v in violacoes if v.bloqueia], 1):
        linhas.append(f"\n{i}. [{v.secao}] {v.motivo}\n   Trecho: {v.trecho}\n   Correção: {v.correcao}")
    linhas.append("\nOS ÚNICOS DOCUMENTOS DO CASO (numeração que a peça deve usar):")
    for i, arquivo in zip(fontes.numeros or range(1, len(fontes.numerados) + 1), fontes.numerados):
        tipo = next((a.get("tipo") for a in fontes.anexos if a.get("arquivo") == arquivo), "") or "não classificado"
        linhas.append(f"- Documento {i:02d} — {arquivo} ({tipo})")
    linhas.append(
        "\nQualquer outro documento NÃO existe: onde a peça precisar dele, escreva [PENDENTE:"
        " juntar ...]. Não mude o que não está listado acima."
    )
    return "\n".join(linhas)


def marcar_citacoes_nao_verificadas(
    secoes: list[dict[str, Any]], violacoes: list[Violacao]
) -> list[dict[str, Any]]:
    """Carimba na PRÓPRIA peça a citação que ninguém conferiu.

    O aviso na tela some quando o `.docx` sai por e-mail; o carimbo no texto não. Uma
    vez por citação e por seção — repetir a marca em cada ocorrência poluiria a peça.
    """
    alvos = {(v.secao, v.citacao) for v in violacoes if v.codigo == "CITACAO_NAO_VERIFICADA" and v.citacao}
    saida = []
    for secao in secoes:
        conteudo = str(secao.get("content") or "")
        for codigo, citacao in alvos:
            if codigo != secao.get("code"):
                continue
            m = re.search(
                re.escape(citacao).replace(r"\ ", r"\s+")
                + r"(?:,\s*[IVXLC]+)?(?:,?\s*d[oa]\s+(?:TST|STF|STJ|SDI-?\d?))?",
                conteudo,
            )
            if m and not conteudo[m.end() :].lstrip().startswith(MARCA_NAO_VERIFICADA):
                conteudo = conteudo[: m.end()] + f" {MARCA_NAO_VERIFICADA}" + conteudo[m.end() :]
        saida.append({**secao, "content": conteudo})
    return saida


def como_achados(violacoes: list[Violacao]) -> list[dict[str, Any]]:
    """No formato que a tela já sabe mostrar (`AchadoRevisao` no frontend)."""
    return [
        {
            "severity": "BLOCKING" if v.bloqueia else "WARNING",
            "category": v.codigo,
            "section": v.secao,
            "message": f"{v.motivo} {v.correcao}",
            "detail": v.trecho,
        }
        for v in violacoes
    ]
