"""Estado durável do pipeline documental orientado a evidências.

O OCR bruto, a classificação, a extração e a validação têm ciclos de vida
distintos. Guardá-los somente em ``entregas.extracao_json`` fazia qualquer nova
tentativa substituir a explicação anterior e obrigava a repetir OCR para testar
um classificador novo. Este módulo registra uma execução e suas etapas de forma
idempotente; ``extracao_json`` continua sendo a projeção compatível para a UI.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from . import banco

VERSAO_PIPELINE = "mistral-documentos-v1"

ETAPAS: tuple[tuple[str, int], ...] = (
    ("ocr_mistral", 10),
    ("classificar_documento", 20),
    ("extrair_schema_especifico", 30),
    ("validar_e_conciliar", 40),
    ("extrair_evidencias", 50),
    ("revisao_humana", 60),
    ("resumo_do_caso", 70),
)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(valor: Any) -> str:
    return json.dumps(valor if valor is not None else {}, ensure_ascii=False)


def _carregar(valor: Any, padrao: Any) -> Any:
    if isinstance(valor, (dict, list)):
        return valor
    if not valor:
        return padrao
    try:
        return json.loads(str(valor))
    except (TypeError, ValueError, json.JSONDecodeError):
        return padrao


def criar(
    entrega_id: str,
    caso_id: str,
    *,
    contexto: dict[str, Any],
    hash_conteudo: str | None = None,
) -> dict[str, Any]:
    """Cria ou reinicia a execução sem apagar feedback e histórico de correção."""
    existente = obter_por_entrega(entrega_id)
    agora = _agora()
    analise_id = existente["id"] if existente else str(uuid.uuid4())
    with banco.conectar() as con:
        if existente:
            con.execute(
                """
                UPDATE analises_documento
                   SET status = 'NA_FILA', etapa_atual = 'ocr_mistral',
                       revisao_necessaria = 0, motivo_revisao = NULL,
                       versao_pipeline = ?, hash_conteudo = ?, contexto_json = ?,
                       resultado_json = '{}', resumo_json = '{}',
                       atualizado_em = ?, finalizado_em = NULL
                 WHERE id = ?
                """,
                (VERSAO_PIPELINE, hash_conteudo, _json(contexto), agora, analise_id),
            )
            con.execute("DELETE FROM analise_documento_etapas WHERE analise_id = ?", (analise_id,))
        else:
            con.execute(
                """
                INSERT INTO analises_documento
                    (id, entrega_id, caso_id, status, etapa_atual, revisao_necessaria,
                     versao_pipeline, hash_conteudo, contexto_json, resultado_json,
                     resumo_json, criado_em, atualizado_em)
                VALUES (?, ?, ?, 'NA_FILA', 'ocr_mistral', 0, ?, ?, ?, '{}', '{}', ?, ?)
                """,
                (
                    analise_id,
                    entrega_id,
                    caso_id,
                    VERSAO_PIPELINE,
                    hash_conteudo,
                    _json(contexto),
                    agora,
                    agora,
                ),
            )
        for etapa, ordem in ETAPAS:
            con.execute(
                """
                INSERT INTO analise_documento_etapas
                    (id, analise_id, etapa, ordem, status, tentativas, versao,
                     resultado_json, criado_em)
                VALUES (?, ?, ?, ?, 'PENDENTE', 0, ?, '{}', ?)
                """,
                (str(uuid.uuid4()), analise_id, etapa, ordem, VERSAO_PIPELINE, agora),
            )
    return obter(analise_id) or {"id": analise_id}


def _normalizar(registro: dict[str, Any] | None, *, incluir_etapas: bool = True) -> dict[str, Any] | None:
    if not registro:
        return None
    saida = dict(registro)
    saida["revisao_necessaria"] = bool(saida.get("revisao_necessaria"))
    saida["contexto"] = _carregar(saida.pop("contexto_json", None), {})
    saida["resultado"] = _carregar(saida.pop("resultado_json", None), {})
    saida["resumo"] = _carregar(saida.pop("resumo_json", None), {})
    if incluir_etapas:
        saida["etapas"] = listar_etapas(str(saida["id"]))
    return saida


def obter(analise_id: str) -> dict[str, Any] | None:
    with banco.conectar() as con:
        linha = con.execute(
            "SELECT * FROM analises_documento WHERE id = ?", (analise_id,)
        ).fetchone()
    return _normalizar(dict(linha) if linha else None)


def obter_por_entrega(entrega_id: str) -> dict[str, Any] | None:
    with banco.conectar() as con:
        linha = con.execute(
            "SELECT * FROM analises_documento WHERE entrega_id = ?", (entrega_id,)
        ).fetchone()
    return _normalizar(dict(linha) if linha else None)


def listar_etapas(analise_id: str) -> list[dict[str, Any]]:
    with banco.conectar() as con:
        linhas = con.execute(
            """
            SELECT etapa, ordem, status, tentativas, modelo, versao, resultado_json,
                   erro, duracao_ms, iniciado_em, finalizado_em
              FROM analise_documento_etapas
             WHERE analise_id = ? ORDER BY ordem
            """,
            (analise_id,),
        ).fetchall()
    saida = []
    for linha in linhas:
        item = dict(linha)
        item["resultado"] = _carregar(item.pop("resultado_json", None), {})
        saida.append(item)
    return saida


def resultado_etapa(analise_id: str, etapa: str) -> dict[str, Any]:
    with banco.conectar() as con:
        linha = con.execute(
            """SELECT resultado_json FROM analise_documento_etapas
                 WHERE analise_id = ? AND etapa = ?""",
            (analise_id, etapa),
        ).fetchone()
    return _carregar(linha["resultado_json"] if linha else None, {})


def iniciar_etapa(analise_id: str, etapa: str, *, modelo: str | None = None) -> None:
    agora = _agora()
    with banco.conectar() as con:
        con.execute(
            """
            UPDATE analise_documento_etapas
               SET status = 'PROCESSANDO', tentativas = tentativas + 1,
                   modelo = COALESCE(?, modelo), iniciado_em = ?, erro = NULL
             WHERE analise_id = ? AND etapa = ?
            """,
            (modelo, agora, analise_id, etapa),
        )
        con.execute(
            """UPDATE analises_documento
                  SET status = 'PROCESSANDO', etapa_atual = ?, atualizado_em = ?
                WHERE id = ?""",
            (etapa, agora, analise_id),
        )


def concluir_etapa(
    analise_id: str,
    etapa: str,
    resultado: dict[str, Any],
    *,
    duracao_ms: int,
    modelo: str | None = None,
) -> None:
    agora = _agora()
    with banco.conectar() as con:
        con.execute(
            """
            UPDATE analise_documento_etapas
               SET status = 'CONCLUIDA', resultado_json = ?, duracao_ms = ?,
                   modelo = COALESCE(?, modelo), erro = NULL, finalizado_em = ?
             WHERE analise_id = ? AND etapa = ?
            """,
            (_json(resultado), duracao_ms, modelo, agora, analise_id, etapa),
        )
        mestre = con.execute(
            "SELECT resultado_json FROM analises_documento WHERE id = ?", (analise_id,)
        ).fetchone()
        acumulado = _carregar(mestre["resultado_json"] if mestre else None, {})
        acumulado[etapa] = resultado
        con.execute(
            "UPDATE analises_documento SET resultado_json = ?, atualizado_em = ? WHERE id = ?",
            (_json(acumulado), agora, analise_id),
        )


def pular_etapa(analise_id: str, etapa: str, motivo: str) -> None:
    agora = _agora()
    with banco.conectar() as con:
        con.execute(
            """UPDATE analise_documento_etapas
                  SET status = 'IGNORADA', erro = ?, finalizado_em = ?
                WHERE analise_id = ? AND etapa = ?""",
            (motivo[:1600], agora, analise_id, etapa),
        )


def falhar_etapa(analise_id: str, etapa: str, erro: str) -> None:
    agora = _agora()
    with banco.conectar() as con:
        con.execute(
            """UPDATE analise_documento_etapas
                  SET status = 'FALHOU', erro = ?, finalizado_em = ?
                WHERE analise_id = ? AND etapa = ?""",
            (erro[:1600], agora, analise_id, etapa),
        )
        con.execute(
            """UPDATE analises_documento
                  SET status = 'FALHOU', etapa_atual = ?, atualizado_em = ?,
                      motivo_revisao = ? WHERE id = ?""",
            (etapa, agora, erro[:1200], analise_id),
        )


def aguardar_revisao(analise_id: str, motivos: list[str]) -> None:
    agora = _agora()
    motivo = " ".join(dict.fromkeys(m.strip() for m in motivos if m.strip()))[:1200]
    with banco.conectar() as con:
        con.execute(
            """UPDATE analise_documento_etapas
                  SET status = 'AGUARDANDO_REVISAO', erro = ?, iniciado_em = ?
                WHERE analise_id = ? AND etapa = 'revisao_humana'""",
            (motivo, agora, analise_id),
        )
        con.execute(
            """UPDATE analises_documento
                  SET status = 'REVISAO_NECESSARIA', etapa_atual = 'revisao_humana',
                      revisao_necessaria = 1, motivo_revisao = ?, atualizado_em = ?
                WHERE id = ?""",
            (motivo, agora, analise_id),
        )


# Nome anterior preservado para extensoes locais que ja o importem.
solicitar_revisao = aguardar_revisao


def concluir(analise_id: str, resumo: dict[str, Any]) -> None:
    agora = _agora()
    with banco.conectar() as con:
        con.execute(
            """UPDATE analises_documento
                  SET status = 'CONCLUIDA', etapa_atual = 'resumo_do_caso',
                      revisao_necessaria = 0, motivo_revisao = NULL,
                      resumo_json = ?, atualizado_em = ?, finalizado_em = ?
                WHERE id = ?""",
            (_json(resumo), agora, agora, analise_id),
        )


def registrar_feedback(
    analise_id: str,
    entrega_id: str,
    *,
    etapa: str,
    campo: str,
    valor_anterior: Any,
    valor_correto: Any,
    motivo: str,
    corrigido_por: str,
) -> None:
    with banco.conectar() as con:
        con.execute(
            """
            INSERT INTO analise_documento_feedback
                (id, analise_id, entrega_id, etapa, campo, valor_anterior,
                 valor_correto, motivo, corrigido_por, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()), analise_id, entrega_id, etapa, campo[:120],
                str(valor_anterior or "")[:800] or None,
                str(valor_correto or "")[:800] or None,
                motivo[:800] or None, corrigido_por[:200], _agora(),
            ),
        )


