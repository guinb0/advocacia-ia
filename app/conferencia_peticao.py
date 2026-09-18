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
from typing import Any

__all__ = [
    "Fontes",
    "Violacao",
    "conferir",
    "como_achados",
    "instrucao_de_correcao",
    "marcar_citacoes_nao_verificadas",
    "normalizar",
    "numeros_colados",
    "SINONIMOS",
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


#: O nome que se usa e o que está escrito no documento raramente coincidem.
SINONIMOS: tuple[tuple[str, ...], ...] = (
    ("ctps", "carteira de trabalho"),
    ("rg", "identidade", "registro geral"),
    ("pis", "nis", "pasep"),
    ("cnh", "habilitacao"),
    ("trct", "termo de rescisao", "rescisao"),
    ("cat", "comunicacao de acidente"),
    ("aso", "atestado de saude ocupacional"),
    ("holerite", "contracheque", "recibo de pagamento", "demonstrativo de pagamento"),
    ("comprovante de residencia", "comprovante de endereco", "conta de luz", "conta de energia", "conta de agua"),
    ("carta de concessao", "comunicacao de decisao", "concessao do beneficio"),
    ("cnis", "cadastro nacional de informacoes sociais", "extrato previdenciario"),
)


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
        termos = _termos_do_documento(descricao)
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
        conhecida, até cinco anos adiante ou atrás (estabilidade, prescrição). Só o
        mesmo dia não basta: deixaria passar qualquer data inventada no dia 14.
        """
        alvo = _data(texto)
        if alvo is None:
            return True
        if alvo in self._datas:
            return True
        return any(
            (conhecida.day, conhecida.month) == (alvo.day, alvo.month) and abs(alvo.year - conhecida.year) <= 5
            for conhecida in self._datas
        )

    def tem_citacao(self, tipo: str, numero: str) -> bool:
        """A súmula/OJ/tema aparece no material que o modelo recebeu."""
        return bool(
            re.search(rf"{tipo}\w*\s*(?:n[ºo°.]*\s*)?{re.escape(numero)}\b", self._tudo)
        )


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
    "requer", "requerem", "requerendo", "junta", "juntar", "juntam", "apresenta", "apresentar",
    "apresentados", "apresentadas", "colaciona", "colacionar", "traz", "trazer",
}


def _termos_do_documento(descricao: str) -> tuple[list[str], list[str]] | None:
    """Os sinônimos conhecidos e as palavras que identificam o documento citado."""
    texto = normalizar(descricao)
    sinonimos = [s for grupo in SINONIMOS if any(_padrao(t).search(texto) for t in grupo) for s in grupo]
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


#: Onde a norma tem número e o número não é de documento do cliente.
_CONTEXTO_NORMATIVO = re.compile(
    r"(lei|decreto|resolu|ato|portaria|instru|emenda|provis|\bnr\b|s[uú]mula|\boj\b|tema|"
    r"art\.?|artigo|par[aá]grafo|inciso|precedente|processo|recurso|cnj|csjt|tst|trt|stf|stj)"
    r"[^\n]{0,25}$",
    re.IGNORECASE,
)


def _documentos_citados(secoes: dict[str, str], fontes: Fontes) -> list[Violacao]:
    violacoes = []
    total = len(fontes.numerados)
    for codigo, texto in secoes.items():
        for m in re.finditer(r"\bDocumento\s+(?:n[ºo°.]*\s*)?(\d{1,3})\b", texto, re.IGNORECASE):
            numero = int(m.group(1))
            if 1 <= numero <= total:
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
    r"(?:anex[oa]s?\b|em\s+anexo|juntad[oa]s?\b|acostad[oa]s?\b|inclus[oa]s?\b)",
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


def _numeros_sem_origem(secoes: dict[str, str], fontes: Fontes) -> list[Violacao]:
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
            if _CONTEXTO_NORMATIVO.search(antes):
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


def _valor(texto: str) -> float:
    return float(texto.replace(".", "").replace(",", "."))


#: Pedido que, por natureza, não leva valor próprio.
_PEDIDO_SEM_VALOR_PROPRIO = re.compile(
    r"honor[aá]rio|juros|corre[çc][ãa]o monet|gratuidade|justi[çc]a gratuita|exib|notifica|cita[çc][ãa]o"
    r"|proced[eê]ncia|produ[çc][ãa]o de prova|intima|expedi[çc][ãa]o de of[ií]cio|anota[çc][ãa]o"
    r"|reintegra",  # obrigação de fazer; a indenização substitutiva é que leva valor
    re.IGNORECASE,
)
#: Pedido sem conteúdo econômico do autor: não entra na soma nem precisa de conta,
#: MESMO que venha com valor. Na segunda rodada o modelo passou a escrever "estimado
#: em R$ 0,00" em gratuidade, citação e provas — e "custas R$ 2.018,80" como pedido.
_SEM_CONTEUDO_ECONOMICO = re.compile(
    r"gratuidade|justi[çc]a gratuita|cita[çc][ãa]o|produ[çc][ãa]o de|provas? admitid|intima|notifica"
    r"|exib|custas|honor[aá]rio|juros|corre[çc][ãa]o monet|proced[eê]ncia"
    # recolhimento previdenciário/fiscal é obrigação da ré perante a União, não
    # crédito do autor — entrou na soma do valor da causa na terceira rodada
    r"|recolhimento|contribui[çc][õo]es previdenci",
    re.IGNORECASE,
)


_ANUNCIA_VALOR = (
    r"(?:totaliz\w*|valor estimado(?:\s+de)?|estimad[oa] em|no valor de|valor de|total de|montante de)"
    r"\s*:?\s*R\$\s*([\d.]+,\d{2})"
)
#: O que vai entre [PENDENTE: …] é aviso, não texto da peça: "[PENDENTE: nº de dias ×
#: 2h × valor-hora]" não é a conta feita — é a conta que NÃO foi feita.
_PENDENTE = re.compile(r"\[PENDENTE[^\]]*\]", re.IGNORECASE)
#: Pedido cujo valor é arbitrado pelo juízo — não há conta a mostrar.
_ARBITRADO = re.compile(r"dano[s]? mora|danos? est[ée]tic|arbitr", re.IGNORECASE)
#: Sinal de que o valor tem CONTA ao lado, e não só vocabulário de conta.
#:
#: Mencionar "horas" ou "50%" não é critério: "horas extras com adicional de 50%.
#: Valor estimado: R$ 15.000,00" não diz de onde saíram os quinze mil. Conta é uma
#: operação explícita (× ou =), ou um número de meses com o valor mensal ("9 meses e
#: 5 dias, R$ 2.380,00 mensais, totalizando…"). "[PENDENTE: confirmar critério]" NÃO
#: conta: foi a brecha que o modelo usou para manter R$ 15.000,00 inventados.
_CRITERIO = re.compile(
    r"\d\s*[×x*]\s*[\dR]|[×x*]\s*\d|=\s*R\$"
    r"|\b\d+\s*meses\b.{0,160}(?:mensa|por m[êe]s|ao m[êe]s|/m[êe]s)"
    r"|(?:mensa|por m[êe]s|ao m[êe]s|/m[êe]s).{0,160}\b\d+\s*meses\b",
    re.IGNORECASE | re.DOTALL,
)


#: Como se corrige um valor sem conta. Sem saída de emergência: "[PENDENTE: confirmar
#: critério]" foi usado para manter número inventado com cara de pendência.
_PREMISSAS = (
    " Faça a conta com premissas EXPLÍCITAS — salário e período tirados dos documentos,"
    " jornada tirada do relato (dita «conforme relato») — e escreva cada premissa. Nunca"
    " um número redondo sem conta, nem [PENDENTE] no lugar da conta."
)


def _itens(claims: str) -> list[str]:
    partes = re.split(r"\n\s*(?:\*\*)?\s*(?=[a-z]\)|\d{1,2}[.)]\s)", "\n" + claims)
    return [p.strip() for p in partes if re.match(r"(?:[a-z]\)|\d{1,2}[.)])", p.strip())]


def _valores(secoes: dict[str, str]) -> list[Violacao]:
    violacoes: list[Violacao] = []
    claims = secoes.get("CLAIMS", "")
    soma = 0.0
    for item in _itens(claims):
        if re.search(r"valor da causa|d[aá]-se [àa] causa", item, re.IGNORECASE):
            continue
        if _SEM_CONTEUDO_ECONOMICO.search(item.split(",")[0][:120]):
            continue
        valores = [_valor(v) for v in re.findall(r"R\$\s*([\d.]+,\d{2})", item)]
        if valores:
            # O valor PEDIDO é o que vem anunciado ("totalizando", "valor estimado",
            # "no valor de"); o maior valor do item pode ser a base de cálculo — no
            # FGTS, o salário de R$ 2.380,00 era maior que os R$ 1.500,00 pedidos.
            # Com a conta escrita, o pedido é o RESULTADO dela: em "valor estimado de
            # R$ 2.380,00 × 9 meses = R$ 21.420,00" o anunciado é a base, não o total.
            resultado = re.findall(r"=\s*R\$\s*([\d.]+,\d{2})", item)
            anunciado = resultado or re.findall(_ANUNCIA_VALOR, item, re.IGNORECASE)
            soma += _valor(anunciado[-1]) if anunciado else max(valores)
            if not _ARBITRADO.search(item) and not _CRITERIO.search(_PENDENTE.sub(" ", item)):
                violacoes.append(
                    Violacao(
                        "VALOR_SEM_CRITERIO",
                        "CLAIMS",
                        " ".join(item.split())[:220],
                        "Valor estimado sem critério: a peça não mostra de onde saiu o número.",
                        "Escreva ao lado do valor a conta que o gera a partir dos dados dos"
                        " documentos (ex.: horas/dia × dias × meses × valor-hora × adicional)."
                        + _PREMISSAS,
                    )
                )
            continue
        if _PEDIDO_SEM_VALOR_PROPRIO.search(item.split(",")[0][:120]):
            continue
        violacoes.append(
            Violacao(
                "PEDIDO_SEM_VALOR",
                "CLAIMS",
                " ".join(item.split())[:220],
                "Pedido sem valor: o art. 840, § 1º, da CLT exige pedido certo, determinado e com"
                " indicação do valor — sem isso o pedido pode ser extinto sem resolução do mérito.",
                "Dê a este pedido um valor ESTIMADO, com o critério escrito ao lado (ex.: nº de horas"
                " × valor-hora × meses, a partir do salário dos documentos)." + _PREMISSAS,
            )
        )

    total = [_valor(v) for v in re.findall(r"R\$\s*([\d.]+,\d{2})", secoes.get("VALUE", ""))[:1]]
    if total and soma and abs(total[0] - soma) > 0.01 * max(total[0], 1):
        violacoes.append(
            Violacao(
                "VALOR_DA_CAUSA_INCOERENTE",
                "VALUE",
                " ".join(secoes.get("VALUE", "").split())[:220],
                f"O valor da causa (R$ {total[0]:,.2f}) não bate com a soma dos valores dos pedidos"
                f" (R$ {soma:,.2f}).".replace(",", "X").replace(".", ",").replace("X", "."),
                "O valor da causa é a soma dos valores dados na seção de pedidos. Não crie parcela"
                " nova só para arredondar o total — ajuste o total à soma.",
            )
        )
    return violacoes


#: Um tópico que conclui CONTRA o cliente e não pede nada.
_CONCLUI_CONTRA = re.compile(
    r"n[ãa]o se aplica|n[ãa]o h[áa] (?:atraso|parcela|direito|diferen|elementos? que indique)"
    r"|n[ãa]o (?:faz|fazem) jus|[ée] indevid[oa]|n[ãa]o se (?:formula|deduz|pleiteia) (?:o )?pedido",
    re.IGNORECASE,
)
#: Só VERBO de quem pede. "pagamento" ficou de fora de propósito: a explicação da lei
#: ("multa quando o empregador não efetuar o pagamento") o contém, e foi assim que
#: "VII – DA MULTA DO ART. 477 … não se formula pedido" escapou na segunda rodada.
_PEDE = re.compile(r"\brequer|\bpleite|faz jus|s[ãa]o devid|[ée] devid|condena[çr]|deferi", re.IGNORECASE)


def _topicos_contra_o_cliente(secoes: dict[str, str]) -> list[Violacao]:
    violacoes: list[Violacao] = []
    for codigo in ("PRELIMINARY", "LEGAL_GROUNDS", "CLAIMS"):
        texto = secoes.get(codigo, "")
        # tópicos = blocos que começam por um título em negrito ou numeração romana
        blocos = re.split(r"\n(?=\s*\*\*[IVXLC]+\s*[–—-]|\s*[IVXLC]+\s*[–—-]\s)", "\n" + texto)
        for bloco in blocos:
            corpo = bloco.strip()
            if not corpo or not _CONCLUI_CONTRA.search(corpo):
                continue
            titulo = corpo.split("\n", 1)[0]
            resto = corpo[len(titulo):]
            if _PEDE.search(_CONCLUI_CONTRA.sub("", resto)):
                continue
            violacoes.append(
                Violacao(
                    "TOPICO_CONTRA_O_CLIENTE",
                    codigo,
                    " ".join(corpo.split())[:220],
                    "Este tópico conclui que o cliente NÃO tem direito a algo — isso não pertence à"
                    " petição inicial dele.",
                    "Retire o tópico inteiro da peça. Se a observação importa, ela vai para a análise"
                    " (observações ao advogado), nunca para o texto que será protocolado.",
                )
            )
    return violacoes


_CITA_JURISPRUDENCIA = re.compile(
    r"\b(s[úu]mula(?:\s+vinculante)?|orienta[çc][ãa]o\s+jurisprudencial|\bOJ|tema)\s*(?:n[ºo°.]*\s*)?(\d{1,4})",
    re.IGNORECASE,
)
MARCA_NAO_VERIFICADA = "[CONFERIR: citação não verificada no acervo]"


def _citacoes(secoes: dict[str, str], fontes: Fontes) -> list[Violacao]:
    violacoes: list[Violacao] = []
    vistos: set[tuple[str, str]] = set()
    for codigo, texto in secoes.items():
        for m in _CITA_JURISPRUDENCIA.finditer(texto):
            tipo = normalizar(m.group(1)).split()[0][:5]  # sumul | orien | oj | tema
            chave = (tipo, m.group(2))
            if chave in vistos or fontes.tem_citacao(tipo if tipo != "orien" else "orientacao", m.group(2)):
                continue
            vistos.add(chave)
            violacoes.append(
                Violacao(
                    "CITACAO_NAO_VERIFICADA",
                    codigo,
                    _trecho(texto, m.start(), m.end()),
                    f"«{m.group(0)}» foi citada de memória: não está no material do acervo recebido"
                    " nesta geração, e o acervo ainda não tem catálogo de súmulas para conferir.",
                    "Mantenha só se o advogado conferir o número e o texto na fonte oficial.",
                    bloqueia=False,
                    citacao=re.sub(r"\s+", " ", m.group(0)),
                )
            )
    return violacoes


# ------------------------------------------------------------------ interface


def conferir(secoes: list[dict[str, Any]], fontes: Fontes) -> list[Violacao]:
    """Tudo o que a peça afirma e os autos não sustentam."""
    por_codigo = {str(s.get("code") or ""): str(s.get("content") or "") for s in secoes}
    return [
        *_documentos_citados(por_codigo, fontes),
        *_anexos_alegados(por_codigo, fontes),
        *_numeros_sem_origem(por_codigo, fontes),
        *_valores(por_codigo),
        *_topicos_contra_o_cliente(por_codigo),
        *_citacoes(por_codigo, fontes),
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
    for i, arquivo in enumerate(fontes.numerados, 1):
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
