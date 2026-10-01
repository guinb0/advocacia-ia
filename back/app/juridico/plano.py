"""PETITION_PLAN jurídico: o que a redação recebe pronto, para não escolher tese enquanto escreve.

Integra ao plano estruturado existente (`plano_da_peticao`) as teses do issue spotting e os valores dos
cálculos determinísticos; o que não pode entrar no corpo (tese a confirmar, cálculo sem parâmetro,
contradição) vira pendência NOMEADA para o advogado — nada some em silêncio.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from . import autoridades as aut
from . import calculos as calc
from . import teses as ts
from .autoridades import norm


def _tokens(t: str) -> set[str]:
    return {x for x in re.findall(r"[a-z]{4,}", norm(t))}


def _similar(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def _pedido(pid: str, *, tipo: str, objeto: str, tese_origem: str, valor: float | None, criterio: str) -> dict[str, Any]:
    return {
        "id": pid, "tipo": tipo, "objeto": objeto, "fundamento": "", "valor_ou_base": f"{calc.brl(valor)} — {criterio}" if valor else "",
        "de_praxe": False, "tese_origem": tese_origem, "causa_de_pedir": objeto, "natureza": "cumulativo", "subsidiario_de": "",
        "dependencias": [], "valor": valor,
        "metodo_calculo": {"base": valor, "multiplicador": 1, "resultado": valor, "criterio": criterio, "deterministico": True} if valor else {},
        "tipo_de_item": "autonomo", "agrava": "", "agrava_id": "", "bem_juridico": "", "evento_causador": "", "dano": "", "objeto_economico": "",
        "origem": "issue_spotting",
    }


def integrar(plano_est: dict[str, Any], issues: dict[str, Any], calculos: list[dict[str, Any]], matriz: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Plano estruturado + issue spotting + cálculos → (novo plano, pendências nomeadas)."""
    plano = copy.deepcopy(plano_est)
    plano.setdefault("teses", [])
    plano.setdefault("pedidos", [])
    ref_para_f = {f["id"]: f.get("ref") for f in matriz.get("fatos") or [] if f.get("origem") == "plano" and f.get("ref")}
    por_tese = {c.get("tese_id"): c for c in calculos}
    pendencias: list[str] = []
    for t in issues.get("teses") or []:
        existente = max(plano["teses"], key=lambda x: _similar(x["titulo"], t["tese"]), default=None)
        if existente is not None and _similar(existente["titulo"], t["tese"]) >= 0.5:
            t["tese_plano_id"] = existente["id"]
        if t["decisao"] == ts.POTENCIAL:
            pendencias.append(f"A confirmar: {t['tese']} — {t['rebaixada_por'] or t['motivo']}"
                              + (f" (faltam: {'; '.join(t['fatos_faltantes'])})" if t["fatos_faltantes"] else ""))
            continue
        if t["decisao"] != ts.INCLUIR:
            continue
        c = por_tese.get(t["id"])
        monetario = bool(t["calculo"].get("rubrica"))
        if monetario and (c is None or c.get("erro") or not c.get("valor")):
            t["pendente_de_calculo"] = True
            faltam = t["calculo"].get("parametros_faltantes") or [(c or {}).get("erro") or "parâmetros do cálculo"]
            pendencias.append(f"Calcular antes do protocolo: {t['tese']} — faltam {', '.join(faltam)}")
            continue
        if not t.get("tese_plano_id"):
            tid = f"T{len(plano['teses']) + 1:02d}"
            plano["teses"].append({
                "id": tid, "id_do_modelo": t["id"], "titulo": t["tese"], "fatos_ids": sorted({ref_para_f[i] for i in t["fatos_que_suportam"] if i in ref_para_f}),
                "provas": t["prova"], "fundamentos_legais": [], "jurisprudencias": [], "consequencia": t["pedido"],
                "funcao_argumentativa": "", "relacao": "principal", "gera_pedido": bool(t["pedido"]), "pedidos_ids": [], "origem": "issue_spotting",
            })
            t["tese_plano_id"] = tid
        tid = t["tese_plano_id"]
        do_plano = [p for p in plano["pedidos"] if p.get("tese_origem") == tid]
        valor = float(c["valor"]) if c and c.get("valor") else None
        criterio = "; ".join(c.get("memoria") or []) if c else ""
        if do_plano:
            alvo = do_plano[0]
            if valor and alvo.get("valor") in (None, ""):
                alvo.update(valor=valor, valor_ou_base=f"{calc.brl(valor)} — {criterio}",
                            metodo_calculo={"base": valor, "multiplicador": 1, "resultado": valor, "criterio": criterio, "deterministico": True})
            elif valor and abs(float(alvo["valor"]) - valor) > 0.01:
                pendencias.append(f"Valor divergente em {alvo['id']} ({alvo['tipo']}): planejador {calc.brl(alvo['valor'])} × cálculo {calc.brl(valor)} — adotado o cálculo")
                alvo.update(valor=valor, valor_ou_base=f"{calc.brl(valor)} — {criterio}",
                            metodo_calculo={"base": valor, "multiplicador": 1, "resultado": valor, "criterio": criterio, "deterministico": True})
            continue
        if t["pedido"]:
            pid = f"P{len(plano['pedidos']) + 1:02d}"
            plano["pedidos"].append(_pedido(pid, tipo=t["tese"][:60], objeto=t["pedido"], tese_origem=tid, valor=valor, criterio=criterio))
            for x in plano["teses"]:
                if x["id"] == tid:
                    x.setdefault("pedidos_ids", []).append(pid)
    for c in matriz.get("contradicoes") or []:
        versoes = " × ".join(f"«{v.get('valor', v.get('detalhe', ''))}»" for v in c["versoes"])
        pendencias.append(f"Contradição em {c['chave']}: {versoes} — confirmar a versão correta")
    plano["valor_da_causa_calculado"] = calc.valor_da_causa(plano["pedidos"])
    return plano, pendencias


