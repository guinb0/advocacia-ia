"""Recuperação por TESE — o que buscar, em cada base, para cada ponto que a peça vai sustentar.

O PROBLEMA

Os três canais de recuperação (julgados, legislação, peças do escritório) eram consultados com
o mesmo texto: o dossiê inteiro do caso (`contexto[:12000]`) — entrevista, OCR de contracheque,
CPF, endereço. Um vetor desse texto é a "média" do caso, e a média de um processo de assalto
em agência dos Correios é parecida com a de qualquer acidente de trabalho. Medido no acervo:
a consulta do dossiê devolvia 12 trechos de petições genéricas de acidente/doença ocupacional,
nenhuma sobre assalto, embora o acervo tenha uma sobre o tema e 73 decisões que falam em assalto.

A CORREÇÃO

O planejamento (`_outline_juridico`) já produz as TESES do caso com os fatos e as provas que as
sustentam. Cada tese vira uma consulta curta e específica; cada base é consultada por tese; os
resultados são unidos, deduplicados e cortados por relevância. Nada aqui conhece direito
material: as teses vêm do plano, o assunto vem da tabela da skill.

PROVENIÊNCIA

Cada item recuperado vira um registro (`Proveniencia`) com id, score, a(s) tese(s) que o
trouxeram e os caracteres enviados ao modelo. Depois da redação, `medir_influencia` diz quais
itens deixaram marca no texto — separa "a busca executou" de "a busca contribuiu".
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any

from . import jurimetria_caso, rag
from .pesquisa_jurisprudencial import StatusVerificacao

log = logging.getLogger("recuperacao_por_tese")

#: Consultas em paralelo: o pgvector é remoto e cada consulta espera rede.
_PARALELISMO = 4
#: Teses a consultar (a consulta global entra além delas).
MAXIMO_DE_TESES = 10



@dataclass
class Proveniencia:
    canal: str                       # precedente | legislacao | peca
    id: str                          # processo / identificador / arquivo
    titulo: str = ""
    score: float = 0.0
    teses: list[str] = field(default_factory=list)
    chars_enviados: int = 0
    natureza: str = ""               # ex.: "acórdão do TRT", "sentença de 1º grau"
    contribuiu: bool | None = None   # preenchido por `medir_influencia`
    secoes: list[str] = field(default_factory=list)

    def como_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["score"] = round(self.score, 4)
        return d


def _resumo(texto: Any, limite: int) -> str:
    return " ".join(str(texto or "").split())[:limite]


def consultas_do_plano(plano: dict[str, Any] | None, contexto: str, categoria: str) -> list[dict[str, str]]:
    """Uma consulta GLOBAL (o caso em uma frase) e uma por tese do plano.

    Sem plano (o planejamento falhou) devolve só a global, feita do início do contexto — a
    recuperação degrada para o comportamento antigo, não para o vazio.
    """
    plano = plano or {}
    teses = [t for t in (plano.get("teses") or []) if isinstance(t, dict) and t.get("tese")]
    fatos = [
        _resumo(c.get("fato"), 160)
        for c in (plano.get("cronologia") or [])[:4]
        if isinstance(c, dict) and c.get("fato")
    ]
    nomes = "; ".join(_resumo(t["tese"], 80) for t in teses[:MAXIMO_DE_TESES])
    # ÂNCORA: o evento e o réu do caso entram em TODA consulta. Sem ela a tese sai abstrata
    # ("responsabilidade objetiva por atividade de risco") e o vetor traz qualquer acidente de
    # trabalho; com ela, traz o julgado sobre O MESMO fato e o MESMO réu.
    ancora = _resumo(f"{categoria}. {fatos[0] if fatos else ''}", 200)
    global_ = f"{ancora}. Teses: {nomes}".strip(". ")
    consultas = [{"tese": "(visão geral do caso)", "consulta": global_[:700] or contexto[:700]}]
    for t in teses[:MAXIMO_DE_TESES]:
        sustentam = "; ".join(_resumo(f, 120) for f in (t.get("fatos_que_sustentam") or [])[:2])
        consulta = f"{ancora}. {_resumo(t['tese'], 200)}. {sustentam}".strip()
        consultas.append({"tese": _resumo(t["tese"], 90), "consulta": consulta[:700]})
    blob = f"{categoria}\n{contexto[:4000]}"
    if re.search(r"assalto|roubo|correios|\bect\b", blob, re.IGNORECASE):
        consultas.append({
            "tese": "assalto em agência dos Correios",
            "consulta": "TST roubo ou assalto em agência dos Correios ECT atendente ou caixa dano moral responsabilidade",
        })
    return consultas


def _em_paralelo(funcao, consultas: list[dict[str, str]]) -> list[tuple[dict[str, str], Any, Exception | None]]:
    def executar(c: dict[str, str]):
        try:
            return c, funcao(c["consulta"]), None
        except Exception as erro:  # noqa: BLE001 - uma consulta que falha não derruba as outras
            return c, None, erro

    with ThreadPoolExecutor(max_workers=_PARALELISMO) as pool:
        return list(pool.map(executar, consultas))


#: Expediente (notificação, pauta, edital, despacho de mero andamento) não é precedente.
_EXPEDIENTE = re.compile(r"notifica|distribui|pauta|edital|despacho|intima|certid", re.IGNORECASE)


def apenas_verificados(achados: list[Any] | None) -> list[Any]:
    """Filtro único para qualquer caminho que possa alimentar a redação."""
    return [x for x in (achados or [])
            if str(x.metadados.get("status_verificacao") or "UNVERIFIED").upper()
            == StatusVerificacao.VERIFIED.value]


def _natureza(metadados: dict[str, Any]) -> str:
    """Grau e força do julgado, para o modelo (e o advogado) não tratarem tudo como igual."""
    tipo = str(metadados.get("tipo_documento") or "").casefold()
    origem = str(metadados.get("origem") or "")
    tribunal = str(metadados.get("tribunal") or ("TRT8" if origem == "trt8_juris" else origem)).upper()
    if "acórdão" in tipo or "acordao" in tipo:
        return f"acórdão ({tribunal or 'tribunal'}) — persuasivo"
    if "sentença" in tipo or "sentenca" in tipo:
        return f"sentença de 1º grau ({tribunal or 'TRT'}) — persuasivo, só mostra como a região decide"
    if "despacho" in tipo:
        return f"despacho/decisão monocrática ({tribunal or 'tribunal'}) — fraco como precedente"
    return f"decisão ({tribunal or 'tribunal'})"


def precedentes(
    consultas: list[dict[str, str]], contexto: str, *, uf: str = "", por_tese: int = 4, total: int = 18
) -> tuple[list[Any], list[Proveniencia], list[str]]:
    """Julgados por tese. Devolve (trechos, proveniência, erros)."""
    def buscar(consulta: str):
        similares, _jur, _uf = jurimetria_caso.buscar_focada(
            consulta, uf=uf, texto_para_uf=contexto
        )
        return similares

    melhores: dict[str, tuple[Any, Proveniencia]] = {}
    erros: list[str] = []
    for c, achados, erro in _em_paralelo(buscar, consultas):
        if erro is not None:
            erros.append(f"{c['tese']}: {type(erro).__name__}: {str(erro)[:120]}")
            continue
        # Legado sem selo não é precedente confirmado. Só o fluxo de validação
        # externa pode promover o registro a VERIFIED; snippet ou embedding nunca.
        verificados = apenas_verificados(achados)
        uteis = [x for x in verificados if not _EXPEDIENTE.search(str(x.metadados.get("tipo_documento") or ""))]
        for trecho in uteis[:por_tese]:
            ref = trecho.referencia()
            chave = str(ref.get("processo") or ref.get("identificador") or trecho.identificador)
            atual = melhores.get(chave)
            if atual is None:
                melhores[chave] = (trecho, Proveniencia(
                    "precedente", chave, trecho.titulo or "", float(trecho.similaridade),
                    [c["tese"]], min(len(trecho.texto), 1800), _natureza(trecho.metadados),
                ))
            else:
                if c["tese"] not in atual[1].teses:
                    atual[1].teses.append(c["tese"])
                if float(trecho.similaridade) > atual[1].score:
                    melhores[chave] = (trecho, atual[1])
                    atual[1].score = float(trecho.similaridade)
    # Quem serve a mais de uma tese sobe: é o julgado que a peça mais vai usar.
    ordenados = sorted(melhores.values(), key=lambda p: (len(p[1].teses), p[1].score), reverse=True)[:total]
    return [t for t, _ in ordenados], [p for _, p in ordenados], erros


def legislacao(
    consultas: list[dict[str, str]], *, por_tese: int = 3, total: int = 14
) -> tuple[list[Any], list[Proveniencia], list[str]]:
    melhores: dict[str, tuple[Any, Proveniencia]] = {}
    erros: list[str] = []
    for c, achados, erro in _em_paralelo(lambda q: rag.buscar_legislacao(q, limite=por_tese), consultas):
        if erro is not None:
            erros.append(f"{c['tese']}: {type(erro).__name__}: {str(erro)[:120]}")
            continue
        for trecho in achados or []:
            chave = f"{trecho.identificador}|{_resumo(trecho.texto, 60)}"
            if chave not in melhores:
                melhores[chave] = (trecho, Proveniencia(
                    "legislacao", str(trecho.identificador or trecho.titulo), trecho.titulo or "",
                    float(trecho.similaridade), [c["tese"]], min(len(trecho.texto), 1500),
                ))
            elif c["tese"] not in melhores[chave][1].teses:
                melhores[chave][1].teses.append(c["tese"])
    ordenados = sorted(melhores.values(), key=lambda p: (len(p[1].teses), p[1].score), reverse=True)[:total]
    return [t for t, _ in ordenados], [p for _, p in ordenados], erros


def pecas(
    consultas: list[dict[str, str]], assuntos: list[str], *, por_tese: int = 3, total: int = 10
) -> tuple[list[dict[str, Any]], list[Proveniencia], list[str]]:
    """Trechos de petições do escritório por tese (memória argumentativa — nunca fonte de fato)."""
    melhores: dict[str, tuple[dict[str, Any], Proveniencia]] = {}
    erros: list[str] = []
    for c, achados, erro in _em_paralelo(
        lambda q: rag.buscar_pecas_conteudisticas(q, limite=por_tese, assunto=assuntos), consultas
    ):
        if erro is not None:
            erros.append(f"{c['tese']}: {type(erro).__name__}: {str(erro)[:120]}")
            continue
        for trecho in achados or []:
            chave = f"{trecho.get('peca_id') or trecho['arquivo']}|{_resumo(trecho['texto'], 80)}"
            if chave not in melhores:
                melhores[chave] = (trecho, Proveniencia(
                    "peca", str(trecho["arquivo"]), str(trecho["categoria"]),
                    float(trecho["similaridade"]), [c["tese"]], min(len(trecho["texto"]), 1800),
                    "mesmo assunto" if trecho.get("mesmo_assunto") else "outro assunto",
                ))
            elif c["tese"] not in melhores[chave][1].teses:
                melhores[chave][1].teses.append(c["tese"])
    ordenados = sorted(
        melhores.values(),
        key=lambda p: (bool(p[0].get("mesmo_assunto")), len(p[1].teses), p[1].score),
        reverse=True,
    )[:total]
    return [t for t, _ in ordenados], [p for _, p in ordenados], erros


# ------------------------------------------------------------------ influência


def _ngramas(texto: str, n: int = 7) -> set[tuple[str, ...]]:
    palavras = re.findall(r"\w+", texto.lower())
    return {tuple(palavras[i : i + n]) for i in range(max(0, len(palavras) - n + 1))}


def medir_influencia(
    itens: list[tuple[Proveniencia, str]], secoes: list[dict[str, Any]]
) -> None:
    """Marca em cada item se deixou rastro no texto e em quais seções.

    Julgado e lei: o identificador (número do processo, "art. 927") aparece na seção.
    Peça do acervo: compartilha sequências de 7 palavras com a seção — sinal de que o argumento
    foi reaproveitado (ou, acima do limite de `copia_suspeita`, copiado).
    """
    for prov, texto in itens:
        alvo = re.sub(r"\D", "", prov.id) if prov.canal == "precedente" else ""
        gramas = _ngramas(texto) if prov.canal != "precedente" else set()
        for secao in secoes:
            conteudo = str(secao.get("content") or "")
            achou = False
            if alvo and len(alvo) >= 12 and alvo in re.sub(r"\D", "", conteudo):
                achou = True
            elif prov.canal == "legislacao":
                m = re.search(r"art\w*\.?\s*(\d+)", prov.titulo + " " + prov.id, re.IGNORECASE)
                achou = bool(m and re.search(rf"art\w*\.?\s*{m.group(1)}\b", conteudo, re.IGNORECASE))
            elif gramas:
                achou = len(gramas & _ngramas(conteudo)) >= 2
            if achou:
                prov.secoes.append(str(secao.get("code") or ""))
        prov.contribuiu = bool(prov.secoes)
