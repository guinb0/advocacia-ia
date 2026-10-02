"""Alertas da equipe que existem só enquanto a condição que os criou for verdadeira.

A CAUSA DO PROBLEMA ANTIGO

A Central de Documentação tocava de novo, a cada abertura da tela, pedidos de
chamadas encerradas havia dias. Três defeitos somados: nada gravava o fim do
atendimento, a listagem não tinha prazo, e a memória do "já avisei" era um
`useRef` que morria com a tela.

O QUE MUDA

O alerta é DERIVADO do atendimento (`app/atendimentos.py`). `desejados()` diz,
a partir do estado e da presença na sala, quais alertas deveriam existir agora;
`sincronizar()` cria os que faltam e resolve — com motivo — os que deixaram de
valer. Ninguém "apaga" alerta na tela: ele some porque o servidor parou de
devolvê-lo, e o servidor parou porque a condição acabou.

- `cliente_aguardando` (para o responsável): o cliente está na sala, com batida
  recente, e ninguém do escritório entrou.
- `escalonamento` (para quem tem o módulo `entrevista`): a mesma espera passou de
  `escalonar_apos_min` minutos. Uma linha só por episódio de espera — sem spam.
- `documentacao_pendente` (para o módulo `documentacao`): caso criado aguardando
  a equipe de documentação assumir.

A chave única inclui o instante em que o cliente entrou: se ele sai e volta, é
outro episódio e outro alerta; se a tela recarrega, é o mesmo.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

import pyodbc

from . import atendimentos as at
from . import banco
from .banco import PREFIXO, SCHEMA
from .esquema_portavel import Coluna, Tabela, criar as criar_tabelas

log = logging.getLogger("alertas")

TABELA = f"{SCHEMA}.{PREFIXO}alertas"

CLIENTE_AGUARDANDO = "cliente_aguardando"
ESCALONAMENTO = "escalonamento"
DOCUMENTACAO_PENDENTE = "documentacao_pendente"

#: Teto de vida de um alerta de sala, mesmo que a varredura falhe.
VIDA_MAXIMA_SALA = timedelta(hours=3)

_ERROS_DE_CHAVE = (pyodbc.IntegrityError, sqlite3.IntegrityError)

TABELAS = (
    Tabela(
        TABELA,
        (
            Coluna("id", "id", nula=False),
            Coluna("chave", "chave", nula=False),
            Coluna("tipo", "codigo", nula=False),
            Coluna("atendimento_id", "id", nula=False),
            Coluna("destinatario_id", "id"),
            Coluna("modulo", "codigo"),
            Coluna("titulo", "curto", nula=False),
            Coluna("texto", "texto"),
            Coluna("acao", "codigo"),
            Coluna("dados_json", "longo"),
            Coluna("criado_em", "data", nula=False),
            Coluna("expira_em", "data"),
            Coluna("resolvido_em", "data"),
            Coluna("motivo_resolucao", "codigo"),
        ),
        ("id",),
        unicos=(("ux_acervo_alertas_chave", ("chave",)),),
        indices=(("ix_acervo_alertas_ativos", ("resolvido_em", "atendimento_id")),),
    ),
)


def inicializar() -> None:
    with banco.conectar() as con:
        criar_tabelas(con, TABELAS)


# ---------------------------------------------------------- o que deveria existir


def desejados(
    registro: dict[str, Any], instante: datetime, escalonar_apos_min: int
) -> list[dict[str, Any]]:
    """Os alertas que este atendimento justifica AGORA. Função pura."""
    saida: list[dict[str, Any]] = []
    estado = registro.get("estado")
    if estado == at.CLIENTE_AGUARDANDO and at.presente(registro.get("cliente_batida_em"), instante):
        entrou = registro.get("cliente_entrou_em") or registro.get("cliente_batida_em")
        dados = {
            "cliente": registro.get("cliente") or "Cliente",
            "sala": registro.get("sala"),
            "desde": entrou,
            "responsavel": registro.get("responsavel_nome") or "",
            "responsavel_id": registro.get("responsavel_id") or "",
        }
        destino = registro.get("responsavel_id")
        saida.append({
            "chave": f"{CLIENTE_AGUARDANDO}:{registro['id']}:{entrou}",
            "tipo": CLIENTE_AGUARDANDO,
            "destinatario_id": destino or None,
            "modulo": None if destino else "entrevista",
            "titulo": f"{dados['cliente']} entrou na sala da entrevista",
            "texto": "O cliente está aguardando na chamada.",
            "acao": "entrar",
            "dados": dados,
        })
        inicio = at.ler_data(entrou)
        if inicio is not None and instante - inicio >= timedelta(minutes=escalonar_apos_min):
            saida.append({
                "chave": f"{ESCALONAMENTO}:{registro['id']}:{entrou}",
                "tipo": ESCALONAMENTO,
                "destinatario_id": None,
                "modulo": "entrevista",
                "titulo": "Cliente aguardando atendimento",
                "texto": (
                    f"{dados['cliente']} está aguardando. "
                    f"Responsável: {dados['responsavel'] or 'não definido'}."
                ),
                "acao": "assumir",
                "dados": dados,
            })
    elif estado == at.DOCUMENTACAO_PENDENTE:
        documentos = registro.get("documentos") or {}
        saida.append({
            "chave": f"{DOCUMENTACAO_PENDENTE}:{registro['id']}",
            "tipo": DOCUMENTACAO_PENDENTE,
            "destinatario_id": None,
            "modulo": "documentacao",
            "titulo": "Novo caso aguardando documentação",
            "texto": f"{registro.get('cliente') or 'Cliente'}: "
                     + ", ".join(a.get("nome", "") for a in registro.get("acoes") or [] if a.get("nome")),
            "acao": "abrir_caso",
            "dados": {
                "cliente": registro.get("cliente") or "",
                "acoes": [a.get("nome") for a in registro.get("acoes") or [] if a.get("nome")],
                "casos": registro.get("casos") or [],
                "disponiveis": [d.get("nome") for d in documentos.get("disponiveis") or []],
                "pendentes": [d.get("nome") for d in documentos.get("faltantes") or []],
                "responsavel": registro.get("atendente_nome") or registro.get("responsavel_nome") or "",
                "data_entrevista": registro.get("data_hora") or registro.get("criado_em"),
            },
        })
    return saida


def motivo_da_resolucao(registro: dict[str, Any] | None, tipo: str) -> str:
    """Por que o alerta deixou de valer — gravado para auditoria."""
    if registro is None:
        return "atendimento_removido"
    estado = registro.get("estado")
    if tipo in (CLIENTE_AGUARDANDO, ESCALONAMENTO):
        if estado == at.EM_ATENDIMENTO:
            atendente = registro.get("atendente_id")
            if atendente and atendente != registro.get("responsavel_id"):
                return "assumido_por_outro"
            return "responsavel_entrou"
        if estado in (at.AGENDADA, at.CLIENTE_AGUARDANDO):
            return "cliente_saiu"
        if estado in (at.CLIENTE_FALTOU, at.CANCELADA):
            return "expirado"
        return "entrevista_finalizada"
    if tipo == DOCUMENTACAO_PENDENTE:
        return "documentacao_assumida" if estado == at.CONCLUIDA else "estado_mudou"
    return "estado_mudou"


# --------------------------------------------------------------- sincronização


def _ativos_do_atendimento(con: Any, atendimento_id: str) -> list[Any]:
    return con.execute(
        f"SELECT id, chave, tipo FROM {TABELA} WHERE atendimento_id = ? AND resolvido_em IS NULL",
        (atendimento_id,),
    ).fetchall()


def sincronizar(registro: dict[str, Any], instante: datetime | None = None) -> dict[str, int]:
    instante = instante or at._agora_dt()
    config = at.obter_config()
    alvo = {a["chave"]: a for a in desejados(registro, instante, int(config["escalonar_apos_min"]))}
    criados = resolvidos = 0
    agora_iso = instante.isoformat(timespec="seconds")
    with banco.conectar() as con:
        ativos = _ativos_do_atendimento(con, registro["id"])
        chaves_ativas = {linha["chave"] for linha in ativos}
        for linha in ativos:
            if linha["chave"] in alvo:
                continue
            con.execute(
                f"UPDATE {TABELA} SET resolvido_em = ?, motivo_resolucao = ? "
                "WHERE id = ? AND resolvido_em IS NULL",
                (agora_iso, motivo_da_resolucao(registro, linha["tipo"]), linha["id"]),
            )
            resolvidos += 1
    for chave, alerta in alvo.items():
        if chave in chaves_ativas:
            continue
        expira = (
            (instante + VIDA_MAXIMA_SALA).isoformat(timespec="seconds")
            if alerta["tipo"] in (CLIENTE_AGUARDANDO, ESCALONAMENTO) else None
        )
        try:
            with banco.conectar() as con:
                existe = con.execute(
                    f"SELECT 1 AS existe FROM {TABELA} WHERE chave = ?", (chave,)
                ).fetchone()
                if existe:
                    # Já existiu e foi resolvido: o mesmo episódio não volta a tocar.
                    continue
                con.execute(
                    f"""INSERT INTO {TABELA}
                        (id, chave, tipo, atendimento_id, destinatario_id, modulo, titulo,
                         texto, acao, dados_json, criado_em, expira_em)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        uuid.uuid4().hex, chave, alerta["tipo"], registro["id"],
                        alerta["destinatario_id"], alerta["modulo"], alerta["titulo"][:200],
                        (alerta["texto"] or "")[:1000], alerta["acao"],
                        json.dumps(alerta["dados"], ensure_ascii=False), agora_iso, expira,
                    ),
                )
            criados += 1
        except _ERROS_DE_CHAVE:
            # Outra requisição criou o mesmo alerta no mesmo instante.
            continue
    return {"criados": criados, "resolvidos": resolvidos}


