from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from app import whatsapp


def test_link_zapsign_automatico_so_vai_para_parte_externa(monkeypatch):
    reservas: list[str] = []
    enviados: list[tuple[str, str]] = []

    def reservar(chave, _tipo, _destino, _caso_id):
        reservas.append(chave)
        return True

    monkeypatch.setattr(whatsapp.automacoes_whatsapp, "reservar", reservar)
    monkeypatch.setattr(whatsapp.automacoes_whatsapp, "finalizar", lambda *_args: None)

    async def enviar(numero, texto):
        enviados.append((numero, texto))

    monkeypatch.setattr(whatsapp, "_enviar_texto", enviar)
    registro = {
        "id": "assinatura-1", "caso_id": "caso-1", "nome": "Procuração — Maria",
        "signatarios": [
            {"token": "cliente", "nome": "Maria", "telefone": "61999999999",
             "papel": "cliente", "url_assinatura": "https://zap.exemplo/cliente"},
            {"token": "escritorio", "nome": "Advogada", "telefone": "61988888888",
             "papel": "escritório", "url_assinatura": "https://zap.exemplo/escritorio"},
        ],
    }

    assert asyncio.run(whatsapp.enviar_links_assinatura_automaticos(registro)) == 1
    assert reservas == ["zapsign:assinatura-1:cliente"]
    assert enviados[0][0] == "5561999999999"
    assert "https://zap.exemplo/cliente" in enviados[0][1]


def test_avaliacao_google_nao_duplica(monkeypatch):
    monkeypatch.setattr(whatsapp.automacoes_whatsapp, "reservar", lambda *_args: False)
    envio = AsyncMock()
    monkeypatch.setattr(whatsapp, "_enviar_texto", envio)

    resposta = asyncio.run(
        whatsapp.enviar_avaliacao_google(whatsapp.Destinatario(telefone="61999999999"))
    )

    assert resposta == {"enviado": False, "ja_enviado": True}
    envio.assert_not_awaited()


def test_cobranca_recalcula_o_texto_no_momento_do_envio(monkeypatch):
    config = {
        "caso_id": "caso-1", "telefone": "5561999999999", "intervalo_dias": 3,
        "incluir_opcionais": False,
    }
    monkeypatch.setattr(whatsapp.automacoes_whatsapp, "listar_cobrancas_vencidas", lambda: [config])
    monkeypatch.setattr(
        whatsapp.armazenamento, "obter_caso_com_segredos",
        lambda _caso_id: {"portal_token": "portal-seguro-123"},
    )
    monkeypatch.setattr(
        whatsapp.casos, "montar_pedido",
        lambda *_args: {
            "texto": "Agora falta somente o RG", "faltando_obrigatorios": ["RG"],
            "faltando_opcionais": [], "reenviar": [],
        },
    )
    enviado: list[str] = []
    monkeypatch.setattr(whatsapp, "_enviar_texto_sync", lambda _numero, texto: enviado.append(texto))
    monkeypatch.setattr(whatsapp.automacoes_whatsapp, "registrar_resultado_cobranca", lambda *_args: None)

    assert whatsapp.processar_cobrancas_documentos() == 1
    assert len(enviado) == 1
    assert "Agora falta somente o RG" in enviado[0]
    assert enviado[0].endswith("/portal/portal-seguro-123")
