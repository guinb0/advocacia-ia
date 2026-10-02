"""FACT MATRIX (camada A): todo fato do caso com valor, fonte, documento, página, confiança e estado.

Estado de um fato:
- confirmado: o valor está no texto de um DOCUMENTO do caso;
- alegado: só a entrevista (ou o cadastro) o afirma;
- inferido: nenhuma fonte o traz literalmente (proposta do modelo) — nunca é apresentado como verdade.

Contradição: a mesma chave (ex.: `contrato.salario`) com valores diferentes em fontes diferentes. A
matriz não escolhe: registra as versões, e a resolução vem da regra de peso de `case_facts` ou do humano.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from .autoridades import norm

CONFIRMADO, ALEGADO, INFERIDO = "confirmado", "alegado", "inferido"
_TIPOS_DOCUMENTO = {"documento", "analise_documental", "manual"}

_REAIS = re.compile(r"R\$\s*([\d.]+,\d{2}|[\d.]+)")
_DATA = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
_HORA = re.compile(r"\b(\d{1,2})\s*(?:h|:)\s*(\d{2})?\b")
_PAGINA = re.compile(r"(?:---\s*)?(?:p[aá]gina|p[aá]g\.?|page|fls?\.?)\s*(\d{1,4})", re.I)
_EVENTOS = (
    ("BENEFIT_START", re.compile(r"\b(?:benef[ií]cio|aux[ií]lio|NB\b|DIB\b|INSS)" , re.I)),
    ("SURGERY", re.compile(r"\b(?:cirurgia|cir[uú]rgic)" , re.I)),
    ("EXPERT_EXAM", re.compile(r"\b(?:per[ií]cia|pericial)" , re.I)),
    ("ACCIDENT", re.compile(r"\b(?:acidente|assalto|queda|sinistro)" , re.I)),
    ("ADMISSION", re.compile(r"\b(?:admiss[aã]o|admitid)" , re.I)),
    ("DISMISSAL", re.compile(r"\b(?:dispensa|rescis[aã]o|demiss[aã]o)" , re.I)),
)


def tipo_de_evento(texto: str) -> str:
    for tipo, padrao in _EVENTOS:
        if padrao.search(texto or ""):
            return tipo
    return ""


def reais(texto: str) -> float | None:
    m = _REAIS.search(str(texto or ""))
    if not m:
        return None
    bruto = m[1]
    return float(bruto.replace(".", "").replace(",", ".")) if "," in bruto else float(bruto.replace(".", ""))


def valor_canonico(valor: Any) -> str:
    """Forma comparável: dinheiro em centavos, data ISO, hora em minutos, texto normalizado."""
    s = str(valor if valor is not None else "").strip()
    if not s:
        return ""
    v = reais(s) if "R$" in s else None
    if v is None and re.fullmatch(r"[\d.]+,\d{2}", s):
        v = float(s.replace(".", "").replace(",", "."))
    if v is not None:
        return f"R${round(v * 100):d}"
    m = _DATA.search(s)
    if m:
        return f"{m[3]}-{m[2]}-{m[1]}"
    m = _HORA.fullmatch(s)
    if m:
        return f"{int(m[1]) * 60 + int(m[2] or 0)}min"
    try:
        return f"n{float(s.replace(',', '.')):g}"
    except ValueError:
        return norm(s)


def _variantes(valor: str) -> list[str]:
    """Formas em que o valor pode estar escrito no documento."""
    s = str(valor or "").strip()
    out = {s}
    v = reais(s) if "R$" in s else None
    if v is None and re.fullmatch(r"[\d.]+(,\d{2})?", s):
        try:
            v = float(s.replace(".", "").replace(",", ".")) if "," in s else None
        except ValueError:
            v = None
    if v is not None:
        inteiro, cent = f"{v:.2f}".split(".")
        com_ponto = f"{int(inteiro):,}".replace(",", ".")
        out |= {f"{com_ponto},{cent}", f"{inteiro},{cent}"}
    m = _DATA.search(s)
    if m:
        out |= {f"{m[1]}/{m[2]}/{m[3]}", f"{m[1]}.{m[2]}.{m[3]}", f"{m[3]}-{m[2]}-{m[1]}"}
    return [x for x in out if x]


def localizar(valor: str, texto: str) -> tuple[bool, str]:
    """(consta?, página) — página quando o OCR preservou o marcador de página antes da ocorrência."""
    alvo_bruto = str(texto or "")
    for v in _variantes(valor):
        i = alvo_bruto.find(v)
        if i < 0:
            i = norm(alvo_bruto).find(norm(v)) if len(norm(v)) >= 4 else -1
        if i >= 0:
            paginas = list(_PAGINA.finditer(alvo_bruto[:i]))
            return True, paginas[-1][1] if paginas else ""
    return False, ""


def montar(
    plano_est: dict[str, Any] | None, *, case_facts: dict[str, Any] | None = None,
    fatos_extraidos: Iterable[dict[str, Any]] | None = None, fontes: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Matriz a partir do PETITION_PLAN, das partes resolvidas (CASE_FACTS) e dos fatos chaveados do issue spotting.

    `fontes` = [{tipo, nome, texto}] do caso; é contra o TEXTO delas que um valor proposto vira confirmado.
    """
    fontes = [f for f in (fontes or []) if isinstance(f, dict)]
    por_nome = {str(f.get("nome") or ""): f for f in fontes}
    docs = [f for f in fontes if f.get("tipo") in _TIPOS_DOCUMENTO]
    fatos: list[dict[str, Any]] = []

    def novo(**campos: Any) -> dict[str, Any]:
        f = {"id": f"M{len(fatos) + 1:03d}", "event_id": "", "event_type": "", "subject": "", "fato": "", "chave": "", "valor": "", "fonte": "", "documento": "",
             "pagina": "", "confianca": "baixa", "estado": INFERIDO, "contradicoes": [], "origem": "", "ref": ""}
        f.update(campos)
        f["event_id"] = str(f.get("event_id") or f["id"])
        f["event_type"] = str(f.get("event_type") or tipo_de_evento(str(f.get("fato") or "")))
        f["subject"] = str(f.get("subject") or f.get("chave") or f.get("fato") or "")[:160]
        fatos.append(f)
        return f

    for f in (plano_est or {}).get("fatos") or []:
        if not isinstance(f, dict) or not f.get("fato"):
            continue
        documentos = [d for d in f.get("documentos") or [] if d]
        fonte = str(f.get("fonte") or "")
        if documentos:
            estado, conf = CONFIRMADO, "alta"
        elif fonte:
            estado, conf = (ALEGADO, "media") if "entrevista" in norm(fonte) or fonte not in por_nome else (CONFIRMADO, "media")
        else:
            estado, conf = INFERIDO, "baixa"
        novo(fato=str(f["fato"]), data=str(f.get("data") or ""), fonte=fonte, documento=", ".join(documentos),
             confianca=conf, estado=estado, origem="plano", ref=str(f.get("id") or ""), citacao=str(f.get("citacao") or ""))

    for papel, campos in ((case_facts or {}).get("PARTIES") or {}).items():
        for campo, e in (campos or {}).items():
            if not isinstance(e, dict):
                continue
            fontes_e = list(e.get("fontes") or [])
            documental = any(por_nome.get(x, {}).get("tipo") in _TIPOS_DOCUMENTO for x in fontes_e)
            if e.get("valor"):
                novo(fato=f"{papel}.{campo}", chave=f"{papel}.{campo}", valor=str(e["valor"]), fonte=", ".join(fontes_e),
                     documento=", ".join(x for x in fontes_e if por_nome.get(x, {}).get("tipo") in _TIPOS_DOCUMENTO),
                     confianca=str(e.get("confianca") or "media"), estado=CONFIRMADO if documental else ALEGADO, origem="case_facts")
            for alt in e.get("alternativas") or []:
                novo(fato=f"{papel}.{campo}", chave=f"{papel}.{campo}", valor=str(alt.get("valor") or ""),
                     fonte=", ".join(alt.get("fontes") or []), confianca="baixa", estado=ALEGADO, origem="case_facts_alternativa")

    for x in fatos_extraidos or []:
        if not isinstance(x, dict) or not str(x.get("chave") or "").strip() or x.get("valor") in (None, ""):
            continue
        valor, fonte = str(x["valor"]).strip(), str(x.get("fonte") or "").strip()
        alvo = por_nome.get(fonte)
        candidatos = [alvo] if alvo else (docs + [f for f in fontes if f.get("tipo") == "entrevista"])
        consta, pagina, onde = False, "", None
        for f in candidatos:
            consta, pagina = localizar(valor, str(f.get("texto") or ""))
            if consta:
                onde = f
                break
        if onde is None:
            estado, conf = INFERIDO, "baixa"
        elif onde.get("tipo") in _TIPOS_DOCUMENTO:
            estado, conf = CONFIRMADO, "alta"
        else:
            estado, conf = ALEGADO, "media"
        novo(fato=str(x.get("fato") or x["chave"]), chave=str(x["chave"]).strip().lower(), valor=valor,
             fonte=str((onde or {}).get("nome") or fonte), documento=str((onde or {}).get("nome") or "") if estado == CONFIRMADO else "",
             pagina=str(x.get("pagina") or pagina or ""), confianca=conf, estado=estado, origem="issue_spotting",
             ref=str(x.get("id") or ""), categoria=str(x.get("categoria") or ""),
             certeza_declarada=str(x.get("certeza") or "").strip().upper())

    contradicoes = detectar_contradicoes(fatos, case_facts)
    for c in contradicoes:
        for i in c["fatos"]:
            for f in fatos:
                if f["id"] == i:
                    f["contradicoes"].append(c["id"])
    return {"fatos": fatos, "contradicoes": contradicoes, "resumo": {
        e: sum(1 for f in fatos if f["estado"] == e) for e in (CONFIRMADO, ALEGADO, INFERIDO)}}


