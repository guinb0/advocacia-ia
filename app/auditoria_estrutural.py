"""Auditoria ESTRUTURAL determinística da peça: o que o código consegue provar sem pedir opinião ao modelo.

Cobre: abertura única (qualificação, endereçamento, título da ação, objeto), numeração/hierarquia das seções,
pendência que contradiz dado canônico, repetição substancial entre tópicos, ledger de pedidos (sobreposição,
majoração como 2ª indenização, subsidiário somado, valor × método, critério de cálculo × fundamentação, valor
da causa) e tese sem pedido. Tudo genérico: nomes de blocos, bases de cálculo e regexes de estrutura vêm da
SKILL (`validacoes.md` → `parametros`), nunca de um processo específico.
"""

from __future__ import annotations

import re
from typing import Any

from . import plano_da_peticao as pp
from .conferencia_peticao import Violacao
from .recuperacao_por_secao import dividir_em_topicos, paragrafos

_PENDENTE = re.compile(r"\[PENDENTE[^\]]*\]", re.IGNORECASE)
_VALOR = re.compile(r"R\$\s*([\d.]+,\d{2})")


def _reais(t: str) -> float:
    return float(t.replace(".", "").replace(",", "."))


def _v(codigo: str, secao: str, trecho: str, motivo: str, correcao: str, bloqueia: bool = True) -> Violacao:
    return Violacao(codigo, secao, str(trecho)[:220], motivo, correcao, bloqueia)


# ------------------------------------------------------------------ abertura única

def _paragrafos_com_posicao(secoes: list[dict[str, Any]]) -> list[tuple[int, str]]:
    saida = []
    for i, s in enumerate(secoes):
        for p in re.split(r"\n\s*\n", str(s.get("content") or "")):
            if p.strip():
                saida.append((i, p.strip()))
    return saida


def _eh_qualificacao(par: str, autor: dict[str, Any]) -> bool:
    nome = autor.get("nome")
    if not nome or pp.norm(nome) not in pp.norm(par):
        return False
    n, d = pp.norm(par), pp._so_digitos(par)  # noqa: SLF001
    presentes = sum(1 for c in ("cpf", "rg", "endereco", "pis", "ctps") if autor.get(c) and pp._valor_consta(c, autor[c], n, d))  # noqa: SLF001
    return presentes >= 2


def abertura_unica(secoes: list[dict[str, Any]], partes: dict[str, Any], params: dict[str, Any]) -> list[Violacao]:
    saida: list[Violacao] = []
    autor = partes.get("autor") or {}
    quali = [(i, p) for i, p in _paragrafos_com_posicao(secoes) if _eh_qualificacao(p, autor)]
    if len(quali) > 1:
        saida.append(_v("QUALIFICACAO_DUPLICADA", str(secoes[quali[1][0]].get("code")), quali[1][1],
                        f"A qualificação completa do autor aparece {len(quali)} vezes na peça.",
                        "Mantenha UMA qualificação, na abertura; remova as demais."))
    est = params.get("estrutura") or {}
    texto_todo = "\n".join(str(s.get("content") or "") for s in secoes)
    for bloco in est.get("blocos_unicos", []):
        n = len(re.findall(rf"^\s*:::\s*{re.escape(bloco)}\s*$", texto_todo, re.MULTILINE))
        if n > 1:
            saida.append(_v("BLOCO_ESTRUTURAL_DUPLICADO", "", f"::: {bloco} × {n}",
                            f"O bloco «{bloco}» (definido pela skill como único) aparece {n} vezes.", "Mantenha só o primeiro."))
    titulo = est.get("titulo_da_acao_regex")
    if titulo:
        n = sum(1 for _, p in _paragrafos_com_posicao(secoes) if re.match(titulo, p.strip("*: \n"), re.IGNORECASE))
        if n > 1:
            saida.append(_v("TITULO_DA_ACAO_DUPLICADO", "", f"{n} títulos de ação", "A identificação da ação aparece mais de uma vez.", "Mantenha um só."))
    return saida


