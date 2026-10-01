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
from .juridico import canonico
from .juridico.auditores import _ACESSORIO_DA_LIQUIDACAO, _ILIQUIDO
from .juridico.calculos import valor_da_causa as _valor_da_causa
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
    for bloco in est.get("blocos_unicos") or []:
        n = len(re.findall(rf"^\s*:::\s*{re.escape(bloco)}\s*$", texto_todo, re.MULTILINE))
        if n > 1:
            saida.append(_v("BLOCO_ESTRUTURAL_DUPLICADO", "", f"::: {bloco} × {n}",
                            f"O bloco «{bloco}» (definido pela skill como único) aparece {n} vezes.", "Mantenha só o primeiro."))
    titulo = est.get("titulo_da_acao_regex")
    if titulo:
        n = sum(
            1
            for linha in texto_todo.splitlines()
            if pp.norm(linha.strip("*: #\n")).startswith("reclamacao trabalhista")
        )
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
            if nome in (est.get("blocos_unicos") or []) and vistos[nome] > 1:
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


def repeticao_entre_topicos(secoes: list[dict[str, Any]], limiar: float = 0.30, plano: dict[str, Any] | None = None) -> list[Violacao]:
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
            if plano:  # tese principal × subsidiária pode tratar do mesmo evento: não é duplicação
                ta, tb = pp.tese_do_topico(plano, a[1]), pp.tese_do_topico(plano, b[1])
                if ta and tb and ta["id"] != tb["id"] and any(str(t.get("relacao", "principal")).startswith(("subsidiaria", "alternativa")) for t in (ta, tb)):
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


def _autonomo_monetario(p: dict[str, Any]) -> bool:
    return p.get("tipo_de_item", "autonomo") == "autonomo" and not p.get("de_praxe") and bool(p.get("valor") or re.search(r"R\$\s*\d", p.get("valor_ou_base", "")))


def ledger(plano: dict[str, Any]) -> list[Violacao]:
    saida: list[Violacao] = []
    peds = plano.get("pedidos") or []
    # AGRAVANTE / critério / consequência NÃO é segundo pedido econômico: entra na quantificação do principal
    for p in peds:
        if p.get("tipo_de_item") in ("agravante", "criterio_de_quantificacao", "consequencia") and (p.get("valor") or p.get("natureza", "cumulativo") == "cumulativo" and re.search(r"R\$\s*\d", p.get("valor_ou_base", ""))):
            saida.append(_v("AGRAVANTE_COM_VALOR_PROPRIO", "CLAIMS", f"{p['id']} {p['tipo']}", f"{p['id']} é {p['tipo_de_item']} de outro pedido mas tem valor próprio: virou segunda indenização.",
                            "Integre o fator ao método de cálculo do pedido principal e retire o valor separado."))
    # mesmo bem jurídico + mesmo evento + mesmo objeto econômico = a MESMA reparação, ainda que o texto seja outro
    monetarios = [p for p in peds if _autonomo_monetario(p) and p.get("natureza", "cumulativo") == "cumulativo"]
    for i, a in enumerate(monetarios):
        for b in monetarios[i + 1:]:
            campos = ("bem_juridico", "evento_causador", "objeto_economico")
            if all(a.get(c) and b.get(c) and pp._jaccard(pp._tokens(a[c]), pp._tokens(b[c])) >= 0.5 for c in campos):  # noqa: SLF001
                autonomos = pp._jaccard(pp._tokens(a.get("dano", "")), pp._tokens(b.get("dano", ""))) < 0.25 and a.get("dano") and b.get("dano")  # noqa: SLF001
                if not autonomos:
                    saida.append(_v("MESMA_REPARACAO_DUAS_VEZES", "CLAIMS", f"{a['id']} × {b['id']}", f"{a['id']} e {b['id']} reparam o mesmo dano (mesmo bem jurídico, evento causador e objeto econômico).",
                                    "Funda em um só pedido; se são danos autônomos, o dano de cada um deve estar distinto e fundamentado."))
    for i, a in enumerate(peds):
        for b in peds[i + 1:]:
            if a.get("de_praxe") or b.get("de_praxe"):
                continue
            if (
                a.get("bem_juridico") and b.get("bem_juridico")
                and pp._jaccard(pp._tokens(a["bem_juridico"]), pp._tokens(b["bem_juridico"])) < 0.5  # noqa: SLF001
                and a.get("dano") and b.get("dano")
                and pp._jaccard(pp._tokens(a["dano"]), pp._tokens(b["dano"])) < 0.5  # noqa: SLF001
            ):
                continue
            # principal × subsidiário/alternativo do mesmo objeto é RELAÇÃO declarada, não duplicidade
            if a.get("natureza", "cumulativo") != b.get("natureza", "cumulativo") and "cumulativo" in (a.get("natureza", "cumulativo"), b.get("natureza", "cumulativo")):
                continue
            sim = pp._jaccard(_nucleo(a), _nucleo(b))  # noqa: SLF001
            mesma_lesao = a.get("causa_de_pedir") and pp.norm(a["causa_de_pedir"]) == pp.norm(b.get("causa_de_pedir", ""))
            if _MAJORACAO.search(f"{b['tipo']} {b['objeto']}") and _autonomo_monetario(a) and _autonomo_monetario(b) and (sim >= 0.12 or mesma_lesao or a["tese_origem"] == b["tese_origem"]):
                saida.append(_v("MAJORACAO_COMO_SEGUNDA_INDENIZACAO", "CLAIMS", f"{a['id']} × {b['id']}",
                                f"O pedido {b['id']} («{b['tipo']}») parece uma majoração/agravamento do {a['id']}, mas foi lançado como pedido e valor SEPARADOS: a mesma lesão indenizada duas vezes.",
                                "Funda em um só pedido, com o critério de cálculo que já considera o agravamento; ou justifique a lesão autônoma."))
            elif sim >= 0.5 and not pp.periodos_distintos(a, b) and (a["tese_origem"] == b["tese_origem"] or mesma_lesao):
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
    """A MESMA soma da camada jurídica (`juridico.calculos.valor_da_causa`): uma regra só para o valor da causa."""
    return _valor_da_causa(plano.get("pedidos") or [])["valor"]


