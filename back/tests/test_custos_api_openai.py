"""OpenAI no painel de gastos: custo estimado por token e saldo pelo crédito informado."""

import asyncio
import threading
from contextlib import contextmanager
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app import custos_api
from app.rotas import gastos


class _ConexaoFalsa:
    def __init__(self, linha=None):
        self.executados: list[tuple[str, tuple]] = []
        self._linha = linha

    def execute(self, sql, parametros=()):
        self.executados.append((sql, parametros))
        return self

    def fetchone(self):
        return self._linha


def _conectar_falso(conexao):
    @contextmanager
    def conectar(timeout=15):
        yield conexao

    return conectar


# ------------------------------------------------------------------ custo estimado


def test_custo_do_gpt5_mini_conta_a_entrada_em_cache_a_parte():
    uso = {"prompt_tokens": 1000, "completion_tokens": 500, "prompt_tokens_details": {"cached_tokens": 200}}
    custo = custos_api.estimar_custo_openai("gpt-5-mini", uso)
    assert custo == Decimal("0.001205")


def test_modelo_com_data_usa_o_preco_do_modelo_base():
    uso = {"prompt_tokens": 1_000_000, "completion_tokens": 0}
    assert custos_api.estimar_custo_openai("gpt-5-mini-2025-08-07", uso) == Decimal("0.25")


def test_modelo_fora_da_tabela_nao_herda_preco_de_outro(monkeypatch):
    monkeypatch.delenv("OPENAI_PRECO_ENTRADA_1M", raising=False)
    monkeypatch.delenv("OPENAI_PRECO_SAIDA_1M", raising=False)
    assert custos_api.estimar_custo_openai("gpt-5.3-instant", {"prompt_tokens": 10}) is None


def test_preco_do_ambiente_vale_para_modelo_novo(monkeypatch):
    monkeypatch.setenv("OPENAI_PRECO_ENTRADA_1M", "1")
    monkeypatch.setenv("OPENAI_PRECO_SAIDA_1M", "4")
    uso = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    assert custos_api.estimar_custo_openai("gpt-9", uso) == Decimal(5)


def test_registro_da_openai_grava_custo_estimado(monkeypatch):
    conexao = _ConexaoFalsa()
    monkeypatch.setattr(custos_api, "conectar", _conectar_falso(conexao))
    custos_api.registrar_uso("openai", "gpt-5-mini", "chat_peticao", {"prompt_tokens": 1000, "completion_tokens": 500})
    parametros = conexao.executados[0][1]
    assert parametros[2] == "openai"
    assert parametros[8] == Decimal("0.00125")
    assert parametros[9] == 1


def test_outro_fornecedor_sem_custo_nao_ganha_estimativa(monkeypatch):
    conexao = _ConexaoFalsa()
    monkeypatch.setattr(custos_api, "conectar", _conectar_falso(conexao))
    custos_api.registrar_uso("deepseek", "deepseek-chat", "chat_peticao", {"prompt_tokens": 1000})
    parametros = conexao.executados[0][1]
    assert parametros[8] is None
    assert parametros[9] == 0


# ------------------------------------------------------------------ crédito informado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [("25,50", "25.50"), ("US$ 1.234,56", "1234.56"), ("1,234.56", "1234.56"), ("40", "40"), ("", None), ("abc", None)],
)
def test_le_o_valor_do_jeito_que_se_digita(texto, esperado):
    valor = custos_api.ler_valor(texto)
    assert (None if valor is None else str(valor)) == esperado


def test_informar_saldo_guarda_com_quem_informou(monkeypatch):
    conexao = _ConexaoFalsa()
    monkeypatch.setattr(custos_api, "conectar", _conectar_falso(conexao))
    salvo = custos_api.informar_saldo("openai", "25,50", por="Cláudia")
    assert salvo["valor"] == 25.5
    _, parametros = conexao.executados[0]
    assert parametros[1:3] == ("openai", Decimal("25.50"))
    assert parametros[4] == "Cláudia"


