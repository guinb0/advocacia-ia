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
from . import canonico
from . import teses as ts
from .autoridades import norm


def _tokens(t: str) -> set[str]:
    return {x for x in re.findall(r"[a-z]{4,}", norm(t))}


def _similar(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def _pedido(pid: str, *, tipo: str, objeto: str, tese_origem: str, valor: float | None, criterio: str, calculation_id: str = "") -> dict[str, Any]:
    return {
        "id": pid, "tipo": tipo, "objeto": objeto, "fundamento": "", "valor_ou_base": f"{calc.brl(valor)} — {criterio}" if valor else "",
        "de_praxe": False, "tese_origem": tese_origem, "causa_de_pedir": objeto, "natureza": "cumulativo", "subsidiario_de": "",
        "dependencias": [], "valor": valor, "calculation_id": calculation_id if valor else "",
        "metodo_calculo": {"base": valor, "multiplicador": 1, "resultado": valor, "criterio": criterio, "deterministico": True} if valor else {},
        "tipo_de_item": "autonomo", "agrava": "", "agrava_id": "", "bem_juridico": "", "evento_causador": "", "dano": "", "objeto_economico": "",
        "origem": "issue_spotting",
        "issue_id": tese_origem, "semantic_key": norm(tipo or objeto).upper().replace(" ", "_"), "no_request_reason": None,
    }


#: Pedido de PAGAMENTO (exige valor líquido); pedido declaratório/de fazer/processual não.
_MONETARIO = re.compile(r"pagamento|pagar|indeniza|multa|diferen[cç]a|adicional|horas?\s+extra|verbas|fgts|f[eé]rias|13[ºo°]|d[eé]cimo\s+terceiro|"
                        r"sal[aá]rio|aviso\s+pr[eé]vio|pens[aã]o|pensionamento|reembolso|ressarc|danos?\s+(?:morais|materiais|est[eé]ticos)", re.I)
_PRAXE = re.compile(r"\b(cita[cç][aã]o|intima[cç][aã]o|comunica[cç][aã]o|notifica[cç][aã]o|"
                    r"produ[cç][aã]o de prova|prova pericial|justi[cç]a gratuita|gratuidade|honor[aá]rios|"
                    r"processamento|proced[êe]ncia|juntada|sigilo)\b", re.I)


def monetario(pedido: dict[str, Any]) -> bool:
    if pedido.get("de_praxe") or str(pedido.get("tipo_de_item") or "autonomo") != "autonomo":
        return False
    return bool(pedido.get("valor") not in (None, "") or pedido.get("objeto_economico")
                or _MONETARIO.search(f"{pedido.get('tipo') or ''} {pedido.get('objeto') or ''}"))


def estruturar_pedidos(plano: dict[str, Any], issues: dict[str, Any], autoridades_por_tese: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Cada pedido no contrato estruturado {request_id, title, factual_support, authority_ids, calculation_id, value,
    reflexes, expert_evidence_required, status}. Os campos internos antigos continuam (o legado os lê)."""
    incluidas = [t for t in issues.get("teses") or [] if t.get("decisao") == ts.INCLUIR]
    por_tese_do_plano = {t.get("tese_plano_id"): t for t in incluidas if t.get("tese_plano_id")}
    teses_do_plano = {str(t.get("id") or ""): t for t in plano.get("teses") or []}
    for p in plano.get("pedidos") or []:
        t = por_tese_do_plano.get(p.get("tese_origem")) or {}
        # Pedidos herdados do outline podem ter perdido o vínculo textual com a
        # tese. Faça o casamento uma vez, ANTES de finalizar o plano, e nunca no
        # renderer ou auditor.
        if not t:
            base = teses_do_plano.get(str(p.get("tese_origem") or "")) or {}
            alvo = f"{base.get('titulo') or ''} {p.get('tipo') or ''} {p.get('objeto') or ''}"
            candidato = max(incluidas, key=lambda i: _similar(alvo, str(i.get("tese") or "")), default={})
            if candidato and _similar(alvo, str(candidato.get("tese") or "")) >= 0.15:
                t = candidato
                p["tese_origem"] = str(candidato.get("tese_plano_id") or p.get("tese_origem") or "")
        valor = p.get("valor") if p.get("valor") not in (None, "") else None
        de_praxe = bool(p.get("de_praxe")) or bool(_PRAXE.search(f"{p.get('tipo') or ''} {p.get('objeto') or ''}"))
        p.update({
            "request_id": p.get("id"),
            "title": str(p.get("tipo") or p.get("objeto") or "")[:120],
            "factual_support": list(t.get("fatos_que_suportam") or []),
            "authority_ids": [a.id for a in autoridades_por_tese.get(t.get("id"), [])] if t else [],
            "calculation_id": p.get("calculation_id") or "",
            "value": valor,
            "reflexes": list(t.get("reflexos") or []),
            "expert_evidence_required": bool(t.get("exige_pericia")),
            "unidade": "BRL",
            "status": "PENDING_CALCULATION" if monetario(p) and valor is None else "SUPPORTED",
            "de_praxe": de_praxe,
            "issue_id": str(t.get("id") or "") if t else "",
            "semantic_key": norm(str(p.get("tipo") or p.get("title") or p.get("objeto") or "")).upper().replace(" ", "_"),
            "no_request_reason": None,
        })
    return plano.get("pedidos") or []


def retirar_pedidos_sem_vinculo(plano: dict[str, Any]) -> list[str]:
    """Remove, antes da finalização, item legado que não conseguiu vínculo probatório/jurídico.

    A remoção é deliberada e rastreável no planejador. Diferentemente do fluxo
    antigo, renderer e auditor nunca omitem esse pedido depois que o plano já
    está congelado.
    """
    pendencias: list[str] = []
    mantidos: list[dict[str, Any]] = []
    removidos: set[str] = set()
    for p in plano.get("pedidos") or []:
        pid = str(p.get("id") or p.get("request_id") or "?")
        motivos: list[str] = []
        if not p.get("de_praxe") and not p.get("factual_support"):
            motivos.append("sem fato documental vinculado")
        if not p.get("de_praxe") and not p.get("authority_ids"):
            motivos.append("sem autoridade jurídica vinculada")
        if monetario(p) and not p.get("calculation_id"):
            motivos.append("sem cálculo canônico")
        # Ausência de vínculo é diagnosticada no plano e volta como finding dos
        # gates; não se apaga uma tese declaratória em silêncio. Já valor sem
        # cálculo é estruturalmente impossível e, por isso, fica fora ANTES do
        # congelamento.
        if "sem cálculo canônico" in motivos:
            removidos.add(pid)
            pendencias.append(f"Pedido não incluído no PETITION_PLAN: {pid} — {', '.join(motivos)}")
            continue
        if motivos:
            pendencias.append(f"Pedido pendente de vínculo no PETITION_PLAN: {pid} — {', '.join(motivos)}")
        mantidos.append(p)
    if removidos:
        plano["pedidos"] = mantidos
        for tese in plano.get("teses") or []:
            if isinstance(tese.get("pedidos_ids"), list):
                tese["pedidos_ids"] = [pid for pid in tese["pedidos_ids"] if pid not in removidos]
        plano["valor_da_causa_calculado"] = calc.valor_da_causa(mantidos)
    return pendencias


def integrar(plano_est: dict[str, Any], issues: dict[str, Any], calculos: list[dict[str, Any]], matriz: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Plano estruturado + issue spotting + cálculos → (novo plano, pendências nomeadas)."""
    plano = copy.deepcopy(plano_est)
    plano.setdefault("teses", [])
    # No strict o outline legado ainda fornece contexto/fatos, mas nunca pedidos.
    # Requests nascem exclusivamente deste planejador, a partir de issues + cálculos.
    plano["pedidos"] = [] if plano.get("_somente_motor_juridico") else plano.setdefault("pedidos", [])
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
            t["no_request_reason"] = "PENDING_CALCULATION"
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
        cid = str((c or {}).get("calculation_id") or "")
        if do_plano:
            alvo = do_plano[0]
            if valor and alvo.get("valor") in (None, ""):
                alvo.update(valor=valor, valor_ou_base=f"{calc.brl(valor)} — {criterio}", calculation_id=cid,
                            metodo_calculo={"base": valor, "multiplicador": 1, "resultado": valor, "criterio": criterio, "deterministico": True})
            elif valor and abs(float(calc.valor_numerico(alvo["valor"]) or 0) - valor) > 0.01:
                pendencias.append(f"Valor divergente em {alvo['id']} ({alvo['tipo']}): planejador {calc.brl(calc.valor_numerico(alvo['valor']) or 0)} × cálculo {calc.brl(valor)} — adotado o cálculo")
                alvo.update(valor=valor, valor_ou_base=f"{calc.brl(valor)} — {criterio}", calculation_id=cid,
                            metodo_calculo={"base": valor, "multiplicador": 1, "resultado": valor, "criterio": criterio, "deterministico": True})
            elif valor:
                alvo["calculation_id"] = cid
            continue
        if t["pedido"]:
            pid = f"P{len(plano['pedidos']) + 1:02d}"
            plano["pedidos"].append(_pedido(pid, tipo=t["tese"][:60], objeto=t["pedido"], tese_origem=tid, valor=valor, criterio=criterio, calculation_id=cid))
            for x in plano["teses"]:
                if x["id"] == tid:
                    x.setdefault("pedidos_ids", []).append(pid)
        elif t["decisao"] == ts.INCLUIR:
            t["no_request_reason"] = "ISSUE_SEM_PRETENSAO_AUTONOMA"
    for c in matriz.get("contradicoes") or []:
        versoes = " × ".join(f"«{v.get('valor', v.get('detalhe', ''))}»" for v in c["versoes"])
        pendencias.append(f"Contradição em {c['chave']}: {versoes} — confirmar a versão correta")
    plano["valor_da_causa_calculado"] = calc.valor_da_causa(plano["pedidos"])
    return plano, pendencias


def retirar_pedidos_sem_pressuposto(plano: dict[str, Any], issues: dict[str, Any], canon: dict[str, Any] | None) -> list[str]:
    """Pedido rescisório (aviso prévio, multas 467/477, 40% do FGTS…) sem término do contrato nem rescisão indireta
    sai do plano — inclusive o que veio do planejador — e vira pendência nomeada."""
    incluidas = [t for t in issues.get("teses") or [] if t["decisao"] == ts.INCLUIR]
    do_plano = [{"tese": p.get("tipo") or "", "pedido": p.get("objeto") or ""} for p in plano.get("pedidos") or []]
    indireta = canonico.pede_rescisao_indireta([*incluidas, *do_plano])
    pendencias: list[str] = []
    mantidos = []
    for p, resumo in zip(plano.get("pedidos") or [], do_plano):
        motivo = canonico.pressuposto_rescisorio({**resumo, "calculo": {}}, canon, rescisao_indireta=indireta)
        if motivo:
            pendencias.append(f"Pedido retirado: {p.get('tipo') or p.get('objeto') or p.get('id')} — {motivo}")
            for t in plano.get("teses") or []:
                if p.get("id") in (t.get("pedidos_ids") or []):
                    t["pedidos_ids"] = [i for i in t["pedidos_ids"] if i != p.get("id")]
            continue
        mantidos.append(p)
    if len(mantidos) != len(plano.get("pedidos") or []):
        plano["pedidos"] = mantidos
        plano["valor_da_causa_calculado"] = calc.valor_da_causa(mantidos)
    return pendencias


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
            linhas.append(f"- {p['id']} {p['tipo']}: {calc.brl(calc.valor_numerico(p['valor']) or 0)}"
                          + (f" ({p['calculation_id']})" if p.get("calculation_id") else ""))
    vc = plano.get("valor_da_causa_calculado") or {}
    if vc.get("valor"):
        linhas.append(f"VALOR DA CAUSA: {calc.brl(vc['valor'])} (soma de {', '.join(vc['pedidos_somados'])}) — um único valor em toda a peça.")
    memorias = [c for c in calculos if not c.get("erro") and c.get("valor")]
    if memorias:
        linhas.append("\nMEMÓRIA DE CÁLCULO:")
        linhas += [f"- {c['rubrica']}: " + " | ".join(c["memoria"]) for c in memorias]
    usar = [c for c, d in tabelas.items() if d["decisao"] == "USE_TABLE"]
    if usar:
        linhas.append("\nTABELAS (montadas pelo sistema com os dados canônicos): onde cada uma couber, escreva SOMENTE o marcador "
                      + ", ".join(f"[[TABELA:{c}]]" for c in usar) + " — nunca digite a tabela.")
    nao = [t for t in issues.get("teses") or [] if t["decisao"] != ts.INCLUIR or t.get("pendente_de_calculo")]
    if nao:
        linhas.append("\nNÃO ESCREVA NO CORPO (vão ao relatório do advogado): " + "; ".join(t["tese"] for t in nao))
    if alertas_juridicos:
        linhas.append("\nALERTAS DA BASE JURÍDICA (prevalecem sobre a skill e sobre peças antigas):")
        linhas += [f"- {a}" for a in alertas_juridicos]
    return "\n".join(linhas)