def valor_da_causa(secoes: list[dict[str, Any]], plano: dict[str, Any]) -> list[Violacao]:
    texto = "\n".join(str(s.get("content") or "") for s in secoes)
    ocorrencias = list(
        re.finditer(
            r"(?:d[aá]-se\s+[àa]\s+causa|valor\s+da\s+causa)[^$\n]{0,60}R\$\s*([\d.]+,\d{2})",
            texto,
            re.IGNORECASE,
        )
    )
    saida: list[Violacao] = []
    if len(ocorrencias) > 1:
        saida.append(_v(
            "VALOR_DA_CAUSA_DUPLICADO",
            "VALUE",
            ocorrencias[1].group(0)[:120],
            f"«Dá-se à causa» / valor da causa aparece {len(ocorrencias)} vezes na peça.",
            "Mantenha UMA linha de valor da causa, no fechamento; remova as demais.",
        ))
    soma = soma_cumulativos(plano)
    if ocorrencias and soma and abs(_reais(ocorrencias[0].group(1)) - soma) > 0.01:
        saida.append(_v(
            "VALOR_DA_CAUSA_NAO_FECHA",
            "CLAIMS",
            f"R$ {ocorrencias[0].group(1)} × Σ pedidos cumulativos R$ {soma:,.2f}",
            "O valor da causa não é a soma dos pedidos cumulativos do ledger (subsidiários/alternativos não somam).",
            "Ajuste o valor da causa à soma correta ou classifique o pedido.",
        ))
    return saida


#: Marcadores e nomes de fixture que NÃO podem chegar à peça protocolável.
#: Cada geração do zero oscilava (v13/v14/v15): o que já estava certo quebrava de novo.
#: Estes gates são DETERMINÍSTICOS — o modelo não decide se passa.
_DADO_DE_TESTE = re.compile(
    r"(?i)(?:BEZERRA\s+TESTE|\(TESTE\)|\bNOME\s+TESTE\b|"
    r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇÀ-ÿ]{1,}(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇÀ-ÿ]{1,})*\s+TESTE\b)"
)
_PLACEHOLDER_PROIBIDO = re.compile(
    r"\[(?:PENDENTE|data(?:\s+por\s+extenso)?|INFORMA[CÇ][AÃ]O)[^\]]*\]",
    re.IGNORECASE,
)


