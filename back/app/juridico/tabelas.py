"""USE_TABLE: em quais categorias a peça apresenta os dados em tabela.

Decisão de APRESENTAÇÃO, por volume de dados estruturados na matriz e nos cálculos — não de conteúdo
jurídico. A preferência da skill (`preferir_tabelas`) sobrepõe o limiar.
"""

from __future__ import annotations

import re
from typing import Any

from . import canonico
from .autoridades import _data
from .calculos import brl

CATEGORIAS = ("contrato", "cronologia", "pagamentos", "descontos", "fgts", "jornada", "provas", "memoria_de_calculo")

#: Itens homogêneos a partir dos quais a tabela é a preferência inicial (salvo veto da skill).
LIMIAR_HOMOGENEO = 3
#: Itens mínimos para a tabela valer mais que o texto corrido; nenhuma categoria exige mais que LIMIAR_HOMOGENEO.
LIMIARES = {c: min(n, LIMIAR_HOMOGENEO) for c, n in {
    "contrato": 3, "cronologia": 3, "pagamentos": 3, "descontos": 2, "fgts": 2, "jornada": 2, "provas": 3, "memoria_de_calculo": 1}.items()}

_PREFIXOS = {"contrato": ("contrato.", "autor.", "reu."), "pagamentos": ("pagamento.", "salario."), "descontos": ("desconto.",),
             "fgts": ("fgts.",), "jornada": ("jornada.", "intervalo.", "horario.")}


def _categoria(f: dict[str, Any]) -> str:
    cat = str(f.get("categoria") or "").strip().lower()
    if cat in CATEGORIAS:
        return cat
    chave = str(f.get("chave") or "").lower()
    for c, prefixos in _PREFIXOS.items():
        if chave.startswith(prefixos):
            return c
    return ""


def decidir(matriz: dict[str, Any], calculos: list[dict[str, Any]] | None = None,
            preferencia_da_skill: dict[str, bool] | None = None) -> dict[str, dict[str, Any]]:
    fatos = matriz.get("fatos") or []
    contagem = {c: 0 for c in CATEGORIAS}
    for f in fatos:
        c = _categoria(f)
        if c:
            contagem[c] += 1
    contagem["cronologia"] = sum(1 for f in fatos if str(f.get("data") or "").strip())
    contagem["provas"] = len({d.strip() for f in fatos for d in str(f.get("documento") or "").split(",") if d.strip()})
    contagem["memoria_de_calculo"] = sum(1 for c in calculos or [] if not c.get("erro") and c.get("valor"))
    saida = {}
    for c in CATEGORIAS:
        pref = (preferencia_da_skill or {}).get(c)
        usa = pref if pref is not None else contagem[c] >= LIMIARES[c]
        motivo = "preferência da skill" if pref is not None else f"{contagem[c]} item(ns); limiar {LIMIARES[c]}"
        saida[c] = {"decisao": "USE_TABLE" if usa else "NO_TABLE", "itens": contagem[c], "motivo": motivo}
    return saida


# ------------------------------------------------------------------ tabelas montadas pelo código

#: Onde a redação quer uma tabela, escreve só o marcador; o conteúdo vem dos dados canônicos.
MARCADOR = re.compile(r"\[\[\s*TABELA\s*:\s*([a-z_]+)\s*\]\]", re.I)


def _celula(x: Any) -> str:
    return " ".join(str(x if x is not None else "").replace("|", "/").split()) or "-"


def _markdown(cabecalho: list[str], linhas: list[list[Any]]) -> str:
    if not linhas:
        return ""
    saida = ["| " + " | ".join(cabecalho) + " |", "| " + " | ".join("---" for _ in cabecalho) + " |"]
    saida += ["| " + " | ".join(_celula(c) for c in linha) + " |" for linha in linhas]
    return "\n".join(saida)


_DOC_NUMERADO = re.compile(r"^\s*Doc(?:umento)?\s*(\d+)\s*[.:\-–]?\s*(.*?)(?:\.(?:pdf|docx?|jpe?g|png|webp|tiff?))?\s*$", re.I)


