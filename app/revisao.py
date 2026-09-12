"""Revisão de petições: fila do que revisar, aprovação e métricas do revisor.

O revisor (perfil `revisor`) vê as petições em revisão, ABRE uma — o que registra
o INÍCIO — e depois aprova ou devolve para ajustes, o que registra a CONCLUSÃO. O
tempo entre os dois e a contagem por revisor são as métricas de atividade.

As métricas são OPERACIONAIS: dizem quanto foi revisado e em quanto tempo, não se
a revisão foi boa. Não devem ser usadas isoladamente como avaliação de qualidade
(é a observação expressa da issue).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .banco import PREFIXO, SCHEMA, conectar

log = logging.getLogger("revisao")

#: Nome curto (o `banco._qualificar` traduz para `dbo.acervo_revisoes`).
_TABELA = "revisoes"

#: Estados da petição em `peticoes_locais.status`.
EM_REVISAO = "IN_REVIEW"
APROVADA = "APPROVED"
EM_AJUSTE = "CHANGES_REQUESTED"

#: Como uma revisão termina.
RESULTADO_STATUS = {"aprovada": APROVADA, "ajustes": EM_AJUSTE}

ESQUEMA = f"""
IF OBJECT_ID('{SCHEMA}.{PREFIXO}{_TABELA}') IS NULL
CREATE TABLE {SCHEMA}.{PREFIXO}{_TABELA} (
    id           int          IDENTITY(1,1) NOT NULL CONSTRAINT pk_acervo_revisoes PRIMARY KEY,
    caso_id      varchar(64)  NOT NULL,
    versao       int          NOT NULL CONSTRAINT df_acervo_revisoes_versao DEFAULT 1,
    revisor      varchar(200) NOT NULL,
    revisor_id   varchar(160) NULL,
    iniciada_em  varchar(40)  NOT NULL,
    concluida_em varchar(40)  NULL,
    resultado    varchar(20)  NULL,
    criado_em    varchar(40)  NOT NULL
)
"""


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def inicializar() -> None:
    """Cria a tabela de revisões se ainda não existir. Chamado no start (main)."""
    with conectar() as con:
        con.execute(ESQUEMA)
        con.execute(
            f"IF COL_LENGTH('{SCHEMA}.{PREFIXO}{_TABELA}', 'revisor_id') IS NULL "
            f"ALTER TABLE {SCHEMA}.{PREFIXO}{_TABELA} ADD revisor_id varchar(160) NULL"
        )
        con.execute(
            f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'idx_acervo_revisoes_iniciada') "
            f"CREATE INDEX idx_acervo_revisoes_iniciada ON {SCHEMA}.{PREFIXO}{_TABELA} (iniciada_em DESC)"
        )
        con.execute(
            f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'idx_acervo_revisoes_concluida') "
            f"CREATE INDEX idx_acervo_revisoes_concluida ON {SCHEMA}.{PREFIXO}{_TABELA} (concluida_em DESC)"
        )
        con.commit()


def fila_pendentes() -> list[dict[str, Any]]:
    """Petições que precisam de revisão (status IN_REVIEW), da mais antiga p/ nova.

    Traz o cliente e a versão, e — se já houver uma revisão ABERTA desta versão —
    quem a está conduzindo e desde quando, para a tela não deixar dois revisores
    no mesmo documento sem saber um do outro.
    """
    with conectar() as con:
        linhas = con.execute(
            """
            SELECT p.caso_id, p.versao, p.status, p.atualizado_em,
                   c.cliente, c.categoria,
                   r.revisor AS revisor_andamento, r.iniciada_em AS andamento_desde
              FROM peticoes_locais p
              JOIN casos c ON c.id = p.caso_id
              LEFT JOIN revisoes r
                     ON r.caso_id = p.caso_id AND r.versao = p.versao
                        AND r.concluida_em IS NULL
             WHERE p.status = ?
             ORDER BY p.atualizado_em ASC
            """,
            (EM_REVISAO,),
        ).fetchall()
    return [dict(l) for l in linhas]


def _versao_atual(con: Any, caso_id: str) -> int:
    linha = con.execute(
        "SELECT versao FROM peticoes_locais WHERE caso_id = ?", (caso_id,)
    ).fetchone()
    return int(linha["versao"]) if linha else 1


def iniciar(caso_id: str, revisor: str, revisor_id: str = "") -> dict[str, Any]:
    """Registra o início da revisão desta versão por este revisor (idempotente).

    Abrir de novo a mesma versão não cria uma segunda contagem: reaproveita a
    revisão aberta. Assim, sair e voltar à tela não infla o tempo nem o número.
    """
    agora = _agora()
    with conectar() as con:
        versao = _versao_atual(con, caso_id)
        aberta = con.execute(
            """
            SELECT id, iniciada_em FROM revisoes
             WHERE caso_id = ? AND versao = ? AND revisor = ? AND concluida_em IS NULL
            """,
            (caso_id, versao, revisor),
        ).fetchone()
        if aberta:
            return {"caso_id": caso_id, "versao": versao, "iniciada_em": str(aberta["iniciada_em"]), "reaberta": True}
        con.execute(
            """
            INSERT INTO revisoes (caso_id, versao, revisor, revisor_id, iniciada_em, criado_em)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (caso_id, versao, revisor, revisor_id.strip(), agora, agora),
        )
        con.commit()
    return {"caso_id": caso_id, "versao": versao, "iniciada_em": agora, "reaberta": False}


