"""Contrato estrutural de uma petição, derivado da skill do escritório.

O modelo redige conteúdo; ele não pode criar uma arquitetura paralela.  Os
papéis são técnicos e estáveis, enquanto os títulos e a ordem vêm de
``estrutura_peca.md``.  Assim uma mudança da skill é visível no trace e não
vira uma regra escondida para um caso específico.
"""
from __future__ import annotations

import re
from typing import Any

from .conferencia_peticao import Violacao


def _norm(valor: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", valor.lower()) if unicodedata.category(c) != "Mn")


def papel(titulo: str) -> str | None:
    t = _norm(titulo)
    if "enderec" in t or "qualific" in t:
        return "HEADING"
    if "preliminar" in t:
        return "PRELIMINARY"
    if "fato" in t:
        return "FACTS"
    if "direito" in t or "fundament" in t:
        return "LEGAL_GROUNDS"
    if "pedido" in t:
        return "CLAIMS"
    if "valor" in t:
        return "VALUE"
    if "fechamento" in t or "assinatura" in t:
        return "CLOSING"
    return None


def montar(itens_da_skill: list[dict[str, str]]) -> dict[str, Any]:
    blocos = []
    for item in itens_da_skill:
        role = papel(str(item.get("titulo") or ""))
        if role:
            blocos.append({**item, "code": role})
    # blocos de abertura podem estar separados na skill, mas constituem uma só
    # seção física para impedir dupla qualificação.
    permitidos = []
    for bloco in blocos:
        if bloco["code"] not in permitidos:
            permitidos.append(bloco["code"])
    return {"fonte": "references/estrutura_peca.md", "blocos": blocos, "permitidos": permitidos}


def canonicalizar(secoes: list[dict[str, Any]], contrato: dict[str, Any]) -> tuple[list[dict[str, Any]], list[Violacao]]:
    """Converte aliases de título em papéis e barra arquitetura inventada.

    Não descarta texto desconhecido silenciosamente: ele fica identificado e a
    validação final retém a minuta. Isso evita tanto vazamento quanto perda de
    argumento durante uma correção automática.
    """
    permitidos = set(contrato.get("permitidos") or [])
    saida, achados = [], []
    vistos: set[str] = set()
    assinaturas: set[tuple[str, str]] = set()
    for secao in secoes:
        bruto = str(secao.get("code") or "")
        code = bruto.upper().strip()
        role = code if code in permitidos else papel(f"{secao.get('label') or ''} {bruto}")
        if role:
            secao = {**secao, "code": role}
        code = str(secao.get("code") or "")
        # Repetição literal de uma seção inteira é sempre erro de geração, até
        # para direito/preliminares que podem conter subtópicos distintos.
        assinatura = (code, re.sub(r"\s+", " ", _norm(str(secao.get("content") or "")).strip()))
        if assinatura in assinaturas:
            achados.append(Violacao("SECAO_DUPLICADA", code, str(secao.get("label") or code),
                "A mesma seção foi devolvida mais de uma vez pelo redator.",
                "Mantenha uma única ocorrência do bloco canônico.", True))
            continue
        assinaturas.add(assinatura)
        if code not in permitidos:
            achados.append(Violacao("SECAO_NAO_AUTORIZADA_PELA_SKILL", code, str(secao.get("label") or code),
                "A minuta criou uma seção que não consta do contrato extraído da skill.",
                "Mova o conteúdo para o bloco autorizado correspondente ou remova-o.", True))
        elif code in vistos and code not in {"LEGAL_GROUNDS", "PRELIMINARY"}:
            achados.append(Violacao("SECAO_DUPLICADA", code, str(secao.get("label") or code),
                "O contrato permite um único bloco para este papel; duplicá-lo causa abertura, pedidos ou fechamento repetidos.",
                "Una o conteúdo no bloco canônico.", True))
        vistos.add(code)
        saida.append(secao)
    ordem = {b["code"]: i for i, b in enumerate(contrato.get("blocos") or [])}
    ultima = -1
    for secao in saida:
        atual = ordem.get(str(secao.get("code") or ""))
        if atual is not None and atual < ultima:
            achados.append(Violacao("ORDEM_DE_SECOES_DIVERGENTE_DA_SKILL", str(secao.get("code")), "",
                "A ordem dos blocos diverge de estrutura_peca.md.", "Reordene conforme o contrato da skill.", True))
            break
        if atual is not None:
            ultima = atual
    return saida, achados
