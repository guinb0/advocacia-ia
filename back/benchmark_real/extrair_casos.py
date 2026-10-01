"""Extrai do SQL Server de PRODUÇÃO, SÓ LEITURA, os pares (versão gerada pelo sistema × versão aprovada pelo advogado)
e grava cada caso ANONIMIZADO em `back/benchmark_real/casos/` (pasta no .gitignore — nunca vai ao repositório).

    cd back
    $env:SQLSERVER_HOST=...; $env:SQLSERVER_PASSWORD=...   # só no processo, nunca em arquivo
    python -m benchmark_real.extrair_casos [--limite 30]

Garantias:
- conexão com `ApplicationIntent=ReadOnly` e `autocommit`; cada comando passa por `_somente_select` (recusa o que não
  for SELECT) e usa `WITH (NOLOCK)` para não segurar lock de tabela que o escritório está usando;
- nenhuma credencial é lida de arquivo do benchmark nem gravada; a saída não tem nome, CPF, CNPJ, RG, e-mail,
  telefone, CEP, número de processo nem id de caso (o id vira hash).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

PASTA = Path(__file__).resolve().parent / "casos"
APROVADA = "APPROVED"

_SQL_APROVADAS = """
SELECT p.caso_id, p.versao, p.status, p.dados_json, p.atualizado_em, c.categoria, c.cliente
  FROM dbo.acervo_peticoes_locais p WITH (NOLOCK)
  JOIN dbo.acervo_casos c WITH (NOLOCK) ON c.id = p.caso_id
 WHERE p.status = ? OR p.dados_json LIKE '%"protocolo": {%'
 ORDER BY p.atualizado_em DESC
"""
_SQL_VERSOES = """
SELECT versao, status, dados_json, criado_em
  FROM dbo.acervo_peticao_versoes WITH (NOLOCK)
 WHERE caso_id = ?
 ORDER BY versao ASC
"""


def _somente_select(sql: str) -> str:
    limpo = re.sub(r"--[^\n]*", "", sql).strip()
    if not re.match(r"(?is)^select\b", limpo) or re.search(r"(?i)\b(insert|update|delete|merge|drop|alter|create|exec|truncate|grant)\b", limpo):
        raise RuntimeError("o extrator só executa SELECT")
    return sql


def _conectar() -> Any:
    import pyodbc  # noqa: PLC0415 - só quem extrai precisa do driver

    from app.banco import dsn  # noqa: PLC0415

    return pyodbc.connect(dsn() + "ApplicationIntent=ReadOnly;", autocommit=True, timeout=20)


def _consultar(con: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cur = con.cursor()
    cur.execute(_somente_select(sql), params)
    colunas = [c[0] for c in cur.description]
    return [dict(zip(colunas, linha)) for linha in cur.fetchall()]


# ------------------------------------------------------------------ anonimização

_PADROES = [
    (re.compile(r"\b\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}\b"), "[PROCESSO]"),
    (re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"), "[CNPJ]"),
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "[CPF]"),
    (re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-?[\dxX]\b"), "[RG]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
    (re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b"), "[TELEFONE]"),
    (re.compile(r"\b\d{5}-?\d{3}\b"), "[CEP]"),
    (re.compile(r"\b(PIS|PASEP|NIT|CTPS)\s*(n[ºo°.]*\s*)?[\d./-]{6,}", re.I), r"\1 [NUMERO]"),
]


def _nomes(dados: dict[str, Any], cliente: str) -> list[str]:
    """Nomes próprios a apagar: cliente, partes do plano e qualificação do case brief (3+ letras, mais longos primeiro)."""
    achados = {cliente}
    for versao in (dados, *(dados.get("_versoes") or [])):
        pipe = ((versao.get("trace") or {}).get("pipeline") or {})
        partes = ((pipe.get("plano_estruturado") or {}).get("partes") or {})
        for lado in partes.values():
            if isinstance(lado, dict):
                achados |= {str(v) for k, v in lado.items() if k in ("nome", "razao_social", "nome_fantasia", "representante") and v}
        brief = ((versao.get("trace") or {}).get("case_brief") or {})
        for p in brief.get("parties") or brief.get("partes") or []:
            if isinstance(p, dict) and p.get("nome"):
                achados.add(str(p["nome"]))
    nomes = set()
    for n in achados:
        n = " ".join(str(n or "").split())
        if len(n) >= 3:
            nomes.add(n)
            nomes |= {parte for parte in n.split() if len(parte) >= 4 and parte[0].isupper()}
    return sorted(nomes, key=len, reverse=True)


def anonimizar(valor: Any, nomes: list[str]) -> Any:
    if isinstance(valor, str):
        texto = valor
        for n in nomes:
            texto = re.sub(rf"(?i)\b{re.escape(n)}\b", "[NOME]", texto)
        for padrao, troca in _PADROES:
            texto = padrao.sub(troca, texto)
        return texto
    if isinstance(valor, list):
        return [anonimizar(v, nomes) for v in valor]
    if isinstance(valor, dict):
        return {k: anonimizar(v, nomes) for k, v in valor.items() if k not in ("_docx", "protocolo", "generation_id")}
    return valor


# ------------------------------------------------------------------ montagem do caso

def _secoes(dados: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"code": s.get("code"), "label": s.get("label"), "content": s.get("content") or ""} for s in dados.get("sections") or []]


def _gerada(versoes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A primeira versão produzida pelo sistema: edição manual e revisão por prompt arquivam a anterior em
    `peticao_versoes` antes de sobrescrever, então a mais antiga com `trace.pipeline` é a que saiu da geração.
    Sem versão arquivada a peça foi aprovada como gerada — não há diferença a medir."""
    for v in versoes:
        if (v.get("trace") or {}).get("pipeline"):
            return v
    return None


