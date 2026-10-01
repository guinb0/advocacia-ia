"""Acervo Jurídico: leis, versões de dispositivos, jurisprudência, embeddings e alertas (só administrador).

O painel lê o PostgreSQL do RAG. Sem a migration 011 cada leitura responde `migracao_aplicada: false`
(a tela mostra "migração não aplicada"); com o banco fora do ar, `disponivel: false`. Nenhuma das
duas situações vira 500 — o resto do sistema não depende desta tela.

Ações que mexem no acervo (verificar agora, reindexar) só enfileiram a sincronização na fila `low`
e exigem `ACERVO_SINCRONIZACAO_ATIVA=1`; o texto das normas nunca é editado por aqui.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import auth

log = logging.getLogger("acervo")

roteador = APIRouter(prefix="/api/acervo")
_ADMIN = auth.exigir_modulo("acervo_juridico")


class Confirmacao(BaseModel):
    confirmar: bool = False


class NovaAnotacao(BaseModel):
    texto: str = Field(min_length=1, max_length=4000)
    document_id: str = ""
    dispositivo_id: str = ""
    authority_id: str = ""


class ImportacaoJurisprudencia(BaseModel):
    itens: list[dict[str, Any]] = Field(min_length=1, max_length=5000)


def _ler(funcao: Callable[[Any], Any], chave: str | None = None) -> dict[str, Any]:
    """Envelope comum: migração/indisponibilidade viram estado na resposta, não erro HTTP."""
    from ..acervo import armazenamento
    try:
        store = armazenamento.padrao()
        if not store.migracao_aplicada():
            return {"migracao_aplicada": False, "disponivel": True,
                    "erro": "Migration 011_acervo_juridico.sql não aplicada no PostgreSQL do RAG."}
        dados = funcao(store)
    except Exception as erro:  # noqa: BLE001
        # Só o tipo do erro: a mensagem do driver pode trazer host e usuário do banco.
        log.warning("acervo: leitura indisponível: %s", type(erro).__name__)
        return {"migracao_aplicada": None, "disponivel": False, "erro": f"Banco do acervo indisponível ({type(erro).__name__})."}
    corpo = {chave: dados} if chave else dict(dados)
    return {"migracao_aplicada": True, "disponivel": True, **corpo}


def _store_pronto() -> Any:
    from ..acervo import armazenamento
    store = armazenamento.padrao()
    try:
        migrada = store.migracao_aplicada()
    except Exception as erro:  # noqa: BLE001
        raise HTTPException(503, f"Banco do acervo indisponível ({type(erro).__name__}).") from erro
    if not migrada:
        raise HTTPException(409, "Migration 011_acervo_juridico.sql não aplicada no PostgreSQL do RAG.")
    return store


def _exigir_sincronizacao_ativa() -> None:
    from ..acervo import agenda
    if not agenda.ativa():
        raise HTTPException(409, "Sincronização desligada (ACERVO_SINCRONIZACAO_ATIVA=0). "
                                 "Ligue-a no ambiente ou rode `python -m scripts.sincronizar_acervo --executar`.")


def _enfileirar(document_id: str, *, usuario: auth.Usuario, reindexar: bool) -> dict[str, Any]:
    from ..acervo import sincronizacao
    from ..tasks.acervo import sincronizar_documento
    if not sincronizacao.item_do_manifesto(document_id):
        raise HTTPException(404, f"Norma {document_id} não está no manifesto do acervo.")
    _exigir_sincronizacao_ativa()
    _store_pronto()
    try:
        tarefa = sincronizar_documento.apply_async(
            args=[document_id], kwargs={"origem": "manual", "solicitado_por": usuario.nome, "reindexar": reindexar}, queue="low")
    except Exception as erro:  # noqa: BLE001
        raise HTTPException(503, f"Fila de tarefas indisponível ({type(erro).__name__}).") from erro
    return {"enfileirado": True, "tarefa": tarefa.id, "document_id": document_id, "reindexar": reindexar}


# ------------------------------------------------------------------ leitura

@roteador.get("/resumo")
async def resumo(_u: auth.Usuario = Depends(_ADMIN)) -> dict[str, Any]:
    from ..acervo import consulta
    return await run_in_threadpool(_ler, consulta.resumo)


@roteador.get("/configuracao")
async def configuracao(_u: auth.Usuario = Depends(_ADMIN)) -> dict[str, Any]:
    from ..acervo import consulta
    return await run_in_threadpool(consulta.configuracao)


@roteador.get("/normas")
async def normas(
    busca: str = Query(default="", max_length=200), categoria: str = Query(default="", max_length=40),
    status: str = Query(default="", max_length=40), _u: auth.Usuario = Depends(_ADMIN),
) -> dict[str, Any]:
    from ..acervo import consulta
    return await run_in_threadpool(_ler, lambda s: consulta.normas(s, busca=busca, categoria=categoria, status=status), "itens")


@roteador.get("/normas/{document_id}")
async def norma(document_id: str, _u: auth.Usuario = Depends(_ADMIN)) -> dict[str, Any]:
    from ..acervo import consulta
    corpo = await run_in_threadpool(_ler, lambda s: {"norma": consulta.norma(s, document_id)})
    if corpo.get("migracao_aplicada") and corpo.get("norma") is None:
        raise HTTPException(404, "Norma não encontrada no acervo.")
    return corpo


@roteador.get("/dispositivos/{version_id}")
async def dispositivo(version_id: int, _u: auth.Usuario = Depends(_ADMIN)) -> dict[str, Any]:
    from ..acervo import consulta
    corpo = await run_in_threadpool(_ler, lambda s: {"dispositivo": consulta.dispositivo(s, version_id)})
    if corpo.get("migracao_aplicada") and corpo.get("dispositivo") is None:
        raise HTTPException(404, "Versão de dispositivo não encontrada.")
    return corpo


@roteador.get("/autoridades/resolver")
async def resolver_autoridade(autoridade: str = Query(min_length=1, max_length=300), _u: auth.Usuario = Depends(_ADMIN)) -> dict[str, Any]:
    """Link do trace da peça (`authority_id`) → dispositivo ou ficha de jurisprudência."""
    from ..acervo import consulta
    return await run_in_threadpool(_ler, lambda s: consulta.resolver_autoridade(s, autoridade), "destino")


@roteador.get("/jurisprudencia")
async def jurisprudencia(
    busca: str = Query(default="", max_length=200), status: str = Query(default="", max_length=40), _u: auth.Usuario = Depends(_ADMIN),
) -> dict[str, Any]:
    from ..acervo import consulta
    return await run_in_threadpool(_ler, lambda s: consulta.jurisprudencia(s, busca=busca, status=status), "itens")


@roteador.get("/sincronizacoes")
async def sincronizacoes(
    document_id: str = Query(default="", max_length=120), limite: int = Query(default=50, ge=1, le=500), _u: auth.Usuario = Depends(_ADMIN),
) -> dict[str, Any]:
    from ..acervo import consulta
    return await run_in_threadpool(
        _ler, lambda s: [consulta._limpo(x) for x in s.sincronizacoes(document_id=document_id or None, limite=limite)], "itens")  # noqa: SLF001


@roteador.get("/alertas")
async def alertas(abertos: bool = True, limite: int = Query(default=200, ge=1, le=1000), _u: auth.Usuario = Depends(_ADMIN)) -> dict[str, Any]:
    from ..acervo import consulta
    return await run_in_threadpool(_ler, lambda s: [consulta._limpo(a) for a in s.alertas(abertos=abertos, limite=limite)], "itens")  # noqa: SLF001


@roteador.get("/problemas")
async def problemas(_u: auth.Usuario = Depends(_ADMIN)) -> dict[str, Any]:
    from ..acervo import consulta
    return await run_in_threadpool(_ler, consulta.problemas, "itens")


# ------------------------------------------------------------------ ações

@roteador.post("/normas/{document_id}/verificar")
async def verificar_agora(document_id: str, usuario: auth.Usuario = Depends(_ADMIN)) -> dict[str, Any]:
    """Enfileira a sincronização desta norma agora (só o que mudou ganha versão e embedding novo)."""
    return await run_in_threadpool(lambda: _enfileirar(document_id, usuario=usuario, reindexar=False))


@roteador.post("/normas/{document_id}/reindexar")
async def reindexar(document_id: str, corpo: Confirmacao, usuario: auth.Usuario = Depends(_ADMIN)) -> dict[str, Any]:
    """Refaz o embedding de TODOS os artigos da norma (custo de API). Exige `confirmar: true`."""
    if not corpo.confirmar:
        raise HTTPException(400, "Reindexar refaz todos os embeddings da norma e tem custo; confirme com `confirmar: true`.")
    return await run_in_threadpool(lambda: _enfileirar(document_id, usuario=usuario, reindexar=True))


@roteador.post("/anotacoes")
async def anotar(corpo: NovaAnotacao, usuario: auth.Usuario = Depends(_ADMIN)) -> dict[str, Any]:
    if not (corpo.document_id or corpo.dispositivo_id or corpo.authority_id):
        raise HTTPException(400, "Informe a norma, o dispositivo ou a autoridade anotada.")

    def gravar() -> dict[str, Any]:
        from ..acervo import armazenamento
        store = _store_pronto()
        aid = store.anotar({**corpo.model_dump(), "texto": corpo.texto.strip(), "autor": usuario.nome}, agora=armazenamento.agora_utc())
        return {"id": aid}
    return await run_in_threadpool(gravar)


@roteador.post("/alertas/{alerta_id}/resolver")
async def resolver_alerta(alerta_id: int, usuario: auth.Usuario = Depends(_ADMIN)) -> dict[str, Any]:
    def resolver() -> dict[str, Any]:
        from ..acervo import armazenamento
        if not _store_pronto().resolver_alerta(alerta_id, por=usuario.nome, agora=armazenamento.agora_utc()):
            raise HTTPException(404, "Alerta não encontrado ou já resolvido.")
        return {"resolvido": True}
    return await run_in_threadpool(resolver)


@roteador.post("/jurisprudencia/importar")
async def importar_jurisprudencia(corpo: ImportacaoJurisprudencia, usuario: auth.Usuario = Depends(_ADMIN)) -> dict[str, Any]:
    """Súmulas/OJs/SVs que não vêm por coleta automática. Tudo entra AGUARDANDO_VERIFICACAO."""
    def importar() -> dict[str, Any]:
        from ..acervo import armazenamento, jurisprudencia as juris
        store = _store_pronto()
        invalidos = []
        for i, item in enumerate(corpo.itens):
            try:
                juris.normalizar(item)
            except juris.ItemInvalido as erro:
                invalidos.append({"item": i + 1, "erro": str(erro)})
        if invalidos:
            raise HTTPException(400, {"mensagem": "Nada foi importado: há itens inválidos.", "invalidos": invalidos[:50]})
        return juris.importar(corpo.itens, armazenamento=store, agora=armazenamento.agora_utc(), origem=f"painel:{usuario.nome}")
    return await run_in_threadpool(importar)
