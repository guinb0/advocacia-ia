"""Sinalização da chamada de voz entre advogado e cliente (WebRTC).

O servidor NÃO processa mídia. Ele só apresenta os dois lados um ao outro: cada
navegador manda sua oferta/resposta SDP e seus candidatos ICE, e este módulo
repassa para o outro participante da sala. O áudio vai direto de um navegador
para o outro.

    advogado ──── SDP/ICE ────► [servidor] ────► cliente
        └──────────── áudio direto (P2P) ───────────┘

Isso importa por três razões:

1. **Custo.** Repassar áudio exigiria um SFU e banda no servidor. Aqui o
   servidor só troca alguns kilobytes de texto por chamada.
2. **Privacidade.** A conversa não trafega pelo nosso servidor.
3. **Transcrição.** O navegador do advogado recebe a faixa do cliente separada
   da dele. É essa faixa que vai para o Whisper — assim transcrevemos o cliente,
   não o entrevistador, sem precisar de diarização.

Limitação conhecida: sem servidor TURN, redes com NAT simétrico (algumas
corporativas e 4G) não conseguem estabelecer o par. STUN público resolve a
maioria dos casos domésticos. Colocar TURN é o próximo passo se aparecer
cliente que não conecta.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import WebSocket

log = logging.getLogger("chamada")

Papel = Literal["advogado", "cliente"]


def gerar_sala() -> str:
    """Nome de sala válido em XMPP: 32 caracteres hexadecimais.

    Não usa `secrets.token_urlsafe` como o portal porque a sala vira o nome de
    uma MUC no Prosody, e o Jitsi normaliza para minúsculas — um token com
    maiúsculas viraria outro nome no servidor, e as duas pontas poderiam
    divergir dependendo de quem normalizou primeiro. Hexadecimal já nasce
    minúsculo. São 128 bits: não é adivinhável.
    """
    return secrets.token_hex(16)

#: STUN público do Google. Só descobre o IP externo; não vê nem toca a mídia.
SERVIDORES_ICE: list[dict[str, Any]] = [
    {"urls": ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"]}
]


@dataclass
class Participante:
    papel: Papel
    ws: WebSocket


@dataclass
class Sala:
    """Uma chamada. No máximo um advogado e um cliente."""

    id: str
    participantes: dict[Papel, Participante] = field(default_factory=dict)

    def outro(self, papel: Papel) -> Participante | None:
        alvo: Papel = "cliente" if papel == "advogado" else "advogado"
        return self.participantes.get(alvo)

    @property
    def cheia(self) -> bool:
        return len(self.participantes) >= 2


class Salas:
    def __init__(self) -> None:
        self._itens: dict[str, Sala] = {}
        self._trava = asyncio.Lock()

    async def entrar(self, sala_id: str, papel: Papel, ws: WebSocket) -> tuple[Sala, bool]:
        """Devolve a sala e se o outro lado já estava lá."""
        async with self._trava:
            sala = self._itens.setdefault(sala_id, Sala(id=sala_id))
            # Reconexão do mesmo papel substitui a anterior: uma aba recarregada
            # não pode deixar um fantasma ocupando a vaga.
            anterior = sala.participantes.get(papel)
            if anterior is not None:
                try:
                    await anterior.ws.close()
                except Exception:
                    pass
            sala.participantes[papel] = Participante(papel=papel, ws=ws)
            return sala, sala.outro(papel) is not None

    async def sair(self, sala_id: str, papel: Papel, ws: WebSocket) -> bool:
        """Tira o participante da sala. `False` se a vaga já era de outro.

        A conferência de identidade não é zelo excessivo: quando uma aba
        recarrega, o `entrar` fecha a conexão anterior, e o laço dela só
        desperta para morrer DEPOIS que a nova já ocupou a vaga. Sem comparar o
        WebSocket, esse desligamento atrasado expulsaria a conexão nova e ainda
        anunciaria 'saiu' — a chamada morreria exatamente quando o cliente
        acabou de voltar.
        """
        async with self._trava:
            sala = self._itens.get(sala_id)
            if sala is None:
                return False
            atual = sala.participantes.get(papel)
            if atual is None or atual.ws is not ws:
                return False
            sala.participantes.pop(papel, None)
            if not sala.participantes:
                self._itens.pop(sala_id, None)
            return True

    async def repassar(self, sala_id: str, de: Papel, mensagem: dict[str, Any]) -> bool:
        """Entrega a mensagem ao outro participante. `False` se ele não está lá."""
        async with self._trava:
            sala = self._itens.get(sala_id)
            destino = sala.outro(de) if sala else None
        if destino is None:
            return False
        try:
            await destino.ws.send_json(mensagem)
            return True
        except Exception:
            log.warning("Falha ao repassar %s para %s", mensagem.get("type"), de)
            return False
