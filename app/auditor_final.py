"""AUDITOR FINAL — segunda etapa INDEPENDENTE, antes do DOCX, com correção e limite de iterações.

Geração e validação são chamadas separadas: quem redige não "confere de cabeça". O auditor recebe os dados
canônicos (CASE_FACTS), o mapa de teses, o ledger de pedidos, as evidências e o rascunho, e responde ao checklist
completo. As verificações que o código consegue PROVAR (`petition_linter`, `auditoria_estrutural`, regras da skill)
rodam sempre; o modelo cobre só o que exige leitura semântica (sobreposição de teses, mesma lesão indenizada
duas vezes, principal × subsidiário, história jurídica coerente).

Erro corrigível é corrigido e a auditoria roda de novo; passado o limite de iterações o que sobrar NÃO é
"consertado na sorte": vira pendência para revisão humana e a peça sai retida.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from . import auditoria_estrutural as ae
from . import petition_linter, plano_da_peticao as pp
from .conferencia_peticao import Violacao

log = logging.getLogger("auditor_final")

CHECKLIST = (
    "qualificação existe", "qualificação aparece uma única vez", "dados das partes consistentes com o CASE_FACTS",
    "sem placeholders indevidos", "sem seções estruturais duplicadas", "fatos não se contradizem",
    "nenhum fato de peça de referência (acervo) no caso", "teses separadas corretamente",
    "sem repetição argumentativa excessiva entre capítulos", "pedidos sem duplicidade SEMÂNTICA (causa de pedir, consequência, objeto econômico)",
    "principal/subsidiário/alternativo tratados corretamente (subsidiário não somado ao principal)", "cada pedido tem fundamentação",
    "valores correspondem ao critério da fundamentação", "valor da causa fecha com os pedidos cumulativos",
    "afirmações relevantes têm suporte documental ou estão qualificadas (ausência de prova ≠ prova de ausência)",
    "numeração e hierarquia das seções corretas", "abertura, desenvolvimento e pedidos contam a mesma história jurídica",
)

INSTRUCAO = (
    "Você é o AUDITOR de uma petição já redigida por outro modelo. Você NÃO escreve a peça: audita. Receberá: CASE_FACTS "
    "(dados canônicos e incertezas), o mapa de teses, o ledger de pedidos, as evidências e o rascunho completo. Verifique CADA item do "
    "checklist e devolva APENAS JSON: {\"itens\":[{\"criterio\":\"texto do checklist\",\"ok\":true|false,\"severidade\":\"critico|aviso\","
    "\"secao\":\"code da seção ou LEDGER\",\"trecho\":\"trecho curto\",\"problema\":\"o que está errado\",\"correcao\":\"como corrigir sem inventar\"}]} — "
    "liste APENAS os itens com problema. Regras: repetição necessária para conexão argumentativa é aceitável, duplicação substancial não; "
    "pedidos com linguagem parecida mas objeto/período/beneficiário diferentes NÃO são duplicados; uma tese subsidiária não pode aparecer como cumulativa; "
    "'majoração' lançada como segunda indenização da MESMA lesão é sobreposição. Não invente problema: cite trecho real.\nCHECKLIST:\n- " + "\n- ".join(CHECKLIST)
)


def auditar_com_modelo(chamar: Callable[[str, str], dict[str, Any]], case_facts: dict[str, Any], plano: dict[str, Any], secoes: list[dict[str, Any]],
                       candidatos: list[Violacao] | None = None) -> list[Violacao]:
    payload = {
        "CASE_FACTS": {"PARTIES": {p: {c: e.get("valor") for c, e in campos.items()} for p, campos in case_facts.get("PARTIES", {}).items()},
                       "UNCERTAINTIES": case_facts.get("UNCERTAINTIES", [])},
        "mapa_de_teses": [{k: t.get(k) for k in ("id", "titulo", "fatos_ids", "provas", "fundamentos_legais", "jurisprudencias", "consequencia", "funcao_argumentativa", "pedidos_ids")} for t in plano.get("teses", [])],
        "fatos": [{"id": f["id"], "fato": f["fato"], "documentos": f["documentos"]} for f in plano.get("fatos", [])],
        "ledger_de_pedidos": plano.get("pedidos", []),
        # o pré-detector barato (embeddings/n-gramas) aponta ONDE olhar; o modelo só julga o que é relevante
        "candidatos_de_sobreposicao": [{"onde": c.trecho, "motivo": c.motivo} for c in (candidatos or [])],
        "rascunho": [{"secao": s.get("code"), "titulo": s.get("label"), "texto": str(s.get("content") or "")[:14000]} for s in secoes],
    }
    try:
        saida = chamar(INSTRUCAO, json.dumps(payload, ensure_ascii=False))
    except Exception as erro:  # noqa: BLE001 - sem o auditor semântico, as verificações determinísticas continuam valendo
        log.warning("auditor semântico indisponível: %s", str(erro)[:160])
        return []
    return [
        Violacao("AUDITOR_" + pp.norm(str(i.get("criterio", "")))[:40].replace(" ", "_").upper(), str(i.get("secao") or ""), str(i.get("trecho") or "")[:220],
                 f"Auditor: {i.get('problema', '')}", str(i.get("correcao") or ""), str(i.get("severidade")).lower() == "critico")
        for i in saida.get("itens") or [] if isinstance(i, dict) and not i.get("ok", False)
    ]


def revisar_ledger(chamar: Callable[[str, str], dict[str, Any]], plano: dict[str, Any], problemas: list[Violacao]) -> list[dict[str, Any]] | None:
    """Peça ao modelo o ledger CORRIGIDO e só o aceite se a validação determinística não achar mais erro crítico."""
    try:
        saida = chamar(
            "Corrija o LEDGER de pedidos de uma petição apontado pelos problemas. Funda pedidos que indenizam a MESMA lesão (majoração vira critério "
            "do pedido principal, não segundo pedido); classifique `natureza` como cumulativo|subsidiario|alternativo; preencha `metodo_calculo` "
            "{base, multiplicador, resultado} e `valor` coerentes; mantenha os pedidos de praxe e NÃO crie pedido sem fato do caso. "
            "Devolva APENAS JSON: {\"pedidos\":[mesmo esquema do ledger recebido]}.",
            json.dumps({"ledger": plano["pedidos"], "teses": [{"id": t["id"], "titulo": t["titulo"]} for t in plano["teses"]],
                        "problemas": [{"codigo": p.codigo, "motivo": p.motivo} for p in problemas]}, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        return None
    novos = saida.get("pedidos")
    if not isinstance(novos, list) or not novos:
        return None
    base = {"de_praxe": False, "tese_origem": "", "fundamento": "", "valor_ou_base": "", "natureza": "cumulativo"}
    candidato = {**plano, "pedidos": [{**base, **n, "id": f"P{i + 1:02d}"} for i, n in enumerate(novos) if isinstance(n, dict)]}
    return candidato["pedidos"] if not [v for v in ae.ledger(candidato) if v.bloqueia] else None


def executar(
    secoes: list[dict[str, Any]], plano: dict[str, Any], case_facts: dict[str, Any], *, params: dict[str, Any],
    verificacoes: Callable[[list[dict[str, Any]], dict[str, Any]], list[Violacao]],
    chamar: Callable[[str, str], dict[str, Any]],
    reescrever: Callable[[dict[str, Any], str], str | None],
    rerenderizar_pedidos: Callable[[list[dict[str, Any]], dict[str, Any]], list[dict[str, Any]]],
    max_iteracoes: int = 3,
) -> tuple[list[dict[str, Any]], list[Violacao], dict[str, Any]]:
    """Audita → corrige → audita de novo (até `max_iteracoes`). Devolve (seções, achados finais, relatório)."""
    relatorio: dict[str, Any] = {"iteracoes": [], "pendencias_humanas": []}
    achados: list[Violacao] = []
    for it in range(1, max_iteracoes + 1):
        determinicos = verificacoes(secoes, plano)
        candidatos = [a for a in determinicos if a.codigo == "SOBREPOSICAO_SEMANTICA_CANDIDATA"]
        achados = determinicos + auditar_com_modelo(chamar, case_facts, plano, secoes, candidatos)
        criticos = [a for a in achados if a.bloqueia]
        passo: dict[str, Any] = {"n": it, "criticos": [f"{a.codigo}:{a.secao}" for a in criticos], "avisos": len(achados) - len(criticos), "correcoes": []}
        relatorio["iteracoes"].append(passo)
        if not criticos:
            break
        if it == max_iteracoes:
            break
        # 1) abertura duplicada: correção DETERMINÍSTICA
        if any(a.codigo in ("QUALIFICACAO_DUPLICADA", "BLOCO_ESTRUTURAL_DUPLICADO", "TITULO_DA_ACAO_DUPLICADO") for a in criticos):
            secoes, n = ae.remover_aberturas_duplicadas(secoes, plano.get("partes") or {}, params)
            passo["correcoes"].append({"aberturas_duplicadas_removidas": n})
        # 2) ledger: o modelo propõe, o código valida
        do_ledger = [a for a in criticos if a.secao == "LEDGER" or a.codigo in (
            "MAJORACAO_COMO_SEGUNDA_INDENIZACAO", "PEDIDOS_SOBREPOSTOS", "SUBSIDIARIO_SOMADO_AO_PRINCIPAL", "VALOR_INCONSISTENTE_COM_METODO", "PEDIDO_DUPLICADO")]
        if do_ledger:
            novos = revisar_ledger(chamar, plano, do_ledger)
            if novos:
                plano["pedidos"] = novos
                secoes = rerenderizar_pedidos(secoes, plano)
                passo["correcoes"].append({"ledger_revisado": [p["id"] for p in novos]})
        # 3) o resto: reescrita da seção com a lista exata de defeitos
        por_secao: dict[str, list[Violacao]] = {}
        for a in criticos:
            if a in do_ledger or a.codigo in ("QUALIFICACAO_DUPLICADA", "BLOCO_ESTRUTURAL_DUPLICADO", "TITULO_DA_ACAO_DUPLICADO", "PEDIDO_FORA_DO_PLANO"):
                continue
            por_secao.setdefault(a.secao or "", []).append(a)
        novas = []
        for s in secoes:
            do_s = por_secao.get(str(s.get("code")))
            if not do_s:
                novas.append(s)
                continue
            texto = reescrever(s, "CORRIJA EXATAMENTE ESTES PONTOS (sem inventar dado; ausência de prova não é prova de ausência):\n" + "\n".join(
                f"- [{a.codigo}] {a.motivo} Trecho: {a.trecho}. Correção: {a.correcao}" for a in do_s))
            if texto:
                novas.append({**s, "content": texto})
                passo["correcoes"].append({"secao": s.get("code"), "codigos": sorted({a.codigo for a in do_s})})
            else:
                novas.append(s)
        secoes = novas
    finais = [a for a in achados if a.bloqueia]
    relatorio["pendencias_humanas"] = [f"{a.codigo}:{a.secao} — {a.motivo}"[:260] for a in finais]
    relatorio["liberada"] = not finais
    return secoes, achados, relatorio
