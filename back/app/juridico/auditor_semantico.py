"""SEMANTIC_CONTRADICTION: a peça não pode afirmar duas coisas opostas sobre o mesmo fato.

Camada 1 — determinística, sempre roda:
- famílias genéricas de pares opostos em `dados/contradicoes_semanticas.json` (trajeto × serviço,
  definitiva × perícia, férias gozadas × vencidas, vínculo ativo × extinto, vínculo ativo × verba
  rescisória); a frase com argumento
  subsidiário, negação ou alegação da ré não conta;
- base salarial: o salário escrito no texto e a base usada nos cálculos têm de ser a do dado canônico;
- indício × prova: o mesmo documento descrito como indício num ponto e como prova cabal em outro.

Camada 2 — LLM (opcional): aponta contradições com DOIS trechos literais; o achado só vale se os dois
trechos existirem na peça, forem diferentes e tiverem tamanho mínimo. Se a camada foi pedida e falhou, o
gate não passa (não há queda silenciosa).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from . import calculos as calc
from . import canonico
from .auditores import BLOQUEIA, _achado, _reais_do_texto, _texto
from .autoridades import norm

AUDITOR = "SEMANTIC_CONTRADICTION"
ARQUIVO_FAMILIAS = Path(__file__).resolve().parent / "dados" / "contradicoes_semanticas.json"
_NEGACAO = re.compile(r"\bn[ãa]o\b|\bnunca\b|\bjamais\b|\bsem\b", re.I)
_DOC = re.compile(r"\b(?:Doc(?:umento)?\.?\s*(?:n[ºo°.]?\s*)?\d{1,3})\b", re.I)
_INDICIO = re.compile(r"ind[íi]cio|indica|sugere|aponta\s+para|sinaliza", re.I)
_PROVA_CABAL = re.compile(r"comprova(?:m)?\b|prova\s+cabal|demonstra\s+(?:de\s+forma\s+)?inequ[íi]voc|n[ãa]o\s+deixa\s+d[úu]vida|cabalmente", re.I)
_SALARIO = re.compile(r"sal[áa]rio|remunera[çc][ãa]o|percebia|recebia\s+mensalmente", re.I)
TAMANHO_MINIMO_TRECHO = 15


@lru_cache(maxsize=1)
def familias() -> dict[str, Any]:
    with ARQUIVO_FAMILIAS.open(encoding="utf-8") as f:
        dados = json.load(f)
    comp = lambda lista: [re.compile(p, re.I) for p in lista or []]  # noqa: E731
    return {
        "ressalvas": comp(dados.get("ressalvas_da_frase")),
        "familias": [{**fam, "polo_a": comp(fam.get("polo_a")), "polo_b": comp(fam.get("polo_b")),
                      "exceto_se_presente": comp(fam.get("exceto_se_presente"))} for fam in dados.get("familias") or []],
    }


def _frases(secoes: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(str(s.get("code") or ""), f.strip()) for s in secoes for f in re.split(r"(?<=[.;!?])\s+|\n+", _texto(s)) if f.strip()]


def _afirma(frase: str, padroes: list[re.Pattern[str]], ressalvas: list[re.Pattern[str]]) -> bool:
    if any(r.search(frase) for r in ressalvas):
        return False
    for p in padroes:
        m = p.search(frase)
        if m and not _NEGACAO.search(frase[max(0, m.start() - 18):m.start()]):
            return True
    return False


def _familias(frases: list[tuple[str, str]]) -> list[dict[str, Any]]:
    cfg = familias()
    achados = []
    corpo = " ".join(f for _, f in frases)
    for fam in cfg["familias"]:
        if any(p.search(corpo) for p in fam["exceto_se_presente"]):
            continue
        a = [(c, f) for c, f in frases if _afirma(f, fam["polo_a"], cfg["ressalvas"])]
        b = [(c, f) for c, f in frases if _afirma(f, fam["polo_b"], cfg["ressalvas"])]
        if a and b:
            achados.append(_achado(AUDITOR, f"CONTRADICAO_{fam['id'].upper()}", BLOQUEIA, a[0][0], f"«{a[0][1][:100]}» × «{b[0][1][:100]}»",
                                   f"{fam['descricao']}: {fam.get('rotulo_a', 'polo A')} ({a[0][0]}) × {fam.get('rotulo_b', 'polo B')} ({b[0][0]})"))
    return achados


def _base_salarial(frases: list[tuple[str, str]], canon: dict[str, Any] | None, calculos: list[dict[str, Any]],
                   matriz: dict[str, Any] | None) -> list[dict[str, Any]]:
    bases = {round(float(v), 2) for v in (canonico.valor(canon, "current_salary"), canonico.valor(canon, "compensation_base")) if v}
    if not bases:
        return []
    historico = set(bases)
    for f in (matriz or {}).get("fatos") or []:
        if re.search(r"salari|remunera", str(f.get("chave") or "")) and canonico.certeza_do_fato(f) in canonico.UTILIZAVEIS:
            v = calc.valor_numerico(f.get("valor"))
            if v is not None:
                historico.add(round(float(v), 2))
    achados = []
    for c in calculos or []:
        for nome in ("salario", "base_mensal"):
            v = calc.valor_numerico(((c.get("parametros") or {}).get(nome)))
            if v is not None and round(float(v), 2) not in historico:
                achados.append(_achado(AUDITOR, "BASE_SALARIAL_DIVERGENTE", BLOQUEIA, "", f"{c.get('calculation_id') or c.get('rubrica')}: {nome} = {calc.brl(v)}",
                                       "o cálculo usa base diferente do salário/remuneração canônicos: " + ", ".join(calc.brl(b) for b in sorted(bases))))
    for code, frase in frases:
        if code in ("CLAIMS", "VALUE") or not _SALARIO.search(frase):
            continue
        perto = [v for v in _reais_do_texto(frase)]
        if len(perto) == 1 and perto[0] not in historico and not re.search(r"piso|m[íi]nimo|diferen[çc]a|deveria|correto|equipara", frase, re.I):
            achados.append(_achado(AUDITOR, "BASE_SALARIAL_DIVERGENTE", BLOQUEIA, code, frase[:220],
                                   "salário escrito diferente do canônico: " + ", ".join(calc.brl(b) for b in sorted(bases))))
    return achados


def _indicio_x_prova(frases: list[tuple[str, str]]) -> list[dict[str, Any]]:
    por_doc: dict[str, dict[str, tuple[str, str]]] = {}
    for code, frase in frases:
        for m in _DOC.finditer(frase):
            doc = re.sub(r"\D", "", m.group(0))
            if _INDICIO.search(frase):
                por_doc.setdefault(doc, {}).setdefault("indicio", (code, frase))
            if _PROVA_CABAL.search(frase):
                por_doc.setdefault(doc, {}).setdefault("prova", (code, frase))
    return [_achado(AUDITOR, "INDICIO_E_PROVA_CABAL", BLOQUEIA, v["indicio"][0], f"«{v['indicio'][1][:100]}» × «{v['prova'][1][:100]}»",
                    f"o documento {doc} é tratado como indício e como prova cabal")
            for doc, v in por_doc.items() if "indicio" in v and "prova" in v and v["indicio"][1] != v["prova"][1]]


_INSTRUCAO_LLM = """Você revisa uma petição trabalhista procurando CONTRADIÇÕES INTERNAS: dois trechos da MESMA peça que
afirmam coisas incompatíveis sobre o mesmo fato (datas, dinâmica do evento, quem fez o quê, natureza do vínculo,
extensão de dano, valores). Argumento subsidiário («ainda que», «caso se entenda») não é contradição.
Devolva JSON: {"contradicoes":[{"tipo":"curto","trecho_a":"cópia LITERAL da peça","trecho_b":"cópia LITERAL da peça","explicacao":"por que são incompatíveis"}]}
Copie os trechos exatamente como estão (sem reescrever). Sem contradição: {"contradicoes":[]}."""


def _compacto(t: str) -> str:
    return " ".join(str(t or "").split())


def _llm(secoes: list[dict[str, Any]], llm: Callable[[str, str], dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    corpo = "\n\n".join(f"[{s.get('code')}]\n{_texto(s)}" for s in secoes)
    saida = llm(_INSTRUCAO_LLM, corpo[:90_000]) or {}
    texto = _compacto(corpo)
    achados, descartadas = [], 0
    for c in saida.get("contradicoes") or []:
        if not isinstance(c, dict):
            continue
        a, b = _compacto(c.get("trecho_a")), _compacto(c.get("trecho_b"))
        if len(a) < TAMANHO_MINIMO_TRECHO or len(b) < TAMANHO_MINIMO_TRECHO or norm(a) == norm(b) or a not in texto or b not in texto:
            descartadas += 1
            continue
        achados.append(_achado(AUDITOR, "CONTRADICAO_SEMANTICA", BLOQUEIA, "", f"«{a[:100]}» × «{b[:100]}»",
                               f"{str(c.get('tipo') or '').strip()}: {str(c.get('explicacao') or '').strip()}"))
    return achados, {"propostas": len(saida.get("contradicoes") or []), "confirmadas": len(achados), "descartadas_sem_trecho_literal": descartadas}


def auditar(secoes: list[dict[str, Any]], *, canon: dict[str, Any] | None = None, calculos: list[dict[str, Any]] | None = None,
            matriz: dict[str, Any] | None = None, llm: Callable[[str, str], dict[str, Any]] | None = None) -> dict[str, Any]:
    frases = _frases(secoes)
    achados = [*_familias(frases), *_base_salarial(frases, canon, calculos or [], matriz), *_indicio_x_prova(frases)]
    rel: dict[str, Any] = {"camada_llm": "não pedida"}
    if llm is not None:
        try:
            extra, rel["camada_llm"] = _llm(secoes, llm)
            achados += extra
        except Exception as erro:  # noqa: BLE001 - vira achado que bloqueia: o gate não pode passar sem rodar
            rel["camada_llm"] = {"erro": f"{type(erro).__name__}: {str(erro)[:200]}"}
            achados.append(_achado(AUDITOR, "VERIFICACAO_SEMANTICA_NAO_EXECUTADA", BLOQUEIA, "", "", f"camada LLM falhou: {type(erro).__name__}"))
    return {"auditor": AUDITOR, "achados": achados, "relatorio": rel}