def detectar_contradicoes(fatos: list[dict[str, Any]], case_facts: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Mesma chave, valores diferentes, fontes diferentes. Inclui os conflitos que CASE_FACTS já tinha visto."""
    grupos: dict[str, list[dict[str, Any]]] = {}
    for f in fatos:
        if f.get("chave") and f.get("valor"):
            grupos.setdefault(f["chave"], []).append(f)
    saida: list[dict[str, Any]] = []
    for chave, lista in grupos.items():
        valores: dict[str, list[dict[str, Any]]] = {}
        for f in lista:
            valores.setdefault(valor_canonico(f["valor"]), []).append(f)
        if len(valores) < 2:
            continue
        fontes = {f["fonte"] for f in lista}
        if len(fontes) < 2 and all(f["origem"] != "case_facts_alternativa" for f in lista):
            continue
        saida.append({
            "id": f"X{len(saida) + 1:02d}", "chave": chave, "fatos": [f["id"] for f in lista],
            "versoes": [{"valor": v[0]["valor"], "fontes": sorted({f["fonte"] for f in v}), "estado": v[0]["estado"]} for v in valores.values()],
            "resolvida": False,
        })
    vistos = {c["chave"] for c in saida}
    for u in (case_facts or {}).get("UNCERTAINTIES") or []:
        if isinstance(u, dict) and u.get("tipo") == "conflito" and u.get("campo") not in vistos:
            saida.append({"id": f"X{len(saida) + 1:02d}", "chave": u["campo"], "fatos": [], "versoes": [{"detalhe": u.get("detalhe", "")}], "resolvida": False})
    return saida


def por_chave(matriz: dict[str, Any], chave: str) -> dict[str, Any] | None:
    """O fato de uma chave que pode ser usado: confirmado vence alegado; inferido e contraditório não servem."""
    lista = [f for f in matriz.get("fatos") or [] if f.get("chave") == chave and f.get("estado") != INFERIDO and not f.get("contradicoes")]
    lista.sort(key=lambda f: (f["estado"] == CONFIRMADO, f["confianca"] == "alta"), reverse=True)
    return lista[0] if lista else None


def para_prompt(matriz: dict[str, Any], *, limite: int = 220) -> str:
    linhas = ["=== MATRIZ DE FATOS (id | estado | fato/chave = valor | fonte | doc | pág) ==="]
    for f in (matriz.get("fatos") or [])[:limite]:
        corpo = f"{f['chave']} = {f['valor']}" if f.get("chave") else f["fato"]
        marca = " | CONTRADITÓRIO" if f.get("contradicoes") else ""
        linhas.append(f"- {f['id']} | {f['estado']} | {corpo[:260]} | {f.get('fonte') or '-'} | {f.get('documento') or '-'} | {f.get('pagina') or '-'}{marca}")
    for c in matriz.get("contradicoes") or []:
        linhas.append(f"CONTRADIÇÃO {c['id']} ({c['chave']}): " + " × ".join(
            f"«{v.get('valor', v.get('detalhe', ''))}» ({', '.join(v.get('fontes') or [])})" for v in c["versoes"]))
    linhas.append("Fato «alegado» se escreve como alegação do autor; «inferido» não é afirmado; contraditório não é usado sem resolução.")
    return "\n".join(linhas)
