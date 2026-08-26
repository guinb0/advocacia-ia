from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import logging

from celery.signals import worker_ready

from .. import armazenamento, casos, categorias, jobs, pipeline
from ..celery_app import celery_app

log = logging.getLogger("ocr-worker")


def _executar_ocr(caminho: str, nome: str, idioma: str, tipo: str | None) -> dict:
    conteudo = Path(caminho).read_bytes()
    return pipeline.processar(conteudo, nome, idioma, tipo)


def _ler_anexo(entrega_id: str, caminho: str) -> bytes:
    """O binário do documento, venha ele do disco ou do banco.

    QUEM GRAVA E QUEM LÊ PODEM NÃO SER A MESMA MÁQUINA.

    O caminho que chega aqui foi escrito pela API, no disco DELA. Na estação de
    trabalho isso é o mesmo disco e ninguém nota. Em container — e em qualquer
    worker rodando fora da máquina da API, que é o modo de escalar descrito em
    `docs/CELERY.md` — o caminho pode simplesmente não existir deste lado.

    Ler direto do caminho transformava isso em `FileNotFoundError`, que a task
    reconhece como `OSError` e tenta de novo três vezes antes de desistir: quatro
    leituras condenadas a falhar por um arquivo que está inteiro no SQL Server,
    em `entregas.conteudo`. `caminho_duravel_da_entrega` restaura a cópia local a
    partir dele, conferindo o checksum antes de servir.
    """
    arquivo = Path(caminho)
    if arquivo.is_file():
        return arquivo.read_bytes()

    restaurado = armazenamento.caminho_duravel_da_entrega(entrega_id)
    if restaurado is None:
        # De propósito NÃO é um `OSError`: `autoretry_for` o repetiria três vezes,
        # e nada disto melhora com o tempo — ou o binário está no banco, ou não
        # está. Falhar na hora põe o pedido de reenvio na tela do advogado agora.
        raise RuntimeError(
            "O arquivo enviado não está no disco deste leitor nem tem cópia íntegra "
            "no banco. Peça o reenvio do documento."
        )
    log.info("anexo da entrega %s restaurado do banco para %s", entrega_id, restaurado)
    return restaurado.read_bytes()


def _entregar_ao_agente(caso_id: str, entrega_id: str) -> None:
    """Enfileira a integracao sem manter o worker pesado esperando HTTP."""
    try:
        from .agente import enviar_entrega_ao_agente

        enviar_entrega_ao_agente.apply_async(
            args=(caso_id, entrega_id),
            queue="default",
            priority=6,
        )
    except Exception:
        # O documento ja esta persistido e continua pendente no vinculo. Abrir o dossie
        # ainda executa a sincronizacao idempotente; perder a notificacao nunca perde OCR.
        log.warning(
            "nao foi possivel enfileirar a entrega %s ao agente juridico",
            entrega_id,
            exc_info=True,
        )


@worker_ready.connect
def aquecer_worker_ocr(sender=None, **_kwargs):
    """Carrega o modelo no worker, sem prender o boot numa inferência completa."""
    hostname = str(getattr(sender, "hostname", ""))
    if not hostname.lower().startswith("ocr@"):
        return
    try:
        from ..ocr_engine import aquecer

        aquecer()
        log.info("Mistral OCR configurada no worker %s.", hostname)
    except Exception:
        # O primeiro job tenta novamente; worker vivo é melhor que abortar toda
        # a fila por uma falha transitória de modelo no boot.
        log.exception("Falha ao configurar Mistral OCR no worker %s.", hostname)


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
        jobs.atualizar(job_id, progresso=30)
        resultado = _executar_ocr(caminho, nome, idioma, tipo)
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


@celery_app.task(
    bind=True,
    name="app.tasks.ocr.processar_entrega",
    autoretry_for=(OSError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def processar_entrega(
    self,
    entrega_id: str,
    caso_id: str,
    caminho: str,
    nome: str,
    item_codigo: str,
    categoria_codigo: str,
    idioma: str,
    usar_para_rg_e_cpf: bool,
):
    """Lê documento do checklist no worker dedicado ao OCR."""
    try:
        armazenamento.marcar_entrega_processando(entrega_id)
        categoria = categorias.obter(categoria_codigo)
        if categoria is None:
            raise ValueError(f"Categoria {categoria_codigo!r} não existe mais.")
        item = next((i for i in categoria.itens if i.codigo == item_codigo), None)
        if item is None:
            raise ValueError(f"Item {item_codigo!r} não pertence ao checklist.")

        conteudo = _ler_anexo(entrega_id, caminho)
        tipo_extracao = (
            "cin" if usar_para_rg_e_cpf and item.tipo_ocr in {"rg", "cpf"}
            else item.tipo_ocr
        )
        # O checklist persiste o JSON no banco e conserva o original em `dados`.
        # Gravar ainda outro JSON e XML em `tmp` era I/O sem consumidor.
        resultado = pipeline.processar(
            conteudo,
            nome,
            idioma,
            tipo_extracao,
            gerar_arquivos_temporarios=False,
        )

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
        _entregar_ao_agente(caso_id, entrega_id)
        return {"entrega_id": entrega_id, "concluida": True}
    except Exception as exc:
        log.exception("Falha ao ler o documento da entrega %s", entrega_id)
        armazenamento.falhar_entrega(entrega_id, str(exc))
        raise
