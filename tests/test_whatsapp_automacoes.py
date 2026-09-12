from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import httpx

from app import whatsapp
from app import automacoes_whatsapp


def test_nome_da_instancia_com_espaco_vai_codificado():
    assert whatsapp._url_instancia(
        "https://evolution.exemplo", "message/sendText", "Advocacia LM"
    ) == "https://evolution.exemplo/message/sendText/Advocacia%20LM"


def test_instancia_oficial_recupera_configuracao_antiga(monkeypatch):
    monkeypatch.setenv("EVOLUTION_INSTANCE", "instancia-antiga")
    monkeypatch.setattr(whatsapp, "INSTANCIA_OFICIAL", "Advocacia LM")

    assert whatsapp._instancias_candidatas() == ["instancia-antiga", "Advocacia LM"]


def test_envio_tenta_instancia_oficial_quando_configurada_nao_existe(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "https://evolution.exemplo")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "instancia-antiga")
    monkeypatch.setattr(whatsapp, "INSTANCIA_OFICIAL", "Advocacia LM")
    urls: list[str] = []

    class ClienteFalso:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **_kwargs):
            urls.append(url)
            requisicao = httpx.Request("POST", url)
            return httpx.Response(404 if len(urls) == 1 else 201, request=requisicao)

    monkeypatch.setattr(whatsapp.httpx, "AsyncClient", ClienteFalso)

    asyncio.run(whatsapp._enviar_texto("5561999999999", "convite"))

    assert urls == [
        "https://evolution.exemplo/message/sendText/instancia-antiga",
        "https://evolution.exemplo/message/sendText/Advocacia%20LM",
    ]


def test_erro_da_evolution_e_explicito_sem_cravar_causa_nem_expor_resposta():
    requisicao = httpx.Request("POST", "https://evolution.exemplo/message/sendText/instancia")
    resposta = httpx.Response(401, request=requisicao, text="apikey secreta recusada")
    erro = httpx.HTTPStatusError("Unauthorized", request=requisicao, response=resposta)

    mensagem = whatsapp._mensagem_erro_evolution(erro, "geração do QR")

    assert "geração do QR recebeu HTTP 401" in mensagem
    assert "EVO-DIAG-2-HTTP-401" in mensagem
    assert "não prova erro na chave" in mensagem
    assert "secreta" not in mensagem


def test_contrato_antigo_de_intervalo_continua_usando_dias():
    config = whatsapp.ConfiguracaoCobranca(intervalo_dias=3)

    assert config.intervalo_horas is None


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


def test_avaliacao_google_reenvia_quando_forcado(monkeypatch):
    # Com o cliente na chamada o atendente pode pedir o link de novo: `forcar`
    # atravessa a dedup do envio já concluído e a mensagem sai outra vez.
    capturado = {}

    def reservar(chave, tipo, destino, caso_id=None, forcar=False):
        capturado["forcar"] = forcar
        return True

    monkeypatch.setattr(whatsapp.automacoes_whatsapp, "reservar", reservar)
    monkeypatch.setattr(whatsapp.automacoes_whatsapp, "finalizar", lambda *_a, **_k: None)
    envio = AsyncMock()
    monkeypatch.setattr(whatsapp, "_enviar_texto", envio)

    resposta = asyncio.run(
        whatsapp.enviar_avaliacao_google(
            whatsapp.Destinatario(telefone="61999999999", forcar=True)
        )
    )

    assert resposta == {"enviado": True, "ja_enviado": False}
    assert capturado["forcar"] is True
    envio.assert_awaited_once()


def test_telefone_da_cobranca_vem_do_caso(monkeypatch):
    monkeypatch.setattr(
        automacoes_whatsapp.armazenamento,
        "obter_caso",
        lambda _caso_id: {"telefone": "(61) 99999-0000"},
    )

    assert automacoes_whatsapp.telefone_do_caso("caso-1") == "(61) 99999-0000"


def test_telefone_da_cobranca_cai_para_signatario_antigo(monkeypatch):
    monkeypatch.setattr(
        automacoes_whatsapp.armazenamento,
        "obter_caso",
        lambda _caso_id: {"cliente": "Maria Silva", "telefone": ""},
    )
    monkeypatch.setattr(
        automacoes_whatsapp.armazenamento,
        "obter_qualificacao",
        lambda _caso_id: {"cpf": "123.456.789-00"},
    )
    monkeypatch.setattr(
        automacoes_whatsapp.armazenamento,
        "listar_assinaturas",
        lambda **_kwargs: [
            {
                "signatarios": [
                    {"papel": "cliente", "telefone": "61999990000"},
                ],
            }
        ],
    )

    assert automacoes_whatsapp.telefone_do_caso("caso-1") == "61999990000"