def dado_de_teste_no_texto(secoes: list[dict[str, Any]]) -> list[Violacao]:
    """Nome/fixture de teste no texto da peça — o erro mais grave possível numa inicial."""
    saida = []
    for s in secoes:
        for m in _DADO_DE_TESTE.finditer(str(s.get("content") or "")):
            saida.append(_v(
                "DADO_DE_TESTE_NO_TEXTO",
                str(s.get("code") or ""),
                m.group(0),
                f"A peça contém dado de teste («{m.group(0)}»). Isso polui cadastro, modelo ou cache — não é falha de redação.",
                "Remova a fonte do dado de teste (cadastro/fixture) e regenere com a identidade canônica do CASE_FACTS.",
            ))
    return saida


def placeholders_proibidos(secoes: list[dict[str, Any]]) -> list[Violacao]:
    """`[PENDENTE]`, `[data por extenso]` e afins no documento final barram a entrega."""
    saida = []
    for s in secoes:
        for m in _PLACEHOLDER_PROIBIDO.finditer(str(s.get("content") or "")):
            saida.append(_v(
                "PLACEHOLDER_PROIBIDO_NO_DOCUMENTO",
                str(s.get("code") or ""),
                m.group(0),
                f"Marcador «{m.group(0)}» no documento final — peça incompleta para protocolo.",
                "Preencha com dado canônico do CASE_FACTS/ledger ou retire o trecho; não entregue placeholder.",
            ))
    return saida


def cidade_endereco_vs_vara(secoes: list[dict[str, Any]], partes: dict[str, Any]) -> list[Violacao]:
    """Endereço da reclamada em cidade diferente da Vara do endereçamento — sinal clássico de dado de outro caso."""
    texto = "\n".join(str(s.get("content") or "") for s in secoes)
    m_vara = re.search(
        r"Vara\s+do\s+Trabalho\s+de\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÀ-ÿ\s'-]+?)(?:/|\s*[-–—]|\s*$)",
        texto,
        re.IGNORECASE,
    )
    endereco_reu = str((partes.get("reu") or {}).get("endereco") or "")
    if not m_vara or not endereco_reu:
        return []
    cidade_vara = pp.norm(m_vara.group(1).split("/")[0].strip())
    # Cidade no endereço: última palavra significativa antes do UF (…, Cidade/UF ou … - Cidade)
    m_cid = re.search(
        r"([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÀ-ÿ'-]+)\s*[-–—/]\s*[A-Z]{2}\b",
        endereco_reu,
        re.IGNORECASE,
    )
    if not m_cid:
        return []
    cidade_end = pp.norm(m_cid.group(1))
    if cidade_vara and cidade_end and cidade_vara != cidade_end and cidade_end not in cidade_vara and cidade_vara not in cidade_end:
        return [_v(
            "CIDADE_ENDERECO_DIVERGENTE_DA_VARA",
            "HEADING",
            f"Vara: {m_vara.group(1)} × endereço: {m_cid.group(1)}",
            "A cidade do endereço da reclamada diverge da cidade da Vara do endereçamento — típico de dado de outro caso/fixture.",
            "Use o endereço canônico do CASE_FACTS e o Juízo da comarca correspondente.",
        )]
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


def auditar(secoes: list[dict[str, Any]], plano: dict[str, Any], params: dict[str, Any], titulos: list[tuple[str, str]], embed: Any = None) -> list[Violacao]:
    partes = plano.get("partes") or {}
    return [
        *abertura_unica(secoes, partes, params),
        *numeracao(titulos), *subitens(secoes),
        *pendencia_com_dado_canonico(secoes, partes),
        *repeticao_entre_topicos(secoes, plano=plano),
        *repeticao_de_conteudo(secoes, params), *contradicao_de_data(secoes, plano),
        *dado_rejeitado_no_texto(secoes, plano.get("case_facts") or {}),
        *dado_de_teste_no_texto(secoes),
        *placeholders_proibidos(secoes),
        *cidade_endereco_vs_vara(secoes, partes),
        *coerencia_juridica_minima(secoes, plano),
        *pressupostos_e_atualidade(secoes, plano),
        *(candidatos_semanticos(secoes, plano, embed) if embed else []),
        *ledger(plano), *valor_da_causa(secoes, plano), *criterio_de_calculo(secoes, params),
    ]


# ------------------------------------------------------------------ dono do conteúdo + repetição de QUALQUER tamanho

_SECOES_DE_REFERENCIA = {"CLAIMS", "CLOSING"}


