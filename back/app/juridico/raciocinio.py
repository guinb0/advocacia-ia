"""LEGAL REASONING GRAPH: por que cada tese existe, montado por CÓDIGO a partir do issue spotting e da matriz.

Por tese (não rejeitada): fato → requisito → prova → proposição/autoridade → contratese → pedido → reflexo.
- Requisitos vêm do catálogo genérico versionado `dados/requisitos.json` (o instituto é reconhecido pelo nome
  da tese) e dos que o issue spotting propôs (`origem=modelo`). Fato só entra no grafo se existir na matriz.
- Um requisito está `atendido` com fato confirmado utilizável; `so_alegado` só com entrevista; `contraditorio`
  quando o único fato está em contradição; `ausente` sem fato.
- `prova.py`, `proposicoes.py`, `contrateses.py` e `scores.py` completam a mesma estrutura (CASE_STATE.raciocinio);
  `explicar()` devolve o caminho com as fontes, `orientacoes()` o que vai ao prompt do capítulo da tese.

O modelo não decide nada aqui: propõe requisitos e liga fatos; o código valida e classifica.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import teses as ts
from .autoridades import norm
from .fatos import ALEGADO, CONFIRMADO, INFERIDO

ARQUIVO_REQUISITOS = Path(__file__).resolve().parent / "dados" / "requisitos.json"
ATENDIDO, SO_ALEGADO, CONTRADITORIO, AUSENTE = "atendido", "so_alegado", "contraditorio", "ausente"
_VAZIAS = {"para", "pela", "pelo", "como", "mais", "deve", "sobre", "entre", "quando", "com", "sem", "dos", "das", "nos",
           "nas", "que", "uma", "ser", "seu", "sua", "este", "esta", "esse", "essa", "caso", "tese", "pedido", "direito"}


@lru_cache(maxsize=1)
def catalogo() -> dict[str, Any]:
    with ARQUIVO_REQUISITOS.open(encoding="utf-8") as f:
        dados = json.load(f)
    institutos = []
    for inst in dados.get("institutos") or []:
        institutos.append({
            **inst,
            "_padroes": [re.compile(p) for p in inst.get("padroes") or []],
            "requisitos": [{**r, "_termos": [re.compile(t) for t in r.get("termos") or []]} for r in inst.get("requisitos") or []],
        })
    return {"versao": dados.get("versao", ""), "institutos": institutos}


def tokens(texto: Any) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{4,}", norm(texto)) if t not in _VAZIAS}


def institutos_da_tese(titulo: str) -> list[dict[str, Any]]:
    alvo = norm(titulo)
    return [i for i in catalogo()["institutos"] if any(p.search(alvo) for p in i["_padroes"])]


def _texto_do_fato(f: dict[str, Any]) -> str:
    return norm(" ".join(str(f.get(k) or "") for k in ("chave", "valor", "fato", "documento", "categoria")))


def usavel(f: dict[str, Any]) -> bool:
    return f.get("estado") != INFERIDO and not f.get("contradicoes")


def estado_do_requisito(fatos: list[dict[str, Any]]) -> str:
    if any(usavel(f) and f.get("estado") == CONFIRMADO for f in fatos):
        return ATENDIDO
    if any(usavel(f) and f.get("estado") == ALEGADO for f in fatos):
        return SO_ALEGADO
    if any(f.get("contradicoes") for f in fatos):
        return CONTRADITORIO
    return AUSENTE


def _casa(req: dict[str, Any], texto: str) -> bool:
    return any(t.search(texto) for t in req.get("_termos") or [])


def _especificidade(req: dict[str, Any], nome: str) -> int:
    """Quanto o nome de um requisito proposto pelo modelo se parece com o do catálogo: termos mais longos casados
    pesam mais («jornada contrat» vence «jornada»), e cada palavra em comum soma."""
    alvo = norm(nome)
    return sum(len(t.pattern) for t in req.get("_termos") or [] if t.search(alvo)) + 4 * len(tokens(nome) & tokens(req["requisito"]))


def _requisitos_da_tese(t: dict[str, Any], fatos: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    da_tese = [i for i in [*t.get("fatos_que_suportam", []), *(n.get("fato_id") for n in t.get("fatos_necessarios") or []),
                           *(i for r in t.get("requisitos") or [] for i in r.get("fatos") or [])] if i and i in fatos]
    da_tese = list(dict.fromkeys(da_tese))
    do_modelo = list(t.get("requisitos") or [])
    institutos = institutos_da_tese(t["tese"])
    presentes = {i["id"] for i in institutos}
    do_catalogo = [(inst, r) for inst in institutos for r in inst["requisitos"] if not presentes & set(r.get("dispensado_com") or [])]
    destino_do_modelo: dict[int, str] = {}
    for k, m in enumerate(do_modelo):
        notas = [(_especificidade(r, m["requisito"]), f"{inst['id']}.{r['id']}") for inst, r in do_catalogo]
        melhor = max(notas, default=(0, ""))
        if melhor[0] > 0:
            destino_do_modelo[k] = melhor[1]
    saida: list[dict[str, Any]] = []
    for inst, r in do_catalogo:
        rid = f"{inst['id']}.{r['id']}"
        if any(x["id"] == rid for x in saida):
            continue
        ligados: dict[str, str] = {}
        for k, m in enumerate(do_modelo):
            if destino_do_modelo.get(k) == rid:
                for i in m.get("fatos") or []:
                    ligados.setdefault(i, "modelo")
        for i in da_tese:
            if i not in ligados and _casa(r, _texto_do_fato(fatos[i])):
                ligados[i] = "codigo"
        if not ligados:
            for f in fatos.values():
                if usavel(f) and _casa(r, _texto_do_fato(f)):
                    ligados[f["id"]] = "codigo_matriz"
                    if len(ligados) >= 3:
                        break
        lista = [fatos[i] for i in ligados if i in fatos]
        saida.append({"id": rid, "requisito": r["requisito"], "instituto": inst["id"], "origem": "catalogo",
                      "fatos": [{"id": i, "origem": o, "estado": fatos[i]["estado"]} for i, o in ligados.items() if i in fatos],
                      "estado": estado_do_requisito(lista)})
    for k, m in enumerate(do_modelo):
        if k in destino_do_modelo:
            continue
        lista = [fatos[i] for i in m.get("fatos") or [] if i in fatos]
        saida.append({"id": f"{t['id']}.M{k + 1}", "requisito": m["requisito"], "instituto": "", "origem": "modelo",
                      "fatos": [{"id": f["id"], "origem": "modelo", "estado": f["estado"]} for f in lista],
                      "estado": estado_do_requisito(lista)})
    cobertos = {norm(x["requisito"]) for x in saida}
    for k, n in enumerate(t.get("fatos_necessarios") or []):
        if norm(n["fato"]) in cobertos or any(tokens(n["fato"]) and len(tokens(n["fato"]) & tokens(x["requisito"])) >= 2 for x in saida):
            continue
        lista = [fatos[n["fato_id"]]] if n.get("fato_id") in fatos else []
        saida.append({"id": f"{t['id']}.N{k + 1}", "requisito": n["fato"], "instituto": "", "origem": "issue_spotting",
                      "fatos": [{"id": f["id"], "origem": "modelo", "estado": f["estado"]} for f in lista],
                      "estado": estado_do_requisito(lista)})
    return saida


def _proposicoes_da_tese(t: dict[str, Any], requisitos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    textos = list(t.get("proposicoes") or [])
    origem = "issue_spotting"
    if not textos:
        textos = [*t.get("base_legal_a_pesquisar", []), *t.get("jurisprudencia_a_pesquisar", [])][:4]
        origem = "pesquisa_do_issue_spotting"
    if not textos:
        textos = [f"{r['requisito']} configura-se no caso" for r in requisitos[:4]]
        origem = "requisitos"
    return [{"id": f"{t['id']}.P{k + 1}", "texto": p, "origem": origem} for k, p in enumerate(dict.fromkeys(textos)) if p][:5]


def montar(issues: dict[str, Any], matriz: dict[str, Any], *, calculos: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    fatos = {f["id"]: f for f in matriz.get("fatos") or []}
    por_tese_calc = {c.get("tese_id"): c for c in calculos or [] if c.get("tese_id")}
    saida = []
    for t in issues.get("teses") or []:
        if ts.rejeitada(t):
            continue
        requisitos = _requisitos_da_tese(t, fatos)
        calc = por_tese_calc.get(t["id"]) or {}
        saida.append({
            "tese_id": t["id"], "tese": t["tese"], "decisao": t["decisao"], "institutos": sorted({r["instituto"] for r in requisitos if r["instituto"]}),
            "fatos_relevantes": [i for i in t.get("fatos_que_suportam") or [] if i in fatos],
            "requisitos": requisitos, "proposicoes": _proposicoes_da_tese(t, requisitos),
            "pedido": {"texto": t.get("pedido") or "", "valor": calc.get("valor") if not calc.get("erro") else None,
                       "calculation_id": calc.get("calculation_id") or ""},
            "reflexos": list(t.get("reflexos") or []), "exige_pericia": bool(t.get("exige_pericia")),
            "contrateses": [], "scores": {},
        })
    return {"versao_catalogo": catalogo()["versao"], "teses": saida, "lacunas": [], "capitulos_vulneraveis": []}


def tese(raciocinio: dict[str, Any] | None, tese_id: str) -> dict[str, Any] | None:
    return next((t for t in (raciocinio or {}).get("teses") or [] if t["tese_id"] == tese_id), None)


# ------------------------------------------------------------------ leitura (admin, prompt, explicação)

def como_grafo(t: dict[str, Any], fatos: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Nós e arestas de uma tese, cada aresta com a origem (documento, modelo, catálogo, código)."""
    fatos = fatos or {}
    nos = [{"id": t["tese_id"], "tipo": "tese", "rotulo": t["tese"]}]
    arestas: list[dict[str, str]] = []
    vistos = {t["tese_id"]}

    def no(i: str, tipo: str, rotulo: str, **extra: Any) -> None:
        if i not in vistos:
            vistos.add(i)
            nos.append({"id": i, "tipo": tipo, "rotulo": rotulo[:160], **extra})

    for r in t["requisitos"]:
        no(r["id"], "requisito", r["requisito"], estado=r["estado"])
        arestas.append({"de": r["id"], "para": t["tese_id"], "relacao": "exigido_por", "origem": r["origem"]})
        for f in r["fatos"]:
            base = fatos.get(f["id"]) or {}
            no(f["id"], "fato", (base.get("chave") and f"{base['chave']} = {base.get('valor', '')}") or str(base.get("fato") or f["id"]),
               estado=f["estado"])
            arestas.append({"de": f["id"], "para": r["id"], "relacao": "atende", "origem": f["origem"]})
        for p in r.get("provas") or []:
            pid = f"prova:{p['fato_id']}:{p['classe']}"
            no(pid, "prova", f"{p['classe']} — {p.get('documento') or p['fato_id']}", classe=p["classe"])
            arestas.append({"de": pid, "para": r["id"], "relacao": "prova", "origem": "documento" if p.get("documento") else "codigo"})
    for p in t["proposicoes"]:
        no(p["id"], "proposicao", p["texto"], certeza=p.get("certeza", ""))
        arestas.append({"de": p["id"], "para": t["tese_id"], "relacao": "sustenta", "origem": p["origem"]})
        for a in p.get("autoridades") or []:
            no(a["id"], "autoridade", a.get("titulo") or a["id"], posicao=a.get("posicao", ""))
            arestas.append({"de": a["id"], "para": p["id"], "relacao": a.get("posicao") or "relacionada", "origem": "acervo"})
    for k, c in enumerate(t.get("contrateses") or []):
        cid = f"{t['tese_id']}.C{k + 1}"
        no(cid, "contratese", c["defesa"], respondida=c.get("respondida"), forca=c.get("forca", ""))
        arestas.append({"de": cid, "para": c.get("requisito_id") or t["tese_id"], "relacao": "ataca", "origem": c.get("origem", "")})
    if t["pedido"]["texto"]:
        pid = f"{t['tese_id']}.PEDIDO"
        no(pid, "pedido", t["pedido"]["texto"], valor=t["pedido"].get("valor"))
        arestas.append({"de": t["tese_id"], "para": pid, "relacao": "fundamenta", "origem": "issue_spotting"})
        for k, rf in enumerate(t["reflexos"]):
            no(f"{pid}.R{k + 1}", "reflexo", rf)
            arestas.append({"de": pid, "para": f"{pid}.R{k + 1}", "relacao": "reflete_em", "origem": "issue_spotting"})
    return {"nos": nos, "arestas": arestas}


