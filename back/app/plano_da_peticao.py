"""PETITION_PLAN — o plano ESTRUTURADO da peça: partes, fatos com id, teses isoladas, pedidos únicos.

POR QUE ISTO EXISTE

Numa geração de teste três erros chegaram ao texto: peça aberta sem a qualificação das partes,
pedido escrito duas vezes e fato/fundamento de uma tese vazando para outra. Os três têm a mesma
causa: a peça era "contexto enorme → LLM → petição inteira", e nada no código sabia QUAL fato
pertencia a QUAL tese, QUAIS pedidos existiam nem QUEM eram as partes. Pedido nascia em dois
lugares (dentro da tese e de novo na seção "Dos pedidos"), e o acervo (peças de outros clientes)
entrava no mesmo contexto dos fatos do caso.

O QUE ESTE MÓDULO FAZ (tudo determinístico; o LLM só redige)

- `partes`: autor e réu com campos VERIFICADOS contra o texto do caso (o que não consta dos
  documentos/entrevista/cadastro não entra — nunca se completa qualificação com dado inventado);
  quais campos a peça exige vem da SKILL (`validacoes.md`, parâmetro `qualificacao`).
- `fatos`: F01.. com proveniência (documento/citação) quando existir.
- `teses`: T01.. cada uma declara os fatos (`fatos_ids`), as provas e os pedidos que usa;
  `contexto_da_tese` devolve SÓ o que aquela tese pode usar.
- `pedidos`: P01.. — FONTE ÚNICA. A seção "Dos pedidos" é RENDERIZADA daqui (`renderizar_pedidos`),
  nunca pedida de novo ao modelo; a deduplicação é por tipo/tese/objeto/base (e por similaridade
  semântica, com adjudicação), não por string.
- O acervo de peças não cria pedido, fato nem parte: `pedidos` só nascem do plano do CASO.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable

CAMPOS_DE_PARTE = {
    "autor": ("nome", "nacionalidade", "estado_civil", "profissao", "cpf", "rg", "pis", "ctps", "endereco", "cep", "telefone", "email"),
    "reu": ("nome", "cnpj", "endereco", "cep"),
}


def norm(texto: str) -> str:
    sem = "".join(c for c in unicodedata.normalize("NFD", str(texto or "").lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", sem)).strip()


def _so_digitos(t: str) -> str:
    return re.sub(r"\D", "", str(t or ""))


def _tokens(t: str, minimo: int = 4) -> set[str]:
    return {w for w in norm(t).split() if len(w) >= minimo}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


# ------------------------------------------------------------------ partes (verificadas)

def _valor_consta(campo: str, valor: str, texto_norm: str, texto_digitos: str) -> bool:
    if campo in ("cpf", "cnpj", "rg", "pis", "ctps", "cep", "telefone"):
        d = _so_digitos(valor)
        return len(d) >= 5 and d in texto_digitos
    # Cidade/UF do endereço tem de estar no texto. Cobertura de 80% dos tokens
    # deixava passar «Rua X, Tucuruí/PA» quando o documento só diz Belém: a rua
    # batia e a cidade de outro caso entrava na qualificação.
    for cidade in re.findall(r"\b([A-Za-zÀ-ÿ][\wÀ-ÿ'-]{3,})\s*[-–—/]\s*[A-Z]{2}\b", str(valor or "")):
        if norm(cidade) not in texto_norm:
            return False
    n = norm(valor)
    if len(n) < 3:
        return False
    if n in texto_norm:
        return True
    # Endereço, profissão e nome vêm formatados de outro jeito nos documentos ("Passagem Santa Fé, nº 70,
    # bairro Guamá" × "PS. STA. SANTA FE ... 70"): vale a COBERTURA dos termos significativos, não a igualdade.
    termos = [t for t in n.split() if len(t) >= 3 or t.isdigit()]
    return len(termos) >= 2 and sum(1 for t in termos if t in texto_norm) / len(termos) >= 0.8


def verificar_partes(bruto: dict[str, Any] | None, cadastro: dict[str, Any], texto_do_caso: str) -> dict[str, Any]:
    """Partes com SÓ os campos que constam do caso (cadastro estruturado ou texto dos documentos/entrevista).

    `bruto` é a proposta do modelo; cadastro estruturado tem prioridade. Campo que o modelo propôs e
    que não aparece no texto do caso é descartado e listado em `descartados` — é exatamente o dado
    inventado para "completar" a qualificação.
    """
    texto_norm, texto_dig = norm(texto_do_caso), _so_digitos(texto_do_caso)
    partes: dict[str, Any] = {"autor": {}, "reu": {}, "descartados": [], "origem": {}}
    for papel, campos in CAMPOS_DE_PARTE.items():
        proposto = (bruto or {}).get(papel) if isinstance((bruto or {}).get(papel), dict) else {}
        for campo in campos:
            valor = ""
            if papel == "autor" and cadastro.get(campo):
                valor, origem = str(cadastro[campo]), "cadastro"
            elif proposto.get(campo):
                valor, origem = str(proposto[campo]).strip(), "documentos"
            else:
                continue
            if origem == "cadastro" or _valor_consta(campo, valor, texto_norm, texto_dig):
                partes[papel][campo] = valor
                partes["origem"][f"{papel}.{campo}"] = origem
            else:
                partes["descartados"].append(f"{papel}.{campo}={valor}")
    return partes


def campos_faltantes(partes: dict[str, Any], exigidos: dict[str, list[str]]) -> dict[str, list[str]]:
    return {papel: [c for c in campos if not partes.get(papel, {}).get(c)] for papel, campos in exigidos.items()}


# ------------------------------------------------------------------ fatos, teses, pedidos

def _melhor_fato(texto: str, fatos: list[dict[str, Any]], minimo: float = 0.25) -> str | None:
    alvo = _tokens(texto)
    melhor, pontos = None, 0.0
    for f in fatos:
        p = _jaccard(alvo, _tokens(f["fato"]))
        if p > pontos:
            melhor, pontos = f["id"], p
    return melhor if pontos >= minimo else None


def montar(outline: dict[str, Any] | None, *, partes: dict[str, Any], fatos_documentais: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """PETITION_PLAN a partir do plano do modelo (outline) + fatos da análise documental."""
    outline = outline or {}
    fatos: list[dict[str, Any]] = []
    id_do_modelo: dict[str, str] = {}  # "C1" (id que o modelo deu na cronologia) → "F01"
    for c in outline.get("cronologia") or []:
        if isinstance(c, dict) and str(c.get("fato") or "").strip():
            fatos.append({"id": f"F{len(fatos) + 1:02d}", "data": str(c.get("data") or ""), "fato": str(c["fato"]).strip(),
                          "fonte": str(c.get("fonte") or ""), "documentos": [], "citacao": ""})
            if c.get("id"):
                id_do_modelo[str(c["id"]).strip().upper()] = fatos[-1]["id"]
    for d in fatos_documentais or []:
        existente = _melhor_fato(d["fato"], fatos, 0.4)
        prov = d.get("proveniencia") or {}
        if existente:
            f = next(x for x in fatos if x["id"] == existente)
            f["documentos"] = sorted(set(f["documentos"]) | {prov.get("arquivo", "")} - {""})
            f["citacao"] = f["citacao"] or prov.get("citacao", "")
        else:
            fatos.append({"id": f"F{len(fatos) + 1:02d}", "data": "", "fato": d["fato"], "fonte": prov.get("arquivo", ""),
                          "documentos": [prov.get("arquivo", "")] if prov.get("arquivo") else [], "citacao": prov.get("citacao", "")})

    teses: list[dict[str, Any]] = []
    for t in outline.get("teses") or []:
        if not isinstance(t, dict) or not str(t.get("tese") or "").strip():
            continue
        # ids declarados pelo modelo (determinístico); o casamento por texto só cobre o que ele deixou de declarar
        ids = [id_do_modelo[str(x).strip().upper()] for x in t.get("fatos_ids") or [] if str(x).strip().upper() in id_do_modelo]
        if not ids:
            ids = [i for i in (_melhor_fato(str(x), fatos) for x in t.get("fatos_que_sustentam") or []) if i]
        teses.append({"id": f"T{len(teses) + 1:02d}", "id_do_modelo": str(t.get("id") or "").strip().upper(),
                      "titulo": str(t["tese"]).strip(), "fatos_ids": sorted(set(ids)),
                      "provas": [str(x) for x in t.get("provas") or []],
                      # LEGAL_ARGUMENT_MAP: tese → fatos → provas → fundamento → jurisprudência → consequência → pedido
                      "fundamentos_legais": [str(x) for x in t.get("fundamentos_legais") or []],
                      "jurisprudencias": [str(x) for x in t.get("jurisprudencias") or []],
                      "consequencia": str(t.get("consequencia") or "").strip(),
                      "funcao_argumentativa": str(t.get("funcao_argumentativa") or "").strip(),
                      "relacao": str(t.get("relacao") or "principal").strip().lower(),
                      "gera_pedido": t.get("gera_pedido", True) is not False, "pedidos_ids": []})

    pedidos: list[dict[str, Any]] = []
    for p in outline.get("pedidos_estruturados") or []:
        if not isinstance(p, dict) or not str(p.get("objeto") or p.get("tipo") or "").strip():
            continue
        tese = next((t for t in teses if p.get("tese_id") and t["id_do_modelo"] == str(p["tese_id"]).strip().upper()), None)
        pontos = 1.0 if tese else 0.0
        alvo = _tokens(f"{p.get('tese', '')} {p.get('tipo', '')} {p.get('objeto', '')}")
        for t in ([] if tese else teses):
            s = _jaccard(alvo, _tokens(t["titulo"]))
            if s > pontos:
                tese, pontos = t, s
        de_praxe = bool(p.get("de_praxe"))
        metodo = p.get("metodo_calculo") if isinstance(p.get("metodo_calculo"), dict) else {}
        try:
            valor = float(p["valor_numerico"]) if p.get("valor_numerico") not in (None, "") else None
        except (TypeError, ValueError):
            valor = None
        natureza = str(p.get("natureza") or "cumulativo").strip().lower()
        pedidos.append({
            "id": f"P{len(pedidos) + 1:02d}", "tipo": str(p.get("tipo") or "").strip(), "objeto": str(p.get("objeto") or "").strip(),
            "fundamento": str(p.get("fundamento") or "").strip(), "valor_ou_base": str(p.get("valor_ou_base") or "").strip(),
            "de_praxe": de_praxe, "tese_origem": tese["id"] if tese and pontos >= 0.1 else ("" if not de_praxe else "praxe"),
            # CLAIM LEDGER
            "causa_de_pedir": str(p.get("causa_de_pedir") or "").strip(), "natureza": natureza if natureza in ("cumulativo", "subsidiario", "alternativo") else "cumulativo",
            "subsidiario_de": str(p.get("subsidiario_de") or "").strip(), "dependencias": [str(x) for x in p.get("dependencias") or []],
            "valor": valor, "metodo_calculo": metodo,
            # o que este item É no ledger: pedido autônomo, ou agravante/critério/consequência de OUTRO (nunca 2ª indenização)
            "tipo_de_item": str(p.get("tipo_de_item") or "autonomo").strip().lower(), "agrava": str(p.get("agrava") or "").strip(),
            "bem_juridico": str(p.get("bem_juridico") or "").strip(), "evento_causador": str(p.get("evento_causador") or "").strip(),
            "dano": str(p.get("dano") or "").strip(), "objeto_economico": str(p.get("objeto_economico") or "").strip(),
        })
    for p in pedidos:
        for t in teses:
            if p["tese_origem"] == t["id"]:
                t["pedidos_ids"].append(p["id"])
    # o item que declara `agrava` aponta para o pedido que ele majora
    for p in pedidos:
        if p["tipo_de_item"] in ("agravante", "criterio_de_quantificacao", "consequencia") or p["agrava"]:
            alvo = _tokens(p["agrava"] or f"{p['tipo']} {p['objeto']}")
            melhor = max((q for q in pedidos if q is not p and q["tipo_de_item"] == "autonomo"), key=lambda q: _jaccard(alvo, _chave(q)), default=None)
            p["agrava_id"] = melhor["id"] if melhor and _jaccard(alvo, _chave(melhor)) > 0 else ""
    for f in fatos:
        f["estado_probatorio"] = "CONFIRMED" if f["documentos"] else "ALLEGED"
    ausencias = [{"afirmacao": str(a.get("afirmacao") or ""), "estado": str(a.get("estado") or "NOT_FOUND_IN_AVAILABLE_DOCUMENTS").upper()}
                 for a in outline.get("ausencias") or [] if isinstance(a, dict) and str(a.get("afirmacao") or "").strip()]
    return {"partes": partes, "fatos": fatos, "teses": teses, "pedidos": pedidos, "ausencias": ausencias}


def tese_do_topico(plano: dict[str, Any], titulo: str, texto: str = "") -> dict[str, Any] | None:
    alvo = _tokens(f"{titulo} {titulo} {texto[:300]}")
    melhor, pontos = None, 0.0
    for t in plano.get("teses") or []:
        s = _jaccard(alvo, _tokens(t["titulo"]))
        if s > pontos:
            melhor, pontos = t, s
    return melhor if pontos >= 0.08 else None


def fatos_comuns(plano: dict[str, Any]) -> set[str]:
    """Fato declarado por 2+ teses é COMUM: uso legítimo em qualquer uma delas."""
    contagem: dict[str, int] = {}
    for t in plano.get("teses") or []:
        for i in t.get("fatos_ids") or []:
            contagem[i] = contagem.get(i, 0) + 1
    return {i for i, n in contagem.items() if n >= 2}


def contexto_da_tese(plano: dict[str, Any], tese: dict[str, Any] | None) -> str:
    """O que UMA tese pode usar — e o que é de outras teses (para não vazar)."""
    if not tese:
        return ""
    por_id = {f["id"]: f for f in plano["fatos"]}
    comuns = fatos_comuns(plano)
    permitidos = list(dict.fromkeys([*(tese.get("fatos_ids") or []), *sorted(comuns)]))
    linhas = [f"ISOLAMENTO DESTA TESE ({tese['id']} — {tese['titulo']}):", "FATOS PERMITIDOS (id | fato | documento):"]
    for i in permitidos:
        f = por_id.get(i)
        if f:
            linhas.append(f"- {i} | {f['fato']} | {', '.join(f['documentos']) or f['fonte']}")
    outros = [t for t in plano["teses"] if t["id"] != tese["id"]]
    exclusivos = sorted({i for t in outros for i in (t.get("fatos_ids") or [])} - set(permitidos))
    if exclusivos:
        linhas.append("FATOS DE OUTRAS TESES (NÃO os traga para cá): " + "; ".join(f"{i} {por_id[i]['fato'][:70]}" for i in exclusivos if i in por_id))
    if outros:
        linhas.append("Outras teses (não invada): " + "; ".join(t["titulo"][:60] for t in outros))
    ped = [p for p in plano["pedidos"] if p["id"] in tese["pedidos_ids"]]
    linhas.append("Pedidos DESTA tese (só referência; a lista de pedidos é montada pelo sistema, NÃO escreva pedidos novos): "
                  + ("; ".join(f"{p['id']} {p['tipo']}" for p in ped) or "nenhum"))
    return "\n".join(linhas)


def para_prompt(plano: dict[str, Any]) -> str:
    """O plano estruturado em texto, para o rascunho: partes, fatos com id, teses e pedidos."""
    linhas = ["=== PLANO ESTRUTURADO DA PEÇA (PETITION_PLAN — siga; a seção de pedidos é montada pelo sistema a partir dele) ==="]
    partes = plano.get("partes") or {}
    for papel in ("autor", "reu"):
        campos = partes.get(papel) or {}
        if campos:
            linhas.append(f"Parte {papel.upper()}: " + "; ".join(f"{k}: {v}" for k, v in campos.items()))
    linhas.append("A abertura da peça (endereçamento, título da ação, objeto e qualificação das partes) aparece UMA ÚNICA VEZ, no início, com EXATAMENTE estes dados; "
                  "não repita qualificação nem título em nenhuma outra seção. Dado que não consta acima vira UMA pendência [PENDENTE: <campo>], nunca inventado.")
    categorias = list((plano.get("_funcoes_de_conteudo") or {}).keys())
    if categorias:
        linhas.append("RESPONSABILIDADE POR CONTEÚDO — desenvolva UMA vez, na seção competente, e nas demais só referencie em uma frase: "
                      + ", ".join(c.replace("_", " ") for c in categorias)
                      + ". O pedido final (dos pedidos/fecho) traz só a consequência, com o fundamento entre parênteses — nunca reproduz o desenvolvimento nem repete o mesmo requerimento.")
    if plano.get("ausencias"):
        linhas.append("ESTADO DA EVIDÊNCIA — o que os documentos disponíveis NÃO registram (não é prova de que não aconteceu): "
                      + "; ".join(a["afirmacao"] for a in plano["ausencias"])
                      + ". Redija como «os documentos disponíveis não registram …»; NUNCA como ausência demonstrada/comprovada; se o fato importa, requeira a prova (sem afirmá-lo como provado).")
    for u in ((plano.get("case_facts") or {}).get("UNCERTAINTIES") or []):
        if not isinstance(u, dict):
            continue
        linhas.append(f"INCERTEZA ({u['tipo']}) {u['campo']}: {u['detalhe']} — NÃO use nenhuma das versões; escreva uma única pendência.")
    linhas.append("\nFatos (id | data | fato | documentos):")
    linhas += [f"- {f['id']} | {f['data']} | {f['fato']} | {', '.join(f.get('documentos') or []) or f.get('fonte', '')}"
               for f in plano.get("fatos") or [] if isinstance(f, dict)]
    linhas.append("\nTeses (id | título | fatos | pedidos):")
    linhas += [f"- {t['id']} | {t['titulo']} | {','.join(t.get('fatos_ids') or [])} | {','.join(t.get('pedidos_ids') or [])}"
               for t in plano.get("teses") or [] if isinstance(t, dict)]
    linhas.append("\nPedidos (id | tipo | objeto | tese | valor/base) — FONTE ÚNICA; não escreva pedidos fora desta lista:")
    linhas += [f"- {p['id']} | {p['tipo']} | {p['objeto']} | {p.get('tese_origem') or '?'} | {p.get('valor_ou_base', '')}"
               for p in plano.get("pedidos") or [] if isinstance(p, dict)]
    return "\n".join(linhas)


# ------------------------------------------------------------------ deduplicação dos pedidos

def periodos_distintos(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Período/base/valor diferentes (anos, datas, números) fazem de dois pedidos parecidos pedidos DISTINTOS."""
    def marcas(p: dict[str, Any]) -> set[str]:
        return set(re.findall(r"\b\d{2,4}\b|\d{2}/\d{2}/\d{4}", f"{p.get('objeto', '')} {p.get('valor_ou_base', '')} {p.get('causa_de_pedir', '')}"))
    ma, mb = marcas(a), marcas(b)
    return bool(ma and mb and ma != mb)


