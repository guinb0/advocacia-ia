"""Indicadores operacionais por colaborador.

    .venv\Scripts\python.exe -m tests.test_operacao
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import operacao


AGORA = datetime(2026, 9, 9, 15, 0, tzinfo=timezone.utc)
falhas = 0


def checar(condicao: bool, descricao: str, detalhe: str = "") -> None:
    global falhas
    if condicao:
        print(f"  PASS  {descricao}")
    else:
        falhas += 1
        print(f"  FALHA {descricao}" + (f"\n          {detalhe}" if detalhe else ""))


def main() -> int:
    montado = operacao.compor(
        colaboradores=[
            {"id": "ana", "nome": "Ana Silva"},
            {"id": "bruno", "nome": "Bruno Lima"},
            {"id": "carla", "nome": "Carla Reis"},
        ],
        ligacoes=[
            {"atendente_id": "ana", "atendente_nome": "Ana Silva"},
            {"atendente_id": "ana", "atendente_nome": "Ana Silva"},
            {"atendente_id": "bruno", "atendente_nome": "Bruno Lima"},
        ],
        atividades=[
            {
                "entrevistador_id": "bruno",
                "entrevistador_nome": "Bruno Lima",
                "cliente": "Cliente em atendimento",
                "iniciado_em": "2026-09-09T14:00:00+00:00",
                "atualizado_em": "2026-09-09T14:50:00+00:00",
            }
        ],
        entrevistas=[
            {"entrevistador_id": "ana", "entrevistador": "Ana Silva", "avaliacao_google_em": "x"},
            {"entrevistador_id": "ana", "entrevistador": "Ana Silva", "avaliacao_google_em": None},
            {"entrevistador_id": "bruno", "entrevistador": "Bruno Lima", "avaliacao_google_em": None},
        ],
        auditorias=[
            {
                "entrevistador_id": "ana",
                "entrevistador": "Ana Silva",
                "resultado": {
                    "total_perguntas": 10,
                    "cobertas": [{"id": "a"}] * 8,
                    "incertas": [{"id": "i"}],
                    "faltando_obrigatorias": [{"id": "f"}],
                },
            }
        ],
        revisoes=[
            {"revisor_id": "bruno", "revisor": "Bruno Lima", "concluida_em": "x"},
            {"revisor_id": "bruno", "revisor": "Bruno Lima", "concluida_em": None},
        ],
        peticoes=[
            {"solicitante_id": "ana", "solicitante_nome": "Ana Silva", "status": "completed"},
            {"solicitante_id": "ana", "solicitante_nome": "Ana Silva", "status": "failed"},
        ],
        agora=AGORA,
    )
    por_nome = {item["nome"]: item for item in montado["colaboradores"]}

    checar(por_nome["Ana Silva"]["ligacoes"] == 2, "soma ligações por colaborador")
    checar(por_nome["Ana Silva"]["entrevistas"] == 2, "conta entrevistas no período")
    checar(por_nome["Ana Silva"]["google_confirmado"] == 1, "conta confirmação do Google")
    checar(por_nome["Ana Silva"]["roteiro_percentual"] == 80.0, "calcula cobertura auditada")
    checar(por_nome["Ana Silva"]["entrevistas_nao_auditadas"] == 1, "declara entrevista não auditada")
    checar(por_nome["Bruno Lima"]["revisoes"] == 1, "conta revisões concluídas")
    checar(por_nome["Bruno Lima"]["revisoes_abertas"] == 1, "separa revisões abertas")
    checar(por_nome["Ana Silva"]["peticoes_falhas"] == 1, "conta falhas de geração")
    checar(por_nome["Carla Reis"]["entrevistas"] == 0, "inclui colaborador sem atividade")
    checar(montado["resumo"]["maior_volume"] == ["Ana Silva"], "identifica maior volume")
    checar(montado["paginacao"]["total"] == 3, "informa o total para paginação")
    checar(
        montado["ranking_ligacoes"][0]
        == {"id": "ana", "nome": "Ana Silva", "ligacoes": 2, "posicao": 1},
        "ordena ranking de ligações",
    )

    paginado = operacao.compor(
        colaboradores=[
            {"id": "ana", "nome": "Ana Silva"},
            {"id": "bruno", "nome": "Bruno Lima"},
            {"id": "carla", "nome": "Carla Reis"},
        ],
        ligacoes=[],
        atividades=[],
        entrevistas=[],
        auditorias=[],
        revisoes=[],
        peticoes=[],
        agora=AGORA,
        busca="a",
        pagina=2,
        tamanho=1,
    )
    checar(paginado["paginacao"]["total"] == 3, "filtra colaboradores no backend")
    checar(paginado["colaboradores"][0]["nome"] == "Bruno Lima", "retorna apenas a página solicitada")

    por_ligacoes = operacao.compor(
        colaboradores=[
            {"id": "ana", "nome": "Ana Silva"},
            {"id": "bruno", "nome": "Bruno Lima"},
            {"id": "carla", "nome": "Carla Reis"},
        ],
        ligacoes=[
            {"atendente_id": "ana", "atendente_nome": "Ana Silva"},
            {"atendente_id": "ana", "atendente_nome": "Ana Silva"},
            {"atendente_id": "bruno", "atendente_nome": "Bruno Lima"},
        ],
        atividades=[],
        entrevistas=[],
        auditorias=[],
        revisoes=[],
        peticoes=[],
        agora=AGORA,
        ordem="ligacoes",
        direcao="desc",
        pagina=2,
        tamanho=1,
    )
    checar(
        por_ligacoes["colaboradores"][0]["nome"] == "Bruno Lima",
        "ordena antes de paginar a equipe",
    )

    instante = AGORA.isoformat()
    alertas = operacao.compor(
        colaboradores=[
            {"id": "ligacao", "nome": "Ligação"},
            {"id": "atividade", "nome": "Atividade"},
            {"id": "entrevista", "nome": "Entrevista"},
            {"id": "auditoria", "nome": "Auditoria"},
            {"id": "revisao", "nome": "Revisão"},
            {"id": "peticao", "nome": "Petição"},
            {"id": "inativo", "nome": "Inativo"},
        ],
        ligacoes=[{"atendente_id": "ligacao", "atendente_nome": "Ligação", "realizada_em": instante}],
        atividades=[
            {
                "entrevistador_id": "atividade",
                "entrevistador_nome": "Atividade",
                "atualizado_em": instante,
            }
        ],
        entrevistas=[{"entrevistador_id": "entrevista", "entrevistador": "Entrevista", "criado_em": instante}],
        auditorias=[
            {
                "entrevistador_id": "auditoria",
                "entrevistador": "Auditoria",
                "auditado_em": instante,
            }
        ],
        revisoes=[{"revisor_id": "revisao", "revisor": "Revisão", "iniciada_em": instante}],
        peticoes=[{"solicitante_id": "peticao", "solicitante_nome": "Petição", "solicitada_em": instante}],
        agora=AGORA,
    )
    checar(
        alertas["alertas"]["sem_movimentacao_hoje"]["colaboradores"] == [
            {"id": "inativo", "nome": "Inativo", "ultima_movimentacao": None}
        ],
        "alerta diário considera todas as fontes de movimentação",
    )
    checar(
        alertas["alertas"]["sem_movimentacao_7_dias"]["total"] == 1,
        "alerta semanal identifica ausência por sete dias",
    )

    alerta_paginado = operacao.compor(
        colaboradores=[
            {"id": "ana", "nome": "Ana"},
            {"id": "bruno", "nome": "Bruno"},
            {"id": "carla", "nome": "Carla"},
        ],
        ligacoes=[],
        atividades=[],
        entrevistas=[],
        auditorias=[],
        revisoes=[],
        peticoes=[],
        agora=AGORA,
        alerta="hoje",
        alerta_pagina=2,
        alerta_tamanho=1,
    )
    checar(
        alerta_paginado["alertas"]["sem_movimentacao_hoje"]["colaboradores"][0]["nome"] == "Bruno",
        "pagina a lista completa de alertas no backend",
    )

    with (
        patch.object(operacao.usuarios, "listar_colaboradores_ativos", return_value=[]),
        patch.object(operacao.armazenamento, "listar_ligacoes_desde", return_value=[]) as ligacoes,
        patch.object(operacao.documentacao, "listar_entrevistas_ativas", return_value=[]) as ativas,
        patch.object(operacao.armazenamento, "listar_entrevistas_desde", return_value=[]),
        patch.object(operacao.armazenamento, "listar_auditorias_desde", return_value=[]),
        patch.object(operacao.revisao, "listar_por_periodo", return_value=[]),
        patch.object(operacao.armazenamento, "listar_solicitacoes_peticao_desde", return_value=[]),
    ):
        vazio = operacao.montar(AGORA)
    checar(vazio["colaboradores"] == [], "não inventa colaboradores sem fontes")
    checar(ligacoes.call_args.args[0] == "2026-08-10T15:00:00+00:00", "recorta ligações em trinta dias")
    checar(ativas.call_args.args[0] == "2026-09-09T14:00:00+00:00", "recorta atividades em sessenta minutos")

    print("Tudo certo." if not falhas else f"{falhas} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
