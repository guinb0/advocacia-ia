"""Fila de transferência das entrevistas para o Departamento de Documentação."""

from __future__ import annotations

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
        for item in itens
        if item.get("obrigatorio") and item.get("status") == casos.PENDENTE
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
        resultado = con.execute(f"""UPDATE {TABELA} SET caso_id=?,sala=?,cliente=?,status='solicitado',
            solicitado_em=?,atualizado_em=? WHERE entrevista_id=?""",
            (dados.caso_id, dados.sala, dados.cliente, instante, instante, entrevista_id))
    if resultado.rowcount == 0:
        raise HTTPException(404, "Atendimento não encontrado.")
    return {"ok": True}


@roteador.get("/atendimentos", dependencies=[PodeDocumentacao])
def listar():
    limite = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat(timespec="seconds")
    with conectar() as con:
        linhas = con.execute(f"""SELECT * FROM {TABELA}
            WHERE status IN ('solicitado','assumido') OR (status='entrevista' AND atualizado_em>=?)
            ORDER BY CASE status WHEN 'solicitado' THEN 0 WHEN 'assumido' THEN 1 ELSE 2 END,
            iniciado_em""", (limite,)).fetchall()
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
            WHERE entrevista_id=? AND status='solicitado'""",
            (usuario.id, usuario.nome, instante, instante, entrevista_id))
        linha = con.execute(f"SELECT * FROM {TABELA} WHERE entrevista_id=?", (entrevista_id,)).fetchone()
    if resultado.rowcount == 0:
        raise HTTPException(409, "Esta chamada já foi assumida ou não está aguardando.")
    return _linha(linha)


@roteador.get("/atendimentos/{entrevista_id}")
def obter(entrevista_id: str, usuario: auth.Usuario = Depends(auth.usuario_atual)):
    with conectar() as con:
        linha = con.execute(f"SELECT * FROM {TABELA} WHERE entrevista_id=?", (entrevista_id,)).fetchone()
    if not linha:
        raise HTTPException(404, "Atendimento não encontrado.")
    return _linha(linha)
