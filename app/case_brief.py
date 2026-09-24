"""Representação estruturada do caso, montada ANTES da geração da peça.

POR QUE ISTO EXISTE

A geração local (`peticao_local.gerar`) sempre partiu de texto solto: entrevista
e OCR concatenados, cortados em 110 mil caracteres, direto para o prompt. O
modelo tinha de organizar E redigir na mesma passada — e organizar é o que
sofre primeiro num prompt grande.

Este módulo não lê documento nenhum de novo. Ele reaproveita o que
`analise_documentos` já apurou (achados com citação conferida, cronologia com
fonte) e reorganiza em um objeto único, com cada fato apontando para onde ele
veio — `fato → documento → trecho`. Quem consome (o outline jurídico, e no
futuro o validador pós-geração) lê estrutura, não prosa a ser reinterpretada.

Nenhum campo aqui é gerado por LLM além do que `analise_documentos` já gera; é
puramente reorganização. Por isso falha de rede/modelo aqui é a MESMA falha de
`analise_documentos` — não se some outro ponto de falha ao pipeline.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

from . import analise_documentos, armazenamento, case_brief_estado, casos

log = logging.getLogger(__name__)


def montar(caso_id: str) -> dict[str, Any]:
    """O case brief do caso: partes, cronologia, fatos, provas e o que falta.

    `source_map` é a chave por id (`fato-1`, `evento-1`, ...) que aponta para
    `{"documento": ..., "trecho": ...}` — a mesma citação que `analise_documentos`
    já conferiu contra o texto lido. Um fato sem entrada aqui não tem como ter
    sido inventado por este módulo: ele só existe se veio de um achado ou de um
    evento da cronologia, os dois com citação obrigatória na origem.
    """
    caso = armazenamento.obter_caso(caso_id) or {}
    source_map: dict[str, dict[str, str]] = {}

    try:
        leitura = analise_documentos.analisar(caso_id)
    except analise_documentos.ErroAnaliseDocumentos as erro:
        log.warning("case_brief: leitura dos documentos indisponível: %s", erro)
        leitura = {}

    fatos: list[dict[str, Any]] = []
    inconsistencias: list[dict[str, Any]] = []
    for indice, achado in enumerate(leitura.get("achados") or [], start=1):
        fato_id = f"fato-{indice}"
        fato = {
            "id": fato_id,
            "descricao": str(achado.get("informacao") or ""),
            "parte": str(achado.get("parte") or "indefinido"),
            "papel": str(achado.get("papel") or ""),
            "relevancia": str(achado.get("relevancia") or ""),
            "contradiz_entrevista": bool(achado.get("contradiz")),
        }
        fatos.append(fato)
        source_map[fato_id] = {
            "documento": str(achado.get("documento") or ""),
            "trecho": str(achado.get("citacao") or ""),
        }
        if fato["contradiz_entrevista"]:
            inconsistencias.append(fato)

    timeline: list[dict[str, Any]] = []
    for indice, evento in enumerate(leitura.get("cronologia") or [], start=1):
        evento_id = f"evento-{indice}"
        timeline.append({
            "id": evento_id,
            "data": str(evento.get("data") or ""),
            "evento": str(evento.get("evento") or ""),
        })
        source_map[evento_id] = {
            "documento": str(evento.get("documento") or ""),
            "trecho": str(evento.get("citacao") or ""),
        }
    # A cronologia já vem ordenada por `analise_documentos`; aqui só se
    # preserva a ordem — reordenar de novo arriscaria inverter datas que já
    # saíram certas de lá.

    # Estado humano por cima da leitura crua — ver `case_brief_estado` para o
    # porquê e para a regra de prioridade. Falha (Postgres fora, tabela ainda
    # não criada) não pode impedir o brief de existir: cai para "tudo
    # DETECTED", que era o único estado que existia antes desta camada.
    try:
        estados = case_brief_estado.estados_do_caso(caso_id)
    except Exception as erro:
        log.warning("case_brief: estado humano indisponível: %s", erro)
        estados = {}

    confirmados: list[dict[str, Any]] = []
    nao_confirmados: list[dict[str, Any]] = []

    def _com_estado(item: dict[str, Any]) -> dict[str, Any] | None:
        """Aplica o estado humano a um fato/evento; `None` = fora do brief (REJECTED)."""
        registro = estados.get(item["id"])
        if registro is None:
            item["estado"] = "DETECTED"
            return item
        estado = str(registro.get("estado") or "DETECTED")
        item["estado"] = estado
        if estado == "REJECTED":
            return None
        if estado == "CORRECTED" and str(registro.get("valor_corrigido") or "").strip():
            item["valor_original"] = item.get("descricao") or item.get("evento") or ""
            if "descricao" in item:
                item["descricao"] = registro["valor_corrigido"]
            else:
                item["evento"] = registro["valor_corrigido"]
        if estado == "CONFIRMED":
            confirmados.append(item)
        elif estado == "NEEDS_CONFIRMATION":
            nao_confirmados.append(item)
        return item

    fatos = [f for f in (_com_estado(f) for f in fatos) if f is not None]
    timeline = [e for e in (_com_estado(e) for e in timeline) if e is not None]
    # `inconsistencias` foi montada ANTES do overlay de estado — se o advogado
    # já rejeitou ou corrigiu uma inconsistência, ela não deve continuar
    # aparecendo como pendência. Refeita aqui, depois do overlay.
    fatos_por_id = {f["id"]: f for f in fatos}
    inconsistencias = [
        fatos_por_id[f["id"]] for f in inconsistencias if f["id"] in fatos_por_id
    ]

    evidencias = [
        {"id": doc["id"], "arquivo": doc["arquivo"]}
        for doc in analise_documentos._documentos_do_caso(caso_id)  # noqa: SLF001 - mesmo módulo, mesma fonte
    ]

    try:
        pendentes = casos.documentos_pendentes_do_caso(caso_id) or {}
        faltando = [
            str(item.get("nome") or item.get("codigo") or "")
            for item in pendentes.get("pendentes") or []
            if item.get("obrigatorio")
        ]
    except Exception as erro:  # noqa: BLE001 - o brief não pode travar por causa do checklist
        log.warning("case_brief: checklist indisponível: %s", erro)
        faltando = []

    return {
        "parties": {
            "cliente": str(caso.get("cliente") or ""),
            "telefone": str(caso.get("telefone") or ""),
        },
        "case_type": str(caso.get("categoria") or ""),
        "timeline": timeline,
        "facts": fatos,
        "evidence": evidencias,
        "inconsistencies": inconsistencias,
        "confirmed_information": confirmados,
        "unconfirmed_information": nao_confirmados,
        "missing_information": faltando,
        "source_map": source_map,
    }


def para_prompt(brief: dict[str, Any]) -> str:
    """O case brief em texto, para entrar no material de quem gera ou planeja.

    Mesmo objeto que `montar` devolve, só que em linhas — o outline jurídico e a
    redação leem texto, não JSON aninhado.
    """
    linhas = ["=== CASE BRIEF (fatos e provas já organizados; cite pelo id) ==="]
    partes = brief.get("parties") or {}
    if partes.get("cliente"):
        linhas.append(f"Cliente: {partes['cliente']}")
    if brief.get("case_type"):
        linhas.append(f"Tipo de caso: {brief['case_type']}")

    timeline = brief.get("timeline") or []
    if timeline:
        linhas.append("\nCronologia (id | data | evento):")
        linhas.extend(f"- {e['id']} | {e['data']} | {e['evento']}" for e in timeline)

    fatos = brief.get("facts") or []
    normais = [f for f in fatos if not f.get("contradiz_entrevista")]
    if normais:
        linhas.append("\nFatos apurados nos documentos (id | descrição):")
        for f in normais:
            marca = " [CONFIRMADO PELO ADVOGADO]" if f.get("estado") == "CONFIRMED" else ""
            if f.get("estado") == "CORRECTED" and f.get("valor_original"):
                marca = f" [CORRIGIDO PELO ADVOGADO — original: \"{f['valor_original']}\"]"
            linhas.append(f"- {f['id']} | {f['descricao']}{marca}")

    inconsistencias = brief.get("inconsistencies") or []
    if inconsistencias:
        linhas.append("\nInconsistências com a entrevista (id | descrição):")
        linhas.extend(f"- {f['id']} | {f['descricao']}" for f in inconsistencias)

    nao_confirmados = brief.get("unconfirmed_information") or []
    if nao_confirmados:
        linhas.append(
            "\nPontos que a IA identificou e AINDA NÃO foram confirmados pelo advogado "
            "(não afirme como fato resolvido — trate como [PENDENTE] se for essencial):"
        )
        linhas.extend(f"- {f['id']} | {f.get('descricao') or f.get('evento') or ''}" for f in nao_confirmados)

    faltando = brief.get("missing_information") or []
    if faltando:
        linhas.append("\nDocumentos obrigatórios ainda pendentes: " + ", ".join(faltando))

    linhas.append(
        "\nCada fato e evento acima tem um trecho literal do documento de origem "
        "guardado à parte (source map) — ao citar um id deste brief, você está "
        "citando algo com prova conferida. Não afirme nada que não tenha id aqui "
        "nem em outro bloco do material."
    )
    return "\n".join(linhas)


def _normalizar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", sem_acento.lower()).strip()


def _palavras_relevantes(texto: str, minimo: int = 5) -> set[str]:
    """As palavras de `texto` compridas o bastante para não darem falso positivo.

    "afastamento" bate errado por acaso; "de", "em", "com" batem sempre — por
    isso o corte de tamanho, não uma lista de paradas para manter.
    """
    return {p for p in _normalizar(texto).split() if len(p) >= minimo}


def cobertura(brief: dict[str, Any], secoes: list[dict[str, Any]]) -> dict[str, Any]:
    """Quais fatos e eventos do brief aparecem (ou não) no texto da peça gerada.

    Heurística, não semântica: considera "usado" quando pelo menos metade das
    palavras relevantes da descrição aparece no texto da peça. Não precisa de
    outra chamada de LLM — é o que permite rodar em toda geração, de graça, e
    é isso que dá a "matriz de cobertura" (fato × usado-ou-não) que o trace
    grava. Falso negativo é o erro aceitável aqui (a peça pode ter narrado o
    fato com outras palavras); falso positivo por sorte de vocabulário é raro
    o bastante para não avisar por engano com frequência.
    """
    texto_peca = _normalizar(" ".join(str(s.get("content") or "") for s in secoes))

    def usado(descricao: str) -> bool:
        palavras = _palavras_relevantes(descricao)
        if not palavras:
            return True  # nada para checar não é omissão
        acertos = sum(1 for p in palavras if p in texto_peca)
        return acertos >= max(1, len(palavras) // 2)

    fatos_usados, fatos_nao_usados = [], []
    for fato in brief.get("facts") or []:
        if fato.get("contradiz_entrevista"):
            continue  # inconsistência é para o advogado decidir, não para "usar na peça"
        (fatos_usados if usado(fato["descricao"]) else fatos_nao_usados).append(fato["id"])

    eventos_usados, eventos_nao_usados = [], []
    for evento in brief.get("timeline") or []:
        (eventos_usados if usado(evento["evento"]) else eventos_nao_usados).append(evento["id"])

    return {
        "fatos_usados": fatos_usados,
        "fatos_nao_usados": fatos_nao_usados,
        "eventos_usados": eventos_usados,
        "eventos_nao_usados": eventos_nao_usados,
    }
