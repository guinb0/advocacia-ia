"""Critérios de classificação dos tipos de caso e os tipos criados pela IA.

CRITÉRIOS

"Quando usar" é um parágrafo; a análise pós-entrevista precisa de uma lista que
ela possa conferir item a item ("cliente era empregado dos Correios", "houve
afastamento pelo INSS"). Cada critério é uma linha ordenável, e — diferente do
checklist — vale também para as ações do sistema: o critério não muda o que o
cliente entrega, só ajuda a reconhecer a ação no relato.

TIPOS GERADOS PELA IA

Quando a análise encontra uma ação que o catálogo não tem, o advogado pode
aceitá-la. Ela nasce como tipo de caso comum (em `tipos_caso`), com uma linha
aqui marcando `requer_revisao`: a tela mostra "Gerado por IA — requer revisão"
até alguém aprovar. Ficar numa tabela à parte, e não em colunas novas de
`tipos_caso`, mantém intactas as consultas e os testes daquele cadastro.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import auth, banco, tipos_caso
from .banco import PREFIXO, SCHEMA
from .esquema_portavel import Coluna, Tabela, criar as criar_tabelas

log = logging.getLogger("criterios_caso")

TABELA_CRITERIOS = f"{SCHEMA}.{PREFIXO}tipos_caso_criterios"
TABELA_IA = f"{SCHEMA}.{PREFIXO}tipos_caso_ia"
LIMITE_CRITERIO = 400
MAXIMO_CRITERIOS = 40

TABELAS = (
    Tabela(
        TABELA_CRITERIOS,
        (
            Coluna("id", "id", nula=False),
            Coluna("tipo_codigo", "codigo", nula=False),
            Coluna("ordem", "inteiro", nula=False, padrao=0),
            Coluna("texto", "texto", nula=False),
            Coluna("ativo", "inteiro", nula=False, padrao=1),
            Coluna("criado_em", "data", nula=False),
            Coluna("atualizado_em", "data", nula=False),
            Coluna("atualizado_por", "curto"),
        ),
        ("id",),
        indices=(("ix_acervo_tc_criterios_tipo", ("tipo_codigo", "ordem")),),
    ),
    Tabela(
        TABELA_IA,
        (
            Coluna("tipo_codigo", "codigo", nula=False),
            Coluna("origem", "codigo", nula=False, padrao="ia"),
            Coluna("requer_revisao", "inteiro", nula=False, padrao=1),
            Coluna("informacoes_necessarias_json", "longo"),
            Coluna("fundamentos_json", "longo"),
            Coluna("atendimento_id", "id"),
            Coluna("gerado_em", "data", nula=False),
            Coluna("gerado_por", "curto"),
            Coluna("aprovado_em", "data"),
            Coluna("aprovado_por", "curto"),
        ),
        ("tipo_codigo",),
    ),
)


class ErroCriterio(ValueError):
    status = 400


def inicializar() -> None:
    with banco.conectar() as con:
        criar_tabelas(con, TABELAS)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _texto(valor: Any) -> str:
    limpo = " ".join(str(valor or "").split())
    if len(limpo) < 3:
        raise ErroCriterio("Escreva o critério (mínimo de 3 caracteres).")
    if len(limpo) > LIMITE_CRITERIO:
        raise ErroCriterio(f"O critério passa de {LIMITE_CRITERIO} caracteres.")
    return limpo


def _exigir_tipo(codigo: str) -> None:
    if tipos_caso.obter(codigo) is None:
        raise ErroCriterio(f"O tipo de caso “{codigo}” não está no catálogo.")


# ---------------------------------------------------------------- critérios


def listar(tipo_codigo: str, *, incluir_inativos: bool = True) -> list[dict[str, Any]]:
    filtro = "" if incluir_inativos else " AND ativo = 1"
    with banco.conectar() as con:
        linhas = con.execute(
            f"SELECT * FROM {TABELA_CRITERIOS} WHERE tipo_codigo = ?{filtro} ORDER BY ordem, criado_em",
            (tipo_codigo,),
        ).fetchall()
    return [
        {**dict(zip(linha.keys(), linha)), "ativo": bool(linha["ativo"])} for linha in linhas
    ]


def por_tipos(codigos: list[str]) -> dict[str, list[str]]:
    """Os critérios ATIVOS de cada tipo, na ordem — o que a análise jurídica lê."""
    if not codigos:
        return {}
    marcadores = ",".join("?" for _ in codigos)
    try:
        with banco.conectar() as con:
            linhas = con.execute(
                f"SELECT tipo_codigo, texto FROM {TABELA_CRITERIOS} "
                f"WHERE ativo = 1 AND tipo_codigo IN ({marcadores}) ORDER BY tipo_codigo, ordem, criado_em",
                tuple(codigos),
            ).fetchall()
    except Exception:  # noqa: BLE001 - critério ajuda; sem ele a análise ainda roda
        log.warning("Critérios indisponíveis.", exc_info=True)
        return {}
    saida: dict[str, list[str]] = {}
    for linha in linhas:
        saida.setdefault(str(linha["tipo_codigo"]), []).append(str(linha["texto"]))
    return saida


def criar(tipo_codigo: str, texto: str, usuario: str, *, verificar_tipo: bool = True) -> dict[str, Any]:
    if verificar_tipo:
        _exigir_tipo(tipo_codigo)
    limpo = _texto(texto)
    atuais = listar(tipo_codigo)
    if len(atuais) >= MAXIMO_CRITERIOS:
        raise ErroCriterio(f"São aceitos até {MAXIMO_CRITERIOS} critérios por tipo.")
    instante = _agora()
    novo = {
        "id": uuid.uuid4().hex, "tipo_codigo": tipo_codigo,
        "ordem": max([c["ordem"] for c in atuais] or [0]) + 1, "texto": limpo, "ativo": True,
        "criado_em": instante, "atualizado_em": instante, "atualizado_por": usuario[:200],
    }
    with banco.conectar() as con:
        con.execute(
            f"""INSERT INTO {TABELA_CRITERIOS}
                (id, tipo_codigo, ordem, texto, ativo, criado_em, atualizado_em, atualizado_por)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
            (novo["id"], tipo_codigo, novo["ordem"], limpo, instante, instante, novo["atualizado_por"]),
        )
    return novo