def para_prompt(*, issues: dict[str, Any], plano: dict[str, Any], autoridades_por_tese: dict[str, list[aut.Autoridade]],
                tabelas: dict[str, Any], calculos: list[dict[str, Any]], alertas_juridicos: list[str]) -> str:
    """O PETITION_PLAN que abre a entrada da redação (vem ANTES do material do caso, nunca é cortado)."""
    linhas = ["=== PETITION_PLAN (decidido antes da redação — siga; NÃO acrescente nem retire teses) ==="]
    for t in issues.get("teses") or []:
        if t["decisao"] != ts.INCLUIR or t.get("pendente_de_calculo"):
            continue
        ids = [a.id for a in autoridades_por_tese.get(t["id"], [])]
        linhas.append(f"TESE {t.get('tese_plano_id') or t['id']} — {t['tese']} | fatos: {', '.join(t['fatos_que_suportam']) or '-'} | prova: {'; '.join(t['prova']) or '-'}"
                      + (" | REQUERER PERÍCIA" if t["exige_pericia"] else "")
                      + f" | autoridades: {', '.join(ids) if ids else 'NENHUMA — escreva [REQUIRES_LEGAL_RESEARCH: ' + ('; '.join(t['base_legal_a_pesquisar'][:2]) or t['tese']) + ']'}")
        if t["reflexos"]:
            linhas.append(f"   reflexos: {', '.join(t['reflexos'])}")
    linhas.append("\nPEDIDOS COM VALOR (cálculo determinístico — use exatamente estes valores):")
    for p in plano.get("pedidos") or []:
        if p.get("valor"):
            linhas.append(f"- {p['id']} {p['tipo']}: {calc.brl(p['valor'])}")
    vc = plano.get("valor_da_causa_calculado") or {}
    if vc.get("valor"):
        linhas.append(f"VALOR DA CAUSA: {calc.brl(vc['valor'])} (soma de {', '.join(vc['pedidos_somados'])}) — um único valor em toda a peça.")
    memorias = [c for c in calculos if not c.get("erro") and c.get("valor")]
    if memorias:
        linhas.append("\nMEMÓRIA DE CÁLCULO:")
        linhas += [f"- {c['rubrica']}: " + " | ".join(c["memoria"]) for c in memorias]
    usar = [c for c, d in tabelas.items() if d["decisao"] == "USE_TABLE"]
    if usar:
        linhas.append("\nAPRESENTE EM TABELA (markdown): " + ", ".join(c.replace("_", " ") for c in usar))
    nao = [t for t in issues.get("teses") or [] if t["decisao"] != ts.INCLUIR or t.get("pendente_de_calculo")]
    if nao:
        linhas.append("\nNÃO ESCREVA NO CORPO (vão ao relatório do advogado): " + "; ".join(t["tese"] for t in nao))
    if alertas_juridicos:
        linhas.append("\nALERTAS DA BASE JURÍDICA (prevalecem sobre a skill e sobre peças antigas):")
        linhas += [f"- {a}" for a in alertas_juridicos]
    return "\n".join(linhas)