def _classificar(paragrafo: str, funcoes: dict[str, str]) -> str | None:
    """Função estrutural do parágrafo (comunicações, provas, gratuidade…): a categoria com mais acertos do vocabulário da SKILL."""
    melhor, pontos = None, 0
    for categoria, rx in funcoes.items():
        n = len(re.findall(rx, paragrafo, re.IGNORECASE))
        if n > pontos:
            melhor, pontos = categoria, n
    return melhor


def _unidades(secoes: list[dict[str, Any]], funcoes: dict[str, str]) -> list[dict[str, Any]]:
    unidades = []
    for i, s in enumerate(secoes):
        if s.get("code") == "HEADING":
            continue
        for p in paragrafos(str(s.get("content") or "")):
            palavras = len(p.split())
            if palavras >= 6:
                unidades.append({"i": i, "code": str(s.get("code")), "texto": p, "palavras": palavras, "tokens": pp._tokens(p),  # noqa: SLF001
                                 "categoria": _classificar(p, funcoes)})
    return unidades


def _contem(a: set[str], b: set[str]) -> float:
    menor = min(len(a), len(b))
    return len(a & b) / menor if menor >= 5 else 0.0


def repeticao_de_conteudo(secoes: list[dict[str, Any]], params: dict[str, Any]) -> list[Violacao]:
    """Duplicação relevante NÃO depende do tamanho: compara parágrafos de qualquer porte e considera a FUNÇÃO da seção.

    Regra: cada função estrutural (comunicações, provas, justiça gratuita…) é DESENVOLVIDA numa seção — a que mais
    a desenvolve — e as demais só a referenciam. Referência curta nos pedidos/fecho é legítima; reproduzir o
    desenvolvimento (ou a mesma frase) noutra seção não é.
    """
    funcoes = params.get("funcoes_de_conteudo") or {}
    un = _unidades(secoes, funcoes)
    saida: list[Violacao] = []
    # 1) mesmo conteúdo em duas seções, com ou sem função declarada
    for a_i, a in enumerate(un):
        for b in un[a_i + 1:]:
            if a["i"] == b["i"]:
                continue
            c = _contem(a["tokens"], b["tokens"])
            if c < 0.75:
                continue
            referencia_legitima = b["code"] in _SECOES_DE_REFERENCIA and b["palavras"] <= 0.6 * a["palavras"]
            if not referencia_legitima:
                saida.append(_v("REPETICAO_DESNECESSARIA", b["code"], b["texto"][:100],
                                f"Este trecho repete ({c:.0%}) conteúdo já desenvolvido na seção {a['code']} sem acrescentar função jurídica nova.",
                                "Desenvolva o conteúdo numa só seção (a competente) e, nas demais, deixe no máximo uma referência de uma frase."))
    # 2) dono do conteúdo: quem desenvolve cada função
    palavras: dict[str, dict[int, int]] = {}
    for u in un:
        if u["categoria"] and u["code"] not in _SECOES_DE_REFERENCIA:
            palavras.setdefault(u["categoria"], {}).setdefault(u["i"], 0)
            palavras[u["categoria"]][u["i"]] += u["palavras"]
    dono = {c: max(m, key=m.get) for c, m in palavras.items()}
    for c, m in palavras.items():
        for i, n in m.items():
            if i != dono[c] and n >= 40 and n >= 0.4 * m[dono[c]]:
                saida.append(_v("CONTEUDO_DESENVOLVIDO_FORA_DA_SECAO_COMPETENTE", str(secoes[i].get("code")), f"{c}: {n} palavras",
                                f"A função «{c}» é desenvolvida em duas seções; a competente é {secoes[dono[c]].get('code')}.",
                                "Desenvolva uma vez, na seção competente; aqui deixe só a referência.", n >= 0.7 * m[dono[c]]))
    # 3) pedido final que reproduz o desenvolvimento de outra seção (provas, comunicações, gratuidade…)
    for u in un:
        if u["code"] == "CLAIMS" and u["categoria"] in dono and u["palavras"] > 35:
            donos = [o for o in un if o["i"] == dono[u["categoria"]] and o["categoria"] == u["categoria"]]
            cont = max((_contem(u["tokens"], o["tokens"]) for o in donos), default=0.0)
            if cont >= 0.5 or u["palavras"] > 90:
                saida.append(_v("PEDIDO_REPRODUZ_DESENVOLVIMENTO", "CLAIMS", u["texto"][:100],
                                f"O pedido final reproduz o desenvolvimento de «{u['categoria']}» já feito na seção {secoes[dono[u['categoria']]].get('code')}.",
                                "No pedido, só a consequência/referência (uma frase, com o fundamento entre parênteses).", cont >= 0.5))
    return saida


