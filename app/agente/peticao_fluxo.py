"""Fluxo de petição local — entrevista + OCR → análise → redação (DeepSeek)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .. import armazenamento, peticao_local
from .. import casos as casos_ocr
from .cliente import ErroDoAgente

log = logging.getLogger("agente")

__all__ = [
    "analisar_entrevista",
    "estado",
    "gerar_completo",
    "gerar_peticao",
    "transcricao",
]

ID_LOCAL = peticao_local.ID_LOCAL


def transcricao(caso_id: str) -> dict[str, Any]:
    entrevistas = armazenamento.listar_entrevistas(caso_id)
    com_texto = [e for e in entrevistas if (e.get("texto") or "").strip()]
    if not com_texto:
        raise ErroDoAgente(
            "Nenhuma entrevista com transcrição encontrada para este caso."
        )
    ultima = max(com_texto, key=lambda e: e.get("criado_em") or "")
    texto = str(ultima.get("texto") or "").strip()
    return {
        "entrevista_id": ultima["id"],
        "arquivo": ultima.get("arquivo"),
        "caracteres": len(texto),
        "previa": texto[:2000],
        "texto": texto,
        "enviada": bool(ultima.get("enviada")),
    }


def _resumo_preparacao(caso_id: str) -> dict[str, Any]:
    situacao = casos_ocr.montar_situacao(caso_id) or {}
    progresso = situacao.get("progresso") or {}
    documentos = 0
    for entrega in armazenamento.listar_entregas(caso_id):
        detalhe = armazenamento.obter_entrega(entrega["id"])
        if (
            detalhe
            and str((detalhe.get("extracao") or {}).get("texto_completo") or "").strip()
        ):
            documentos += 1
    return {
        "documentos_lidos": documentos,
        "checklist_obrigatorios": progresso.get("obrigatorios_total"),
        "checklist_entregues": progresso.get("obrigatorios_entregues"),
    }


def _erro_peticao(erro: peticao_local.ErroPeticao) -> ErroDoAgente:
    return ErroDoAgente(str(erro))


def estado(caso_id: str) -> dict[str, Any]:
    ent = None
    try:
        ent = transcricao(caso_id)
    except ErroDoAgente:
        pass
    local = peticao_local.carregar(caso_id)
    caso = armazenamento.obter_caso(caso_id) or {}
    analise = (local or {}).get("analise")
    return {
        "entrevista": ent,
        "analise": analise,
        "preparacao": _resumo_preparacao(caso_id),
        "categoria": caso.get("categoria"),
        "peticao_id": ID_LOCAL if local else None,
        "peticao_pronta": local is not None,
    }


def analisar_entrevista(caso_id: str) -> dict[str, Any]:
    ent = transcricao(caso_id)
    try:
        analise = peticao_local.analisar(caso_id, texto_entrevista=ent["texto"])
    except peticao_local.ErroPeticao as erro:
        raise _erro_peticao(erro) from erro
    return {
        "entrevista_id": ent["entrevista_id"],
        "analise": {k: v for k, v in analise.items() if k != "contexto"},
        "preparacao": _resumo_preparacao(caso_id),
    }


def gerar_peticao(caso_id: str, *, opcao: int = 0) -> dict[str, Any]:
    del opcao  # estratégias removidas — fluxo direto
    return gerar_completo(caso_id)


def gerar_completo(caso_id: str) -> dict[str, Any]:
    """Analisa entrevista + OCR e redige a petição (síncrono)."""
    ent = transcricao(caso_id)
    try:
        dados = peticao_local.gerar(caso_id, texto_entrevista=ent["texto"])
    except peticao_local.ErroPeticao as erro:
        raise _erro_peticao(erro) from erro

    analise = dados.get("analise") or {}
    agora = dados.get("updated_at") or datetime.now(timezone.utc).isoformat()
    analise_limpa = {k: v for k, v in analise.items() if k != "contexto"}
    return {
        "run_id": ID_LOCAL,
        "status": "DONE",
        "requested_at": agora,
        "generation_id": ID_LOCAL,
        "pipeline": "local",
        "analise": analise_limpa,
        "peticao": peticao_local.para_api(dados),
    }
