from __future__ import annotations

from unittest.mock import patch

from app import fila_sql, worker_sql


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
        ) as concluir, patch("app.worker_sql.threading.Thread"):
            assert worker_sql.executar_uma_vez("w1") is True
        assert recebido == [7]
        concluir.assert_called_once_with("j1")
    finally:
        if anterior is None:
            worker_sql._handlers.pop("teste", None)
        else:
            worker_sql._handlers["teste"] = anterior


def test_worker_falha_sem_executar_duas_vezes() -> None:
    job = {"id": "j2", "tipo": "falha", "argumentos": {}, "worker_id": "w1"}
    anterior = worker_sql._handlers.get("falha")
    worker_sql.registrar("falha", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    try:
        with patch("app.worker_sql.fila_sql.reservar", return_value=job), patch(
            "app.worker_sql.fila_sql.falhar"
        ) as falhar, patch("app.worker_sql.threading.Thread"):
            assert worker_sql.executar_uma_vez("w1") is True
        falhar.assert_called_once()
    finally:
        if anterior is None:
            worker_sql._handlers.pop("falha", None)
        else:
            worker_sql._handlers["falha"] = anterior
