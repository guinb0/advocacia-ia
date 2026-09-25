"""DOCUMENTO FINAL — higiene determinística + FINAL_DOCUMENT_VALIDATOR sobre o que será EFETIVAMENTE renderizado.

POR QUE ESTE MÓDULO EXISTE (v11)

Os validadores anteriores rodavam sobre o rascunho e sobre seções "como o modelo as devolveu". Erros chegavam ao PDF
porque nasciam DEPOIS ou ONDE o validador não olhava: um título escrito em texto corrido (sem `#`) dentro da seção de
pedidos passava por "título" no documento mas não na numeração; um título de ação vinha de um bloco e de um parágrafo
em negrito ao mesmo tempo; a instrução de registro de alterações do chat virava uma seção da peça.

Aqui a regra é: `higienizar` aplica só correções SEGURAS e determinísticas (metadado interno sai do documento,
numeração é estrutural, título/abertura repetidos saem) e `validar_documento_final` confere o resultado sobre a
MESMA representação que `montar_docx` imprime (rótulos impressos + conteúdo, após a migração de peças legadas).
Depois disso nada pode mudar as seções: `impressao_hash` é conferido antes de gravar.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from . import auditoria_estrutural as ae
from . import document_ledger, peticao_migracao_legado, petition_linter, plano_da_peticao as pp
from .conferencia_peticao import Violacao
from .recuperacao_por_secao import paragrafos

_TITULO_ROMANO = re.compile(r"^\s*(?:#{1,3}\s*)?(?:\*\*)?([IVXLC]+)\s*[.\-–—)]\s+(\S.{2,90}?)(?:\*\*)?\s*$")
_ROMANOS = [(100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def _v(codigo: str, secao: str, trecho: str, motivo: str, correcao: str, bloqueia: bool = True) -> Violacao:
    return Violacao(codigo, secao, str(trecho)[:220], motivo, correcao, bloqueia)


def para_romano(n: int) -> str:
    saida = ""
    for v, s in _ROMANOS:
        while n >= v:
            saida += s
            n -= v
    return saida


def _titulo_sem_numero(texto: str) -> str:
    m = _TITULO_ROMANO.match(texto)
    return pp.norm(m.group(2) if m else texto)


# ------------------------------------------------------------------ representação FINAL (o que sai no DOCX)

def representacao_final(secoes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """As seções exatamente como `montar_docx` as imprime: migração de legado aplicada e rótulo impresso como `# `."""
    migradas = peticao_migracao_legado.migrar_secoes(secoes)
    saida = []
    for s in migradas:
        conteudo = str(s.get("content") or "")
        rotulo = str(s.get("label") or "").strip()
        if petition_linter.deve_imprimir_rotulo(rotulo, conteudo):
            conteudo = f"# {rotulo}\n\n{conteudo}"
        saida.append({**s, "content": conteudo})
    return saida


def impressao_hash(secoes: list[dict[str, Any]]) -> str:
    return hashlib.sha256("\n␞".join(str(s.get("content") or "") for s in representacao_final(secoes)).encode("utf-8")).hexdigest()[:16]


def headings_reais(secoes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Todo título de capítulo como ele aparece — com `#`, em negrito ou em texto corrido (o que a v11 escondia)."""
    saida = []
    for s in representacao_final(secoes):
        for linha in str(s.get("content") or "").split("\n"):
            m = _TITULO_ROMANO.match(linha.strip())
            if m and len(linha.strip()) <= 100 and not linha.rstrip().endswith((".", ";", ":")) or (m and re.match(r"^\s*#", linha)):
                saida.append({"secao": str(s.get("code")), "texto": linha.strip("# *"), "numero": m.group(1), "titulo": pp.norm(m.group(2))})
    return saida


# ------------------------------------------------------------------ higiene determinística

