"""Leitura do Acervo para o painel administrativo. Nada aqui escreve."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from ..juridico import autoridades as aut
from . import agenda, sincronizacao
from . import status as st
from .armazenamento import Armazenamento

#: Norma sem verificação há mais que isto aparece em "Problemas" como desatualizada.
HORAS_DESATUALIZADA = 36


def _iso(v: Any) -> Any:
    return v.isoformat() if hasattr(v, "isoformat") else v


def _limpo(d: dict[str, Any]) -> dict[str, Any]:
    return {k: _iso(v) for k, v in d.items() if k != "embedding"}


def _status_documento(doc: dict[str, Any]) -> str:
    return str(doc.get("sync_status") or st.PENDENTE)


def _desatualizada(doc: dict[str, Any], agora: datetime) -> bool:
    ultima = doc.get("last_checked_at")
    return not isinstance(ultima, datetime) or agora - (ultima if ultima.tzinfo else ultima.replace(tzinfo=UTC)) > timedelta(hours=HORAS_DESATUALIZADA)


def _linha_norma(doc: dict[str, Any], cont: dict[str, Any], item: dict[str, Any] | None, agora: datetime) -> dict[str, Any]:
    s = _status_documento(doc)
    return {
        "id": doc["document_id"], "nome": doc.get("nome_amigavel") or doc.get("document_name") or (item or {}).get("nome_amigavel") or doc["document_id"],
        "nome_oficial": doc.get("document_name") or "", "numero": doc.get("document_number") or "", "ano": doc.get("document_year") or "",
        "categoria": doc.get("categoria") or "legislacao", "tipo": doc.get("tipo") or "lei", "orgao": doc.get("orgao") or "",
        "fonte": doc.get("official_source") or "", "url": doc.get("source_url") or "", "chave_norma": doc.get("chave_norma") or "",
        "selo": st.selo(s), "ultimo_erro": doc.get("ultimo_erro") or "",
        "ultima_verificacao": _iso(doc.get("last_checked_at")), "ultima_atualizacao": _iso(doc.get("last_updated_at")),
        "proxima_verificacao": _iso(doc.get("next_check_at")) if agenda.ativa() else None,
        "fonte_modificada_em": _iso(doc.get("source_last_modified_at")), "content_hash": doc.get("content_hash") or "",
        "encoding": doc.get("encoding") or "", "parser": doc.get("parser_version") or "",
        "dispositivos": int(cont.get("dispositivos_atuais") or 0), "artigos": int(cont.get("artigos_atuais") or 0),
        "revogados": int(cont.get("revogados") or 0), "versoes_historicas": int(cont.get("versoes_historicas") or 0),
        "legado": int(cont.get("legado") or 0), "sem_vigencia": int(cont.get("sem_vigencia") or 0),
        "embeddings": {k: int(cont.get(k) or 0) for k in ("chunks", "chunks_com_embedding", "chunks_pendentes", "chunks_invalidados")},
        "desatualizada": _desatualizada(doc, agora),
    }


def normas(store: Armazenamento, *, busca: str = "", categoria: str = "", status: str = "", agora: datetime | None = None) -> list[dict[str, Any]]:
    agora = agora or datetime.now(UTC)
    contagens = store.contagens()
    docs = {d["document_id"]: d for d in store.documentos()}
    for item in sincronizacao.manifesto():
        if item.get("categoria", "legislacao") == "legislacao" and item["id"] not in docs:
            docs[item["id"]] = {"document_id": item["id"], "document_name": item["nome"], "nome_amigavel": item.get("nome_amigavel"),
                                "document_number": item.get("numero"), "categoria": "legislacao", "tipo": item.get("tipo"),
                                "official_source": item.get("fonte"), "source_url": item["url"], "sync_status": st.PENDENTE,
                                "chave_norma": item.get("chave_norma")}
    itens = {i["id"]: i for i in sincronizacao.manifesto()}
    linhas = [_linha_norma(d, contagens.get(k) or {}, itens.get(k), agora) for k, d in sorted(docs.items())]
    b = aut.norm(busca)
    return [l for l in linhas if (not b or b in aut.norm(f"{l['nome']} {l['nome_oficial']} {l['numero']} {l['id']}"))
            and (not categoria or l["categoria"] == categoria) and (not status or l["selo"]["status"] == status)]


def jurisprudencia(store: Armazenamento, *, busca: str = "", status: str = "") -> list[dict[str, Any]]:
    b = aut.norm(busca)
    saida = []
    for a in store.autoridades():
        if a.get("tipo") == "artigo":
            continue
        sync = a.get("sync_status") or (st.ATUALIZADO if a.get("verificada") else st.AGUARDANDO_VERIFICACAO)
        if a.get("status") in ("revogado", "superado", "cancelado"):
            sync_vis = st.REVOGADO
        else:
            sync_vis = sync
        linha = {"id": a["id"], "tipo": a.get("tipo"), "tribunal": a.get("tribunal"), "orgao": a.get("orgao"), "numero": a.get("numero"),
                 "titulo": a.get("titulo"), "status_juridico": a.get("status"), "superado_por": a.get("superado_por") or "",
                 "verificada": bool(a.get("verificada")), "selo": st.selo(sync_vis), "url": a.get("url"), "fonte": a.get("fonte_oficial"),
                 "vigencia_inicio": _iso(a.get("vigencia_inicio")), "vigencia_fim": _iso(a.get("vigencia_fim")),
                 "ultima_verificacao": _iso(a.get("ultima_verificacao") or a.get("verificado_em")), "texto": (a.get("texto") or "")[:600]}
        if b and b not in aut.norm(f"{linha['titulo']} {linha['numero']} {linha['tribunal']} {linha['texto']}"):
            continue
        if status and linha["selo"]["status"] != status:
            continue
        saida.append(linha)
    return sorted(saida, key=lambda l: (str(l["tribunal"]), str(l["tipo"]), aut._digitos(l["numero"]).zfill(6)))  # noqa: SLF001


def saude_rag(store: Armazenamento, contagens: dict[str, dict[str, Any]], docs: list[dict[str, Any]], agora: datetime) -> dict[str, Any]:
    modelo, dimensoes = sincronizacao.modelo_de_embedding()
    total = {k: sum(int(c.get(k) or 0) for c in contagens.values()) for k in ("chunks", "chunks_com_embedding", "chunks_pendentes", "chunks_invalidados")}
    modelos = sorted({m for c in contagens.values() for m in (c.get("modelos") or [])})
    dims = sorted({int(d) for c in contagens.values() for d in (c.get("dimensoes") or [])})
    verificacoes = []

    def checar(nome: str, ok: bool, detalhe: str, *, aviso: bool = False) -> None:
        verificacoes.append({"nome": nome, "ok": ok, "detalhe": detalhe, "selo": st.selo(st.ATUALIZADO if ok else (st.PENDENTE if aviso else st.ERRO))})

    checar("Provedor de embeddings configurado", sincronizacao.embeddings_configurados(),
           modelo or "EMBEDDINGS_MODEL_NAME/EMBEDDINGS_BASE_URL/EMBEDDINGS_API_KEY ausentes", aviso=True)
    checar("Dimensão dos vetores", not dims or dims == [dimensoes],
           f"configurada {dimensoes}; no banco {', '.join(map(str, dims)) or 'nenhum vetor ainda'}")
    checar("Modelo único nos vetores", len(modelos) <= 1 and (not modelos or not modelo or modelos == [modelo]),
           f"no banco: {', '.join(modelos) or 'sem registro (carga antiga)'}; configurado: {modelo or '—'}", aviso=True)
    checar("Trechos sem vetor", total["chunks_pendentes"] == 0, f"{total['chunks_pendentes']} trecho(s) fora da busca até ganhar vetor", aviso=True)
    checar("Trechos invalidados", True, f"{total['chunks_invalidados']} trecho(s) de redação antiga ou revogada, ignorados pela busca")
    com_erro = [d["document_id"] for d in docs if d.get("sync_status") == st.ERRO]
    checar("Normas com erro de sincronização", not com_erro, ", ".join(com_erro) or "nenhuma")
    desatualizadas = [d["document_id"] for d in docs if _desatualizada(d, agora)]
    checar(f"Normas verificadas nas últimas {HORAS_DESATUALIZADA} h", not desatualizadas, ", ".join(desatualizadas) or "todas", aviso=True)
    legado = sum(int(c.get("legado") or 0) for c in contagens.values())
    checar("Carga antiga migrada para o versionamento novo", legado == 0, f"{legado} versão(ões) com identificador posicional", aviso=True)
    sem_vigencia = sum(int(c.get("sem_vigencia") or 0) for c in contagens.values())
    checar("Dispositivos com início de vigência", sem_vigencia == 0,
           f"{sem_vigencia} versão(ões) abertas sem data — o Citation Gate não aprova citação delas", aviso=True)
    cobertura = round(100 * total["chunks_com_embedding"] / total["chunks"], 1) if total["chunks"] else 0.0
    return {"modelo_configurado": modelo, "dimensoes_configuradas": dimensoes, "modelos_no_banco": modelos, "dimensoes_no_banco": dims,
            "cobertura_percentual": cobertura, **total, "verificacoes": verificacoes,
            "saudavel": all(v["ok"] or v["selo"]["cor"] == "amarelo" for v in verificacoes)}


def resumo(store: Armazenamento, *, agora: datetime | None = None) -> dict[str, Any]:
    agora = agora or datetime.now(UTC)
    contagens = store.contagens()
    docs = store.documentos()
    lista = normas(store, agora=agora)
    juris = jurisprudencia(store)
    alertas = store.alertas(abertos=True, limite=500)
    sincs = store.sincronizacoes(limite=20)
    por_cor: dict[str, int] = {}
    for l in lista:
        por_cor[l["selo"]["cor"]] = por_cor.get(l["selo"]["cor"], 0) + 1
    return {
        "migracao_aplicada": True, "disponivel": True,
        "cartoes": {
            "normas": len(lista), "dispositivos_vigentes": sum(l["dispositivos"] - l["revogados"] for l in lista),
            "revogados": sum(l["revogados"] for l in lista), "versoes_historicas": sum(l["versoes_historicas"] for l in lista),
            "jurisprudencia": len(juris), "jurisprudencia_aguardando": sum(1 for j in juris if not j["verificada"]),
            "jurisprudencia_superada": sum(1 for j in juris if j["status_juridico"] in ("superado", "cancelado", "revogado")),
            "alertas_abertos": len(alertas), "alertas_altos": sum(1 for a in alertas if a.get("severidade") == "alta"),
        },
        "normas_por_cor": por_cor,
        "sincronizacao": {"automatica": agenda.ativa(), "agenda": agenda.descricao(), "proxima": _iso(agenda.proxima_execucao(agora)),
                          "ultima": _limpo(sincs[0]) if sincs else None, "fila": "low"},
        "saude_rag": saude_rag(store, contagens, docs, agora),
    }


def arvore(versoes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Nós atuais em árvore (sem texto, que vem ao clicar)."""
    nos = {v["dispositivo_id"]: {"id": v["id"], "dispositivo_id": v["dispositivo_id"], "tipo": v.get("tipo_no"),
                                 "rotulo": (v.get("hierarchy") or {}).get("rotulo") or v["dispositivo_id"], "status": v.get("status"),
                                 "versao": v.get("version"), "valid_from": _iso(v.get("valid_from")), "filhos": [],
                                 **({"contexto": (v.get("hierarchy") or {}).get("ancestrais") or []} if v.get("tipo_no") == "artigo" else {})}
           for v in versoes if v.get("dispositivo_id")}
    raizes = []
    for v in sorted((v for v in versoes if v.get("dispositivo_id")), key=lambda v: v.get("ordem") or 0):
        no = nos[v["dispositivo_id"]]
        pai = nos.get(v.get("parent_identifier") or "")
        (pai["filhos"] if pai else raizes).append(no)
    return raizes


