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
    "aceitar_revisao",
    "descartar_revisao",
    "estado",
    "gerar_completo",
    "gerar_peticao",
    "historico_de_peticao",
    "revisar_peca_anexa",
    "revisar_peticao",
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
    # Contar em UMA consulta, e não abrindo cada anexo.
    #
    # Isto é só o número "46 docs com texto OCR" do alto do painel, e custava um
    # `obter_entrega` por arquivo — cada um com conexão própria e uma pergunta ao
    # agente jurídico. Medido no caso `da5a030b`: 99 consultas e 30s para ABRIR a
    # tela, antes de o advogado clicar em nada.
    documentos = sum(
        1
        for entrega in armazenamento.listar_extracoes_do_caso(caso_id)
        if str((entrega.get("extracao") or {}).get("texto_completo") or "").strip()
    )
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


def revisar_peticao(
    caso_id: str, *, prompt: str, usuario: str, generaliza: bool = True
) -> dict[str, Any]:
    """Issue "Permitir alteração da petição por prompt com rastreabilidade"."""
    try:
        dados = peticao_local.revisar_com_prompt(
            caso_id, prompt_critica=prompt, usuario=usuario, generaliza=generaliza
        )
    except peticao_local.ErroPeticao as erro:
        raise _erro_peticao(erro) from erro
    return {
        "peticao": peticao_local.para_api(dados),
        "criticas": peticao_local.historico_de_criticas(caso_id),
        "revisao": dados.get("revisao"),
    }


def revisar_peca_anexa(peca_id: str, *, prompt: str, usuario: str = "") -> dict[str, Any]:
    try:
        dados = peticao_local.revisar_anexa_com_prompt(
            peca_id, prompt_critica=prompt, usuario=usuario
        )
    except peticao_local.ErroPeticao as erro:
        raise _erro_peticao(erro) from erro
    return {"peticao": dados, "criticas": [], "revisao": dados.get("revisao")}


def aceitar_revisao(caso_id: str, revisao_id: str) -> dict[str, Any]:
    try:
        return {"peticao": peticao_local.para_api(peticao_local.aceitar_revisao_pendente(caso_id, revisao_id))}
    except peticao_local.ErroPeticao as erro:
        raise _erro_peticao(erro) from erro


def descartar_revisao(caso_id: str, revisao_id: str) -> dict[str, Any]:
    try:
        return {"peticao": peticao_local.para_api(peticao_local.descartar_revisao_pendente(caso_id, revisao_id))}
    except peticao_local.ErroPeticao as erro:
        raise _erro_peticao(erro) from erro


def historico_de_peticao(caso_id: str, peca_id: str | None = None) -> dict[str, Any]:
    """Rastreabilidade completa: críticas feitas e versões anteriores da petição."""
    if peca_id:
        return {"criticas": [], "versoes": peticao_local.historico_de_versoes(caso_id, peca_id)}
    return {
        "criticas": peticao_local.historico_de_criticas(caso_id),
        "versoes": peticao_local.historico_de_versoes(caso_id),
    }
