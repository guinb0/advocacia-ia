"""Orquestra as etapas da camada jurídica e registra o rastro de cada uma (observabilidade).

preparar(): matriz de fatos → catálogo da skill → issue spotting → fatos chaveados → cálculos →
            base jurídica (busca por tese + atualidade + auditoria da própria skill) → tabelas → PETITION_PLAN
auditar():  os quatro auditores sobre a peça final + veredito

Todas as dependências externas (modelo, banco, recuperação) entram como parâmetro: o módulo é testável
sem rede, e uma falha de etapa vira registro no rastro, não exceção solta.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import date
from typing import Any, Callable, Iterable, Iterator

from . import auditores, autoridades as aut, calculos, fatos, plano, tabelas, teses
from .busca import Filtros, ProvedorDeAutoridades


class Rastro:
    def __init__(self) -> None:
        self.etapas: list[dict[str, Any]] = []
        self._inicio = time.monotonic()

    @contextmanager
    def etapa(self, nome: str, *, modelo: str = "") -> Iterator[dict[str, Any]]:
        reg: dict[str, Any] = {"etapa": nome, "modelo": modelo, "inicio_s": round(time.monotonic() - self._inicio, 2), "ok": True}
        t0 = time.monotonic()
        try:
            yield reg
        except Exception as erro:
            reg["ok"] = False
            reg["erro"] = f"{type(erro).__name__}: {str(erro)[:240]}"
            raise
        finally:
            reg["duracao_ms"] = round((time.monotonic() - t0) * 1000)
            self.etapas.append(reg)


def _rastreado(llm: Callable[[str, str], dict[str, Any]], reg: dict[str, Any]) -> Callable[[str, str], dict[str, Any]]:
    def chamar(instrucao: str, entrada: str) -> dict[str, Any]:
        saida = llm(instrucao, entrada)
        reg["chamadas"] = reg.get("chamadas", 0) + 1
        reg["tokens_entrada_aprox"] = reg.get("tokens_entrada_aprox", 0) + (len(instrucao) + len(entrada)) // 4
        reg["tokens_saida_aprox"] = reg.get("tokens_saida_aprox", 0) + len(json.dumps(saida, ensure_ascii=False)) // 4
        return saida
    return chamar


def montar_entrada(prioritario: str, contexto_caso: str, *, limite: int = 118_000) -> tuple[str, dict[str, int]]:
    """Plano e base jurídica PRIMEIRO; o que não couber sai do fim do material do caso, nunca do plano."""
    cabecalho = "\n\n=== MATERIAL DO CASO (fatos: só valem os da MATRIZ DE FATOS acima) ===\n"
    espaco = max(0, limite - len(prioritario) - len(cabecalho))
    return prioritario + cabecalho + contexto_caso[:espaco], {
        "prioritario": len(prioritario), "caso_enviado": min(len(contexto_caso), espaco), "caso_cortado": max(0, len(contexto_caso) - espaco)}


def _auditar_skill(textos_skill: dict[str, str], registro: aut.Registro, referencia: date) -> list[str]:
    alertas = []
    for caminho, texto in sorted(textos_skill.items()):
        for r in aut.gate(texto, registro, referencia):
            if r["status"] in (aut.SUPERADA, aut.FORA_DE_VIGENCIA):
                alertas.append(f"A skill ({caminho}) cita «{r['trecho']}», {r['motivo']}. NÃO reproduza esse fundamento.")
        for c in aut.criterios_superados(texto, registro, referencia):
            alertas.append(f"A skill ({caminho}) usa o critério «{c['marcador']}»: {c['motivo']}" + (f"; vigente: {c['superado_por']}" if c["superado_por"] else "") + ". NÃO reproduza.")
    return alertas


def preparar(
    *, plano_est: dict[str, Any], contexto_caso: str, fontes: list[dict[str, Any]], llm: Callable[[str, str], dict[str, Any]],
    textos_skill: dict[str, str], autoridades_base: Iterable[aut.Autoridade] = (), alertas_base: Iterable[str] = (),
    trechos_legislacao: Iterable[Any] = (), trechos_precedentes: Iterable[Any] = (), data_referencia: date | None = None,
    trt_competente: str = "", modelo: str = "", preferencia_tabelas: dict[str, bool] | None = None,
) -> dict[str, Any]:
    prep = analisar(plano_est=plano_est, contexto_caso=contexto_caso, fontes=fontes, llm=llm, textos_skill=textos_skill,
                    data_referencia=data_referencia, modelo=modelo)
    return fundamentar(prep, autoridades_base=autoridades_base, alertas_base=alertas_base, trechos_legislacao=trechos_legislacao,
                       trechos_precedentes=trechos_precedentes, trt_competente=trt_competente, preferencia_tabelas=preferencia_tabelas)


def consultas_das_teses(prep: dict[str, Any]) -> list[dict[str, Any]]:
    """Teses do issue spotting no formato do outline (`recuperacao_por_tese.consultas_do_plano`)."""
    return [{"tese": t["tese"], "fatos_que_sustentam": [*t["base_legal_a_pesquisar"][:1], *t["jurisprudencia_a_pesquisar"][:1]]}
            for t in prep["issues"]["teses"] if not teses.rejeitada(t)]


def analisar(
    *, plano_est: dict[str, Any], contexto_caso: str, fontes: list[dict[str, Any]], llm: Callable[[str, str], dict[str, Any]],
    textos_skill: dict[str, str], data_referencia: date | None = None, modelo: str = "",
) -> dict[str, Any]:
    """Fase 1 (antes da recuperação): fatos, catálogo, issue spotting e cálculos."""
    referencia = data_referencia or date.today()
    rastro = Rastro()
    with rastro.etapa("matriz_de_fatos") as r:
        matriz = fatos.montar(plano_est, case_facts=plano_est.get("case_facts"), fontes=fontes)
        r["resumo"] = matriz["resumo"]
    with rastro.etapa("catalogo_da_skill") as r:
        catalogo = teses.catalogo_da_skill(textos_skill)
        r["itens"] = len(catalogo)
        r["arquivos"] = sorted({k["arquivo"] for k in catalogo})
    with rastro.etapa("issue_spotting", modelo=modelo) as r:
        issues = teses.executar(_rastreado(llm, r), catalogo=catalogo, matriz=matriz, texto_matriz=fatos.para_prompt(matriz),
                                contexto_caso=contexto_caso, estrategia_da_skill=textos_skill.get("SKILL.md", ""))
        r.update(teses.resumo_para_trace(issues))
    with rastro.etapa("matriz_com_fatos_chaveados") as r:
        matriz = fatos.montar(plano_est, case_facts=plano_est.get("case_facts"), fontes=fontes, fatos_extraidos=issues["fatos_extraidos"])
        r["resumo"] = matriz["resumo"]
        r["contradicoes"] = [c["chave"] for c in matriz["contradicoes"]]
    with rastro.etapa("calculos") as r:
        specs = [{"rubrica": t["calculo"]["rubrica"], "parametros": t["calculo"]["parametros"], "tese_id": t["id"]}
                 for t in issues["teses"] if t["decisao"] == teses.INCLUIR and t["calculo"].get("rubrica")]
        calcs = [c.como_dict() for c in calculos.executar(specs)]
        r["executados"] = [{"rubrica": c["rubrica"], "valor": c["valor"], "erro": c["erro"]} for c in calcs]
    return {"data_referencia": referencia, "plano_est_base": plano_est, "matriz": matriz, "catalogo": catalogo, "issues": issues,
            "calculos": calcs, "textos_skill": textos_skill, "rastro": rastro}


def fundamentar(
    prep: dict[str, Any], *, autoridades_base: Iterable[aut.Autoridade] = (), alertas_base: Iterable[str] = (),
    trechos_legislacao: Iterable[Any] = (), trechos_precedentes: Iterable[Any] = (), trt_competente: str = "",
    preferencia_tabelas: dict[str, bool] | None = None, provedor: ProvedorDeAutoridades | None = None,
) -> dict[str, Any]:
    """Fase 2 (depois da recuperação): base jurídica por tese, atualidade, tabelas e PETITION_PLAN.

    `provedor`: a busca de autoridades a usar; sem ele, o registro em memória com `autoridades_base`.
    """
    rastro: Rastro = prep["rastro"]
    referencia: date = prep["data_referencia"]
    issues, matriz, calcs, textos_skill = prep["issues"], prep["matriz"], prep["calculos"], prep["textos_skill"]
    plano_est = prep["plano_est_base"]
    alertas_juridicos: list[str] = []
    with rastro.etapa("base_juridica") as r:
        registro = provedor if provedor is not None else aut.Registro(autoridades_base, alertas=list(alertas_base))
        for a in [*aut.de_trechos_de_legislacao(trechos_legislacao), *aut.de_trechos_de_precedentes(trechos_precedentes)]:
            registro.adicionar(a)
        r["provedor"] = type(registro).__name__
        r["autoridades_no_registro"] = len(registro)
        r["alertas_do_registro"] = registro.alertas
        por_tese: dict[str, list[aut.Autoridade]] = {}
        r["consultas"] = []
        filtros = Filtros(data_referencia=referencia, incluir_inativas=True, trt_competente=trt_competente)
        for t in issues["teses"]:
            if teses.rejeitada(t):
                continue
            consulta = " ".join([t["tese"], *t["base_legal_a_pesquisar"], *t["jurisprudencia_a_pesquisar"]])
            achados = registro.consultar(consulta, filtros, 8)
            vigentes = [a for a, _ in achados if a.vigente_em(referencia) is not False]
            superadas = [a for a, _ in achados if a.vigente_em(referencia) is False]
            for s in superadas:
                substituta = registro.por_referencia(s.superado_por)
                alertas_juridicos.append(f"{s.titulo or s.chave} está {s.status} em {referencia.isoformat()}" + (f"; vigente: {substituta.titulo or substituta.chave} [{substituta.id}]" if substituta else (f"; substituída por {s.superado_por}" if s.superado_por else "")))
                if substituta and substituta not in vigentes:
                    vigentes.insert(0, substituta)
            por_tese[t["id"]] = vigentes[:5]
            r["consultas"].append({"tese": t["tese"], "consulta": consulta[:300], "recuperadas": [{"id": a.id, "score": s} for a, s in achados],
                                   "superadas": [a.id for a in superadas]})
        alertas_juridicos += _auditar_skill(textos_skill, registro, referencia)
        r["alertas"] = alertas_juridicos
    with rastro.etapa("tabelas") as r:
        tabs = tabelas.decidir(matriz, calcs, preferencia_tabelas)
        r["usar"] = [c for c, d in tabs.items() if d["decisao"] == "USE_TABLE"]
    with rastro.etapa("petition_plan") as r:
        plano_novo, pendencias = plano.integrar(plano_est, issues, calcs, matriz)
        unicas = list({a.id: a for lista in por_tese.values() for a in lista}.values())
        texto_plano = "\n\n".join([
            plano.para_prompt(issues=issues, plano=plano_novo, autoridades_por_tese=por_tese, tabelas=tabs, calculos=calcs, alertas_juridicos=alertas_juridicos),
            aut.bloco_para_prompt(unicas), fatos.para_prompt(matriz)])
        r["pedidos"] = len(plano_novo.get("pedidos") or [])
        r["pendencias"] = len(pendencias)
        r["chars"] = len(texto_plano)
    prep.update({"registro": registro, "autoridades_por_tese": por_tese, "alertas_juridicos": alertas_juridicos, "tabelas": tabs,
                 "plano_est": plano_novo, "pendencias": pendencias, "texto_plano": texto_plano})
    return prep


def auditar(
    secoes: list[dict[str, Any]], prep: dict[str, Any], *, pendencias: list[str], texto_das_fontes: str = "",
    carregar_dispositivos: Callable[[Iterable[str]], tuple[list[aut.Autoridade], str]] | None = None,
    pedidos_obrigatorios_ausentes: list[str] | None = None,
) -> dict[str, Any]:
    rastro: Rastro = prep["rastro"]
    registro: aut.Registro = prep["registro"]
    with rastro.etapa("auditoria") as r:
        if carregar_dispositivos:
            chaves = {c.chave for s in secoes for c in aut.extrair_citacoes(str(s.get("content") or ""))}
            novos, erro = carregar_dispositivos(chaves)
            for a in novos:
                registro.adicionar(a)
            r["dispositivos_carregados"] = len(novos)
            if erro:
                r["aviso"] = erro
        legal = auditores.auditar_legal(secoes, registro, prep["data_referencia"])
        fato = auditores.auditar_fatos(secoes, prep["matriz"], calculos=prep["calculos"], texto_das_fontes=texto_das_fontes)
        conta = auditores.auditar_calculos(secoes, prep["plano_est"].get("pedidos") or [], prep["calculos"])
        consist = auditores.auditar_consistencia(secoes, issues=prep["issues"], plano_est=prep["plano_est"], pendencias=pendencias,
                                                 matriz=prep["matriz"], tabelas=prep["tabelas"],
                                                 pedidos_obrigatorios_ausentes=pedidos_obrigatorios_ausentes)
        v = auditores.veredito(legal, fato, conta, consist)
        r.update(v)
    return {"veredito": v, "achados": [*legal["achados"], *fato["achados"], *conta["achados"], *consist["achados"]],
            "citacoes": legal["citacoes"], "authority_ids": legal["authority_ids"], "valor_da_causa": conta["valor_da_causa"],
            "valor_da_causa_declarado": conta["declarados"]}


def comparar_com_legado(secoes_legado: list[dict[str, Any]], prep: dict[str, Any], auditoria: dict[str, Any] | None,
                        *, plano_legado: dict[str, Any], pendencias_legado: list[str]) -> dict[str, Any]:
    """Modo shadow: o que a camada mudaria na peça que o fluxo legado entregou."""
    corpo = "\n".join(str(s.get("content") or "") for s in secoes_legado)
    no_corpo = auditores._tokens(corpo)  # noqa: SLF001
    pend = aut.norm(" ".join(pendencias_legado or []))

    def presente(t: dict[str, Any]) -> bool:
        alvo = auditores._tokens(t["tese"])  # noqa: SLF001
        return bool(alvo) and len(alvo & no_corpo) / len(alvo) >= 0.6

    todas = prep["issues"]["teses"]
    sustentadas = [t for t in todas if t["decisao"] == teses.SUPPORTED]
    potenciais = [t for t in todas if t["decisao"] == teses.POTENCIAL]
    pedidos_legado = plano_legado.get("pedidos") or []
    pedidos_novos = prep["plano_est"].get("pedidos") or []
    citacoes = (auditoria or {}).get("citacoes") or []
    achados = (auditoria or {}).get("achados") or []
    return {
        "teses_sustentadas": len(sustentadas),
        "teses_sustentadas_ausentes_no_legado": [t["tese"] for t in sustentadas if not presente(t)],
        "teses_a_confirmar_sem_registro_no_legado": [t["tese"] for t in potenciais if aut.norm(t["tese"])[:40] not in pend and not presente(t)],
        "citacoes_no_legado": len(citacoes),
        "citacoes_reprovadas_no_legado": [{k: c.get(k) for k in ("trecho", "status", "motivo", "secao")} for c in citacoes if not c.get("aprovada")],
        "valor_da_causa": {"legado_declarado": (auditoria or {}).get("valor_da_causa_declarado") or [],
                           "calculado_pela_camada": (prep["plano_est"].get("valor_da_causa_calculado") or {}).get("valor")},
        "pedidos": {"legado": len(pedidos_legado), "camada": len(pedidos_novos),
                    "so_na_camada": [p.get("objeto") or p.get("tipo") for p in pedidos_novos if p.get("origem") == "issue_spotting"]},
        "veredito_se_fosse_strict": (auditoria or {}).get("veredito"),
        "bloqueios_que_o_strict_apontaria": [f"[{a['auditor']}] {a['codigo']}: {a['trecho'] or a['detalhe']}"[:220]
                                             for a in achados if a["severidade"] == auditores.BLOQUEIA][:60],
    }


def trace_de_falha(modo: str, falhas: list[str]) -> dict[str, Any]:
    """Rastro quando a camada não chegou a produzir análise: o motivo aparece no admin e no veredito."""
    return {"ativo": True, "modo": modo, "falhas": list(falhas) or ["camada jurídica não produziu análise"],
            "comparacao_com_legado": None, "data_referencia": date.today().isoformat(), "etapas": [], "fatos": [],
            "contradicoes": [], "catalogo": [], "teses": [], "nao_avaliadas": [], "matriz_tese_fato_prova": [], "calculos": [],
            "autoridades_por_tese": {}, "alertas_juridicos": [], "tabelas": {}, "pendencias": [], "valor_da_causa": {},
            "auditoria": None, "citacoes": None}


def trace(prep: dict[str, Any], auditoria: dict[str, Any] | None, *, modo: str = "strict", falhas: list[str] | None = None,
          comparacao: dict[str, Any] | None = None) -> dict[str, Any]:
    """Versão serializável para o trace da peça e a tela do administrativo (sem texto bruto do caso)."""
    issues = prep["issues"]
    return {
        "ativo": True,
        "modo": modo,
        "falhas": list(falhas or []),
        "comparacao_com_legado": comparacao,
        "data_referencia": prep["data_referencia"].isoformat(),
        "etapas": prep["rastro"].etapas,
        "fatos": [{k: f.get(k) for k in ("id", "fato", "chave", "valor", "fonte", "documento", "pagina", "confianca", "estado", "contradicoes")}
                  for f in prep["matriz"]["fatos"]],
        "contradicoes": prep["matriz"]["contradicoes"],
        "catalogo": [{"id": k["id"], "tema": k["tema"], "arquivo": k["arquivo"]} for k in prep["catalogo"]],
        "teses": [{**{k: t.get(k) for k in ("id", "catalogo_id", "tese", "decisao", "decisao_do_modelo", "motivo", "rebaixada_por",
                                             "fatos_que_suportam", "fatos_necessarios", "fatos_faltantes", "base_legal_a_pesquisar",
                                             "jurisprudencia_a_pesquisar", "pedido", "reflexos", "prova", "exige_pericia", "risco",
                                             "pendente_de_calculo", "tese_plano_id")},
                   "rotulo": teses.ROTULOS.get(t["decisao"], t["decisao"]),
                   "fatos_detalhados": [{"id": i, "estado": f["estado"], "fato": (f.get("chave") and f"{f['chave']} = {f.get('valor', '')}") or f["fato"][:140]}
                                        for i in t["fatos_que_suportam"] for f in prep["matriz"]["fatos"] if f["id"] == i]}
                  for t in issues["teses"]],
        "nao_avaliadas": [k["tema"] for k in issues.get("nao_avaliados") or []],
        "matriz_tese_fato_prova": teses.matriz_tese_fato_prova(issues["teses"], prep["matriz"]),
        "calculos": prep["calculos"],
        "autoridades_por_tese": {tid: [{"id": a.id, "titulo": a.titulo or a.chave, "tipo": a.tipo, "tribunal": a.tribunal,
                                        "status": a.status, "verificada": a.verificada, "origem": a.origem} for a in lista]
                                 for tid, lista in prep["autoridades_por_tese"].items()},
        "alertas_juridicos": prep["alertas_juridicos"],
        "tabelas": prep["tabelas"],
        "pendencias": prep["pendencias"],
        "valor_da_causa": (prep["plano_est"].get("valor_da_causa_calculado") or {}),
        "auditoria": auditoria and {k: auditoria[k] for k in ("veredito", "achados", "authority_ids", "valor_da_causa")},
        "citacoes": auditoria and [{k: c.get(k) for k in ("trecho", "chave", "status", "authority_id", "motivo", "secao")} for c in auditoria["citacoes"]],
    }
