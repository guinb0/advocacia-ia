"""ISSUE SPOTTING: quais teses o caso comporta, ANTES de qualquer redação.

O catálogo de teses a considerar vem da SKILL do escritório (camada C), lido dos arquivos dela:
- as "Subteses" de todo arquivo de assunto (não só do assunto escolhido para o caso);
- as listas de exemplos ("ex. …", "… etc.") e os pedidos de praxe;
- os capítulos dos modelos de petição.
Trocar a skill troca o catálogo. O código não conhece tese nenhuma.

O modelo classifica CADA item do catálogo, sempre com motivo:
  SUPPORTED                     fatos utilizáveis da matriz sustentam a tese; vai ao corpo da peça
  POTENTIAL_NEEDS_CONFIRMATION  falta fato necessário ou confirmação; vai às pendências do advogado
  REJECTED_NO_FACTUAL_BASIS     nenhum fato do caso aponta para a tese
  REJECTED_LEGAL                os fatos existem, mas a tese não se sustenta juridicamente (prescrição, incompatibilidade…)
  REJECTED_STRATEGIC            cabível, mas a estratégia do escritório (skill) manda não deduzir
Liga cada tese a fatos da MATRIZ por id e diz o que pesquisar — sem citar número de memória. O código
rebaixa a POTENTIAL_NEEDS_CONFIRMATION toda tese SUPPORTED sem fato necessário e toda rejeição "sem base
fática" que aponte fato utilizável; nenhuma tese avaliada some depois sem registro (`auditores.auditar_consistencia`).
"""

from __future__ import annotations

import inspect
import json
import re
from typing import Any, Callable

from . import calculos, canonico
from .autoridades import norm
from .fatos import INFERIDO

SUPPORTED = "SUPPORTED"
POTENCIAL = "POTENTIAL_NEEDS_CONFIRMATION"
REJEITADA_SEM_FATO = "REJECTED_NO_FACTUAL_BASIS"
REJEITADA_JURIDICA = "REJECTED_LEGAL"
REJEITADA_ESTRATEGICA = "REJECTED_STRATEGIC"
INCLUIR = SUPPORTED
REJEITADAS = {REJEITADA_SEM_FATO, REJEITADA_JURIDICA, REJEITADA_ESTRATEGICA}
DECISOES = {SUPPORTED, POTENCIAL, *REJEITADAS}
#: Nomes antigos que o modelo (ou rastro gravado) ainda pode devolver.
_SINONIMOS = {"INCLUIR": SUPPORTED, "POTENTIAL_ISSUE_NEEDS_CONFIRMATION": POTENCIAL, "DESCARTAR": REJEITADA_SEM_FATO,
              "REJECTED": REJEITADA_SEM_FATO}
ROTULOS = {
    SUPPORTED: "incluída — fatos da matriz sustentam a tese",
    POTENCIAL: "potencial — falta fato necessário ou confirmação",
    REJEITADA_SEM_FATO: "não incluída — sem suporte factual no caso",
    REJEITADA_JURIDICA: "não incluída — óbice jurídico",
    REJEITADA_ESTRATEGICA: "não incluída — decisão estratégica do escritório",
}


def rejeitada(tese: dict[str, Any]) -> bool:
    return tese.get("decisao") in REJEITADAS

_TITULO = re.compile(r"(?m)^#\s+(.+)$")
_SUBTESES = re.compile(r"(?ms)^##\s+Subteses[^\n]*\n(.*?)(?=^##\s|\Z)")
_ITEM = re.compile(r"\*\*\s*(?:[IVXL]+\.\d+\s*[—–-]\s*)?([^*]{3,160}?)\s*\*\*\s*:?\s*([^\n]*)")
_CAPITULO_MODELO = re.compile(r"(?m)^##\s+(?:[IVXL]+\b[^.\n]*\.\s*)?(.{4,120})$")
_PARENTESES = re.compile(r"\(([^()]{10,500})\)")
#: A lista de exemplos só é catálogo de teses quando a linha fala de assunto, ação, tese, verba ou pedido.
_LINHA_DE_TESE = re.compile(r"assunto|a[cç][aã]o|tese|verba|pedido|tipo de", re.I)
_ESTRUTURAL = re.compile(
    r"qualifica|endere[cç]|valor da causa|requerimentos? finais|termos em que|fecho|s[ií]ntese|comunica[cç][oõ]es processuais"
    r"|^(?:fatos|direito|pedidos|fechamento|precedentes|rito processual)$", re.I)