# ------------------------------------------------------------------ contradição de data (determinística) e candidatos semânticos

_DATA_BR = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")


def contradicao_de_data(secoes: list[dict[str, Any]], plano: dict[str, Any]) -> list[Violacao]:
    """Fato do plano com data X e trecho que descreve o MESMO fato com outra data."""
    saida = []
    for f in plano.get("fatos") or []:
        datas = set(_DATA_BR.findall(f"{f.get('data', '')} {f.get('fato', '')}"))
        alvo = pp._tokens(re.sub(_DATA_BR, " ", f["fato"]))  # noqa: SLF001
        if len(datas) != 1 or len(alvo) < 3:
            continue
        for s in secoes:
            for frase in re.split(r"(?<=[.;])\s+", str(s.get("content") or "")):
                em_frase = set(_DATA_BR.findall(frase))
                if em_frase and not (em_frase & datas) and len(alvo & pp._tokens(frase)) / len(alvo) >= 0.6:  # noqa: SLF001
                    saida.append(_v("CONTRADICAO_DE_DATA", str(s.get("code")), frase[:120],
                                    f"O fato {f['id']} tem data {sorted(datas)[0]} no caso, mas este trecho o descreve com {sorted(em_frase)[0]}.", "Use a data do CASE_FACTS."))
    return saida


_CACHE_EMBED: dict[tuple[str, ...], list[list[float]]] = {}


def candidatos_semanticos(secoes: list[dict[str, Any]], plano: dict[str, Any], embed: Any, limiar: float = 0.9) -> list[Violacao]:
    """PRÉ-detector barato (embeddings, sem LLM): tópicos de teses diferentes semanticamente quase iguais.

    Pega paráfrase que o n-grama não pega. Não é veredito — vira candidato para o auditor por modelo julgar.
    """
    topicos = []
    for s in secoes:
        if s.get("code") in ("HEADING", "CLOSING", "VALUE", "CLAIMS"):
            continue
        for t in dividir_em_topicos(str(s.get("content") or "")):
            corpo = "\n\n".join(paragrafos(t["corpo"]))
            if t["titulo"] and len(corpo.split()) >= 40:
                topicos.append((str(s.get("code")), t["titulo"], corpo[:1500]))
    if len(topicos) < 2:
        return []
    chave = tuple(t[2] for t in topicos)
    try:
        vs = _CACHE_EMBED.get(chave) or embed(list(chave))
        _CACHE_EMBED[chave] = vs
    except Exception:  # noqa: BLE001 - sem embeddings, só o n-grama e o auditor global
        return []
    saida = []
    if not isinstance(vs, list) or any(not isinstance(v, (list, tuple)) for v in vs):
        return []
    for i, a in enumerate(topicos):
        for j in range(i + 1, len(topicos)):
            if i >= len(vs) or j >= len(vs):
                continue
            b = topicos[j]
            num = sum(x * y for x, y in zip(vs[i], vs[j]))
            den = (sum(x * x for x in vs[i]) ** 0.5) * (sum(y * y for y in vs[j]) ** 0.5)
            cos = num / den if den else 0.0
            ta, tb = pp.tese_do_topico(plano, a[1], a[2]), pp.tese_do_topico(plano, b[1], b[2])
            relacionadas = any(t and str(t.get("relacao", "principal")).startswith(("subsidiaria", "alternativa")) for t in (ta, tb)) and ta and tb and ta["id"] != tb["id"]
            if cos >= limiar and not relacionadas:
                saida.append(_v("SOBREPOSICAO_SEMANTICA_CANDIDATA", a[0], f"«{a[1][:40]}» × «{b[1][:40]}» (cos {cos:.2f})",
                                "Tópicos com sentido quase idêntico (possível mesmo argumento em capítulos diferentes).", "O auditor decide se há duplicação substancial.", False))
    return saida