_trava_varredura = threading.Lock()
_ultima_varredura = 0.0
#: A leitura de alertas também move o relógio: escalonamento e saída do cliente
#: dependem do tempo, e não de uma requisição. Sem beat dedicado, quem consulta varre.
INTERVALO_VARREDURA_S = 10.0


def varrer(instante: datetime | None = None, forcar: bool = False) -> None:
    global _ultima_varredura
    if not forcar and time.monotonic() - _ultima_varredura < INTERVALO_VARREDURA_S:
        return
    if not _trava_varredura.acquire(blocking=False):
        return
    try:
        _ultima_varredura = time.monotonic()
        at.varrer_vencidos(instante)
        for registro in at.listar(estados=[at.CLIENTE_AGUARDANDO]):
            sincronizar(registro, instante)
        _resolver_orfaos(instante)
    finally:
        _trava_varredura.release()


def _resolver_orfaos(instante: datetime | None = None) -> None:
    """Alerta cujo atendimento já não justifica nada (ou venceu o teto de vida)."""
    instante = instante or at._agora_dt()
    agora_iso = instante.isoformat(timespec="seconds")
    with banco.conectar() as con:
        linhas = con.execute(
            f"SELECT id, atendimento_id, tipo, expira_em FROM {TABELA} WHERE resolvido_em IS NULL"
        ).fetchall()
    for linha in linhas:
        vencido = linha["expira_em"] and str(linha["expira_em"]) <= agora_iso
        registro = at.obter(linha["atendimento_id"])
        if vencido or registro is None:
            with banco.conectar() as con:
                con.execute(
                    f"UPDATE {TABELA} SET resolvido_em = ?, motivo_resolucao = ? "
                    "WHERE id = ? AND resolvido_em IS NULL",
                    (agora_iso, "expirado" if vencido else "atendimento_removido", linha["id"]),
                )
        elif registro["estado"] not in (at.CLIENTE_AGUARDANDO, at.DOCUMENTACAO_PENDENTE):
            sincronizar(registro, instante)


