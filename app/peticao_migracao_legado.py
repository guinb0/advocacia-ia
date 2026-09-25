"""Migração de peças LEGADAS para o formato estruturado atual — camada isolada.

    documento antigo -> migrar (aqui) -> formato novo -> renderer genérico

O renderer (`peticao_local.montar_docx`) é determinístico e NÃO adivinha nada: título só
existe se o texto traz `#`, bloco só existe se traz `::: nome`. Peças gravadas antes da
skill virar a autoridade única não trazem essa marcação; os títulos delas eram
reconhecidos por heurística (romano, caixa alta, "Ao Juízo…"). Essa heurística mora SÓ
aqui, e só roda sobre documento sem a marca `formato == 2`. Documento novo nunca passa por
ela. Se as heurísticas de peça antiga forem um dia dispensáveis, apaga-se este arquivo.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

#: Versão do formato estruturado: `#`, `>` e `::: nome`. Toda seção nova carrega esta marca.
FORMATO_ATUAL = 2

_TITULO_ROMANO = re.compile(r"^[IVXLC]+\s*[–—-]\s*\S")
_SUBTITULO_NUMERADO = re.compile(r"^[IVXLC]+\.\d+\s*[–—-]\s*\S")
_ENDERECAMENTO = re.compile(r"^(ao|à|a)\s+(ju[íi]zo|exmo|excelent[íi]ssim)", re.IGNORECASE)
_TEM_MARCACAO = re.compile(r"^\s*(#{1,6}\s|:::)", re.MULTILINE)


def _titulo_curto(linha: str) -> bool:
    return bool(linha) and len(linha) <= 90 and not linha.endswith(".")


def _migrar_conteudo(conteudo: str) -> str:
    saida: list[str] = []
    for bruta in conteudo.split("\n"):
        linha = bruta.strip().replace("**", "")
        if not _titulo_curto(linha) or bruta.lstrip().startswith((">", "|", "[[")):
            saida.append(bruta)
        elif _SUBTITULO_NUMERADO.match(linha):
            saida.append(f"## {linha}")
        elif _TITULO_ROMANO.match(linha):
            saida.append(f"# {linha}")
        elif _ENDERECAMENTO.match(linha):
            saida.extend(["::: enderecamento", linha, ":::"])
        elif not any(c.islower() for c in linha) and any(c.isalpha() for c in linha):
            saida.append(f"# {linha}")
        else:
            saida.append(bruta)
    return "\n".join(saida)


def migrar_secoes(secoes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Devolve as seções no formato atual; as que já estão nele passam intactas."""
    resultado: list[dict[str, Any]] = []
    migradas = 0
    for secao in secoes:
        conteudo = str(secao.get("content") or "")
        if secao.get("formato") == FORMATO_ATUAL or _TEM_MARCACAO.search(conteudo):
            resultado.append(secao)
            continue
        migradas += 1
        resultado.append({**secao, "content": _migrar_conteudo(conteudo), "formato": FORMATO_ATUAL})
    if migradas:
        log.info("peticao: %d seção(ões) legada(s) migrada(s) para o formato estruturado", migradas)
    return resultado
