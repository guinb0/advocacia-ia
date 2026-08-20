from __future__ import annotations

from datetime import datetime, timezone
from contextlib import nullcontext
import os
from pathlib import Path
import logging

from celery.signals import worker_ready

from .. import armazenamento, casos, categorias, jobs, pipeline
from ..celery_app import celery_app
from ..gpu_lock import gpu_exclusiva

log = logging.getLogger("ocr-worker")


@worker_ready.connect
def aquecer_worker_ocr(sender=None, **_kwargs):
    """Aquece o modelo no processo que realmente executa `/extrair/jobs`."""
    hostname = str(getattr(sender, "hostname", ""))
    if not hostname.lower().startswith("ocr@"):
        return
    try:
        from ..ocr_engine import aquecer
        aquecer()
        log.info("PaddleOCR aquecido no worker %s.", hostname)
    except Exception:
        # O primeiro job tenta novamente; worker vivo é melhor que abortar toda
        # a fila por uma falha transitória de modelo no boot.
        log.exception("Falha ao aquecer PaddleOCR no worker %s.", hostname)


@celery_app.task(
    bind=True,
    name="app.tasks.ocr.processar_documento",
    autoretry_for=(OSError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def processar_documento(self, job_id: str, caminho: str, nome: str, idioma: str, tipo: str | None):
    inicio = datetime.now(timezone.utc)
    jobs.atualizar(job_id, status="STARTED", progresso=5, iniciado_em=inicio)
    try:
        jobs.atualizar(job_id, status="PROCESSING", progresso=15)
        conteudo = Path(caminho).read_bytes()
        # O Paddle atual é CPU por decisão medida. Ao ativar a wheel CUDA, esta
        # mesma tarefa passa a disputar a trava interprocesso com o Whisper.
        trava = gpu_exclusiva() if os.getenv("OCR_USA_GPU", "0") == "1" else nullcontext()
        with trava:
            jobs.atualizar(job_id, progresso=30)
            resultado = pipeline.processar(conteudo, nome, idioma, tipo)
        jobs.atualizar(
            job_id,
            status="COMPLETED",
            progresso=100,
            resultado=resultado,
            finalizado_em=datetime.now(timezone.utc),
        )
        Path(caminho).unlink(missing_ok=True)
        return resultado
    except Exception as exc:
        # Se houver retry, a próxima execução volta o estado para STARTED.
        jobs.atualizar(job_id, status="FAILED", erro=str(exc), finalizado_em=datetime.now(timezone.utc))
        raise


@celery_app.task(name="app.tasks.ocr.processar_entrega")
def processar_entrega(
    entrega_id: str,
    caso_id: str,
    caminho: str,
    nome: str,
    item_codigo: str,
    categoria_codigo: str,
    idioma: str,
    usar_para_rg_e_cpf: bool,
):
    """Lê documento do checklist no worker que já mantém o Paddle aquecido."""
    try:
        categoria = categorias.obter(categoria_codigo)
        if categoria is None:
            raise ValueError(f"Categoria {categoria_codigo!r} não existe mais.")
        item = next((i for i in categoria.itens if i.codigo == item_codigo), None)
        if item is None:
            raise ValueError(f"Item {item_codigo!r} não pertence ao checklist.")

        conteudo = Path(caminho).read_bytes()
        tipo_extracao = (
            "cin" if usar_para_rg_e_cpf and item.tipo_ocr in {"rg", "cpf"}
            else item.tipo_ocr
        )
        resultado = pipeline.processar(conteudo, nome, idioma, tipo_extracao)

        unificar = usar_para_rg_e_cpf
        if not unificar and item.tipo_ocr in {"rg", "cpf"}:
            unificar = casos.cobre_rg_e_cpf(resultado)
        try:
            itens_atendidos = (
                casos.itens_para_identidade_unificada(categoria, item)
                if unificar else [item.codigo]
            )
        except ValueError:
            itens_atendidos = [item.codigo]
            unificar = False

        detectado = resultado.get("tipo", {}).get("detectado")
        confere = casos.tipo_confere(item, detectado, unificar)
        armazenamento.concluir_entrega(entrega_id, resultado, confere, itens_atendidos)
        try:
            from ..agente import espelho
            espelho.enviar_entrega(caso_id, entrega_id)
        except Exception:
            log.warning("Não foi possível entregar %s ao agente jurídico.", entrega_id, exc_info=True)
        return {"entrega_id": entrega_id, "concluida": True}
    except Exception as exc:
        log.exception("Falha ao ler o documento da entrega %s", entrega_id)
        armazenamento.falhar_entrega(entrega_id, str(exc))
        raise
