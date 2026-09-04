from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.celery_app import celery_app
from app.tasks import ocr
from app.tasks import agente as tarefa_agente


def test_configuracao_para_tarefas_caras():
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.task_routes["app.tasks.ocr.*"]["queue"] == "gpu_background"
    assert celery_app.conf.task_routes["app.tasks.agente.*"]["queue"] == "default"
    assert "limpar-temporarios" in celery_app.conf.beat_schedule
    assert "reenfileirar-entregas-ao-agente" in celery_app.conf.beat_schedule


def test_entrega_ao_agente_roda_fora_da_fila_de_ocr(monkeypatch):
    chamada = {}
    monkeypatch.setattr(
        tarefa_agente.espelho,
        "garantir_caso",
        lambda caso_id: chamada.update(caso=caso_id),
    )
    monkeypatch.setattr(
        tarefa_agente.espelho,
        "enviar_entrega",
        lambda caso_id, entrega_id, *, silencioso: chamada.update(
            entrega=entrega_id, silencioso=silencioso
        )
        or True,
    )

    assert tarefa_agente.enviar_entrega_ao_agente.run("caso-1", "entrega-1") is True
    assert chamada == {"caso": "caso-1", "entrega": "entrega-1", "silencioso": False}


def test_reconciliacao_reenfileira_apenas_entrega_pronta_e_nao_enviada(monkeypatch):
    """Só reenfileira o que está pronto E ainda não foi enviado.

    O teste dublava `obter_vinculo_agente` devolvendo `{"enviados": [...]}`, que era
    como a reconciliação sabia o que já tinha ido. A implementação passou a marcar o
    envio na PRÓPRIA entrega (`agente_envio_chave`) e a ler `estado_agente` — o dublê
    virou peça morta, nada mais filtrava "já enviado", e a asserção de 1 recebia 2.
    Aqui a marca de enviado está onde o código de hoje a procura.
    """
    monkeypatch.setattr(tarefa_agente.armazenamento, "listar_casos", lambda: [{"id": "c1"}])
    monkeypatch.setattr(tarefa_agente.armazenamento, "estado_agente", lambda _caso: {})
    monkeypatch.setattr(
        tarefa_agente.armazenamento,
        "listar_entregas",
        lambda _caso: [
            {"id": "e1", "status_proc": "pronto", "agente_envio_chave": None},
            {"id": "e2", "status_proc": "pronto", "agente_envio_chave": "ja-enviada"},
            {"id": "e3", "status_proc": "processando", "agente_envio_chave": None},
        ],
    )
    chamadas = []
    monkeypatch.setattr(
        tarefa_agente.enviar_entrega_ao_agente,
        "apply_async",
        lambda **opcoes: chamadas.append(opcoes),
    )

    assert tarefa_agente.reenfileirar_pendentes.run() == 1
    assert chamadas == [{"args": ("c1", "e1"), "queue": "default", "priority": 6}]


def test_worker_ocr_carrega_modelo_sem_inferencia_no_boot():
    sender = type("Worker", (), {"hostname": "ocr@teste"})()
    with patch("app.ocr_engine.aquecer") as carregar:
        ocr.aquecer_worker_ocr(sender=sender)
    carregar.assert_called_once_with()


def test_worker_de_outra_fila_nao_carrega_ocr():
    sender = type("Worker", (), {"hostname": "background@teste"})()
    with patch("app.ocr_engine.aquecer") as carregar:
        ocr.aquecer_worker_ocr(sender=sender)
    carregar.assert_not_called()


def test_entrega_usa_o_pipeline_do_worker(tmp_path, monkeypatch):
    entrada = tmp_path / "rg.pdf"
    entrada.write_bytes(b"documento")
    item = SimpleNamespace(codigo="DOC.03", tipo_ocr="rg")
    categoria = SimpleNamespace(itens=[item])
    resultado = {"tipo": {"detectado": "rg"}}

    monkeypatch.setattr(ocr.categorias, "obter", lambda _codigo: categoria)
    # `gerar_arquivos_temporarios` vai por nome: o dublê precisa aceitar kwargs.
    monkeypatch.setattr(ocr.pipeline, "processar", lambda *args, **kwargs: resultado)
    monkeypatch.setattr(ocr.casos, "cobre_rg_e_cpf", lambda _resultado: False)
    monkeypatch.setattr(ocr.casos, "tipo_confere", lambda *_args: True)
    monkeypatch.setattr(ocr, "_entregar_ao_agente", lambda *_args: None)
    estados = []
    monkeypatch.setattr(
        ocr.armazenamento,
        "marcar_entrega_processando",
        lambda entrega_id: estados.append((entrega_id, "processando")),
    )
    concluidas = []
    # `concluir_entrega` ganhou `item_codigo`, `origem`, `confianca` e `motivo`, e
    # `ocr.py` passa alguns por nome. Um dublê só com `*args` estourava
    # `TypeError: unexpected keyword argument 'item_codigo'` — e o erro ficava
    # escondido atrás de um `PermissionError` do diretório temporário do pytest.
    monkeypatch.setattr(
        ocr.armazenamento,
        "concluir_entrega",
        lambda *args, **kwargs: concluidas.append((args, kwargs)),
    )

    retorno = ocr.processar_entrega.run(
        "entrega-1", "caso-1", str(entrada), "rg.pdf", "DOC.03", "cat", "pt", False
    )

    assert retorno == {"entrega_id": "entrega-1", "concluida": True}
    assert estados == [("entrega-1", "processando")]

    (args, kwargs), = concluidas
    assert args == ("entrega-1", resultado, True, ["DOC.03"])
    # A entrega passou a registrar TAMBÉM por que foi para aquele item: qual item,
    # se o destino veio da escolha do advogado ou da leitura, com que confiança e
    # com que justificativa. É o que a tela mostra quando o documento muda de item
    # sozinho — sem isso o advogado veria a mudança sem o motivo.
    assert kwargs["item_codigo"] == "DOC.03"
    assert kwargs["origem"] == "escolha"
    assert kwargs["motivo"]


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
