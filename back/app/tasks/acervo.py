"""Sincronização noturna do Acervo Jurídico (fila `low`).

A ronda do beat não sincroniza nada sozinha: enfileira UMA subtarefa por norma. O worker de
produção consome `low` junto com `ai`/`documents` e concorrência 1 — uma norma por vez deixa as
outras filas respirarem entre uma e outra. Enquanto `ACERVO_SINCRONIZACAO_ATIVA != 1`, nada roda.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..celery_app import celery_app

log = logging.getLogger("acervo")


@celery_app.task(name="app.tasks.acervo.sincronizar_acervo")
def sincronizar_acervo() -> dict:
    from ..acervo import agenda, armazenamento, sincronizacao
    if not agenda.ativa():
        return {"executado": False, "motivo": "ACERVO_SINCRONIZACAO_ATIVA desligada"}
    if not armazenamento.padrao().migracao_aplicada():
        log.warning("acervo: migration 011 não aplicada; sincronização não roda")
        return {"executado": False, "motivo": "migração 011 não aplicada"}
    ids = [i["id"] for i in sincronizacao.manifesto() if i.get("categoria", "legislacao") == "legislacao"]
    for doc in ids:
        sincronizar_documento.apply_async(args=[doc], kwargs={"origem": "agendada"}, queue="low")
    finalizar_ronda.apply_async(countdown=3600, queue="low")
    return {"executado": True, "enfileirados": ids}


@celery_app.task(name="app.tasks.acervo.sincronizar_documento", soft_time_limit=1500, time_limit=1800)
def sincronizar_documento(document_id: str, origem: str = "manual", solicitado_por: str = "", reindexar: bool = False) -> dict:
    from ..acervo import agenda, armazenamento, sincronizacao
    if not agenda.ativa():
        return {"executado": False, "motivo": "ACERVO_SINCRONIZACAO_ATIVA desligada"}
    item = sincronizacao.item_do_manifesto(document_id)
    if not item:
        return {"executado": False, "motivo": f"norma {document_id} fora do manifesto"}
    gerar = sincronizacao.gerar_embeddings_padrao if sincronizacao.embeddings_configurados() else None
    rel = sincronizacao.sincronizar_documento(item, armazenamento=armazenamento.padrao(), gerar_embeddings=gerar, origem=origem,
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
