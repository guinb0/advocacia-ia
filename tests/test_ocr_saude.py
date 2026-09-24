"""Contrato da classificação: broker, SQL, inspect e heartbeat têm pesos distintos."""
from app.ocr_saude import _classificar


def _base(**altera):
    dados = {
        "waiting": 0, "active": 0, "healthy_workers": 3,
        "oldest_waiting_seconds": None, "oldest_processing_seconds": None,
        "queue_progressing": True,
    }
    dados.update(altera)
    return dados


def test_fila_sem_pendencia_e_workers_saudaveis():
    assert _classificar(_base()) == "HEALTHY"


def test_backlog_com_progresso_e_degradado_nao_travado():
    assert _classificar(_base(waiting=12, active=3, queue_progressing=True)) == "DEGRADED"


def test_backlog_antigo_sem_progresso_e_stalled():
    assert _classificar(_base(waiting=1, queue_progressing=False, oldest_waiting_seconds=301)) == "STALLED"


def test_sem_heartbeat_com_backlog_e_no_consumers():
    assert _classificar(_base(waiting=2, healthy_workers=0, queue_progressing=False)) == "NO_CONSUMERS"


def test_tarefa_longa_com_worker_vivo_e_possivel_hang():
    assert _classificar(_base(active=1, oldest_processing_seconds=781)) == "POSSIBLE_HUNG_TASK"


def test_redis_indisponivel_nunca_parece_saudavel():
    assert _classificar(_base(broker_error="ConnectionError")) == "DEGRADED"