def ausencia_falsa_de_documento_listado(
    secoes: list[dict[str, Any]], ledger: list[dict[str, Any]],
) -> list[Violacao]:
    """Afirmar que um tipo de prova «não integra» os autos quando o ledger o lista — regressão v15."""
    if not ledger:
        return []
    texto = "\n".join(str(s.get("content") or "") for s in secoes)
    n = pp.norm(texto)
    saida = []
    # tipo canônico → padrões de negação no texto
    checagens = (
        ("contracheque", r"contracheque|holerite|folha de pagamento", r"(contracheque|holerite).{0,40}(nao integra|nao constam|inexist|nao foram juntad|nao ha)"),
        ("cat", r"\bcat\b|comunicado de acidente", r"\bcat\b.{0,40}(nao integra|nao consta|inexist)"),
        ("boletim", r"boletim| b\.?o\.?\b", r"(boletim|\bbo\b).{0,40}(nao integra|nao consta|inexist)"),
    )
    for tipo, rx_tipo, rx_neg in checagens:
        no_ledger = any(
            re.search(rx_tipo, f"{d.get('document_type', '')} {d.get('canonical_file', '')}", re.I)
            for d in ledger
        )
        if no_ledger and re.search(rx_neg, n):
            saida.append(_v(
                "AUSENCIA_FALSA_DE_DOCUMENTO_LISTADO",
                "",
                tipo,
                f"A peça diz que «{tipo}» não integra/não consta dos autos, mas o DOCUMENT_LEDGER lista esse tipo.",
                "Cite o(s) Documento NN do índice canônico; não marque como inexistente o que o ledger numera.",
            ))
            return saida
    return saida


_VINCULO_ATIVO = re.compile(
    r"(?:v[íi]nculo|contrato(?:\s+de\s+trabalho)?)\s+(?:permanece|continua|segue|est[áa])\s+(?:ativo|vigente|em\s+curso|em\s+vigor)|"
    r"(?:ainda|segue|continua|permanece)\s+(?:trabalhando|laborando|prestando\s+servi[çc]os|empregad[oa]|em\s+atividade)|"
    r"contrato\s+(?:de\s+trabalho\s+)?(?:ativo|vigente|em\s+vigor)|v[íi]nculo\s+(?:empregat[íi]cio\s+)?ativo", re.I)
_TERMINO = re.compile(
    r"\bdispensad[oa]|\bdemitid[oa]|\bdispensa\s+(?:sem\s+justa|por\s+justa|imotivada|ocorrida|em\s+\d)|pedido\s+de\s+demiss|"
    r"rescis[ãa]o\s+(?:do\s+contrato|contratual|indireta)|\bTRCT\b|termo\s+de\s+rescis|desligad[oa]|extin[çc][ãa]o\s+do\s+contrato|baixa\s+na\s+CTPS", re.I)
_CRITERIO_GRATUIDADE_SUPERADO = re.compile(
    r"40\s*%\s*(?:\(\s*quarenta\s+por\s+cento\s*\)\s*)?d[oa]\s+(?:limite\s+m[áa]ximo|teto)|quarenta\s+por\s+cento\s+do\s+(?:limite|teto)|"
    r"s[úu]mula\s+(?:n[º°.]*\s*)?463\s*,?\s*(?:item\s+)?I\b(?![IV])|tema\s+(?:n[º°.]*\s*)?21\b[^.\n]{0,40}(?:TST|IRR)", re.I)