def _chave(p: dict[str, Any]) -> set[str]:
    return _tokens(f"{p['tipo']} {p['objeto']}")


def duplicados_deterministicos(pedidos: list[dict[str, Any]], limiar: float = 0.6) -> list[tuple[str, str]]:
    """Pares que, pelo tipo/objeto normalizados, são o mesmo pedido da MESMA tese/base."""
    pares = []
    for i, a in enumerate(pedidos):
        for b in pedidos[i + 1:]:
            mesma_origem = a["tese_origem"] == b["tese_origem"] or not (a["tese_origem"] and b["tese_origem"])
            mesma_base = norm(a["valor_ou_base"]) == norm(b["valor_ou_base"]) or not (a["valor_ou_base"] and b["valor_ou_base"])
            if mesma_origem and mesma_base and not periodos_distintos(a, b) and _jaccard(_chave(a), _chave(b)) >= limiar:
                pares.append((a["id"], b["id"]))
    return pares


def deduplicar(
    pedidos: list[dict[str, Any]],
    *, similaridade: Callable[[str, str], float] | None = None,
    adjudicar: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
    limiar_semantico: float = 0.88,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(pedidos únicos, registro do que foi fundido).

    1) igual por tipo/objeto/tese/base → funde; 2) parecido semanticamente (`similaridade` ≥ limiar)
    → só funde se `adjudicar` confirmar que NÃO há diferença juridicamente relevante. Pedidos
    legítimos diferentes (mesma linguagem, períodos/beneficiários distintos) sobrevivem.
    """
    unicos: list[dict[str, Any]] = []
    fundidos: list[dict[str, Any]] = []
    for p in pedidos:
        alvo = None
        for u in unicos:
            igual = (u["tese_origem"] == p["tese_origem"] or not (u["tese_origem"] and p["tese_origem"])) \
                and (norm(u["valor_ou_base"]) == norm(p["valor_ou_base"]) or not (u["valor_ou_base"] and p["valor_ou_base"])) \
                and not periodos_distintos(u, p) and _jaccard(_chave(u), _chave(p)) >= 0.6
            if igual:
                alvo, motivo = u, "mesmo tipo/objeto/tese/base"
                break
            if similaridade and adjudicar and not periodos_distintos(u, p) and similaridade(f"{u['tipo']} {u['objeto']}", f"{p['tipo']} {p['objeto']}") >= limiar_semantico:
                if adjudicar(u, p):
                    alvo, motivo = u, "semanticamente igual (adjudicado)"
                    break
        if alvo is None:
            unicos.append(dict(p))
        else:
            alvo["fundamento"] = alvo["fundamento"] or p["fundamento"]
            fundidos.append({"mantido": alvo["id"], "removido": p["id"], "motivo": motivo})
    return unicos, fundidos


# ------------------------------------------------------------------ renderização a partir da fonte única

def renderizar_pedidos(plano: dict[str, Any], redigir: Callable[[list[dict[str, Any]]], dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """Texto da seção "Dos pedidos" montado do plano. `redigir` (LLM) só dá a REDAÇÃO de cada item.

    Devolve (texto, relatório). A ordem, a numeração (a), b), c)…) e a presença de cada pedido são do
    código: o modelo não decide quais pedidos existem, e não há como um pedido aparecer duas vezes.
    """
    todos = plano["pedidos"]
    pedidos = [p for p in todos if p.get("tipo_de_item", "autonomo") in ("autonomo", "acessorio", "")]
    fatores: dict[str, list[str]] = {}
    for p in todos:
        if p.get("tipo_de_item") in ("agravante", "criterio_de_quantificacao", "consequencia") and p.get("agrava_id"):
            fatores.setdefault(p["agrava_id"], []).append(p["objeto"] or p["tipo"])
    # A lista pode receber uma sugestão de abertura/fecho do modelo, mas NUNCA a
    # redação de cada alínea. Era essa segunda fonte que deixava entrar TEPT,
    # valores e consequências que não existiam no PETITION_PLAN.
    saida = redigir([{**p, "fatores_de_quantificacao": fatores.get(p["id"], [])} for p in pedidos]) or {}
    linhas = []
    faltou = []
    for n, p in enumerate(pedidos):
        # Fonte única: a consequência aprovada no ledger. Não interpolar texto
        # livre aqui; fatos clínicos, danos e fundamentos pertencem ao plano.
        texto = f"{p['objeto'] or p['tipo']}".strip().rstrip(";.")
        if p.get("valor_ou_base"):
            texto += f" ({p['valor_ou_base']})"
        letra = "abcdefghijklmnopqrstuvwxyz"[n] if n < 26 else f"{n + 1}"
        linhas.append(f"{letra}) {texto}{';' if n < len(pedidos) - 1 else '.'}")
    abertura = str(saida.get("abertura") or "").strip()
    # Um fecho longo também podia reintroduzir pedido livre. Só a abertura
    # curta, sem valores/listas, é aproveitada; o restante é estrutural.
    if len(abertura) > 400 or re.search(r"R\$|\n\s*[a-z]\)", abertura, re.I):
        abertura = ""
    # Fecho processual padronizado, também sem texto livre do modelo. Não cria
    # tese nem pedido econômico e mantém a lista formalmente completa.
    fecho = ("Requer, por fim, a citação da reclamada, o regular processamento pelo rito cabível, "
             "a intimação exclusiva em nome do advogado constituído, as comunicações processuais e a procedência dos pedidos.")
    memoria = memoria_de_calculo(pedidos)
    texto = "\n\n".join(x for x in (abertura, "\n\n".join(linhas), fecho, memoria) if x)
    return texto, {"pedidos_renderizados": [p["id"] for p in pedidos], "sem_redacao_do_modelo": faltou,
                   "memoria_de_calculo": bool(memoria)}


TITULO_MEMORIA = "Memória de cálculo dos pedidos"


def _numero(v: Any) -> float | None:
    from .juridico.calculos import valor_numerico

    n = valor_numerico(v) if v not in (None, "") else None
    return float(n) if n is not None else None


def _fator(x: float) -> str:
    return f"{int(x)}" if float(x).is_integer() else f"{x:.4f}".rstrip("0").replace(".", ",")


def memoria_de_calculo(pedidos: list[dict[str, Any]]) -> str:
    """Tabela da memória de cálculo montada do LEDGER (nunca do modelo): pedido, critério/base, conta e resultado.

    A letra é a mesma da lista de pedidos; só entram os pedidos com valor em R$. O total soma apenas os
    cumulativos autônomos — a mesma regra do valor da causa.
    """
    from .juridico.calculos import brl, valor_da_causa

    linhas = []
    for n, p in enumerate(pedidos):
        valor = _numero(p.get("valor"))
        if valor is None or valor <= 0 or str(p.get("unidade") or "BRL") != "BRL":
            continue
        letra = "abcdefghijklmnopqrstuvwxyz"[n] if n < 26 else f"{n + 1}"
        metodo = p.get("metodo_calculo") if isinstance(p.get("metodo_calculo"), dict) else {}
        base, mult = _numero(metodo.get("base")), _numero(metodo.get("multiplicador"))
        criterio = str(metodo.get("criterio") or p.get("valor_ou_base") or "valor atribuído ao pedido").strip()
        if base is not None and mult is not None:
            conta = f"{brl(base)} × {_fator(mult)}"
        elif base is not None:
            conta = brl(base)
        else:
            conta = "valor atribuído"
        nome = str(p.get("tipo") or p.get("objeto") or "").strip()
        if str(p.get("natureza") or "cumulativo") != "cumulativo":
            nome += f" ({p['natureza']})"
        nome, criterio = nome.replace("|", "/"), criterio.replace("|", "/")
        linhas.append(f"| {letra}) {nome} | {criterio} | {conta} | {brl(valor)} |")
    if not linhas:
        return ""
    total = valor_da_causa(pedidos)["valor"]
    tabela = ["| Pedido | Critério e base | Conta | Resultado |", "| --- | --- | --- | --- |", *linhas,
              f"| Total dos pedidos cumulativos |  |  | {brl(total)} |"]
    return f"{TITULO_MEMORIA}:\n\n" + "\n".join(tabela)