def _cortar_metadata(secoes: list[dict[str, Any]], params: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Metadado interno de geração (registro de alterações, relatório) NÃO é conteúdo da peça: sai e vai para o relatório."""
    meta = params.get("metadata_interna") or {}
    titulos = [re.compile(r, re.IGNORECASE) for r in meta.get("titulos", [])]
    rotulos = [re.compile(r, re.IGNORECASE | re.MULTILINE) for r in meta.get("rotulos", [])]
    removidos: list[dict[str, str]] = []
    saida = []
    for s in secoes:
        conteudo, rotulo = str(s.get("content") or ""), str(s.get("label") or "")
        if any(t.search(rotulo) for t in titulos):
            removidos.append({"secao": str(s.get("code")), "texto": conteudo[:4000]})
            continue
        linhas = conteudo.split("\n")
        corte = None
        for i, linha in enumerate(linhas):
            limpa = linha.strip("# *:")
            if len(limpa) <= 80 and any(t.search(limpa) for t in titulos):
                corte = i
                break
        if corte is None and len({i for i, r in enumerate(rotulos) if r.search(conteudo)}) >= 3:
            # o bloco só aparece como "Formatação: … Organização: … Inclusões: …" sem título: corta a partir do 1º rótulo
            primeiros = [m.start() for r in rotulos for m in [r.search(conteudo)] if m]
            inicio = min(primeiros)
            corte = conteudo[:inicio].count("\n")
        if corte is not None:
            removidos.append({"secao": str(s.get("code")), "texto": "\n".join(linhas[corte:])[:4000]})
            conteudo = "\n".join(linhas[:corte]).rstrip()
            if not conteudo.strip():
                continue
        saida.append({**s, "content": conteudo})
    return saida, removidos


def _remover_titulos_repetidos(secoes: list[dict[str, Any]], params: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Uma seção lógica = um heading: título estrutural cujo texto (sem o número) já apareceu sai; o título da ação fica uma vez.

    Pega também o título escrito como PRIMEIRA LINHA de um parágrafo (sem `#`), que era como o «III. Dos Pedidos» da v11
    escapava da validação de numeração. Do título da ação, fica o que vem logo após «propor a presente» (a fórmula
    narrativa da skill); os demais saem.
    """
    regex_acao = (params.get("estrutura") or {}).get("titulo_da_acao_regex")
    vistos: set[str] = set()
    removidos = 0
    novas: list[dict[str, Any]] = []
    acoes: list[tuple[int, int, bool]] = []  # (secao, indice do trecho, vem após "propor a presente")
    blocos_por_secao: list[list[str]] = []
    for si, s in enumerate(secoes):
        rotulo = str(s.get("label") or "")
        if rotulo and _TITULO_ROMANO.match(rotulo) and petition_linter.deve_imprimir_rotulo(rotulo, str(s.get("content") or "")):
            chave = _titulo_sem_numero(rotulo)
            vistos.add(chave)
        pars = re.split(r"(\n\s*\n)", str(s.get("content") or ""))
        anterior = ""
        for pi, trecho in enumerate(pars):
            if re.fullmatch(r"\n\s*\n", trecho) or not trecho.strip():
                continue
            linhas = trecho.strip().split("\n")
            primeira = linhas[0].strip()
            if _TITULO_ROMANO.match(primeira) and len(primeira) <= 100 and not primeira.endswith((".", ";", ":")) or re.match(r"^#\s", primeira):
                chave = _titulo_sem_numero(primeira.lstrip("# "))
                if chave in vistos and s.get("code") != "HEADING" and _TITULO_ROMANO.match(primeira.lstrip("# ")):
                    resto = "\n".join(linhas[1:]).strip()
                    pars[pi] = resto
                    removidos += 1
                    trecho = resto
                else:
                    vistos.add(chave)
            visivel = re.sub(r"^:::.*$", "", trecho, flags=re.MULTILINE).strip().strip("*# ")
            if regex_acao and visivel and len(visivel.split()) <= 16 and re.match(regex_acao, visivel, re.IGNORECASE):
                acoes.append((si, pi, bool(re.search(r"propor\s+a\s+presente\s*:?\s*$", anterior.strip(), re.IGNORECASE))))
            anterior = trecho
        blocos_por_secao.append(pars)
    if len(acoes) > 1:
        manter = next((a for a in acoes if a[2]), acoes[0])
        for si, pi, _ in acoes:
            if (si, pi) != manter[:2]:
                blocos_por_secao[si][pi] = ""
                removidos += 1
    for s, pars in zip(secoes, blocos_por_secao):
        texto = re.sub(r"\n{3,}", "\n\n", "".join(pars)).strip()
        novas.append({**s, "content": texto})
    return novas, removidos


def _renumerar_capitulos(secoes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Numeração ESTRUTURAL: os números romanos dos capítulos são recalculados na ordem em que saem — o modelo não escolhe número."""
    n = 0
    novas = []
    for s in secoes:
        rotulo, conteudo = str(s.get("label") or "").strip(), str(s.get("content") or "")
        m = _TITULO_ROMANO.match(rotulo)
        if m and petition_linter.deve_imprimir_rotulo(rotulo, conteudo):
            n += 1
            rotulo = f"{para_romano(n)}. {m.group(2)}"
        primeira = conteudo.lstrip().split("\n", 1)[0]
        mc = re.match(r"^#\s+([IVXLC]+)\s*[.\-–—)]\s+(.*)$", primeira)
        if mc:
            n += 1
            conteudo = conteudo.replace(primeira, f"# {para_romano(n)}. {mc.group(2)}", 1)
        novas.append({**s, "label": rotulo, "content": conteudo})
    return novas


def higienizar(secoes: list[dict[str, Any]], plano: dict[str, Any], params: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rel: dict[str, Any] = {}
    secoes = peticao_migracao_legado.migrar_secoes(secoes)
    secoes, metadata = _cortar_metadata(secoes, params)
    rel["metadata_interna_removida"] = metadata
    secoes, n_repetidos = _remover_titulos_repetidos(secoes, params)
    rel["titulos_repetidos_removidos"] = n_repetidos
    if plano.get("partes"):
        secoes, n_ab = ae.remover_aberturas_duplicadas(secoes, plano["partes"], params)
        rel["aberturas_duplicadas_removidas"] = n_ab
    secoes = [s for s in secoes if str(s.get("content") or "").strip() or str(s.get("label") or "").strip() == ""] or secoes
    secoes = _renumerar_capitulos(secoes)
    return secoes, rel


# ------------------------------------------------------------------ FINAL_DOCUMENT_VALIDATOR

def _frases(texto: str) -> list[str]:
    return [f.strip() for f in re.split(r"(?<=[.;!?])\s+|\n+", texto) if len(f.strip()) > 20]


def epistemica(secoes: list[dict[str, Any]], params: dict[str, Any], plano: dict[str, Any]) -> list[Violacao]:
    """Ausência de prova ≠ prova de ausência — no nível da FRASE, com a classificação de evidência do plano."""
    ep = params.get("epistemica") or {}
    if not ep:
        return []
    neg, cert = re.compile(ep["negacao"], re.IGNORECASE), re.compile(ep["certeza"], re.IGNORECASE)
    qual = re.compile(ep["qualificador"], re.IGNORECASE)
    req = re.compile(ep.get("requerimento_probatorio", "$^"), re.IGNORECASE)
    saida: list[Violacao] = []
    categoricas: list[tuple[str, set[str]]] = []
    frases = [(str(s.get("code")), f) for s in secoes for f in _frases(str(s.get("content") or ""))]
    ausencias = [pp._tokens(a.get("afirmacao", "")) for a in plano.get("ausencias") or []]  # noqa: SLF001
    for codigo, f in frases:
        eh_ausencia = bool(neg.search(f)) or any(len(a & pp._tokens(f)) >= 3 for a in ausencias)  # noqa: SLF001
        normalizada = pp.norm(f)
        eh_ausencia = eh_ausencia or bool(re.search(r"\b(ausencia|inexistencia|falta) de\b", normalizada))
        categorica = bool(cert.search(f)) or bool(re.search(r"documentalmente (demonstr|comprov)|esta (comprov|demonstr)|restou (comprov|demonstr)|comprova.* que nao", normalizada))
        qualificada = bool(qual.search(f)) or bool(re.search(r"documentos? (disponiveis|juntados)|nao (consta|registra|ha registro)|segundo o relato", normalizada))
        # "não mera alegação" não é qualificador: é precisamente afirmação categórica.
        qualificada = qualificada and "mera alegacao" not in normalizada
        if eh_ausencia and categorica and not qualificada:
            saida.append(_v("AUSENCIA_REDIGIDA_COMO_CONFIRMADA", codigo, f, "Fato «não encontrado nos documentos disponíveis» foi redigido como ausência CONFIRMADA/demonstrada.",
                            "Reescreva como: «os documentos disponíveis não registram …», e — se importa — requeira a prova; nunca «está comprovado que não havia …»."))
            categoricas.append((codigo, {t for t in pp._tokens(f) if len(t) >= 6}))  # noqa: SLF001
    if categoricas:
        for codigo, f in frases:
            if req.search(f) or re.search(r"\b(exibi|exib|prova|esclarec|pericia)\w*", pp.norm(f)):
                tk = {t for t in pp._tokens(f) if len(t) >= 6}  # noqa: SLF001
                for cod2, tokens in categoricas:
                    if len(tk & tokens) >= 2:
                        saida.append(_v("AFIRMACAO_CATEGORICA_X_PROVA_REQUERIDA", codigo, f, f"A peça afirma como demonstrado (seção {cod2}) o que depois requer prova para esclarecer.",
                                        "Ou o fato está provado (e não se requer a prova para apurá-lo) ou é alegação/ausência documental (e a afirmação categórica sai)."))
                        break
    return saida


def metadata_no_documento(secoes: list[dict[str, Any]], params: dict[str, Any]) -> list[Violacao]:
    _, removidos = _cortar_metadata(secoes, params)
    return [_v("METADATA_INTERNA_NO_DOCUMENTO", r["secao"], r["texto"][:100], "Metadado interno de geração (ex.: registro de alterações) no documento da peça.", "Remova: relatório interno não faz parte da peça.") for r in removidos]


def pedidos_no_texto(secoes: list[dict[str, Any]]) -> list[Violacao]:
    """Sobreposição econômica no que foi EFETIVAMENTE escrito: item de majoração com valor próprio ao lado do pedido que ele majora."""
    saida = []
    itens = []
    for s in secoes:
        if s.get("code") == "CLAIMS":
            itens += [m.group(2) for m in re.finditer(r"^\s*(?:\*\*)?([a-z])\)\s*(.+)$", str(s.get("content") or ""), re.MULTILINE)]
    monetarios = [i for i in itens if re.search(r"R\$\s*[\d.]+,\d{2}", i)]
    for i, a in enumerate(monetarios):
        if ae._MAJORACAO.search(a[:200]):  # noqa: SLF001
            for b in monetarios:
                if b is not a and pp._jaccard(pp._tokens(a[:220]), pp._tokens(b[:220])) >= 0.15 and not ae._MAJORACAO.search(b[:200]):  # noqa: SLF001
                    saida.append(_v("MAJORACAO_COMO_SEGUNDA_INDENIZACAO", "CLAIMS", a[:120], "Um pedido de MAJORAÇÃO com valor próprio ao lado do pedido que ele majora: o agravante virou segunda indenização.",
                                    "O agravante entra na quantificação do pedido principal (um só valor, com o critério), não como pedido econômico separado."))
                    break
    return saida


def validar_documento_final(
    secoes: list[dict[str, Any]], plano: dict[str, Any], params: dict[str, Any], ledger: list[dict[str, Any]] | None = None,
) -> list[Violacao]:
    """Tudo o que precisa ser verdade no artefato final — rodado sobre `representacao_final` (o que sai no DOCX)."""
    final = representacao_final(secoes)
    hs = headings_reais(secoes)
    saida: list[Violacao] = []
    # headings: título estrutural repetido / numeração real
    por_titulo: dict[str, list[dict[str, Any]]] = {}
    for h in hs:
        por_titulo.setdefault(h["titulo"], []).append(h)
    for t, lista in por_titulo.items():
        if len(lista) > 1:
            saida.append(_v("HEADING_DUPLICADO", lista[1]["secao"], " / ".join(h["texto"] for h in lista), f"O capítulo «{t}» aparece {len(lista)} vezes como título.", "Uma seção lógica = um heading estrutural."))
    saida += ae.numeracao([(h["secao"], f"{h['numero']}. {h['titulo']}") for h in hs])
    if sum(1 for s in final if s.get("code") == "CLAIMS") > 1:
        saida.append(_v("PEDIDOS_EM_MAIS_DE_UMA_SECAO", "CLAIMS", "", "A seção de pedidos aparece mais de uma vez.", "Só uma seção estrutural de pedidos."))
    saida += ae.abertura_unica(final, plano.get("partes") or {}, params)
    saida += metadata_no_documento(secoes, params)
    saida += [_v("PLACEHOLDER_NO_DOCUMENTO_FINAL", c, m, f"Marcador {m[:60]} no documento final.", "Resolva o dado ou registre a pendência para revisão humana antes de considerar a peça pronta.", False) for c, m in ae.pendencias(final)]
    saida += ae.pendencia_com_dado_canonico(final, plano.get("partes") or {})
    saida += ae.dado_rejeitado_no_texto(final, plano.get("case_facts") or {})
    if ledger:
        saida += document_ledger.validar_bijecao(ledger) + document_ledger.validar_referencias(final, ledger)
    saida += pedidos_no_texto(final) + ae.ledger(plano) + ae.valor_da_causa(final, plano) + ae.criterio_de_calculo(final, params)
    saida += epistemica(final, params, plano)
    return saida
