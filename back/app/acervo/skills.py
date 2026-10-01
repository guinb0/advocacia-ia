"""Skills que citam regra superada ou alterada. SÓ LÊ as skills e gera alerta; nunca altera arquivo."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..caminhos import SKILLS
from ..juridico import autoridades as aut
from . import status as st
from .armazenamento import Armazenamento

_EXTENSOES = {".md", ".txt"}


def _arquivos(raiz: Path) -> list[Path]:
    return sorted(p for p in raiz.rglob("*") if p.is_file() and p.suffix.lower() in _EXTENSOES) if raiz.is_dir() else []


def registro(armazenamento: Armazenamento, chaves: set[str], *, agora: datetime) -> aut.Registro:
    """Autoridades importadas + versões (abertas e encerradas) dos artigos citados."""
    autoridades = aut.de_registro_bruto(armazenamento.autoridades())
    artigos = sorted({c.split(":", 2)[2] for c in chaves if c.startswith("art:")})
    versoes = [st.autoridade_de_versao(v, agora=agora) for v in armazenamento.artigos(artigos)] if artigos else []
    return aut.Registro([*autoridades, *versoes])


def chaves_alteradas(alterados: set[tuple[str, str]], normas: dict[str, str]) -> set[str]:
    """(document_id, dispositivo_id) → chave de citação `art:<norma>:<n>`. Mudança num inciso conta como mudança no artigo.

    Sem a norma, "art. 22" da Lei 8.213 casaria com o art. 22 de qualquer lei sincronizada.
    """
    chaves: set[str] = set()
    for document_id, dispositivo_id in alterados:
        norma = normas.get(document_id)
        artigo = dispositivo_id.split(".", 1)[0].split("~", 1)[0]
        if norma and artigo.startswith("art-"):
            chaves.add(f"art:{norma}:{artigo[4:]}")
    return chaves


def varrer(armazenamento: Armazenamento, *, alterados: set[tuple[str, str]] | None = None, raiz: Path | None = None,
           agora: datetime | None = None, normas: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """`alterados`: pares (document_id, dispositivo_id) que mudaram; `normas`: document_id → chave_norma do manifesto."""
    agora = agora or datetime.now(UTC)
    raiz = raiz or SKILLS
    citacoes: list[tuple[Path, aut.Citacao]] = []
    for arquivo in _arquivos(raiz):
        try:
            texto = arquivo.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        citacoes.extend((arquivo, c) for c in aut.extrair_citacoes(texto))
    if not citacoes:
        return []
    reg = registro(armazenamento, {c.chave for _, c in citacoes}, agora=agora)
    if normas is None:
        from .sincronizacao import manifesto
        normas = {i["id"]: i["chave_norma"] for i in manifesto() if i.get("chave_norma")}
    mudaram = chaves_alteradas(alterados or set(), normas)
    gerados: list[dict[str, Any]] = []
    vistos: set[tuple[str, str]] = set()
    for arquivo, c in citacoes:
        rel = str(arquivo.relative_to(raiz)) if arquivo.is_relative_to(raiz) else arquivo.name
        if (rel, c.chave) in vistos:
            continue
        vistos.add((rel, c.chave))
        r = reg.resolver(c, agora.date())
        alerta = None
        if r["status"] in (aut.SUPERADA, aut.FORA_DE_VIGENCIA):
            alerta = {"tipo": "SKILL_CITA_SUPERADA", "severidade": "alta",
                      "titulo": f"Skill {rel} cita {c.trecho} ({'superada' if r['status'] == aut.SUPERADA else 'fora de vigência'})",
                      "detalhe": r.get("motivo") or "", "authority_id": r.get("authority_id") or "",
                      "dados": {"skill": rel, "trecho": c.trecho, "chave": c.chave, "superado_por": r.get("superado_por") or ""}}
        elif c.tipo == "artigo" and r.get("authority_id"):
            disp = f"art-{c.chave.split(':', 2)[2]}"
            if c.chave in mudaram:
                alerta = {"tipo": "SKILL_CITA_ALTERADA", "severidade": "media",
                          "titulo": f"Skill {rel} cita {c.trecho}, cuja redação mudou nesta sincronização",
                          "detalhe": "Conferir se o argumento da skill continua de pé com o texto novo.", "dispositivo_id": disp,
                          "authority_id": rel, "dados": {"skill": rel, "trecho": c.trecho, "chave": c.chave}}
        if alerta:
            alerta["dispositivo_id"] = alerta.get("dispositivo_id") or rel
            if armazenamento.alertar(alerta, agora=agora):
                gerados.append(alerta)
    return gerados
