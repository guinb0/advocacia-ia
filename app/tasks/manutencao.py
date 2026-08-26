from __future__ import annotations

from .. import armazenamento, casos, jobs, pipeline
from ..celery_app import celery_app
from pathlib import Path
import logging
import time

log = logging.getLogger("manutencao")

#: Mesmo limite que a tela usa para parar de dizer "aguardando a vez na fila".
#: Vem de `casos` para que o alerta e a recuperação nunca discordem — uma entrega
#: nunca deve ser anunciada como travada sem que alguém esteja indo buscá-la.
MINUTOS_TRAVADA = casos.MINUTOS_ESPERA_ANORMAL


@celery_app.task(name="app.tasks.manutencao.limpar_temporarios")
def limpar_temporarios() -> int:
    removidos = pipeline.limpar_temporarios()
    pasta_jobs = pipeline.TMP_DIR / "jobs"
    limite = time.time() - 24 * 3600
    for caminho in pasta_jobs.glob("*.upload") if pasta_jobs.exists() else ():
        try:
            if caminho.stat().st_mtime < limite:
                caminho.unlink()
                removidos += 1
        except OSError:
            pass
    return removidos


@celery_app.task(name="app.tasks.manutencao.recuperar_jobs_abandonados")
def recuperar_jobs_abandonados() -> int:
    return jobs.recuperar_abandonados()


def _leitor_de_documentos_ativo() -> tuple[bool, set[str]]:
    """O worker de OCR está no ar, e quais entregas ele já tem em mãos?

    Duas perguntas numa consulta só porque as duas saem do mesmo `inspect` — e
    porque as duas decidem a mesma coisa. Sem worker consumindo `gpu_background`,
    reenfileirar só empilha mensagem que ninguém vai buscar; e uma entrega que
    ESTÁ sendo lida agora não pode ser reenfileirada por estar demorando.

    Broker fora do ar responde `None`, e aí a resposta é "não há worker": o lado
    seguro de errar é não mexer em nada.
    """
    try:
        inspecao = celery_app.control.inspect(timeout=3)
        filas = inspecao.active_queues() or {}
        ativas = inspecao.active() or {}
    except Exception:  # noqa: BLE001 - fronteira com o broker
        log.warning("não foi possível inspecionar os workers", exc_info=True)
        return False, set()

    consumindo = any(
        q.get("name") == "gpu_background" for fila in filas.values() for q in fila
    )
    # O primeiro argumento de `processar_entrega` é o id da entrega.
    em_leitura = {
        str(tarefa["args"][0])
        for tarefas in ativas.values()
        for tarefa in tarefas
        if tarefa.get("name", "").endswith("processar_entrega") and tarefa.get("args")
    }
    return consumindo, em_leitura


@celery_app.task(name="app.tasks.manutencao.recuperar_entregas_travadas")
def recuperar_entregas_travadas() -> int:
    """Devolve à fila o documento que ficou "Lendo" para sempre.

    O par desta função é `jobs.recuperar_abandonados`, que já cobria o mesmo
    acidente do lado de `/api/extrair/jobs`. O checklist nunca teve equivalente:
    entrega que entrasse em `na_fila` com o worker de OCR morto ficava ali
    indefinidamente, sem timeout, sem nova tentativa e sem erro — a tela dizia
    "aguardando a vez na fila" enquanto não havia fila andando.

    Reenfileira em vez de marcar erro porque o arquivo continua em disco: quando
    o leitor volta, o documento é lido sozinho e ninguém precisa reenviar nada.
    O laço termina por si — a task ou conclui (`pronto`) ou levanta (`erro`), e
    nos dois casos a entrega sai deste conjunto.
    """
    travadas = armazenamento.entregas_travadas(MINUTOS_TRAVADA)
    if not travadas:
        return 0

    ativo, em_leitura = _leitor_de_documentos_ativo()
    if not ativo:
        # Reenfileirar aqui só empilharia cópias da mesma mensagem a cada 5 min.
        # A linha existe para que o motivo real apareça no log: o problema é o
        # worker, não o documento.
        log.error(
            "%d entrega(s) esperando leitura e NENHUM worker consumindo 'gpu_background' — "
            "o leitor de documentos está fora do ar.",
            len(travadas),
        )
        return 0

    from .ocr import processar_entrega

    reenfileiradas = 0
    for entrega in travadas:
        if entrega["id"] in em_leitura:
            continue  # está sendo lida agora; demorar não é estar travada.

        # NÃO basta `Path(caminho).exists()`. Em container, quem gravou o upload
        # foi a API, e o caminho de lá pode não existir aqui — mas o binário está
        # no SQL Server (`entregas.conteudo`), e `caminho_duravel_da_entrega`
        # restaura o arquivo local a partir dele, conferindo o checksum. Testar
        # só o disco condenaria ao erro um documento que está inteiro no banco.
        caminho = armazenamento.caminho_duravel_da_entrega(entrega["id"])
        if caminho is None:
            # Nem disco nem banco: não há o que reler. Vira erro para o advogado
            # ver a pendência e pedir o reenvio, em vez de esperar pelo que não vem.
            armazenamento.falhar_entrega(
                entrega["id"],
                "O arquivo enviado não está mais no servidor. Peça o reenvio do documento.",
            )
            log.warning(
                "entrega %s não tem arquivo em disco nem cópia no banco; marcada como erro",
                entrega["id"],
            )
            continue

        processar_entrega.apply_async(
            args=(
                entrega["id"],
                entrega["caso_id"],
                str(caminho),
                entrega["arquivo"],
                entrega["item_codigo"],
                entrega["categoria"],
                "pt",
                len(entrega["itens_atendidos"]) > 1,
            ),
            queue="gpu_background",
            priority=7,
        )
        reenfileiradas += 1
        log.warning(
            "entrega %s estava em '%s' desde %s; devolvida à fila de leitura",
            entrega["id"],
            entrega["status_proc"],
            entrega["criado_em"],
        )

    return reenfileiradas
