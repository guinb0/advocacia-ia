import asyncio

import httpx
import pytest

from app.investigacao import PedidoInvestigacao, _coletar_cnpj, _texto_json


def test_alvos_sao_normalizados() -> None:
    pedido = PedidoInvestigacao(
        cnpj="12.345.678/0001-90",
        numero_processo="0001234-56.2026.5.08.0001",
        tribunal="trt8",
    )
    assert pedido.cnpj == "12345678000190"
    assert pedido.numero_processo == "00012345620265080001"


def test_rejeita_alvos_invalidos() -> None:
    with pytest.raises(ValueError):
        PedidoInvestigacao(cnpj="123", tribunal="trt8")
    with pytest.raises(ValueError):
        PedidoInvestigacao(numero_processo="123", tribunal="trt8")


def test_texto_json_preserva_rotulos() -> None:
    texto = _texto_json({"razao_social": "EMPRESA X", "qsa": [{"nome": "SÓCIO Y"}]})
    assert "razao_social: EMPRESA X" in texto
    assert "nome: SÓCIO Y" in texto


def test_coleta_cnpj_guarda_procedencia() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "cnpj": "12345678000190", "razao_social": "EMPRESA TESTE",
            "descricao_situacao_cadastral": "ATIVA", "qsa": [],
        })

    async def executar():
        async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http:
            return await _coletar_cnpj(http, "12345678000190")

    evidencia = asyncio.run(executar())[0]
    assert evidencia.fonte == "BrasilAPI/CNPJ"
    assert evidencia.metadados["cnpj"] == "12345678000190"
    assert "EMPRESA TESTE" in evidencia.texto
