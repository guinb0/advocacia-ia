"""Aprendizado contínuo, auditável e contextual para petições.

Histórico não é aprendizado: cada feedback fica como evento imutável; somente uma
preferência explícita ou recorrente promove uma regra reutilizável. As regras ficam
em banco separado das críticas cruas para que possam ser versionadas, medidas e
recuperadas por contexto sem despejar o histórico inteiro no prompt.
"""
from __future__ import annotations

import os
import re
import uuid
from difflib import SequenceMatcher
from time import monotonic
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


# A camada é opcional para a redação. Se o banco estiver indisponível, não se
# tenta reconectar em cada etapa da mesma geração (nem se adicionam dezenas de
# segundos à petição por telemetria).
_INDISPONIVEL_ATE = 0.0


def _url() -> str:
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.lstrip().startswith("#"):
                chave, valor = linha.split("=", 1)
                os.environ.setdefault(chave.strip(), valor.strip())
    return os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)


def _conectar(**kwargs: Any):
    if monotonic() < _INDISPONIVEL_ATE:
        raise ConnectionError("base de aprendizado temporariamente indisponível")
    return psycopg.connect(_url(), connect_timeout=10, **kwargs)


def _marcar_indisponivel() -> None:
    global _INDISPONIVEL_ATE
    _INDISPONIVEL_ATE = monotonic() + 30.0


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chave(texto: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", texto.lower()).split())[:900]


def inicializar() -> None:
    with _conectar() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS peticao_feedback_eventos (
              id uuid PRIMARY KEY, caso_id varchar(64) NOT NULL,
              categoria varchar(80) NOT NULL DEFAULT '', advogado varchar(200) NOT NULL DEFAULT '',
              document_type varchar(80) NOT NULL DEFAULT 'INITIAL_PETITION',
              tipo varchar(48) NOT NULL, texto text NOT NULL, geral boolean NOT NULL,
              versao_origem integer, versao_resultado integer, criado_em timestamptz NOT NULL DEFAULT now()
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS peticao_regras_aprendidas (
              id uuid PRIMARY KEY, chave text NOT NULL, texto text NOT NULL,
              escopo varchar(32) NOT NULL, categoria varchar(80) NOT NULL DEFAULT '',
              advogado varchar(200) NOT NULL DEFAULT '', document_type varchar(80) NOT NULL DEFAULT '',
              tipo varchar(48) NOT NULL, confidence double precision NOT NULL,
              observacoes integer NOT NULL DEFAULT 1, aplicacoes integer NOT NULL DEFAULT 0,
              aceites integer NOT NULL DEFAULT 0, rejeicoes integer NOT NULL DEFAULT 0,
              status varchar(24) NOT NULL DEFAULT 'HYPOTHESIS',
              versao integer NOT NULL DEFAULT 1, substituida_por uuid NULL,
              criada_em timestamptz NOT NULL DEFAULT now(), atualizada_em timestamptz NOT NULL DEFAULT now(),
              ultima_confirmacao timestamptz NULL, ultimo_uso timestamptz NULL
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS ix_regras_aprendidas_contexto ON peticao_regras_aprendidas (status, categoria, advogado, document_type)")
        con.execute("""
            CREATE TABLE IF NOT EXISTS peticao_skill_execucoes (
              id uuid PRIMARY KEY, generation_id varchar(80) NOT NULL, caso_id varchar(64) NOT NULL,
              skill_name varchar(80) NOT NULL, skill_version varchar(40) NOT NULL DEFAULT '1',
              status varchar(20) NOT NULL, iniciado_em timestamptz NOT NULL DEFAULT now(),
              finalizado_em timestamptz NULL, latencia_ms integer NULL, input_context_hash varchar(64),
              output_hash varchar(64), itens_recuperados jsonb NOT NULL DEFAULT '[]'::jsonb,
              confidence double precision NULL, erro text NULL, fallback_usado boolean NOT NULL DEFAULT false
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS peticao_avaliacoes_geracao (
              id uuid PRIMARY KEY, generation_id varchar(80) NOT NULL, caso_id varchar(64) NOT NULL,
              tipo varchar(40) NOT NULL, resultado varchar(16) NOT NULL, achados jsonb NOT NULL DEFAULT '[]'::jsonb,
              criado_em timestamptz NOT NULL DEFAULT now()
            )
        """)


def classificar(texto: str, *, geral: bool) -> str:
    t = _chave(texto)
    if not geral:
        return "CASE_SPECIFIC"
    if any(x in t for x in ("sempre", "todas as", "proximas pecas", "padrao", "prefer")):
        return "STYLE_PREFERENCE"
    if any(x in t for x in ("titulo", "estrutura", "seção", "secao", "pedido")):
        return "STRUCTURAL_PREFERENCE"
    return "POSSIBLE_GENERALIZATION"


def registrar_feedback(*, caso_id: str, categoria: str, advogado: str, texto: str,
                       geral: bool, versao_origem: int, versao_resultado: int,
                       document_type: str = "INITIAL_PETITION") -> dict[str, Any]:
    """Registra evento e promove regra somente com sinal explícito/recorrente."""
    inicializar()
    texto = texto.strip()
    tipo = classificar(texto, geral=geral)
    evento_id = str(uuid.uuid4())
    with _conectar(row_factory=dict_row) as con:
        con.execute("""INSERT INTO peticao_feedback_eventos
          (id,caso_id,categoria,advogado,document_type,tipo,texto,geral,versao_origem,versao_resultado)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (evento_id, caso_id, categoria, advogado, document_type, tipo, texto, geral, versao_origem, versao_resultado))
        if not geral:
            return {"event_id": evento_id, "tipo": tipo, "promovida": False}
        # O checkbox atual significa "para as próximas peças desta categoria";
        # portanto a regra é do escritório/categoria, não privada do usuário que
        # clicou. O autor continua preservado no evento acima.
        advogado_da_regra = ""
        chave = _chave(texto)
        regra = con.execute("""SELECT * FROM peticao_regras_aprendidas
          WHERE chave=%s AND categoria=%s AND advogado=%s AND document_type=%s AND status <> 'ARCHIVED'
          ORDER BY atualizada_em DESC LIMIT 1""", (chave, categoria, advogado_da_regra, document_type)).fetchone()
        if regra:
            observacoes = int(regra["observacoes"]) + 1
            confidence = min(.98, float(regra["confidence"]) + (.12 if observacoes <= 3 else .04))
            status = "ACTIVE" if observacoes >= 2 or confidence >= .8 else "HYPOTHESIS"
            con.execute("""UPDATE peticao_regras_aprendidas SET observacoes=%s, confidence=%s,
              status=%s, aceites=aceites+1, atualizada_em=now(), ultima_confirmacao=now() WHERE id=%s""",
              (observacoes, confidence, status, regra["id"]))
            return {"event_id": evento_id, "rule_id": str(regra["id"]), "tipo": tipo, "promovida": status == "ACTIVE"}
        regra_id = str(uuid.uuid4())
        # O checkbox "ensinar" é sinal forte: começa ativa, mas continua auditável.
        con.execute("""INSERT INTO peticao_regras_aprendidas
          (id,chave,texto,escopo,categoria,advogado,document_type,tipo,confidence,status,aceites,ultima_confirmacao)
          VALUES (%s,%s,%s,'CATEGORY',%s,%s,%s,%s,.82,'ACTIVE',1,now())""",
          (regra_id, chave, texto, categoria, advogado_da_regra, document_type, tipo))
        return {"event_id": evento_id, "rule_id": regra_id, "tipo": tipo, "promovida": True}


def regras_para_contexto(*, categoria: str, advogado: str = "", document_type: str = "INITIAL_PETITION", limite: int = 12) -> list[dict[str, Any]]:
    """Ranking contextual: especificidade, confiança e efetividade — não histórico bruto."""
    try:
        inicializar()
        with _conectar(row_factory=dict_row) as con:
            linhas = con.execute("""SELECT * FROM peticao_regras_aprendidas
              WHERE status='ACTIVE' AND categoria IN ('', %s) AND document_type IN ('', %s)
                AND (advogado='' OR advogado=%s)
              ORDER BY (CASE WHEN advogado=%s THEN 4 WHEN categoria=%s THEN 2 ELSE 1 END) DESC,
                confidence DESC, (aceites-rejeicoes) DESC, atualizada_em DESC LIMIT %s""",
              (categoria, document_type, advogado, advogado, categoria, limite)).fetchall()
            for linha in linhas:
                con.execute("UPDATE peticao_regras_aprendidas SET aplicacoes=aplicacoes+1, ultimo_uso=now() WHERE id=%s", (linha["id"],))
        return [{**dict(l), "id": str(l["id"])} for l in linhas]
    except Exception:
        _marcar_indisponivel()
        return []


def diff_semantico(antes: list[dict[str, Any]], depois: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Diff auditável por seção; não tenta inferir fatos jurídicos do texto puro."""
    indice_antes = {str(s.get("code") or ""): str(s.get("content") or "") for s in antes}
    indice_depois = {str(s.get("code") or ""): str(s.get("content") or "") for s in depois}
    eventos: list[dict[str, Any]] = []
    for secao in sorted(set(indice_antes) | set(indice_depois)):
        a, b = indice_antes.get(secao, ""), indice_depois.get(secao, "")
        if a == b:
            continue
        if not a:
            tipo = "SECTION_ADDED"
        elif not b:
            tipo = "SECTION_REMOVED"
        else:
            similaridade = SequenceMatcher(None, a, b).ratio()
            tipo = "REWRITTEN" if similaridade < .72 else "EDITED"
        eventos.append({"section": secao, "type": tipo, "before_chars": len(a),
                        "after_chars": len(b), "similarity": round(SequenceMatcher(None, a, b).ratio(), 3)})
    return eventos


def avaliar_documento(secoes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Críticos determinísticos, transparentes e sem expor raciocínio do modelo."""
    textos = {str(s.get("code") or ""): str(s.get("content") or "").strip() for s in secoes}
    achados: list[dict[str, Any]] = []
    obrigatorias = ("HEADING", "FACTS", "LEGAL_GROUNDS", "CLAIMS", "CLOSING")
    for codigo in obrigatorias:
        if not textos.get(codigo):
            achados.append({"critic": "consistency_check", "severity": "warning", "code": "MISSING_SECTION", "section": codigo})
    if textos.get("FACTS") and len(textos["FACTS"]) < 280:
        achados.append({"critic": "legal_critic", "severity": "warning", "code": "FACTS_TOO_SHORT", "section": "FACTS"})
    if textos.get("LEGAL_GROUNDS") and len(textos["LEGAL_GROUNDS"]) < 350:
        achados.append({"critic": "legal_critic", "severity": "warning", "code": "GROUNDS_TOO_SHORT", "section": "LEGAL_GROUNDS"})
    if "[PENDENTE:" in "\n".join(textos.values()):
        achados.append({"critic": "consistency_check", "severity": "info", "code": "PENDING_INFORMATION"})
    return achados


def registrar_execucao(*, generation_id: str, caso_id: str, skill_name: str, status: str = "DONE",
                       itens_recuperados: list[dict[str, Any]] | None = None, confidence: float | None = None,
                       erro: str | None = None, fallback_usado: bool = False) -> None:
    try:
        import hashlib
        inicializar()
        resumo = repr(itens_recuperados or []).encode("utf-8")
        with _conectar() as con:
            con.execute("""INSERT INTO peticao_skill_execucoes
              (id,generation_id,caso_id,skill_name,status,finalizado_em,itens_recuperados,confidence,erro,fallback_usado,output_hash)
              VALUES (%s,%s,%s,%s,%s,now(),%s::jsonb,%s,%s,%s,%s)""",
              (str(uuid.uuid4()), generation_id, caso_id, skill_name, status,
               __import__("json").dumps(itens_recuperados or []), confidence, erro, fallback_usado,
               hashlib.sha256(resumo).hexdigest()))
    except Exception:
        # Observabilidade nunca pode impedir protocolo ou revisão.
        _marcar_indisponivel()
        return


def registrar_avaliacao(*, generation_id: str, caso_id: str, tipo: str, achados: list[dict[str, Any]]) -> None:
    try:
        inicializar()
        with _conectar() as con:
            con.execute("""INSERT INTO peticao_avaliacoes_geracao (id,generation_id,caso_id,tipo,resultado,achados)
                VALUES (%s,%s,%s,%s,%s,%s::jsonb)""",
                (str(uuid.uuid4()), generation_id, caso_id, tipo, "WARNING" if achados else "PASS",
                 __import__("json").dumps(achados)))
    except Exception:
        _marcar_indisponivel()
        return


def estatisticas() -> dict[str, Any]:
    """Métricas agregadas para painel; não devolve conteúdo de petições."""
    try:
        inicializar()
        with _conectar(row_factory=dict_row) as con:
            regras = con.execute("""SELECT count(*) AS total,
                count(*) FILTER (WHERE status='ACTIVE') AS ativas,
                count(*) FILTER (WHERE status='HYPOTHESIS') AS hipoteses,
                coalesce(sum(aplicacoes),0) AS aplicacoes FROM peticao_regras_aprendidas""").fetchone()
            skills = con.execute("SELECT skill_name, count(*) AS execucoes FROM peticao_skill_execucoes GROUP BY skill_name ORDER BY execucoes DESC").fetchall()
        return {"rules": dict(regras), "skills": [dict(s) for s in skills]}
    except Exception:
        _marcar_indisponivel()
        return {"rules": {"total": 0, "ativas": 0, "hipoteses": 0, "aplicacoes": 0}, "skills": []}