@pytest.mark.parametrize(
    ("fornecedor", "valor"),
    [("openrouter", "10"), ("openai", "-1"), ("openai", "nada"), ("openai", "NaN"), ("openai", "200000")],
)
def test_informar_saldo_recusa_o_que_nao_faz_sentido(monkeypatch, fornecedor, valor):
    conexao = _ConexaoFalsa()
    monkeypatch.setattr(custos_api, "conectar", _conectar_falso(conexao))
    with pytest.raises(ValueError):
        custos_api.informar_saldo(fornecedor, valor)
    assert conexao.executados == []


def _so_openai(monkeypatch):
    for provedor in custos_api.PROVEDORES:
        monkeypatch.delenv(provedor["env"], raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-teste")
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
    monkeypatch.setattr(custos_api, "_gastos_por_fornecedor", dict)


def _openai(painel):
    return next(api for api in painel["apis"] if api["id"] == "openai")


def test_sem_credito_informado_o_painel_pede_para_informar(monkeypatch):
    _so_openai(monkeypatch)
    monkeypatch.setattr(custos_api, "_ultimo_saldo_informado", lambda f: None)
    api = _openai(custos_api.painel())
    assert api["saldo_informado"] is True
    assert api["sinal"] == "desconhecido"
    assert "Informe o crédito" in api["mensagem"]


def test_saldo_desce_com_o_gasto_e_avisa_quando_acaba(monkeypatch):
    _so_openai(monkeypatch)
    monkeypatch.setattr(
        custos_api, "_ultimo_saldo_informado",
        lambda f: {"valor_usd": Decimal(50), "informado_em": "2026-09-20T12:00:00+00:00"},
    )
    monkeypatch.setattr(custos_api, "_gasto_local_desde", lambda f, desde: Decimal("45.5"))
    api = _openai(custos_api.painel())
    assert api["saldo"] == 4.5
    assert api["teto"] == 50
    assert api["sinal"] == "critico"
    assert api["fonte_gasto"] == "estimado"
    assert api["gasto_desde_informado"] == 45.5


def test_com_chave_de_administrador_usa_o_gasto_da_openai(monkeypatch):
    _so_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "sk-admin-teste")
    monkeypatch.setattr(
        custos_api, "_ultimo_saldo_informado",
        lambda f: {"valor_usd": Decimal(100), "informado_em": "2026-09-20T12:00:00+00:00"},
    )
    monkeypatch.setattr(custos_api, "_gasto_openai_oficial", lambda chave, desde: Decimal(80))
    monkeypatch.setattr(custos_api, "_gasto_local_desde", lambda f, desde: pytest.fail("não devia usar o local"))
    api = _openai(custos_api.painel())
    assert api["saldo"] == 20
    assert api["sinal"] == "atencao"
    assert api["fonte_gasto"] == "oficial"


def test_falha_na_openai_cai_para_o_gasto_registrado_aqui(monkeypatch):
    _so_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "sk-admin-teste")
    monkeypatch.setattr(
        custos_api, "_ultimo_saldo_informado",
        lambda f: {"valor_usd": Decimal(100), "informado_em": "2026-09-20T12:00:00+00:00"},
    )

    def fora_do_ar(chave, desde):
        raise RuntimeError("403")

    monkeypatch.setattr(custos_api, "_gasto_openai_oficial", fora_do_ar)
    monkeypatch.setattr(custos_api, "_gasto_local_desde", lambda f, desde: Decimal(10))
    api = _openai(custos_api.painel())
    assert api["saldo"] == 90
    assert api["fonte_gasto"] == "estimado"


