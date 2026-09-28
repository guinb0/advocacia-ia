"""Constantes e utilitários que mais de uma área da API usa.

Fica fora do `main` para que nenhum router precise importá-lo: o `main` é quem
importa os routers, e o caminho inverso fecharia um ciclo.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from .. import (
    armazenamento,
    auth,
    pipeline,
    portal,
)

# Onde o frontend atende — é o que monta o link enviado ao cliente.
URL_PORTAL = os.getenv("URL_PORTAL", "http://localhost:3000").rstrip("/")

log = logging.getLogger("api")

# Raiz do repositório (este arquivo está em app/rotas/).
BASE = Path(__file__).resolve().parent.parent.parent
STATIC = BASE / "static"

MAX_BYTES = 20 * 1024 * 1024
# O pacote agrega documentos; recebe teto próprio. O conteúdo expandido segue
# limitado separadamente para bloquear ZIP bomb.
MAX_BYTES_ZIP_UPLOAD = int(os.getenv("MAX_BYTES_ZIP_UPLOAD", str(500 * 1024 * 1024)))
_ocr_aquecido = threading.Event()


def _fila_sql_ocr_ativa() -> bool:
    """OCR usa o pool SQL Server. Desligar só com FILA_SQL_OCR_ATIVA=0 (legado Celery)."""
    return os.getenv("FILA_SQL_OCR_ATIVA", "1").strip().lower() in {"1", "true", "sim"}


async def _ler_upload(arquivo: UploadFile) -> bytes:
    """Aceita qualquer tipo de arquivo e aplica apenas limites de segurança.

    Imagens e PDFs seguem para o OCR. Os demais formatos continuam sendo
    preservados no caso e vão para conferência/triagem, em vez de serem
    recusados antes mesmo de o escritório recebê-los.
    """
    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")
    if len(conteudo) > MAX_BYTES:
        raise HTTPException(413, f"Arquivo maior que {MAX_BYTES // (1024 * 1024)}MB.")
    return conteudo


async def _ler_upload_zip(arquivo: UploadFile) -> bytes:
    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")
    if len(conteudo) > MAX_BYTES_ZIP_UPLOAD:
        raise HTTPException(
            413,
            f"O ZIP passa de {MAX_BYTES_ZIP_UPLOAD // (1024 * 1024)}MB. Divida o pacote em partes menores.",
        )
    return conteudo


async def _processar(
    conteudo: bytes, nome: str, idioma: str, tipo_forcado: str | None
) -> dict:
    try:
        # O OCR leva segundos e é puro CPU: fora do event loop, senão o servidor
        # para de responder (inclusive ao /api/saude) enquanto processa.
        return await run_in_threadpool(
            pipeline.processar, conteudo, nome, idioma, tipo_forcado
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        log.exception("Erro ao processar %s", nome)
        raise HTTPException(500, f"Erro ao processar a imagem: {exc}") from exc


# ------------------------------------------------------------------- casos


def _criar_portal(caso_id: str) -> dict[str, Any]:
    """Sorteia link e senha do portal e grava só o hash da senha."""
    token = portal.gerar_token()
    senha = portal.gerar_senha()
    senha_hash, sal = portal.hash_senha(senha)
    armazenamento.definir_portal(caso_id, token, senha_hash, sal)
    portal.limpar_tentativas(token)
    return {
        "url": f"{URL_PORTAL}/portal/{token}",
        "token": token,
        "senha": senha,
        "aviso": "Anote a senha agora: ela não pode ser consultada depois, só trocada.",
    }


def _autor_da_acao(usuario: auth.Usuario) -> str:
    return usuario.nome or usuario.usuario or usuario.id or "escritório"
