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
import re
from collections import Counter
from typing import Any

from . import analise_documentos, armazenamento, categorias, rag, tribunais

log = logging.getLogger("jurimetria-caso")

#: Sigla de UF como palavra isolada — para achar o estado no endereço que o OCR
#: extraiu ("Nova Iguaçu - RJ"). Só as 27 válidas; a mais frequente vence.
_RE_UF = re.compile(r"(?<![A-Z0-9])(" + "|".join(tribunais.UF_PARA_TRT) + r")(?![A-Z0-9])")


def _detectar_uf(texto: str) -> str:
    """Best-effort: o estado do caso a partir do endereço lido nos documentos.

    Prefere a sigla mais repetida no texto. Sem sigla, tenta o nome por extenso.
    Serve só para FOCAR a busca; erro aqui degrada para a região/nacional, não
    inventa dado no dossiê.
    """
    if not texto:
        return ""
    achados = _RE_UF.findall(texto.upper())
    if achados:
        return Counter(achados).most_common(1)[0][0]
    for pedaco in re.split(r"[,\-/\n]", texto):
        sigla = tribunais.normalizar_uf(pedaco.strip())
        if sigla:
            return sigla
    return ""


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


#: Abaixo disto a camada do estado é rasa demais para ler tendência — cai para a
#: vizinhança (mesma região) e, por fim, para o acervo nacional.
MINIMO_AMOSTRA = 8


def _buscar_por_jurisdicao(consulta: str, uf: str) -> tuple[list[Any], str]:
    """Busca no TRT do estado; sem amostra, abre para a região e depois o país.

    Devolve os trechos e a jurisdição de fato usada, para a tela dizer de onde
    vieram os números ("TRT8", "Região Norte", "acervo nacional").
    """
    camadas = tribunais.tribunais_por_prioridade(uf)
    ultimo: list[Any] = []
    for indice, trts in enumerate(camadas):
        achados = rag.buscar_similares(
            consulta, limite=30, timeout=40, connect_timeout=5, connect_retries=1,
            tribunais=trts or None,
        )
        ultimo = achados
        if len(achados) >= MINIMO_AMOSTRA or indice == len(camadas) - 1:
            if trts:
                jur = " + ".join(trts) if len(trts) <= 2 else f"{len(trts)} regionais da região"
            else:
                jur = "acervo nacional" if uf else "acervo nacional (sem estado informado)"
            return achados, jur
    return ultimo, "acervo nacional"


def cruzar(caso_id: str, *, uf: str = "", limite_precedentes: int = 12) -> dict[str, Any]:
    """Precedentes semelhantes ao caso + a distribuição de desfechos da amostra.

    `uf` foca a análise no TRT daquele estado (com fallback para a região e o
    país). Nunca levanta: base fora do ar é um estado a mostrar, não um 500.
    """
    sinais = _sinais_do_caso(caso_id)
    consulta = _consulta(sinais)
    jurisdicao = ""
    # UF do parâmetro vence; sem ela, tenta descobrir pelo endereço extraído.
    uf_efetiva = tribunais.normalizar_uf(uf) or _detectar_uf(
        f"{sinais['entrevista']} {' '.join(sinais['achados'])}"
    )
    resumo_sinais = {
        "categoria": sinais["categoria"],
        "tem_entrevista": bool(sinais["entrevista"]),
        "achados": sinais["achados"][:8],
        "uf": uf_efetiva,
        "uf_automatica": bool(uf_efetiva and not tribunais.normalizar_uf(uf)),
    }
    if not consulta:
        return {
            "disponivel": False,
            "aviso": "Ainda não há entrevista nem dados extraídos para cruzar com a jurimetria.",
            "sinais": resumo_sinais,
            "jurisdicao": jurisdicao,
            "precedentes": [],
            "estatisticas": None,
        }
    try:
        similares, jurisdicao = _buscar_por_jurisdicao(consulta, uf_efetiva)
    except Exception as erro:  # noqa: BLE001 - base remota pode estar fora do ar
        log.warning("jurimetria do caso %s indisponível: %s", caso_id, str(erro)[:160])
        return {
            "disponivel": False,
            "aviso": "A base de decisões não respondeu agora. Nada foi estimado; tente de novo.",
            "sinais": resumo_sinais,
            "jurisdicao": jurisdicao,
            "precedentes": [],
            "estatisticas": None,
        }
    if not similares:
        return {
            "disponivel": False,
            "aviso": "Nenhuma decisão suficientemente semelhante foi encontrada no acervo.",
            "sinais": resumo_sinais,
            "jurisdicao": jurisdicao,
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
        "jurisdicao": jurisdicao,
        "precedentes": precedentes,
        "estatisticas": rag._estatisticas_amostra(similares),
    }
