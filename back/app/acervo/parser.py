"""Texto oficial → árvore de dispositivos com ids estáveis.

Id é o caminho na árvore, não a posição no arquivo: `art-482`, `art-482.par-1`, `art-482.par-unico`,
`art-7.inc-xviii`, `art-482.par-1.inc-ii.ali-a`. Disposições transitórias levam o prefixo `adct.`
(a Constituição repete a numeração no ADCT). Repetição restante no mesmo documento ganha `~2`, `~3`.
O id antigo do ingestor ("art-482-310", posicional) mudava sempre que a lei ganhava um artigo
antes; este não muda.

O texto do ARTIGO é o trecho inteiro, do "Art." até o próximo, como no ingestor anterior: é ele que
vira embedding (um chunk por artigo) e é nele que o Citation Gate procura parágrafo e inciso.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from . import encoding

VERSAO_PARSER = "acervo-parser/2.0"

#: "Art. 1º", "Art. 5o", "Art. 482-A", "Art. 1.001." (milhar com ponto, comum no Código Civil).
ARTIGO = re.compile(r"(?im)^Art\.\s*(\d{1,3}(?:\.\d{3})*|\d+)\s*([ºo°])?(?:\s*-\s*([A-Z]{1,2}))?(?=[\s.:]|$)")
_PARAGRAFO = re.compile(r"^§\s*(\d+)\s*[ºo°]?(?:\s*-\s*([A-Z]))?(?=[\s.:-]|$)")
_PARAGRAFO_UNICO = re.compile(r"(?i)^par[áa]grafo\s+[úu]nico\b")
_INCISO = re.compile(r"^([IVXLC]+)(?:\s*-\s*([A-Z]))?\s*[-–—]\s+")
_ALINEA = re.compile(r"^([a-z])\)\s+")
_REVOGADO = re.compile(r"(?i)^\(?\s*(revogad[oa]s?|vetad[oa]s?)\b")
_ESTRUTURA = re.compile(r"(?i)^(livro|t[íi]tulo|cap[íi]tulo|se[çc][ãa]o|subse[çc][ãa]o)\b")
_ESTRUTURA_NUMERADA = re.compile(r"(?i)^(livro|t[íi]tulo|cap[íi]tulo|se[çc][ãa]o|subse[çc][ãa]o)\s+([IVXLCDM]+|[úu]nic[oa]|\d+)\b")
_ADCT = re.compile(r"(?i)^ato\s+das\s+disposi[çc][õo]es\s+constitucionais\s+transit[óo]rias")
REFERENCIA = re.compile(r"(?i)\b(?:Lei|Decreto(?:-Lei)?|Emenda Constitucional|Medida Provis[óo]ria)\s*(?:n[ºo.]?\s*)?\d+[\d./-]*")

#: Tags cujo texto NÃO é a redação vigente: tachado = redação revogada no Planalto compilado.
_IGNORAR = {"script", "style", "noscript", "strike", "s", "del"}
_QUEBRA = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote"}


_TACHADO = re.compile(r"line-through", re.I)
_EM_LINHA = {"span", "font", "strike", "s", "del", "a", "b", "i", "u", "em", "strong", "sup", "sub", "small"}


class _Extrator(HTMLParser):
    """Texto vigente do HTML oficial.

    O Planalto marca a redação revogada de dois jeitos: `<strike>` e `style="text-decoration:line-through"`
    (em `span`/`font`/`p`). Os dois saem. O HTML de lá nem sempre fecha as tags, então o tachado aberto
    dentro de um parágrafo termina, no máximo, com o parágrafo.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self.abertas: dict[str, int] = {}
        self.ignorando: list[tuple[str, int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _QUEBRA:
            # `<p>` não se aninha: um novo fecha o anterior, mesmo sem `</p>`.
            self.ignorando = [(t, n) for t, n in self.ignorando if t not in _EM_LINHA and not (tag == "p" and t == "p")]
            self.partes.append("\n")
        if tag in ("br", "img", "hr", "meta", "link", "input"):
            return
        self.abertas[tag] = self.abertas.get(tag, 0) + 1
        estilo = next((v or "" for k, v in attrs if k == "style"), "")
        if tag in _IGNORAR or _TACHADO.search(estilo):
            self.ignorando.append((tag, self.abertas[tag]))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _QUEBRA:
            self.partes.append("\n")

    def handle_endtag(self, tag: str) -> None:
        nivel = self.abertas.get(tag, 0)
        if self.ignorando and self.ignorando[-1] == (tag, nivel):
            self.ignorando.pop()
        if nivel:
            self.abertas[tag] = nivel - 1
        if tag in _QUEBRA:
            self.ignorando = [(t, n) for t, n in self.ignorando if t not in _EM_LINHA]
            self.partes.append("\n")

    def handle_data(self, data: str) -> None:
        # Quebra de linha dentro do HTML é espaço (a Câmara quebra "Art.\n482." no meio do parágrafo);
        # linha nova só vem das tags de bloco.
        if not self.ignorando:
            self.partes.append(re.sub(r"\s+", " ", data))


def texto_do_html(html: str) -> str:
    p = _Extrator()
    p.feed(html.replace("\x00", ""))
    p.close()
    return encoding.normalizar("".join(p.partes))


def sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def numero_do_artigo(numero: str, sufixo: str | None = None) -> str:
    """"1.001" → "1001", "482" + "A" → "482-a". É a forma que `juridico.autoridades` usa na chave."""
    n = numero.replace(".", "")
    return f"{n}-{sufixo.lower()}" if sufixo else n


@dataclass
class No:
    dispositivo_id: str
    tipo_no: str                # artigo | paragrafo | inciso | alinea
    artigo: str
    paragrafo: str = ""
    inciso: str = ""
    alinea: str = ""
    parent: str = ""
    texto: str = ""
    ordem: int = 0
    rotulo: str = ""
    contexto: list[str] = field(default_factory=list)
    status: str = "VIGENTE"     # VIGENTE | REVOGADA

    @property
    def hash(self) -> str:
        return sha256(self.texto)

    def como_dict(self) -> dict:
        return {"dispositivo_id": self.dispositivo_id, "tipo_no": self.tipo_no, "artigo": self.artigo, "paragrafo": self.paragrafo,
                "inciso": self.inciso, "alinea": self.alinea, "parent": self.parent, "texto": self.texto, "ordem": self.ordem,
                "rotulo": self.rotulo, "contexto": list(self.contexto), "status": self.status, "content_hash": self.hash}


VIGENTE, REVOGADA = "VIGENTE", "REVOGADA"


def _status(texto_sem_rotulo: str) -> str:
    """VIGENTE ou REVOGADA. Vetado também não vigora: entra como REVOGADA (o texto "(VETADO)" fica no nó)."""
    return REVOGADA if _REVOGADO.match(texto_sem_rotulo.strip(" .:-–—")) else VIGENTE


def _cabecalho(linha: str) -> bool:
    """Título/Capítulo/Seção e o nome em caixa alta que vem logo abaixo deles."""
    if _ESTRUTURA.match(linha) or _ADCT.match(linha):
        return True
    return (linha.isupper() and len(linha) < 160 and not linha.rstrip().endswith((".", ";", ":"))
            and not (_INCISO.match(linha) or _PARAGRAFO.match(linha) or _ALINEA.match(linha)))


def _nome_de_cabecalho(linha: str) -> bool:
    """Nome que vem sob "Seção II" em caixa mista ("Das Diretrizes"): curto, sem pontuação final, não é dispositivo."""
    return (len(linha) < 160 and not linha.rstrip().endswith((".", ";", ":", ","))
            and not (_INCISO.match(linha) or _PARAGRAFO.match(linha) or _PARAGRAFO_UNICO.match(linha) or _ALINEA.match(linha)))


def _separar_cauda(linhas: list[str]) -> list[str]:
    """Tira do fim do trecho as linhas de estrutura que pertencem ao artigo seguinte (muda `linhas`)."""
    cauda: list[str] = []
    while len(linhas) > 1 and _cabecalho(linhas[-1]):
        cauda.insert(0, linhas.pop())
    for j in range(len(linhas) - 1, max(0, len(linhas) - 4), -1):
        if _ESTRUTURA_NUMERADA.match(linhas[j]) and all(_nome_de_cabecalho(x) for x in linhas[j + 1:]):
            cauda = linhas[j:] + cauda
            del linhas[j:]
            while len(linhas) > 1 and _cabecalho(linhas[-1]):
                cauda.insert(0, linhas.pop())
            break
    return cauda


def _cabecalhos_do_inicio(linhas: list[str]) -> list[str]:
    """Estrutura antes do 1º artigo, com o nome em caixa mista logo abaixo de "Seção I" ("Dos Princípios")."""
    saida: list[str] = []
    anterior = ""
    for linha in (x.strip() for x in linhas):
        if not linha:
            continue
        if _cabecalho(linha) or (_ESTRUTURA_NUMERADA.match(anterior) and _nome_de_cabecalho(linha)):
            saida.append(linha)
        anterior = linha
    return saida


def _filhos(artigo_id: str, artigo: str, linhas: list[str], ordem_base: int) -> list[No]:
    """Parágrafos, incisos e alíneas de um artigo. Cada nó leva o próprio texto e o dos descendentes."""
    nos: list[No] = []
    par: No | None = None
    inc: No | None = None
    abertos: list[No] = []
    abrir = nos.append

    for linha in linhas:
        m_par, m_unico = _PARAGRAFO.match(linha), _PARAGRAFO_UNICO.match(linha)
        m_inc, m_ali = _INCISO.match(linha), _ALINEA.match(linha)
        if m_par or m_unico:
            num = "unico" if m_unico else (m_par[1] + (f"-{m_par[2].lower()}" if m_par[2] else ""))
            corpo = linha[(m_unico or m_par).end():]
            par = No(f"{artigo_id}.par-{num}", "paragrafo", artigo, paragrafo=num, parent=artigo_id, texto=linha,
                     rotulo="Parágrafo único" if num == "unico" else f"§ {num}", status=_status(corpo))
            inc = None
            abrir(par)
            abertos = [par]
        elif m_inc:
            num = m_inc[1].lower() + (f"-{m_inc[2].lower()}" if m_inc[2] else "")
            pai = par.dispositivo_id if par else artigo_id
            inc = No(f"{pai}.inc-{num}", "inciso", artigo, paragrafo=par.paragrafo if par else "", inciso=num, parent=pai,
                     texto=linha, rotulo=f"inciso {m_inc[1]}", status=_status(linha[m_inc.end():]))
            abrir(inc)
            abertos = [x for x in (par, inc) if x]
        elif m_ali:
            num = m_ali[1]
            pai_id = inc.dispositivo_id if inc else par.dispositivo_id if par else artigo_id
            ali = No(f"{pai_id}.ali-{num}", "alinea", artigo, paragrafo=par.paragrafo if par else "", inciso=inc.inciso if inc else "",
                     alinea=num, parent=pai_id, texto=linha, rotulo=f"alínea {num}", status=_status(linha[m_ali.end():]))
            abrir(ali)
            abertos = [x for x in (par, inc, ali) if x]
        else:
            for no in abertos:
                no.texto += "\n" + linha
            continue
        for no in abertos[:-1]:
            no.texto += "\n" + linha
    for i, no in enumerate(nos, start=1):
        no.ordem = ordem_base + i
    return nos


_NIVEL = {"livro": 1, "titulo": 2, "capitulo": 3, "secao": 4, "subsecao": 5}


def _nivel(linha: str) -> int:
    m = _ESTRUTURA.match(linha)
    if not m:
        return 0
    chave = m[1].lower().translate(str.maketrans("íçã", "ica"))
    return _NIVEL.get(chave, 5)


def _atualizar_contexto(contexto: list[str], cabecalhos: list[str]) -> list[str]:
    """Pilha Livro > Título > Capítulo > Seção: um Capítulo novo substitui o anterior e o que estava abaixo dele."""
    pilha = [(_nivel(x.split(" — ")[0]), x) for x in contexto]
    for linha in cabecalhos:
        if _ADCT.match(linha):
            pilha = [(0, linha)]
        elif nivel := _nivel(linha):
            pilha = [(n, x) for n, x in pilha if n < nivel or n == 0] + [(nivel, linha)]
        elif pilha:
            n, x = pilha[-1]
            pilha[-1] = (n, f"{x} — {linha}")
    return [x for _, x in pilha]


MAX_ARTIGOS_DO_ATO_QUE_APROVA = 6


def _mover_para_preambulo(nos: list[No]) -> None:
    """O número do artigo também muda, para a busca do Citation Gate por "art. 1" não achar o do decreto."""
    for n in nos:
        n.dispositivo_id = f"preambulo.{n.dispositivo_id}"
        n.parent = f"preambulo.{n.parent}" if n.parent else ""
        n.artigo = f"preambulo.{n.artigo}"
        n.rotulo = f"{n.rotulo} (ato de aprovação)"
        n.contexto = ["Ato de aprovação", *n.contexto]


def arvore(texto: str, *, nome_documento: str = "") -> list[No]:
    """Todos os nós do documento, artigos e descendentes, em ordem de leitura."""
    inicios = list(ARTIGO.finditer(texto))
    if not inicios:
        raise ValueError("PARSER_SEM_ARTIGOS")
    nos: list[No] = []
    usados: dict[str, int] = {}
    linhas_antes = texto[: inicios[0].start()].splitlines()
    prefixo, contexto = "", _atualizar_contexto([], _cabecalhos_do_inicio(linhas_antes))
    if any(_ADCT.match(x) for x in linhas_antes):
        prefixo = "adct."
    ordem = 0
    for i, m in enumerate(inicios):
        fim = inicios[i + 1].start() if i + 1 < len(inicios) else len(texto)
        parte = texto[m.start():fim].strip()
        linhas = parte.splitlines()
        # Linhas de estrutura e o título do ADCT ficam no fim do trecho anterior; saem dele e viram contexto do próximo.
        cauda = _separar_cauda(linhas)
        parte = "\n".join(linhas)
        numero = numero_do_artigo(m[1], m[3])
        base = f"{prefixo}art-{numero}"
        if numero == "1" and base in usados and not prefixo and sum(n.tipo_no == "artigo" for n in nos) <= MAX_ARTIGOS_DO_ATO_QUE_APROVA:
            # CLT e RPS: o decreto que aprova o código tem "Art. 1º/2º" próprios antes de o código recomeçar no 1.
            _mover_para_preambulo(nos)
            usados = {}
        usados[base] = usados.get(base, 0) + 1
        art_id = base if usados[base] == 1 else f"{base}~{usados[base]}"
        ordem += 1
        artigo = No(art_id, "artigo", numero, texto=parte, ordem=ordem, rotulo=f"Art. {numero.upper()}", contexto=list(contexto),
                    status=_status(linhas[0][len(m.group(0)):]))
        filhos = _filhos(art_id, numero, linhas[1:], ordem)
        ordem += len(filhos)
        nos.append(artigo)
        nos.extend(filhos)
        if any(_ADCT.match(x) for x in cauda):
            prefixo = "adct."
        contexto = _atualizar_contexto(contexto, cauda)
    return nos


def texto_para_embedding(no: No, nome_documento: str) -> str:
    """O que se vetoriza para um artigo: norma, estrutura, rótulo e o texto (mesmo formato do ingestor anterior)."""
    return "\n".join([nome_documento, *no.contexto, no.rotulo, no.texto])


def referencias(texto: str) -> list[str]:
    return sorted({m.group(0).strip() for m in REFERENCIA.finditer(texto)})
