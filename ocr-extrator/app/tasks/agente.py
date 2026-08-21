"""Entregas leves ao agente juridico, separadas do worker pesado de OCR."""

from __future__ import annotations

import logging

from .. import armazenamento
from ..agente import espelho
from ..agente.cliente import AgenteIndisponivel, ErroDoAgente
from ..celery_app import celery_app

log = logging.getLogger("integracao-agente")


@celery_app.task(
    bind=True,
    name="app.tasks.agente.enviar_entrega",
    autoretry_for=(AgenteIndisponivel,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def enviar_entrega_ao_agente(self, caso_id: str, entrega_id: str) -> bool:
    """Garante o vinculo e envia sem repetir a inferencia PaddleOCR em caso de falha."""
    try:
        espelho.garantir_caso(caso_id)
        enviado = espelho.enviar_entrega(caso_id, entrega_id, silencioso=False)
    except ErroDoAgente as erro:
        # Falhas 4xx representam configuracao/contrato e precisam de intervencao. Rede e
        # respostas 5xx sao transitorias e entram no retry automatico do Celery.
        if isinstance(erro, AgenteIndisponivel) or (erro.status or 0) >= 500:
            raise AgenteIndisponivel(str(erro)) from erro
        raise
    if not enviado:
        log.warning("entrega %s ainda nao estava pronta para o agente", entrega_id)
    return enviado


@celery_app.task(name="app.tasks.agente.reenfileirar_pendentes")
def reenfileirar_pendentes(limite: int = 200) -> int:
    """Recupera notificacoes perdidas sem reexecutar o OCR."""
    enfileiradas = 0
    for caso in armazenamento.listar_casos():
        caso_id = str(caso["id"])
        vinculo = armazenamento.obter_vinculo_agente(caso_id) or {}
        enviadas = {str(item) for item in (vinculo.get("enviados") or [])}
        for entrega in armazenamento.listar_entregas(caso_id):
            if entrega.get("status_proc") != "pronto" or str(entrega["id"]) in enviadas:
                continue
            enviar_entrega_ao_agente.apply_async(
                args=(caso_id, str(entrega["id"])),
                queue="default",
                priority=6,
            )
            enfileiradas += 1
            if enfileiradas >= max(1, min(limite, 1000)):
                return enfileiradas
    return enfileiradas
