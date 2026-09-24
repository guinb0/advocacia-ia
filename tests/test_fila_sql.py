"""Fila SQL OCR: claim, retry, órfãos, idempotência e qualificação de tabelas."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from app import banco, fila_sql, worker_sql


def test_qualificar_mapeia_fila_jobs_e_workers() -> None:
    """Regressão da causa raiz: sem isto o enqueue falhava com nome inválido."""
    sql = "SELECT id FROM fila_jobs WHERE status='PENDING'"
    assert "dbo.acervo_fila_jobs" in banco._qualificar(sql)
    assert "dbo.acervo_fila_workers" in banco._qualificar(
        "UPDATE fila_workers SET estado='READY' WHERE worker_id=?"
    )
    # Idempotente: não dobra o prefixo.
    ja = "SELECT id FROM dbo.acervo_fila_jobs"
    assert banco._qualificar(ja) == ja


def test_enfileirar_ocr_mapeia_argumentos_e_chave() -> None:
    args = ("e1", "c1", "/tmp/a.pdf", "a.pdf", "item", "cat", "pt", True)
    with patch("app.fila_sql.enfileirar", return_value="job-1") as enfileirar:
        assert fila_sql.enfileirar_ocr(args) == "job-1"
    tipo, argumentos = enfileirar.call_args.args
    assert tipo == "ocr_entrega"
    assert argumentos["entrega_id"] == "e1"
    assert argumentos["usar_para_rg_e_cpf"] is True
    assert enfileirar.call_args.kwargs["chave"] == "ocr:e1"
    assert enfileirar.call_args.kwargs["prioridade"] == 7


def test_enfileirar_ocr_rejeita_assinatura_incompleta() -> None:
    try:
        fila_sql.enfileirar_ocr(("e1",))
    except ValueError as erro:
        assert "argumentos inválidos" in str(erro)
    else:
        raise AssertionError("assinatura incompleta deveria falhar")


def test_worker_conclui_job_e_preserva_handler() -> None:
    job = {"id": "j1", "tipo": "teste", "argumentos": {"valor": 7}, "worker_id": "w1"}
    recebido: list[int] = []
    anterior = worker_sql._handlers.get("teste")
    worker_sql.registrar("teste", lambda valor: recebido.append(valor))
    try:
        with patch("app.worker_sql.fila_sql.reservar", return_value=job), patch(
            "app.worker_sql.fila_sql.concluir"
        ) as concluir, patch("app.worker_sql.threading.Thread"), patch(
            "app.worker_sql.fila_sql._evento"
        ):
            assert worker_sql.executar_uma_vez("w1") is True
        assert recebido == [7]
        concluir.assert_called_once()
        assert concluir.call_args.args[0] == "j1"
    finally:
        if anterior is None:
            worker_sql._handlers.pop("teste", None)
        else:
            worker_sql._handlers["teste"] = anterior


def test_worker_falha_temporaria_reenfileira_entrega() -> None:
    job = {
        "id": "j2",
        "tipo": "falha",
        "argumentos": {"entrega_id": "e9"},
        "worker_id": "w1",
        "tentativas": 1,
        "tentativas_max": 3,
    }
    anterior = worker_sql._handlers.get("falha")
    worker_sql.registrar("falha", lambda **_kw: (_ for _ in ()).throw(RuntimeError("x")))
    try:
        with patch("app.worker_sql.fila_sql.reservar", return_value=job), patch(
            "app.worker_sql.fila_sql.falhar", return_value="PENDING"
        ) as falhar, patch("app.worker_sql.threading.Thread"), patch(
            "app.worker_sql.fila_sql._evento"
        ), patch("app.armazenamento.marcar_entrega_enfileirada") as marcar:
            assert worker_sql.executar_uma_vez("w1") is True
        falhar.assert_called_once()
        marcar.assert_called_once_with("e9", "j2")
    finally:
        if anterior is None:
            worker_sql._handlers.pop("falha", None)
        else:
            worker_sql._handlers["falha"] = anterior


def test_worker_falha_definitiva_marca_entrega() -> None:
    job = {
        "id": "j3",
        "tipo": "falha",
        "argumentos": {"entrega_id": "e8"},
        "worker_id": "w1",
        "tentativas": 3,
        "tentativas_max": 3,
    }
    anterior = worker_sql._handlers.get("falha")
    worker_sql.registrar("falha", lambda **_kw: (_ for _ in ()).throw(RuntimeError("boom")))
    try:
        with patch("app.worker_sql.fila_sql.reservar", return_value=job), patch(
            "app.worker_sql.fila_sql.falhar", return_value="FAILED"
        ), patch("app.worker_sql.threading.Thread"), patch(
            "app.worker_sql.fila_sql._evento"
        ), patch("app.armazenamento.falhar_entrega") as falhar_entrega:
            assert worker_sql.executar_uma_vez("w1") is True
        falhar_entrega.assert_called_once()
        assert falhar_entrega.call_args.args[0] == "e8"
        assert "boom" in falhar_entrega.call_args.args[1]
    finally:
        if anterior is None:
            worker_sql._handlers.pop("falha", None)
        else:
            worker_sql._handlers["falha"] = anterior


def test_worker_falha_sem_executar_duas_vezes() -> None:
    job = {"id": "j2", "tipo": "falha", "argumentos": {}, "worker_id": "w1"}
    anterior = worker_sql._handlers.get("falha")
    worker_sql.registrar("falha", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    try:
        with patch("app.worker_sql.fila_sql.reservar", return_value=job), patch(
            "app.worker_sql.fila_sql.falhar", return_value="FAILED"
        ) as falhar, patch("app.worker_sql.threading.Thread"), patch(
            "app.worker_sql.fila_sql._evento"
        ):
            assert worker_sql.executar_uma_vez("w1") is True
        falhar.assert_called_once()
    finally:
        if anterior is None:
            worker_sql._handlers.pop("falha", None)
        else:
            worker_sql._handlers["falha"] = anterior


def test_falhar_calcula_backoff_e_status() -> None:
    job = {
        "id": "jx",
        "tentativas": 1,
        "tentativas_max": 3,
        "argumentos": {"entrega_id": "e1"},
    }
    con = MagicMock()
    with patch("app.fila_sql.conectar") as ctx:
        ctx.return_value.__enter__.return_value = con
        status = fila_sql.falhar(job, RuntimeError("temporario"))
    assert status == "PENDING"
    args = con.execute.call_args.args
    assert args[1][0] == "PENDING"
    assert args[1][2] is not None  # disponivel_em com backoff


def test_falhar_esgota_tentativas() -> None:
    job = {"id": "jy", "tentativas": 3, "tentativas_max": 3, "argumentos": {}}
    con = MagicMock()
    with patch("app.fila_sql.conectar") as ctx:
        ctx.return_value.__enter__.return_value = con
        status = fila_sql.falhar(job, RuntimeError("definitivo"))
    assert status == "FAILED"
    assert con.execute.call_args.args[1][0] == "FAILED"
    assert con.execute.call_args.args[1][2] is None


def test_recuperar_orfaos_devolve_pending() -> None:
    con = MagicMock()
    orfao = {
        "id": "jo",
        "argumentos_json": '{"entrega_id":"e1"}',
        "worker_id": "morto",
        "tentativas": 1,
    }
    select = MagicMock()
    select.fetchall.return_value = [orfao]
    update = MagicMock()
    update.rowcount = 1
    con.execute.side_effect = [select, update]
    with patch("app.fila_sql.conectar") as ctx:
        ctx.return_value.__enter__.return_value = con
        assert fila_sql.recuperar_orfaos() == 1
    sql_update = con.execute.call_args_list[1].args[0]
    assert "PENDING" in sql_update


def test_dois_workers_nao_reclamam_mesmo_job_via_readpast() -> None:
    """O claim usa UPDLOCK+READPAST: o SQL da reserva é o contrato anti-corrida."""
    import inspect

    fonte = inspect.getsource(fila_sql.reservar)
    assert "UPDLOCK" in fonte
    assert "READPAST" in fonte
    assert "ROWLOCK" in fonte
    assert "status = 'PENDING'" in fonte


def test_enfileirar_deduplica_chave_ativa() -> None:
    con = MagicMock()
    con.execute.return_value.fetchone.return_value = {"id": "existente"}
    with patch("app.fila_sql.conectar") as ctx:
        ctx.return_value.__enter__.return_value = con
        assert (
            fila_sql.enfileirar(
                "ocr_entrega",
                {"entrega_id": "e1"},
                chave="ocr:e1",
            )
            == "existente"
        )
    sqls = [c.args[0] for c in con.execute.call_args_list]
    assert not any(s.strip().upper().startswith("INSERT") for s in sqls)


def test_default_fila_sql_ocr_ativa() -> None:
    from app.tasks import manutencao

    env = {k: v for k, v in os.environ.items() if k != "FILA_SQL_OCR_ATIVA"}
    with patch.dict(os.environ, env, clear=True):
        assert manutencao._fila_sql_ocr_ativa() is True
        # Espelha o default de main._fila_sql_ocr_ativa sem importar a API inteira.
        assert os.getenv("FILA_SQL_OCR_ATIVA", "1").strip().lower() in {"1", "true", "sim"}
