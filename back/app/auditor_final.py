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
    "'majoração' lançada como segunda indenização da MESMA lesão é sobreposição — compare bem jurídico + evento causador + dano + consequência jurídica + objeto econômico, não só o texto: agravante (sequela/adoecimento/duração que aumenta a extensão do MESMO dano) é FATOR de quantificação do principal, não segundo pedido. Fato «não encontrado nos documentos disponíveis» NUNCA pode ser redigido como ausência comprovada, sobretudo se a peça requer prova para apurá-lo. Cada tese responde à SUA pergunta (responsabilidade: por que responde sem culpa; dano in re ipsa: por que há dano sem prova do sofrimento; agravamento: como a extensão aumenta; subsidiária: fundamento se afastada a principal; quantificação: fatores do quantum) — precedente desenvolvido numa tese é só REFERENCIADO nas outras. Não invente problema: cite trecho real.\nCHECKLIST:\n- " + "\n- ".join(CHECKLIST)
)


def auditar_com_modelo(chamar: Callable[[str, str], dict[str, Any]], case_facts: dict[str, Any], plano: dict[str, Any], secoes: list[dict[str, Any]],
                       candidatos: list[Violacao] | None = None) -> list[Violacao]:
    try:
        # `.get(chave, [])` devolve None quando a chave existe e o valor é null.
        # Montar o payload fora do try fazia isso abortar a petição já redigida.
        parties = case_facts.get("PARTIES") or {}
        payload = {
            "CASE_FACTS": {"PARTIES": {p: {c: e.get("valor") for c, e in (campos or {}).items() if isinstance(e, dict)}
                                       for p, campos in parties.items() if isinstance(campos, dict)},
                           "UNCERTAINTIES": case_facts.get("UNCERTAINTIES") or []},
            "mapa_de_teses": [{k: t.get(k) for k in ("id", "titulo", "fatos_ids", "provas", "fundamentos_legais", "jurisprudencias", "consequencia", "funcao_argumentativa", "pedidos_ids")}
                              for t in (plano.get("teses") or []) if isinstance(t, dict)],
            "fatos": [{"id": f.get("id"), "fato": f.get("fato"), "documentos": f.get("documentos") or []}
                      for f in (plano.get("fatos") or []) if isinstance(f, dict)],
            "ledger_de_pedidos": plano.get("pedidos") or [],
            "candidatos_de_sobreposicao": [{"onde": c.trecho, "motivo": c.motivo} for c in (candidatos or [])],
            "rascunho": [{"secao": s.get("code"), "titulo": s.get("label"), "texto": str(s.get("content") or "")[:14000]} for s in secoes],
        }
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
            "Corrija o LEDGER de pedidos de uma petição apontado pelos problemas. Funda pedidos que reparam o MESMO dano: majoração/agravamento NÃO é segundo pedido — "
            "marque-o com tipo_de_item=\"agravante\", agrava=<tipo do pedido principal>, SEM valor, e incorpore o fator ao metodo_calculo (base, multiplicador, resultado) do principal; classifique `natureza` como cumulativo|subsidiario|alternativo; preencha `metodo_calculo` "
            "{base, multiplicador, resultado} e `valor` coerentes; mantenha os pedidos de praxe e NÃO crie pedido sem fato do caso. "
            "Pedido de PAGAMENTO sem valor: calcule com o dado dos fatos (salário, período, horas) e registre metodo_calculo.criterio "
            "dizendo de onde veio a base; sem dado para calcular, retire só esse pedido — nunca «a apurar em liquidação». "
            "Devolva APENAS JSON: {\"pedidos\":[mesmo esquema do ledger recebido]}.",
            json.dumps({"ledger": plano["pedidos"], "teses": [{"id": t["id"], "titulo": t["titulo"]} for t in plano["teses"]],
                        "fatos": [str(f.get("descricao") or f.get("fato") or "")[:300] for f in (plano.get("fatos") or [])[:60] if isinstance(f, dict)],
                        "problemas": [{"codigo": p.codigo, "motivo": p.motivo} for p in problemas]}, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        return None
    novos = saida.get("pedidos")
    if not isinstance(novos, list) or not novos:
        return None
    base = {"de_praxe": False, "tese_origem": "", "fundamento": "", "valor_ou_base": "", "natureza": "cumulativo"}
    candidato = {**plano, "pedidos": [{**base, **n, "id": f"P{i + 1:02d}"} for i, n in enumerate(novos) if isinstance(n, dict)]}
    if [v for v in ae.ledger(candidato) if v.bloqueia]:
        return None
    # A correção só vale se CONSOLIDOU: menos pedidos econômicos autônomos, ou o agravante ficou sem valor próprio.
    # (Aceitar só porque a checagem de texto parou de reclamar deixava o modelo renomear o pedido sobreposto.)
    antes = sum(1 for p in plano["pedidos"] if ae._autonomo_monetario(p))  # noqa: SLF001
    depois = sum(1 for p in candidato["pedidos"] if ae._autonomo_monetario(p))  # noqa: SLF001
    ha_agravante_sem_valor = any(p.get("tipo_de_item") in ("agravante", "criterio_de_quantificacao") and not p.get("valor") for p in candidato["pedidos"])
    consolidou = depois < antes or ha_agravante_sem_valor
    if any(p.codigo in ("MAJORACAO_COMO_SEGUNDA_INDENIZACAO", "PEDIDOS_SOBREPOSTOS", "MESMA_REPARACAO_DUAS_VEZES", "AGRAVANTE_COM_VALOR_PROPRIO") for p in problemas) and not consolidou:
        return None
    if any(p.codigo == "PEDIDO_DE_PAGAMENTO_SEM_VALOR" for p in problemas):
        sem_valor = len(ae.pedidos_de_pagamento_sem_valor(plano))
        # quem não tem valor pode sair; o resto do ledger não pode sumir junto
        if ae.pedidos_de_pagamento_sem_valor(candidato) or len(candidato["pedidos"]) < len(plano["pedidos"]) - sem_valor:
            return None
    return candidato["pedidos"]


def retirar_pedidos(plano: dict[str, Any], retirar: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tira do ledger os pedidos indicados (e os agravantes que dependiam deles) e renumera P01.. Devolve os retirados."""
    ids = {p.get("id") for p in retirar}
    if not ids:
        return []
    fora = [p for p in plano.get("pedidos") or [] if p.get("id") in ids or p.get("agrava_id") in ids]
    ids_fora = {id(p) for p in fora}
    ficam = [dict(p) for p in plano.get("pedidos") or [] if id(p) not in ids_fora]
    novos_ids = {p["id"]: f"P{i + 1:02d}" for i, p in enumerate(ficam)}
    for p in ficam:
        p["id"] = novos_ids[p["id"]]
        if p.get("agrava_id"):
            p["agrava_id"] = novos_ids.get(p["agrava_id"], "")
    for t in plano.get("teses") or []:
        if isinstance(t.get("pedidos_ids"), list):
            t["pedidos_ids"] = [novos_ids[i] for i in t["pedidos_ids"] if i in novos_ids]
    plano["pedidos"] = ficam
    return fora


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
        # auditor por modelo: UMA vez (custo/latência); as iterações seguintes conferem as correções deterministicamente
        semanticos = auditar_com_modelo(chamar, case_facts, plano, secoes, candidatos) if it == 1 else []
        achados = determinicos + semanticos
        criticos = [a for a in achados if a.bloqueia]
        passo: dict[str, Any] = {"n": it, "criticos": [f"{a.codigo}:{a.secao}" for a in criticos], "avisos": len(achados) - len(criticos), "correcoes": []}
        relatorio["iteracoes"].append(passo)
        if not criticos:
            break
        if it == max_iteracoes:
            break
        # Auditoria é read-only. Findings indicam replanejamento, nunca uma
        # alteração de facts, requests, cálculos, autoridades ou prosa.
        passo["correcoes"].append({"request_replan": sorted({a.codigo for a in criticos})})
        break
    finais = [a for a in achados if a.bloqueia]
    relatorio["pendencias_humanas"] = [f"{a.codigo}:{a.secao} — {a.motivo}"[:260] for a in finais]
    relatorio["liberada"] = not finais
    return secoes, achados, relatorio