def editar(tipo_codigo: str, criterio_id: str, *, texto: str | None, ativo: bool | None,
           usuario: str) -> dict[str, Any]:
    sets, params = ["atualizado_em = ?", "atualizado_por = ?"], [_agora(), usuario[:200]]
    if texto is not None:
        sets.append("texto = ?")
        params.append(_texto(texto))
    if ativo is not None:
        sets.append("ativo = ?")
        params.append(int(ativo))
    with banco.conectar() as con:
        alteradas = con.execute(
            f"UPDATE {TABELA_CRITERIOS} SET {', '.join(sets)} WHERE id = ? AND tipo_codigo = ?",
            (*params, criterio_id, tipo_codigo),
        ).rowcount
    if not alteradas:
        raise ErroCriterio("Critério não encontrado.")
    return next(c for c in listar(tipo_codigo) if c["id"] == criterio_id)


def remover(tipo_codigo: str, criterio_id: str) -> None:
    with banco.conectar() as con:
        con.execute(
            f"DELETE FROM {TABELA_CRITERIOS} WHERE id = ? AND tipo_codigo = ?",
            (criterio_id, tipo_codigo),
        )


def reordenar(tipo_codigo: str, ids: list[str], usuario: str) -> list[dict[str, Any]]:
    atuais = {c["id"] for c in listar(tipo_codigo)}
    if set(ids) != atuais:
        raise ErroCriterio("A nova ordem precisa conter todos os critérios do tipo, uma vez cada.")
    instante = _agora()
    with banco.conectar() as con:
        for posicao, criterio_id in enumerate(ids, start=1):
            con.execute(
                f"UPDATE {TABELA_CRITERIOS} SET ordem = ?, atualizado_em = ?, atualizado_por = ? "
                "WHERE id = ? AND tipo_codigo = ?",
                (posicao, instante, usuario[:200], criterio_id, tipo_codigo),
            )
    return listar(tipo_codigo)


# ------------------------------------------------------- tipos gerados pela IA


def metadados_ia() -> dict[str, dict[str, Any]]:
    try:
        with banco.conectar() as con:
            linhas = con.execute(f"SELECT * FROM {TABELA_IA}").fetchall()
    except Exception:  # noqa: BLE001
        log.warning("Metadados de tipos gerados por IA indisponíveis.", exc_info=True)
        return {}
    saida: dict[str, dict[str, Any]] = {}
    for linha in linhas:
        r = dict(zip(linha.keys(), linha))
        r["requer_revisao"] = bool(r.get("requer_revisao"))
        r["informacoes_necessarias"] = json.loads(r.pop("informacoes_necessarias_json") or "[]")
        r["fundamentos"] = json.loads(r.pop("fundamentos_json") or "[]")
        saida[str(r["tipo_codigo"])] = r
    return saida