def test_telefone_nao_e_inferido_por_nome_sem_cpf(monkeypatch):
    consultas: list[dict[str, str]] = []
    monkeypatch.setattr(
        automacoes_whatsapp.armazenamento,
        "obter_caso",
        lambda _caso_id: {"cliente": "Nome Homônimo", "telefone": ""},
    )
    monkeypatch.setattr(
        automacoes_whatsapp.armazenamento,
        "obter_qualificacao",
        lambda _caso_id: {"cpf": ""},
    )

    def listar_assinaturas(**filtros):
        consultas.append(filtros)
        return []

    monkeypatch.setattr(
        automacoes_whatsapp.armazenamento,
        "listar_assinaturas",
        listar_assinaturas,
    )

    assert automacoes_whatsapp.telefone_do_caso("caso-1") == ""
    assert consultas == [{"caso_id": "caso-1"}]


def test_cobranca_recalcula_o_texto_no_momento_do_envio(monkeypatch):
    config = {
        "caso_id": "caso-1", "telefone": "5561999999999", "intervalo_dias": 3,
        "intervalo_horas": 24, "max_envios_dia": 1, "incluir_opcionais": False,
    }
    monkeypatch.setattr(whatsapp.automacoes_whatsapp, "listar_cobrancas_vencidas", lambda: [config])
    monkeypatch.setattr(
        whatsapp.armazenamento, "obter_caso_com_segredos",
        lambda _caso_id: {"portal_token": "portal-seguro-123"},
    )
    monkeypatch.setattr(
        whatsapp.casos, "documentos_pendentes_do_caso",
        lambda *_args: {
            "caso": {"cliente": "Maria Silva"},
            "pendentes": [{"codigo": "rg", "nome": "RG", "status": "pendente"}],
        },
    )
    enviado: list[str] = []
    monkeypatch.setattr(whatsapp.automacoes_whatsapp, "envios_de_cobranca_hoje", lambda _caso_id: 0)
    monkeypatch.setattr(whatsapp.automacoes_whatsapp, "reservar", lambda *_args: True)
    monkeypatch.setattr(whatsapp.automacoes_whatsapp, "finalizar", lambda *_args: None)
    monkeypatch.setattr(whatsapp, "_enviar_texto_sync", lambda _numero, texto: enviado.append(texto))
    monkeypatch.setattr(whatsapp.automacoes_whatsapp, "registrar_resultado_cobranca", lambda *_args, **_kwargs: None)

    assert whatsapp.processar_cobrancas_documentos() == 1
    assert len(enviado) == 1
    assert "RG" in enviado[0]
    assert "não envie documentos por esta conversa de WhatsApp" in enviado[0]
    assert enviado[0].endswith("/portal/portal-seguro-123")


def test_mensagem_cobranca_limita_dados_e_orienta_portal():
    texto = whatsapp._mensagem_cobranca_documentos(
        cliente="Maria Silva",
        pendentes=[
            {"codigo": "rg", "nome": "RG"},
            {"codigo": "cpf", "nome": "CPF"},
        ],
        url_portal="https://app.exemplo/portal/token",
        chave_variante="caso-1",
    )

    assert "RG" in texto
    assert "CPF" in texto
    assert "https://app.exemplo/portal/token" in texto
    assert "não envie documentos por esta conversa de WhatsApp" in texto


def test_cobranca_respeita_limite_diario(monkeypatch):
    config = {
        "caso_id": "caso-1", "telefone": "5561999999999", "intervalo_dias": 1,
        "intervalo_horas": 6, "max_envios_dia": 2, "incluir_opcionais": False,
    }
    reagendados: list[str] = []
    envio = []

    monkeypatch.setattr(whatsapp.automacoes_whatsapp, "listar_cobrancas_vencidas", lambda: [config])
    monkeypatch.setattr(
        whatsapp.armazenamento, "obter_caso_com_segredos",
        lambda _caso_id: {"portal_token": "portal-seguro-123"},
    )
    monkeypatch.setattr(
        whatsapp.casos, "documentos_pendentes_do_caso",
        lambda *_args: {"caso": {"cliente": "Maria"}, "pendentes": [{"nome": "RG"}]},
    )
    monkeypatch.setattr(whatsapp.automacoes_whatsapp, "envios_de_cobranca_hoje", lambda _caso_id: 2)
    monkeypatch.setattr(whatsapp.automacoes_whatsapp, "reagendar_cobranca_para_amanha", reagendados.append)
    monkeypatch.setattr(whatsapp.automacoes_whatsapp, "reservar", lambda *_args: True)
    monkeypatch.setattr(whatsapp, "_enviar_texto_sync", lambda *_args: envio.append(True))

    assert whatsapp.processar_cobrancas_documentos() == 0
    assert reagendados == ["caso-1"]
    assert envio == []
