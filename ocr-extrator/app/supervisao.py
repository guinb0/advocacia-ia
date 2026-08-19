"""Acompanhamento da equipe: quem entrevistou, quanto, e o que foi dito.

PARA QUE ISTO EXISTE

O secretário do escritório precisa responder duas perguntas que nenhuma tela
respondia: quantas entrevistas cada pessoa fez, e o que foi dito em cada uma.
Antes, entrevista só aparecia dentro do caso — para ter o total de alguém era
preciso abrir caso por caso e somar de cabeça.

DE ONDE VEM A ATRIBUIÇÃO, E O QUE ELA NÃO ALCANÇA

Da coluna `entrevistador`. Ela sempre existiu, mas era texto livre preenchido à
mão e ficava vazia: das sete entrevistas já gravadas, seis não dizem quem as fez.
A rota de envio passou a assumir quem está logado (ver `_quem_conduziu` em
`main.py`), então isso se resolve DAQUI PARA A FRENTE — o que já está gravado sem
nome continua sem nome, e aparece agrupado como "não identificado" em vez de ser
escondido. Sumir com elas faria a soma da tela não bater com a realidade.

POR QUE SÓ O SECRETÁRIO

Ver a transcrição de todas as entrevistas do escritório é acesso amplo a relato
de cliente. O advogado já alcança o que é dos casos dele; esta visão atravessa
todos, e por isso é do papel cuja função é justamente essa.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from . import armazenamento, auditoria
from .auth import exigir_papel

log = logging.getLogger("supervisao")

roteador = APIRouter(prefix="/api/supervisao", tags=["supervisao"])

SoSecretario = Depends(exigir_papel("secretario"))

#: Como aparece quem conduziu entrevista antes de a atribuição existir.
SEM_NOME = "não identificado"


def _chave(nome: object) -> str:
    """Junta grafias do mesmo nome sem inventar identidade.

    Compara sem caixa e sem espaço duplicado — "  Dra. Helena  Prado" e
    "Dra. Helena Prado" são a mesma pessoa. NÃO tenta casar apelido com nome
    completo: errar isso somaria o trabalho de uma pessoa na conta de outra, que
    é pior que mostrar duas linhas parecidas e deixar quem olha decidir.
    """
    return " ".join(str(nome or "").split()).casefold()


@roteador.get("/entrevistas", dependencies=[SoSecretario])
def por_entrevistador() -> dict[str, Any]:
    """Quantas entrevistas cada um fez, e a lista de cada pessoa."""
    entrevistas = armazenamento.listar_todas_entrevistas()

    pessoas: dict[str, dict[str, Any]] = {}
    for e in entrevistas:
        nome = " ".join(str(e.get("entrevistador") or "").split())
        chave = _chave(nome) or SEM_NOME
        grupo = pessoas.setdefault(
            chave, {"entrevistador": nome or SEM_NOME, "quantidade": 0, "entrevistas": []}
        )
        grupo["quantidade"] += 1
        grupo["entrevistas"].append(
            {
                "id": e.get("id"),
                "caso_id": e.get("caso_id"),
                "arquivo": e.get("arquivo"),
                "realizada_em": e.get("realizada_em"),
                "criado_em": e.get("criado_em"),
                # O tamanho dá noção do que há para ler sem despejar o texto
                # inteiro numa lista que pode ter centenas de linhas.
                "caracteres": len(str(e.get("texto") or "")),
                "fatos_gerados": e.get("fatos_gerados"),
            }
        )

    itens = sorted(
        pessoas.values(),
        # Quem mais fez primeiro; "não identificado" vai para o fim mesmo sendo
        # grande, porque é pendência de dado, não desempenho de ninguém.
        key=lambda p: (p["entrevistador"] == SEM_NOME, -p["quantidade"]),
    )
    for pessoa in itens:
        pessoa["entrevistas"].sort(key=lambda x: str(x.get("criado_em") or ""), reverse=True)

    return {
        "itens": itens,
        "total_entrevistas": len(entrevistas),
        "total_pessoas": sum(1 for p in itens if p["entrevistador"] != SEM_NOME),
        "sem_atribuicao": sum(
            p["quantidade"] for p in itens if p["entrevistador"] == SEM_NOME
        ),
    }


@roteador.get("/entrevistas/{entrevista_id}", dependencies=[SoSecretario])
def transcricao(entrevista_id: str) -> dict[str, Any]:
    """A transcrição inteira de uma entrevista, com o que o agente extraiu dela."""
    e = armazenamento.obter_entrevista(entrevista_id)
    if e is None:
        raise HTTPException(404, "Entrevista não encontrada.")
    return {
        "id": e.get("id"),
        "caso_id": e.get("caso_id"),
        "entrevistador": e.get("entrevistador") or SEM_NOME,
        "arquivo": e.get("arquivo"),
        "realizada_em": e.get("realizada_em"),
        "criado_em": e.get("criado_em"),
        "texto": e.get("texto") or "",
        "resumo": e.get("resumo") or "",
        "perguntas": e.get("perguntas") or [],
        "fatos_gerados": e.get("fatos_gerados"),
    }


@roteador.post("/entrevistas/{entrevista_id}/auditoria", dependencies=[SoSecretario])
def auditar_entrevista(entrevista_id: str) -> dict[str, Any]:
    """Lê a transcrição bruta e diz o que do roteiro não aparece nela.

    É POST e não GET porque cada chamada custa uma ida ao modelo: com GET, um
    refresh da tela dispararia a análise de novo, e o secretário abre esta lista
    o dia inteiro.
    """
    e = armazenamento.obter_entrevista(entrevista_id)
    if e is None:
        raise HTTPException(404, "Entrevista não encontrada.")
    try:
        relatorio = auditoria.auditar(str(e.get("texto") or ""))
    except auditoria.ErroAuditoria as exc:
        # 503 e não 500: falta de chave ou modelo fora do ar é indisponibilidade,
        # e a mensagem já diz o que fazer.
        raise HTTPException(503, str(exc)) from exc
    relatorio["entrevista_id"] = entrevista_id
    relatorio["entrevistador"] = e.get("entrevistador") or SEM_NOME
    return relatorio