def norma(store: Armazenamento, document_id: str, *, agora: datetime | None = None) -> dict[str, Any] | None:
    agora = agora or datetime.now(UTC)
    doc = store.documento(document_id)
    item = sincronizacao.item_do_manifesto(document_id)
    if not doc and not item:
        return None
    if not doc:
        doc = {"document_id": document_id, "document_name": item["nome"], "nome_amigavel": item.get("nome_amigavel"),
               "source_url": item["url"], "official_source": item.get("fonte"), "sync_status": st.PENDENTE}
    atuais = store.versoes(document_id, atuais=True, com_texto=False)
    return {
        **_linha_norma(doc, store.contagens().get(document_id) or {}, item, agora),
        "relatorio": doc.get("report") or {},
        "arvore": arvore(atuais),
        "legado": [_limpo(v) for v in atuais if not v.get("dispositivo_id")][:50],
        "sincronizacoes": [_limpo(s) for s in store.sincronizacoes(document_id=document_id, limite=20)],
        "alertas": [_limpo(a) for a in store.alertas(abertos=True) if a.get("document_id") == document_id][:50],
        "anotacoes": [_limpo(a) for a in store.anotacoes(document_id=document_id) if not a.get("dispositivo_id")],
    }


def dispositivo(store: Armazenamento, version_id: int) -> dict[str, Any] | None:
    v = store.versao(version_id)
    if not v:
        return None
    disp = v.get("dispositivo_id") or v["identifier"]
    historico = store.versoes(v["document_id"], dispositivo_id=disp)
    chunk = None
    artigo_id = disp.split(".par-")[0].split(".inc-")[0].split(".ali-")[0]
    for c in store.chunks(v["document_id"]):
        if (c.get("metadados") or {}).get("dispositivo") in (artigo_id, v["identifier"]):
            chunk = {"id": c["id"], "tem_embedding": bool(c.get("tem_embedding")), "modelo": c.get("embedding_model"),
                     "dimensoes": c.get("embedding_dimensions"), "gerado_em": _iso(c.get("embedded_at")), "content_hash": c.get("content_hash")
                     or (c.get("metadados") or {}).get("content_hash") or (c.get("metadados") or {}).get("sha256"),
                     "invalidado_em": _iso(c.get("invalidado_em") or (c.get("metadados") or {}).get("invalidado_em")),
                     "artigo": artigo_id, "versao_vinculada": c.get("device_version_id")}
            break
    autoridade = st.autoridade_de_versao(v)
    return {
        "id": v["id"], "document_id": v["document_id"], "norma": v.get("nome_amigavel") or v.get("document_name"), "dispositivo_id": disp,
        "rotulo": (v.get("hierarchy") or {}).get("rotulo") or disp, "tipo": v.get("tipo_no"), "texto": v.get("text") or "",
        "status": v.get("status"), "versao": v.get("version"), "valid_from": _iso(v.get("valid_from")), "valid_until": _iso(v.get("valid_until")),
        "valid_from_origem": v.get("valid_from_origem") or "", "content_hash": v.get("content_hash"), "url": v.get("source_url"),
        "coletado_em": _iso(v.get("retrieved_at")), "ultima_verificacao": _iso(v.get("ultima_verificacao")), "superada_por": v.get("superada_por") or "",
        "hierarquia": v.get("hierarchy") or {},
        "versoes": [{"id": h["id"], "versao": h.get("version"), "status": h.get("status"), "valid_from": _iso(h.get("valid_from")),
                     "valid_until": _iso(h.get("valid_until")), "content_hash": h.get("content_hash"), "texto": h.get("text") or "",
                     "superada_por": h.get("superada_por") or ""} for h in historico],
        "embedding": chunk,
        "como_o_gate_ve": {"authority_id": autoridade.id, "chave": autoridade.chave, "status": autoridade.status,
                           "vigente_hoje": autoridade.vigente_em(datetime.now(UTC).date()), "verificada": autoridade.verificada},
        "anotacoes": [_limpo(a) for a in store.anotacoes(document_id=v["document_id"], dispositivo_id=disp)],
    }