def pressupostos_e_atualidade(secoes: list[dict[str, Any]], plano: dict[str, Any]) -> list[Violacao]:
    """Fato × pedido e critério jurídico superado, no fluxo legado (o modo strict tem os gates da camada jurídica).

    - verba rescisória (multa do art. 477, aviso prévio, 40% do FGTS…) pedida com o contrato ativo e sem rescisão indireta;
    - critério de gratuidade afastado pela ADC 80 do STF (percentual do teto do RGPS, Súmula 463, I, do TST, Tema 21 do TST);
    - pedido de pagamento deixado para liquidação e pedidos sem memória de cálculo (aviso: o valor não é inventado na correção).
    """
    saida: list[Violacao] = []
    claims = "\n".join(str(s.get("content") or "") for s in secoes if s.get("code") == "CLAIMS")
    resto = "\n".join(str(s.get("content") or "") for s in secoes if s.get("code") != "CLAIMS")
    fatos = " ".join(str(f.get(k) or "") for f in plano.get("fatos") or [] if isinstance(f, dict) for k in ("descricao", "fato", "valor"))
    rescisorios = [p for p in plano.get("pedidos") or []
                   if canonico.menciona_verba_rescisoria(f"{p.get('tipo', '')} {p.get('objeto', '')} {p.get('causa_de_pedir', '')}")]
    indireta = canonico.pede_rescisao_indireta([{"tese": f"{resto} {claims}"}, *({"tese": p.get("tipo", ""), "pedido": p.get("objeto", "")} for p in plano.get("pedidos") or [])])
    contexto = f"{resto} {fatos}"
    if rescisorios and not indireta and (_VINCULO_ATIVO.search(contexto) or not _TERMINO.search(contexto)):
        ids = ", ".join(f"{p.get('id')} {str(p.get('tipo') or '')[:40]}" for p in rescisorios)
        saida.append(_v("VERBA_RESCISORIA_COM_VINCULO_ATIVO", "LEDGER", ids,
                        "Pedido de verba rescisória (multa do art. 477, aviso prévio, 40% do FGTS, multa do art. 467, seguro-desemprego) "
                        "sem término do contrato nos fatos: o vínculo está ativo e não há pedido de rescisão indireta.",
                        "Retire esses pedidos do ledger (ou, se a estratégia aprovada for a rescisão indireta, ela tem de estar fundamentada e pedida)."))
    for s in secoes:
        m = _CRITERIO_GRATUIDADE_SUPERADO.search(str(s.get("content") or ""))
        if m:
            saida.append(_v("GRATUIDADE_CRITERIO_SUPERADO", str(s.get("code") or ""), m.group(0),
                            "Critério de gratuidade afastado pelo STF na ADC 80 (julgada em 03/09/2026): o percentual do teto do RGPS do "
                            "art. 790, § 3º, da CLT foi declarado inconstitucional e o item I da Súmula 463 do TST também.",
                            "Fundamente pela ADC 80: até R$ 5.000,00 de remuneração há presunção relativa de insuficiência (com o salário "
                            "do contracheque); acima disso, demonstre a insuficiência com documentos (art. 790, § 4º, da CLT). Não cite a "
                            "Súmula 463, I, nem o Tema 21 do TST como critério atual."))
    for linha in claims.split("\n"):
        if _ILIQUIDO.search(linha) and not _ACESSORIO_DA_LIQUIDACAO.search(linha):
            saida.append(_v("PEDIDO_ILIQUIDO", "CLAIMS", linha.strip(),
                            "Pedido de pagamento deixado para liquidação: o rito trabalhista exige valor certo (art. 840, § 1º, da CLT).",
                            "Calcule com os dados dos documentos e traga a memória de cálculo; sem dado, retire o pedido e registre a pendência.", False))
    if re.search(r"R\$\s*\d", claims) and not re.search(r"mem[óo]ria\s+de\s+c[áa]lculo", claims, re.I) and "|" not in claims:
        saida.append(_v("MEMORIA_DE_CALCULO_AUSENTE", "CLAIMS", "pedidos com valor",
                        "Os pedidos têm valor, mas a peça não traz a memória de cálculo discriminada (base, documento, período, conta, resultado).",
                        "Inclua a memória de cálculo logo após os pedidos, uma linha por parcela.", False))
    return saida


