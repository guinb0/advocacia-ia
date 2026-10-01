"""USE_TABLE: em quais categorias a peça apresenta os dados em tabela.

Decisão de APRESENTAÇÃO, por volume de dados estruturados na matriz e nos cálculos — não de conteúdo
jurídico. A preferência da skill (`preferir_tabelas`) sobrepõe o limiar.
"""

from __future__ import annotations

from typing import Any

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
