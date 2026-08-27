"""Estado durável das automações de WhatsApp.

O texto de cobrança não é armazenado: ele é remontado a partir do checklist no
instante do envio. Assim, cada documento recebido altera automaticamente a
próxima mensagem, sem o atendente precisar editar uma cópia antiga.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pyodbc

from . import armazenamento
from .banco import conectar


def _agora_dt() -> datetime:
    return datetime.now(timezone.utc)


def _iso(valor: datetime | None = None) -> str:
    return (valor or _agora_dt()).isoformat()


def reservar(chave: str, tipo: str, destino: str, caso_id: str | None = None) -> bool:
    """Reserva um envio, impedindo duplicidade entre API e workers concorrentes."""
    instante = _iso()
    try:
        with conectar() as con:
            anterior = con.execute(
                "SELECT status FROM automacoes_whatsapp WHERE chave = ?", (chave,)
            ).fetchone()
            if anterior and anterior["status"] in ("enviando", "enviado"):
                return False
            if anterior:
                con.execute(
                    """UPDATE automacoes_whatsapp
                          SET status = 'enviando', tentativas = tentativas + 1,
                              ultimo_erro = NULL, atualizado_em = ? WHERE chave = ?""",
                    (instante, chave),
                )
            else:
                con.execute(
                    """INSERT INTO automacoes_whatsapp
                       (chave, tipo, caso_id, destino, status, tentativas, criado_em, atualizado_em)
                       VALUES (?, ?, ?, ?, 'enviando', 1, ?, ?)""",
                    (chave, tipo, caso_id, destino, instante, instante),
                )
        return True
    except pyodbc.IntegrityError:
        return False


def finalizar(chave: str, erro: str | None = None) -> None:
    instante = _iso()
    with conectar() as con:
        con.execute(
            """UPDATE automacoes_whatsapp
                  SET status = ?, ultimo_erro = ?, enviado_em = ?, atualizado_em = ?
                WHERE chave = ?""",
            ("falhou" if erro else "enviado", erro, None if erro else instante, instante, chave),
        )


def obter_cobranca(caso_id: str) -> dict[str, Any]:
    with conectar() as con:
        linha = con.execute(
            "SELECT * FROM cobrancas_documentos WHERE caso_id = ?", (caso_id,)
        ).fetchone()
    if not linha:
        return {
            "caso_id": caso_id, "ativa": False, "telefone": "", "intervalo_dias": 3,
            "incluir_opcionais": False, "proximo_envio_em": None,
            "ultimo_envio_em": None, "ultimo_erro": None,
        }
    return {
        "caso_id": linha["caso_id"], "ativa": bool(linha["ativa"]),
        "telefone": linha["telefone"], "intervalo_dias": linha["intervalo_dias"],
        "incluir_opcionais": bool(linha["incluir_opcionais"]),
        "proximo_envio_em": linha["proximo_envio_em"],
        "ultimo_envio_em": linha["ultimo_envio_em"], "ultimo_erro": linha["ultimo_erro"],
    }


def salvar_cobranca(
    caso_id: str, *, ativa: bool, telefone: str, intervalo_dias: int,
    incluir_opcionais: bool,
) -> dict[str, Any]:
    instante = _iso()
    proximo = instante if ativa else None
    with conectar() as con:
        existe = con.execute(
            "SELECT caso_id FROM cobrancas_documentos WHERE caso_id = ?", (caso_id,)
        ).fetchone()
        if existe:
            con.execute(
                """UPDATE cobrancas_documentos SET ativa = ?, telefone = ?, intervalo_dias = ?,
                   incluir_opcionais = ?, proximo_envio_em = ?, ultimo_erro = NULL,
                   atualizado_em = ? WHERE caso_id = ?""",
                (int(ativa), telefone, intervalo_dias, int(incluir_opcionais), proximo, instante, caso_id),
            )
        else:
            con.execute(
                """INSERT INTO cobrancas_documentos
                   (caso_id, ativa, telefone, intervalo_dias, incluir_opcionais,
                    proximo_envio_em, criado_em, atualizado_em)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (caso_id, int(ativa), telefone, intervalo_dias, int(incluir_opcionais), proximo, instante, instante),
            )
    return obter_cobranca(caso_id)


def listar_cobrancas_vencidas() -> list[dict[str, Any]]:
    instante = _iso()
    with conectar() as con:
        linhas = con.execute(
            """SELECT caso_id FROM cobrancas_documentos
                WHERE ativa = 1 AND telefone <> ''
                  AND (proximo_envio_em IS NULL OR proximo_envio_em <= ?)""",
            (instante,),
        ).fetchall()
    return [obter_cobranca(linha["caso_id"]) for linha in linhas]


def registrar_resultado_cobranca(
    caso_id: str, intervalo_dias: int, texto_hash: str | None, erro: str | None = None,
) -> None:
    instante = _agora_dt()
    proximo = instante + timedelta(days=intervalo_dias)
    with conectar() as con:
        con.execute(
            """UPDATE cobrancas_documentos
                  SET proximo_envio_em = ?, ultimo_envio_em = ?, ultimo_hash = ?,
                      ultimo_erro = ?, atualizado_em = ? WHERE caso_id = ?""",
            (_iso(proximo), None if erro else _iso(instante), texto_hash, erro, _iso(instante), caso_id),
        )


def caso_existe(caso_id: str) -> bool:
    return armazenamento.obter_caso(caso_id) is not None