def resolver_autoridade(store: Armazenamento, authority_id: str) -> dict[str, Any]:
    """Link do trace da peça: `ndv:123` abre o dispositivo; outra autoridade abre a ficha da jurisprudência."""
    if authority_id.startswith("ndv:") and authority_id[4:].isdigit():
        v = store.versao(int(authority_id[4:]))
        if v:
            return {"tipo": "dispositivo", "document_id": v["document_id"], "version_id": v["id"]}
    for a in store.autoridades():
        if a["id"] == authority_id or a.get("chave") == authority_id:
            return {"tipo": "jurisprudencia", "authority_id": a["id"]}
    return {"tipo": "desconhecida", "authority_id": authority_id}


def problemas(store: Armazenamento, *, agora: datetime | None = None) -> list[dict[str, Any]]:
    agora = agora or datetime.now(UTC)
    saida = []
    for l in normas(store, agora=agora):
        if l["selo"]["status"] == st.ERRO:
            saida.append({"tipo": "SINCRONIZACAO_COM_ERRO", "severidade": "alta", "norma": l["id"], "titulo": f"{l['nome']}: {l['ultimo_erro'] or 'erro'}"})
        if l["desatualizada"] and l["selo"]["status"] != st.PENDENTE:
            saida.append({"tipo": "NORMA_DESATUALIZADA", "severidade": "media", "norma": l["id"],
                          "titulo": f"{l['nome']}: sem verificação há mais de {HORAS_DESATUALIZADA} h"})
        if l["selo"]["status"] == st.PENDENTE and not l["ultima_verificacao"]:
            saida.append({"tipo": "NUNCA_SINCRONIZADA", "severidade": "media", "norma": l["id"], "titulo": f"{l['nome']}: ainda não sincronizada"})
        if l["embeddings"]["chunks_pendentes"]:
            saida.append({"tipo": "EMBEDDINGS_PENDENTES", "severidade": "media", "norma": l["id"],
                          "titulo": f"{l['nome']}: {l['embeddings']['chunks_pendentes']} trecho(s) sem vetor"})
        if l["legado"]:
            saida.append({"tipo": "CARGA_ANTIGA", "severidade": "baixa", "norma": l["id"],
                          "titulo": f"{l['nome']}: {l['legado']} versão(ões) da carga antiga ainda sem id estável"})
        if l["sem_vigencia"]:
            saida.append({"tipo": "SEM_DATA_DE_VIGENCIA", "severidade": "media", "norma": l["id"],
                          "titulo": f"{l['nome']}: {l['sem_vigencia']} dispositivo(s) sem início de vigência (o gate não aprova)"})
    for a in store.alertas(abertos=True, limite=300):
        if a.get("tipo") in ("ENCODING_CORROMPIDO", "FONTE_INDISPONIVEL", "EMBEDDING_FALHOU", "SKILL_CITA_SUPERADA", "AUTORIDADE_SUPERADA"):
            saida.append({"tipo": a["tipo"], "severidade": a.get("severidade") or "media", "norma": a.get("document_id") or "",
                          "titulo": a.get("titulo") or a["tipo"], "alerta_id": a["id"]})
    ordem = {"alta": 0, "media": 1, "baixa": 2}
    return sorted(saida, key=lambda p: ordem.get(p["severidade"], 3))


def configuracao() -> dict[str, Any]:
    """O que está ligado, sem expor segredo nenhum."""
    return {"sincronizacao_ativa": agenda.ativa(), "agenda": agenda.descricao(), "embeddings_configurados": sincronizacao.embeddings_configurados(),
            "validade_dias": st.validade_dias(), "armazenamento": "json-local" if os.getenv("ACERVO_ARMAZENAMENTO_JSON") else "pgvector"}
