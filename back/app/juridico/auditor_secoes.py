"""CROSS_SECTION_AUDITOR: o mesmo dado crítico tem de ser igual em toda a peça.

Impressões digitais saem da fonte única (dados canônicos, pedidos estruturados, cálculos): idade, tempo de
serviço, datas por papel (admissão, término, evento, nascimento), percentual de incapacidade, CPF/CNPJ/CEP por
parte, valor de cada pedido e de cada cálculo. A varredura cobre fatos, direito, tabelas, memória, pedidos e
valor; qualquer ocorrência divergente bloqueia. O auditor CALCULATION continua rodando (valor da causa, pedido ×
cálculo, dupla contagem) e entra neste mesmo veredito.
"""

from __future__ import annotations

import re
from typing import Any

from . import calculos as calc
from . import canonico, datas, tabelas
from .auditores import ALERTA, BLOQUEIA, _achado, _reais_do_texto, _texto
from .autoridades import _data, norm

AUDITOR = "CROSS_SECTION"
_CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
_CNPJ = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")
_CEP = re.compile(r"\b\d{5}-\d{3}\b")
_IDADE = re.compile(r"(?:contava|com|possu[íi]a|tinha|tem|idade\s+de)\s+(\d{1,3})\s+anos(?:\s+de\s+idade)?(?!\s+de\s+(?:servi|contrato|empresa|casa|trabalho|v[íi]nculo))|"
                    r"(\d{1,3})\s+anos\s+de\s+idade", re.I)
_TEMPO = re.compile(r"(\d{1,2})\s+anos?(?:\s+e\s+(\d{1,2})\s+m[eê]s(?:es)?)?\s+de\s+(?:servi[çc]os?|contrato|v[íi]nculo|trabalho|empresa|casa)", re.I)
_PERCENTUAL = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d+)?)\s*%")
_REFLEXO = re.compile(r"reflex", re.I)
_INCAPACIDADE = re.compile(r"incapacidad|redu[çc][ãa]o\s+(?:da\s+)?capacidade|perda\s+(?:funcional|da\s+capacidade)|d[ée]ficit\s+funcional", re.I)
_PAPEIS_DE_DATA = (
    ("employment.start_date", re.compile(r"admiss|admitid|contratad", re.I)),
    ("employment.end_date", re.compile(r"dispens|demiss|desligad|rescis|t[ée]rmino\s+do\s+contrato|extin[çc][ãa]o\s+do\s+contrato", re.I)),
    ("claimant.birth_date", re.compile(r"nascid|nascimento", re.I)),
    ("event.accident_date", re.compile(r"acidente|sinistro|assalto|ocorrid[oa]\s+em|evento\s+danoso", re.I)),
)
_ESCRITORIO = re.compile(r"escrit[óo]rio|advogad|procurador|OAB", re.I)
_LOCAL_DE_TRABALHO = re.compile(r"laborava|prestava\s+(?:seus\s+)?servi[çc]os|local\s+de\s+trabalho|lotad[oa]|trabalhava\s+(?:na|no|em)", re.I)
_PARTE_AUTORA = re.compile(r"reclamante|\bautora?\b|residente|domiciliad", re.I)
_PARTE_RE = re.compile(r"reclamada|\br[ée]\b|empresa|empregadora|sediada|com\s+sede", re.I)


def _frases(texto: str) -> list[tuple[int, str]]:
    saida, pos = [], 0
    for parte in re.split(r"((?<=[.;!?])\s+|\n+)", texto):
        if parte and not re.fullmatch(r"\s+", parte):
            saida.append((pos, parte))
        pos += len(parte)
    return saida


def _area(code: str, frase: str) -> str:
    if frase.lstrip().startswith("|"):
        return "tabelas"
    return {"FACTS": "fatos", "CLAIMS": "pedidos", "VALUE": "valor"}.get(code, "direito")


def _blocos_de_tabela(texto: str) -> list[str]:
    blocos, atual = [], []
    for linha in texto.split("\n"):
        if linha.strip().startswith("|"):
            atual.append(linha.strip())
        elif atual:
            blocos.append("\n".join(atual))
            atual = []
    if atual:
        blocos.append("\n".join(atual))
    return blocos