def textos_da_skill_ativa() -> dict[str, str]:
    """Arquivos da skill de petição em uso (a enviada pelo escritório ou a que vem com o sistema)."""
    from .. import peticao_skill_arquivos, skill_peticao
    try:
        textos = skill_peticao.ativa().textos
    except Exception:  # noqa: BLE001 - sem banco, vale a skill do disco
        textos = None
    return dict(textos) if textos else peticao_skill_arquivos.textos_do_disco()


def catalogo_da_skill(textos: dict[str, str]) -> list[dict[str, Any]]:
    itens: list[dict[str, Any]] = []
    vistos: set[str] = set()

    def add(tema: str, assunto: str, arquivo: str, descricao: str, origem: str) -> None:
        tema = re.sub(r"\s+", " ", tema).strip(" .:;—–-")
        chave = norm(tema)
        if len(chave) < 4 or chave in vistos or _ESTRUTURAL.search(tema):
            return
        vistos.add(chave)
        itens.append({"id": f"K{len(itens) + 1:02d}", "tema": tema, "assunto": assunto, "arquivo": arquivo,
                      "descricao": " ".join(descricao.split())[:420], "origem": origem})

    for caminho, texto in sorted(textos.items()):
        texto = texto or ""
        titulo = (_TITULO.search(texto) or [None, caminho])[1].strip()
        for bloco in _SUBTESES.findall(texto):
            for m in _ITEM.finditer(bloco):
                add(m[1], titulo, caminho, m[2], "subtese")
        if caminho.rsplit("/", 1)[-1].startswith("modelo"):
            assunto = caminho.rsplit("/", 1)[0] if "/" in caminho else titulo
            for m in _CAPITULO_MODELO.finditer(texto):
                add(re.sub(r"^(?:d[aoe]s?)\s+", "", m[1].strip(), flags=re.I), assunto, caminho, "", "capitulo_de_modelo")
        for m in _PARENTESES.finditer(texto):
            dentro = m[1].strip()
            linha = texto[texto.rfind("\n", 0, m.start()) + 1: m.start()]
            exemplo = (re.match(r"ex\b\.?:?", dentro, re.I) or re.search(r"\betc\.?$", dentro)) and _LINHA_DE_TESE.search(linha)
            praxe = re.search(r"praxe", linha[-60:], re.I)
            if not (exemplo or praxe):
                continue
            corpo = re.sub(r"^ex\b\.?:?\s*", "", dentro, flags=re.I)
            corpo = re.sub(r"\s*etc\.?$", "", corpo)
            partes = [p.strip() for p in corpo.split(",") if p.strip() and not re.search(r"[×\"“]|\d+\s*h\b", p)]
            if len(partes) >= 3:
                for p in partes:
                    add(p, "pedidos de praxe" if praxe else f"exemplos — {titulo}", caminho, "", "praxe" if praxe else "exemplo")
    return itens


def _assinaturas_de_calculo() -> str:
    linhas = []
    for nome, funcao in calculos.CALCULADORAS.items():
        if nome in calculos.UNIDADES:
            continue
        params = [p for p in inspect.signature(funcao).parameters.values() if p.kind == p.KEYWORD_ONLY]
        linhas.append(f"- {nome}(" + ", ".join(p.name + ("?" if p.default is not p.empty else "") for p in params) + ")")
    return "\n".join(linhas)


def _chaves_canonicas() -> str:
    return ", ".join(f"{c.chave} ({c.rotulo})" for c in canonico.CAMPOS)


