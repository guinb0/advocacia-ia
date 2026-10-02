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

from . import (auditor_certeza, auditor_secoes, auditor_semantico, auditor_temporal, auditores, autoridades as aut, calculos,
               canonico, citacao, contrateses, fatos, luna_pipeline, plano, proposicoes, prova, raciocinio, scores, tabelas, teses)
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
    llm_contrateses: Callable[[str, str], dict[str, Any]] | None = None, modelo_contrateses: str = "",
) -> dict[str, Any]:
    """Fase 1 (antes da recuperação): fatos, catálogo, issue spotting, cálculos e o grafo de raciocínio.

    `llm_contrateses`: o modelo que levanta as defesas prováveis; sem ele, só as do catálogo."""
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
        if luna_pipeline.ativo():
            bruto, telemetria, skill_meta = luna_pipeline.issue_spotting_duplo(
                _rastreado(llm, r), matriz=matriz, catalogo=catalogo, textos_skill=textos_skill)
            issues = teses.normalizar(bruto, catalogo, matriz)
            r["luna_pipeline_v2"] = {"telemetria": telemetria, "skill": skill_meta}
        else:
            issues = teses.executar(_rastreado(llm, r), catalogo=catalogo, matriz=matriz, texto_matriz=fatos.para_prompt(matriz),
                                    contexto_caso=contexto_caso, estrategia_da_skill=textos_skill.get("SKILL.md", ""))
        r.update(teses.resumo_para_trace(issues))
    with rastro.etapa("matriz_com_fatos_chaveados") as r:
        matriz = fatos.montar(plano_est, case_facts=plano_est.get("case_facts"), fontes=fontes, fatos_extraidos=issues["fatos_extraidos"])
        r["resumo"] = matriz["resumo"]
        r["contradicoes"] = [c["chave"] for c in matriz["contradicoes"]]
    with rastro.etapa("dados_canonicos") as r:
        canon = canonico.montar(matriz, petition_date=referencia)
        r["resumo"] = canon["resumo"]
        r["conflitos"] = [c["chave"] for c in canon["conflitos"]]
        r["derivados"] = [c["calculation_id"] for c in canon["calculos"] if not c["erro"]]
    with rastro.etapa("pressupostos_faticos") as r:
        incluidas = [t for t in issues["teses"] if t["decisao"] == teses.INCLUIR]
        rescisao_indireta = canonico.pede_rescisao_indireta(incluidas)
        r["termino_do_contrato"] = canonico.termino_do_contrato(canon)
        r["rescisao_indireta"] = rescisao_indireta
        r["rebaixadas"] = []
        for t in incluidas:
            motivo = canonico.pressuposto_rescisorio(t, canon, rescisao_indireta=rescisao_indireta)
            if motivo:
                t["decisao"], t["rebaixada_por"] = teses.POTENCIAL, motivo
                r["rebaixadas"].append({"tese_id": t["id"], "tese": t["tese"], "motivo": motivo})
    with rastro.etapa("calculos") as r:
        specs, preenchidos = [], {}
        for t in issues["teses"]:
            if t["decisao"] != teses.INCLUIR or not t["calculo"].get("rubrica"):
                continue
            rubrica = t["calculo"]["rubrica"]
            params, usados = canonico.completar_parametros(rubrica, t["calculo"]["parametros"], canon)
            extras: dict[str, dict[str, Any]] = {}
            if (rescisao_indireta and rubrica in canonico.RUBRICAS_RESCISORIAS and not canonico.termino_do_contrato(canon)
                    and "dispensa" in canonico.parametros_aceitos(rubrica)):
                params["dispensa"] = canon["petition_date"]
                extras["dispensa"] = {"chave": "petition_date", "rotulo": "término considerado", "exibir": referencia.strftime("%d/%m/%Y"),
                                      "valor": canon["petition_date"], "tipo": "data",
                                      "fonte": "data do ajuizamento — rescisão indireta pedida nesta ação"}
            specs.append({"rubrica": rubrica, "parametros": params, "tese_id": t["id"],
                          "fontes": canonico.fontes_dos_parametros(params, usados, canon, extras=extras)})
            if usados:
                preenchidos[t["id"]] = usados
        calcs = [c.como_dict() for c in calculos.executar(specs)]
        for c, spec in zip(calcs, specs):
            c["fontes"] = {k: f for k, f in spec["fontes"].items() if k in c["parametros"]}
        r["executados"] = [{"calculation_id": c["calculation_id"], "rubrica": c["rubrica"], "valor": c["valor"], "erro": c["erro"]} for c in calcs]
        r["parametros_da_fonte_unica"] = preenchidos
    rac = _montar_raciocinio(rastro, issues, matriz, calcs, llm=llm_contrateses, modelo=modelo_contrateses)
    return {"data_referencia": referencia, "plano_est_base": plano_est, "matriz": matriz, "catalogo": catalogo, "issues": issues,
            "canonico": canon, "calculos": calcs, "textos_skill": textos_skill, "rastro": rastro, "raciocinio": rac}


