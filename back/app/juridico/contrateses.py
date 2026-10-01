"""CONTRATESES obrigatórias e COUNTERARGUMENT_AUDITOR.

Antes da redação: até 3 defesas plausíveis da reclamada por tese relevante, em UMA chamada em lote (JSON validado:
tese e requisito têm de existir no grafo, fato tem de existir na matriz). Semente: `dados/defesas_tipicas.json`
pelo instituto da tese; sem modelo (ou se ele falhar), a semente é usada como está.

Cada defesa é cruzada com a matriz de prova: `tem_prova` quando o requisito atacado tem prova forte/média ou há fato
utilizável que a enfrente. Defesa sem prova que a enfrente vira «capítulo vulnerável» e orientação dirigida ao
capítulo da tese (fortalecer o requisito com a prova X) — nunca argumentação defensiva no texto.

Depois da redação, o auditor confere, por defesa, se a peça já a enfrenta: entailment em lote exigindo trecho LITERAL
da peça (o código confere que o trecho existe; sem trecho, não respondida). Sem modelo, avaliação léxica.
Achados são WARNING: não retêm a peça, entram nas pendências e no admin.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from . import prova as pv
from .auditores import ALERTA, _achado, _texto
from .autoridades import norm
from .fatos import CONFIRMADO
from .raciocinio import tokens, usavel

AUDITOR = "COUNTERARGUMENT"
ARQUIVO_DEFESAS = Path(__file__).resolve().parent / "dados" / "defesas_tipicas.json"
MAX_POR_TESE = 3
FORCAS = ("alta", "media", "baixa")
_SECOES_FORA = {"HEADING", "CLAIMS", "VALUE", "CLOSING", "JURIMETRY"}


@lru_cache(maxsize=1)
def _defesas() -> dict[str, list[dict[str, str]]]:
    with ARQUIVO_DEFESAS.open(encoding="utf-8") as f:
        return json.load(f)["defesas"]


def sementes(t: dict[str, Any]) -> list[dict[str, Any]]:
    saida = []
    for inst in t.get("institutos") or []:
        for d in _defesas().get(inst) or []:
            rid = f"{inst}.{d['requisito']}"
            saida.append({"defesa": d["defesa"], "requisito_id": rid if any(r["id"] == rid for r in t["requisitos"]) else ""})
    return saida


_INSTRUCAO = """Você é o advogado da RECLAMADA. Para cada tese do reclamante abaixo, liste até 3 DEFESAS plausíveis que a
contestação provavelmente usará, considerando os FATOS deste caso (não defesas genéricas que os fatos já afastam).
Parta das sugestões do catálogo de cada tese e ajuste ao caso; descarte as que não se aplicam.
Devolva JSON estrito:
{"teses":[{"tese_id":"I01","defesas":[{"defesa":"frase curta","requisito_id":"id do requisito atacado (da lista) ou null",
  "fatos_que_a_enfrentam":["M00x da matriz que a peça pode usar contra essa defesa"],"forca":"alta|media|baixa"}]}]}
