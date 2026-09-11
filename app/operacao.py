"""Indicadores operacionais dos colaboradores."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from . import armazenamento, auth, documentacao, revisao, usuarios

roteador = APIRouter(prefix="/api/operacao", tags=["operacao"])
PodeOperacao = Depends(auth.exigir_modulo("operacao"))

DIAS_DO_PERIODO = 30
MINUTOS_ATIVIDADE_ATIVA = 60
TAMANHO_PADRAO = 8
LIMITE_RANKING = 10
LIMITE_ALERTAS = 12
ORDEM_PADRAO = "entrevistas"
CAMPOS_DE_ORDENACAO = {
    "colaborador",
    "atividade",
    "entrevistas",
    "google",
    "roteiro",
    "ligacoes",
    "revisoes",
    "revisoes_abertas",
    "peticoes",
    "falhas_peticao",
}


def _chave(identificador: object, nome: object) -> str:
    valor = str(identificador or "").strip()
    if valor:
        return f"id:{valor}"
    texto = " ".join(str(nome or "").split())
    return f"nome:{texto.casefold()}" if texto else "nao-informado"


def _nome(nome: object) -> str:
    return " ".join(str(nome or "").split()) or "Não informado"


def _data(valor: object) -> datetime | None:
    if not isinstance(valor, str) or not valor.strip():
        return None
    try:
        instante = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
    return instante if instante.tzinfo else instante.replace(tzinfo=timezone.utc)


def _ordenar(equipe: list[dict[str, Any]], ordem: str, direcao: str) -> None:
    if ordem not in CAMPOS_DE_ORDENACAO:
        raise ValueError(f"Campo de ordenação inválido: {ordem}.")
    if direcao not in {"asc", "desc"}:
        raise ValueError(f"Direção de ordenação inválida: {direcao}.")

    campos = {
        "atividade": "em_atividade",
        "entrevistas": "entrevistas",
        "google": "google_confirmado",
        "ligacoes": "ligacoes",
        "revisoes": "revisoes",
        "revisoes_abertas": "revisoes_abertas",
        "peticoes": "peticoes_solicitadas",
        "falhas_peticao": "peticoes_falhas",
    }
    equipe.sort(key=lambda item: (item["nome"].casefold(), item["id"]))
    if ordem == "colaborador":
        if direcao == "desc":
            equipe.reverse()
        return
    if ordem == "roteiro":
        auditados = [item for item in equipe if item["roteiro_percentual"] is not None]
        nao_auditados = [item for item in equipe if item["roteiro_percentual"] is None]
        auditados.sort(key=lambda item: item["roteiro_percentual"], reverse=direcao == "desc")
        equipe[:] = auditados + nao_auditados
        return
    equipe.sort(key=lambda item: item[campos[ordem]], reverse=direcao == "desc")


def _paginar_alertas(
    colaboradores: list[dict[str, Any]], pagina: int, tamanho: int
) -> dict[str, Any]:
    total = len(colaboradores)
    tamanho_real = max(1, min(tamanho, 50))
    paginas = max(1, ceil(total / tamanho_real))
    pagina_real = min(max(1, pagina), paginas)
    inicio = (pagina_real - 1) * tamanho_real
    return {
        "total": total,
        "pagina": pagina_real,
        "tamanho": tamanho_real,
        "paginas": paginas,
        "colaboradores": colaboradores[inicio : inicio + tamanho_real],
    }


def compor(
    *,
    colaboradores: list[dict[str, Any]],
    ligacoes: list[dict[str, Any]],
    atividades: list[dict[str, Any]],
    entrevistas: list[dict[str, Any]],
    auditorias: list[dict[str, Any]],
    revisoes: list[dict[str, Any]],
    peticoes: list[dict[str, Any]],
    agora: datetime,
    busca: str = "",
    pagina: int = 1,
    tamanho: int = TAMANHO_PADRAO,
    ordem: str = ORDEM_PADRAO,
    direcao: str = "desc",
    alerta: str = "",
    alerta_pagina: int = 1,
    alerta_tamanho: int = LIMITE_ALERTAS,
) -> dict[str, Any]:
    por_colaborador: dict[str, dict[str, Any]] = {}

    def registro(identificador: object, nome: object) -> dict[str, Any]:
        chave = _chave(identificador, nome)
        if chave not in por_colaborador:
            por_colaborador[chave] = {
                "id": str(identificador or "").strip(),
                "nome": _nome(nome),
                "ligacoes": 0,
                "entrevistas": 0,
                "google_confirmado": 0,
                "google_sem_registro": 0,
                "auditorias": 0,
                "roteiro_cobertas": 0,
                "roteiro_total": 0,
                "roteiro_incertas": 0,
                "obrigatorias_ausentes": 0,
                "revisoes": 0,
                "revisoes_abertas": 0,
                "peticoes_solicitadas": 0,
                "peticoes_concluidas": 0,
                "peticoes_falhas": 0,
                "atividades": [],
                "ultima_movimentacao": None,
            }
        return por_colaborador[chave]

    def registrar_movimentacao(item: dict[str, Any], valor: object) -> None:
        instante = _data(valor)
        atual = _data(item["ultima_movimentacao"])
        if instante and (atual is None or instante > atual):
            item["ultima_movimentacao"] = instante.isoformat(timespec="seconds")

    for colaborador in colaboradores:
        registro(colaborador.get("id"), colaborador.get("nome"))
    for ligacao in ligacoes:
        item = registro(ligacao.get("atendente_id"), ligacao.get("atendente_nome"))
        item["ligacoes"] += 1
        registrar_movimentacao(item, ligacao.get("realizada_em"))
    for entrevista in entrevistas:
        item = registro(entrevista.get("entrevistador_id"), entrevista.get("entrevistador"))
        item["entrevistas"] += 1
        registrar_movimentacao(item, entrevista.get("criado_em"))
        if entrevista.get("avaliacao_google_em"):
            item["google_confirmado"] += 1
        else:
            item["google_sem_registro"] += 1
    for atividade in atividades:
        item = registro(atividade.get("entrevistador_id"), atividade.get("entrevistador_nome"))
        registrar_movimentacao(item, atividade.get("atualizado_em"))
        item["atividades"].append(
            {
                "tipo": "Entrevista guiada",
                "cliente": str(atividade.get("cliente") or "").strip() or "Cliente não informado",
                "iniciado_em": atividade.get("iniciado_em"),
                "ultima_batida_em": atividade.get("atualizado_em"),
            }
        )
    for auditoria in auditorias:
        item = registro(auditoria.get("entrevistador_id"), auditoria.get("entrevistador"))
        registrar_movimentacao(item, auditoria.get("auditado_em"))
        resultado = auditoria.get("resultado") or {}
        item["auditorias"] += 1
        item["roteiro_cobertas"] += len(resultado.get("cobertas") or [])
        item["roteiro_total"] += int(resultado.get("total_perguntas") or 0)
        item["roteiro_incertas"] += len(resultado.get("incertas") or [])
        item["obrigatorias_ausentes"] += len(resultado.get("faltando_obrigatorias") or [])
    for revisao in revisoes:
        item = registro(revisao.get("revisor_id"), revisao.get("revisor"))
        registrar_movimentacao(item, revisao.get("iniciada_em"))
        registrar_movimentacao(item, revisao.get("concluida_em"))
        if revisao.get("concluida_em"):
            item["revisoes"] += 1
        else:
            item["revisoes_abertas"] += 1
    for peticao in peticoes:
        item = registro(peticao.get("solicitante_id"), peticao.get("solicitante_nome"))
        item["peticoes_solicitadas"] += 1
        registrar_movimentacao(item, peticao.get("solicitada_em"))
        if peticao.get("status") == "completed":
            item["peticoes_concluidas"] += 1
        elif peticao.get("status") == "failed":
            item["peticoes_falhas"] += 1

    equipe = list(por_colaborador.values())
    for item in equipe:
        item["em_atividade"] = bool(item["atividades"])
        total = item["roteiro_total"]
        item["roteiro_percentual"] = round(item["roteiro_cobertas"] * 100 / total, 1) if total else None
        item["entrevistas_nao_auditadas"] = max(0, item["entrevistas"] - item["auditorias"])
    inicio_dia = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    inicio_semana = agora - timedelta(days=7)
    sem_movimentacao_hoje = []
    sem_movimentacao_7_dias = []
    for item in equipe:
        ultima_movimentacao = _data(item["ultima_movimentacao"])
        registro_alerta = {
            "id": item["id"],
            "nome": item["nome"],
            "ultima_movimentacao": item["ultima_movimentacao"],
        }
        if ultima_movimentacao is None or ultima_movimentacao < inicio_dia:
            sem_movimentacao_hoje.append(registro_alerta)
        if ultima_movimentacao is None or ultima_movimentacao < inicio_semana:
            sem_movimentacao_7_dias.append(registro_alerta)
        item.pop("ultima_movimentacao")

    sem_movimentacao_hoje.sort(key=lambda item: (item["nome"].casefold(), item["id"]))
    sem_movimentacao_7_dias.sort(key=lambda item: (item["nome"].casefold(), item["id"]))
    _ordenar(equipe, ordem, direcao)

    volumes = [item["ligacoes"] for item in equipe]
    maior = max(volumes) if volumes else None
    menor = min(volumes) if volumes else None
    busca_normalizada = " ".join(busca.split()).casefold()
    equipe_filtrada = [
        item for item in equipe if busca_normalizada in item["nome"].casefold()
    ]
    total = len(equipe_filtrada)
    paginas = max(1, ceil(total / tamanho))
    pagina_real = min(pagina, paginas)
    inicio = (pagina_real - 1) * tamanho
    ranking_ordenado = sorted(equipe, key=lambda item: (-item["ligacoes"], item["nome"]))
    ranking: list[dict[str, int | str]] = []
    for indice, item in enumerate(ranking_ordenado):
        anterior = ranking_ordenado[indice - 1] if indice else None
        posicao = (
            int(ranking[-1]["posicao"])
            if anterior and item["ligacoes"] == anterior["ligacoes"]
            else indice + 1
        )
        ranking.append(
            {
                "id": item["id"],
                "nome": item["nome"],
                "ligacoes": item["ligacoes"],
                "posicao": posicao,
            }
        )
    return {
        "periodo": {
            "de": (agora - timedelta(days=DIAS_DO_PERIODO)).isoformat(timespec="seconds"),
            "ate": agora.isoformat(timespec="seconds"),
            "dias": DIAS_DO_PERIODO,
        },
        "atividade": {"janela_minutos": MINUTOS_ATIVIDADE_ATIVA},
        "colaboradores": equipe_filtrada[inicio : inicio + tamanho],
        "paginacao": {
            "busca": busca_normalizada,
            "pagina": pagina_real,
            "tamanho": tamanho,
            "paginas": paginas,
            "total": total,
            "ordem": ordem,
            "direcao": direcao,
        },
        "alertas": {
            "sem_movimentacao_hoje": _paginar_alertas(
                sem_movimentacao_hoje,
                alerta_pagina if alerta == "hoje" else 1,
                alerta_tamanho if alerta == "hoje" else LIMITE_ALERTAS,
            ),
            "sem_movimentacao_7_dias": _paginar_alertas(
                sem_movimentacao_7_dias,
                alerta_pagina if alerta == "7-dias" else 1,
                alerta_tamanho if alerta == "7-dias" else LIMITE_ALERTAS,
            ),
        },
        "ranking_ligacoes": ranking[:LIMITE_RANKING],
        "resumo": {
            "colaboradores": len(equipe),
            "em_atividade": sum(1 for item in equipe if item["em_atividade"]),
            "ligacoes": len(ligacoes),
            "entrevistas": len(entrevistas),
            "google_confirmado": sum(item["google_confirmado"] for item in equipe),
            "auditorias": len(auditorias),
            "revisoes": sum(item["revisoes"] for item in equipe),
            "peticoes_solicitadas": len(peticoes),
            "maior_volume": [item["nome"] for item in equipe if maior is not None and item["ligacoes"] == maior],
            "menor_volume": [item["nome"] for item in equipe if menor is not None and item["ligacoes"] == menor],
        },
        "aviso": (
            "Os volumes mostram registros operacionais. Auditoria de roteiro é assistiva e só "
            "aparece após conferência manual da Supervisão; nenhum indicador mede qualidade sozinho."
        ),
        "gerado_em": agora.isoformat(timespec="seconds"),
    }


def montar(
    agora: datetime | None = None,
    busca: str = "",
    pagina: int = 1,
    tamanho: int = TAMANHO_PADRAO,
    ordem: str = ORDEM_PADRAO,
    direcao: str = "desc",
    alerta: str = "",
    alerta_pagina: int = 1,
    alerta_tamanho: int = LIMITE_ALERTAS,
) -> dict[str, Any]:
    referencia = agora or datetime.now(timezone.utc)
    desde = (referencia - timedelta(days=DIAS_DO_PERIODO)).isoformat(timespec="seconds")
    atividade_desde = (referencia - timedelta(minutes=MINUTOS_ATIVIDADE_ATIVA)).isoformat(
        timespec="seconds"
    )
    return compor(
        colaboradores=usuarios.listar_colaboradores_ativos(),
        ligacoes=armazenamento.listar_ligacoes_desde(desde),
        atividades=documentacao.listar_entrevistas_ativas(atividade_desde),
        entrevistas=armazenamento.listar_entrevistas_desde(desde),
        auditorias=armazenamento.listar_auditorias_desde(desde),
        revisoes=revisao.listar_por_periodo(desde),
        peticoes=armazenamento.listar_solicitacoes_peticao_desde(desde),
        agora=referencia,
        busca=busca,
        pagina=pagina,
        tamanho=tamanho,
        ordem=ordem,
        direcao=direcao,
        alerta=alerta,
        alerta_pagina=alerta_pagina,
        alerta_tamanho=alerta_tamanho,
    )


@roteador.get("/alertas/{periodo}", dependencies=[PodeOperacao])
def listar_alertas(
    periodo: str,
    pagina: int = Query(1, ge=1),
    tamanho: int = Query(20, ge=1, le=50),
) -> dict[str, Any]:
    chaves = {
        "hoje": "sem_movimentacao_hoje",
        "7-dias": "sem_movimentacao_7_dias",
    }
    if periodo not in chaves:
        raise HTTPException(422, "Período de alerta inválido.")
    painel = montar(alerta=periodo, alerta_pagina=pagina, alerta_tamanho=tamanho)
    return painel["alertas"][chaves[periodo]]


@roteador.get("", dependencies=[PodeOperacao])
def painel_operacional(
    busca: str = Query("", max_length=160),
    pagina: int = Query(1, ge=1),
    tamanho: int = Query(TAMANHO_PADRAO, ge=1, le=50),
    ordem: str = Query(ORDEM_PADRAO, max_length=40),
    direcao: str = Query("desc", pattern="^(asc|desc)$"),
) -> dict[str, Any]:
    if ordem not in CAMPOS_DE_ORDENACAO:
        raise HTTPException(422, "Campo de ordenação inválido.")
    return montar(busca=busca, pagina=pagina, tamanho=tamanho, ordem=ordem, direcao=direcao)
