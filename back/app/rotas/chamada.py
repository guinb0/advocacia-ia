"""Chamada de vídeo do atendimento (Jitsi e sinalização P2P)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import (
    APIRouter,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)

from .. import chamada
from .comum import URL_PORTAL, log

roteador = APIRouter()


# --------------------------------------------------- chamada de voz (WebRTC)


def gerar_token_jitsi(sala: str) -> str | None:
    """Gera JWT HS256 para o Jitsi aceitar a conexão — quando ele pede um.

    O Jitsi valida tokens com aud/iss/sub = JITSI_JWT_APP_ID e room = nome da sala.
    O secret é compartilhado com o Prosody (configurado em docker-jitsi-meet/.env).

    SEM SECRET, DEVOLVE `None` — E ISSO É UM ESTADO VÁLIDO

    O token só existe porque o Jitsi o exige quando sobe com `AUTH_TYPE=jwt`. Com
    `ENABLE_AUTH=0`, que é como o stack local está hoje, o servidor aceita
    conexão anônima e o token é decorativo: o que protege a sala continua sendo o
    nome dela, 256 bits sorteados que ninguém adivinha.

    A versão anterior registrava um aviso e seguia adiante para `jwt.encode`, que
    recusa chave vazia com `InvalidKeyError`. O resultado era 500 na criação da
    sala — e, no navegador, "Failed to fetch", porque resposta de exceção não
    tratada sai sem cabeçalho de CORS e o `fetch` rejeita antes de ver o status.
    Um aviso no log do servidor não ajuda quem está com o cliente na linha vendo
    a chamada não abrir.

    Ligando `AUTH_TYPE=jwt` no Jitsi, preencha `JITSI_JWT_APP_SECRET` com o mesmo
    valor do `docker-jitsi-meet/.env`: aí o token volta a ser obrigatório dos
    dois lados.
    """
    secret = os.environ.get("JITSI_JWT_APP_SECRET", "")
    if not secret:
        return None
    app_id = os.environ.get("JITSI_JWT_APP_ID", "level33-chamadas")
    agora = datetime.now(timezone.utc)

    payload = {
        "aud": app_id,
        "iss": app_id,
        "sub": app_id,
        "room": sala,
        "exp": agora + timedelta(hours=2),
        "nbf": agora - timedelta(seconds=10),
        "context": {
            "user": {
                "name": "Advogado",
                "id": "advogado",
                "moderator": True,
            }
        },
    }
    return jwt.encode(payload, secret, algorithm="HS256")


_salas = chamada.Salas()


def p2p_ligado() -> bool:
    """A chamada tenta ligação direta entre os navegadores antes do bridge?

    PADRÃO DESLIGADO, E O INTERRUPTOR MORA AQUI POR UM MOTIVO

    Com P2P, uma sala de duas pessoas tenta ligar os navegadores diretamente. É
    mais barato, e falha exatamente onde o cliente está: no 4G, o NAT simétrico
    da operadora não deixa o caminho direto fechar, e o sintoma é o pior
    possível — a sala abre, os retratos aparecem e ninguém ouve ninguém. Pelo
    videobridge o celular só manda UDP para um IP público conhecido.

    Mas desligar o P2P aposta tudo no bridge: se ele estiver inalcançável
    (`JVB_ADVERTISE_IPS` errado, UDP 10000 fechada), não sobra caminho e TODA
    chamada emudece. Por isso a decisão é do SERVIDOR, e não do build: religar é
    `CHAMADA_P2P=1` e reiniciar a API, em segundos. Se fosse `NEXT_PUBLIC_*`,
    voltar atrás custaria um pipeline inteiro de build com o cliente na linha.
    """
    return os.environ.get("CHAMADA_P2P", "0").strip().lower() in {"1", "true", "sim"}


@roteador.get("/api/chamada/config")
def config_chamada():
    """Servidores ICE para o navegador montar a conexão. Público e sem segredo."""
    return {"iceServers": chamada.SERVIDORES_ICE}


@roteador.post("/api/chamada/sala", status_code=201)
def criar_sala(payload: dict | None = None):
    """Sorteia uma sala de chamada e devolve o link para mandar ao entrevistado.

    A entrevista acontece ANTES de o caso existir — é ela que decide a categoria
    —, então a sala não pode depender de caso nem de portal. O nome da sala é o
    segredo: 256 bits sorteados, do mesmo gerador que assina o portal. Quem tem
    o link entra; quem não tem não adivinha.

    Sala é efêmera e não é gravada em lugar nenhum: existe enquanto houver
    alguém dentro (ver `app/chamada.py`).

    O token JWT é exigido pelo Jitsi quando AUTH_TYPE=jwt. O cliente também
    chama este endpoint com o sala existente para obter o próprio token. Sem
    `JITSI_JWT_APP_SECRET` o campo vem vazio, e é assim que deve ser: o Jitsi
    local roda com `ENABLE_AUTH=0` e aceita conexão anônima (ver
    `gerar_token_jitsi`).
    """
    sala = (payload or {}).get("sala") if payload else None
    if not sala:
        sala = chamada.gerar_sala()
    token = gerar_token_jitsi(sala)
    return {
        "sala": sala,
        "url": f"{URL_PORTAL}/chamada/{sala}",
        "token": token or "",
        "p2p": p2p_ligado(),
    }


@roteador.post("/api/chamada/sala/{sala_id}/token", status_code=201)
def token_da_sala(sala_id: str):
    """O token para ENTRAR numa sala que já existe. Sem login, de propósito.

    É o que o cliente chama ao abrir o link da chamada. Ele não tem conta — a
    página promete que não precisa criar uma —, e a rota de cima exige sessão
    porque criar sala é ato do escritório. Sem esta separação, o link público
    abria uma tela de login.

    O QUE PROTEGE A SALA CONTINUA SENDO O NOME DELA

    São 256 bits sorteados pelo mesmo gerador que assina o portal. Quem tem o
    link entra; quem não tem não adivinha. É a mesma proteção que o portal do
    caso usa, e o motivo de a sala vir no CAMINHO: o middleware libera por
    prefixo, e o segredo viaja com a requisição sem depender do corpo.

    Não cria nada. Sala inexistente devolve token para um nome que ninguém está
    usando — e a chamada fica esperando alguém que não vem, que é o mesmo que
    acontece com um link antigo. Recusar aqui exigiria manter registro de salas,
    e a sala é efêmera de propósito (ver `app/chamada.py`).
    """
    sala_id = sala_id.strip()
    if not sala_id:
        raise HTTPException(422, "Identificador da sala vazio.")
    token = gerar_token_jitsi(sala_id)
    return {
        "sala": sala_id,
        "url": f"{URL_PORTAL}/chamada/{sala_id}",
        "token": token or "",
        # O cliente entra por AQUI, e não pela rota de cima. Sem esta linha ele
        # cairia no padrão do código (P2P desligado) enquanto o escritório
        # seguiria o servidor — as duas pontas negociando modos diferentes.
        "p2p": p2p_ligado(),
    }


@roteador.websocket("/ws/chamada/{sala_id}")
async def ws_chamada(ws: WebSocket, sala_id: str, papel: str = "cliente"):
    """Sinalização: repassa SDP e ICE entre os dois lados da chamada.

    O servidor não vê nem toca o áudio — ele só apresenta os dois navegadores.
    A `sala_id` é o token do portal do caso, que o cliente já tem e que não é
    adivinhável (256 bits).

    Protocolo:
        â†’ {"type":"offer"|"answer"|"ice", ...}   repassado ao outro lado
        â† {"type":"pronto"}                      o outro lado entrou
        â† {"type":"saiu"}                        o outro lado caiu
    """
    if papel not in ("advogado", "cliente"):
        await ws.close(code=4001)
        return

    await ws.accept()
    papel_tipado: chamada.Papel = papel  # type: ignore[assignment]
    _, tem_outro = await _salas.entrar(sala_id, papel_tipado, ws)

    # Quem chega por último sabe que pode ofertar; quem já estava é avisado.
    await ws.send_json({"type": "entrou", "papel": papel, "outroPresente": tem_outro})
    if tem_outro:
        await _salas.repassar(sala_id, papel_tipado, {"type": "pronto", "papel": papel})

    try:
        while True:
            msg = await ws.receive_json()
            tipo = msg.get("type")
            if tipo in ("offer", "answer", "ice", "encerrar"):
                entregue = await _salas.repassar(sala_id, papel_tipado, msg)
                if not entregue:
                    await ws.send_json({"type": "ausente"})
            elif tipo == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Erro na sinalização da chamada")
    finally:
        # Só avisa a saída se esta conexão ainda era a dona da vaga: uma aba que
        # recarregou já foi substituída, e o "saiu" derrubaria a chamada nova.
        if await _salas.sair(sala_id, papel_tipado, ws):
            await _salas.repassar(
                sala_id, papel_tipado, {"type": "saiu", "papel": papel}
            )
