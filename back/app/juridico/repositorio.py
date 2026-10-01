"""Leitura da base jurídica verificada no PostgreSQL do RAG (somente SELECT).

- `autoridades_juridicas` (sql/010): súmulas, OJs, temas, controle concentrado e artigos curados, com
  vigência, status e "superado por".
- `normative_device_versions` + `corpus_manifest` (sql/006): versões de dispositivos com vigência.

Sem banco ou sem tabela, devolve lista vazia e o motivo — a geração segue, e o gate marca toda citação
como REQUIRES_LEGAL_RESEARCH em vez de aprovar de memória.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Iterable

from . import autoridades as aut

log = logging.getLogger(__name__)


def _consultar(sql: str, parametros: tuple[Any, ...]) -> list[dict[str, Any]]:
    from .. import rag
    return rag._consultar_pgvector(sql, parametros, connect_timeout=int(os.getenv("JURIDICO_CONNECT_TIMEOUT", "8")), tentativas_maximas=1)  # noqa: SLF001


def carregar_autoridades(organization_id: str = "") -> tuple[list[aut.Autoridade], str]:
    try:
        linhas = _consultar(
            "SELECT * FROM autoridades_juridicas WHERE organization_id IN ('', %s) LIMIT 20000", (organization_id,))
    except Exception as erro:  # noqa: BLE001
        log.warning("juridico: autoridades_juridicas indisponível: %s", erro)
        return [], f"autoridades_juridicas indisponível: {type(erro).__name__}"
    return aut.de_registro_bruto(linhas), ""


def carregar_dispositivos(chaves: Iterable[str]) -> tuple[list[aut.Autoridade], str]:
    """Versões de artigos citados (chaves `art:<norma>:<n>`), com a vigência de cada versão."""
    artigos = sorted({c.split(":", 2)[2] for c in chaves if c.startswith("art:")})
    if not artigos:
        return [], ""
    try:
        linhas = _consultar(
            """SELECT v.id, v.identifier, v.version, v.text, v.status, v.valid_from, v.valid_until, v.source_url,
                      v.retrieved_at, v.hierarchy, m.document_name, m.document_number, m.official_source
                 FROM normative_device_versions v JOIN corpus_manifest m ON m.document_id = v.document_id
                WHERE regexp_replace(lower(v.identifier), '[^0-9a-z-]', '', 'g') = ANY(%s)""",
            ([f"art{a}" for a in artigos] + artigos,))
    except Exception as erro:  # noqa: BLE001
        log.warning("juridico: normative_device_versions indisponível: %s", erro)
        return [], f"normative_device_versions indisponível: {type(erro).__name__}"
    saida = []
    for r in linhas:
        norma = aut.chave_da_norma(f"{r.get('document_name') or ''} {r.get('document_number') or ''}")
        artigo = aut._digitos(r.get("identifier")) or str(r.get("identifier") or "")  # noqa: SLF001
        hierarquia = r.get("hierarchy") or {}
        saida.append(aut.Autoridade(
            id=f"ndv:{r['id']}", tipo="artigo", chave=f"art:{norma}:{artigo.lower()}", titulo=f"art. {artigo} ({r.get('document_name') or norma})",
            texto=str(r.get("text") or ""), norma=norma, artigo=artigo,
            paragrafo=str(hierarquia.get("paragrafo") or ""), inciso=str(hierarquia.get("inciso") or ""),
            vigencia_inicio=str(r.get("valid_from") or ""), vigencia_fim=str(r.get("valid_until") or ""), versao=str(r.get("version") or ""),
            status=str(r.get("status") or "vigente"), fonte_oficial=str(r.get("official_source") or ""), url=str(r.get("source_url") or ""),
            verificado_em=str(r.get("retrieved_at") or ""), verificada=bool(r.get("valid_from")), origem="normative_device_versions",
        ))
    return saida, ""