def coerencia_juridica_minima(secoes: list[dict[str, Any]], plano: dict[str, Any]) -> list[Violacao]:
    """Portões para erros jurídicos concretos já encontrados em iniciais da ECT.

    São regras negativas e verificáveis: não decidem a tese, mas impedem que a
    redação transforme hipótese sem fonte em fato ou cite dispositivo para uma
    matéria que ele não disciplina.
    """
    texto = "\n".join(str(s.get("content") or "") for s in secoes)
    n = pp.norm(texto)
    saida: list[Violacao] = []

    for p in plano.get("pedidos") or []:
        alvo = pp.norm(f"{p.get('tipo', '')} {p.get('objeto', '')}")
        if "dano material" in alvo and p.get("tipo_de_item", "autonomo") == "autonomo" and not p.get("valor"):
            saida.append(_v("DANO_MATERIAL_SEM_VALOR", "CLAIMS", str(p.get("id") or ""),
                            "Pedido de dano material não tem valor indicado no ledger.",
                            "Retire-o se não houver base mínima, ou informe valor e método de cálculo verificável."))
    if re.search(r"nexo.{0,25}presum", n):
        saida.append(_v("NEXO_PRESUMIDO_SEM_BASE", "", "nexo presumido",
                        "A peça chama o nexo médico de presumido sem base documental ou legal identificada.",
                        "Descreva somente o que consta da CAT/laudo e trate o nexo como matéria de prova quando necessário."))
    if re.search(r"servico medico.{0,35}(propri[oa]|da).{0,20}reclamad", n):
        saida.append(_v("VINCULO_MEDICO_INFERIDO", "", "serviço médico da reclamada",
                        "A peça atribui o médico/clinica à reclamada sem documento que prove esse vínculo.",
                        "Identifique-o apenas como médico do trabalho/documento que integra a CAT, salvo prova do vínculo."))
    if "tema 84" in n and re.search(r"(agencia|movimentacao de valores).{0,100}tema 84|tema 84.{0,100}(agencia|movimentacao de valores)", n) and "analogia" not in n:
        saida.append(_v("TEMA_84_SEM_ANALOGIA", "", "Tema 84",
                        "O Tema 84 é aplicado diretamente a atividade diversa da entrega postal.",
                        "Explique expressamente a analogia e não atribua ao Tema 84 tese sobre movimentação de valores em agência."))
    if "art 195" in n and re.search(r"pericia (medica|psiquiatr|clinica)", n):
        saida.append(_v("ARTIGO_195_FORA_DO_TEMA", "", "art. 195 da CLT",
                        "O art. 195 da CLT foi usado para perícia médica, embora trate de insalubridade/periculosidade.",
                        "Fundamente a prova pericial médica no dispositivo processual pertinente ou retire a referência."))
    if re.search(r"art\.?\s*847.{0,100}revelia|revelia.{0,100}art\.?\s*847", n):
        saida.append(_v("ARTIGO_847_FORA_DO_TEMA", "", "art. 847 da CLT",
                        "O art. 847 da CLT foi associado à revelia; ele disciplina a defesa.",
                        "Use o art. 844 da CLT para revelia ou retire a referência."))
    if "ect" in n or "correios" in n or "ect" in pp.norm(str(((plano.get("partes") or {}).get("reu") or {}).get("nome") or "")):
        cnpj = str(((plano.get("partes") or {}).get("reu") or {}).get("cnpj") or "")
        if not pp._so_digitos(cnpj):  # noqa: SLF001
            saida.append(_v("CNPJ_RECLAMADA_AUSENTE", "HEADING", "ECT/Correios",
                            "A reclamada ECT foi qualificada sem CNPJ canônico no CASE_FACTS.",
                            "Preencha o CNPJ estruturado da reclamada antes de liberar a inicial."))
        if "juros" in n and re.search(r"forma da lei|regime vigente", n):
            saida.append(_v("JUROS_ECT_GENERICOS", "", "juros da ECT",
                            "Juros/correção da ECT foram formulados de modo genérico, sem enfrentar seu regime jurídico.",
                            "Indique o regime aplicável à ECT com fonte verificável, ou deixe o ponto para revisão humana."))
    return saida


def dado_rejeitado_no_texto(secoes: list[dict[str, Any]], case_facts: dict[str, Any]) -> list[Violacao]:
    """A versão PERDEDORA (ou em conflito) de um dado canônico não pode aparecer no texto: uma só verdade por peça."""
    texto = "\n".join(str(s.get("content") or "") for s in secoes)
    norm_t, dig_t = pp.norm(texto), pp._so_digitos(texto)  # noqa: SLF001
    saida = []
    for papel, campos in (case_facts.get("PARTIES") or {}).items():
        for campo, e in campos.items():
            for alt in e.get("alternativas") or []:
                mesma_raiz = campo == "cnpj" and e.get("valor") and pp._so_digitos(alt["valor"])[:8] == pp._so_digitos(e["valor"])[:8]  # noqa: SLF001
                if mesma_raiz:
                    continue  # matriz/filial: as duas são da mesma empresa, o que vale é não misturar na qualificação
                if pp._valor_consta(campo, alt["valor"], norm_t, dig_t):  # noqa: SLF001
                    saida.append(_v("DADO_REJEITADO_NO_TEXTO", "", f"{papel}.{campo}: {alt['valor']}",
                                    f"«{alt['valor']}» foi REJEITADO pelo CASE_FACTS para {papel}.{campo} (vale «{e.get('valor')}») mas aparece na peça.",
                                    "Use só o valor canônico; se o campo está em conflito, escreva uma única pendência."))
    return saida
