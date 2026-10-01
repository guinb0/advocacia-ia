"""Sincronização semanal do Acervo Jurídico (fila `low`).

A ronda do beat não sincroniza nada sozinha: enfileira UMA subtarefa por norma (padrão: a CLT,
`ACERVO_DOCUMENTOS_AGENDADOS`). A garantia, a cada 30 min, cobre a primeira carga depois do deploy
e a ronda que falhou. A rodada automática só roda com embeddings configurados: sem vetor, o texto
alterado sairia da busca até a próxima sincronização. Enquanto `ACERVO_SINCRONIZACAO_ATIVA != 1`,
nada roda.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..celery_app import celery_app

log = logging.getLogger("acervo")

ORIGENS_AUTOMATICAS = ("agendada", "garantia")


def _impedimento_automatico() -> str:
    from ..acervo import agenda, armazenamento, sincronizacao
    if not agenda.ativa():
        return "ACERVO_SINCRONIZACAO_ATIVA desligada"
    if not sincronizacao.embeddings_configurados():
        return "EMBEDDINGS_* não configurado: a rodada automática não roda sem vetor"
    if not armazenamento.padrao().migracao_aplicada():
        log.warning("acervo: migration 011 não aplicada; sincronização não roda")
        return "migração 011 não aplicada"
    return ""


@celery_app.task(name="app.tasks.acervo.sincronizar_acervo")
def sincronizar_acervo() -> dict:
    from ..acervo import agenda
    motivo = _impedimento_automatico()
    if motivo:
        return {"executado": False, "motivo": motivo}
    ids = agenda.documentos_agendados()
    for doc in ids:
        sincronizar_documento.apply_async(args=[doc], kwargs={"origem": "agendada"}, queue="low")
    finalizar_ronda.apply_async(countdown=3600, queue="low")
    return {"executado": True, "enfileirados": ids}


@celery_app.task(name="app.tasks.acervo.garantir_sincronizacao")
def garantir_sincronizacao() -> dict:
    from ..acervo import agenda, armazenamento
    motivo = _impedimento_automatico()
    if motivo:
        return {"executado": False, "motivo": motivo}
    atrasados = agenda.documentos_atrasados(armazenamento.padrao(), agenda.documentos_agendados())
    for doc in atrasados:
        sincronizar_documento.apply_async(args=[doc], kwargs={"origem": "garantia"}, queue="low")
    if atrasados:
        log.info("acervo: sincronização garantida para %s", ", ".join(atrasados))
        finalizar_ronda.apply_async(countdown=3600, queue="low")
    return {"executado": bool(atrasados), "enfileirados": atrasados}


@celery_app.task(name="app.tasks.acervo.sincronizar_documento", soft_time_limit=1500, time_limit=1800)
def sincronizar_documento(document_id: str, origem: str = "manual", solicitado_por: str = "", reindexar: bool = False) -> dict:
    from ..acervo import agenda, armazenamento, sincronizacao
    if not agenda.ativa():
        return {"executado": False, "motivo": "ACERVO_SINCRONIZACAO_ATIVA desligada"}
    item = sincronizacao.item_do_manifesto(document_id)
    if not item:
        return {"executado": False, "motivo": f"norma {document_id} fora do manifesto"}
    store = armazenamento.padrao()
    if origem in ORIGENS_AUTOMATICAS and agenda.sincronizada_agora_pouco(store, document_id):
        return {"executado": False, "motivo": f"{document_id} já sincronizada ou em andamento"}
    gerar = sincronizacao.gerar_embeddings_padrao if sincronizacao.embeddings_configurados() else None
    rel = sincronizacao.sincronizar_documento(item, armazenamento=store, gerar_embeddings=gerar, origem=origem,
                                              solicitado_por=solicitado_por, forcar_reindexacao=reindexar)
    return {k: v for k, v in rel.items() if not isinstance(v, list)}


@celery_app.task(name="app.tasks.acervo.finalizar_ronda")
def finalizar_ronda() -> dict:
    """Depois das normas: jurisprudência importada e varredura das skills (só alerta)."""
    from ..acervo import agenda, armazenamento, jurisprudencia, skills
    if not agenda.ativa():
        return {"executado": False}
    store = armazenamento.padrao()
    agora = datetime.now(UTC)
    alterados = {(a["document_id"], a["dispositivo_id"]) for a in store.alertas(abertos=True, limite=500)
                 if a["tipo"] in ("DISPOSITIVO_ALTERADO", "DISPOSITIVO_REVOGADO") and a.get("criado_em") and
                 (agora - a["criado_em"]).total_seconds() < 6 * 3600}
    juris = jurisprudencia.importar_pasta(armazenamento=store, agora=agora)
    gerados = skills.varrer(store, alterados=alterados, agora=agora)
    return {"executado": True, "jurisprudencia": juris, "alertas_de_skill": len(gerados)}
