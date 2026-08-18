from pathlib import Path

from app.celery_app import celery_app
from app.tasks import ocr


def test_configuracao_para_tarefas_caras():
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.task_routes["app.tasks.ocr.*"]["queue"] == "gpu_background"
    assert "limpar-temporarios" in celery_app.conf.beat_schedule


def test_ocr_atualiza_estado_e_remove_upload(tmp_path, monkeypatch):
    entrada = tmp_path / "entrada.upload"
    entrada.write_bytes(b"imagem")
    eventos = []
    monkeypatch.setattr(ocr.jobs, "atualizar", lambda job_id, **campos: eventos.append(campos))
    monkeypatch.setattr(ocr.pipeline, "processar", lambda *args: {"id": "documento-1"})
    monkeypatch.setenv("OCR_USA_GPU", "0")

    resultado = ocr.processar_documento.run("job-1", str(entrada), "rg.png", "pt", None)

    assert resultado == {"id": "documento-1"}
    assert [evento["status"] for evento in eventos if "status" in evento] == [
        "STARTED", "PROCESSING", "COMPLETED"
    ]
    assert eventos[-1]["progresso"] == 100
    assert not entrada.exists()