def remover_aberturas_duplicadas(secoes: list[dict[str, Any]], partes: dict[str, Any], params: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Correção DETERMINÍSTICA: mantém a primeira abertura e apaga as repetidas (qualificação, blocos únicos, título).

    Uma abertura repetida é o trecho que vai da 2ª qualificação até o parágrafo que nomeia o réu ("em face de …"),
    incluindo o título da ação que a antecede; os blocos únicos repetidos saem inteiros.
    """
    autor, reu = partes.get("autor") or {}, partes.get("reu") or {}
    removidos = 0
    novas = [dict(s) for s in secoes]
    est = params.get("estrutura") or {}
    # blocos únicos: só o primeiro
    vistos: dict[str, int] = {}
    for s in novas:
        def sub(m: re.Match[str]) -> str:
            nonlocal removidos
            nome = m.group(1)
            vistos[nome] = vistos.get(nome, 0) + 1
            if nome in est.get("blocos_unicos", []) and vistos[nome] > 1:
                removidos += 1
                return ""
            return m.group(0)

        s["content"] = re.sub(r"^:::\s*([\w-]+)\s*\n.*?\n:::\s*$", sub, str(s.get("content") or ""), flags=re.MULTILINE | re.DOTALL)
    # qualificações repetidas
    achou = 0
    for s in novas:
        pars = re.split(r"(\n\s*\n)", str(s.get("content") or ""))
        saida, pular_ate_reu = [], False
        for trecho in pars:
            if re.fullmatch(r"\n\s*\n", trecho):
                saida.append(trecho)
                continue
            if pular_ate_reu:
                if reu.get("nome") and pp.norm(reu["nome"])[:20] in pp.norm(trecho):
                    pular_ate_reu = False
                removidos += 1
                saida.pop() if saida and re.fullmatch(r"\n\s*\n", saida[-1]) else None
                continue
            if _eh_qualificacao(trecho, autor):
                achou += 1
                if achou > 1:
                    pular_ate_reu = True
                    removidos += 1
                    # o título da ação que veio logo antes desta qualificação repetida também é repetição
                    while saida and (re.fullmatch(r"\n\s*\n", saida[-1]) or re.match(est.get("titulo_da_acao_regex", "$^"), pp.norm(saida[-1]).replace("*", ""), re.IGNORECASE)):
                        saida.pop()
                    continue
            saida.append(trecho)
        s["content"] = "".join(saida)
    return novas, removidos


# ------------------------------------------------------------------ numeração e hierarquia

_ROMANOS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def _romano(s: str) -> int:
    total, ant = 0, 0
    for c in reversed(s):
        v = _ROMANOS[c]
        total += -v if v < ant else v
        ant = max(ant, v)
    return total


def numeracao(titulos: list[tuple[str, str]]) -> list[Violacao]:
    """`titulos` = [(secao, texto do título como será impresso)]: capítulos romanos sequenciais; subitens a), b), c)…"""
    saida: list[Violacao] = []
    esperado = None
    for secao, t in titulos:
        m = re.match(r"^\s*(?:#+\s*)?(?:\*\*)?([IVXLC]+)\s*[.\-–—)]\s", t)
        if not m:
            continue
        n = _romano(m.group(1))
        if esperado is not None and n != esperado:
            saida.append(_v("NUMERACAO_DE_SECOES", secao, t, f"A numeração pula ou repete: veio {m.group(1)} quando se esperava {esperado}.",
                            "Numere os capítulos em sequência; título ausente indica cabeçalho perdido."))
        esperado = n + 1
    return saida


def subitens(secoes: list[dict[str, Any]]) -> list[Violacao]:
    saida: list[Violacao] = []
    for s in secoes:
        letras = [m.group(1) for m in re.finditer(r"^#{2,3}\s+([a-z])\)", str(s.get("content") or ""), re.MULTILINE)]
        for a, b in zip(letras, letras[1:]):
            if ord(b) != ord(a) + 1:
                saida.append(_v("NUMERACAO_DE_SUBITENS", str(s.get("code")), f"{a}) → {b})", f"Subitens fora de sequência: {a}) seguido de {b}).", "Reordene/renumere os subitens sem pular letra."))
    return saida


# ------------------------------------------------------------------ pendências × dado canônico

_CAMPO_POR_PALAVRA = {"cnpj": ("reu", "cnpj"), "cpf": ("autor", "cpf"), "rg": ("autor", "rg"), "cep": (None, "cep"), "endereco": (None, "endereco"),
                      "endereço": (None, "endereco"), "nome": (None, "nome"), "pis": ("autor", "pis"), "ctps": ("autor", "ctps")}


def pendencias(secoes: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(str(s.get("code")), m.group(0)) for s in secoes for m in _PENDENTE.finditer(str(s.get("content") or ""))]


def pendencia_com_dado_canonico(secoes: list[dict[str, Any]], partes: dict[str, Any]) -> list[Violacao]:
    saida = []
    for codigo, marcador in pendencias(secoes):
        n = pp.norm(marcador)
        for palavra, (papel, campo) in _CAMPO_POR_PALAVRA.items():
            if pp.norm(palavra) in n:
                papeis = [papel] if papel else ["autor", "reu"]
                for p in papeis:
                    if (partes.get(p) or {}).get(campo):
                        saida.append(_v("PENDENTE_COM_DADO_CANONICO", codigo, marcador,
                                        f"«{marcador}» marca como pendente um dado que o CASE_FACTS já tem ({p}.{campo}); a mesma peça não pode ter o dado preenchido num ponto e pendente em outro.",
                                        "Use o dado canônico, ou remova a versão divergente."))
                        break
    return saida


# ------------------------------------------------------------------ repetição substancial entre tópicos

def _shingles(texto: str, n: int = 5) -> set[tuple[str, ...]]:
    w = pp.norm(texto).split()
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def repeticao_entre_topicos(secoes: list[dict[str, Any]], limiar: float = 0.30) -> list[Violacao]:
    unidades: list[tuple[str, str, set[tuple[str, ...]], int]] = []
    for s in secoes:
        if s.get("code") in ("HEADING", "CLOSING", "VALUE", "CLAIMS"):
            continue
        for t in dividir_em_topicos(str(s.get("content") or "")):
            corpo = "\n\n".join(paragrafos(t["corpo"]))
            palavras = len(corpo.split())
            if palavras >= 120:
                unidades.append((str(s.get("code")), t["titulo"] or str(s.get("label") or s.get("code")), _shingles(corpo), palavras))
    saida = []
    for i, a in enumerate(unidades):
        for b in unidades[i + 1:]:
            if a[1] == b[1]:
                continue
            menor = min(len(a[2]), len(b[2]))
            if menor and len(a[2] & b[2]) / menor >= limiar:
                saida.append(_v("REPETICAO_ENTRE_TOPICOS", a[0], f"«{a[1][:45]}» × «{b[1][:45]}»",
                                f"Os tópicos «{a[1][:50]}» e «{b[1][:50]}» repetem substancialmente o mesmo texto ({len(a[2] & b[2]) / menor:.0%} de sobreposição).",
                                "Cada tópico precisa de função argumentativa própria: mantenha o desenvolvimento no tópico a que pertence e, no outro, só a referência cruzada.",
                                len(a[2] & b[2]) / menor >= 0.4))
    blocos: dict[str, int] = {}
    for s in secoes:
        for b in re.findall(r"^>\s*(.{80,})$", str(s.get("content") or ""), re.MULTILINE):
            k = pp.norm(b)[:120]
            blocos[k] = blocos.get(k, 0) + 1
    for k, n in blocos.items():
        if n > 1:
            saida.append(_v("JURISPRUDENCIA_REPETIDA", "", k[:80], f"A mesma transcrição aparece {n} vezes.", "Transcreva uma vez e, nas demais, apenas remeta a ela."))
    return saida


# ------------------------------------------------------------------ ledger de pedidos

_MAJORACAO = re.compile(r"majora|acr[ée]scimo|complement|agrava|adicional de|em raz[ãa]o d[oa] (?:adoecimento|agravamento)", re.IGNORECASE)


def _nucleo(p: dict[str, Any]) -> set[str]:
    return pp._tokens(f"{p.get('causa_de_pedir', '')} {p.get('tipo', '')} {p.get('objeto', '')}")  # noqa: SLF001


def ledger(plano: dict[str, Any]) -> list[Violacao]:
    saida: list[Violacao] = []
    peds = plano.get("pedidos") or []
    for i, a in enumerate(peds):
        for b in peds[i + 1:]:
            if a.get("de_praxe") or b.get("de_praxe"):
                continue
            sim = pp._jaccard(_nucleo(a), _nucleo(b))  # noqa: SLF001
            mesma_lesao = a.get("causa_de_pedir") and pp.norm(a["causa_de_pedir"]) == pp.norm(b.get("causa_de_pedir", ""))
            if _MAJORACAO.search(f"{b['tipo']} {b['objeto']}") and (sim >= 0.15 or mesma_lesao or a["tese_origem"] == b["tese_origem"]) and \
                    pp._jaccard(pp._tokens(a["tipo"]), pp._tokens("dano moral")) > 0 and pp._jaccard(pp._tokens(b["tipo"] + b["objeto"]), pp._tokens("dano moral")) > 0:  # noqa: SLF001
                saida.append(_v("MAJORACAO_COMO_SEGUNDA_INDENIZACAO", "CLAIMS", f"{a['id']} × {b['id']}",
                                f"O pedido {b['id']} («{b['tipo']}») parece uma majoração/agravamento do {a['id']}, mas foi lançado como pedido e valor SEPARADOS: a mesma lesão indenizada duas vezes.",
                                "Funda em um só pedido, com o critério de cálculo que já considera o agravamento; ou justifique a lesão autônoma."))
            elif sim >= 0.5 and (a["tese_origem"] == b["tese_origem"] or mesma_lesao):
                saida.append(_v("PEDIDOS_SOBREPOSTOS", "CLAIMS", f"{a['id']} × {b['id']}", f"Os pedidos {a['id']} e {b['id']} têm o mesmo objeto/causa de pedir.", "Funda ou diferencie objeto/período/base."))
    for p in peds:
        if p.get("natureza") in ("subsidiario", "alternativo") and p.get("incluido_no_valor_da_causa"):
            saida.append(_v("SUBSIDIARIO_SOMADO_AO_PRINCIPAL", "CLAIMS", p["id"], f"O pedido {p['id']} é {p['natureza']} mas entrou na soma do valor da causa como cumulativo.", "Some só os pedidos cumulativos."))
        m = p.get("metodo_calculo") or {}
        try:
            base, mult, res = (float(m.get(k)) for k in ("base", "multiplicador", "resultado"))
            if abs(base * mult - res) > 0.01 * max(res, 1):
                saida.append(_v("VALOR_INCONSISTENTE_COM_METODO", "CLAIMS", p["id"], f"{p['id']}: {base:,.2f} × {mult} ≠ {res:,.2f}.", "Corrija o resultado ou o critério."))
        except (TypeError, ValueError):
            pass
    tese_ids = {p["tese_origem"] for p in peds}
    for t in plano.get("teses") or []:
        if t.get("gera_pedido", True) and t.get("consequencia") and t["id"] not in tese_ids:
            saida.append(_v("TESE_SEM_PEDIDO", "CLAIMS", f"{t['id']} {t['titulo'][:50]}", f"A tese {t['id']} tem consequência jurídica mas nenhum pedido correspondente.", "Registre o pedido no ledger ou marque a tese como sem pedido.", False))
    return saida


def soma_cumulativos(plano: dict[str, Any]) -> float:
    return round(sum(float(p["valor"]) for p in plano.get("pedidos") or [] if p.get("valor") and p.get("natureza", "cumulativo") == "cumulativo"), 2)


def valor_da_causa(secoes: list[dict[str, Any]], plano: dict[str, Any]) -> list[Violacao]:
    texto = "\n".join(str(s.get("content") or "") for s in secoes)
    m = re.search(r"(?:d[aá]-se\s+[àa]\s+causa|valor\s+da\s+causa)[^$\n]{0,60}R\$\s*([\d.]+,\d{2})", texto, re.IGNORECASE)
    soma = soma_cumulativos(plano)
    if m and soma and abs(_reais(m.group(1)) - soma) > 0.01:
        return [_v("VALOR_DA_CAUSA_NAO_FECHA", "CLAIMS", f"R$ {m.group(1)} × Σ pedidos cumulativos R$ {soma:,.2f}",
                   "O valor da causa não é a soma dos pedidos cumulativos do ledger (subsidiários/alternativos não somam).", "Ajuste o valor da causa à soma correta ou classifique o pedido.")]
    return []


def criterio_de_calculo(secoes: list[dict[str, Any]], params: dict[str, Any]) -> list[Violacao]:
    """A base de cálculo dita na fundamentação tem de ser a usada nos pedidos (vocabulário de bases vem da skill)."""
    bases = params.get("bases_de_calculo") or {}
    if not bases:
        return []

    def usadas(texto: str) -> set[str]:
        return {k for k, rx in bases.items() if re.search(rx, texto, re.IGNORECASE)}

    fund, ped = set(), set()
    for s in secoes:
        if s.get("code") == "CLAIMS":
            ped |= usadas(str(s.get("content") or ""))
            continue
        for t in dividir_em_topicos(str(s.get("content") or "")):
            if re.search(r"quantifica|arbitr|valor da indeniza|c[áa]lculo", t["titulo"], re.IGNORECASE):
                fund |= usadas(t["corpo"])
    if fund and ped and not (fund & ped):
        return [_v("CRITERIO_DE_CALCULO_DIVERGENTE", "CLAIMS", f"fundamentação: {sorted(fund)} × pedidos: {sorted(ped)}",
                   f"A fundamentação calcula por «{', '.join(sorted(fund))}» e os pedidos usam «{', '.join(sorted(ped))}».",
                   "Use nos pedidos exatamente o critério da fundamentação (ou corrija a fundamentação) — um só critério, rastreável até o dado do caso.")]
    return []


def auditar(secoes: list[dict[str, Any]], plano: dict[str, Any], params: dict[str, Any], titulos: list[tuple[str, str]]) -> list[Violacao]:
    partes = plano.get("partes") or {}
    return [
        *abertura_unica(secoes, partes, params),
        *numeracao(titulos), *subitens(secoes),
        *pendencia_com_dado_canonico(secoes, partes),
        *repeticao_entre_topicos(secoes),
        *ledger(plano), *valor_da_causa(secoes, plano), *criterio_de_calculo(secoes, params),
    ]