def _falha(rac: dict[str, Any], etapa: str, erro: Exception) -> None:
    rac.setdefault("falhas", []).append(f"{etapa}: {type(erro).__name__}: {str(erro)[:200]}")


def _montar_raciocinio(rastro: Rastro, issues: dict[str, Any], matriz: dict[str, Any], calcs: list[dict[str, Any]], *,
                       llm: Callable[[str, str], dict[str, Any]] | None, modelo: str) -> dict[str, Any]:
    """Grafo, matriz de prova, lacunas e contrateses. Aditivo: uma falha aqui fica no rastro e em `falhas`,
    sem derrubar a análise que já existia antes do motor."""
    rac: dict[str, Any] = {"versao_catalogo": "", "teses": [], "lacunas": [], "capitulos_vulneraveis": [], "falhas": []}
    try:
        with rastro.etapa("grafo_e_prova") as r:
            rac = {**raciocinio.montar(issues, matriz, calculos=calcs), "falhas": []}
            prova.montar(rac, matriz)
            prova.lacunas(rac)
            r["teses"] = len(rac["teses"])
            r["requisitos"] = sum(len(t["requisitos"]) for t in rac["teses"])
            r["lacunas"] = len(rac["lacunas"])
    except Exception as erro:  # noqa: BLE001
        _falha(rac, "grafo_e_prova", erro)
        return rac
    try:
        with rastro.etapa("contrateses", modelo=modelo if llm else "") as r:
            r.update(contrateses.gerar(rac, matriz, llm=_rastreado(llm, r) if llm else None, texto_matriz=fatos.para_prompt(matriz)))
            r["capitulos_vulneraveis"] = len(rac["capitulos_vulneraveis"])
    except Exception as erro:  # noqa: BLE001
        _falha(rac, "contrateses", erro)
    return rac