def memoria_feedback(*, etapa: str, campo: str, limite: int = 20) -> list[dict[str, Any]]:
    """Exemplos corrigidos sem OCR bruto, para avaliar erros recorrentes."""
    with banco.conectar() as con:
        linhas = con.execute(
            """
            SELECT valor_anterior, valor_correto, motivo, corrigido_por, criado_em
              FROM analise_documento_feedback
             WHERE etapa = ? AND campo = ?
             ORDER BY criado_em DESC
            """,
            (etapa, campo),
        ).fetchall()
    return [dict(linha) for linha in linhas[:limite]]


def reiniciar_desde(analise_id: str, etapa: str) -> dict[str, Any]:
    """Invalida uma etapa e as posteriores, preservando OCR e feedback anteriores."""
    ordens = dict(ETAPAS)
    if etapa not in ordens or etapa == "ocr_mistral":
        raise ValueError("O reprocessamento sem novo upload deve começar após o OCR.")
    analise = obter(analise_id)
    if not analise:
        raise ValueError("Análise documental não encontrada.")
    agora = _agora()
    resultado = dict(analise.get("resultado") or {})
    invalidar = [nome for nome, ordem in ETAPAS if ordem >= ordens[etapa]]
    for nome in invalidar:
        resultado.pop(nome, None)
    with banco.conectar() as con:
        con.execute(
            """UPDATE analise_documento_etapas
                  SET status = 'PENDENTE', resultado_json = '{}', erro = NULL,
                      duracao_ms = NULL, iniciado_em = NULL, finalizado_em = NULL
                WHERE analise_id = ? AND ordem >= ?""",
            (analise_id, ordens[etapa]),
        )
        con.execute(
            """UPDATE analises_documento
                  SET status = 'NA_FILA', etapa_atual = ?, revisao_necessaria = 0,
                      motivo_revisao = NULL, resultado_json = ?, resumo_json = '{}',
                      atualizado_em = ?, finalizado_em = NULL
                WHERE id = ?""",
            (etapa, _json(resultado), agora, analise_id),
        )
    return obter(analise_id) or {}