Não cite número de artigo, súmula, tema ou processo."""


def _entrada(teses: list[dict[str, Any]], texto_matriz: str) -> str:
    blocos = []
    for t in teses:
        reqs = "\n".join(f"   - {r['id']}: {r['requisito']} [{r['estado']}, prova {r.get('forca_da_prova', '?')}]" for r in t["requisitos"])
        sem = "\n".join(f"   - {s['defesa']}" for s in sementes(t)) or "   - (sem sugestão no catálogo)"
        blocos.append(f"## {t['tese_id']} — {t['tese']}\nRequisitos:\n{reqs}\nSugestões do catálogo:\n{sem}")
    return "\n\n".join(blocos) + "\n\n" + texto_matriz[:40_000]


def _tem_prova(t: dict[str, Any], requisito_id: str, fatos_ids: list[str], fatos: dict[str, dict[str, Any]]) -> bool:
    req = next((r for r in t["requisitos"] if r["id"] == requisito_id), None)
    if req is not None and req.get("forca_da_prova") in (pv.FORTE, pv.MEDIA):
        return True
    return any(usavel(fatos[i]) and fatos[i].get("estado") == CONFIRMADO for i in fatos_ids if i in fatos)


def _orientacao(t: dict[str, Any], c: dict[str, Any], fatos: dict[str, dict[str, Any]]) -> str:
    req = next((r for r in t["requisitos"] if r["id"] == c["requisito_id"]), None)
    if c["tem_prova"]:
        provas = [p.get("documento") or p["fato_id"] for p in (req or {}).get("provas") or [] if not p["contraditoria"]][:2]
        provas = provas or [str(fatos[i].get("documento") or i) for i in c["fatos_que_a_enfrentam"] if i in fatos][:2]
        return (f"Defesa provável «{c['defesa']}»: deixe explícita no capítulo a prova que a afasta ({', '.join(provas)}), "
                "sem reproduzir a defesa.")
    tipica = pv.prova_tipica(c["requisito_id"] or "*.*")
    alvo = f"«{req['requisito']}»" if req else "o requisito atacado"
    return (f"Capítulo vulnerável à defesa «{c['defesa']}»: fortaleça {alvo} com os fatos do caso e indique a prova a produzir "
            f"({tipica['tipica']}; alternativa: {tipica['alternativa']}), sem escrever a defesa da ré.")


def gerar(raciocinio: dict[str, Any], matriz: dict[str, Any], *, llm: Callable[[str, str], dict[str, Any]] | None = None,
          texto_matriz: str = "", max_teses: int = 8) -> dict[str, Any]:
    fatos = {f["id"]: f for f in matriz.get("fatos") or []}
    ordem = {"SUPPORTED": 0, "POTENTIAL_NEEDS_CONFIRMATION": 1}
    relevantes = sorted((t for t in raciocinio.get("teses") or [] if t["decisao"] in ordem), key=lambda t: ordem[t["decisao"]])[:max_teses]
    do_modelo: dict[str, list[dict[str, Any]]] = {}
    erro = ""
    if llm is not None and relevantes:
        try:
            bruto = llm(_INSTRUCAO, _entrada(relevantes, texto_matriz)) or {}
            for item in bruto.get("teses") or []:
                if isinstance(item, dict) and isinstance(item.get("defesas"), list):
                    do_modelo[str(item.get("tese_id") or "")] = [d for d in item["defesas"] if isinstance(d, dict)]
        except Exception as e:  # noqa: BLE001 - sem modelo, vale a semente do catálogo
            erro = f"{type(e).__name__}: {str(e)[:160]}"
    vulneraveis = []
    for t in relevantes:
        ids_req = {r["id"] for r in t["requisitos"]}
        brutas = do_modelo.get(t["tese_id"])
        origem = "modelo" if brutas else "catalogo"
        lista = []
        for d in (brutas or sementes(t))[:MAX_POR_TESE]:
            texto = str(d.get("defesa") or "").strip()
            if not texto:
                continue
            rid = str(d.get("requisito_id") or "").strip()
            rid = rid if rid in ids_req else ""
            fids = [i for i in d.get("fatos_que_a_enfrentam") or [] if isinstance(i, str) and i in fatos]
            forca = str(d.get("forca") or "media").strip().lower()
            c = {"defesa": texto[:240], "requisito_id": rid,
                 "requisito": next((r["requisito"] for r in t["requisitos"] if r["id"] == rid), ""),
                 "forca": forca if forca in FORCAS else "media", "fatos_que_a_enfrentam": fids, "origem": origem,
                 "respondida": None, "trecho_resposta": ""}
            c["tem_prova"] = _tem_prova(t, rid, fids, fatos)
            c["vulneravel"] = not c["tem_prova"] and c["forca"] != "baixa"
            c["orientacao"] = _orientacao(t, c, fatos) if c["forca"] != "baixa" else ""
            lista.append(c)
            if c["vulneravel"]:
                vulneraveis.append({"tese_id": t["tese_id"], "tese": t["tese"], "defesa": c["defesa"], "requisito": c["requisito"],
                                    "orientacao": c["orientacao"]})
        t["contrateses"] = lista
    raciocinio["capitulos_vulneraveis"] = vulneraveis
    return {"teses": len(relevantes), "geradas": sum(len(t.get("contrateses") or []) for t in relevantes),
            "origem": "modelo" if do_modelo else "catalogo", "erro": erro}


# ------------------------------------------------------------------ auditor

def _compacto(t: str) -> str:
    return norm(" ".join(str(t or "").split()))


def capitulo_da_tese(secoes: list[dict[str, Any]], tese: str, *, limite: int = 6000) -> str:
    """Parágrafos argumentativos que tratam da tese (por termos do nome), na ordem da peça."""
    alvo = tokens(tese)
    paragrafos = [p for s in secoes if str(s.get("code") or "") not in _SECOES_FORA
                  for p in re.split(r"\n\s*\n", _texto(s)) if p.strip()]
    if not alvo:
        return "\n\n".join(paragrafos)[:limite]
    escolhidos = [i for i, p in enumerate(paragrafos) if len(alvo & tokens(p)) >= min(2, len(alvo))]
    vizinhos = sorted({j for i in escolhidos for j in (i, i + 1) if j < len(paragrafos)})
    return "\n\n".join(paragrafos[j] for j in vizinhos)[:limite]


_INSTRUCAO_AUDITOR = """Você confere se um trecho de PETIÇÃO já enfrenta uma DEFESA provável da reclamada (com fato, prova ou
argumento que a afaste). Para cada item: "respondida": true/false e, se true, `trecho` com cópia LITERAL da petição que a
enfrenta (obrigatória). Devolva JSON estrito: {"itens":[{"id":"D1","respondida":true,"trecho":"..."}]}"""


def auditar(secoes: list[dict[str, Any]], raciocinio: dict[str, Any] | None, *,
            llm: Callable[[str, str], dict[str, Any]] | None = None) -> dict[str, Any]:
    achados: list[dict[str, Any]] = []
    itens = []
    for t in (raciocinio or {}).get("teses") or []:
        if not t.get("contrateses"):
            continue
        cap = capitulo_da_tese(secoes, t["tese"])
        for c in t["contrateses"]:
            itens.append({"t": t, "c": c, "capitulo": cap})
    avaliacao = "lexica"
    if llm is not None and itens:
        try:
            for inicio in range(0, len(itens), 8):
                lote = itens[inicio:inicio + 8]
                for n, x in enumerate(lote, start=1):
                    x["id"] = f"D{n}"
                entrada = "\n\n".join(f"### {x['id']}\nDEFESA: {x['c']['defesa']}\nPETIÇÃO (capítulo da tese {x['t']['tese']}):\n{x['capitulo'] or '(a peça não tem capítulo desta tese)'}"
                                      for x in lote)
                saida = llm(_INSTRUCAO_AUDITOR, entrada) or {}
                por_id = {str(r.get("id")): r for r in saida.get("itens") or [] if isinstance(r, dict)}
                for x in lote:
                    r = por_id.get(x["id"]) or {}
                    trecho = str(r.get("trecho") or "").strip()
                    ok = bool(r.get("respondida")) and len(_compacto(trecho)) >= 15 and _compacto(trecho) in _compacto(x["capitulo"])
                    x["c"]["respondida"], x["c"]["trecho_resposta"] = ok, trecho[:300] if ok else ""
            avaliacao = "modelo"
        except Exception:  # noqa: BLE001 - cai para a avaliação léxica, registrada em `avaliacao`
            avaliacao = "lexica"
    if avaliacao == "lexica":
        for x in itens:
            alvo = tokens(x["c"]["defesa"])
            x["c"]["respondida"] = bool(alvo) and len(alvo & tokens(x["capitulo"])) / len(alvo) >= 0.5
    for x in itens:
        c, t = x["c"], x["t"]
        if c["forca"] == "baixa":
            continue
        if not c["respondida"] and c["forca"] == "alta":
            achados.append(_achado(AUDITOR, "CONTRATESE_RELEVANTE_SEM_RESPOSTA", ALERTA, "LEGAL_GROUNDS", t["tese"],
                                   f"defesa provável «{c['defesa']}» não é enfrentada no capítulo; {c.get('orientacao') or ''}"))
        if not c["tem_prova"]:
            achados.append(_achado(AUDITOR, "CONTRATESE_SEM_PROVA_NA_MATRIZ", ALERTA, "LEGAL_GROUNDS", t["tese"],
                                   f"nenhuma prova da matriz enfrenta «{c['defesa']}»" + (f" (requisito: {c['requisito']})" if c["requisito"] else "")))
    return {"auditor": AUDITOR, "achados": achados, "avaliacao": avaliacao}


def pendencias(raciocinio: dict[str, Any] | None, *, limite: int = 6) -> list[str]:
    saida = []
    for t in (raciocinio or {}).get("teses") or []:
        if t["decisao"] != "SUPPORTED":
            continue
        for c in t.get("contrateses") or []:
            if c.get("vulneravel") or (c.get("respondida") is False and c["forca"] == "alta"):
                saida.append(f"Contratese provável em «{t['tese']}»: {c['defesa']}"
                             + ("" if c["tem_prova"] else " — sem prova no caso que a enfrente")
                             + (" — a peça não a enfrenta" if c.get("respondida") is False else ""))
    return saida[:limite]
