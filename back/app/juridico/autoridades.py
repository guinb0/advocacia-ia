"""Base jurídica verificada (camada B): autoridades, busca híbrida e gate de citação.

Uma AUTORIDADE é qualquer coisa que a peça possa citar como norma ou precedente: artigo de lei,
súmula, OJ, tema, decisão de controle concentrado, acórdão. Cada uma tem vigência, versão, status
(vigente, revogado, superado, cancelado), "superado por" e fonte oficial com data de verificação.

O GATE DE CITAÇÃO extrai toda citação do texto e exige uma autoridade do registro, vigente na data de
referência do caso. Sem autoridade: REQUIRES_LEGAL_RESEARCH, nunca o número completado de memória.
Autoridade superada: SUPERADA, com a que a substituiu. Skill e peças do acervo NÃO entram no registro:
dizem como escrever, não o que a lei diz hoje.

Nada aqui conhece tese jurídica. O código sabe reconhecer a FORMA de uma citação ("Súmula nº N do TST",
"art. N da CLT"); o conteúdo, a vigência e a superação vêm dos dados do registro.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Iterable

STATUS_VIGENTE = "vigente"
STATUS_INATIVOS = {"revogado", "superado", "cancelado", "suspenso"}

VALIDADA = "VALIDADA"
VALIDADA_SEM_VIGENCIA = "VALIDADA_SEM_VIGENCIA"
REQUIRES_LEGAL_RESEARCH = "REQUIRES_LEGAL_RESEARCH"
SUPERADA = "SUPERADA"
FORA_DE_VIGENCIA = "FORA_DE_VIGENCIA"
AMBIGUA = "AMBIGUA"
APROVADAS = {VALIDADA, VALIDADA_SEM_VIGENCIA}


def norm(texto: Any) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def _digitos(texto: Any) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def _data(valor: Any) -> date | None:
    if isinstance(valor, date):
        return valor
    s = str(valor or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s) or None
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.match(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", s)
    if m:
        try:
            return date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            return None
    return None


@dataclass
class Autoridade:
    id: str
    tipo: str                      # artigo | lei | sumula | sumula_vinculante | oj | tema | controle_concentrado | precedente
    chave: str                     # forma normalizada que o gate casa (ver `chave_de`)
    titulo: str = ""
    texto: str = ""
    norma: str = ""
    artigo: str = ""
    paragrafo: str = ""
    inciso: str = ""
    alinea: str = ""
    tribunal: str = ""
    orgao: str = ""
    classe: str = ""
    numero: str = ""
    tema: str = ""
    assunto: str = ""
    tese: str = ""
    data: str = ""
    vigencia_inicio: str = ""
    vigencia_fim: str = ""
    versao: str = ""
    status: str = STATUS_VIGENTE
    superado_por: str = ""
    vinculante: bool = False
    transito_em_julgado: bool | None = None
    fonte_oficial: str = ""
    url: str = ""
    verificado_em: str = ""
    verificada: bool = False
    origem: str = "registro"
    #: expressões que caracterizam a tese (para reconhecer o critério superado mesmo sem número citado)
    marcadores: list[str] = field(default_factory=list)

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)

    def vigente_em(self, referencia: date | None) -> bool | None:
        """True/False quando a vigência é conhecida; None quando o registro não traz datas."""
        inicio, fim = _data(self.vigencia_inicio), _data(self.vigencia_fim)
        if self.status in STATUS_INATIVOS and not fim:
            return False
        if not inicio and not fim:
            return None if self.status == STATUS_VIGENTE else False
        if referencia is None:
            return self.status == STATUS_VIGENTE and not fim
        if inicio and referencia < inicio:
            return False
        if fim and referencia >= fim:
            return False
        return True


# ------------------------------------------------------------------ chaves e extração de citações

#: Grafias da mesma norma. É vocabulário (como a norma é escrita), não conteúdo jurídico.
_NORMAS = (
    (r"clt|consolida[cç][aã]o das leis do trabalho|decreto-lei n?[ºo°.]?\s*5\.?452", "clt"),
    (r"cf(?:/88|/1988)?|crfb(?:/88)?|constitui[cç][aã]o(?: federal| da rep[uú]blica)?", "cf"),
    (r"cpc(?:/2015)?|c[oó]digo de processo civil", "cpc"),
    (r"cc(?:/2002)?|c[oó]digo civil", "cc"),
    (r"cdc|c[oó]digo de defesa do consumidor", "cdc"),
)


def chave_da_norma(texto: str) -> str:
    t = norm(texto).strip(" .,;")
    lei = re.compile(r"\blei(?: complementar)?\s*(?:n[ºo°.]*\s*)?(\d[\d.]*)")
    m = lei.match(t)
    if m:
        return f"lei{_digitos(m[1])}"
    for padrao, chave in _NORMAS:
        if re.search(rf"(?<![a-z])(?:{padrao})(?![a-z])", t):
            return chave
    m = re.search(r"\bdecreto(?!-lei)\s*(?:n[ºo°.]*\s*)?(\d[\d.]*)", t)
    if m:
        return f"decreto{_digitos(m[1])}"
    m = lei.search(t)
    if m:
        return f"lei{_digitos(m[1])}"
    return re.sub(r"\W+", "", t)[:30]


def _tribunal(texto: str) -> str:
    t = norm(texto)
    if re.search(r"\bstf\b|supremo tribunal", t):
        return "stf"
    if re.search(r"\bstj\b|superior tribunal de justica", t):
        return "stj"
    if re.search(r"\btst\b|tribunal superior do trabalho", t):
        return "tst"
    m = re.search(r"\btrt[\s-]*(\d{1,2})", t)
    return f"trt{int(m[1])}" if m else ""


@dataclass
class Citacao:
    tipo: str
    chave: str
    trecho: str
    inicio: int
    detalhe: dict[str, str] = field(default_factory=dict)

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


_ORD = r"(?:n[ºo°.]*\s*)?"
_NUM = r"(\d[\d.]*)"
_PADROES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sumula_vinculante", re.compile(rf"s[uú]mula\s+vinculante\s+{_ORD}{_NUM}", re.I)),
    ("sumula", re.compile(rf"s[uú]mula\s+{_ORD}{_NUM}(?:\s*,?\s*(?:item\s+)?[IVXL]+\s*,?)?(?:\s*,?\s*d[oa]\s+(?:colendo\s+|egr[eé]gio\s+)?(TST|STF|STJ|TRT[\s-]*\d{{1,2}}|Tribunal Superior do Trabalho|Supremo Tribunal Federal|Superior Tribunal de Justi[cç]a))?", re.I)),
    ("oj", re.compile(rf"(?:\bOJ\b|orienta[cç][aã]o jurisprudencial)\s+(?:transit[oó]ria\s+)?{_ORD}{_NUM}(?:\s*,?\s*d[ae]\s+(?:colenda\s+)?(S?B?DI[\s-]*[12I]+|SDC|SBDI[\s-]*[12I]+|Tribunal Pleno))?", re.I)),
    ("tema", re.compile(rf"\btema\s+(?:de\s+repercuss[aã]o\s+geral\s+)?{_ORD}{_NUM}(?:\s*(?:,|d[ao]|da|de)?\s*(?:repercuss[aã]o geral|tabela de)?\s*(?:do\s+|da\s+)?(STF|TST|STJ|IRR|recursos? repetitivos?|repercuss[aã]o geral))?", re.I)),
    ("controle_concentrado", re.compile(r"\b(ADC|ADI|ADIn|ADPF|ADO)\s*(?:n[ºo°.]*\s*)?(\d[\d.]*)", re.I)),
    ("processo", re.compile(r"\b(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})\b")),
    ("artigo", re.compile(
        r"\bart(?:igo)?s?\.?\s*(\d+)\s*[º°o]?(?:-([A-Z]))?"
        r"((?:\s*,?\s*(?:§\s*\d+\s*[º°o]?|par[aá]grafo [uú]nico|caput|inciso\s+[IVXL]+|[IVXL]+\b|al[ií]nea\s+\"?[a-z]\"?|\"[a-z]\"))*)"
        r"\s*,?\s*(?:d[aoe]s?\s+|na\s+|no\s+)?"
        r"(CLT|CF(?:/88|/1988)?|CRFB(?:/88)?|CPC(?:/2015)?|CC(?:/2002)?|CDC|Constitui[cç][aã]o(?: Federal| da Rep[uú]blica)?|Consolida[cç][aã]o das Leis do Trabalho|C[oó]digo (?:de Processo )?Civil|Lei(?: Complementar)?\s*(?:n[ºo°.]*\s*)?[\d.]+(?:/\d{2,4})?)",
        re.I)),
)


def _tribunal_padrao(tipo: str, capturado: str, contexto: str) -> str:
    if capturado:
        t = _tribunal(capturado)
        if t:
            return t
        if re.search(r"irr|repetitiv", capturado, re.I):
            return "tst"
        if re.search(r"repercuss", capturado, re.I):
            return "stf"
    if tipo == "sumula_vinculante" or tipo == "controle_concentrado":
        return "stf"
    if tipo == "oj":
        return "tst"
    return _tribunal(contexto) or "?"


def _orgao_oj(capturado: str) -> str:
    t = norm(capturado).replace(" ", "").replace("-", "")
    if not t:
        return "sdi1"
    if "sdc" in t:
        return "sdc"
    if "pleno" in t:
        return "pleno"
    return "sdi2" if t.endswith("2") or t.endswith("ii") else "sdi1"


def extrair_citacoes(texto: str) -> list[Citacao]:
    """Toda referência a norma ou precedente que aparece no texto, com a chave que o registro casa."""
    achadas: list[Citacao] = []
    ocupado: list[tuple[int, int]] = []

    def livre(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in ocupado)

    for tipo, padrao in _PADROES:
        for m in padrao.finditer(texto or ""):
            if not livre(m.start(), m.end()):
                continue
            janela = texto[max(0, m.start() - 40): m.end() + 60]
            if tipo in ("sumula", "sumula_vinculante"):
                trib = _tribunal_padrao(tipo, m.group(2) if tipo == "sumula" else "", janela)
                chave = f"{'sv' if tipo == 'sumula_vinculante' else 'sumula'}:{trib}:{_digitos(m.group(1))}"
            elif tipo == "oj":
                chave = f"oj:{_orgao_oj(m.group(2) or '')}:{_digitos(m.group(1))}"
            elif tipo == "tema":
                chave = f"tema:{_tribunal_padrao(tipo, m.group(2) or '', janela)}:{_digitos(m.group(1))}"
            elif tipo == "controle_concentrado":
                classe = m.group(1).upper().replace("ADIN", "ADI")
                chave = f"{classe.lower()}:stf:{_digitos(m.group(2))}"
            elif tipo == "processo":
                chave = f"processo:{_digitos(m.group(1))}"
            else:
                det = m.group(3) or ""
                detalhe = {
                    "artigo": m.group(1) + (f"-{m.group(2).upper()}" if m.group(2) else ""),
                    "paragrafo": (re.search(r"§\s*(\d+)", det) or [None, ""])[1] or ("unico" if re.search(r"par[aá]grafo [uú]nico", det, re.I) else ""),
                    "inciso": (re.search(r"(?:inciso\s+)?\b([IVXL]+)\b", det) or [None, ""])[1],
                    "alinea": (re.search(r"(?:al[ií]nea\s+)?\"?\b([a-z])\b\"?", re.sub(r"[IVXL]+|§\s*\d+|par[aá]grafo [uú]nico|caput|inciso|al[ií]nea", " ", det, flags=re.I)) or [None, ""])[1],
                    "norma": chave_da_norma(m.group(4)),
                }
                chave = f"art:{detalhe['norma']}:{detalhe['artigo'].lower()}"
                achadas.append(Citacao("artigo", chave, m.group(0).strip(), m.start(), detalhe))
                ocupado.append((m.start(), m.end()))
                continue
            achadas.append(Citacao(tipo, chave, m.group(0).strip(), m.start()))
            ocupado.append((m.start(), m.end()))
    return sorted(achadas, key=lambda c: c.inicio)


def chave_de(a: Autoridade) -> str:
    """Chave canônica de uma autoridade a partir dos seus campos estruturados."""
    if a.chave:
        return a.chave
    trib = norm(a.tribunal).replace(" ", "") or "?"
    if a.tipo == "artigo":
        return f"art:{chave_da_norma(a.norma)}:{norm(a.artigo).replace(' ', '')}"
    if a.tipo == "sumula_vinculante":
        return f"sv:stf:{_digitos(a.numero)}"
    if a.tipo == "sumula":
        return f"sumula:{trib}:{_digitos(a.numero)}"
    if a.tipo == "oj":
        return f"oj:{_orgao_oj(a.orgao)}:{_digitos(a.numero)}"
    if a.tipo == "tema":
        return f"tema:{trib}:{_digitos(a.numero or a.tema)}"
    if a.tipo == "controle_concentrado":
        return f"{norm(a.classe)}:stf:{_digitos(a.numero)}"
    if a.tipo == "precedente":
        return f"processo:{_digitos(a.numero)}"
    if a.tipo == "lei":
        return f"lei:{chave_da_norma(a.norma or a.numero)}"
    return f"{a.tipo}:{norm(a.numero)}"


# ------------------------------------------------------------------ hierarquia

def prioridade(a: Autoridade, trt_competente: str = "") -> int:
    """0 = mais forte. Norma vem antes; depois STF vinculante → TST Pleno/IRR → SDI → Turmas → TRT competente → demais."""
    if a.tipo in ("artigo", "lei"):
        return 0
    t, o = norm(a.tribunal).replace(" ", ""), norm(a.orgao)
    if t == "stf" and (a.vinculante or a.tipo in ("sumula_vinculante", "controle_concentrado", "tema")):
        return 1
    if t == "tst" and (a.tipo in ("sumula", "tema") or re.search(r"pleno|irr|repetitiv|incidente", o)):
        return 2
    if t == "tst" and (a.tipo == "oj" or re.search(r"s?b?di", o)):
        return 3
    if t == "tst":
        return 4
    if t and trt_competente and t == norm(trt_competente).replace(" ", "").replace("-", ""):
        return 5
    if t.startswith("trt"):
        return 6
    return 7


#: Meia-vida do peso de recência (anos). Decaimento suave: autoridade antiga perde pouco e nunca é descartada.
RECENCIA_ANOS = 10.0


def recencia(a: Autoridade, referencia: date | None) -> float:
    """1.0 para autoridade da data de referência, decaindo suavemente com a idade; 0.5 quando a data é desconhecida."""
    d = _data(a.data) or _data(a.vigencia_inicio)
    if not d or not referencia:
        return 0.5
    anos = max(0.0, (referencia - d).days / 365.25)
    return math.exp(-anos / RECENCIA_ANOS)


# ------------------------------------------------------------------ registro + busca híbrida

def _tokens(texto: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]{3,}", norm(texto))]


class Registro:
    """Autoridades disponíveis para UMA geração (banco verificado + o que a recuperação trouxe).

    Implementação em memória de `busca.ProvedorDeAutoridades`.
    """

    def __init__(self, autoridades: Iterable[Autoridade] = (), *, alertas: list[str] | None = None):
        self.autoridades: list[Autoridade] = []
        self.por_chave: dict[str, list[Autoridade]] = {}
        self.por_id: dict[str, Autoridade] = {}
        self.alertas: list[str] = list(alertas or [])
        for a in autoridades:
            self.adicionar(a)

    def adicionar(self, a: Autoridade) -> None:
        if a.id in self.por_id:
            return
        a.chave = chave_de(a)
        self.autoridades.append(a)
        self.por_id[a.id] = a
        self.por_chave.setdefault(a.chave, []).append(a)

    def __len__(self) -> int:
        return len(self.autoridades)

    def _documento(self, a: Autoridade) -> list[str]:
        return _tokens(" ".join([a.titulo, a.texto[:3000], a.tese, a.assunto, a.tema, a.norma, " ".join(a.marcadores)]))

    def buscar(
        self, consulta: str, *, data_referencia: date | None = None, tipos: Iterable[str] | None = None,
        k: int = 8, vetoriais: dict[str, float] | None = None, incluir_inativas: bool = False, trt_competente: str = "",
    ) -> list[tuple[Autoridade, float]]:
        """BM25 + ranking vetorial (fusão por posição recíproca) + filtro de metadados + reordenação pela hierarquia,
        verificação, vinculância, recência (decaimento suave) e status (inativa, quando incluída, vem depois)."""
        tipos = set(tipos or [])
        candidatos = [a for a in self.autoridades if (not tipos or a.tipo in tipos)
                      and (incluir_inativas or a.vigente_em(data_referencia) is not False)]
        if not candidatos:
            return []
        docs = [self._documento(a) for a in candidatos]
        q = set(_tokens(consulta))
        n, media = len(docs), (sum(len(d) for d in docs) / len(docs)) or 1.0
        df: dict[str, int] = {}
        for d in docs:
            for t in set(d):
                df[t] = df.get(t, 0) + 1
        bm25: list[float] = []
        for d in docs:
            freq: dict[str, int] = {}
            for t in d:
                freq[t] = freq.get(t, 0) + 1
            s = 0.0
            for t in q:
                if t in freq:
                    idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                    s += idf * freq[t] * 2.2 / (freq[t] + 1.2 * (0.25 + 0.75 * len(d) / media))
            bm25.append(s)
        ordem_lexica = sorted(range(n), key=lambda i: bm25[i], reverse=True)
        rrf = [0.0] * n
        for pos, i in enumerate(ordem_lexica):
            if bm25[i] > 0:
                rrf[i] += 1 / (60 + pos)
        if vetoriais:
            ordem_vetorial = sorted((i for i in range(n) if candidatos[i].id in vetoriais), key=lambda i: vetoriais[candidatos[i].id], reverse=True)
            for pos, i in enumerate(ordem_vetorial):
                rrf[i] += 1 / (60 + pos)
        pontuados = []
        for i, a in enumerate(candidatos):
            if rrf[i] <= 0:
                continue
            s = (rrf[i] + 0.004 * (7 - prioridade(a, trt_competente)) + (0.003 if a.verificada else 0.0)
                 + (0.001 if a.vinculante else 0.0) + 0.002 * recencia(a, data_referencia)
                 - (0.006 if a.vigente_em(data_referencia) is False else 0.0))
            pontuados.append((a, round(s, 6)))
        return sorted(pontuados, key=lambda x: x[1], reverse=True)[:k]

    def consultar(self, consulta: str, filtros: Any, top_k: int) -> list[tuple[Autoridade, float]]:
        return self.buscar(consulta, data_referencia=filtros.data_referencia, tipos=filtros.tipos or None, k=top_k,
                           incluir_inativas=filtros.incluir_inativas, trt_competente=filtros.trt_competente)

    def por_referencia(self, referencia: str) -> Autoridade | None:
        if not referencia:
            return None
        return self.por_id.get(referencia) or next(iter(self.por_chave.get(referencia, [])), None)

    def inativas_com_marcadores(self, data_referencia: date | None) -> list[Autoridade]:
        return [a for a in self.autoridades if a.marcadores and a.vigente_em(data_referencia) is False]

    def resolver(self, citacao: Citacao, data_referencia: date | None) -> dict[str, Any]:
        """Uma citação contra o registro. Devolve status, authority_id e, se superada, por quem."""
        lista = list(self.por_chave.get(citacao.chave, []))
        if not lista and citacao.chave.startswith("tema:?:"):
            num = citacao.chave.rsplit(":", 1)[1]
            lista = [a for c, v in self.por_chave.items() if c.startswith("tema:") and c.endswith(f":{num}") for a in v]
            if len({a.chave for a in lista}) > 1:
                return {"status": AMBIGUA, "authority_id": None, "motivo": "tema sem tribunal e com mais de um registro"}
        if citacao.tipo == "artigo" and lista:
            d = citacao.detalhe
            especificos = [a for a in lista if (not a.paragrafo or norm(a.paragrafo) == norm(d.get("paragrafo")))
                           and (not a.inciso or norm(a.inciso) == norm(d.get("inciso")))]
            lista = especificos or lista
        if not lista:
            return {"status": REQUIRES_LEGAL_RESEARCH, "authority_id": None, "motivo": "nenhuma autoridade recuperada/validada"}
        vigentes = [a for a in lista if a.vigente_em(data_referencia) is True]
        sem_data = [a for a in lista if a.vigente_em(data_referencia) is None]
        if vigentes:
            a = sorted(vigentes, key=lambda x: (x.verificada, x.versao), reverse=True)[0]
            return {"status": VALIDADA if a.verificada else VALIDADA_SEM_VIGENCIA, "authority_id": a.id,
                    "motivo": "" if a.verificada else "texto recuperado de fonte, vigência não verificada no registro"}
        if sem_data:
            a = sem_data[0]
            return {"status": VALIDADA_SEM_VIGENCIA, "authority_id": a.id, "motivo": "registro sem datas de vigência"}
        a = sorted(lista, key=lambda x: str(x.vigencia_fim or ""), reverse=True)[0]
        status = SUPERADA if a.superado_por or a.status == "superado" else FORA_DE_VIGENCIA
        return {"status": status, "authority_id": a.id, "superado_por": a.superado_por,
                "motivo": f"{a.status} em {a.vigencia_fim or 'data não informada'}" + (f"; substituída por {a.superado_por}" if a.superado_por else "")}


# ------------------------------------------------------------------ gate

def gate(texto: str, registro: Any, data_referencia: date | None) -> list[dict[str, Any]]:
    """Cada citação do texto com o seu status no registro. Nada é completado de memória."""
    saida = []
    for c in extrair_citacoes(texto):
        r = registro.resolver(c, data_referencia)
        saida.append({**c.como_dict(), **r, "aprovada": r["status"] in APROVADAS})
    return saida


def criterios_superados(texto: str, registro: Any, data_referencia: date | None) -> list[dict[str, Any]]:
    """Critério de autoridade superada usado SEM citar o número (ex.: o parâmetro antigo da gratuidade)."""
    alvo = norm(texto)
    achados = []
    for a in registro.inativas_com_marcadores(data_referencia):
        for m in a.marcadores:
            if norm(m) and norm(m) in alvo:
                achados.append({"authority_id": a.id, "chave": a.chave, "marcador": m, "superado_por": a.superado_por,
                                "motivo": f"critério de {a.titulo or a.chave} ({a.status}) usado no texto"})
                break
    return achados


def bloco_para_prompt(autoridades: Iterable[Autoridade], *, limite_texto: int = 900) -> str:
    """O que a redação PODE citar, cada item com o seu authority_id."""
    linhas = ["=== BASE JURÍDICA VERIFICADA (cite SOMENTE estas autoridades; cada citação leva o authority_id) ==="]
    for a in autoridades:
        cab = f"[{a.id}] {a.titulo or a.chave} — {a.tipo}"
        if a.tribunal:
            cab += f" | {a.tribunal.upper()} {a.orgao}".rstrip()
        if a.vigencia_inicio or a.vigencia_fim:
            cab += f" | vigência {a.vigencia_inicio or '?'} a {a.vigencia_fim or 'atual'}"
        if not a.verificada:
            cab += " | vigência NÃO verificada"
        linhas.append(cab)
        corpo = (a.tese or a.texto or "").strip()
        if corpo:
            linhas.append("   " + " ".join(corpo.split())[:limite_texto])
    linhas.append("Fora desta lista: não cite número de artigo, súmula, OJ, tema ou processo — escreva [REQUIRES_LEGAL_RESEARCH: <o que pesquisar>].")
    return "\n".join(linhas)


# ------------------------------------------------------------------ autoridades a partir do que o RAG já recupera

_ART_NO_TEXTO = re.compile(r"(?m)^\s*Art\.\s*(\d+)\s*[º°o]?(?:-([A-Z]))?\.?\s*(.{0,1200})")


def de_trechos_de_legislacao(trechos: Iterable[Any]) -> list[Autoridade]:
    """Artigos de texto legal oficial recuperado. Sem datas de vigência → VALIDADA_SEM_VIGENCIA (alerta, não aprovação plena)."""
    saida: list[Autoridade] = []
    for t in trechos or []:
        meta = getattr(t, "metadados", {}) or {}
        norma = chave_da_norma(f"{getattr(t, 'titulo', '')} {getattr(t, 'identificador', '')}")
        texto = getattr(t, "texto", "") or ""
        for m in _ART_NO_TEXTO.finditer(texto):
            artigo = m[1] + (f"-{m[2].upper()}" if m[2] else "")
            corpo = m[3]
            revogado = bool(re.search(r"\(revogad[oa]", corpo[:200], re.I))
            saida.append(Autoridade(
                id=f"lei:{norma}:art{artigo.lower()}", tipo="artigo", chave=f"art:{norma}:{artigo.lower()}",
                titulo=f"art. {artigo} ({getattr(t, 'titulo', '') or norma})", texto=corpo, norma=norma, artigo=artigo,
                status="revogado" if revogado else STATUS_VIGENTE,
                vigencia_inicio=str(meta.get("vigencia_inicio") or ""), vigencia_fim=str(meta.get("vigencia_fim") or ""),
                fonte_oficial=str(meta.get("fonte_oficial") or meta.get("origem") or ""), url=str(getattr(t, "url", "") or ""),
                verificado_em=str(meta.get("verificado_em") or meta.get("consultado_em") or ""),
                verificada=str(meta.get("status_verificacao") or "").upper() == "VERIFIED" and bool(meta.get("vigencia_inicio")),
                origem="rag_legislacao",
            ))
    return saida


def de_trechos_de_precedentes(trechos: Iterable[Any]) -> list[Autoridade]:
    """Acórdãos recuperados. Só os com selo VERIFIED chegam aqui (ver `recuperacao_por_tese.apenas_verificados`)."""
    saida: list[Autoridade] = []
    for t in trechos or []:
        meta = getattr(t, "metadados", {}) or {}
        processo = _digitos(meta.get("numero_processo"))
        if not processo:
            continue
        saida.append(Autoridade(
            id=f"proc:{processo}", tipo="precedente", chave=f"processo:{processo}",
            titulo=str(getattr(t, "titulo", "") or ""), texto=str(getattr(t, "texto", "") or "")[:2000],
            tribunal=str(meta.get("tribunal") or ""), orgao=str(meta.get("orgao_julgador") or ""),
            numero=processo, tema=str(meta.get("tema") or ""), tese=str(meta.get("tese_aplicada") or ""),
            data=str(meta.get("julgado_em") or meta.get("data") or ""),
            verificada=str(meta.get("status_verificacao") or "").upper() == "VERIFIED",
            fonte_oficial=str(meta.get("origem") or ""), url=str(getattr(t, "url", "") or ""), origem="rag_precedente",
        ))
    return saida


def de_registro_bruto(linhas: Iterable[dict[str, Any]]) -> list[Autoridade]:
    """Linhas da tabela `autoridades_juridicas` (ou de um arquivo de importação) em autoridades."""
    campos = set(Autoridade.__dataclass_fields__)
    saida = []
    for linha in linhas or []:
        dados = {k: v for k, v in dict(linha).items() if k in campos and v is not None}
        if not dados.get("id") or not dados.get("tipo"):
            continue
        dados.setdefault("chave", "")
        for k in ("data", "vigencia_inicio", "vigencia_fim", "verificado_em"):
            if k in dados and not isinstance(dados[k], str):
                dados[k] = str(dados[k])
        dados["marcadores"] = list(dados.get("marcadores") or [])
        saida.append(Autoridade(**dados))
    return saida
