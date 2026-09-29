"""Cifra de segredos guardados no banco — hoje, o token de provedor de assinatura.

POR QUE ISTO EXISTE

O token da Clicksign ou da Autentique não é nosso: é do escritório-cliente, que o
digita na tela de configuração para o SISTEMA mandar os documentos dele pela conta
dele. Diferente da senha de login (`app/usuarios.py`, hash sem volta), este segredo
precisa ser recuperado em texto claro a cada envio — é o que vai no cabeçalho
`Authorization` da chamada à API do provedor. Por isso é CIFRADO, não HASHEADO: hash
destrói o segredo de propósito, e aqui ele precisa voltar.

Nunca em claro: nem no banco, nem em log, nem de volta para a tela (a tela só recebe
"configurado: sim/não" e o resultado do teste — ver `app/assinatura_config.py`).

DE ONDE VEM A CHAVE

Fernet pede 32 bytes. Em vez de pedir mais uma variável crítica no `.env`, deriva-se
de `JWT_SECRET` por SHA-256 — quem já guarda essa chave a salvo (é o segredo dos
tokens de sessão) guarda também esta. `CRIPTO_SECRET` existe como saída para o dia em
que trocar o `JWT_SECRET` (o que derruba todas as sessões abertas) e cifrar de novo
sejam operações que precisem ser independentes.

Sem nenhuma das duas, cifrar/decifrar RECUSA — nunca guarda em claro por a chave
estar ausente, e nunca finge sucesso na leitura.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

from . import auth

__all__ = ["ErroCripto", "cifrar", "decifrar"]


class ErroCripto(RuntimeError):
    """Falta a chave, ou o cifrado não abre com a chave atual."""


def _chave() -> bytes:
    segredo = auth.JWT_SECRET or (os.getenv("CRIPTO_SECRET", "") or "").strip()
    if not segredo:
        raise ErroCripto(
            "Falta JWT_SECRET (ou CRIPTO_SECRET) no ambiente — sem uma chave, este "
            "token não pode ser cifrado com segurança para guardar no banco."
        )
    # Fernet exige uma chave de 32 bytes em base64 urlsafe; o segredo do ambiente
    # pode ter qualquer tamanho, então passa por um hash de tamanho fixo antes.
    return base64.urlsafe_b64encode(hashlib.sha256(segredo.encode("utf-8")).digest())


def cifrar(texto: str) -> str:
    """Texto em claro → cifrado (ascii, seguro para gravar numa coluna `nvarchar`)."""
    return Fernet(_chave()).encrypt(texto.encode("utf-8")).decode("ascii")


def decifrar(cifrado: str) -> str:
    """Cifrado → texto em claro. Levanta se a chave mudou ou o valor foi corrompido."""
    try:
        return Fernet(_chave()).decrypt(cifrado.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ErroCripto(
            "Não foi possível decifrar o token — a chave (JWT_SECRET) pode ter "
            "mudado desde que ele foi salvo. Configure o token de novo."
        ) from exc
