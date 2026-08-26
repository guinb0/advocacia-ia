"""Portal do cliente: link público por caso, protegido por senha.

O cliente não tem conta no sistema — recebe um link e uma senha pelo WhatsApp.
O que protege os documentos (CPF, laudos médicos, CAT) é justamente esta senha,
então tudo aqui é dimensionado para isso:

- Senha gerada por CSPRNG (`secrets`), nunca por `random`, que é previsível.
- Guardada só como hash PBKDF2 com sal por caso. Nem o banco nem a tela do
  advogado conseguem revelá-la depois: ela aparece uma única vez, na geração.
- Comparação em tempo constante, para a resposta não vazar quantos caracteres
  estavam certos.
- Tentativas limitadas por caso: sem isso, uma senha de 50 bits ainda cairia se
  alguém pudesse chutar sem parar.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Any

log = logging.getLogger("portal")

# Alfabeto sem caracteres que se confundem quando alguém dita ou digita a senha:
# sem O/0, I/l/1, e sem letras minúsculas ambíguas. 32 símbolos = 5 bits cada.
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
TAMANHO_SENHA = 10  # 10 x 5 bits = 50 bits de entropia

# OWASP recomenda >= 600k iterações para PBKDF2-HMAC-SHA256 (2023).
ITERACOES = 600_000

DURACAO_SESSAO_S = 2 * 60 * 60  # 2 h: o cliente fotografa documentos com calma

MAX_TENTATIVAS = 5
JANELA_BLOQUEIO_S = 15 * 60


def _segredo_sessao() -> bytes:
    """Chave que assina as sessões do portal.

    Sem `PORTAL_SEGREDO` no ambiente, sorteia uma por processo: as sessões caem
    a cada reinício do servidor, o que é chato mas honesto — melhor que embutir
    um segredo padrão no código, que não protegeria ninguém.
    """
    do_ambiente = os.getenv("PORTAL_SEGREDO", "").strip()
    if do_ambiente:
        return do_ambiente.encode()
    log.warning(
        "PORTAL_SEGREDO não definido: as sessões do portal do cliente serão "
        "invalidadas a cada reinício do servidor."
    )
    return secrets.token_bytes(32)


SEGREDO = _segredo_sessao()


# ------------------------------------------------------------------ senha


def gerar_senha() -> str:
    """Senha de 50 bits, em dois blocos de 5 para facilitar o ditado."""
    bruta = "".join(secrets.choice(ALFABETO) for _ in range(TAMANHO_SENHA))
    return f"{bruta[:5]}-{bruta[5:]}"


def gerar_token() -> str:
    """Identificador público do caso na URL. 256 bits: não é adivinhável."""
    return secrets.token_urlsafe(32)


def hash_senha(senha: str, sal: bytes | None = None) -> tuple[str, str]:
    """Devolve (hash_hex, sal_hex). O hífen é ignorado na conferência."""
    sal = sal or secrets.token_bytes(16)
    derivado = hashlib.pbkdf2_hmac("sha256", _normalizar(senha).encode(), sal, ITERACOES)
    return derivado.hex(), sal.hex()


def _normalizar(senha: str) -> str:
    """Aceita a senha com ou sem hífen, em maiúscula ou minúscula."""
    return senha.strip().replace("-", "").replace(" ", "").upper()


def conferir_senha(senha: str, hash_hex: str, sal_hex: str) -> bool:
    calculado, _ = hash_senha(senha, bytes.fromhex(sal_hex))
    # compare_digest: o tempo de resposta não revela onde a senha divergiu.
    return hmac.compare_digest(calculado, hash_hex)


# ------------------------------------------------- limite de tentativas


_tentativas: dict[str, list[float]] = {}
_trava = threading.Lock()


def registrar_falha(token: str) -> None:
    with _trava:
        agora = time.time()
        recentes = [t for t in _tentativas.get(token, []) if agora - t < JANELA_BLOQUEIO_S]
        recentes.append(agora)
        _tentativas[token] = recentes


def limpar_tentativas(token: str) -> None:
    with _trava:
        _tentativas.pop(token, None)


def bloqueado(token: str) -> int:
    """Segundos restantes de bloqueio, ou 0 se pode tentar."""
    with _trava:
        agora = time.time()
        recentes = [t for t in _tentativas.get(token, []) if agora - t < JANELA_BLOQUEIO_S]
        _tentativas[token] = recentes
        if len(recentes) < MAX_TENTATIVAS:
            return 0
        return int(JANELA_BLOQUEIO_S - (agora - min(recentes))) + 1


# ---------------------------------------------------------------- sessão


def _assinar(dados: bytes) -> str:
    return hmac.new(SEGREDO, dados, hashlib.sha256).hexdigest()


def criar_sessao(token: str) -> dict[str, Any]:
    """Token de sessão assinado. Sem banco: o próprio valor carrega a validade."""
    expira = int(time.time()) + DURACAO_SESSAO_S
    corpo = json.dumps({"t": token, "exp": expira}, separators=(",", ":")).encode()
    corpo_b64 = urlsafe_b64encode(corpo).decode().rstrip("=")
    return {
        "sessao": f"{corpo_b64}.{_assinar(corpo_b64.encode())}",
        "expira_em": expira,
        "duracao_s": DURACAO_SESSAO_S,
    }


def validar_sessao(sessao: str, token_esperado: str) -> bool:
    """A sessão é autêntica, está no prazo e pertence a ESTE caso?"""
    try:
        corpo_b64, assinatura = sessao.split(".", 1)
    except ValueError:
        return False

    if not hmac.compare_digest(_assinar(corpo_b64.encode()), assinatura):
        return False

    try:
        preenchimento = "=" * (-len(corpo_b64) % 4)
        dados = json.loads(urlsafe_b64decode(corpo_b64 + preenchimento))
    except Exception:
        return False

    if dados.get("exp", 0) < time.time():
        return False
    # Amarra a sessão ao caso: uma sessão válida de outro caso não serve aqui.
    return hmac.compare_digest(str(dados.get("t", "")), token_esperado)
