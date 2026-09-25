"""PETITION LINTER — validação determinística ANTES de a peça virar DOCX.

Complementa `conferencia_peticao` (que confere o texto contra os autos) com o que só o PLANO
estruturado permite verificar: partes qualificadas, pedidos únicos e vindos do plano, fatos de uma
tese não vazando para outra e nenhum dado de petição antiga (acervo) tratado como fato do cliente.

Tudo aqui é código: o LLM redige e revisa semântica; o linter garante presença de blocos, ids,
relacionamentos e integridade. Regras jurídicas/editoriais ficam na SKILL (`validacoes.md`,
parâmetros `qualificacao` e `estrutura`): este módulo lê de lá QUAIS campos a qualificação exige.
"""

from __future__ import annotations

import re
from typing import Any

from . import plano_da_peticao as pp
from .conferencia_peticao import Violacao
from .recuperacao_por_secao import dividir_em_topicos

_DATA = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
_VALOR = re.compile(r"R\$\s*[\d.]+,\d{2}")
_NUMERO = re.compile(r"(?<![\d,])\d[\d./-]{4,}\d(?![\d,])")
_ITEM = re.compile(r"^\s*(?:\*\*)?([a-z])\)\s*(.+)$", re.MULTILINE)


def _especificos(texto: str) -> set[str]:
    """Marcadores que identificam UM caso: datas, valores em reais e números longos (CPF, CNPJ, NB…)."""
    achados = {m.group(0) for m in _DATA.finditer(texto)}
    achados |= {re.sub(r"\s+", "", m.group(0)) for m in _VALOR.finditer(texto)}
    achados |= {pp._so_digitos(m.group(0)) for m in _NUMERO.finditer(texto) if len(pp._so_digitos(m.group(0))) >= 6}  # noqa: SLF001
    return achados


def _presente(marcador: str, texto: str) -> bool:
    if "/" in marcador or marcador.startswith("R$"):
        return marcador in texto or marcador in re.sub(r"\s+", "", texto)
    return marcador in pp._so_digitos(texto)  # noqa: SLF001


def _secao(secoes: list[dict[str, Any]], codigo: str) -> dict[str, Any] | None:
    return next((s for s in secoes if s.get("code") == codigo), None)


def _achado(codigo: str, secao: str, trecho: str, motivo: str, correcao: str, bloqueia: bool = True) -> Violacao:
    return Violacao(codigo, secao, trecho[:220], motivo, correcao, bloqueia)


# ------------------------------------------------------------------ estrutura + qualificação

