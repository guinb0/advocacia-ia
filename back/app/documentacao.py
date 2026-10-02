"""Fila de transferência das entrevistas para o Departamento de Documentação."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import armazenamento, auth, casos
from .banco import PREFIXO, SCHEMA, conectar

roteador = APIRouter(prefix="/api/documentacao", tags=["documentacao"])
PodeDocumentacao = Depends(auth.exigir_modulo("documentacao"))
TABELA = f"{SCHEMA}.{PREFIXO}atendimentos_documentacao"
TABELA_PRESENCA = f"{SCHEMA}.{PREFIXO}documentadores_online"

ESQUEMA = f"""
IF OBJECT_ID('{TABELA}') IS NULL
CREATE TABLE {TABELA} (
    entrevista_id varchar(64) NOT NULL CONSTRAINT pk_acervo_atend_doc PRIMARY KEY,
    caso_id varchar(64) NULL,
    cliente nvarchar(200) NOT NULL CONSTRAINT df_acervo_atend_cliente DEFAULT N'',
    sala varchar(120) NULL,
    status varchar(30) NOT NULL CONSTRAINT df_acervo_atend_status DEFAULT 'entrevista',
    entrevistador_id varchar(64) NOT NULL,
    entrevistador_nome nvarchar(160) NOT NULL,
    documentador_id varchar(64) NULL,
    documentador_nome nvarchar(160) NULL,
    iniciado_em varchar(40) NOT NULL,
    solicitado_em varchar(40) NULL,
    assumido_em varchar(40) NULL,
    atualizado_em varchar(40) NOT NULL
);

