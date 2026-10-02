"""Strict: o que é DADO na peça sai do código, não do modelo.

- Capítulo de pedidos: um item por pedido estruturado do PETITION_PLAN, com o valor do cálculo e o
  `calculation_id`; reflexos e perícia quando o plano manda.
- Valor da causa: a soma única de `calculos.valor_da_causa`.
- Data do fechamento: a `petition_date` (data da geração), por extenso — substitui marcador de modelo
  («[data por extenso]») e data velha de peça antiga.
- Tabelas: `[[TABELA:categoria]]` vira a tabela montada com os dados canônicos.
- Memória de cálculo: sempre ao fim dos pedidos (se a redação não pôs o marcador em outro lugar), uma linha
  por cálculo com base, documento de origem, conta e resultado — pedido trabalhista é líquido.

O modelo redige o argumento; números, datas e listas de pedidos não passam por ele.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from . import calculos as calc
from . import datas, tabelas

_ASSINATURA = re.compile(r"OAB|advogad[oa]|procurador", re.I)
INTRODUCAO_MEMORIA = "Memória de cálculo dos pedidos (valores líquidos, discriminados por parcela, com a base e o documento de origem):"
_LISTA = re.compile(r"(?m)^\s*(?:[a-z]{1,2}\)|\d+[.)]|[-•*])\s+")


def _letra(i: int) -> str:
    letras = "abcdefghijklmnopqrstuvwxyz"
    return letras[i] if i < 26 else letras[i // 26 - 1] + letras[i % 26]


def _introducao(conteudo_do_modelo: str) -> str:
    """A frase de abertura que o modelo escreveu («Diante do exposto, requer:»), se não trouxer número nem lista."""
    primeiro = next((p.strip() for p in re.split(r"\n\s*\n", conteudo_do_modelo or "") if p.strip()), "")
    if primeiro and len(primeiro) <= 400 and not re.search(r"\d|R\$", primeiro) and not _LISTA.match(primeiro):
        return primeiro
    return "Diante do exposto, requer:"


def secao_pedidos(plano: dict[str, Any], *, introducao: str = "Diante do exposto, requer:") -> str:
    itens: list[str] = []
    pericias: list[str] = []
    for p in plano.get("pedidos") or []:
        if p.get("status") == "PENDING_CALCULATION":
            continue
        objeto = str(p.get("objeto") or p.get("title") or p.get("tipo") or "").strip().rstrip(".;")
        if not objeto:
            continue
        linha = objeto[:1].lower() + objeto[1:] if len(objeto) > 1 and objeto[1].islower() else objeto
        if p.get("value") not in (None, "") or p.get("valor") not in (None, ""):
            valor = p.get("value") if p.get("value") not in (None, "") else p.get("valor")
            # Pedido financeiro sem cálculo não pode virar valor arbitrário no
            # documento final. A pendência já fica registrada no plano/auditoria.
            if not p.get("calculation_id"):
                continue
            linha += f", no valor de {calc.brl(calc.valor_numerico(valor) or 0)}"
            linha += f" (memória de cálculo {p['calculation_id']})"
        if p.get("reflexes"):
            linha += ", com reflexos em " + ", ".join(p["reflexes"])
        itens.append(linha)
        if p.get("expert_evidence_required"):
            pericias.append(str(p.get("title") or objeto))
    if pericias:
        itens.append("a produção de prova pericial para apuração dos fatos que a exigem (" + "; ".join(dict.fromkeys(pericias)) + ")")
    corpo = [f"{_letra(i)}) {texto};" for i, texto in enumerate(itens)]
    if corpo:
        corpo[-1] = corpo[-1][:-1] + "."
    return "\n\n".join([introducao, *corpo]) if corpo else introducao


def secao_valor(plano: dict[str, Any]) -> str:
    vc = calc.valor_da_causa(plano.get("pedidos") or [])
    if not vc["valor"]:
        return ""
    return f"Dá-se à causa o valor de {calc.brl(vc['valor'])}."


def fechamento_com_data(conteudo: str, petition_date: date) -> tuple[str, dict[str, Any]]:
    """Troca marcador e data antiga pela data da petição; sem data, insere antes da assinatura."""
    alvo = datas.por_extenso(petition_date)
    rel: dict[str, Any] = {"marcadores_trocados": 0, "datas_trocadas": [], "inserida": False}
    texto, n = datas.PLACEHOLDER.subn(alvo, conteudo or "")
    rel["marcadores_trocados"] = n
    for d in reversed(datas.extrair(texto)):
        if d.trecho != alvo:
            rel["datas_trocadas"].append(d.trecho)
            texto = texto[:d.inicio] + alvo + texto[d.fim:]
    if alvo not in texto:
        linhas = texto.split("\n")
        i = next((k for k, l in enumerate(linhas) if _ASSINATURA.search(l)), len(linhas))
        linhas.insert(i, f"{alvo}.")
        texto = "\n".join(linhas)
        rel["inserida"] = True
    return texto, rel


def renderizar(secoes: list[dict[str, Any]], prep: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    plano = prep["plano_est"]
    petition_date: date = prep["data_referencia"]
    rel: dict[str, Any] = {"pedidos_renderizados": 0, "valor_da_causa": None, "fechamento": None, "tabelas": [], "marcadores_sem_dados": []}
    novas: list[dict[str, Any]] = []
    codigos = {str(s.get("code") or "") for s in secoes}
    for s in secoes:
        code = str(s.get("code") or "")
        conteudo = str(s.get("content") or "")
        if code == "CLAIMS":
            conteudo = secao_pedidos(plano, introducao=_introducao(conteudo))
            rel["pedidos_renderizados"] = len(re.findall(r"(?m)^[a-z]{1,2}\) ", conteudo))
        elif code == "VALUE":
            conteudo = secao_valor(plano) or conteudo
            rel["valor_da_causa"] = calc.valor_da_causa(plano.get("pedidos") or [])
        elif code == "CLOSING":
            conteudo, rel["fechamento"] = fechamento_com_data(conteudo, petition_date)
        conteudo, feitas, vazias = tabelas.aplicar_marcadores(conteudo, matriz=prep["matriz"], canon=prep.get("canonico"), calculos=prep["calculos"])
        rel["tabelas"] += feitas
        rel["marcadores_sem_dados"] += vazias
        novas.append({**s, "content": conteudo})
    memoria = tabelas.construir("memoria_de_calculo", matriz=prep["matriz"], canon=prep.get("canonico"), calculos=prep["calculos"])
    if memoria and "memoria_de_calculo" not in rel["tabelas"]:
        i = next((k for k, s in enumerate(novas) if s.get("code") == "CLAIMS"), None)
        if i is not None:
            novas[i] = {**novas[i], "content": f"{novas[i]['content']}\n\n{INTRODUCAO_MEMORIA}\n\n{memoria}"}
            rel["tabelas"].append("memoria_de_calculo")
            rel["memoria_de_calculo_anexada"] = True
    if "VALUE" not in codigos and secao_valor(plano):
        i = next((k for k, s in enumerate(novas) if s.get("code") == "CLOSING"), len(novas))
        novas.insert(i, {"code": "VALUE", "label": "", "content": secao_valor(plano)})
        rel["valor_da_causa"] = calc.valor_da_causa(plano.get("pedidos") or [])
    return novas, rel
