"""Rotas do atendimento: agenda, presença na sala, alertas e o fluxo pós-entrevista."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import alertas, analise_acoes, auth, documentacao, perfis, pos_entrevista, whatsapp_modelos
from .. import atendimentos as at

roteador = APIRouter(tags=["atendimentos"])
PodeEntrevistar = Depends(auth.exigir_modulo("entrevista"))


def _http(exc: at.ErroAtendimento) -> HTTPException:
    return HTTPException(exc.status, str(exc))


def _modulos_do_usuario(usuario: auth.Usuario) -> set[str]:
    if not auth.ATIVA:
        return set(perfis.CODIGOS_MODULOS)
    return perfis.modulos_de(list(auth._papeis_atuais(usuario)))


class Lembretes(BaseModel):
    ativo: bool = True
    intervalo_dias: int = Field(1, ge=0, le=30)
    minutos_antes_no_dia: list[int] = Field(default_factory=list, max_length=6)


class NovoAgendamento(BaseModel):
    cliente: str = Field(..., min_length=2, max_length=200)
    telefone: str = Field("", max_length=30)
    data_hora: str = Field(..., max_length=40)
    duracao_min: int = Field(60, ge=10, le=480)
    responsavel_id: str | None = Field(None, max_length=64)
    responsavel_nome: str | None = Field(None, max_length=200)
    observacao: str = Field("", max_length=1000)
    lembretes: Lembretes | None = None
    enviar_confirmacao: bool = True


class EdicaoAgendamento(BaseModel):
    versao: int
    cliente: str | None = Field(None, max_length=200)
    telefone: str | None = Field(None, max_length=30)
    data_hora: str | None = Field(None, max_length=40)
    responsavel_id: str | None = Field(None, max_length=64)
    responsavel_nome: str | None = Field(None, max_length=200)
    observacao: str | None = Field(None, max_length=1000)
    lembretes: Lembretes | None = None
    usar_lembretes_padrao: bool = False


class Presenca(BaseModel):
    evento: str = Field("batida", pattern="^(entrou|batida|saiu)$")


class InicioEntrevista(BaseModel):
    entrevista_id: str = Field(..., min_length=8, max_length=64)
    cliente: str = Field("", max_length=200)
    sala: str | None = Field(None, max_length=120)
    atendimento_id: str | None = Field(None, max_length=64)


class SeguirParaAnalise(BaseModel):
    revisada: bool = False


class PedidoAnalise(BaseModel):
    transcricao: str = Field("", max_length=200_000)
    relato: str = Field("", max_length=50_000)
    respostas: dict[str, Any] = Field(default_factory=dict)
    perguntas: dict[str, str] = Field(default_factory=dict)
    documentos: list[str] = Field(default_factory=list, max_length=80)
    triagem_ao_vivo: dict[str, Any] | None = None
    refazer: bool = False


class AcaoConfirmada(BaseModel):
    codigo: str = Field("", max_length=80)
    nome: str = Field("", max_length=200)
    origem: str = Field("manual", pattern="^(ia|triagem|manual)$")
    nova: dict[str, Any] | None = None


class ConfirmacaoAcoes(BaseModel):
    acoes: list[AcaoConfirmada] = Field(..., min_length=1, max_length=pos_entrevista.MAXIMO_ACOES)
    documentos_declarados: list[str] = Field(default_factory=list, max_length=60)
    cliente: str = Field("", max_length=200)
    telefone: str = Field("", max_length=30)


class Qualificacao(BaseModel):
    dados: dict[str, Any] | None = None


class EnvioAvaliacao(BaseModel):
    telefone: str = Field("", max_length=30)
    forcar: bool = False


class Finalizacao(BaseModel):
    pular_avaliacao: bool = False


class EnvioConfirmacao(BaseModel):
    forcar: bool = False


class ConfigAtendimento(BaseModel):
    escalonar_apos_min: int | None = Field(None, ge=1, le=240)
    tolerancia_falta_min: int | None = Field(None, ge=1, le=240)
    enviar_falta_automatico: bool | None = None
    lembretes: Lembretes | None = None


def _usuario_nome(usuario: auth.Usuario) -> str:
    return usuario.nome or usuario.email or usuario.id or "escritório"


# ------------------------------------------------------------------ alertas


@roteador.get("/api/alertas/ativos")
async def alertas_ativos(usuario: auth.Usuario = Depends(auth.usuario_atual)) -> dict[str, Any]:
    modulos = await run_in_threadpool(_modulos_do_usuario, usuario)
    itens = await run_in_threadpool(alertas.ativos_para, usuario.id, modulos)
    return {"alertas": itens}


# ------------------------------------------------------------------- config


def fluxo_v2_ativo() -> bool:
    """`FLUXO_ATENDIMENTO_V2=0` devolve a tela da entrevista ao fluxo antigo sem novo deploy do front."""
    return os.getenv("FLUXO_ATENDIMENTO_V2", "1").strip().lower() not in ("0", "false", "nao", "não", "off")


@roteador.get("/api/atendimentos/config")
def obter_config() -> dict[str, Any]:
    return {**at.obter_config(), "fluxo_v2": fluxo_v2_ativo()}


@roteador.put("/api/atendimentos/config")
def salvar_config(
    pedido: ConfigAtendimento,
    usuario: auth.Usuario = Depends(auth.exigir_algum_modulo("whatsapp", "entrevista")),
) -> dict[str, Any]:
    valores = pedido.model_dump(exclude_none=True)
    return at.salvar_config(valores, _usuario_nome(usuario))


# ------------------------------------------------------------------- agenda


@roteador.get("/api/atendimentos")
def listar(
    de: str | None = Query(None, max_length=40),
    ate: str | None = Query(None, max_length=40),
    estado: list[str] | None = Query(None),
) -> dict[str, Any]:
    return {"atendimentos": at.listar(de=de, ate=ate, estados=estado)}


def _confirmar_em_segundo_plano(registro: dict[str, Any], usuario_nome: str) -> None:
    resultado = whatsapp_modelos.enviar_confirmacao(registro)
    try:
        at.registrar_evento(registro["id"], f"confirmacao_{resultado.get('status')}",
                            usuario_nome=usuario_nome,
                            detalhes=str(resultado.get("motivo") or "")[:500] or None)
    except Exception:  # noqa: BLE001 - o envio já ficou registrado em automacoes_whatsapp
        pass


@roteador.post("/api/atendimentos", status_code=201)
def agendar(
    pedido: NovoAgendamento, tarefas: BackgroundTasks, usuario: auth.Usuario = PodeEntrevistar
) -> dict[str, Any]:
    try:
        registro = at.criar(
            cliente=pedido.cliente,
            telefone=pedido.telefone,
            data_hora=pedido.data_hora,
            duracao_min=pedido.duracao_min,
            responsavel_id=pedido.responsavel_id or usuario.id,
            responsavel_nome=pedido.responsavel_nome or _usuario_nome(usuario),
            observacao=pedido.observacao,
            config_lembretes=pedido.lembretes.model_dump() if pedido.lembretes else None,
            usuario_nome=_usuario_nome(usuario),
        )
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc
    if pedido.enviar_confirmacao and registro.get("telefone"):
        tarefas.add_task(_confirmar_em_segundo_plano, registro, _usuario_nome(usuario))
    return registro


@roteador.post("/api/atendimentos/entrevista")
def iniciar_entrevista(
    pedido: InicioEntrevista, usuario: auth.Usuario = PodeEntrevistar
) -> dict[str, Any]:
    """Liga a entrevista que começou ao atendimento (agendado ou avulso novo)."""
    try:
        return at.garantir_para_entrevista(
            entrevista_id=pedido.entrevista_id,
            cliente=pedido.cliente,
            sala=pedido.sala,
            usuario_id=usuario.id,
            usuario_nome=_usuario_nome(usuario),
            atendimento_id=pedido.atendimento_id,
        )
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc


@roteador.post("/api/atendimentos/sala/{sala}/presenca")
def presenca_escritorio(
    sala: str, pedido: Presenca, usuario: auth.Usuario = Depends(auth.usuario_atual)
) -> dict[str, Any]:
    try:
        registro = at.presenca_do_escritorio(sala, pedido.evento, usuario.id, _usuario_nome(usuario))
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc
    return {"atendimento": registro}


@roteador.get("/api/atendimentos/{atendimento_id}")
def obter(atendimento_id: str, eventos: bool = Query(False)) -> dict[str, Any]:
    try:
        registro = at.exigir(atendimento_id)
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc
    if eventos:
        registro["eventos"] = at.eventos(atendimento_id)
        registro["alertas"] = alertas.historico(atendimento_id)
    return registro


@roteador.patch("/api/atendimentos/{atendimento_id}")
def editar(
    atendimento_id: str, pedido: EdicaoAgendamento, usuario: auth.Usuario = PodeEntrevistar
) -> dict[str, Any]:
    campos = pedido.model_dump(exclude_none=True, exclude={"versao", "lembretes", "usar_lembretes_padrao"})
    if pedido.lembretes is not None:
        campos["config_lembretes"] = pedido.lembretes.model_dump()
    elif pedido.usar_lembretes_padrao:
        campos["config_lembretes"] = None
    try:
        return at.atualizar_agenda(
            atendimento_id, campos, versao=pedido.versao, usuario_nome=_usuario_nome(usuario)
        )
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc


@roteador.post("/api/atendimentos/{atendimento_id}/cancelar")
def cancelar(atendimento_id: str, usuario: auth.Usuario = PodeEntrevistar) -> dict[str, Any]:
    try:
        return at.transicionar(
            atendimento_id, at.CANCELADA, de=at.ANTES_DA_ENTREVISTA,
            usuario_id=usuario.id, usuario_nome=_usuario_nome(usuario),
        )
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc


@roteador.post("/api/atendimentos/{atendimento_id}/falta")
def marcar_falta(atendimento_id: str, usuario: auth.Usuario = PodeEntrevistar) -> dict[str, Any]:
    try:
        return at.transicionar(
            atendimento_id, at.CLIENTE_FALTOU, de={at.AGENDADA},
            usuario_id=usuario.id, usuario_nome=_usuario_nome(usuario), detalhes="marcada à mão",
        )
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc


@roteador.post("/api/atendimentos/{atendimento_id}/reagendar")
def reagendar(atendimento_id: str, usuario: auth.Usuario = PodeEntrevistar) -> dict[str, Any]:
    try:
        return at.transicionar(
            atendimento_id, at.AGENDADA, de={at.CLIENTE_FALTOU},
            usuario_id=usuario.id, usuario_nome=_usuario_nome(usuario),
        )
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc


@roteador.post("/api/atendimentos/{atendimento_id}/assumir")
def assumir(atendimento_id: str, usuario: auth.Usuario = PodeEntrevistar) -> dict[str, Any]:
    """Quem clicou em "Assumir atendimento" passa a ser o atendente. Um só vence."""
    try:
        return at.iniciar_atendimento(atendimento_id, usuario.id, _usuario_nome(usuario))
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc


@roteador.post("/api/atendimentos/{atendimento_id}/finalizar-entrevista")
def finalizar_entrevista(atendimento_id: str, usuario: auth.Usuario = PodeEntrevistar) -> dict[str, Any]:
    try:
        registro = at.exigir(atendimento_id)
        if registro["estado"] != at.EM_ATENDIMENTO and registro["estado"] not in at.ANTES_DA_ENTREVISTA:
            return registro
        if registro["estado"] in at.ANTES_DA_ENTREVISTA:
            at.iniciar_atendimento(atendimento_id, usuario.id, _usuario_nome(usuario),
                                   motivo="finalizou sem registro de entrada")
        registro = at.transicionar(
            atendimento_id, at.ENTREVISTA_FINALIZADA,
            usuario_id=usuario.id, usuario_nome=_usuario_nome(usuario),
        )
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc
    if registro.get("entrevista_id"):
        documentacao.encerrar(registro["entrevista_id"])
    return registro


@roteador.post("/api/atendimentos/{atendimento_id}/seguir-para-analise")
def seguir_para_analise(
    atendimento_id: str, pedido: SeguirParaAnalise, usuario: auth.Usuario = PodeEntrevistar
) -> dict[str, Any]:
    """"Revisar entrevista" e "Continuar sem revisar" chegam aqui: o mesmo próximo passo."""
    try:
        registro = at.exigir(atendimento_id)
        if registro["estado"] != at.ENTREVISTA_FINALIZADA:
            return registro
        return at.transicionar(
            atendimento_id, at.ANALISE_JURIDICA, de={at.ENTREVISTA_FINALIZADA},
            usuario_id=usuario.id, usuario_nome=_usuario_nome(usuario),
            detalhes="revisada" if pedido.revisada else "sem revisão",
            extras={"revisada": int(pedido.revisada)},
        )
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc


@roteador.post("/api/atendimentos/{atendimento_id}/confirmacao")
def enviar_confirmacao(
    atendimento_id: str, pedido: EnvioConfirmacao, usuario: auth.Usuario = PodeEntrevistar
) -> dict[str, Any]:
    """Confirmação do agendamento por WhatsApp. Repetir não reenvia (sem `forcar`)."""
    try:
        registro = at.exigir(atendimento_id)
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc
    resultado = whatsapp_modelos.enviar_confirmacao(registro, forcar=pedido.forcar)
    at.registrar_evento(atendimento_id, f"confirmacao_{resultado.get('status')}",
                        usuario_id=usuario.id, usuario_nome=_usuario_nome(usuario),
                        detalhes=str(resultado.get("motivo") or "")[:500] or None)
    return resultado


# ------------------------------------------------------------ pós-entrevista


@roteador.post("/api/atendimentos/{atendimento_id}/analise", status_code=202)
def iniciar_analise(
    atendimento_id: str, pedido: PedidoAnalise, usuario: auth.Usuario = PodeEntrevistar
) -> dict[str, Any]:
    entrada = pedido.model_dump(exclude={"refazer"})
    try:
        registro = at.exigir(atendimento_id)
        if registro["estado"] == at.ENTREVISTA_FINALIZADA:
            at.transicionar(atendimento_id, at.ANALISE_JURIDICA, de={at.ENTREVISTA_FINALIZADA},
                            usuario_id=usuario.id, usuario_nome=_usuario_nome(usuario),
                            detalhes="sem revisão")
        analise = analise_acoes.iniciar(
            atendimento_id, entrada, usuario=_usuario_nome(usuario), refazer=pedido.refazer
        )
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc
    return {"analise": analise, "atendimento": at.exigir(atendimento_id)}


@roteador.get("/api/atendimentos/{atendimento_id}/analise")
def obter_analise(atendimento_id: str) -> dict[str, Any]:
    try:
        registro = at.exigir(atendimento_id)
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc
    analise = analise_acoes.ultima(atendimento_id)
    return {"analise": analise, "atendimento": at.exigir(atendimento_id) if analise else registro}


@roteador.post("/api/atendimentos/{atendimento_id}/confirmar-acoes")
def confirmar_acoes(
    atendimento_id: str, pedido: ConfirmacaoAcoes, usuario: auth.Usuario = PodeEntrevistar
) -> dict[str, Any]:
    try:
        return pos_entrevista.confirmar_acoes(
            atendimento_id,
            acoes=[a.model_dump() for a in pedido.acoes],
            documentos_declarados=pedido.documentos_declarados,
            cliente=pedido.cliente,
            telefone=pedido.telefone,
            usuario_id=usuario.id,
            usuario_nome=_usuario_nome(usuario),
        )
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc


@roteador.post("/api/atendimentos/{atendimento_id}/qualificacao")
def concluir_qualificacao(
    atendimento_id: str, pedido: Qualificacao, usuario: auth.Usuario = PodeEntrevistar
) -> dict[str, Any]:
    try:
        return pos_entrevista.concluir_qualificacao(
            atendimento_id, dados=pedido.dados, usuario_id=usuario.id,
            usuario_nome=_usuario_nome(usuario),
        )
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc


@roteador.get("/api/atendimentos/{atendimento_id}/avaliacao")
def estado_avaliacao(atendimento_id: str) -> dict[str, Any]:
    try:
        return pos_entrevista.estado_avaliacao(atendimento_id)
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc


@roteador.post("/api/atendimentos/{atendimento_id}/avaliacao")
def enviar_avaliacao(
    atendimento_id: str, pedido: EnvioAvaliacao, usuario: auth.Usuario = PodeEntrevistar
) -> dict[str, Any]:
    try:
        return pos_entrevista.enviar_avaliacao(
            atendimento_id, telefone=pedido.telefone, forcar=pedido.forcar,
            usuario_nome=_usuario_nome(usuario),
        )
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc


@roteador.post("/api/atendimentos/{atendimento_id}/finalizar")
def finalizar(
    atendimento_id: str, pedido: Finalizacao, usuario: auth.Usuario = PodeEntrevistar
) -> dict[str, Any]:
    try:
        return pos_entrevista.finalizar(
            atendimento_id, usuario_id=usuario.id, usuario_nome=_usuario_nome(usuario),
            pular_avaliacao=pedido.pular_avaliacao,
        )
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc


@roteador.get("/api/atendimentos/{atendimento_id}/documentos-consolidados")
def documentos_consolidados(atendimento_id: str) -> dict[str, Any]:
    try:
        registro = at.exigir(atendimento_id)
    except at.ErroAtendimento as exc:
        raise _http(exc) from exc
    return pos_entrevista.documentos_consolidados(registro)