def instrucao(catalogo: list[dict[str, Any]], estrategia_da_skill: str = "") -> str:
    lista = "\n".join(f"{k['id']} | {k['tema']} | {k['assunto']}" + (f" — {k['descricao'][:160]}" if k["descricao"] else "") for k in catalogo)
    return f"""Você faz ISSUE SPOTTING de um caso trabalhista. NÃO redija a petição: identifique e qualifique as teses.

CATÁLOGO DE TESES DO ESCRITÓRIO (id | tema | assunto) — avalie TODOS, um a um:
{lista}

Teses fora do catálogo que os fatos sustentem também entram (catalogo_id null).

Devolva JSON:
{{
  "fatos_extraidos": [{{"chave":"area.atributo (ex.: contrato.salario, contrato.admissao, jornada.entrada, jornada.intervalo_minutos, pagamento.atraso_dias)",
     "valor":"como está escrito na fonte", "fonte":"nome exato do documento ou 'entrevista'", "pagina":"se houver",
     "categoria":"contrato|cronologia|pagamentos|descontos|fgts|jornada|provas|outros", "fato":"frase curta",
     "certeza":"opcional: INDICATED_BY_DOCUMENTS (o documento só indica) | REQUIRES_EXPERT_CONFIRMATION (depende de perícia)"}}],
  "teses": [{{"catalogo_id":"K01 ou null", "tese":"nome da tese",
     "decisao":"SUPPORTED|POTENTIAL_NEEDS_CONFIRMATION|REJECTED_NO_FACTUAL_BASIS|REJECTED_LEGAL|REJECTED_STRATEGIC",
     "motivo":"por que (obrigatório em toda decisão, ligado aos fatos, ao óbice jurídico ou à estratégia)",
     "fatos_que_suportam":["ids da MATRIZ DE FATOS (M001…)"],
     "fatos_necessarios":[{{"fato":"o que precisa estar provado/alegado", "presente":true, "fato_id":"M00x ou null"}}],
     "documentos":["documento do caso que prova"], "base_legal_a_pesquisar":["assunto normativo a pesquisar — SEM número de artigo de memória"],
     "jurisprudencia_a_pesquisar":["assunto/tese de jurisprudência a pesquisar — SEM número de súmula, tema ou processo de memória"],
     "requisitos":[{{"requisito":"elemento jurídico que a tese exige (ex.: conduta, dano, nexo, jornada excedente)", "fatos":["M00x que o atende"], "presente":true}}],
     "proposicoes":["2 a 5 proposições jurídicas que a peça precisa demonstrar para a tese — SEM número de artigo/súmula/tema"],
     "pedido":"o que se pede", "reflexos":["parcelas reflexas"], "prova":["documental|testemunhal|pericial: o quê"],
     "exige_pericia":false, "risco":"baixo|medio|alto — motivo",
     "calculo":{{"rubrica":"uma das calculadoras abaixo ou null", "parametros":{{}}, "parametros_faltantes":["parâmetro sem fonte"]}}}}]
}}

CALCULADORAS (o sistema calcula; você só informa os parâmetros do caso, com valor numérico e datas dd/mm/aaaa):
{_assinaturas_de_calculo()}

CHAVES FIXAS (use exatamente estas quando o fato for um destes dados): {_chaves_canonicas()}

REGRAS:
- Datas de nascimento, admissão, término e do evento, salário, remuneração e percentual de incapacidade vão SEMPRE
  em `fatos_extraidos` com a chave fixa. Idade e tempo de serviço NÃO se informam: o sistema calcula.
- Uma entrada em `teses` para CADA id do catálogo, com a decisão que explica POR QUE a tese entra ou morre:
  REJECTED_NO_FACTUAL_BASIS só quando nenhum fato do caso aponta para ela (ex.: "nenhum fato de jornada");
  REJECTED_LEGAL quando há fato mas a tese não para em pé juridicamente (diga o óbice, sem número de memória);
  REJECTED_STRATEGIC quando cabível mas a estratégia do escritório manda não deduzir (diga qual regra da skill).
- Tese com fato necessário ausente da matriz → POTENTIAL_NEEDS_CONFIRMATION (não rejeite só por falta de valor: valor se calcula ou se apura).
- Fato que exige perícia (insalubridade, periculosidade, nexo de doença) → exige_pericia=true e a prova pericial em `prova`.
- Em `requisitos`, cada elemento jurídico que a tese exige, ligado por id aos fatos da MATRIZ que o atendem (presente=false
  quando nenhum fato o atende). Em `proposicoes`, o que a peça precisa convencer o juiz, uma afirmação jurídica por item.
- Não cite número de artigo, súmula, OJ, tema ou processo: diga O QUE pesquisar. A base jurídica vem de outra camada.
- Parâmetro de cálculo só com fonte no material; o que faltar vai em parametros_faltantes.
- Não invente fato. Entrevista é alegação; documento é prova.
{('ESTRATÉGIA DO ESCRITÓRIO (skill — orienta quais teses combinar, não é fonte de norma):' + chr(10) + estrategia_da_skill[:12000]) if estrategia_da_skill else ''}"""