def fundamentar(
    prep: dict[str, Any], *, autoridades_base: Iterable[aut.Autoridade] = (), alertas_base: Iterable[str] = (),
    trechos_legislacao: Iterable[Any] = (), trechos_precedentes: Iterable[Any] = (), trt_competente: str = "",
    preferencia_tabelas: dict[str, bool] | None = None, provedor: ProvedorDeAutoridades | None = None,
    llm_proposicoes: Callable[[str, str], dict[str, Any]] | None = None, modelo_proposicoes: str = "",
) -> dict[str, Any]:
    """Fase 2 (depois da recuperação): base jurídica por tese, atualidade, tabelas e PETITION_PLAN.

    `provedor`: a busca de autoridades a usar; sem ele, o registro em memória com `autoridades_base`.
    `llm_proposicoes`: classifica sustenta/contraria por proposição; sem ele, a relação fica presumida.
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
    rac = prep.get("raciocinio")
    if rac and rac.get("teses"):
        try:
            with rastro.etapa("proposicoes", modelo=modelo_proposicoes if llm_proposicoes else "") as r:
                r.update(proposicoes.pesquisar(rac, registro, data_referencia=referencia, trt_competente=trt_competente,
                                               llm=_rastreado(llm_proposicoes, r) if llm_proposicoes else None))
                r["certeza"] = proposicoes.resumo(rac)
        except Exception as erro:  # noqa: BLE001
            _falha(rac, "proposicoes", erro)
        _calcular_scores(rastro, rac, matriz)
    with rastro.etapa("tabelas") as r:
        tabs = tabelas.decidir(matriz, calcs, preferencia_tabelas)
        r["usar"] = [c for c, d in tabs.items() if d["decisao"] == "USE_TABLE"]
    with rastro.etapa("petition_plan") as r:
        plano_novo, pendencias = plano.integrar(plano_est, issues, calcs, matriz)
        retirados = plano.retirar_pedidos_sem_pressuposto(plano_novo, issues, prep.get("canonico"))
        pendencias += retirados
        r["pedidos_retirados_sem_pressuposto"] = retirados
        plano.estruturar_pedidos(plano_novo, issues, por_tese)
        sem_vinculo = plano.retirar_pedidos_sem_vinculo(plano_novo)
        pendencias += sem_vinculo
        r["pedidos_retirados_sem_vinculo"] = sem_vinculo
        r["pedidos_sem_valor"] = [p["id"] for p in plano_novo.get("pedidos") or [] if p.get("status") == "PENDING_CALCULATION"]
        pendencias += [f"Pedido de pagamento sem valor calculado: {p.get('title') or p['id']} — fica fora do corpo até ser calculado"
                       for p in plano_novo.get("pedidos") or [] if p.get("status") == "PENDING_CALCULATION"]
        unicas = list({a.id: a for lista in por_tese.values() for a in lista}.values())
        bloco_motor = raciocinio.para_prompt(rac)
        texto_plano = "\n\n".join([
            plano.para_prompt(issues=issues, plano=plano_novo, autoridades_por_tese=por_tese, tabelas=tabs, calculos=calcs, alertas_juridicos=alertas_juridicos),
            canonico.para_prompt(prep.get("canonico")), aut.bloco_para_prompt(unicas), *([bloco_motor] if bloco_motor else []),
            fatos.para_prompt(matriz)])
        r["pedidos"] = len(plano_novo.get("pedidos") or [])
        r["pendencias"] = len(pendencias)
        r["chars"] = len(texto_plano)
    prep.update({"registro": registro, "autoridades_por_tese": por_tese, "alertas_juridicos": alertas_juridicos, "tabelas": tabs,
                 "plano_est": plano_novo, "pendencias": pendencias, "texto_plano": texto_plano})
    return prep


def _calcular_scores(rastro: Rastro, rac: dict[str, Any], matriz: dict[str, Any]) -> None:
    try:
        with rastro.etapa("scores") as r:
            r["teses"] = [{"tese_id": s["tese_id"], "prioridade": s["prioridade"]} for s in scores.calcular(rac, matriz)]
            rac["alertas"] = scores.alertas(rac)
            r["alertas"] = len(rac["alertas"])
    except Exception as erro:  # noqa: BLE001
        _falha(rac, "scores", erro)


def pendencias_do_motor(prep: dict[str, Any]) -> list[str]:
    """O que o advogado deve revisar segundo o motor: lacunas de prova, defesas sem resposta/prova e alertas de score."""
    rac = prep.get("raciocinio") or {}
    if not rac.get("teses"):
        return []
    return list(dict.fromkeys([*prova.pendencias(rac), *contrateses.pendencias(rac), *(rac.get("alertas") or [])]))


def auditar(
    secoes: list[dict[str, Any]], prep: dict[str, Any], *, pendencias: list[str], texto_das_fontes: str = "",
    carregar_dispositivos: Callable[[Iterable[str]], tuple[list[aut.Autoridade], str]] | None = None,
    pedidos_obrigatorios_ausentes: list[str] | None = None, llm: Callable[[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Os auditores originais + os gates TEMPORAL, FACT_CERTAINTY, SEMANTIC_CONTRADICTION, CITATION_GATE e
    CROSS_SECTION. `llm`: o verificador de sustentação das citações e a 2ª camada semântica; sem ele, a
    sustentação fica NOT_EVALUATED e a peça não fica READY."""
    rastro: Rastro = prep["rastro"]
    registro: aut.Registro = prep["registro"]
    referencia: date = prep["data_referencia"]
    canon = prep.get("canonico")
    pedidos = prep["plano_est"].get("pedidos") or []
    with rastro.etapa("auditoria") as r:
        if carregar_dispositivos:
            chaves = {c.chave for s in secoes for c in aut.extrair_citacoes(str(s.get("content") or ""))}
            novos, erro = carregar_dispositivos(chaves)
            for a in novos:
                registro.adicionar(a)
            r["dispositivos_carregados"] = len(novos)
            if erro:
                r["aviso"] = erro
        legal = auditores.auditar_legal(secoes, registro, referencia)
        fato = auditores.auditar_fatos(secoes, prep["matriz"], calculos=prep["calculos"], texto_das_fontes=texto_das_fontes)
        conta = auditores.auditar_calculos(secoes, pedidos, prep["calculos"])
        consist = auditores.auditar_consistencia(secoes, issues=prep["issues"], plano_est=prep["plano_est"], pendencias=pendencias,
                                                 matriz=prep["matriz"], tabelas=prep["tabelas"],
                                                 pedidos_obrigatorios_ausentes=pedidos_obrigatorios_ausentes)
    with rastro.etapa("gates") as r:
        citadas = [registro.por_id[c["authority_id"]] for c in legal["citacoes"] if c.get("authority_id") in registro.por_id]
        temporal = auditor_temporal.auditar(secoes, petition_date=referencia, matriz=prep["matriz"], canon=canon, autoridades_citadas=citadas)
        certeza = auditor_certeza.auditar(secoes, canon=canon, matriz=prep["matriz"],
                                          exige_pericia=any(t.get("exige_pericia") and t["decisao"] == teses.SUPPORTED for t in prep["issues"]["teses"]))
        semantica = auditor_semantico.auditar(secoes, canon=canon, calculos=prep["calculos"], matriz=prep["matriz"], llm=llm)
        gate2 = citacao.verificar(secoes, registro, referencia, llm=llm)
        cruzado = auditor_secoes.auditar(secoes, canon=canon, pedidos=pedidos, calculos=prep["calculos"], matriz=prep["matriz"],
                                         texto_das_fontes=texto_das_fontes)
        r["citacoes"] = gate2["resumo"]
        r["semantica_llm"] = semantica["relatorio"]["camada_llm"]
        motor = _auditar_motor(secoes, prep, llm=llm)
        r["motor"] = (prep.get("raciocinio") or {}).get("auditoria")
        v = auditores.veredito(legal, fato, conta, consist, temporal, certeza, semantica, gate2, cruzado, *motor)
        r.update(v)
    relatorios = (legal, fato, conta, consist, temporal, certeza, semantica, gate2, cruzado, *motor)
    return {"veredito": v, "achados": [a for rel in relatorios for a in rel["achados"]],
            "citacoes": legal["citacoes"], "citacoes_verificadas": gate2["citacoes"], "authority_ids": legal["authority_ids"],
            "valor_da_causa": conta["valor_da_causa"], "valor_da_causa_declarado": conta["declarados"],
            "impressoes_digitais": cruzado["impressoes"], "semantica": semantica["relatorio"]}


