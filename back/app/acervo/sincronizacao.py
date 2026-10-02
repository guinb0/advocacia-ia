"""Sincronização incremental de uma norma com a fonte oficial.

busca → decodifica (sem mascarar encoding) → normaliza → hash do documento → árvore → diff por
dispositivo → nova versão só do que mudou (a anterior é encerrada com `valid_until`) → embedding só
dos artigos cujo texto mudou → status e alertas.

Garantias:
- falha de fonte, de encoding ou de parser NÃO toca em nada já gravado: a norma fica em ERRO com o
  motivo e o texto anterior continua servindo (com a validade da última verificação);
- queda brusca no número de artigos é tratada como falha da fonte, não como revogação em massa;
- embedding que falha deixa o trecho pendente (sem vetor) e invalidado para a busca — texto novo
  nunca fica pareado com vetor do texto velho;
- `simular=True` lê o banco, calcula tudo e não escreve nem chama o provedor de embeddings.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from . import agenda, encoding, parser
from . import status as st
from .armazenamento import Armazenamento, MigracaoNaoAplicada, Mudancas

log = logging.getLogger("acervo")

MANIFESTO = Path(__file__).with_name("manifesto.json")
LOTE_EMBEDDINGS = 16
#: Abaixo desta fração dos artigos da última carga, a página é tratada como quebrada.
FRACAO_MINIMA_DE_ARTIGOS = 0.5


@dataclass
class Resposta:
    conteudo: bytes
    content_type: str = ""
    last_modified: datetime | None = None
    status: int = 200


Baixar = Callable[[str], Resposta]
GerarEmbeddings = Callable[[list[str]], list[list[float]]]


@lru_cache(maxsize=1)
def manifesto() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(MANIFESTO.read_text(encoding="utf-8")))


def item_do_manifesto(document_id: str) -> dict[str, Any] | None:
    return next((dict(i) for i in manifesto() if i["id"] == document_id), None)


def baixar_http(url: str) -> Resposta:
    from email.utils import parsedate_to_datetime

    import httpx
    ultimo: Exception | None = None
    for tentativa in range(3):
        try:
            # O Planalto derruba a conexão (WinError 10054 / reset) de User-Agent que não começa com "Mozilla/5.0".
            r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; AdvocaciaIA-Acervo/2.0)"}, timeout=90, follow_redirects=True)
            r.raise_for_status()
            modificado = None
            if r.headers.get("last-modified"):
                try:
                    modificado = parsedate_to_datetime(r.headers["last-modified"]).astimezone(UTC)
                except (TypeError, ValueError):
                    modificado = None
            return Resposta(r.content, r.headers.get("content-type", ""), modificado, r.status_code)
        except httpx.HTTPError as erro:
            ultimo = erro
            time.sleep(2 ** tentativa)
    raise RuntimeError(f"FONTE_INDISPONIVEL: {ultimo}")


def embeddings_configurados() -> bool:
    # A mesma chave global da OpenRouter atende transcrição, OCR e embeddings.
    # EMBEDDINGS_API_KEY fica como reserva para instalações antigas.
    return bool(
        os.getenv("EMBEDDINGS_BASE_URL", "").strip()
        and os.getenv("EMBEDDINGS_MODEL_NAME", "").strip()
        and (os.getenv("OPENROUTER_API_KEY", "").strip() or os.getenv("EMBEDDINGS_API_KEY", "").strip())
    )


def gerar_embeddings_padrao(textos: list[str]) -> list[list[float]]:
    from .. import rag
    return rag.gerar_embeddings(textos, timeout=180)


def modelo_de_embedding() -> tuple[str, int]:
    return os.getenv("EMBEDDINGS_MODEL_NAME", "").strip(), int(os.getenv("EMBEDDINGS_DIMENSIONS", "1536") or 1536)


# ------------------------------------------------------------------ associação com a carga antiga

_LEGADO = re.compile(r"^art-(\d[\d.]*)\s*[ºo°]?(?:-([A-Za-z]{1,2}))?-(\d+)$")


def _associar_legado(legado: list[dict[str, Any]], artigos: list[parser.No]) -> dict[str, dict[str, Any]]:
    """Linha antiga ("art-482-310", posicional) → artigo novo. Mesmo texto primeiro; depois o mais próximo em posição."""
    por_numero: dict[str, list[tuple[int, parser.No]]] = {}
    for pos, a in enumerate(artigos, start=1):
        por_numero.setdefault(a.artigo, []).append((pos, a))
    usados: set[str] = set()
    saida: dict[str, dict[str, Any]] = {}
    for v in sorted(legado, key=lambda v: v["identifier"]):
        m = _LEGADO.match(str(v["identifier"]))
        if not m:
            continue
        numero = parser.numero_do_artigo(m[1], m[2])
        candidatos = [(p, a) for p, a in por_numero.get(numero, []) if a.dispositivo_id not in usados]
        if not candidatos:
            continue
        mesmo = next((a for _, a in candidatos if a.hash == v["content_hash"]), None)
        escolhido = mesmo or min(candidatos, key=lambda pa: abs(pa[0] - int(m[3])))[1]
        usados.add(escolhido.dispositivo_id)
        saida[escolhido.dispositivo_id] = v
    return saida


# ------------------------------------------------------------------ uma norma

def _campos_estaticos(item: dict[str, Any]) -> dict[str, Any]:
    return {"document_name": item["nome"], "document_number": item.get("numero") or "", "document_year": item.get("ano") or "",
            "official_source": item.get("fonte") or "", "source_url": item["url"], "categoria": item.get("categoria") or "legislacao",
            "tipo": item.get("tipo") or "lei", "nome_amigavel": item.get("nome_amigavel") or item["nome"],
            "chave_norma": item.get("chave_norma") or "", "orgao": item.get("orgao") or ""}


def _linha_versao(no: parser.No, *, versao: int | None, hoje: date, url: str, agora: datetime) -> dict[str, Any]:
    return {"identifier": no.dispositivo_id, "dispositivo_id": no.dispositivo_id, "version": versao, "parent_identifier": no.parent or None,
            "hierarchy": {"ancestrais": no.contexto, "paragrafo": no.paragrafo, "inciso": no.inciso, "alinea": no.alinea, "rotulo": no.rotulo},
            "text": no.texto, "content_hash": no.hash, "status": no.status, "valid_from": hoje, "valid_until": None,
            "valid_from_origem": "observado", "source_url": url, "retrieved_at": agora, "tipo_no": no.tipo_no, "artigo": no.artigo,
            "paragrafo": no.paragrafo, "inciso": no.inciso, "alinea": no.alinea, "ordem": no.ordem}


def sincronizar_documento(
    item: dict[str, Any], *, armazenamento: Armazenamento, baixar: Baixar = baixar_http,
    gerar_embeddings: GerarEmbeddings | None = None, agora: datetime | None = None, origem: str = "agendada",
    solicitado_por: str = "", simular: bool = False, forcar_reindexacao: bool = False,
) -> dict[str, Any]:
    """Sincroniza uma norma. Devolve o relatório (o mesmo que vai para `acervo_sincronizacoes`)."""
    if not armazenamento.migracao_aplicada():
        raise MigracaoNaoAplicada("migration 011_acervo_juridico.sql não aplicada no PostgreSQL do RAG")
    relogio = time.monotonic()
    agora = agora or datetime.now(UTC)
    hoje = agora.astimezone(UTC).date()
    doc_id = item["id"]
    anterior = armazenamento.documento(doc_id) or {}
    proxima = agenda.proxima_execucao(agora)
    rel: dict[str, Any] = {"document_id": doc_id, "nome": item["nome"], "simulado": simular, "status": "", "erro": "",
                           "dispositivos_total": 0, "dispositivos_novos": 0, "dispositivos_alterados": 0, "dispositivos_revogados": 0,
                           "dispositivos_removidos": 0, "legado_associado": 0, "legado_reprocessado": 0, "legado_encerrado": 0,
                           "embeddings_gerados": 0, "embeddings_mantidos": 0, "embeddings_invalidados": 0, "embeddings_pendentes": 0,
                           "tokens_embeddings_aprox": 0,
                           "alterados": [], "revogados": [], "removidos": [], "novos": []}
    sinc_id = None
    if not simular:
        sinc_id = armazenamento.abrir_sincronizacao(doc_id, origem=origem, solicitado_por=solicitado_por, agora=agora)
        armazenamento.salvar_documento(doc_id, {**_campos_estaticos(item), "sync_status": st.EM_ANDAMENTO})

    def falhar(tipo: str, mensagem: str) -> dict[str, Any]:
        rel.update(status=st.ERRO, erro=mensagem)
        if not simular:
            armazenamento.salvar_documento(doc_id, {"sync_status": st.ERRO, "ultimo_erro": mensagem[:1000], "last_checked_at": agora,
                                                    "next_check_at": proxima})
            armazenamento.alertar({"tipo": tipo, "severidade": "alta", "document_id": doc_id, "titulo": f"{item['nome']}: {mensagem[:160]}",
                                   "detalhe": "O texto anterior continua no acervo; nada foi alterado.", "sincronizacao_id": sinc_id}, agora=agora)
            armazenamento.fechar_sincronizacao(sinc_id, {"status": st.ERRO, "erro": mensagem[:2000], "concluida_em": datetime.now(UTC),
                                                         "duracao_ms": int((time.monotonic() - relogio) * 1000), "relatorio": rel})
        return rel

    # 1. fonte → texto íntegro → árvore
    try:
        resposta = baixar(item["url"])
        bruto, codificacao = encoding.decodificar(resposta.conteudo, resposta.content_type)
        texto = parser.texto_do_html(bruto) if "<" in bruto[:2000] else encoding.normalizar(bruto)
        nos = parser.arvore(texto, nome_documento=item["nome"])
    except encoding.ErroEncoding as erro:
        return falhar("ENCODING_CORROMPIDO", str(erro))
    except ValueError as erro:
        return falhar("FONTE_INDISPONIVEL", f"PARSER: {erro}")
    except Exception as erro:  # noqa: BLE001
        return falhar("FONTE_INDISPONIVEL", str(erro)[:500])

    artigos = [n for n in nos if n.tipo_no == "artigo"]
    abertas = armazenamento.versoes_abertas(doc_id)
    artigos_antes = sum(1 for v in abertas if (v.get("tipo_no") or "artigo") == "artigo")
    if artigos_antes and len(artigos) < artigos_antes * FRACAO_MINIMA_DE_ARTIGOS:
        return falhar("FONTE_INDISPONIVEL", f"PARSER_QUEDA_DE_DISPOSITIVOS: {len(artigos)} artigos agora, {artigos_antes} na última carga")

    digest = parser.sha256(texto)
    rel.update(dispositivos_total=len(nos), encoding=codificacao, content_hash=digest,
               texto_inalterado=bool(anterior.get("content_hash")) and anterior.get("content_hash") == digest)

    # 2. diff por dispositivo
    m = Mudancas(fonte={"titulo": item["nome"], "url": item["url"]}, ordem_dos_artigos={n.dispositivo_id: n.ordem for n in artigos})
    por_disp = {v["dispositivo_id"]: v for v in abertas if v.get("dispositivo_id")}
    legado = [v for v in abertas if not v.get("dispositivo_id")]
    primeira_carga = not por_disp
    associados = _associar_legado(legado, artigos)
    vistos: set[str] = set()
    alertas: list[dict[str, Any]] = []
    for no in nos:
        vistos.add(no.dispositivo_id)
        atual = por_disp.get(no.dispositivo_id)
        antigo = associados.get(no.dispositivo_id) if atual is None else None
        if atual is None and antigo is None:
            m.inserir.append(_linha_versao(no, versao=None, hoje=hoje, url=item["url"], agora=agora))
            rel["dispositivos_novos"] += 1
            if not primeira_carga and no.tipo_no == "artigo":
                rel["novos"].append(no.dispositivo_id)
                alertas.append({"tipo": "DISPOSITIVO_INCLUIDO", "severidade": "baixa", "dispositivo_id": no.dispositivo_id,
                                "titulo": f"{item['nome']}: {no.rotulo} incluído na fonte oficial"})
            continue
        if antigo is not None:
            if antigo["content_hash"] == no.hash:
                coletado = antigo.get("retrieved_at")
                inicio = antigo.get("valid_from") or (coletado.date() if isinstance(coletado, datetime) else hoje)
                m.associar.append((antigo["id"], {"dispositivo_id": no.dispositivo_id, "tipo_no": "artigo", "artigo": no.artigo, "ordem": no.ordem,
                                                  "status": no.status, "valid_from": inicio, "valid_from_origem": "observado",
                                                  "ultima_verificacao": agora}))
                rel["legado_associado"] += 1
            else:
                # Reprocessamento da carga antiga (parser novo), não alteração legislativa: sem alerta e sem marcar ALTERADA.
                m.encerrar.append((antigo["id"], hoje, f"{no.dispositivo_id}@v{int(antigo['version']) + 1}", None))
                m.inserir.append(_linha_versao(no, versao=int(antigo["version"]) + 1, hoje=hoje, url=item["url"], agora=agora))
                rel["legado_reprocessado"] += 1
            continue
        status_antes = st.status_no(atual.get("status"))
        mudou_texto, mudou_status = atual["content_hash"] != no.hash, status_antes != no.status
        if not (mudou_texto or mudou_status):
            m.tocar.append(atual["id"])
            continue
        nova = int(atual["version"]) + 1
        m.encerrar.append((atual["id"], hoje, f"{no.dispositivo_id}@v{nova}", st.ALTERADA if status_antes == st.VIGENTE else None))
        m.inserir.append(_linha_versao(no, versao=nova, hoje=hoje, url=item["url"], agora=agora))
        if no.status == st.REVOGADA and status_antes == st.VIGENTE:
            rel["dispositivos_revogados"] += 1
            rel["revogados"].append(no.dispositivo_id)
            alertas.append({"tipo": "DISPOSITIVO_REVOGADO", "severidade": "alta", "dispositivo_id": no.dispositivo_id,
                            "titulo": f"{item['nome']}: {no.rotulo} ({no.dispositivo_id}) revogado na fonte oficial",
                            "dados": {"versao_anterior": int(atual["version"]), "versao_nova": nova}})
        else:
            rel["dispositivos_alterados"] += 1
            rel["alterados"].append(no.dispositivo_id)
            if no.tipo_no == "artigo":
                alertas.append({"tipo": "DISPOSITIVO_ALTERADO", "severidade": "media", "dispositivo_id": no.dispositivo_id,
                                "titulo": f"{item['nome']}: redação de {no.rotulo} alterada na fonte oficial",
                                "dados": {"versao_anterior": int(atual["version"]), "versao_nova": nova}})
    for disp, v in por_disp.items():
        if disp not in vistos:
            m.encerrar.append((v["id"], hoje, "", None))
            rel["dispositivos_removidos"] += 1
            rel["removidos"].append(disp)
            if (v.get("tipo_no") or "artigo") == "artigo":
                alertas.append({"tipo": "DISPOSITIVO_REMOVIDO", "severidade": "alta", "dispositivo_id": disp,
                                "titulo": f"{item['nome']}: {disp} não aparece mais na fonte oficial",
                                "detalhe": "Conferir na fonte: pode ser renumeração, revogação sem texto ou falha da página."})
    usados_legado = {v["id"] for v in associados.values()}
    for v in legado:
        if v["id"] not in usados_legado:
            m.encerrar.append((v["id"], hoje, "", None))
            rel["legado_encerrado"] += 1
    for no in artigos:
        m.referencias.extend((no.dispositivo_id, alvo) for alvo in parser.referencias(no.texto))

    # 3. embeddings só do que mudou
    _planejar_embeddings(item, artigos, associados, armazenamento.chunks(doc_id), m, rel, forcar=forcar_reindexacao)
    pendentes = [g for g in m.chunks_gravar if g.pop("_precisa", False)]
    modelo, dimensoes = modelo_de_embedding()
    if pendentes and gerar_embeddings is not None and not simular:
        falhou = ""
        for i in range(0, len(pendentes), LOTE_EMBEDDINGS):
            lote = pendentes[i:i + LOTE_EMBEDDINGS]
            try:
                vetores = gerar_embeddings([g["texto"] for g in lote])
                if len(vetores) != len(lote):
                    raise RuntimeError("quantidade de vetores diferente da de textos")
            except Exception as erro:  # noqa: BLE001
                falhou = str(erro)[:300]
                continue
            for g, v in zip(lote, vetores):
                g.update(embedding=v, embedding_model=modelo, embedding_dimensions=len(v), embedded_at=datetime.now(UTC))
                rel["embeddings_gerados"] += 1
                rel["tokens_embeddings_aprox"] += len(g["texto"]) // 4
        if falhou:
            alertas.append({"tipo": "EMBEDDING_FALHOU", "severidade": "media", "titulo": f"{item['nome']}: embeddings pendentes",
                            "detalhe": f"Os trechos ficam fora da busca até a próxima sincronização. Erro: {falhou}"})
    rel["embeddings_pendentes"] = sum(1 for g in pendentes if not g.get("embedding"))

    # 4. grava tudo de uma vez
    if simular:
        rel["status"] = "SIMULADO"
        return rel
    try:
        armazenamento.aplicar(doc_id, m, agora=agora)
    except Exception as erro:  # noqa: BLE001 - a transação volta inteira; o registro não pode ficar EM_ANDAMENTO
        log.exception("acervo: falha ao gravar %s", doc_id)
        return falhar("FALHA_NA_GRAVACAO", f"GRAVACAO: {type(erro).__name__}: {str(erro)[:400]}")
    for a in alertas:
        armazenamento.alertar({"document_id": doc_id, "sincronizacao_id": sinc_id, **a}, agora=agora)
    houve_mudanca = bool(m.inserir or m.encerrar or m.associar)
    contagem = armazenamento.contagens().get(doc_id) or {}
    sync = st.PENDENTE if rel["embeddings_pendentes"] else st.ATUALIZADO
    if item.get("status_juridico") == st.REVOGADA:
        sync = st.REVOGADO
    armazenamento.salvar_documento(doc_id, {
        **_campos_estaticos(item), "retrieved_at": agora, "parser_version": parser.VERSAO_PARSER, "total_devices": len(nos),
        "total_chunks": len(artigos), "total_embeddings": int(contagem.get("chunks_com_embedding") or 0),
        "current_devices": sum(1 for n in nos if n.status == st.VIGENTE), "revoked_devices": sum(1 for n in nos if n.status != st.VIGENTE),
        "historical_versions": int(contagem.get("versoes_historicas") or 0),
        "status": "COMPLETE" if not rel["embeddings_pendentes"] else "VALIDATED_PENDING_EMBEDDINGS",
        "last_checked_at": agora, "content_hash": digest, "encoding": codificacao,
        "last_updated_at": agora if houve_mudanca else anterior.get("last_updated_at") or agora,
        "next_check_at": proxima, "source_last_modified_at": resposta.last_modified, "sync_status": sync, "ultimo_erro": "",
        "report": {k: rel[k] for k in rel if not isinstance(rel[k], list)},
    })
    rel["status"] = "ATUALIZADO" if houve_mudanca else "SEM_ALTERACAO"
    rel["duracao_ms"] = int((time.monotonic() - relogio) * 1000)
    armazenamento.fechar_sincronizacao(sinc_id, {
        "status": rel["status"], "concluida_em": datetime.now(UTC), "content_hash": digest, "encoding": codificacao,
        "duracao_ms": rel["duracao_ms"], "tokens_embeddings_aprox": rel["tokens_embeddings_aprox"],
        **{k: rel[k] for k in ("dispositivos_total", "dispositivos_novos", "dispositivos_alterados", "dispositivos_revogados",
                               "dispositivos_removidos", "embeddings_gerados", "embeddings_mantidos", "embeddings_invalidados")},
        "relatorio": {k: (v[:200] if isinstance(v, list) else v) for k, v in rel.items()},
    })
    return rel


def _planejar_embeddings(item: dict[str, Any], artigos: list[parser.No], associados: dict[str, dict[str, Any]],
                         chunks: list[dict[str, Any]], m: Mudancas, rel: dict[str, Any], *, forcar: bool) -> None:
    """Decide, artigo a artigo, se o vetor fica, se é refeito ou se o trecho sai da busca."""
    por_disp: dict[str, dict[str, Any]] = {}
    for c in chunks:
        disp = str((c.get("metadados") or {}).get("dispositivo") or "")
        if disp:
            por_disp.setdefault(disp, c)
    legado_para_novo = {v["identifier"]: novo for novo, v in associados.items()}
    for antigo, novo in legado_para_novo.items():
        if antigo in por_disp and novo not in por_disp:
            por_disp[novo] = por_disp.pop(antigo)
    usados: set[int] = set()
    for no in artigos:
        c = por_disp.get(no.dispositivo_id)
        texto = parser.texto_para_embedding(no, item["nome"])
        h = parser.sha256(texto)
        if c:
            usados.add(c["id"])
        if no.status != st.VIGENTE:
            if c and not c.get("invalidado_em"):
                m.chunks_invalidar.append(c["id"])
                rel["embeddings_invalidados"] += 1
            continue
        meta = c.get("metadados") or {} if c else {}
        mesmo = c is not None and (c.get("content_hash") == h or meta.get("content_hash") == h or meta.get("sha256") == no.hash)
        if mesmo and c.get("tem_embedding") and not c.get("invalidado_em") and not forcar:
            m.chunks_manter.append((c["id"], no.dispositivo_id, h))
            rel["embeddings_mantidos"] += 1
            continue
        if c and c.get("tem_embedding") and not c.get("invalidado_em"):
            rel["embeddings_invalidados"] += 1
        m.chunks_gravar.append({
            "chunk_id": c["id"] if c else None, "dispositivo_id": no.dispositivo_id, "ordem": no.ordem, "texto": texto, "content_hash": h,
            "metadados": {"origem": "corpus_juridico_oficial", "document_id": item["id"], "dispositivo": no.dispositivo_id,
                          "artigo": no.artigo, "source_url": item["url"], "sha256": no.hash, "content_hash": h, "parser": parser.VERSAO_PARSER},
            "embedding": None, "_precisa": True,
        })
    for c in chunks:
        if c["id"] not in usados and not c.get("invalidado_em"):
            m.chunks_invalidar.append(c["id"])
            rel["embeddings_invalidados"] += 1


# ------------------------------------------------------------------ todas as normas

def sincronizar_tudo(
    *, armazenamento: Armazenamento, baixar: Baixar = baixar_http, gerar_embeddings: GerarEmbeddings | None = None,
    documentos: list[str] | None = None, origem: str = "agendada", solicitado_por: str = "", simular: bool = False,
    varrer_skills: bool = True, importar_jurisprudencia: bool = True,
) -> dict[str, Any]:
    from . import skills as skills_mod
    relatorios = []
    for item in manifesto():
        if documentos and item["id"] not in documentos:
            continue
        if item.get("categoria", "legislacao") != "legislacao":
            continue
        try:
            relatorios.append(sincronizar_documento(dict(item), armazenamento=armazenamento, baixar=baixar, gerar_embeddings=gerar_embeddings,
                                                    origem=origem, solicitado_por=solicitado_por, simular=simular))
        except MigracaoNaoAplicada:
            raise
        except Exception as erro:  # noqa: BLE001
            log.exception("acervo: falha inesperada em %s", item["id"])
            relatorios.append({"document_id": item["id"], "status": st.ERRO, "erro": str(erro)[:500]})
    jurisprudencia: dict[str, Any] = {}
    if importar_jurisprudencia and not simular and not documentos:
        from . import jurisprudencia as juris
        jurisprudencia = juris.importar_pasta(armazenamento=armazenamento, agora=datetime.now(UTC))
    alertas_skill: list[dict[str, Any]] = []
    if varrer_skills and not simular:
        alterados = {(r["document_id"], d) for r in relatorios for d in (r.get("alterados") or []) + (r.get("revogados") or [])}
        alertas_skill = skills_mod.varrer(armazenamento, alterados=alterados)
    return {"documentos": relatorios, "jurisprudencia": jurisprudencia, "alertas_de_skill": len(alertas_skill)}
