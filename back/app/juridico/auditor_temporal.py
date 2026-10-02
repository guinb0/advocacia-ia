"""TEMPORAL: nada na peça pode ser posterior à data da petição, e a cronologia tem de ser possível.

- data escrita no texto (numérica, por extenso ou «mês de aaaa») depois da `petition_date`, fora de contexto
  de projeção (prazo, parcelas vincendas, termo final) → bloqueia;
- fato da matriz / dado canônico datado depois da petição → bloqueia (fato futuro tratado como ocorrido);
- autoridade citada julgada, publicada ou com vigência iniciada depois da petição → bloqueia;
- fechamento sem a data da petição, com outra data ou com marcador de modelo («[data por extenso]») → bloqueia;
- cronologia impossível (término antes da admissão, evento antes do nascimento) → bloqueia.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable

from . import canonico, datas
from .autoridades import Autoridade, _data
from .auditores import BLOQUEIA, _achado, _texto

AUDITOR = "TEMPORAL"
#: Data futura legítima: projeção, prazo, parcelas vincendas, termo final de pensão, estabilidade.
_PROJECAO = re.compile(r"at[ée]\b|vincend|futur|projet|projeç|expectativa|termo\s+final|prazo|vencimento|ser[áa]\b|"
                       r"completar[áa]|estabilidade|pr[óo]xim|previs[ãa]o", re.I)


def _contexto(texto: str, inicio: int, largura: int = 80) -> str:
    return texto[max(0, inicio - largura):inicio]


def auditar(
    secoes: list[dict[str, Any]], *, petition_date: date, matriz: dict[str, Any] | None = None,
    canon: dict[str, Any] | None = None, autoridades_citadas: Iterable[Autoridade] = (),
) -> dict[str, Any]:
    achados: list[dict[str, Any]] = []
    alvo_fechamento = datas.por_extenso(petition_date)
    for s in secoes:
        code = str(s.get("code") or "")
        texto = _texto(s)
        for m in datas.PLACEHOLDER.finditer(texto):
            achados.append(_achado(AUDITOR, "DATA_DE_MODELO", BLOQUEIA, code, m.group(0), "marcador de data de modelo de petição no texto"))
        for d in datas.extrair(texto):
            if datas.posterior(d, petition_date) and not _PROJECAO.search(_contexto(texto, d.inicio)):
                achados.append(_achado(AUDITOR, "DATA_POSTERIOR_A_PETICAO", BLOQUEIA, code, d.trecho,
                                       f"data posterior à data da petição ({petition_date.strftime('%d/%m/%Y')}) narrada como já ocorrida"))
        if code == "CLOSING":
            datas_fechamento = datas.extrair(texto)
            if not datas_fechamento:
                achados.append(_achado(AUDITOR, "DATA_DA_PETICAO_AUSENTE", BLOQUEIA, code, "", f"o fechamento não traz a data da petição ({alvo_fechamento})"))
            for d in datas_fechamento:
                if d.valor != petition_date:
                    achados.append(_achado(AUDITOR, "DATA_DA_PETICAO_DIVERGENTE", BLOQUEIA, code, d.trecho,
                                           f"o fechamento deve trazer a data da petição: {alvo_fechamento}"))
    for f in (matriz or {}).get("fatos") or []:
        d = _data(f.get("data")) or (_data(f.get("valor")) if re.search(r"data|admiss|demiss|dispensa|nasc|acidente", str(f.get("chave") or "")) else None)
        if d and d > petition_date:
            achados.append(_achado(AUDITOR, "FATO_FUTURO", BLOQUEIA, "", f"{f.get('id')} {f.get('chave') or f.get('fato', '')[:80]}",
                                   f"fato datado de {d.strftime('%d/%m/%Y')}, depois da data da petição"))
    campos = (canon or {}).get("campos") or {}

    def data_canonica(chave: str) -> date | None:
        v = canonico.valor(canon, chave)
        return date.fromisoformat(v) if v else None

    for chave in ("claimant.birth_date", "employment.start_date", "employment.end_date", "event.accident_date"):
        d = data_canonica(chave)
        if d and d > petition_date:
            achados.append(_achado(AUDITOR, "FATO_FUTURO", BLOQUEIA, "", chave, f"{campos[chave]['rotulo']} {d.strftime('%d/%m/%Y')} é posterior à petição"))
    nasc, adm, fim, evt = (data_canonica(c) for c in ("claimant.birth_date", "employment.start_date", "employment.end_date", "event.accident_date"))
    for antes, depois, codigo, detalhe in (
        (adm, fim, "TERMINO_ANTES_DA_ADMISSAO", "término do contrato anterior à admissão"),
        (nasc, adm, "ADMISSAO_ANTES_DO_NASCIMENTO", "admissão anterior ao nascimento"),
        (nasc, evt, "EVENTO_ANTES_DO_NASCIMENTO", "evento anterior ao nascimento"),
    ):
        if antes and depois and depois < antes:
            achados.append(_achado(AUDITOR, "CRONOLOGIA_IMPOSSIVEL", BLOQUEIA, "", codigo, detalhe))
    for a in autoridades_citadas:
        for rotulo, bruto in (("julgamento/publicação", a.data), ("início de vigência", a.vigencia_inicio)):
            d = _data(bruto)
            if d and d > petition_date:
                achados.append(_achado(AUDITOR, "AUTORIDADE_POSTERIOR_A_PETICAO", BLOQUEIA, "", a.titulo or a.chave,
                                       f"{rotulo} em {d.strftime('%d/%m/%Y')}, depois da data da petição"))
    return {"auditor": AUDITOR, "achados": achados}