def _auditar_motor(secoes: list[dict[str, Any]], prep: dict[str, Any], *,
                   llm: Callable[[str, str], dict[str, Any]] | None) -> list[dict[str, Any]]:
    """COUNTERARGUMENT, LEGAL_CERTAINTY e PRECEDENT_QUALITY. Achados são WARNING/INFO (nunca retêm a peça);
    uma falha deixa só o registro em `raciocinio.falhas`."""
    rac = prep.get("raciocinio")
    if not rac or not rac.get("teses"):
        return []
    saida = []
    try:
        contra = contrateses.auditar(secoes, rac, llm=llm)
        saida.append(contra)
        saida.append(proposicoes.auditar_certeza(secoes, rac))
        saida.append(proposicoes.auditar_precedentes(secoes, rac, prep["registro"], prep["data_referencia"]))
        rac["auditoria"] = {r["auditor"]: len(r["achados"]) for r in saida} | {"avaliacao_contrateses": contra["avaliacao"]}
    except Exception as erro:  # noqa: BLE001
        _falha(rac, "auditoria_do_motor", erro)
    _calcular_scores(prep["rastro"], rac, prep["matriz"])
    return saida


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
            "comparacao_com_legado": None, "data_referencia": date.today().isoformat(), "etapas": [], "canonico": None, "fatos": [],
            "contradicoes": [], "catalogo": [], "teses": [], "nao_avaliadas": [], "matriz_tese_fato_prova": [], "calculos": [],
            "autoridades_por_tese": {}, "alertas_juridicos": [], "tabelas": {}, "pendencias": [], "valor_da_causa": {},
            "auditoria": None, "citacoes": None, "raciocinio": None, "pendencias_do_motor": []}


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
        "canonico": canonico.para_trace(prep.get("canonico")),
        "fatos": [{**{k: f.get(k) for k in ("id", "fato", "chave", "valor", "fonte", "documento", "pagina", "confianca", "estado", "contradicoes")},
                   "certeza": canonico.certeza_do_fato(f)} for f in prep["matriz"]["fatos"]],
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
        "pedidos": [{k: p.get(k) for k in ("request_id", "title", "factual_support", "authority_ids", "calculation_id", "value", "reflexes",
                                           "expert_evidence_required", "status", "natureza", "tipo_de_item")}
                    for p in prep["plano_est"].get("pedidos") or []],
        "auditoria": auditoria and {**{k: auditoria[k] for k in ("veredito", "achados", "authority_ids", "valor_da_causa")},
                                    "impressoes_digitais": auditoria.get("impressoes_digitais") or [], "semantica": auditoria.get("semantica")},
        "citacoes": auditoria and _citacoes_para_trace(auditoria),
        "raciocinio": raciocinio.para_trace(prep.get("raciocinio"), prep["matriz"]),
        "pendencias_do_motor": pendencias_do_motor(prep),
    }


def _citacoes_para_trace(auditoria: dict[str, Any]) -> list[dict[str, Any]]:
    """Citação com o status do gate antigo e as quatro checagens do 2.0 (mesma ordem de ocorrência na peça)."""
    verificadas = list(auditoria.get("citacoes_verificadas") or [])
    saida = []
    for i, c in enumerate(auditoria.get("citacoes") or []):
        base = {k: c.get(k) for k in ("trecho", "chave", "status", "authority_id", "motivo", "secao")}
        v = verificadas[i] if i < len(verificadas) and verificadas[i].get("chave") == c.get("chave") else None
        if v:
            base.update({k: v.get(k) for k in ("versao", "titulo", "checks", "classificacao", "trecho_oficial", "justificativa", "sucessora", "aprovada", "afirmacao")})
            base["motivo"] = base["motivo"] or v.get("motivo")
        saida.append(base)
    return saida