def concluir(caso_id: str, revisor: str, resultado: str, revisor_id: str = "") -> dict[str, Any]:
    """Fecha a revisão aberta e move a petição para aprovada ou em ajustes.

    `resultado`: "aprovada" ou "ajustes". Sem revisão aberta (o revisor concluiu
    sem ter aberto), abre e fecha na hora — o registro nunca fica sem início.
    """
    if resultado not in RESULTADO_STATUS:
        raise ValueError(f"Resultado inválido: {resultado!r}. Use um de {sorted(RESULTADO_STATUS)}.")
    agora = _agora()
    with conectar() as con:
        versao = _versao_atual(con, caso_id)
        aberta = con.execute(
            """
            SELECT id, iniciada_em FROM revisoes
             WHERE caso_id = ? AND versao = ? AND revisor = ? AND concluida_em IS NULL
             ORDER BY id DESC
            """,
            (caso_id, versao, revisor),
        ).fetchone()
        if aberta:
            con.execute(
                "UPDATE revisoes SET concluida_em = ?, resultado = ? WHERE id = ?",
                (agora, resultado, aberta["id"]),
            )
            iniciada = str(aberta["iniciada_em"])
        else:
            con.execute(
                """
                INSERT INTO revisoes (caso_id, versao, revisor, revisor_id, iniciada_em, concluida_em, resultado, criado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (caso_id, versao, revisor, revisor_id.strip(), agora, agora, resultado, agora),
            )
            iniciada = agora
        con.execute(
            "UPDATE peticoes_locais SET status = ?, atualizado_em = ? WHERE caso_id = ?",
            (RESULTADO_STATUS[resultado], agora, caso_id),
        )
        con.commit()
    return {
        "caso_id": caso_id,
        "versao": versao,
        "resultado": resultado,
        "status_peticao": RESULTADO_STATUS[resultado],
        "iniciada_em": iniciada,
        "concluida_em": agora,
        "duracao_s": _duracao_s(iniciada, agora),
    }


def _duracao_s(inicio: str, fim: str) -> int:
    try:
        return max(0, int((_parse(fim) - _parse(inicio)).total_seconds()))
    except Exception:  # noqa: BLE001 - data malformada não derruba a métrica
        return 0


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def metricas(revisor: str | None = None, revisor_id: str = "") -> dict[str, Any]:
    """Consolida a atividade de revisão: quantas, tempo médio, e o corte por revisor.

    `revisor` filtra para o próprio painel do revisor; sem ele, é o panorama do
    escritório. Só conta revisões CONCLUÍDAS — as abertas ainda não têm duração.

    O FILTRO PREFERE O `revisor_id`, E NÃO O NOME
    
    O recorte "minhas revisões" era feito pelo nome de exibição. Dois revisores
    homônimos — "Ana Silva" e "Ana Silva" — viam as revisões um do outro como
    próprias, e quem tivesse o nome editado (o gestor edita usuário, ver
    `app/usuarios.py`) perdia de vista tudo o que já havia revisado. O id existe
    na tabela justamente para isso e não estava sendo usado.
    
    O nome segue valendo para as linhas ANTIGAS: `revisor_id` entrou por
    `ALTER TABLE` e está NULL nelas, então filtrar só por id apagaria o histórico
    de antes da coluna. O agrupamento de `por_revisor` continua pelo nome, que é
    o que a tela mostra.
    """
    if revisor_id:
        filtro = " AND (revisor_id = ? OR (revisor_id IS NULL AND revisor = ?))"
        params: tuple[Any, ...] = (revisor_id, revisor or "")
    elif revisor:
        filtro = " AND revisor = ?"
        params = (revisor,)
    else:
        filtro = ""
        params = ()
    with conectar() as con:
        concluidas = con.execute(
            f"""
            SELECT revisor, iniciada_em, concluida_em, resultado
              FROM revisoes
             WHERE concluida_em IS NOT NULL{filtro}
            """,
            params,
        ).fetchall()
        abertas = con.execute(
            f"SELECT COUNT(*) AS n FROM revisoes WHERE concluida_em IS NULL{filtro}",
            params,
        ).fetchone()

    duracoes = [_duracao_s(str(l["iniciada_em"]), str(l["concluida_em"])) for l in concluidas]
    por_revisor: dict[str, dict[str, Any]] = {}
    for linha, dur in zip(concluidas, duracoes):
        nome = str(linha["revisor"])
        alvo = por_revisor.setdefault(nome, {"revisor": nome, "revisadas": 0, "aprovadas": 0, "ajustes": 0, "tempo_total_s": 0})
        alvo["revisadas"] += 1
        alvo["tempo_total_s"] += dur
        if str(linha["resultado"]) == "aprovada":
            alvo["aprovadas"] += 1
        elif str(linha["resultado"]) == "ajustes":
            alvo["ajustes"] += 1
    for alvo in por_revisor.values():
        alvo["tempo_medio_s"] = round(alvo["tempo_total_s"] / alvo["revisadas"]) if alvo["revisadas"] else 0

    total = len(concluidas)
    return {
        "revisadas": total,
        "aprovadas": sum(1 for l in concluidas if str(l["resultado"]) == "aprovada"),
        "ajustes": sum(1 for l in concluidas if str(l["resultado"]) == "ajustes"),
        "em_andamento": int(abertas["n"]) if abertas else 0,
        "tempo_medio_s": round(sum(duracoes) / total) if total else 0,
        "por_revisor": sorted(por_revisor.values(), key=lambda x: x["revisadas"], reverse=True),
        "aviso": (
            "Métricas de atividade operacional (volume e tempo). Não medem a "
            "qualidade da revisão e não devem ser usadas isoladamente para avaliá-la."
        ),
    }


def listar_por_periodo(desde: str) -> list[dict[str, Any]]:
    with conectar() as con:
        linhas = con.execute(
            "SELECT revisor, revisor_id, iniciada_em, concluida_em, resultado FROM revisoes "
            "WHERE iniciada_em >= ? OR concluida_em >= ?",
            (desde, desde),
        ).fetchall()
    return [dict(linha) for linha in linhas]
