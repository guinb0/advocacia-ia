"""Os quatro auditores pós-geração. A peça só está PRONTA se os quatro passarem.

LEGAL        toda citação tem autoridade vigente na data de referência; nenhum critério superado.
FACT         todo valor e data afirmados têm fonte; inferido não é afirmado; contradição não é usada.
CALCULATION  todo valor dos pedidos vem de cálculo; valor da causa único e igual à soma.
CONSISTENCY  nenhuma tese do issue spotting some sem registro; perícia requerida; contradições expostas.

Nenhum auditor altera o texto: apontam, e o veredito decide se a peça pode ser entregue como pronta.

Níveis (`nivel` de cada achado): INFO, WARNING, BLOCKING, CRITICAL. `severidade` continua "bloqueia"/"alerta"
(compatível); o nível acrescenta a gravidade: CRITICAL é o erro que, entregue, causa dano direto (autoridade ou
dispositivo inexistente, data impossível, cálculo divergente, valor da causa inconsistente, fato contradito usado
como certo, citação que não sustenta ou contradiz a afirmação, documento ou fato posterior à petição).
Strict: CRITICAL bloqueia sem fallback. Legado: CRITICAL vira pendência destacada para o advogado.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from . import autoridades as aut
from . import calculos as calc
from . import teses as ts
from .autoridades import norm
from .fatos import INFERIDO, _DATA, _REAIS, valor_canonico

BLOQUEIA, ALERTA, INFORMA = "bloqueia", "alerta", "info"
INFO, WARNING, BLOCKING, CRITICAL = "INFO", "WARNING", "BLOCKING", "CRITICAL"
NIVEIS = (INFO, WARNING, BLOCKING, CRITICAL)
#: Códigos que, se a peça sair com eles, causam dano direto. Sempre bloqueiam, qualquer que seja a severidade de origem.
CODIGOS_CRITICOS = frozenset({
    "DISPOSITIVO_INEXISTENTE", "AUTORIDADE_INEXISTENTE",
    "CRONOLOGIA_IMPOSSIVEL", "DATA_POSTERIOR_A_PETICAO", "FATO_FUTURO", "AUTORIDADE_POSTERIOR_A_PETICAO",
    "PEDIDO_DIVERGENTE_DO_CALCULO", "PEDIDO_COM_CALCULO_INEXISTENTE", "DUPLA_CONTAGEM", "BASE_SALARIAL_DIVERGENTE",
    "VALOR_DA_CAUSA_DIVERGENTE", "VALOR_DA_CAUSA_DIFERENTE_DA_SOMA", "VALOR_DA_CAUSA_NAO_FECHA",
    "FATO_CONTRADITORIO_USADO",
    "CITACAO_CONTRADIZ_A_AFIRMACAO", "CITACAO_NAO_SUSTENTA_A_AFIRMACAO",
    "DOCUMENTO_POSTERIOR_A_PETICAO",
})
_NIVEL_DA_SEVERIDADE = {BLOQUEIA: BLOCKING, ALERTA: WARNING, INFORMA: INFO}
_PESQUISA = re.compile(r"\[(?:REQUIRES_LEGAL_RESEARCH|PESQUISAR PRECEDENTE|CONFERIR)[^\]]*\]", re.I)
_IRDR = re.compile(r"\bIRDR\b|incidente de resolu[cç][aã]o de demandas repetitivas", re.I)
_SECOES_DE_PEDIDO = {"CLAIMS", "VALUE"}


def nivel_de(codigo: str, severidade: str) -> str:
    if codigo in CODIGOS_CRITICOS:
        return CRITICAL
    return _NIVEL_DA_SEVERIDADE.get(severidade, WARNING)


def _achado(auditor: str, codigo: str, severidade: str, secao: str = "", trecho: str = "", detalhe: str = "") -> dict[str, Any]:
    nivel = nivel_de(codigo, severidade)
    if nivel == CRITICAL:
        severidade = BLOQUEIA
    return {"auditor": auditor, "codigo": codigo, "severidade": severidade, "nivel": nivel, "secao": secao,
            "trecho": trecho[:220], "detalhe": detalhe[:400]}


def nivel(achado: dict[str, Any]) -> str:
    """Nível de um achado (inclusive de rastro gravado antes dos níveis existirem)."""
    return str(achado.get("nivel") or nivel_de(str(achado.get("codigo") or ""), str(achado.get("severidade") or "")))


def _texto(s: dict[str, Any]) -> str:
    return str(s.get("content") or "")


def _reais_do_texto(texto: str) -> list[float]:
    saida = []
    for m in _REAIS.finditer(texto or ""):
        bruto = m[1]
        try:
            saida.append(round(float(bruto.replace(".", "").replace(",", ".")) if "," in bruto else float(bruto.replace(".", "")), 2))
        except ValueError:
            continue
    return saida


# ------------------------------------------------------------------ LEGAL

def auditar_legal(secoes: list[dict[str, Any]], registro: aut.Registro, data_referencia: date | None) -> dict[str, Any]:
    achados, citacoes = [], []
    for s in secoes:
        texto, code = _texto(s), str(s.get("code") or "")
        for r in aut.gate(texto, registro, data_referencia):
            r["secao"] = code
            citacoes.append(r)
            if r["status"] == aut.VALIDADA_SEM_VIGENCIA:
                achados.append(_achado("LEGAL", "VIGENCIA_NAO_VERIFICADA", ALERTA, code, r["trecho"], r.get("motivo", "")))
            elif not r["aprovada"]:
                achados.append(_achado("LEGAL", r["status"], BLOQUEIA, code, r["trecho"], r.get("motivo", "")))
        for c in aut.criterios_superados(texto, registro, data_referencia):
            achados.append(_achado("LEGAL", "CRITERIO_SUPERADO", BLOQUEIA, code, c["marcador"], c["motivo"] + (f"; use {c['superado_por']}" if c["superado_por"] else "")))
        for m in _PESQUISA.finditer(texto):
            achados.append(_achado("LEGAL", "PESQUISA_JURIDICA_PENDENTE", BLOQUEIA, code, m[0], "fundamento ainda sem autoridade validada"))
        for m in _IRDR.finditer(texto):
            if re.search(r"\bTST\b|\btema\b", texto[max(0, m.start() - 220): m.end() + 220], re.I):
                achados.append(_achado("LEGAL", "INSTITUTO_A_CONFERIR", ALERTA, code, m[0],
                                       "IRDR citado junto a tese do TST: conferir se o instituto é o IRR (recursos de revista repetitivos)"))
    return {"auditor": "LEGAL", "achados": achados, "citacoes": citacoes,
            "authority_ids": sorted({c["authority_id"] for c in citacoes if c.get("authority_id") and c["aprovada"]})}


# ------------------------------------------------------------------ FACT

_REFERENCIA_DE_PRECEDENTE = re.compile(r"\b(?:TST|TRT|STF|STJ|Rel\.|Relat|Redator|julgad|DEJT|DJe|publicad)", re.I)


def _dentro_de_citacao_de_precedente(texto: str, inicio: int) -> bool:
    """Data de julgamento/publicação de precedente não é fato do caso: quem a confere é o auditor LEGAL."""
    abre = texto.rfind("(", max(0, inicio - 400), inicio)
    if abre < 0 or ")" in texto[abre:inicio]:
        return False
    fecha = texto.find(")", inicio)
    return bool(_REFERENCIA_DE_PRECEDENTE.search(texto[abre: fecha if fecha > 0 else inicio + 200]))


def _consta_das_fontes(m: re.Match[str], fontes: str) -> bool:
    """Contracheque e extrato trazem o valor em coluna, sem o "R$": com centavos, o número basta."""
    if not fontes:
        return False
    candidatos = {m[0], m[0].replace("R$ ", "R$")}
    if m.re is _REAIS and "," in m[1]:
        candidatos.add(m[1])
    return any(re.search(rf"(?<![\d.,]){re.escape(c)}(?!\d)", fontes) for c in candidatos)


def auditar_fatos(secoes: list[dict[str, Any]], matriz: dict[str, Any], *, calculos: list[dict[str, Any]] | None = None,
                  texto_das_fontes: str = "") -> dict[str, Any]:
    achados = []
    fatos = matriz.get("fatos") or []
    sustentados = {valor_canonico(f["valor"]) for f in fatos if f.get("valor") and f["estado"] != INFERIDO and not f.get("contradicoes")}
    sustentados |= {valor_canonico(f.get("data")) for f in fatos if f.get("data")}
    for c in calculos or []:
        sustentados.add(valor_canonico(calc.brl(c.get("valor") or 0)))
        for linha in c.get("memoria") or []:
            sustentados |= {valor_canonico(f"R$ {m[1]}") for m in _REAIS.finditer(linha)}
    fontes_norm = texto_das_fontes or ""
    inferidos = {valor_canonico(f["valor"]): f for f in fatos if f.get("valor") and f["estado"] == INFERIDO}
    contraditorios = {valor_canonico(f["valor"]): f for f in fatos if f.get("valor") and f.get("contradicoes")}
    for s in secoes:
        code, texto = str(s.get("code") or ""), _texto(s)
        if code in _SECOES_DE_PEDIDO:
            continue
        for m in list(_REAIS.finditer(texto)) + list(_DATA.finditer(texto)):
            bruto = m[0]
            canon = valor_canonico(bruto)
            if _dentro_de_citacao_de_precedente(texto, m.start()):
                continue
            if canon in contraditorios:
                achados.append(_achado("FACT", "FATO_CONTRADITORIO_USADO", BLOQUEIA, code, bruto, f"versão de {contraditorios[canon]['chave']} em contradição não resolvida"))
            elif canon in sustentados:
                continue
            elif canon in inferidos:
                achados.append(_achado("FACT", "FATO_INFERIDO_AFIRMADO", BLOQUEIA, code, bruto, "valor proposto pelo modelo sem fonte no material"))
            elif _consta_das_fontes(m, fontes_norm):
                continue
            else:
                achados.append(_achado("FACT", "FATO_SEM_FONTE", BLOQUEIA, code, bruto, "valor/data sem fato correspondente na matriz nem nas fontes do caso"))
    for f in fatos:
        if f["estado"] != "alegado" or not f.get("valor"):
            continue
        for s in secoes:
            t = _texto(s)
            i = t.find(str(f["valor"]))
            if i >= 0 and re.search(r"comprovad|demonstrad|restou provad|documentalmente", t[max(0, i - 160): i + 160], re.I):
                achados.append(_achado("FACT", "ALEGACAO_COMO_PROVA", ALERTA, str(s.get("code") or ""), f["valor"], f"{f.get('chave') or f['fato'][:60]} só tem fonte não documental"))
                break
    return {"auditor": "FACT", "achados": achados}


# ------------------------------------------------------------------ CALCULATION

_VALOR_DA_CAUSA = re.compile(r"(?:valor\s+da\s+causa|d[áa][\s-]+se\s+[àa]\s+causa\s+o\s+valor)[^R]{0,80}(R\$\s*[\d.]+,\d{2})", re.I)
#: Pedido sem valor líquido (art. 840, § 1º, da CLT): o rito trabalhista exige pedido certo, determinado e com valor.
_ILIQUIDO = re.compile(
    r"a\s+(?:ser(?:em)?\s+)?(?:apurad[oa]s?|liquidad[oa]s?|calculad[oa]s?)\s+em\s+(?:regular\s+)?liquida[çc][ãa]o|"
    r"(?:valor|quantia|montante)\s+a\s+(?:ser\s+)?(?:apurad|liquidad|arbitrad)[oa]|\ba\s+liquidar\b|\ba\s+apurar\b|"
    r"em\s+liquida[çc][ãa]o\s+de\s+senten[çc]a|por\s+(?:mero\s+)?c[áa]lculo\s+(?:em|na)\s+liquida[çc][ãa]o", re.I)
#: Acessórios que, por natureza, se apuram na liquidação (não são pedido ilíquido).
_ACESSORIO_DA_LIQUIDACAO = re.compile(r"juros|corre[çc][ãa]o\s+monet|atualiza[çc][ãa]o\s+monet|honor[áa]rios|previdenci|fiscais|imposto\s+de\s+renda|"
                                      r"recolhimentos?|custas", re.I)
_PEDIDO_MONETARIO = re.compile(r"pagamento|pagar|indeniza|multa|diferen[cç]a|adicional|horas?\s+extra|verbas|fgts|f[ée]rias|13[ºo°]|"
                                r"sal[aá]rio|aviso\s+pr[ée]vio|pens[aã]o|pensionamento|reembolso|ressarc|danos?\s+(?:morais|materiais|est[ée]ticos)", re.I)


def auditar_calculos(secoes: list[dict[str, Any]], pedidos: list[dict[str, Any]], calculos: list[dict[str, Any]]) -> dict[str, Any]:
    achados = []
    declarados: list[float] = []
    for s in secoes:
        texto = _texto(s)
        if str(s.get("code") or "") == "VALUE":
            declarados += _reais_do_texto(texto)
        else:
            declarados += [v for m in _VALOR_DA_CAUSA.finditer(texto) for v in _reais_do_texto(m[1])]
    for e in calc.verificar_valor_da_causa(pedidos, declarados):
        achados.append(_achado("CALCULATION", e["codigo"], BLOQUEIA, "VALUE", "", e["detalhe"]))
    permitidos = {round(float(p["valor"]), 2) for p in pedidos if p.get("valor") not in (None, "")}
    for c in calculos:
        if c.get("erro"):
            achados.append(_achado("CALCULATION", "CALCULO_INCOMPLETO", ALERTA, "", c.get("rubrica", ""), c["erro"]))
            continue
        permitidos.add(round(float(c.get("valor") or 0), 2))
        for linha in c.get("memoria") or []:
            permitidos |= set(_reais_do_texto(linha))
        for f in (c.get("fontes") or {}).values():
            if f.get("tipo") == "dinheiro" and f.get("valor") not in (None, ""):
                permitidos.add(round(float(f["valor"]), 2))
    soma = calc.valor_da_causa(pedidos)["valor"]
    if soma:
        permitidos.add(round(soma, 2))
    claims = "\n".join(_texto(s) for s in secoes if str(s.get("code") or "") == "CLAIMS")
    iliquidas: set[str] = set()
    for m in _ILIQUIDO.finditer(claims):
        inicio = max(claims.rfind("\n", 0, m.start()), 0)
        fim = claims.find("\n", m.end())
        linha = claims[inicio:fim if fim >= 0 else len(claims)].strip()
        if linha in iliquidas or _ACESSORIO_DA_LIQUIDACAO.search(linha):
            continue
        iliquidas.add(linha)
        achados.append(_achado("CALCULATION", "PEDIDO_ILIQUIDO", BLOQUEIA, "CLAIMS", linha,
                               "pedido deixado para liquidação; todo pedido de pagamento leva valor certo e memória de cálculo discriminada"))
    for v in _reais_do_texto(claims):
        if v not in permitidos:
            achados.append(_achado("CALCULATION", "VALOR_SEM_CALCULO", BLOQUEIA, "CLAIMS", calc.brl(v), "valor nos pedidos sem cálculo determinístico correspondente"))
    for p in pedidos:
        descricao = f"{p.get('tipo') or ''} {p.get('objeto') or ''}"
        if _PEDIDO_MONETARIO.search(descricao) and str(p.get("tipo_de_item") or "autonomo") == "autonomo":
            if p.get("valor") in (None, ""):
                achados.append(_achado("CALCULATION", "PEDIDO_MONETARIO_SEM_VALOR", BLOQUEIA, "CLAIMS", str(p.get("id") or descricao)[:120],
                                       "pedido financeiro não tem valor líquido no ledger"))
            elif not str(p.get("calculation_id") or ""):
                achados.append(_achado("CALCULATION", "PEDIDO_MONETARIO_SEM_CALCULO", BLOQUEIA, "CLAIMS", str(p.get("id") or descricao)[:120],
                                       "pedido financeiro tem valor, mas não aponta calculation_id"))
        if p.get("valor") not in (None, "") and calc.brl(p["valor"]) not in claims:
            achados.append(_achado("CALCULATION", "PEDIDO_SEM_VALOR_NO_TEXTO", ALERTA, "CLAIMS", p.get("objeto", "")[:120], f"valor calculado {calc.brl(p['valor'])} não aparece nos pedidos"))
    usos: dict[str, list[str]] = {}
    for p in pedidos:
        cid = str(p.get("calculation_id") or "")
        if not cid:
            continue
        somado = str(p.get("natureza") or "cumulativo") == "cumulativo" and str(p.get("tipo_de_item") or "autonomo") == "autonomo"
        if somado:
            usos.setdefault(cid, []).append(str(p.get("id") or ""))
        c = calc.por_id(calculos, cid)
        if c is None:
            achados.append(_achado("CALCULATION", "PEDIDO_COM_CALCULO_INEXISTENTE", BLOQUEIA, "CLAIMS", str(p.get("id") or ""), f"o pedido aponta {cid}, que não existe"))
        elif not c.get("erro") and p.get("valor") not in (None, "") and abs(float(p["valor"]) - float(c["valor"])) > 0.01:
            achados.append(_achado("CALCULATION", "PEDIDO_DIVERGENTE_DO_CALCULO", BLOQUEIA, "CLAIMS", str(p.get("id") or ""),
                                   f"pedido {calc.brl(p['valor'])} × {cid} {calc.brl(c['valor'])}"))
    for cid, ids in usos.items():
        if len(ids) > 1:
            achados.append(_achado("CALCULATION", "DUPLA_CONTAGEM", BLOQUEIA, "VALUE", ", ".join(ids),
                                   f"o mesmo cálculo {cid} entra na soma do valor da causa por {len(ids)} pedidos"))
    return {"auditor": "CALCULATION", "achados": achados, "valor_da_causa": calc.valor_da_causa(pedidos), "declarados": sorted(set(declarados))}


# ------------------------------------------------------------------ CONSISTENCY

def _tokens(t: str) -> set[str]:
    return {x for x in re.findall(r"[a-z]{4,}", norm(t))}


def auditar_consistencia(secoes: list[dict[str, Any]], *, issues: dict[str, Any], plano_est: dict[str, Any],
                         pendencias: list[str], matriz: dict[str, Any], tabelas: dict[str, Any] | None = None,
                         pedidos_obrigatorios_ausentes: list[str] | None = None) -> dict[str, Any]:
    achados = [_achado("CONSISTENCY", "PEDIDO_OBRIGATORIO_AUSENTE", BLOQUEIA, "CLAIMS", p, "a skill declara este pedido como obrigatório e a peça não o traz")
               for p in pedidos_obrigatorios_ausentes or []]
    corpo = "\n".join(_texto(s) for s in secoes)
    corpo_tokens = _tokens(corpo)
    pend = norm(" ".join(pendencias or []))
    pedidos = plano_est.get("pedidos") or []
    for t in issues.get("teses") or []:
        alvo = _tokens(t["tese"])
        no_texto = bool(alvo) and len(alvo & corpo_tokens) / len(alvo) >= 0.6
        com_pedido = any(p.get("tese_origem") == t.get("tese_plano_id") for p in pedidos if t.get("tese_plano_id"))
        if t["decisao"] == ts.INCLUIR and t.get("pendente_de_calculo"):
            codigo = "TESE_PENDENTE_DE_CALCULO" if norm(t["tese"])[:40] in pend else "TESE_SUMIU_SEM_REGISTRO"
            achados.append(_achado("CONSISTENCY", codigo, BLOQUEIA, "CLAIMS", t["tese"], "tese incluída cujo pedido depende de parâmetro de cálculo ausente"))
        elif t["decisao"] == ts.INCLUIR and not (no_texto or com_pedido):
            achados.append(_achado("CONSISTENCY", "TESE_SUMIU", BLOQUEIA, "", t["tese"], "tese incluída no issue spotting não aparece na peça"))
        if t["decisao"] == ts.POTENCIAL and norm(t["tese"])[:40] not in pend:
            achados.append(_achado("CONSISTENCY", "TESE_SUMIU_SEM_REGISTRO", BLOQUEIA, "", t["tese"], "tese a confirmar não foi levada às pendências do advogado"))
        if t["decisao"] == ts.INCLUIR and t.get("exige_pericia") and not re.search(r"per[ií]cia|pericial", corpo, re.I):
            achados.append(_achado("CONSISTENCY", "PERICIA_NAO_REQUERIDA", BLOQUEIA, "CLAIMS", t["tese"], "fato que exige perícia sem requerimento de prova pericial"))
    for c in matriz.get("contradicoes") or []:
        if not c.get("resolvida") and norm(c["chave"]) not in pend:
            achados.append(_achado("CONSISTENCY", "CONTRADICAO_NAO_EXPOSTA", BLOQUEIA, "", c["chave"], "contradição entre fontes não levada ao advogado"))
    for cat, d in (tabelas or {}).items():
        if d.get("decisao") == "USE_TABLE" and "|" not in corpo:
            achados.append(_achado("CONSISTENCY", "TABELA_AUSENTE", ALERTA, "", cat, "o plano decidiu USE_TABLE e a peça não traz tabela"))
    return {"auditor": "CONSISTENCY", "achados": achados}


def veredito(*relatorios: dict[str, Any]) -> dict[str, Any]:
    por_auditor = {}
    niveis = dict.fromkeys(NIVEIS, 0)
    for r in relatorios:
        bloqueios = [a for a in r["achados"] if a["severidade"] == BLOQUEIA or nivel(a) == CRITICAL]
        criticos = [a for a in r["achados"] if nivel(a) == CRITICAL]
        for a in r["achados"]:
            niveis[nivel(a)] += 1
        por_auditor[r["auditor"]] = {"status": "FAIL" if bloqueios else "PASS", "bloqueios": len(bloqueios),
                                     "criticos": len(criticos), "alertas": len(r["achados"]) - len(bloqueios)}
    pronta = all(v["status"] == "PASS" for v in por_auditor.values())
    return {"pronta": pronta, "status": "READY" if pronta else "BLOCKED", "auditores": por_auditor,
            "niveis": niveis, "critico": niveis[CRITICAL] > 0}


def criticos(achados: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [a for a in achados if nivel(a) == CRITICAL]