IF OBJECT_ID('{TABELA_PRESENCA}') IS NULL
CREATE TABLE {TABELA_PRESENCA} (
    usuario_id varchar(64) NOT NULL CONSTRAINT pk_acervo_doc_online PRIMARY KEY,
    nome nvarchar(160) NOT NULL,
    atualizado_em varchar(40) NOT NULL
);
"""


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def inicializar() -> None:
    with conectar() as con:
        for lote in ESQUEMA.split(";\n"):
            if lote.strip():
                con.execute(lote)


class Inicio(BaseModel):
    entrevista_id: str = Field(min_length=8, max_length=64)
    cliente: str = Field(default="", max_length=200)


class Solicitacao(BaseModel):
    caso_id: str = Field(min_length=8, max_length=64)
    sala: str = Field(min_length=4, max_length=120)
    cliente: str = Field(default="", max_length=200)


def _linha(l: Any) -> dict[str, Any]:
    return {k: l[k] for k in (
        "entrevista_id", "caso_id", "cliente", "sala", "status",
        "entrevistador_id", "entrevistador_nome", "documentador_id",
        "documentador_nome", "iniciado_em", "solicitado_em", "assumido_em", "atualizado_em",
    )}


def _detalhes_documentos(caso_id: str | None) -> dict[str, Any] | None:
    """Resumo operacional do caso para a fila, sem expor conteúdo dos arquivos."""
    if not caso_id:
        return None
    caso = armazenamento.obter_caso(caso_id)
    if not caso:
        return None
    entregas = armazenamento.listar_entregas(caso_id)
    situacao = casos.situacao_de(caso, entregas)
    itens = situacao.get("itens") or []
    progresso = situacao.get("progresso") or {}
    pendentes = [
        str(item.get("nome") or item.get("codigo") or "Documento")
        for item in casos.documentos_pendentes_da_situacao(situacao)
        if item.get("status") == casos.PENDENTE
    ]
    conferir = [
        str(item.get("nome") or item.get("codigo") or "Documento")
        for item in itens
        if item.get("status") == casos.CONFERIR
    ]
    processando = sum(1 for item in itens if item.get("status") == casos.PROCESSANDO)
    datas = [str(e.get("criado_em") or "") for e in entregas if e.get("criado_em")]
    return {
        "categoria": (situacao.get("categoria") or {}).get("nome") or caso.get("categoria") or "",
        "arquivos_recebidos": len(entregas),
        "obrigatorios_total": int(progresso.get("obrigatorios_total") or 0),
        "obrigatorios_entregues": int(progresso.get("obrigatorios_entregues") or 0),
        "percentual": int(progresso.get("percentual_obrigatorios") or 0),
        "pendencias": pendentes,
        "a_conferir": conferir,
        "processando": processando,
        "em_triagem": int(progresso.get("em_triagem") or 0),
        "pronto": bool(progresso.get("pronto")),
        "ultima_entrega_em": max(datas) if datas else None,
    }


def listar_entrevistas_ativas(desde: str) -> list[dict[str, Any]]:
    """Entrevistas com batida recente, sem carregar dados de documentação do caso."""
    with conectar() as con:
        linhas = con.execute(
            f"""
            SELECT entrevista_id, cliente, entrevistador_id, entrevistador_nome,
                   iniciado_em, atualizado_em
              FROM {TABELA}
             WHERE status = 'entrevista' AND atualizado_em >= ?
             ORDER BY atualizado_em DESC, entrevista_id DESC
            """,
            (desde,),
        ).fetchall()
    return [dict(linha) for linha in linhas]


@roteador.post("/atendimentos")
def iniciar(dados: Inicio, usuario: auth.Usuario = Depends(auth.usuario_atual)):
    instante = agora()
    with conectar() as con:
        existe = con.execute(f"SELECT 1 FROM {TABELA} WHERE entrevista_id=?", (dados.entrevista_id,)).fetchone()
        if existe:
            con.execute(f"UPDATE {TABELA} SET cliente=?, atualizado_em=? WHERE entrevista_id=?",
                        (dados.cliente, instante, dados.entrevista_id))
        else:
            con.execute(f"""INSERT INTO {TABELA}
                (entrevista_id,cliente,status,entrevistador_id,entrevistador_nome,iniciado_em,atualizado_em)
                VALUES (?,?,'entrevista',?,?,?,?)""",
                (dados.entrevista_id, dados.cliente, usuario.id, usuario.nome, instante, instante))
    return {"ok": True}


@roteador.post("/atendimentos/{entrevista_id}/batida")
def batida(entrevista_id: str, usuario: auth.Usuario = Depends(auth.usuario_atual)):
    with conectar() as con:
        resultado = con.execute(f"UPDATE {TABELA} SET atualizado_em=? WHERE entrevista_id=? AND status<>'encerrado'",
                                (agora(), entrevista_id))
    return {"ok": resultado.rowcount > 0}


@roteador.post("/atendimentos/{entrevista_id}/solicitar")
def solicitar(entrevista_id: str, dados: Solicitacao, usuario: auth.Usuario = Depends(auth.usuario_atual)):
    instante = agora()
    with conectar() as con:
        # Só pede presença de quem ainda está em entrevista: um pedido repetido não
        # pode devolver a "solicitado" uma chamada que alguém já assumiu ou encerrou.
        resultado = con.execute(f"""UPDATE {TABELA} SET caso_id=?,sala=?,cliente=?,status='solicitado',
            solicitado_em=?,atualizado_em=? WHERE entrevista_id=? AND status IN ('entrevista','solicitado')""",
            (dados.caso_id, dados.sala, dados.cliente, instante, instante, entrevista_id))
        if resultado.rowcount == 0:
            existe = con.execute(f"SELECT status FROM {TABELA} WHERE entrevista_id=?", (entrevista_id,)).fetchone()
    if resultado.rowcount == 0:
        if existe is None:
            raise HTTPException(404, "Atendimento não encontrado.")
        return {"ok": False, "status": existe["status"]}
    return {"ok": True}


def encerrar(entrevista_id: str) -> bool:
    """Fecha o atendimento na fila. É o que impede um pedido antigo de tocar de novo."""
    with conectar() as con:
        resultado = con.execute(
            f"""UPDATE {TABELA} SET status='encerrado', atualizado_em=?
                 WHERE entrevista_id=? AND status IN ('entrevista','solicitado','assumido')""",
            (agora(), entrevista_id),
        )
    return resultado.rowcount > 0


@roteador.post("/atendimentos/{entrevista_id}/encerrar")
def encerrar_rota(entrevista_id: str, usuario: auth.Usuario = Depends(auth.usuario_atual)):
    return {"ok": encerrar(entrevista_id)}


def enfileirar_para_documentacao(
    *, entrevista_id: str, caso_id: str | None, cliente: str,
    entrevistador_id: str, entrevistador_nome: str,
) -> None:
    """O caso criado entra na fila como "aguardando documentação" — sem chamada viva."""
    instante = agora()
    with conectar() as con:
        alteradas = con.execute(
            f"""UPDATE {TABELA} SET caso_id=?, cliente=?, status='aguardando_documentacao',
                   solicitado_em=?, atualizado_em=?
                 WHERE entrevista_id=? AND status NOT IN ('assumido','aguardando_documentacao')""",
            (caso_id, cliente, instante, instante, entrevista_id),
        ).rowcount
        if alteradas:
            return
        existe = con.execute(f"SELECT 1 AS existe FROM {TABELA} WHERE entrevista_id=?", (entrevista_id,)).fetchone()
        if existe:
            return
        con.execute(
            f"""INSERT INTO {TABELA}
                (entrevista_id, caso_id, cliente, status, entrevistador_id, entrevistador_nome,
                 iniciado_em, solicitado_em, atualizado_em)
                VALUES (?, ?, ?, 'aguardando_documentacao', ?, ?, ?, ?, ?)""",
            (entrevista_id, caso_id, cliente, entrevistador_id, entrevistador_nome,
             instante, instante, instante),
        )


#: Pedido de presença ou chamada assumida sem batida há mais que isto é chamada morta.
PRAZO_CHAMADA_HORAS = 6
_ultima_expiracao = 0.0


def expirar_antigos(forcar: bool = False) -> int:
    """Encerra o que ficou aberto: aba fechada sem "encerrar", servidor reiniciado."""
    global _ultima_expiracao
    if not forcar and time.monotonic() - _ultima_expiracao < 60:
        return 0
    _ultima_expiracao = time.monotonic()
    limite = (datetime.now(timezone.utc) - timedelta(hours=PRAZO_CHAMADA_HORAS)).isoformat(timespec="seconds")
    with conectar() as con:
        resultado = con.execute(
            f"""UPDATE {TABELA} SET status='encerrado'
                 WHERE status IN ('entrevista','solicitado','assumido') AND atualizado_em < ?""",
            (limite,),
        )
    return resultado.rowcount


@roteador.get("/atendimentos", dependencies=[PodeDocumentacao])
def listar():
    try:
        expirar_antigos()
    except Exception:  # noqa: BLE001 - a listagem filtra pelo prazo de qualquer jeito
        pass
    instante = datetime.now(timezone.utc)
    limite = (instante - timedelta(minutes=3)).isoformat(timespec="seconds")
    prazo = (instante - timedelta(hours=PRAZO_CHAMADA_HORAS)).isoformat(timespec="seconds")
    with conectar() as con:
        linhas = con.execute(f"""SELECT * FROM {TABELA}
            WHERE status = 'aguardando_documentacao'
               OR (status IN ('solicitado','assumido') AND atualizado_em>=?)
               OR (status='entrevista' AND atualizado_em>=?)
            ORDER BY CASE status WHEN 'solicitado' THEN 0 WHEN 'aguardando_documentacao' THEN 1
                     WHEN 'assumido' THEN 2 ELSE 3 END,
            iniciado_em""", (prazo, limite)).fetchall()
        online = con.execute(f"SELECT COUNT(*) AS total FROM {TABELA_PRESENCA} WHERE atualizado_em>=?", (limite,)).fetchone()
    itens = []
    for linha in linhas:
        item = _linha(linha)
        item["documentos"] = _detalhes_documentos(item.get("caso_id"))
        itens.append(item)
    resumos = [i["documentos"] for i in itens if i.get("documentos")]
    return {
        "entrevistas_ativas": len(itens),
        "solicitacoes": sum(i["status"] == "solicitado" for i in itens),
        "aguardando_documentacao": sum(i["status"] == "aguardando_documentacao" for i in itens),
        "documentadores_online": int(online["total"]),
        "arquivos_recebidos": sum(r["arquivos_recebidos"] for r in resumos),
        "pendencias_obrigatorias": sum(len(r["pendencias"]) for r in resumos),
        "itens_a_conferir": sum(len(r["a_conferir"]) + r["em_triagem"] for r in resumos),
        "casos_prontos": sum(bool(r["pronto"]) for r in resumos),
        "atendimentos": itens,
    }


@roteador.post("/presenca", dependencies=[PodeDocumentacao])
def presenca(usuario: auth.Usuario = Depends(auth.usuario_atual)):
    instante = agora()
    with conectar() as con:
        existe = con.execute(f"SELECT 1 FROM {TABELA_PRESENCA} WHERE usuario_id=?", (usuario.id,)).fetchone()
        if existe:
            con.execute(f"UPDATE {TABELA_PRESENCA} SET nome=?,atualizado_em=? WHERE usuario_id=?", (usuario.nome, instante, usuario.id))
        else:
            con.execute(f"INSERT INTO {TABELA_PRESENCA} (usuario_id,nome,atualizado_em) VALUES (?,?,?)", (usuario.id, usuario.nome, instante))
    return {"ok": True}


@roteador.post("/atendimentos/{entrevista_id}/assumir", dependencies=[PodeDocumentacao])
def assumir(entrevista_id: str, usuario: auth.Usuario = Depends(auth.usuario_atual)):
    instante = agora()
    with conectar() as con:
        resultado = con.execute(f"""UPDATE {TABELA} SET status='assumido',documentador_id=?,
            documentador_nome=?,assumido_em=?,atualizado_em=?
            WHERE entrevista_id=? AND status IN ('solicitado','aguardando_documentacao')""",
            (usuario.id, usuario.nome, instante, instante, entrevista_id))
        linha = con.execute(f"SELECT * FROM {TABELA} WHERE entrevista_id=?", (entrevista_id,)).fetchone()
    if resultado.rowcount == 0:
        raise HTTPException(409, "Este atendimento já foi assumido ou não está aguardando.")
    _concluir_atendimento(entrevista_id, usuario)
    return _linha(linha)


def _concluir_atendimento(entrevista_id: str, usuario: auth.Usuario) -> None:
    """A documentação assumiu: o atendimento chega ao fim e o alerta se resolve."""
    from . import atendimentos

    try:
        registro = atendimentos.por_entrevista(entrevista_id) or atendimentos.obter(entrevista_id)
        if registro and registro["estado"] == atendimentos.DOCUMENTACAO_PENDENTE:
            atendimentos.transicionar(
                registro["id"], atendimentos.CONCLUIDA, de={atendimentos.DOCUMENTACAO_PENDENTE},
                usuario_id=usuario.id, usuario_nome=usuario.nome, detalhes="documentação assumiu",
            )
    except Exception:  # noqa: BLE001 - assumir na fila não pode falhar por causa do atendimento
        import logging

        logging.getLogger("documentacao").warning(
            "Atendimento da entrevista %s não foi concluído.", entrevista_id, exc_info=True
        )


@roteador.get("/atendimentos/{entrevista_id}")
def obter(entrevista_id: str, usuario: auth.Usuario = Depends(auth.usuario_atual)):
    with conectar() as con:
        linha = con.execute(f"SELECT * FROM {TABELA} WHERE entrevista_id=?", (entrevista_id,)).fetchone()
    if not linha:
        raise HTTPException(404, "Atendimento não encontrado.")
    return _linha(linha)