def pressupostos_dos_pedidos(secoes: list[dict[str, Any]], canon: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Fatos × pedidos: pedido rescisório sem término do contrato nos dados canônicos e sem rescisão indireta na peça.
    Pedido direto bloqueia; reflexo em verba rescisória (aviso prévio etc.) é alerta."""
    if canon is None or canonico.termino_do_contrato(canon):
        return []
    corpo = "\n".join(_texto(s) for s in secoes)
    if canonico.pede_rescisao_indireta([{"tese": corpo}]):
        return []
    achados = []
    for s in secoes:
        if str(s.get("code") or "") != "CLAIMS":
            continue
        for _, frase in _frases(_texto(s)):
            if frase.lstrip().startswith("|"):
                continue
            for m in canonico.PEDIDO_RESCISORIO.finditer(frase):
                reflexo = bool(_REFLEXO.search(frase[max(0, m.start() - 160):m.start()]))
                achados.append(_achado(AUDITOR, "REFLEXO_SEM_PRESSUPOSTO_FATICO" if reflexo else "PEDIDO_SEM_PRESSUPOSTO_FATICO",
                                       ALERTA if reflexo else BLOQUEIA, "CLAIMS", frase.strip()[:220],
                                       f"«{m[0]}» pressupõe contrato encerrado; não há término do contrato nos dados do caso (vínculo ativo?) "
                                       "nem pedido de rescisão indireta"))
                break
    return achados


def auditar(
    secoes: list[dict[str, Any]], *, canon: dict[str, Any] | None, pedidos: list[dict[str, Any]], calculos: list[dict[str, Any]],
    matriz: dict[str, Any] | None = None, texto_das_fontes: str = "",
) -> dict[str, Any]:
    achados: list[dict[str, Any]] = []
    impressoes: dict[str, dict[str, Any]] = {}

    def registrar(chave: str, esperado: str, code: str, frase: str, ok: bool) -> None:
        imp = impressoes.setdefault(chave, {"chave": chave, "esperado": esperado, "ocorrencias": []})
        imp["ocorrencias"].append({"secao": code, "area": _area(code, frase), "trecho": frase.strip()[:160], "ok": ok})

    v = lambda chave: canonico.valor(canon, chave)  # noqa: E731
    idades = {k: v(k) for k in ("claimant.age_at_event", "claimant.age_at_petition") if v(k) is not None}
    meses = v("employment.tenure_months")
    percentual = v("disability_percentage")
    datas_canonicas = {k: _data(v(k)) for k, _ in _PAPEIS_DE_DATA if v(k)}
    todas_as_datas = set(datas_canonicas.values()) | {_data(f.get("data")) for f in (matriz or {}).get("fatos") or [] if _data(f.get("data"))} \
        | {_data(f.get("valor")) for f in (matriz or {}).get("fatos") or [] if _data(f.get("valor"))}
    docs_conhecidos: dict[str, set[str]] = {"cpf": set(), "cnpj": set(), "cep": set()}
    for f in (matriz or {}).get("fatos") or []:
        if canonico.certeza_do_fato(f) in canonico.UTILIZAVEIS:
            for tipo, rx in (("cpf", _CPF), ("cnpj", _CNPJ), ("cep", _CEP)):
                docs_conhecidos[tipo] |= set(rx.findall(str(f.get("valor") or "")))
    cep_autor, cep_re = v("claimant.cep"), v("defendant.cep")
    permitidos: set[float] = set()
    for p in pedidos or []:
        n = calc.valor_numerico(p.get("valor"))
        if n is not None:
            permitidos.add(round(float(n), 2))
    for c in calculos or []:
        if not c.get("erro") and str(c.get("unidade") or "BRL") == "BRL":
            permitidos.add(round(float(c.get("valor") or 0), 2))
            for linha in c.get("memoria") or []:
                permitidos |= set(_reais_do_texto(linha))
    for chave in ("current_salary", "compensation_base", "pension_value"):
        if v(chave):
            permitidos.add(round(float(v(chave)), 2))
    for f in (matriz or {}).get("fatos") or []:
        if canonico.certeza_do_fato(f) in canonico.UTILIZAVEIS:
            permitidos |= set(_reais_do_texto(str(f.get("valor") or "")))
    soma = calc.valor_da_causa(pedidos or [])["valor"]
    if soma:
        permitidos.add(round(soma, 2))

    for c in calculos or []:
        for f in (c.get("fontes") or {}).values():
            if f.get("tipo") == "dinheiro" and f.get("valor") not in (None, ""):
                permitidos.add(round(float(f["valor"]), 2))
    achados += pressupostos_dos_pedidos(secoes, canon)

    tabelas_do_codigo = {tabelas.construir(cat, matriz=matriz or {}, canon=canon, calculos=calculos) for cat in tabelas.CATEGORIAS}
    tabelas_do_codigo = {re.sub(r"\s+", " ", t).strip() for t in tabelas_do_codigo if t}

    for s in secoes:
        code, texto = str(s.get("code") or ""), _texto(s)
        for bloco in _blocos_de_tabela(texto):
            if re.sub(r"\s+", " ", bloco).strip() not in tabelas_do_codigo:
                achados.append(_achado(AUDITOR, "TABELA_FORA_DA_FONTE_UNICA", BLOQUEIA, code, bloco.split("\n")[0][:160],
                                       "tabela digitada na redação; tabela só pelo marcador [[TABELA:categoria]], montada com os dados canônicos"))
            for valor in _reais_do_texto(bloco):
                if valor not in permitidos:
                    achados.append(_achado(AUDITOR, "TABELA_DIVERGENTE", BLOQUEIA, code, calc.brl(valor), "valor na tabela sem correspondência em pedido, cálculo ou dado canônico"))
        for _, frase in _frases(texto):
            if idades:
                for m in _IDADE.finditer(frase):
                    n = int(m[1] or m[2])
                    ok = n in idades.values()
                    registrar("claimant.age", " ou ".join(f"{x} anos" for x in sorted(set(idades.values()))), code, frase, ok)
                    if not ok:
                        achados.append(_achado(AUDITOR, "IDADE_DIVERGENTE", BLOQUEIA, code, frase[:220],
                                               f"{n} anos × idade calculada: " + ", ".join(f"{canonico.POR_CHAVE[k].rotulo} = {x}" for k, x in idades.items())))
            if meses is not None:
                for m in _TEMPO.finditer(frase):
                    anos, extra = int(m[1]), m[2]
                    ok = (anos * 12 + int(extra) == meses) if extra else anos == meses // 12
                    registrar("employment.tenure_months", canonico.exibir(canon["campos"]["employment.tenure_months"]), code, frase, ok)
                    if not ok:
                        achados.append(_achado(AUDITOR, "TEMPO_DE_SERVICO_DIVERGENTE", BLOQUEIA, code, frase[:220],
                                               f"tempo calculado: {canonico.exibir(canon['campos']['employment.tenure_months'])}"))
            if percentual is not None and _INCAPACIDADE.search(frase):
                for m in _PERCENTUAL.finditer(frase):
                    n = float(m[1].replace(",", ".")) / 100
                    ok = abs(n - float(percentual)) < 1e-6
                    registrar("disability_percentage", f"{float(percentual) * 100:g}%", code, frase, ok)
                    if not ok:
                        achados.append(_achado(AUDITOR, "PERCENTUAL_DIVERGENTE", BLOQUEIA, code, frase[:220], f"percentual canônico: {float(percentual) * 100:g}%"))
            if datas_canonicas:
                for lida in datas.extrair(frase):
                    if lida.precisao != "dia":
                        continue
                    d = lida.valor
                    contexto = frase[max(0, lida.inicio - 70):lida.inicio]
                    papeis = []
                    for k, rx in _PAPEIS_DE_DATA:
                        ultimos = list(rx.finditer(contexto)) if k in datas_canonicas else []
                        if ultimos:
                            papeis.append((ultimos[-1].start(), k))
                    if not papeis:
                        continue
                    papel = max(papeis)[1]
                    ok = d == datas_canonicas[papel] or (d in todas_as_datas and d not in datas_canonicas.values())
                    registrar(papel, datas_canonicas[papel].strftime("%d/%m/%Y"), code, frase, ok)
                    if not ok:
                        achados.append(_achado(AUDITOR, "DATA_DIVERGENTE", BLOQUEIA, code, frase[:220],
                                               f"{canonico.POR_CHAVE[papel].rotulo}: {datas_canonicas[papel].strftime('%d/%m/%Y')}"))
            if _ESCRITORIO.search(frase):
                continue
            for tipo, rx in (("cpf", _CPF), ("cnpj", _CNPJ), ("cep", _CEP)):
                for doc in rx.findall(frase):
                    canonicos = {x for x in (v("claimant.cpf"), v("defendant.cnpj"), cep_autor, cep_re) if x}
                    conhecido = doc in docs_conhecidos[tipo] or any(re.sub(r"\D", "", doc) == re.sub(r"\D", "", x) for x in canonicos)
                    registrar(f"documento.{tipo}", "documento de uma das partes", code, frase, conhecido)
                    if not conhecido:
                        achados.append(_achado(AUDITOR, "DOCUMENTO_DE_OUTRA_PARTE_OU_CASO", BLOQUEIA, code, doc,
                                               f"{tipo.upper()} sem fato correspondente na matriz deste caso"
                                               + (" (consta das fontes, mas não está atribuído a nenhuma parte)" if doc in (texto_das_fontes or "") else "")))
                    if tipo == "cep" and cep_autor and cep_re and cep_autor != cep_re:
                        if doc == cep_autor and _PARTE_RE.search(frase) and not _PARTE_AUTORA.search(frase):
                            achados.append(_achado(AUDITOR, "CEP_DE_OUTRA_PARTE", BLOQUEIA, code, frase[:220], "CEP do autor atribuído à ré"))
                        if doc == cep_re and _PARTE_AUTORA.search(frase) and not _PARTE_RE.search(frase):
                            achados.append(_achado(AUDITOR, "CEP_DE_OUTRA_PARTE", BLOQUEIA, code, frase[:220], "CEP da ré atribuído ao autor"))
            if cep_autor and _LOCAL_DE_TRABALHO.search(frase) and cep_autor in frase and not v("employment.workplace"):
                achados.append(_achado(AUDITOR, "LOCAL_DE_TRABALHO_INFERIDO_DA_RESIDENCIA", BLOQUEIA, code, frase[:220],
                                       "local de trabalho afirmado com o endereço residencial do autor, sem fato que o confirme"))
        if code in ("CLAIMS", "VALUE"):
            continue
        for p in pedidos or []:
            alvo = calc.valor_numerico(p.get("valor"))
            if alvo is None:
                continue
            tokens = {t for t in re.findall(r"[a-z]{5,}", norm(p.get("title") or p.get("tipo") or p.get("objeto") or ""))} - {"pagamento", "condenacao", "reclamada"}
            if not tokens:
                continue
            for _, frase in _frases(texto):
                comuns = tokens & set(re.findall(r"[a-z]{5,}", norm(frase)))
                if len(comuns) < min(2, len(tokens)):
                    continue
                for valor in _reais_do_texto(frase):
                    ok = abs(valor - float(alvo)) <= 0.01 or valor in permitidos
                    registrar(f"pedido.{p.get('id')}", calc.brl(alvo), code, frase, ok)
                    if not ok:
                        achados.append(_achado(AUDITOR, "VALOR_DIVERGENTE_ENTRE_SECOES", BLOQUEIA, code, frase[:220],
                                               f"{p.get('title') or p.get('tipo')}: pedido {calc.brl(alvo)} × {calc.brl(valor)} no texto"))
    vistos, unicos = set(), []
    for a in achados:
        k = (a["codigo"], a["secao"], a["trecho"])
        if k not in vistos:
            vistos.add(k)
            unicos.append(a)
    return {"auditor": AUDITOR, "achados": unicos, "impressoes": list(impressoes.values())}