def criar_rascunho_ia(
    *,
    nome: str,
    descricao: str,
    criterios: list[str],
    documentos: list[dict[str, Any]],
    informacoes_necessarias: list[str],
    fundamentos: list[dict[str, Any]],
    usuario: str,
    atendimento_id: str | None = None,
) -> dict[str, Any]:
    """Cria o tipo de caso sugerido pela análise, marcado para revisão.

    `documentos`: [{"nome", "minimo": bool}] — "mínimo" vira item obrigatório do
    checklist. Nome já existente no catálogo devolve o tipo existente: aceitar a
    mesma sugestão duas vezes não pode criar duas ações iguais.
    """
    from .extractors import normalizar

    alvo = normalizar(" ".join(str(nome or "").split()))
    for existente in tipos_caso.listar(incluir_inativos=True):
        if normalizar(existente["nome"]) == alvo:
            return existente
    itens = [
        {"nome": str(d.get("nome") or "").strip()[: tipos_caso.LIMITE_ITEM_NOME],
         "obrigatorio": bool(d.get("minimo", d.get("obrigatorio"))), "tipo_documento": None,
         "observacao": ""}
        for d in documentos or []
        if str(d.get("nome") or "").strip()
    ][: tipos_caso.MAXIMO_ITENS]
    tipo = tipos_caso.criar(
        nome=nome,
        usuario=usuario,
        descricao=(descricao or "")[: tipos_caso.LIMITE_DESCRICAO],
        quando_usar="; ".join(criterios or [])[: tipos_caso.LIMITE_QUANDO_USAR],
        itens=itens,
    )
    codigo = tipo["codigo"]
    with banco.conectar() as con:
        con.execute(
            f"""INSERT INTO {TABELA_IA}
                (tipo_codigo, origem, requer_revisao, informacoes_necessarias_json,
                 fundamentos_json, atendimento_id, gerado_em, gerado_por)
                VALUES (?, 'ia', 1, ?, ?, ?, ?, ?)""",
            (
                codigo,
                json.dumps(list(informacoes_necessarias or [])[:30], ensure_ascii=False),
                json.dumps(list(fundamentos or [])[:20], ensure_ascii=False),
                atendimento_id, _agora(), usuario[:200],
            ),
        )
    for texto in (criterios or [])[:MAXIMO_CRITERIOS]:
        try:
            criar(codigo, texto, usuario, verificar_tipo=False)
        except ErroCriterio:
            continue
    return tipo


def aprovar(tipo_codigo: str, usuario: str) -> dict[str, Any]:
    with banco.conectar() as con:
        alteradas = con.execute(
            f"UPDATE {TABELA_IA} SET requer_revisao = 0, aprovado_em = ?, aprovado_por = ? "
            "WHERE tipo_codigo = ?",
            (_agora(), usuario[:200], tipo_codigo),
        ).rowcount
    if not alteradas:
        raise ErroCriterio("Este tipo de caso não foi gerado pela IA.")
    return metadados_ia().get(tipo_codigo, {})


# ------------------------------------------------------------------- rotas

roteador = APIRouter(prefix="/api/tipos-caso", tags=["tipos-caso"])
roteador_ia = APIRouter(prefix="/api/tipos-caso-ia", tags=["tipos-caso"])
PodeManter = Depends(auth.exigir_modulo(tipos_caso.MODULO))


class NovoCriterio(BaseModel):
    texto: str = Field(..., max_length=LIMITE_CRITERIO * 2)


class EdicaoCriterio(BaseModel):
    texto: str | None = Field(None, max_length=LIMITE_CRITERIO * 2)
    ativo: bool | None = None


class OrdemCriterios(BaseModel):
    ids: list[str] = Field(..., max_length=MAXIMO_CRITERIOS)


def _quem(usuario: auth.Usuario) -> str:
    return usuario.nome or usuario.email or usuario.id or "escritório"


def _http(exc: ErroCriterio) -> HTTPException:
    return HTTPException(exc.status, str(exc))


@roteador_ia.get("")
def rota_metadados_ia() -> dict[str, Any]:
    return {"tipos": metadados_ia()}


@roteador.get("/{codigo}/criterios")
def rota_listar(codigo: str) -> dict[str, Any]:
    return {"criterios": listar(codigo)}


@roteador.post("/{codigo}/criterios", status_code=201)
def rota_criar(codigo: str, pedido: NovoCriterio, usuario: auth.Usuario = PodeManter) -> dict[str, Any]:
    try:
        return criar(codigo, pedido.texto, _quem(usuario))
    except ErroCriterio as exc:
        raise _http(exc) from exc


@roteador.put("/{codigo}/criterios/{criterio_id}")
def rota_editar(codigo: str, criterio_id: str, pedido: EdicaoCriterio,
                usuario: auth.Usuario = PodeManter) -> dict[str, Any]:
    try:
        return editar(codigo, criterio_id, texto=pedido.texto, ativo=pedido.ativo, usuario=_quem(usuario))
    except ErroCriterio as exc:
        raise _http(exc) from exc


@roteador.delete("/{codigo}/criterios/{criterio_id}", status_code=204)
def rota_remover(codigo: str, criterio_id: str, _usuario: auth.Usuario = PodeManter) -> None:
    remover(codigo, criterio_id)


@roteador.put("/{codigo}/criterios-ordem")
def rota_reordenar(codigo: str, pedido: OrdemCriterios, usuario: auth.Usuario = PodeManter) -> dict[str, Any]:
    try:
        return {"criterios": reordenar(codigo, pedido.ids, _quem(usuario))}
    except ErroCriterio as exc:
        raise _http(exc) from exc


@roteador.post("/{codigo}/aprovar")
def rota_aprovar(codigo: str, usuario: auth.Usuario = PodeManter) -> dict[str, Any]:
    try:
        return aprovar(codigo, _quem(usuario))
    except ErroCriterio as exc:
        raise _http(exc) from exc