def _lista(x: Any) -> list[str]:
    if isinstance(x, list):
        return [str(i).strip() for i in x if str(i).strip()]
    return [str(x).strip()] if str(x or "").strip() else []


def normalizar(saida: dict[str, Any] | None, catalogo: list[dict[str, Any]], matriz: dict[str, Any]) -> dict[str, Any]:
    saida = saida if isinstance(saida, dict) else {}
    fatos = {f["id"]: f for f in matriz.get("fatos") or []}
    ids_catalogo = {k["id"]: k for k in catalogo}
    teses: list[dict[str, Any]] = []
    alertas: list[str] = []
    for bruta in saida.get("teses") or []:
        if not isinstance(bruta, dict) or not str(bruta.get("tese") or "").strip():
            continue
        cat = str(bruta.get("catalogo_id") or "").strip().upper()
        cat = cat if cat in ids_catalogo else ""
        decisao = str(bruta.get("decisao") or "").strip().upper()
        decisao = _SINONIMOS.get(decisao, decisao)
        decisao = decisao if decisao in DECISOES else POTENCIAL
        motivo = str(bruta.get("motivo") or "").strip()
        suportam = [i for i in _lista(bruta.get("fatos_que_suportam")) if i in fatos]
        invalidos = [i for i in _lista(bruta.get("fatos_que_suportam")) if i not in fatos]
        utilizaveis = [i for i in suportam if fatos[i]["estado"] != INFERIDO and not fatos[i].get("contradicoes")]
        necessarios = []
        for n in bruta.get("fatos_necessarios") or []:
            if not isinstance(n, dict) or not str(n.get("fato") or "").strip():
                continue
            fid = str(n.get("fato_id") or "").strip()
            presente = bool(n.get("presente")) and fid in fatos and fatos[fid]["estado"] != INFERIDO
            necessarios.append({"fato": str(n["fato"]).strip(), "fato_id": fid if fid in fatos else "", "presente": presente,
                                "estado": fatos[fid]["estado"] if fid in fatos else ""})
        faltantes = [n["fato"] for n in necessarios if not n["presente"]]
        rebaixada = ""
        if decisao == SUPPORTED and (not utilizaveis or faltantes):
            decisao = POTENCIAL
            rebaixada = ("fato necessário ausente/não confirmado: " + "; ".join(faltantes)) if faltantes else "nenhum fato utilizável da matriz sustenta a tese"
        if decisao in REJEITADAS and not motivo:
            decisao, rebaixada = POTENCIAL, "rejeitada sem motivo"
        if decisao == REJEITADA_SEM_FATO and utilizaveis:
            decisao, rebaixada = POTENCIAL, "rejeitada por falta de fato, mas a matriz tem fato que a sustenta: " + ", ".join(utilizaveis)
        prova = _lista(bruta.get("prova"))
        calc = bruta.get("calculo") if isinstance(bruta.get("calculo"), dict) else {}
        requisitos = []
        for r in bruta.get("requisitos") or []:
            if not isinstance(r, dict) or not str(r.get("requisito") or "").strip():
                continue
            ids = _lista(r.get("fatos"))
            requisitos.append({"requisito": str(r["requisito"]).strip()[:200], "fatos": [i for i in ids if i in fatos],
                               "fatos_invalidos": [i for i in ids if i not in fatos], "presente_segundo_o_modelo": bool(r.get("presente"))})
        proposicoes = [p[:300] for p in _lista(bruta.get("proposicoes"))][:5]
        teses.append({
            "id": f"I{len(teses) + 1:02d}", "catalogo_id": cat, "tese": str(bruta["tese"]).strip(), "decisao": decisao,
            "decisao_do_modelo": str(bruta.get("decisao") or "").strip().upper(), "motivo": motivo, "rebaixada_por": rebaixada,
            "fatos_que_suportam": suportam, "fatos_invalidos": invalidos, "fatos_necessarios": necessarios, "fatos_faltantes": faltantes,
            "documentos": _lista(bruta.get("documentos")), "base_legal_a_pesquisar": _lista(bruta.get("base_legal_a_pesquisar")),
            "jurisprudencia_a_pesquisar": _lista(bruta.get("jurisprudencia_a_pesquisar")), "pedido": str(bruta.get("pedido") or "").strip(),
            "reflexos": _lista(bruta.get("reflexos")), "prova": prova, "requisitos": requisitos, "proposicoes": proposicoes,
            "exige_pericia": bool(bruta.get("exige_pericia")) or any("peric" in norm(p) for p in prova),
            "risco": str(bruta.get("risco") or "").strip(),
            "calculo": {"rubrica": str(calc.get("rubrica") or "").strip() or None, "parametros": calc.get("parametros") if isinstance(calc.get("parametros"), dict) else {},
                        "parametros_faltantes": _lista(calc.get("parametros_faltantes"))},
        })
        invalidos += [i for r in requisitos for i in r["fatos_invalidos"] if i not in invalidos]
        if invalidos:
            alertas.append(f"{teses[-1]['id']} cita fatos inexistentes na matriz: {', '.join(invalidos)}")
    cobertos = {t["catalogo_id"] for t in teses if t["catalogo_id"]}
    nao_avaliados = [k for k in catalogo if k["id"] not in cobertos]
    return {"teses": teses, "fatos_extraidos": [f for f in saida.get("fatos_extraidos") or [] if isinstance(f, dict)],
            "nao_avaliados": nao_avaliados, "alertas": alertas}


