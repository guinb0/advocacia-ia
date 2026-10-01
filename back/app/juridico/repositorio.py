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


#: Identificador antigo do ingestor ("art-482-310", "art-482-A-310", "art-1º-1") → número do artigo ("482", "482-a", "1").
_ARTIGO_DO_IDENTIFICADOR_ANTIGO = (
    r"lower(regexp_replace(regexp_replace(v.identifier, '^art-([0-9.]+)\s*[ºo°]?(-[A-Za-z]{1,2})?-[0-9]+$', '\1\2'), '\.', '', 'g'))"
)


def carregar_dispositivos(chaves: Iterable[str]) -> tuple[list[aut.Autoridade], str]:
    """Versões de ARTIGOS citados (chaves `art:<norma>:<n>`), com a vigência de cada versão.

    Com a migration 011, lê as colunas do Acervo (artigo, chave da norma, última verificação). Sem ela,
    cai na leitura antiga, agora casando o identificador posicional pelo número do artigo.
    O status vira `Autoridade.status` pelo mesmo mapeamento do painel (`acervo.status`).
    """
    from ..acervo import status as acervo_status
    from ..acervo.armazenamento import Memoria, Postgres

    artigos = sorted({c.split(":", 2)[2] for c in chaves if c.startswith("art:")})
    if not artigos:
        return [], ""
    timeout = int(os.getenv("JURIDICO_CONNECT_TIMEOUT", "8"))
    local = os.getenv("ACERVO_ARMAZENAMENTO_JSON", "").strip()
    try:
        linhas = (Memoria(local) if local else Postgres(connect_timeout=timeout)).artigos(artigos)
    except Exception as erro_novo:  # noqa: BLE001
        log.info("juridico: leitura do Acervo (011) indisponível, usando a antiga: %s", type(erro_novo).__name__)
        try:
            linhas = _consultar(
                f"""SELECT v.id, v.identifier, v.version, v.text, v.status, v.valid_from, v.valid_until, v.source_url,
                           v.retrieved_at, v.hierarchy, m.document_name, m.document_number, m.official_source
                      FROM normative_device_versions v JOIN corpus_manifest m ON m.document_id = v.document_id
                     WHERE {_ARTIGO_DO_IDENTIFICADOR_ANTIGO} = ANY(%s)""",
                ([a.lower() for a in artigos],))
        except Exception as erro:  # noqa: BLE001
            log.warning("juridico: normative_device_versions indisponível: %s", erro)
            return [], f"normative_device_versions indisponível: {type(erro).__name__}"
    return [acervo_status.autoridade_de_versao(r) for r in linhas], ""