def rotulo_documento(nome: Any) -> str:
    """«Doc 6. CTPS Digital.pdf» -> «Documento 6 — CTPS Digital»: nome de arquivo não vai para a peça."""
    texto = str(nome or "").strip()
    if not texto or texto == "-":
        return "-"
    if texto.lower() == "calculado pelo sistema":
        return "memória de cálculo desta peça"
    m = _DOC_NUMERADO.match(texto)
    if m:
        return f"Documento {m.group(1)}" + (f" — {m.group(2).strip()}" if m.group(2).strip() else "")
    return re.sub(r"\.(?:pdf|docx?|jpe?g|png|webp|tiff?)$", "", texto, flags=re.I)


def _rotulos(texto: Any) -> str:
    return ", ".join(rotulo_documento(parte) for parte in str(texto or "").split(",") if parte.strip()) or "-"


def _fonte(f: dict[str, Any]) -> str:
    return _rotulos(f.get("documento") or f.get("fonte"))


def base_e_fonte(c: dict[str, Any]) -> str:
    """Cada parâmetro do cálculo com o documento de onde saiu (fonte única) — o elo fato → pedido."""
    fontes = c.get("fontes") or {}
    partes = [f"{f['rotulo']}: {f['exibir']} ({_rotulos(f['fonte'])})" for f in fontes.values() if f.get("exibir")]
    if any(nome not in fontes for nome in c.get("parametros") or {}):
        partes.append("demais parâmetros: análise do caso")
    return "; ".join(partes) or "análise do caso"


def construir(categoria: str, *, matriz: dict[str, Any], canon: dict[str, Any] | None, calculos: list[dict[str, Any]]) -> str:
    """Tabela markdown de uma categoria, só com dado da fonte única (canônico, matriz utilizável, cálculos)."""
    fatos = [f for f in matriz.get("fatos") or [] if canonico.certeza_do_fato(f) in canonico.UTILIZAVEIS]
    if categoria == "contrato":
        campos = [e for e in ((canon or {}).get("campos") or {}).values()
                  if e["certeza"] in canonico.UTILIZAVEIS and e["chave"] != "petition_date" and e.get("valor") not in (None, "")]
        return _markdown(["Dado", "Valor", "Fonte"], [[e["rotulo"], canonico.exibir(e), _rotulos(e.get("documento") or e.get("fonte"))] for e in campos])
    if categoria == "cronologia":
        datados = sorted((f for f in fatos if _data(f.get("data"))), key=lambda f: _data(f.get("data")))
        return _markdown(["Data", "Fato", "Fonte"], [[_data(f["data"]).strftime("%d/%m/%Y"), f["fato"][:200], _fonte(f)] for f in datados])
    if categoria == "provas":
        por_doc: dict[str, list[str]] = {}
        for f in fatos:
            for d in str(f.get("documento") or "").split(","):
                if d.strip():
                    por_doc.setdefault(rotulo_documento(d), []).append(str(f.get("fato") or f["id"])[:90].rstrip(" ."))
        return _markdown(["Documento", "Fatos que comprova"], [[d, "; ".join(dict.fromkeys(textos))] for d, textos in sorted(por_doc.items())])
    if categoria == "memoria_de_calculo":
        validos = [c for c in calculos or [] if not c.get("erro") and c.get("valor") and str(c.get("unidade") or "BRL") == "BRL"]
        return _markdown(["Cálculo", "Rubrica", "Base e fonte", "Memória", "Resultado"],
                         [[c.get("calculation_id"), c["rubrica"].replace("_", " "), base_e_fonte(c), "; ".join(c.get("memoria") or []), brl(c["valor"])]
                          for c in validos])
    if categoria in CATEGORIAS:
        itens = [f for f in fatos if _categoria(f) == categoria]
        return _markdown(["Fato", "Valor", "Fonte"], [[f["fato"][:160], f.get("valor"), _fonte(f)] for f in itens])
    return ""


def aplicar_marcadores(texto: str, *, matriz: dict[str, Any], canon: dict[str, Any] | None,
                       calculos: list[dict[str, Any]]) -> tuple[str, list[str], list[str]]:
    """(texto com as tabelas do código, categorias renderizadas, marcadores sem dado — removidos)."""
    feitas, vazias = [], []

    def trocar(m: re.Match[str]) -> str:
        cat = m[1].lower()
        tabela = construir(cat, matriz=matriz, canon=canon, calculos=calculos)
        (feitas if tabela else vazias).append(cat)
        return tabela

    return MARCADOR.sub(trocar, texto or ""), feitas, vazias
