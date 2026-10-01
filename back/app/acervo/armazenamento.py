"""Onde o Acervo guarda as coisas: o mesmo contrato no PostgreSQL do RAG e em memória.

A sincronização calcula as mudanças sem escrever nada (`Mudancas`) e entrega tudo de uma vez a
`aplicar`, que no Postgres roda numa transação só: ou a norma inteira muda, ou nada muda.

`Memoria` serve aos testes e ao uso local (com `caminho`, persiste em JSON — é assim que o painel
roda sem pgvector). `Postgres` exige a migration 011; sem ela, `migracao_aplicada()` é False e a
sincronização recusa rodar.
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterator, Protocol

PREFIXO_FONTE = "corpus-juridico:"


class MigracaoNaoAplicada(RuntimeError):
    """A migration 011 não está no banco; o painel mostra "migração não aplicada"."""


@dataclass
class Mudancas:
    """Tudo o que uma sincronização de UMA norma muda, calculado antes de escrever."""
    encerrar: list[tuple[int, date, str, str | None]] = field(default_factory=list)  # (version_id, valid_until, superada_por, novo status)
    associar: list[tuple[int, dict[str, Any]]] = field(default_factory=list)     # linha antiga ganha dispositivo_id etc.
    inserir: list[dict[str, Any]] = field(default_factory=list)                  # novas versões
    tocar: list[int] = field(default_factory=list)                               # ultima_verificacao = agora
    chunks_manter: list[tuple[int, str, str]] = field(default_factory=list)      # (chunk_id, dispositivo_id, content_hash)
    chunks_gravar: list[dict[str, Any]] = field(default_factory=list)            # upsert de texto/embedding
    chunks_invalidar: list[int] = field(default_factory=list)
    referencias: list[tuple[str, str]] = field(default_factory=list)             # (dispositivo, texto citado)
    fonte: dict[str, str] = field(default_factory=dict)                          # titulo, url
    ordem_dos_artigos: dict[str, int] = field(default_factory=dict)             # dispositivo_id → ordem atual na fonte


def _agrupar_por_colunas(itens: Any) -> list[tuple[tuple[str, ...], list[tuple[Any, tuple[Any, ...]]]]]:
    """(chave, {coluna: valor}) agrupados pelo mesmo conjunto de colunas — um `executemany` por grupo."""
    grupos: dict[tuple[str, ...], list[tuple[Any, tuple[Any, ...]]]] = {}
    for chave, campos in itens:
        if campos:
            grupos.setdefault(tuple(campos), []).append((chave, tuple(campos.values())))
    return list(grupos.items())


class Armazenamento(Protocol):
    def migracao_aplicada(self) -> bool: ...
    def documento(self, document_id: str) -> dict[str, Any] | None: ...
    def documentos(self) -> list[dict[str, Any]]: ...
    def salvar_documento(self, document_id: str, campos: dict[str, Any]) -> None: ...
    def versoes_abertas(self, document_id: str) -> list[dict[str, Any]]: ...
    def versoes(self, document_id: str, *, dispositivo_id: str | None = None, atuais: bool = False, com_texto: bool = True) -> list[dict[str, Any]]: ...
    def versao(self, version_id: int) -> dict[str, Any] | None: ...
    def artigos(self, numeros: list[str]) -> list[dict[str, Any]]: ...
    def chunks(self, document_id: str) -> list[dict[str, Any]]: ...
    def aplicar(self, document_id: str, mudancas: Mudancas, *, agora: datetime) -> dict[str, Any]: ...
    def contagens(self) -> dict[str, dict[str, Any]]: ...
    def abrir_sincronizacao(self, document_id: str, *, origem: str, solicitado_por: str, agora: datetime) -> int: ...
    def fechar_sincronizacao(self, sinc_id: int, campos: dict[str, Any]) -> None: ...
    def sincronizacoes(self, *, document_id: str | None = None, limite: int = 50) -> list[dict[str, Any]]: ...
    def alertar(self, alerta: dict[str, Any], *, agora: datetime) -> bool: ...
    def alertas(self, *, abertos: bool = True, limite: int = 200) -> list[dict[str, Any]]: ...
    def resolver_alerta(self, alerta_id: int, *, por: str, agora: datetime) -> bool: ...
    def anotacoes(self, *, document_id: str = "", dispositivo_id: str = "", authority_id: str = "") -> list[dict[str, Any]]: ...
    def anotar(self, anotacao: dict[str, Any], *, agora: datetime) -> int: ...
    def autoridades(self) -> list[dict[str, Any]]: ...
    def salvar_autoridades(self, linhas: list[dict[str, Any]], *, agora: datetime) -> None: ...


def _proxima_versao(existentes: list[dict[str, Any]], identificador: str) -> int:
    return max((int(v["version"]) for v in existentes if v["identifier"] == identificador or v.get("dispositivo_id") == identificador), default=0) + 1


def _iso(valor: Any) -> Any:
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    return valor


def _de_iso(linha: dict[str, Any], datas: tuple[str, ...], instantes: tuple[str, ...]) -> dict[str, Any]:
    for k in datas:
        if isinstance(linha.get(k), str) and linha[k]:
            linha[k] = date.fromisoformat(linha[k][:10])
    for k in instantes:
        if isinstance(linha.get(k), str) and linha[k]:
            linha[k] = datetime.fromisoformat(linha[k])
    return linha


_DATAS_VERSAO = ("valid_from", "valid_until")
_INSTANTES_VERSAO = ("retrieved_at", "ultima_verificacao")
_INSTANTES_DOC = ("retrieved_at", "last_checked_at", "last_updated_at", "next_check_at", "source_last_modified_at")


# ====================================================================== memória (testes e uso local)

class Memoria:
    """Implementação em memória. Com `caminho`, carrega e grava um JSON a cada escrita."""

    def __init__(self, caminho: str | Path | None = None, *, migrada: bool = True):
        self.caminho = Path(caminho) if caminho else None
        self.migrada = migrada
        self._trava = threading.Lock()
        self.manifest: dict[str, dict[str, Any]] = {}
        self.versoes_: list[dict[str, Any]] = []
        self.chunks_: list[dict[str, Any]] = []
        self.sincs: list[dict[str, Any]] = []
        self.alertas_: list[dict[str, Any]] = []
        self.anotacoes_: list[dict[str, Any]] = []
        self.autoridades_: dict[str, dict[str, Any]] = {}
        self.referencias_: set[tuple[str, str, str]] = set()
        if self.caminho and self.caminho.is_file():
            self._carregar()

    # ------------------------------------------------------------ persistência opcional
    def _carregar(self) -> None:
        dados = json.loads(self.caminho.read_text(encoding="utf-8"))  # type: ignore[union-attr]
        self.manifest = {k: _de_iso(v, (), _INSTANTES_DOC) for k, v in (dados.get("manifest") or {}).items()}
        self.versoes_ = [_de_iso(v, _DATAS_VERSAO, _INSTANTES_VERSAO) for v in dados.get("versoes") or []]
        self.chunks_ = [_de_iso(c, (), ("embedded_at", "invalidado_em")) for c in dados.get("chunks") or []]
        self.sincs = [_de_iso(s, (), ("iniciada_em", "concluida_em")) for s in dados.get("sincronizacoes") or []]
        self.alertas_ = [_de_iso(a, (), ("criado_em", "resolvido_em")) for a in dados.get("alertas") or []]
        self.anotacoes_ = [_de_iso(a, (), ("criado_em",)) for a in dados.get("anotacoes") or []]
        self.autoridades_ = {a["id"]: a for a in dados.get("autoridades") or []}

    def _gravar(self) -> None:
        if not self.caminho:
            return
        def limpar(linhas: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [{k: _iso(v) for k, v in l.items()} for l in linhas]
        dados = {
            "manifest": {k: {kk: _iso(vv) for kk, vv in v.items()} for k, v in self.manifest.items()},
            "versoes": limpar(self.versoes_), "chunks": limpar(self.chunks_), "sincronizacoes": limpar(self.sincs),
            "alertas": limpar(self.alertas_), "anotacoes": limpar(self.anotacoes_), "autoridades": limpar(list(self.autoridades_.values())),
        }
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.caminho.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.caminho)

    # ------------------------------------------------------------ contrato
    def migracao_aplicada(self) -> bool:
        return self.migrada

    def documento(self, document_id: str) -> dict[str, Any] | None:
        d = self.manifest.get(document_id)
        return dict(d) if d else None

    def documentos(self) -> list[dict[str, Any]]:
        return [dict(v) for _, v in sorted(self.manifest.items())]

    def salvar_documento(self, document_id: str, campos: dict[str, Any]) -> None:
        with self._trava:
            self.manifest.setdefault(document_id, {"document_id": document_id}).update(campos)
            self._gravar()

    def versoes_abertas(self, document_id: str) -> list[dict[str, Any]]:
        return [dict(v) for v in self.versoes_ if v["document_id"] == document_id and v.get("valid_until") is None]

    def versoes(self, document_id: str, *, dispositivo_id: str | None = None, atuais: bool = False, com_texto: bool = True) -> list[dict[str, Any]]:
        saida = [v for v in self.versoes_ if v["document_id"] == document_id
                 and (dispositivo_id is None or v.get("dispositivo_id") == dispositivo_id or v["identifier"] == dispositivo_id)
                 and (not atuais or v.get("valid_until") is None)]
        saida = sorted(saida, key=lambda v: (v.get("ordem") or 0, v["identifier"], -int(v["version"])))
        return [dict(v) if com_texto else {k: x for k, x in v.items() if k != "text"} for v in saida]

    def versao(self, version_id: int) -> dict[str, Any] | None:
        v = next((v for v in self.versoes_ if v["id"] == version_id), None)
        if not v:
            return None
        doc = self.manifest.get(v["document_id"]) or {}
        return {**v, **{k: doc.get(k) for k in ("document_name", "document_number", "official_source", "chave_norma", "nome_amigavel")}}

    def artigos(self, numeros: list[str]) -> list[dict[str, Any]]:
        from . import status
        alvo = {n.lower() for n in numeros}
        saida = []
        for v in self.versoes_:
            artigo = (v.get("artigo") or status.artigo_do_identificador(v["identifier"])).lower()
            if artigo in alvo and (v.get("tipo_no") or "artigo") == "artigo":
                saida.append(self.versao(v["id"]))
        return [s for s in saida if s]

    def chunks(self, document_id: str) -> list[dict[str, Any]]:
        return [{**c, "tem_embedding": c.get("embedding") is not None} for c in self.chunks_ if c["document_id"] == document_id]

    def aplicar(self, document_id: str, mudancas: Mudancas, *, agora: datetime) -> dict[str, Any]:
        with self._trava:
            por_id = {v["id"]: v for v in self.versoes_}
            for vid, ate, superada, novo_status in mudancas.encerrar:
                por_id[vid].update(valid_until=ate, superada_por=superada, ultima_verificacao=agora)
                if novo_status:
                    por_id[vid]["status"] = novo_status
            for vid, campos in mudancas.associar:
                por_id[vid].update(campos)
            doc_versoes = [v for v in self.versoes_ if v["document_id"] == document_id]
            for linha in mudancas.inserir:
                nova = {"superada_por": "", "valid_until": None, "ultima_verificacao": agora, **linha, "document_id": document_id,
                        "id": max((v["id"] for v in self.versoes_), default=0) + 1}
                if not nova.get("version"):
                    nova["version"] = _proxima_versao(doc_versoes, nova["identifier"])
                self.versoes_.append(nova)
                doc_versoes.append(nova)
            for vid in mudancas.tocar:
                por_id[vid]["ultima_verificacao"] = agora
            abertas = {v.get("dispositivo_id"): v["id"] for v in doc_versoes if v.get("valid_until") is None and v.get("dispositivo_id")}
            por_chunk = {c["id"]: c for c in self.chunks_}
            for cid, disp, h in mudancas.chunks_manter:
                c = por_chunk[cid]
                c["metadados"] = {**{k: v for k, v in (c.get("metadados") or {}).items() if k != "invalidado_em"}, "dispositivo": disp, "content_hash": h}
                c.update(device_version_id=abertas.get(disp), content_hash=h, invalidado_em=None)
            for g in mudancas.chunks_gravar:
                c = por_chunk.get(g.get("chunk_id") or -1)
                if c is None:
                    c = {"id": max((x["id"] for x in self.chunks_), default=0) + 1, "document_id": document_id}
                    self.chunks_.append(c)
                    por_chunk[c["id"]] = c
                c.update(ordem=g["ordem"], texto=g["texto"], metadados=dict(g["metadados"]), embedding=g.get("embedding"),
                         device_version_id=abertas.get(g["dispositivo_id"]), content_hash=g["content_hash"],
                         embedding_model=g.get("embedding_model"), embedding_dimensions=g.get("embedding_dimensions"),
                         embedded_at=g.get("embedded_at"), invalidado_em=None)
            for cid in mudancas.chunks_invalidar:
                c = por_chunk[cid]
                c["invalidado_em"] = agora
                c["metadados"] = {**(c.get("metadados") or {}), "invalidado_em": agora.isoformat()}
            for disp, alvo in mudancas.referencias:
                self.referencias_.add((document_id, disp, alvo))
            self._gravar()
            return {"abertas": abertas}

    def contagens(self) -> dict[str, dict[str, Any]]:
        saida: dict[str, dict[str, Any]] = {}
        for v in self.versoes_:
            c = saida.setdefault(v["document_id"], _contagem_vazia())
            aberta = v.get("valid_until") is None
            c["dispositivos_atuais"] += int(aberta and bool(v.get("dispositivo_id")))
            c["artigos_atuais"] += int(aberta and bool(v.get("dispositivo_id")) and (v.get("tipo_no") or "artigo") == "artigo")
            c["revogados"] += int(aberta and v.get("status") in ("revogado", "vetado", "REVOGADA", "SUPERADA", "SUSPENSA"))
            c["versoes_historicas"] += int(not aberta)
            c["legado"] += int(aberta and not v.get("dispositivo_id"))
            c["sem_vigencia"] += int(aberta and not v.get("valid_from"))
        for ch in self.chunks_:
            c = saida.setdefault(ch["document_id"], _contagem_vazia())
            c["chunks"] += 1
            invalido = ch.get("invalidado_em") is not None
            c["chunks_invalidados"] += int(invalido)
            c["chunks_com_embedding"] += int(not invalido and ch.get("embedding") is not None)
            c["chunks_pendentes"] += int(not invalido and ch.get("embedding") is None)
            if ch.get("embedding_model"):
                c["modelos"] = sorted(set(c["modelos"]) | {ch["embedding_model"]})
            if ch.get("embedding_dimensions"):
                c["dimensoes"] = sorted(set(c["dimensoes"]) | {int(ch["embedding_dimensions"])})
            if ch.get("embedded_at") and (c["ultimo_embedding"] is None or ch["embedded_at"] > c["ultimo_embedding"]):
                c["ultimo_embedding"] = ch["embedded_at"]
        return saida

    def abrir_sincronizacao(self, document_id: str, *, origem: str, solicitado_por: str, agora: datetime) -> int:
        with self._trava:
            sid = max((s["id"] for s in self.sincs), default=0) + 1
            self.sincs.append({"id": sid, "document_id": document_id, "iniciada_em": agora, "concluida_em": None, "status": "EM_ANDAMENTO",
                               "origem": origem, "solicitado_por": solicitado_por, "erro": "", "relatorio": {}})
            self._gravar()
            return sid

    def fechar_sincronizacao(self, sinc_id: int, campos: dict[str, Any]) -> None:
        with self._trava:
            next(s for s in self.sincs if s["id"] == sinc_id).update(campos)
            self._gravar()

    def sincronizacoes(self, *, document_id: str | None = None, limite: int = 50) -> list[dict[str, Any]]:
        lista = [s for s in self.sincs if document_id is None or s["document_id"] == document_id]
        return [dict(s) for s in sorted(lista, key=lambda s: s["iniciada_em"], reverse=True)[:limite]]

    def alertar(self, alerta: dict[str, Any], *, agora: datetime) -> bool:
        chave = tuple(alerta.get(k, "") for k in ("tipo", "document_id", "dispositivo_id", "authority_id"))
        with self._trava:
            if any(a["resolvido_em"] is None and tuple(a.get(k, "") for k in ("tipo", "document_id", "dispositivo_id", "authority_id")) == chave
                   for a in self.alertas_):
                return False
            self.alertas_.append({"id": max((a["id"] for a in self.alertas_), default=0) + 1, "criado_em": agora, "resolvido_em": None,
                                  "resolvido_por": "", "severidade": "media", "document_id": "", "dispositivo_id": "", "authority_id": "",
                                  "detalhe": "", "dados": {}, "sincronizacao_id": None, **alerta})
            self._gravar()
            return True

    def alertas(self, *, abertos: bool = True, limite: int = 200) -> list[dict[str, Any]]:
        lista = [a for a in self.alertas_ if not abertos or a["resolvido_em"] is None]
        return [dict(a) for a in sorted(lista, key=lambda a: a["criado_em"], reverse=True)[:limite]]

    def resolver_alerta(self, alerta_id: int, *, por: str, agora: datetime) -> bool:
        with self._trava:
            a = next((a for a in self.alertas_ if a["id"] == alerta_id and a["resolvido_em"] is None), None)
            if not a:
                return False
            a.update(resolvido_em=agora, resolvido_por=por)
            self._gravar()
            return True

    def anotacoes(self, *, document_id: str = "", dispositivo_id: str = "", authority_id: str = "") -> list[dict[str, Any]]:
        return [dict(a) for a in self.anotacoes_ if (not document_id or a["document_id"] == document_id)
                and (not dispositivo_id or a["dispositivo_id"] == dispositivo_id) and (not authority_id or a["authority_id"] == authority_id)]

    def anotar(self, anotacao: dict[str, Any], *, agora: datetime) -> int:
        with self._trava:
            aid = max((a["id"] for a in self.anotacoes_), default=0) + 1
            self.anotacoes_.append({"id": aid, "criado_em": agora, "document_id": "", "dispositivo_id": "", "authority_id": "", **anotacao})
            self._gravar()
            return aid

    def autoridades(self) -> list[dict[str, Any]]:
        return [dict(a) for a in self.autoridades_.values()]

    def salvar_autoridades(self, linhas: list[dict[str, Any]], *, agora: datetime) -> None:
        with self._trava:
            for l in linhas:
                self.autoridades_[l["id"]] = {**self.autoridades_.get(l["id"], {}), **l, "atualizado_em": agora.isoformat()}
            self._gravar()


def _contagem_vazia() -> dict[str, Any]:
    return {"dispositivos_atuais": 0, "artigos_atuais": 0, "revogados": 0, "versoes_historicas": 0, "legado": 0, "sem_vigencia": 0,
            "chunks": 0, "chunks_com_embedding": 0, "chunks_pendentes": 0, "chunks_invalidados": 0, "modelos": [], "dimensoes": [],
            "ultimo_embedding": None}


# ====================================================================== PostgreSQL do RAG

_COLUNAS_DOC = ("document_name", "document_number", "document_year", "official_source", "source_url", "retrieved_at", "parser_version",
                "total_devices", "total_chunks", "total_embeddings", "current_devices", "revoked_devices", "historical_versions",
                "status", "last_checked_at", "report", "categoria", "tipo", "nome_amigavel", "chave_norma", "orgao", "tribunal",
                "content_hash", "last_updated_at", "next_check_at", "source_last_modified_at", "sync_status", "ultimo_erro", "encoding")
_COLUNAS_VERSAO = ("identifier", "dispositivo_id", "version", "parent_identifier", "hierarchy", "text", "content_hash", "status",
                   "valid_from", "valid_until", "source_url", "retrieved_at", "tipo_no", "artigo", "paragrafo", "inciso", "alinea",
                   "ordem", "superada_por", "ultima_verificacao", "valid_from_origem")
_COLUNAS_AUTORIDADE = ("id", "organization_id", "tipo", "chave", "titulo", "texto", "norma", "artigo", "paragrafo", "inciso", "alinea",
                       "tribunal", "orgao", "classe", "numero", "tema", "assunto", "tese", "data", "vigencia_inicio", "vigencia_fim",
                       "versao", "status", "superado_por", "vinculante", "transito_em_julgado", "fonte_oficial", "url", "verificado_em",
                       "verificada", "marcadores", "content_hash", "sync_status", "ultima_verificacao")


class Postgres:
    """Contrato sobre o PostgreSQL do RAG (`rag.url_pgvector()`)."""

    _cache_migracao: tuple[float, bool] | None = None

    def __init__(self, url: str | None = None, *, connect_timeout: int | None = None):
        self._url = url
        self.connect_timeout = connect_timeout or int(os.getenv("ACERVO_CONNECT_TIMEOUT", "8"))

    @contextmanager
    def _conexao(self) -> Iterator[Any]:
        import psycopg
        from psycopg.rows import dict_row
        from .. import rag
        with psycopg.connect(self._url or rag.url_pgvector(), connect_timeout=self.connect_timeout, row_factory=dict_row,
                             keepalives=1, keepalives_idle=15, keepalives_interval=5, keepalives_count=3) as con:
            yield con

    def _todas(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._conexao() as con:
            return list(con.execute(sql, params).fetchall())

    def migracao_aplicada(self) -> bool:
        agora = time.monotonic()
        if Postgres._cache_migracao and agora - Postgres._cache_migracao[0] < 60:
            return Postgres._cache_migracao[1]
        linha = self._todas(
            """SELECT to_regclass('acervo_sincronizacoes') IS NOT NULL AND to_regclass('acervo_alertas') IS NOT NULL
                      AND to_regclass('acervo_anotacoes') IS NOT NULL
                      AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='normative_device_versions' AND column_name='dispositivo_id')
                      AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='knowledge_chunks' AND column_name='device_version_id')
                      AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='corpus_manifest' AND column_name='sync_status')
                      AS ok""")[0]
        Postgres._cache_migracao = (agora, bool(linha["ok"]))
        return bool(linha["ok"])

    def documento(self, document_id: str) -> dict[str, Any] | None:
        linhas = self._todas("SELECT * FROM corpus_manifest WHERE document_id=%s", (document_id,))
        return linhas[0] if linhas else None

    def documentos(self) -> list[dict[str, Any]]:
        return self._todas("SELECT * FROM corpus_manifest ORDER BY document_id")

    def salvar_documento(self, document_id: str, campos: dict[str, Any]) -> None:
        from psycopg.types.json import Jsonb
        campos = {k: (Jsonb(v) if k == "report" else v) for k, v in campos.items() if k in _COLUNAS_DOC}
        with self._conexao() as con:
            existe = con.execute("SELECT 1 FROM corpus_manifest WHERE document_id=%s", (document_id,)).fetchone()
            if existe:
                if campos:
                    con.execute(f"UPDATE corpus_manifest SET {', '.join(f'{k}=%s' for k in campos)} WHERE document_id=%s",
                                (*campos.values(), document_id))
            else:
                base = {"document_name": document_id, "official_source": "", "source_url": "", "parser_version": "", **campos}
                con.execute(f"INSERT INTO corpus_manifest (document_id, {', '.join(base)}) VALUES (%s, {', '.join(['%s'] * len(base))})",
                            (document_id, *base.values()))

    def versoes_abertas(self, document_id: str) -> list[dict[str, Any]]:
        return self._todas(f"SELECT id, {', '.join(_COLUNAS_VERSAO)} FROM normative_device_versions WHERE document_id=%s AND valid_until IS NULL",
                           (document_id,))

    def versoes(self, document_id: str, *, dispositivo_id: str | None = None, atuais: bool = False, com_texto: bool = True) -> list[dict[str, Any]]:
        colunas = [c for c in _COLUNAS_VERSAO if com_texto or c != "text"]
        filtros, params = ["document_id=%s"], [document_id]
        if dispositivo_id:
            filtros.append("(dispositivo_id=%s OR identifier=%s)")
            params += [dispositivo_id, dispositivo_id]
        if atuais:
            filtros.append("valid_until IS NULL")
        return self._todas(f"SELECT id, document_id, {', '.join(colunas)} FROM normative_device_versions WHERE {' AND '.join(filtros)} "
                           "ORDER BY ordem, identifier, version DESC", tuple(params))

    def versao(self, version_id: int) -> dict[str, Any] | None:
        linhas = self._todas(
            f"""SELECT v.id, v.document_id, {', '.join('v.' + c for c in _COLUNAS_VERSAO)}, m.document_name, m.document_number,
                       m.official_source, m.chave_norma, m.nome_amigavel
                  FROM normative_device_versions v JOIN corpus_manifest m ON m.document_id=v.document_id WHERE v.id=%s""", (version_id,))
        return linhas[0] if linhas else None

    def artigos(self, numeros: list[str]) -> list[dict[str, Any]]:
        return self._todas(
            f"""SELECT v.id, v.document_id, {', '.join('v.' + c for c in _COLUNAS_VERSAO)}, m.document_name, m.document_number,
                       m.official_source, m.chave_norma, m.nome_amigavel
                  FROM normative_device_versions v JOIN corpus_manifest m ON m.document_id=v.document_id
                 WHERE v.tipo_no='artigo' AND (v.artigo = ANY(%s) OR (v.dispositivo_id IS NULL AND
                       lower(regexp_replace(regexp_replace(v.identifier, '^art-([0-9.]+)\\s*[ºo°]?(-[A-Za-z]{{1,2}})?-[0-9]+$', '\\1\\2'), '\\.', '', 'g')) = ANY(%s)))""",
            ([n.lower() for n in numeros], [n.lower() for n in numeros]))

    def chunks(self, document_id: str) -> list[dict[str, Any]]:
        return self._todas(
            """SELECT k.id, k.ordem, k.metadados, k.embedding IS NOT NULL AS tem_embedding, k.device_version_id, k.content_hash,
                      k.embedding_model, k.embedding_dimensions, k.embedded_at, k.invalidado_em
                 FROM knowledge_chunks k JOIN fontes f ON f.id=k.fonte_id WHERE f.identificador=%s""", (PREFIXO_FONTE + document_id,))

    def aplicar(self, document_id: str, mudancas: Mudancas, *, agora: datetime) -> dict[str, Any]:
        from psycopg.types.json import Jsonb
        from .. import rag
        # Tudo em lote (`executemany` usa o pipeline do psycopg): linha a linha, cada dispositivo custava duas idas
        # e voltas ao servidor e a Constituição levava mais de dez minutos só para gravar.
        with self._conexao() as con, con.transaction():
            cur = con.cursor()
            if mudancas.encerrar:
                cur.executemany("""UPDATE normative_device_versions SET valid_until=%s, superada_por=%s, ultima_verificacao=%s,
                                   status=COALESCE(%s, status) WHERE id=%s""",
                                [(ate, sup, agora, novo, vid) for vid, ate, sup, novo in mudancas.encerrar])
            for colunas, lote in _agrupar_por_colunas(
                    (vid, {k: (Jsonb(v) if k == "hierarchy" else v) for k, v in campos.items() if k in _COLUNAS_VERSAO})
                    for vid, campos in mudancas.associar):
                cur.executemany(f"UPDATE normative_device_versions SET {', '.join(f'{k}=%s' for k in colunas)} WHERE id=%s",
                                [(*valores, vid) for vid, valores in lote])
            if mudancas.inserir:
                maior: dict[str, int] = {}
                for r in cur.execute("SELECT identifier, dispositivo_id, max(version) AS v FROM normative_device_versions "
                                     "WHERE document_id=%s GROUP BY identifier, dispositivo_id", (document_id,)).fetchall():
                    for chave in (r["identifier"], r["dispositivo_id"]):
                        if chave:
                            maior[chave] = max(maior.get(chave, 0), int(r["v"] or 0))
                linhas = []
                for linha in mudancas.inserir:
                    l = {"ultima_verificacao": agora, **{k: v for k, v in linha.items() if k in _COLUNAS_VERSAO}}
                    if not l.get("version"):
                        l["version"] = maior.get(l["identifier"], 0) + 1
                    maior[l["identifier"]] = max(maior.get(l["identifier"], 0), int(l["version"]))
                    l["hierarchy"] = Jsonb(l.get("hierarchy") or {})
                    linhas.append((None, l))
                for colunas, lote in _agrupar_por_colunas(linhas):
                    cur.executemany(f"INSERT INTO normative_device_versions (document_id, {', '.join(colunas)}) "
                                    f"VALUES (%s, {', '.join(['%s'] * len(colunas))})", [(document_id, *valores) for _, valores in lote])
            if mudancas.tocar:
                cur.execute("UPDATE normative_device_versions SET ultima_verificacao=%s WHERE id = ANY(%s)", (agora, list(mudancas.tocar)))
            abertas = {r["dispositivo_id"]: r["id"] for r in cur.execute(
                "SELECT dispositivo_id, id FROM normative_device_versions WHERE document_id=%s AND valid_until IS NULL AND dispositivo_id IS NOT NULL",
                (document_id,)).fetchall()}
            fonte_id = None
            if mudancas.fonte or mudancas.chunks_gravar:
                fonte_id = cur.execute(
                    """INSERT INTO fontes(tipo,titulo,identificador,url) VALUES('lei',%s,%s,%s)
                       ON CONFLICT(tipo,identificador) WHERE identificador IS NOT NULL DO UPDATE SET titulo=EXCLUDED.titulo,url=EXCLUDED.url
                       RETURNING id""",
                    (mudancas.fonte.get("titulo") or document_id, PREFIXO_FONTE + document_id, mudancas.fonte.get("url") or "")).fetchone()["id"]
            # `uq_chunks_fonte_ordem (fonte_id, ordem)`: o trecho reescrito ganha a ordem ATUAL do artigo, mas os trechos que ficam
            # (mantidos e invalidados) ainda guardam a ordem da carga anterior — e a coluna é única. Antes de gravar, os trechos da
            # fonte vão para ordens negativas (abaixo de qualquer negativa já usada); depois, mantidos e reescritos voltam com a
            # ordem atual do artigo. Invalidado fica no negativo: está fora da busca.
            renumerar = bool(mudancas.chunks_gravar) and fonte_id is not None
            if renumerar:
                piso = cur.execute("SELECT LEAST(COALESCE(min(ordem), 0), 0) AS m FROM knowledge_chunks WHERE fonte_id=%s", (fonte_id,)).fetchone()["m"]
                cur.execute("UPDATE knowledge_chunks SET ordem = %s - 1 - ordem WHERE fonte_id=%s AND ordem >= 0", (piso, fonte_id))
            usadas = {g["ordem"] for g in mudancas.chunks_gravar}
            manter = []
            for cid, disp, h in mudancas.chunks_manter:
                ordem = mudancas.ordem_dos_artigos.get(disp) if renumerar else None
                if ordem is not None and ordem in usadas:
                    ordem = None
                if ordem is not None:
                    usadas.add(ordem)
                manter.append((Jsonb({"dispositivo": disp, "content_hash": h}), abertas.get(disp), h, ordem, cid))
            if manter:
                cur.executemany("""UPDATE knowledge_chunks SET metadados=(metadados - 'invalidado_em') || %s, device_version_id=%s, content_hash=%s,
                                   invalidado_em=NULL, ordem=COALESCE(%s, ordem) WHERE id=%s""", manter)
            atualizar, inserir = [], []
            for g in mudancas.chunks_gravar:
                vetor = rag.vetor_literal(g["embedding"]) if g.get("embedding") else None
                valores = (g["ordem"], g["texto"], Jsonb(g["metadados"]), vetor, abertas.get(g["dispositivo_id"]), g["content_hash"],
                           g.get("embedding_model"), g.get("embedding_dimensions"), g.get("embedded_at"))
                if g.get("chunk_id"):
                    atualizar.append((*valores, g["chunk_id"]))
                else:
                    inserir.append((*valores, fonte_id))
            if atualizar:
                cur.executemany("""UPDATE knowledge_chunks SET ordem=%s, texto=%s, metadados=%s, embedding=%s::vector, device_version_id=%s,
                                   content_hash=%s, embedding_model=%s, embedding_dimensions=%s, embedded_at=%s, invalidado_em=NULL WHERE id=%s""",
                                atualizar)
            if inserir:
                cur.executemany("""INSERT INTO knowledge_chunks (ordem, texto, metadados, embedding, device_version_id, content_hash,
                                   embedding_model, embedding_dimensions, embedded_at, fonte_id)
                                   VALUES (%s, %s, %s, %s::vector, %s, %s, %s, %s, %s, %s)""", inserir)
            if mudancas.chunks_invalidar:
                cur.execute("""UPDATE knowledge_chunks SET invalidado_em=%s, metadados=metadados || %s WHERE id = ANY(%s)""",
                            (agora, Jsonb({"invalidado_em": agora.isoformat()}), list(mudancas.chunks_invalidar)))
            if mudancas.referencias:
                cur.executemany("""INSERT INTO corpus_references(document_id,source_identifier,target_text,reason)
                                   VALUES(%s,%s,%s,'referência textual oficial') ON CONFLICT DO NOTHING""",
                                [(document_id, d, t) for d, t in mudancas.referencias])
            return {"abertas": abertas}

    def contagens(self) -> dict[str, dict[str, Any]]:
        saida: dict[str, dict[str, Any]] = {}
        for r in self._todas(
            """SELECT document_id,
                      count(*) FILTER (WHERE valid_until IS NULL AND dispositivo_id IS NOT NULL) AS dispositivos_atuais,
                      count(*) FILTER (WHERE valid_until IS NULL AND dispositivo_id IS NOT NULL AND tipo_no='artigo') AS artigos_atuais,
                      count(*) FILTER (WHERE valid_until IS NULL AND status IN ('revogado','vetado','REVOGADA','SUPERADA','SUSPENSA')) AS revogados,
                      count(*) FILTER (WHERE valid_until IS NOT NULL) AS versoes_historicas,
                      count(*) FILTER (WHERE valid_until IS NULL AND dispositivo_id IS NULL) AS legado,
                      count(*) FILTER (WHERE valid_until IS NULL AND valid_from IS NULL) AS sem_vigencia
                 FROM normative_device_versions GROUP BY document_id"""):
            saida[r["document_id"]] = {**_contagem_vazia(), **{k: v for k, v in r.items() if k != "document_id"}}
        for r in self._todas(
            """SELECT substr(f.identificador, length(%s) + 1) AS document_id, count(*) AS chunks,
                      count(*) FILTER (WHERE k.embedding IS NOT NULL AND (k.metadados->>'invalidado_em') IS NULL) AS chunks_com_embedding,
                      count(*) FILTER (WHERE k.embedding IS NULL AND (k.metadados->>'invalidado_em') IS NULL) AS chunks_pendentes,
                      count(*) FILTER (WHERE (k.metadados->>'invalidado_em') IS NOT NULL) AS chunks_invalidados,
                      COALESCE(array_agg(DISTINCT k.embedding_model) FILTER (WHERE k.embedding_model IS NOT NULL), '{}') AS modelos,
                      COALESCE(array_agg(DISTINCT vector_dims(k.embedding)) FILTER (WHERE k.embedding IS NOT NULL), '{}') AS dimensoes,
                      max(k.embedded_at) AS ultimo_embedding
                 FROM knowledge_chunks k JOIN fontes f ON f.id=k.fonte_id
                WHERE f.identificador LIKE %s GROUP BY 1""", (PREFIXO_FONTE, PREFIXO_FONTE + "%")):
            saida.setdefault(r["document_id"], _contagem_vazia()).update({k: v for k, v in r.items() if k != "document_id"})
        return saida

    def abrir_sincronizacao(self, document_id: str, *, origem: str, solicitado_por: str, agora: datetime) -> int:
        with self._conexao() as con:
            return con.execute("INSERT INTO acervo_sincronizacoes (document_id, iniciada_em, origem, solicitado_por) VALUES (%s,%s,%s,%s) RETURNING id",
                               (document_id, agora, origem, solicitado_por)).fetchone()["id"]

    def fechar_sincronizacao(self, sinc_id: int, campos: dict[str, Any]) -> None:
        from psycopg.types.json import Jsonb
        campos = {k: (Jsonb(v) if k == "relatorio" else v) for k, v in campos.items()}
        with self._conexao() as con:
            con.execute(f"UPDATE acervo_sincronizacoes SET {', '.join(f'{k}=%s' for k in campos)} WHERE id=%s", (*campos.values(), sinc_id))

    def sincronizacoes(self, *, document_id: str | None = None, limite: int = 50) -> list[dict[str, Any]]:
        if document_id:
            return self._todas("SELECT * FROM acervo_sincronizacoes WHERE document_id=%s ORDER BY iniciada_em DESC LIMIT %s", (document_id, limite))
        return self._todas("SELECT * FROM acervo_sincronizacoes ORDER BY iniciada_em DESC LIMIT %s", (limite,))

    def alertar(self, alerta: dict[str, Any], *, agora: datetime) -> bool:
        from psycopg.types.json import Jsonb
        a = {"severidade": "media", "document_id": "", "dispositivo_id": "", "authority_id": "", "detalhe": "", "dados": {}, **alerta}
        a["dados"] = Jsonb(a["dados"])
        with self._conexao() as con:
            r = con.execute(
                f"""INSERT INTO acervo_alertas (criado_em, {', '.join(a)}) VALUES (%s, {', '.join(['%s'] * len(a))})
                    ON CONFLICT (tipo, document_id, dispositivo_id, authority_id) WHERE resolvido_em IS NULL DO NOTHING RETURNING id""",
                (agora, *a.values())).fetchone()
            return r is not None

    def alertas(self, *, abertos: bool = True, limite: int = 200) -> list[dict[str, Any]]:
        filtro = "WHERE resolvido_em IS NULL" if abertos else ""
        return self._todas(f"SELECT * FROM acervo_alertas {filtro} ORDER BY criado_em DESC LIMIT %s", (limite,))

    def resolver_alerta(self, alerta_id: int, *, por: str, agora: datetime) -> bool:
        with self._conexao() as con:
            return con.execute("UPDATE acervo_alertas SET resolvido_em=%s, resolvido_por=%s WHERE id=%s AND resolvido_em IS NULL RETURNING id",
                               (agora, por, alerta_id)).fetchone() is not None

    def anotacoes(self, *, document_id: str = "", dispositivo_id: str = "", authority_id: str = "") -> list[dict[str, Any]]:
        return self._todas("""SELECT * FROM acervo_anotacoes WHERE (%s='' OR document_id=%s) AND (%s='' OR dispositivo_id=%s)
                              AND (%s='' OR authority_id=%s) ORDER BY criado_em DESC LIMIT 200""",
                           (document_id, document_id, dispositivo_id, dispositivo_id, authority_id, authority_id))

    def anotar(self, anotacao: dict[str, Any], *, agora: datetime) -> int:
        a = {"document_id": "", "dispositivo_id": "", "authority_id": "", "autor": "", **anotacao}
        with self._conexao() as con:
            return con.execute(f"INSERT INTO acervo_anotacoes (criado_em, {', '.join(a)}) VALUES (%s, {', '.join(['%s'] * len(a))}) RETURNING id",
                               (agora, *a.values())).fetchone()["id"]

    def autoridades(self) -> list[dict[str, Any]]:
        return self._todas("SELECT * FROM autoridades_juridicas WHERE organization_id='' LIMIT 20000")

    def salvar_autoridades(self, linhas: list[dict[str, Any]], *, agora: datetime) -> None:
        with self._conexao() as con, con.transaction():
            for l in linhas:
                l = {k: v for k, v in l.items() if k in _COLUNAS_AUTORIDADE}
                if "tipo" not in l:
                    # Linha parcial (só a data da conferência): INSERT com NOT NULL faltando falha antes do ON CONFLICT.
                    campos = {k: v for k, v in l.items() if k != "id"}
                    if campos:
                        con.execute(f"UPDATE autoridades_juridicas SET {', '.join(f'{k}=%s' for k in campos)}, atualizado_em=%s WHERE id=%s",
                                    (*campos.values(), agora, l["id"]))
                    continue
                atualiza = ", ".join(f"{k}=EXCLUDED.{k}" for k in l if k != "id")
                con.execute(f"""INSERT INTO autoridades_juridicas ({', '.join(l)}, atualizado_em) VALUES ({', '.join(['%s'] * len(l))}, %s)
                                ON CONFLICT (id) DO UPDATE SET {atualiza}, atualizado_em=EXCLUDED.atualizado_em""", (*l.values(), agora))


def padrao() -> Armazenamento:
    """JSON local quando `ACERVO_ARMAZENAMENTO_JSON` aponta um arquivo (desenvolvimento); senão o pgvector."""
    caminho = os.getenv("ACERVO_ARMAZENAMENTO_JSON", "").strip()
    if caminho:
        return Memoria(caminho)
    return Postgres()


def agora_utc() -> datetime:
    return datetime.now(UTC)