def _estrutura_e_qualificacao(secoes: list[dict[str, Any]], plano: dict[str, Any], params: dict[str, Any]) -> list[Violacao]:
    saida: list[Violacao] = []
    q = params.get("qualificacao") or {}
    codigo_abertura = q.get("secao", "HEADING")
    abertura = _secao(secoes, codigo_abertura) or (secoes[0] if secoes else None)
    texto = str((abertura or {}).get("content") or "")
    regex_ender = (params.get("estrutura") or {}).get("enderecamento_regex")
    if regex_ender and not re.search(regex_ender, texto, re.IGNORECASE):
        saida.append(_achado("ENDERECAMENTO_AUSENTE", codigo_abertura, texto[:80], "A peça não abre com o endereçamento exigido pela skill.",
                             "Abra a peça com o endereçamento conforme a skill (estrutura_peca.md)."))
    if not q.get("exigida"):
        return saida
    partes = plano.get("partes") or {}
    autor = partes.get("autor") or {}
    reu = partes.get("reu") or {}
    norm_texto, dig_texto = pp.norm(texto), pp._so_digitos(texto)  # noqa: SLF001
    ausentes: list[str] = []
    for papel, dados in (("autor", autor), ("reu", reu)):
        for campo in q.get("campos", {}).get(papel, []):
            valor = dados.get(campo)
            if valor and not pp._valor_consta(campo, valor, norm_texto, dig_texto):  # noqa: SLF001
                ausentes.append(f"{papel}.{campo}")
    nome = autor.get("nome", "")
    sem_bloco = not texto.strip() or (nome and pp.norm(nome) not in norm_texto)
    if sem_bloco or len(ausentes) > max(1, len(q.get("campos", {}).get("autor", [])) // 2):
        dados = "; ".join(f"{p}.{k}: {v}" for p in ("autor", "reu") for k, v in (partes.get(p) or {}).items())
        saida.append(_achado(
            "QUALIFICACAO_AUSENTE", codigo_abertura, texto[:120],
            "Este tipo de peça exige a qualificação das partes na abertura e ela não está (ou está incompleta): "
            + (", ".join(ausentes) or "nome do autor ausente"),
            "Inclua a qualificação com EXATAMENTE estes dados do caso, sem inventar nenhum: " + dados
            + ". Campo que não consta vira [PENDENTE: <campo>].",
        ))
    return saida


# ------------------------------------------------------------------ pedidos

def _itens_de_pedidos(secoes: list[dict[str, Any]], codigo: str = "CLAIMS") -> list[str]:
    s = _secao(secoes, codigo)
    return [m.group(2).strip() for m in _ITEM.finditer(str((s or {}).get("content") or ""))]


def _pedidos(secoes: list[dict[str, Any]], plano: dict[str, Any]) -> list[Violacao]:
    saida: list[Violacao] = []
    itens = _itens_de_pedidos(secoes)
    tokens = [pp._tokens(i[:200]) for i in itens]  # noqa: SLF001
    for a in range(len(itens)):
        for b in range(a + 1, len(itens)):
            if pp._jaccard(tokens[a], tokens[b]) >= 0.55:  # noqa: SLF001
                saida.append(_achado("PEDIDO_DUPLICADO", "CLAIMS", itens[b], "O mesmo pedido aparece duas vezes na seção de pedidos.",
                                     "Mantenha um só e funda os fundamentos; a seção é montada a partir do plano estruturado."))
    por_id = plano.get("pedidos") or []
    uso: dict[str, int] = {}
    for texto, tk in zip(itens, tokens):
        melhor, pontos = None, 0.0
        for p in por_id:
            s = pp._jaccard(tk, pp._tokens(f"{p['tipo']} {p['objeto']} {p['fundamento']}"))  # noqa: SLF001
            if s > pontos:
                melhor, pontos = p, s
        if melhor is None or pontos < 0.12:
            saida.append(_achado("PEDIDO_FORA_DO_PLANO", "CLAIMS", texto, "Pedido que não nasce de nenhuma tese do plano do caso (possível pedido trazido de outra petição).",
                                 "Remova: pedido só existe se decorre de tese fundamentada com fatos DESTE caso."))
        else:
            uso[melhor["id"]] = uso.get(melhor["id"], 0) + 1
    for id_, n in uso.items():
        if n > 1:
            saida.append(_achado("PEDIDO_DUPLICADO", "CLAIMS", id_, f"O pedido {id_} do plano foi escrito {n} vezes.", "Um pedido do plano, uma linha na seção."))
    teses = {t["id"]: t for t in plano.get("teses") or []}
    for p in por_id:
        if p["de_praxe"]:
            continue
        tese = teses.get(p["tese_origem"])
        if not tese:
            saida.append(_achado("PEDIDO_SEM_TESE", "CLAIMS", f"{p['id']} {p['tipo']}", "Pedido sem tese de origem.", "Vincule a uma tese fundamentada ou remova."))
        elif not tese["fatos_ids"]:
            saida.append(_achado("PEDIDO_SEM_FATO_NO_CASO", "CLAIMS", f"{p['id']} {p['tipo']}", f"A tese {tese['id']} do pedido não tem nenhum fato do caso que a sustente.",
                                 "Sem fato do caso não há pedido — nunca aproveite pedido de peça antiga."))
        if not p["fundamento"]:
            saida.append(_achado("PEDIDO_SEM_FUNDAMENTO", "CLAIMS", f"{p['id']} {p['tipo']}", "Pedido sem fundamento registrado.", "Registre o fundamento legal/tese.", False))
    return saida


# ------------------------------------------------------------------ fontes: nada do acervo como fato do caso

def _contaminacao(secoes: list[dict[str, Any]], texto_do_caso: str, textos_do_acervo: list[str]) -> list[Violacao]:
    saida: list[Violacao] = []
    acervo = "\n".join(textos_do_acervo)
    if not acervo:
        return saida
    vistos: set[str] = set()
    for s in secoes:
        for m in sorted(_especificos(str(s.get("content") or ""))):
            if m in vistos or _presente(m, texto_do_caso):
                continue
            if _presente(m, acervo):
                vistos.add(m)
                saida.append(_achado("CONTAMINACAO_DO_ACERVO", str(s.get("code")), m,
                                     f"«{m}» aparece na peça, não consta dos documentos/entrevista do caso e consta de petição do acervo (outro cliente).",
                                     "Retire ou troque pelo dado do caso atual; peça do acervo é inspiração de argumento, nunca fonte de fato, valor ou data."))
    return saida


# ------------------------------------------------------------------ isolamento entre teses

def _isolamento(secoes: list[dict[str, Any]], plano: dict[str, Any]) -> list[Violacao]:
    saida: list[Violacao] = []
    teses = plano.get("teses") or []
    if len(teses) < 2:
        return saida
    por_id = {f["id"]: f for f in plano["fatos"]}
    comuns = pp.fatos_comuns(plano)

    def especificos(ids: set[str]) -> set[str]:
        return set().union(*[_especificos(f"{por_id[i]['data']} {por_id[i]['fato']}") for i in ids if i in por_id]) if ids else set()

    for s in secoes:
        if s.get("code") in ("HEADING", "CLOSING", "VALUE", "CLAIMS"):
            continue
        for t in dividir_em_topicos(str(s.get("content") or "")):
            tese = pp.tese_do_topico(plano, t["titulo"], t["corpo"]) if t["titulo"] else None
            if not tese or not tese["fatos_ids"]:
                continue  # sem fatos declarados a tese não tem contra o que ser julgada (o plano é que está incompleto)
            proprios = set(tese["fatos_ids"]) | comuns
            permitidos = especificos(proprios)
            de_outras = especificos({i for o in teses if o["id"] != tese["id"] for i in o["fatos_ids"]} - proprios)
            for m in sorted(_especificos(t["corpo"]) & de_outras - permitidos):
                saida.append(_achado("MISTURA_DE_TESES", str(s.get("code")), f"{t['titulo'][:50]}: {m}",
                                     f"«{m}» é dado de OUTRA tese e aparece no tópico «{t['titulo'][:60]}» ({tese['id']}), cujos fatos não o incluem.",
                                     "Retire o dado deste tópico ou, se o fato realmente serve às duas teses, declare-o nas duas no plano."))
    return saida


# ------------------------------------------------------------------ coerência

def _coerencia(secoes: list[dict[str, Any]], texto_do_caso: str) -> list[Violacao]:
    saida: list[Violacao] = []
    for s in secoes:
        for m in re.finditer(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", str(s.get("content") or "")):
            if pp._so_digitos(m.group(0)) not in pp._so_digitos(texto_do_caso):  # noqa: SLF001
                saida.append(_achado("CPF_CNPJ_SEM_ORIGEM", str(s.get("code")), m.group(0), f"{m.group(0)} não consta do caso.", "Use o número dos documentos ou [PENDENTE]."))
    return saida


def lintar(
    secoes: list[dict[str, Any]], plano: dict[str, Any], *, texto_do_caso: str, textos_do_acervo: list[str], params: dict[str, Any]
) -> list[Violacao]:
    """Achados do linter (BLOQUEANTES e avisos), na ordem: estrutura, pedidos, fontes, teses, coerência."""
    plano = {**plano, "_fontes": [texto_do_caso]}
    return [
        *_estrutura_e_qualificacao(secoes, plano, params),
        *_pedidos(secoes, plano),
        *_contaminacao(secoes, texto_do_caso, textos_do_acervo),
        *_isolamento(secoes, plano),
        *_coerencia(secoes, texto_do_caso),
    ]