_ROTULO_ESTADO = {ATENDIDO: "atendido por fato confirmado", SO_ALEGADO: "só alegado (entrevista)",
                  CONTRADITORIO: "fato em contradição", AUSENTE: "sem fato no caso"}


def explicar(raciocinio: dict[str, Any] | None, tese_id: str, fatos: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """Por que a tese existe: requisitos, fatos com fonte, prova, proposições com certeza, contrateses e pedido."""
    t = tese(raciocinio, tese_id)
    if t is None:
        return []
    fatos = fatos or {}
    linhas = [f"Tese «{t['tese']}» ({ts.ROTULOS.get(t['decisao'], t['decisao'])})."]
    for r in t["requisitos"]:
        fontes = []
        for f in r["fatos"]:
            base = fatos.get(f["id"]) or {}
            fontes.append(f"{f['id']} ({f['estado']}{', ' + str(base.get('documento') or base.get('fonte')) if base.get('documento') or base.get('fonte') else ''})")
        provas = ", ".join(f"{p['classe']}" for p in r.get("provas") or [])
        linhas.append(f"- Requisito «{r['requisito']}» [{r['origem']}]: {_ROTULO_ESTADO[r['estado']]}"
                      + (f" — {'; '.join(fontes)}" if fontes else "") + (f"; prova: {provas}" if provas else ""))
    for p in t["proposicoes"]:
        autoridades = ", ".join(a.get("titulo") or a["id"] for a in p.get("autoridades") or [] if a.get("posicao") != "contraria")
        linhas.append(f"- Proposição «{p['texto']}»: certeza {p.get('certeza') or 'não avaliada'}" + (f" — {autoridades}" if autoridades else ""))
    for c in t.get("contrateses") or []:
        linhas.append(f"- Contratese «{c['defesa']}»: " + ("respondida na peça" if c.get("respondida") else "sem resposta na peça" if c.get("respondida") is False else "não auditada")
                      + ("; há prova que a enfrenta" if c.get("tem_prova") else "; sem prova que a enfrente" if c.get("tem_prova") is False else ""))
    if t["pedido"]["texto"]:
        linhas.append(f"- Pedido: {t['pedido']['texto']}" + (f" (valor calculado {t['pedido']['valor']})" if t["pedido"].get("valor") else ""))
    return linhas


def orientacoes(raciocinio: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    """Por tese, o que o capítulo precisa: requisitos fracos, prova a usar primeiro, tom de cada proposição e
    as defesas a neutralizar com prova. Não é argumentação defensiva: diz o que fortalecer."""
    saida = {}
    for t in (raciocinio or {}).get("teses") or []:
        linhas = []
        fracos = [r for r in t["requisitos"] if r["estado"] != ATENDIDO]
        if fracos:
            linhas.append("Requisitos ainda frágeis: " + "; ".join(f"{r['requisito']} ({_ROTULO_ESTADO[r['estado']]})" for r in fracos[:5]))
        melhores = sorted({(p["peso"], p.get("documento") or p["fato_id"], p["classe"]) for r in t["requisitos"] for p in r.get("provas") or []},
                          reverse=True)[:4]
        if melhores:
            linhas.append("Use primeiro a prova mais forte: " + "; ".join(f"{d} ({c})" for _, d, c in melhores))
        for p in t["proposicoes"]:
            if p.get("tom"):
                linhas.append(f"Proposição «{p['texto'][:140]}»: certeza {p.get('certeza')} — {p['tom']}")
        for c in t.get("contrateses") or []:
            if c.get("orientacao"):
                linhas.append(c["orientacao"])
        if linhas:
            saida[t["tese_id"]] = {"tese": t["tese"], "texto": "ORIENTAÇÃO DO MOTOR JURÍDICO PARA ESTA TESE:\n- " + "\n- ".join(linhas)}
    return saida


def orientacao_para_topico(orient: dict[str, dict[str, str]] | None, titulo: str, corpo: str = "") -> str:
    """A orientação da tese cujo nome mais se parece com o título do tópico (ou, sem título, com o começo do corpo)."""
    if not orient:
        return ""
    alvo = tokens(titulo) or tokens(corpo[:400])
    melhor = None
    for o in orient.values():
        comum = len(alvo & tokens(o["tese"]))
        if comum and (melhor is None or comum > melhor[0]):
            melhor = (comum, o)
    return melhor[1]["texto"] if melhor else ""


def para_prompt(raciocinio: dict[str, Any] | None) -> str:
    orient = orientacoes(raciocinio)
    if not orient:
        return ""
    return "=== MOTOR JURÍDICO (por tese: requisitos, prova, certeza e defesas a neutralizar) ===\n" + "\n\n".join(
        f"[{tid}] {o['tese']}\n{o['texto']}" for tid, o in orient.items())


def para_trace(raciocinio: dict[str, Any] | None, matriz: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not raciocinio:
        return None
    fatos = {f["id"]: f for f in (matriz or {}).get("fatos") or []}
    return {
        "versao_catalogo": raciocinio.get("versao_catalogo"),
        "teses": [{**{k: v for k, v in t.items()}, "grafo": como_grafo(t, fatos), "explicacao": explicar(raciocinio, t["tese_id"], fatos)}
                  for t in raciocinio.get("teses") or []],
        "matriz_de_prova": raciocinio.get("matriz_de_prova") or [],
        "lacunas": raciocinio.get("lacunas") or [],
        "capitulos_vulneraveis": raciocinio.get("capitulos_vulneraveis") or [],
        "alertas": raciocinio.get("alertas") or [],
        "ordem_por_prioridade": raciocinio.get("ordem_por_prioridade") or [],
        "auditoria": raciocinio.get("auditoria"),
        "falhas": raciocinio.get("falhas") or [],
    }
