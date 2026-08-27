"""O documento que ficava "Lendo" para sempre.

O acidente que estes testes travam: o worker de OCR morreu com o resto do sistema
no ar, e toda entrega criada depois disso parou em `na_fila`. Não havia timeout,
nova tentativa nem erro — a tela dizia "aguardando a vez na fila de leitura"
enquanto não existia fila andando, e ficava assim indefinidamente.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app import casos
from app.celery_app import celery_app
from app.tasks import manutencao


def _entrega(minutos_atras: int, **campos):
    criado = datetime.now(timezone.utc) - timedelta(minutes=minutos_atras)
    return {
        "id": "e1",
        "caso_id": "c1",
        "item_codigo": "DOC.03",
        "arquivo": "CNH.jpg",
        "caminho": "",
        "categoria": "cat",
        "status_proc": "na_fila",
        "criado_em": criado.isoformat(timespec="seconds"),
        "itens_atendidos": ["DOC.03"],
        **campos,
    }


def test_beat_tem_a_ronda_das_entregas_travadas():
    assert "recuperar-entregas-travadas" in celery_app.conf.beat_schedule


# ------------------------------------------------------------------ o alerta


def test_alerta_de_fila_vira_aviso_quando_a_espera_passa_do_normal():
    item = SimpleNamespace(codigo="DOC.03", nome="RG", tipo_ocr="rg")

    recente = casos._alertas_da_entrega(_entrega(minutos_atras=0), item)
    assert recente == ["Documento recebido e aguardando a vez na fila de leitura."]

    parada = casos._alertas_da_entrega(
        _entrega(minutos_atras=casos.MINUTOS_ESPERA_ANORMAL + 5), item
    )
    assert "mais que o normal" in parada[0]
    assert "fora do ar" in parada[0]


def test_criado_em_ilegivel_nao_vira_alarme():
    item = SimpleNamespace(codigo="DOC.03", nome="RG", tipo_ocr="rg")
    entrega = _entrega(minutos_atras=0, criado_em="nao-e-uma-data")
    assert casos._alertas_da_entrega(entrega, item) == [
        "Documento recebido e aguardando a vez na fila de leitura."
    ]


# ------------------------------------------------------- a ronda que recupera


def _sem_travadas(monkeypatch, travadas):
    monkeypatch.setattr(
        manutencao.armazenamento, "entregas_travadas", lambda _minutos: travadas
    )


def test_reenfileira_a_entrega_orfa_quando_o_leitor_esta_no_ar(monkeypatch, tmp_path):
    arquivo = tmp_path / "CNH.jpg"
    arquivo.write_bytes(b"imagem")
    _sem_travadas(monkeypatch, [_entrega(minutos_atras=30, caminho="/caminho/da/api")])
    monkeypatch.setattr(
        manutencao, "_leitor_de_documentos_ativo", lambda: (True, set())
    )
    # Em container o caminho gravado pela API não existe aqui; quem resolve isso
    # é a cópia durável no banco. É esse caminho que precisa chegar ao worker.
    monkeypatch.setattr(
        manutencao.armazenamento, "caminho_duravel_da_entrega", lambda _id: arquivo
    )

    envios = []
    monkeypatch.setattr(
        manutencao.armazenamento, "falhar_entrega", lambda *a: envios.append(("erro", a))
    )
    from app.tasks import ocr

    monkeypatch.setattr(
        ocr.processar_entrega,
        "apply_async",
        lambda **kwargs: envios.append(("fila", kwargs)),
    )

    assert manutencao.recuperar_entregas_travadas.run() == 1
    tipo, kwargs = envios[0]
    assert tipo == "fila"
    assert kwargs["queue"] == "gpu_background"
    assert kwargs["args"][0] == "e1"
    assert kwargs["args"][2] == str(arquivo)  # o caminho restaurado, não o da API
    assert kwargs["args"][5] == "cat"  # a categoria vem do caso, não do chute


def test_sem_worker_consumindo_nao_empilha_mensagem(monkeypatch, tmp_path):
    """Reenfileirar com o leitor morto só acumularia cópias a cada 5 minutos."""
    arquivo = tmp_path / "CNH.jpg"
    arquivo.write_bytes(b"imagem")
    _sem_travadas(monkeypatch, [_entrega(minutos_atras=30, caminho=str(arquivo))])
    monkeypatch.setattr(
        manutencao, "_leitor_de_documentos_ativo", lambda: (False, set())
    )

    from app.tasks import ocr

    monkeypatch.setattr(
        ocr.processar_entrega,
        "apply_async",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("não devia enfileirar")),
    )

    assert manutencao.recuperar_entregas_travadas.run() == 0


def test_entrega_em_leitura_agora_nao_e_reenfileirada(monkeypatch, tmp_path):
    """Demorar não é estar travada: o worker está com ela na mão."""
    arquivo = tmp_path / "CNH.jpg"
    arquivo.write_bytes(b"imagem")
    _sem_travadas(
        monkeypatch,
        [_entrega(minutos_atras=30, caminho=str(arquivo), status_proc="processando")],
    )
    monkeypatch.setattr(
        manutencao, "_leitor_de_documentos_ativo", lambda: (True, {"e1"})
    )

    from app.tasks import ocr

    monkeypatch.setattr(
        ocr.processar_entrega,
        "apply_async",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("não devia enfileirar")),
    )

    assert manutencao.recuperar_entregas_travadas.run() == 0


def test_arquivo_sumido_do_disco_E_do_banco_vira_erro(monkeypatch, tmp_path):
    """Só quando nem o banco tem o binário é que não há mais o que reler."""
    _sem_travadas(
        monkeypatch,
        [_entrega(minutos_atras=30, caminho=str(tmp_path / "nao-existe.jpg"))],
    )
    monkeypatch.setattr(
        manutencao, "_leitor_de_documentos_ativo", lambda: (True, set())
    )
    monkeypatch.setattr(
        manutencao.armazenamento, "caminho_duravel_da_entrega", lambda _id: None
    )

    falhas = []
    monkeypatch.setattr(
        manutencao.armazenamento,
        "falhar_entrega",
        lambda entrega_id, mensagem: falhas.append((entrega_id, mensagem)),
    )

    assert manutencao.recuperar_entregas_travadas.run() == 0
    assert falhas[0][0] == "e1"
    assert "reenvio" in falhas[0][1]


# ------------------------------------------- o anexo que não está neste disco


def test_worker_le_do_banco_quando_o_caminho_da_api_nao_existe(monkeypatch, tmp_path):
    """Em container, quem gravou o upload foi a API — noutro sistema de arquivos."""
    from app.tasks import ocr

    copia = tmp_path / "restaurado.jpg"
    copia.write_bytes(b"documento inteiro")
    monkeypatch.setattr(
        ocr.armazenamento, "caminho_duravel_da_entrega", lambda _id: copia
    )

    assert ocr._ler_anexo("e1", "/disco/da/api/nao-existe.jpg") == b"documento inteiro"


def test_disco_local_vence_quando_o_arquivo_esta_ali(monkeypatch, tmp_path):
    """O caminho bom não paga viagem ao banco."""
    from app.tasks import ocr

    local = tmp_path / "aqui.jpg"
    local.write_bytes(b"do disco")

    def nao_deve_ser_chamado(_id):
        raise AssertionError("não devia consultar o banco")

    monkeypatch.setattr(
        ocr.armazenamento, "caminho_duravel_da_entrega", nao_deve_ser_chamado
    )
    assert ocr._ler_anexo("e1", str(local)) == b"do disco"


def test_sem_disco_e_sem_banco_falha_rapido_sem_retentativa(monkeypatch):
    """`OSError` seria repetido 3x por `autoretry_for`; isto não melhora esperando."""
    from app.tasks import ocr

    monkeypatch.setattr(ocr.armazenamento, "caminho_duravel_da_entrega", lambda _id: None)
    try:
        ocr._ler_anexo("e1", "/nao/existe.jpg")
    except Exception as exc:
        assert not isinstance(exc, OSError)
        assert "reenvio" in str(exc)
    else:
        raise AssertionError("devia ter levantado")


# ------------------------------------------- o diagnóstico visível de fora


def _medir_leitura(monkeypatch, filas_por_worker, na_fila):
    """Roda `_estado_da_leitura` com broker e workers falsos, sem cache velho."""
    from app import main

    main._ESTADO_LEITURA.update(medido_em=0.0, dados=None)

    class RedisFalso:
        def llen(self, _nome):
            return na_fila

    monkeypatch.setattr(
        main.celery_app.control,
        "inspect",
        lambda **_k: type("I", (), {"active_queues": lambda _s: filas_por_worker})(),
    )
    import redis

    monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda _c, *a, **k: RedisFalso()))
    resultado = main._estado_da_leitura()
    main._ESTADO_LEITURA.update(medido_em=0.0, dados=None)
    return resultado


def test_saude_denuncia_leitor_ausente(monkeypatch):
    """O caso real: worker de trabalho leve no ar, ninguém em 'gpu_background'."""
    estado = _medir_leitura(
        monkeypatch, {"background@x": [{"name": "default"}, {"name": "low"}]}, na_fila=1
    )
    assert estado["leitor"] == "fora do ar"
    assert estado["esperando_na_fila"] == 1
    assert "esperando indefinidamente" in estado["diagnostico"]


def test_saude_separa_worker_no_ar_de_worker_no_redis_certo(monkeypatch):
    """Worker consumindo a fila E mensagem parada = ele está noutro Redis."""
    estado = _medir_leitura(
        monkeypatch, {"ocr@x": [{"name": "gpu_background"}]}, na_fila=3
    )
    assert estado["leitor"] == "no ar"
    assert "noutro Redis" in estado["diagnostico"]


def test_saude_silenciosa_quando_esta_tudo_certo(monkeypatch):
    estado = _medir_leitura(
        monkeypatch, {"ocr@x": [{"name": "gpu_background"}]}, na_fila=0
    )
    assert estado["leitor"] == "no ar"
    assert "diagnostico" not in estado


def test_broker_fora_do_ar_responde_que_nao_ha_leitor(monkeypatch):
    """Sem conseguir perguntar, a ronda não mexe em nada."""

    def explode(*_a, **_k):
        raise OSError("broker fora do ar")

    monkeypatch.setattr(celery_app.control, "inspect", explode)
    assert manutencao._leitor_de_documentos_ativo() == (False, set())
