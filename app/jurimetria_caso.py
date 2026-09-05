"""Cruza os FATOS do caso — entrevista + o que o OCR extraiu — com a jurimetria.

POR QUE ISTO EXISTE

O cruzamento com o acervo só acontecia ao gerar a petição, e a busca partia do
texto já redigido. Mas o que melhor encontra precedente é o dado bruto extraído
do documento: o CID do laudo, a espécie do benefício do INSS, a vara. Aqui esses
achados entram DIRETO na consulta vetorial, junto com o relato da entrevista e a
categoria — então "caso do cliente → decisões parecidas → desfecho por vara"
aparece antes e melhor, sem depender da minuta.

Descritivo, nunca preditivo: é a foto da amostra semanticamente próxima, não a
probabilidade de êxito. As estatísticas e o aviso vêm de `rag._estatisticas_amostra`.
"""

from __future__ import annotations

import logging
from typing import Any

from . import analise_documentos, armazenamento, categorias, rag

log = logging.getLogger("jurimetria-caso")


def _sinais_do_caso(caso_id: str) -> dict[str, Any]:
    """Junta os sinais que definem o caso: categoria, entrevista e achados do OCR."""
    caso = armazenamento.obter_caso(caso_id)
    categoria_nome = ""
    if caso:
        cat = categorias.obter(caso.get("categoria", ""))
        categoria_nome = cat.nome if cat else str(caso.get("categoria") or "")

    entrevista = ""
    for e in armazenamento.listar_entrevistas(caso_id):
        texto = str(e.get("texto") or "").strip()
        if texto:
            entrevista = texto
            break

    achados: list[str] = []
    try:
        for a in (analise_documentos.analisar(caso_id).get("achados") or [])[:12]:
            info = str(a.get("informacao") or "").strip()
            cit = str(a.get("citacao") or "").strip()
            if info:
                achados.append(f"{info}{f' ({cit})' if cit else ''}")
    except Exception as erro:  # noqa: BLE001 - sem achados, cruza só entrevista+categoria
        log.info("jurimetria do caso %s sem achados: %s", caso_id, str(erro)[:120])

    return {"categoria": categoria_nome, "entrevista": entrevista, "achados": achados}


def _consulta(sinais: dict[str, Any]) -> str:
    partes = []
    if sinais["categoria"]:
        partes.append(f"Tipo de ação: {sinais['categoria']}")
    if sinais["achados"]:
        # Os dados do documento primeiro: CID, benefício e datas puxam o precedente
        # mais específico que o relato corrido da conversa.
        partes.append("Fatos extraídos dos documentos:\n" + "\n".join(f"- {a}" for a in sinais["achados"]))
    if sinais["entrevista"]:
        partes.append("Relato do atendimento:\n" + sinais["entrevista"])
    return "\n\n".join(partes).strip()


def cruzar(caso_id: str, *, limite_precedentes: int = 12) -> dict[str, Any]:
    """Precedentes semelhantes ao caso + a distribuição de desfechos da amostra.

    Nunca levanta para o chamador: uma base fora do ar é um estado a mostrar, não
    um 500 — o painel diz que a jurimetria não respondeu e o resto do dossiê segue.
    """
    sinais = _sinais_do_caso(caso_id)
    consulta = _consulta(sinais)
    resumo_sinais = {
        "categoria": sinais["categoria"],
        "tem_entrevista": bool(sinais["entrevista"]),
        "achados": sinais["achados"][:8],
    }
    if not consulta:
        return {
            "disponivel": False,
            "aviso": "Ainda não há entrevista nem dados extraídos para cruzar com a jurimetria.",
            "sinais": resumo_sinais,
            "precedentes": [],
            "estatisticas": None,
        }
    try:
        similares = rag.buscar_similares(consulta, limite=30, timeout=40, connect_timeout=5, connect_retries=1)
    except Exception as erro:  # noqa: BLE001 - base remota pode estar fora do ar
        log.warning("jurimetria do caso %s indisponível: %s", caso_id, str(erro)[:160])
        return {
            "disponivel": False,
            "aviso": "A base de decisões não respondeu agora. Nada foi estimado; tente de novo.",
            "sinais": resumo_sinais,
            "precedentes": [],
            "estatisticas": None,
        }
    if not similares:
        return {
            "disponivel": False,
            "aviso": "Nenhuma decisão suficientemente semelhante foi encontrada no acervo.",
            "sinais": resumo_sinais,
            "precedentes": [],
            "estatisticas": None,
        }

    precedentes = []
    for trecho in similares[:limite_precedentes]:
        ref = trecho.referencia()
        precedentes.append(
            {
                "processo": ref.get("processo") or ref.get("identificador"),
                "resultado": ref.get("resultado") or "indefinido",
                "vara": ref.get("vara") or "não informado",
                "tipo_documento": ref.get("tipo_documento"),
                "similaridade": ref.get("similaridade"),
                "url": ref.get("url"),
                "trecho": trecho.texto[:400],
            }
        )
    return {
        "disponivel": True,
        "aviso": "",
        "sinais": resumo_sinais,
        "precedentes": precedentes,
        "estatisticas": rag._estatisticas_amostra(similares),
    }