def test_gasto_oficial_soma_todas_as_paginas(monkeypatch):
    import httpx

    paginas = [
        {"data": [{"results": [{"amount": {"value": 1.5}}, {"amount": {"value": "0.25"}}]}], "has_more": True, "next_page": "p2"},
        {"data": [{"results": [{"amount": {"value": 3}}]}], "has_more": False, "next_page": None},
    ]
    pedidos = []

    class Resposta:
        def __init__(self, corpo):
            self._corpo = corpo

        def raise_for_status(self):
            return None

        def json(self):
            return self._corpo

    def get(url, headers, params, timeout):
        pedidos.append(dict(params))
        return Resposta(paginas[len(pedidos) - 1])

    monkeypatch.setattr(httpx, "get", get)
    from datetime import datetime, timezone

    total = custos_api._gasto_openai_oficial("sk-admin", datetime(2026, 9, 20, tzinfo=timezone.utc))
    assert total == Decimal("4.75")
    assert "page" not in pedidos[0] and pedidos[1]["page"] == "p2"


def test_rota_devolve_erro_em_portugues(monkeypatch):
    class Usuario:
        nome = "Cláudia"

    monkeypatch.setattr(custos_api, "conectar", _conectar_falso(_ConexaoFalsa()))
    with pytest.raises(HTTPException) as erro:
        asyncio.run(gastos.informar_saldo_da_api("openai", gastos.SaldoInformado(valor="-3"), usuario=Usuario()))
    assert erro.value.status_code == 400
    assert "dólares" in erro.value.detail
    salvo = asyncio.run(gastos.informar_saldo_da_api("openai", gastos.SaldoInformado(valor="12,00"), usuario=Usuario()))
    assert salvo["valor"] == 12.0


# ------------------------------------------------------------------ o chat da petição


def test_chat_pede_o_consumo_e_grava_na_conta_da_openai(monkeypatch):
    from app.agente import chat_peticao

    monkeypatch.setenv("OPENAI_API_KEY", "sk-teste")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "gpt-5-mini")
    enviados = []

    class Fluxo:
        status_code = 200

        def iter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"Olá"}}]}'
            yield 'data: {"choices":[],"usage":{"prompt_tokens":100,"completion_tokens":20,"total_tokens":120}}'
            yield "data: [DONE]"

    @contextmanager
    def stream(metodo, url, headers, json, timeout):
        enviados.append(json)
        yield Fluxo()

    gravados = []
    gravou = threading.Event()

    def registrar_uso(fornecedor, modelo, operacao, uso, *, latencia_ms=None):
        gravados.append((fornecedor, modelo, operacao, uso))
        gravou.set()

    monkeypatch.setattr(chat_peticao.httpx, "stream", stream)
    monkeypatch.setattr(chat_peticao.custos_api, "registrar_uso", registrar_uso)
    eventos = list(chat_peticao._transmitir([{"role": "user", "content": "oi"}], ferramentas=False))

    assert eventos[-1]["mensagem"]["content"] == "Olá"
    assert enviados[0]["stream_options"] == {"include_usage": True}
    assert gravou.wait(2)
    assert gravados[0][:3] == ("openai", "gpt-5-mini", "chat_peticao")
    assert gravados[0][3]["prompt_tokens"] == 100


def test_provedor_que_recusa_o_pedido_de_consumo_ainda_responde(monkeypatch):
    from app.agente import chat_peticao

    monkeypatch.setenv("OPENAI_API_KEY", "sk-teste")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    enviados = []

    class Recusa:
        status_code = 400
        text = "unknown field stream_options"

        def read(self):
            return b""

    class Fluxo:
        status_code = 200

        def iter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"ok"}}]}'
            yield "data: [DONE]"

    @contextmanager
    def stream(metodo, url, headers, json, timeout):
        enviados.append(dict(json))
        yield Recusa() if len(enviados) == 1 else Fluxo()

    monkeypatch.setattr(chat_peticao.httpx, "stream", stream)
    monkeypatch.setattr(chat_peticao.custos_api, "registrar_uso", lambda *a, **k: None)
    eventos = list(chat_peticao._transmitir([{"role": "user", "content": "oi"}], ferramentas=False))

    assert eventos[-1]["mensagem"]["content"] == "ok"
    assert "stream_options" in enviados[0] and "stream_options" not in enviados[1]