def executar(
    llm: Callable[[str, str], dict[str, Any]], *, catalogo: list[dict[str, Any]], matriz: dict[str, Any],
    texto_matriz: str, contexto_caso: str, estrategia_da_skill: str = "", limite_entrada: int = 110_000,
) -> dict[str, Any]:
    """Issue spotting com UMA repescagem dos itens do catálogo que o modelo deixou sem avaliação."""
    entrada = (texto_matriz + "\n\n=== MATERIAL DO CASO ===\n" + contexto_caso)[:limite_entrada]
    bruto = llm(instrucao(catalogo, estrategia_da_skill), entrada)
    resultado = normalizar(bruto, catalogo, matriz)
    if resultado["nao_avaliados"]:
        faltam = resultado["nao_avaliados"]
        segunda = llm(instrucao(faltam, "") + "\n\nAvalie SOMENTE estes itens do catálogo (os demais já foram avaliados).", entrada)
        extra = normalizar(segunda, faltam, matriz)
        base = len(resultado["teses"])
        for i, t in enumerate(extra["teses"], start=1):
            t["id"] = f"I{base + i:02d}"
        resultado["teses"] += extra["teses"]
        resultado["fatos_extraidos"] += extra["fatos_extraidos"]
        resultado["alertas"] += extra["alertas"]
        resultado["nao_avaliados"] = extra["nao_avaliados"]
        resultado["repescagem"] = [k["id"] for k in faltam]
    for k in resultado["nao_avaliados"]:
        resultado["alertas"].append(f"tese do catálogo não avaliada pelo issue spotting: {k['id']} {k['tema']}")
    return resultado


def matriz_tese_fato_prova(teses: list[dict[str, Any]], matriz: dict[str, Any]) -> list[dict[str, Any]]:
    fatos = {f["id"]: f for f in matriz.get("fatos") or []}
    return [{
        "tese_id": t["id"], "tese": t["tese"], "decisao": t["decisao"],
        "fatos": [{"id": i, "estado": fatos[i]["estado"], "fato": (fatos[i].get("chave") or fatos[i]["fato"])[:120]} for i in t["fatos_que_suportam"] if i in fatos],
        "faltantes": t["fatos_faltantes"], "provas": t["prova"], "documentos": t["documentos"], "exige_pericia": t["exige_pericia"],
    } for t in teses]


def resumo_para_trace(resultado: dict[str, Any]) -> dict[str, Any]:
    teses = resultado.get("teses") or []
    return {
        "consideradas": len(teses),
        "incluidas": [t["tese"] for t in teses if t["decisao"] == SUPPORTED],
        "a_confirmar": [{"tese": t["tese"], "motivo": t["rebaixada_por"] or t["motivo"]} for t in teses if t["decisao"] == POTENCIAL],
        "descartadas": [{"tese": t["tese"], "decisao": t["decisao"], "motivo": t["motivo"]} for t in teses if t["decisao"] in REJEITADAS],
        "por_decisao": {d: sum(1 for t in teses if t["decisao"] == d) for d in sorted(DECISOES)},
        "nao_avaliadas": [k["tema"] for k in resultado.get("nao_avaliados") or []],
        "alertas": resultado.get("alertas") or [],
    }


def para_json(resultado: dict[str, Any]) -> str:
    return json.dumps(resultado, ensure_ascii=False)