def montar_caso(linha: dict[str, Any], versoes_brutas: list[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        aprovada = json.loads(linha["dados_json"])
        versoes = [json.loads(v["dados_json"]) for v in versoes_brutas]
    except (TypeError, json.JSONDecodeError):
        return None
    gerada = _gerada(versoes)
    if gerada is None:
        return None
    pipe = (gerada.get("trace") or {}).get("pipeline") or {}
    nomes = _nomes({**aprovada, "_versoes": versoes}, str(linha.get("cliente") or ""))
    caso = {
        "id": hashlib.sha256(str(linha["caso_id"]).encode()).hexdigest()[:16],
        "categoria": linha.get("categoria") or "",
        "versoes_intermediarias": max(0, len(versoes) - 1),
        "gerada": {"secoes": _secoes(gerada), "modelo": gerada.get("model"), "pendencias": (gerada.get("relatorio_advogado") or {}).get("pendencias") or [],
                   "plano_estruturado": pipe.get("plano_estruturado"), "case_brief": (gerada.get("trace") or {}).get("case_brief"),
                   "outline": (gerada.get("trace") or {}).get("outline"), "juridico": pipe.get("juridico")},
        "aprovada": {"secoes": _secoes(aprovada)},
    }
    return anonimizar(caso, nomes)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=30)
    args = ap.parse_args()
    PASTA.mkdir(parents=True, exist_ok=True)
    con = _conectar()
    try:
        aprovadas = _consultar(con, _SQL_APROVADAS, (APROVADA,))[: args.limite * 3]
        gravados = 0
        for linha in aprovadas:
            caso = montar_caso(linha, _consultar(con, _SQL_VERSOES, (linha["caso_id"],)))
            if caso is None:
                continue
            (PASTA / f"{caso['id']}.json").write_text(json.dumps(caso, ensure_ascii=False, indent=1), encoding="utf-8")
            gravados += 1
            if gravados >= args.limite:
                break
    finally:
        con.close()
    print(f"{gravados} caso(s) anonimizados em {PASTA} (de {len(aprovadas)} petições aprovadas lidas)")
    return 0 if gravados else 1


if __name__ == "__main__":
    sys.exit(main())
