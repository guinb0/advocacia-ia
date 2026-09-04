"""Concilia as evidências dos documentos de um caso antes da síntese estratégica.

Cada documento do caso já passou pelo pipeline Mistral
(`app/tasks/pipeline_documentos.py`) e chegou a `extrair_evidencias`: fatos com
citação literal e página, nunca inventados (ver `documentos_juridicos.py`). Este
módulo só AGREGA — não interpreta, não decide, não resume com opinião. Cruzar
fatos entre documentos e apontar contradição é trabalho do modelo, em
`rag.sintetizar_estrategia_caso`; aqui é só montagem de material rastreável.

Documento sem `extrair_evidencias` concluída (ainda processando, ou caiu para
revisão humana antes de chegar lá) entra em `pendentes`, não é descartado
silenciosamente — o parecer final avisa que aquele documento ainda não contou.
"""

from __future__ import annotations

from typing import Any

from . import analise_documental, armazenamento, categorias


class ErroConciliacao(Exception):
    """Caso sem dado suficiente para montar o pacote — quem chama decide o que fazer."""


def montar_pacote_caso(caso_id: str) -> dict[str, Any]:
    """Junta cliente, categoria, lacunas do checklist e evidências de cada documento lido."""
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise ErroConciliacao(f"Caso '{caso_id}' não encontrado.")

    categoria = categorias.obter(caso.get("categoria") or "")
    entregas = armazenamento.listar_entregas(caso_id)

    documentos: list[dict[str, Any]] = []
    pendentes: list[str] = []
    atendidos: set[str] = set()
    #: Pessoas citadas em QUALQUER documento, agrupadas por nome — cada uma com os
    #: papéis que apareceram e em que documentos. É o material que deixa o parecer
    #: contextualizar quem é quem (cliente, agressor, chefe, perito, testemunha).
    partes: dict[str, dict[str, Any]] = {}

    for entrega in entregas:
        nome_arquivo = str(entrega.get("arquivo") or "documento")
        analise = analise_documental.obter_por_entrega(entrega["id"])
        if analise is None or analise.get("status") != "CONCLUIDA":
            pendentes.append(nome_arquivo)
            continue

        evidencias = analise_documental.resultado_etapa(analise["id"], "extrair_evidencias")
        classificacao = analise_documental.resultado_etapa(analise["id"], "classificar_documento")
        extracao = analise_documental.resultado_etapa(analise["id"], "extrair_schema_especifico")
        lista_evidencias = evidencias.get("evidencias") or []
        if not lista_evidencias:
            pendentes.append(nome_arquivo)
            continue

        itens = list(entrega.get("itens_atendidos") or [])
        atendidos.update(itens)
        documentos.append(
            {
                "arquivo": nome_arquivo,
                "tipo": classificacao.get("rotulo") or "não identificado",
                "itens_atendidos": itens,
                "evidencias": lista_evidencias,
            }
        )

        for pessoa in extracao.get("pessoas") or []:
            nome = str(pessoa.get("nome") or "").strip()
            if not nome:
                continue
            registro = partes.setdefault(
                nome.casefold(),
                {"nome": nome, "papeis": [], "relacoes": [], "documentos": []},
            )
            papel = str(pessoa.get("papel") or "").strip()
            if papel and papel not in registro["papeis"]:
                registro["papeis"].append(papel)
            # Só entra aqui o vínculo que o próprio documento afirmou (ver o prompt
            # de anotação). Vazio não é ausência de vínculo — é ausência de prova
            # dele naquele papel, e o modelo é quem cruza os documentos para inferir.
            relacao = str(pessoa.get("relacao_com_cliente") or "").strip()
            if relacao and relacao not in registro["relacoes"]:
                registro["relacoes"].append(relacao)
            if nome_arquivo not in registro["documentos"]:
                registro["documentos"].append(nome_arquivo)

    obrigatorios = [i for i in (categoria.itens if categoria else ()) if i.obrigatorio]
    lacunas_checklist = [i.nome for i in obrigatorios if i.codigo not in atendidos]

    return {
        "caso_id": caso_id,
        "cliente": str(caso.get("cliente") or ""),
        "categoria": categoria.nome if categoria else str(caso.get("categoria") or ""),
        "documentos": documentos,
        "pendentes": pendentes,
        "lacunas_checklist": lacunas_checklist,
        "partes": list(partes.values()),
    }


def texto_para_modelo(pacote: dict[str, Any]) -> str:
    """Achata o pacote num texto único, no formato que vai para o modelo."""
    secoes = [f"CLIENTE: {pacote['cliente']}", f"CATEGORIA: {pacote['categoria']}"]
    if pacote.get("partes"):
        linhas = [
            "PESSOAS CITADAS NOS DOCUMENTOS "
            "(nome — papel(éis) lido(s) — vínculo com o cliente quando o documento o afirma — em quais arquivos):"
        ]
        for parte in pacote["partes"]:
            papeis = ", ".join(parte.get("papeis") or []) or "papel não informado"
            relacoes = ", ".join(parte.get("relacoes") or []) or "vínculo não declarado nos documentos"
            docs = "; ".join(parte.get("documentos") or [])
            linhas.append(f"- {parte['nome']} — {papeis} — {relacoes} — [{docs}]")
        secoes.append("\n".join(linhas))
    if pacote["lacunas_checklist"]:
        secoes.append(
            "ITENS OBRIGATÓRIOS DO CHECKLIST AINDA SEM DOCUMENTO: "
            + "; ".join(pacote["lacunas_checklist"])
        )
    for doc in pacote["documentos"]:
        linhas = [f"### Documento: {doc['arquivo']} ({doc['tipo']})"]
        for ev in doc["evidencias"]:
            marca = " [SENSÍVEL]" if ev.get("sensivel") else ""
            linhas.append(
                f"- {ev.get('fato', '')}{marca} — citação (p.{ev.get('pagina')}): "
                f"\"{ev.get('citacao', '')}\""
            )
        secoes.append("\n".join(linhas))
    if pacote["pendentes"]:
        secoes.append(
            "DOCUMENTOS AINDA SEM LEITURA CONCLUÍDA (não entraram nesta análise): "
            + "; ".join(pacote["pendentes"])
        )
    return "\n\n".join(secoes)