def ativos_para(usuario_id: str, modulos: set[str] | list[str]) -> list[dict[str, Any]]:
    """O que esta pessoa deve ver agora: os dela e os do módulo que ela tem."""
    try:
        varrer()
    except Exception:  # noqa: BLE001 - a listagem segue com o que já está gravado
        log.warning("Varredura de alertas falhou.", exc_info=True)
    modulos = sorted(set(modulos))
    filtro = "destinatario_id = ?"
    params: list[Any] = [usuario_id]
    if modulos:
        filtro += f" OR modulo IN ({','.join('?' for _ in modulos)})"
        params += modulos
    agora_iso = at.agora()
    with banco.conectar() as con:
        linhas = con.execute(
            f"""SELECT * FROM {TABELA}
                 WHERE resolvido_em IS NULL AND ({filtro})
                   AND (expira_em IS NULL OR expira_em > ?)
                 ORDER BY criado_em""",
            (*params, agora_iso),
        ).fetchall()
    alertas = []
    for linha in linhas:
        dados = {}
        try:
            dados = json.loads(linha["dados_json"] or "{}")
        except ValueError:
            pass
        alertas.append({
            "id": linha["id"], "tipo": linha["tipo"], "atendimento_id": linha["atendimento_id"],
            "titulo": linha["titulo"], "texto": linha["texto"] or "", "acao": linha["acao"],
            "dados": dados, "criado_em": linha["criado_em"],
        })
    diretos = {a["atendimento_id"] for a in alertas if a["tipo"] == CLIENTE_AGUARDANDO}
    # Quem já recebeu o aviso direto não precisa do escalonamento do mesmo cliente.
    return [
        a for a in alertas
        if not (a["tipo"] == ESCALONAMENTO and a["atendimento_id"] in diretos)
        and not (a["tipo"] == ESCALONAMENTO and a["dados"].get("responsavel_id") == usuario_id)
    ]


def historico(atendimento_id: str) -> list[dict[str, Any]]:
    with banco.conectar() as con:
        linhas = con.execute(
            f"SELECT * FROM {TABELA} WHERE atendimento_id = ? ORDER BY criado_em",
            (atendimento_id,),
        ).fetchall()
    return [dict(zip(linha.keys(), linha)) for linha in linhas]
