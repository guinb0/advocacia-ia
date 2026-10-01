"""Atualização jurídica por tese: o que mudou recentemente (precedente vinculante, lei nova) sobre cada tese do caso.

Duas fontes, com papéis diferentes:

- ACERVO VERIFICADO (`autoridades_juridicas` com `verificada`, vigente e de efeito vinculante): entra no prompt da
  redação, junto com os critérios que o Acervo marca como superados (para a peça não usá-los).
- PESQUISA EM FONTES OFICIAIS (internet, só sites do Judiciário e de norma oficial): NÃO entra na peça. Vira pendência
  no relatório do advogado e alerta no Acervo Jurídico, até alguém conferir na fonte e cadastrar a autoridade.
  Não grava em `autoridades_juridicas`: lá, autoridade não verificada já passa no Citation Gate.

Nada aqui levanta exceção para quem chama: falha de busca vira `motivo`, e a peça segue como seria sem a etapa.
"""

from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Any, Callable, Iterable

from . import autoridades as aut
from .autoridades import norm

log = logging.getLogger(__name__)

TIPO_ALERTA = "ATUALIZACAO_JURIDICA_CANDIDATA"
#: Tipos de autoridade cuja mudança altera o critério de uma tese.
TIPOS_VINCULANTES = ("controle_concentrado", "tema", "sumula_vinculante", "sumula", "oj")
CONFIANCAS_OFICIAIS = ("OFICIAL", "TRIBUNAL")

NOVA = "NOVA"
AGUARDANDO_VERIFICACAO = "NO_ACERVO_AGUARDANDO_VERIFICACAO"
JA_VERIFICADA = "NO_ACERVO_VERIFICADA"
ACERVO_DIVERGE = "ACERVO_DIVERGE"


def ativa() -> bool:
    return os.getenv("PETICAO_ATUALIZACAO_JURIDICA", "1").strip().lower() not in ("0", "false", "nao", "não", "off")


def max_teses() -> int:
    return max(1, int(os.getenv("PETICAO_ATUALIZACAO_MAX_TESES", "6") or 6))


def janela_meses() -> int:
    return max(1, int(os.getenv("PETICAO_ATUALIZACAO_JANELA_MESES", "24") or 24))


# ------------------------------------------------------------------ teses do caso

def teses_do_plano(plano_est: dict[str, Any] | None, plano: dict[str, Any] | None = None, *, limite: int | None = None) -> list[str]:
    """Títulos das teses (e, sem tese, dos pedidos) sem repetição, na ordem do plano."""
    brutos: list[str] = []
    for fonte in (plano_est or {}, plano or {}):
        for t in fonte.get("teses") or []:
            brutos.append(str(t.get("titulo") or t.get("tese") or t.get("nome") or "") if isinstance(t, dict) else str(t))
    if not brutos:
        for p in (plano_est or {}).get("pedidos") or []:
            brutos.append(str(p.get("tipo") or p.get("objeto") or ""))
    vistas, saida = set(), []
    for b in brutos:
        b = " ".join(b.split())[:200]
        if b and norm(b) not in vistas:
            vistas.add(norm(b))
            saida.append(b)
    return saida[: limite or max_teses()]


# ------------------------------------------------------------------ acervo verificado → prompt

def bloco_verificado(teses: Iterable[str], registro: aut.Registro, data_referencia: date | None, *, k: int = 2) -> str:
    """Precedentes vinculantes verificados e vigentes pertinentes às teses, e os critérios superados a evitar."""
    vigentes: dict[str, aut.Autoridade] = {}
    superadas: dict[str, aut.Autoridade] = {}
    for tese in teses:
        for a, _ in registro.buscar(tese, data_referencia=data_referencia, tipos=TIPOS_VINCULANTES, k=k):
            if a.verificada and a.vigente_em(data_referencia) is True:
                vigentes.setdefault(a.id, a)
        for a, _ in registro.buscar(tese, data_referencia=data_referencia, tipos=TIPOS_VINCULANTES, k=k, incluir_inativas=True):
            if a.vigente_em(data_referencia) is False and (a.superado_por or a.status in ("superado", "cancelado", "revogado")):
                superadas.setdefault(a.id, a)
    if not vigentes and not superadas:
        return ""
    linhas = ["\n\n=== ATUALIZAÇÃO JURÍDICA VERIFICADA (Acervo Jurídico, conferida na fonte oficial) ===",
              "Prevalece sobre a skill e sobre peças antigas. Aplique só à tese a que for pertinente; cite pelo que o texto diz."]
    for a in vigentes.values():
        cab = f"- {a.titulo or a.chave} ({a.tribunal.upper()}{', desde ' + a.vigencia_inicio if a.vigencia_inicio else ''})"
        corpo = " ".join((a.tese or a.texto or "").split())[:900]
        linhas.append(f"{cab}: {corpo}" + (f" Fonte: {a.url}" if a.url else ""))
    if superadas:
        linhas.append("NÃO USE como critério atual (superados ou cancelados):")
        for a in superadas.values():
            sucessora = registro.por_referencia(a.superado_por) if a.superado_por else None
            linhas.append(f"- {a.titulo or a.chave} — {a.status}" + (f"; substituído por {sucessora.titulo or sucessora.chave}" if sucessora else ""))
    return "\n".join(linhas)


# ------------------------------------------------------------------ pesquisa em fontes oficiais

_INSTRUCAO_JSON = (
    "Responda SOMENTE com JSON, sem texto fora dele: "
    '{"achados": [{"referencia": "ex.: ADC 80 do STF | Tema 21 do TST | Súmula 463 do TST | Lei 15.270/2025", '
    '"tribunal": "STF|TST|TRT|legislativo", "data": "AAAA-MM-DD", "efeito": "o que muda para a tese, em uma frase", '
    '"url": "endereço OFICIAL exatamente como veio nos resultados da busca"}]}. '
    'Sem novidade com fonte oficial nos resultados, devolva {"achados": []}. Não invente número nem endereço.'
)


def pergunta(tese: str, data_referencia: date) -> str:
    meses = janela_meses()
    texto = (
        f"Direito do Trabalho no Brasil, data de hoje {data_referencia.isoformat()}. Tese de uma reclamação trabalhista: "
        f"«{tese[:200]}». Houve, nos últimos {meses} meses, decisão vinculante (STF: ADC, ADI, ADPF, repercussão geral; "
        "TST: IRR, IAC, súmula ou OJ nova, alterada ou cancelada) ou lei nova que mude o critério dessa tese? "
        "Use só sites oficiais (stf.jus.br, tst.jus.br, trt*.jus.br, planalto.gov.br). "
    )
    return (texto + _INSTRUCAO_JSON)[:1000]


def _json_da_resposta(texto: str) -> list[dict[str, Any]]:
    texto = texto or ""
    cercado = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", texto, re.S)
    candidatos = [cercado.group(1)] if cercado else []
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio >= 0 and fim > inicio:
        candidatos.append(texto[inicio:fim + 1])
    for bruto in candidatos:
        try:
            dados = json.loads(bruto)
        except (ValueError, TypeError):
            continue
        lista = dados.get("achados") if isinstance(dados, dict) else dados
        if isinstance(lista, list):
            return [a for a in lista if isinstance(a, dict)]
    return []


def _url_limpa(url: str) -> str:
    return str(url or "").strip().rstrip("/").split("#", 1)[0].lower()


def achados_com_fonte_oficial(resultado: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Achados cujo endereço é uma das fontes OFICIAIS que a busca devolveu de fato (o modelo inventa link)."""
    oficiais = {_url_limpa(f.get("url")): f for f in resultado.get("fontes") or [] if f.get("confianca") in CONFIANCAS_OFICIAIS}
    aceitos, descartados = [], 0
    for a in _json_da_resposta(str(resultado.get("resposta") or "")):
        url = _url_limpa(a.get("url"))
        referencia = " ".join(str(a.get("referencia") or "").split())[:160]
        if not referencia or url not in oficiais:
            descartados += 1
            continue
        aceitos.append({"referencia": referencia, "tribunal": str(a.get("tribunal") or "").strip()[:40],
                        "data": str(a.get("data") or "").strip()[:10], "efeito": " ".join(str(a.get("efeito") or "").split())[:400],
                        "url": oficiais[url]["url"], "titulo_fonte": oficiais[url].get("titulo") or ""})
    return aceitos, descartados


def _chave_da_referencia(referencia: str) -> str:
    citacoes = aut.extrair_citacoes(referencia)
    return citacoes[0].chave if citacoes else ""


def classificar(candidato: dict[str, Any], registro: aut.Registro | None, data_referencia: date | None) -> str:
    chave = candidato.get("chave") or ""
    lista = (registro.por_chave.get(chave) if registro and chave else None) or []
    if not lista:
        return NOVA
    if any(a.vigente_em(data_referencia) is False for a in lista) and not any(a.vigente_em(data_referencia) for a in lista):
        return ACERVO_DIVERGE
    return JA_VERIFICADA if any(a.verificada for a in lista) else AGUARDANDO_VERIFICACAO


def pendencia(c: dict[str, Any]) -> str:
    quando = f", {c['data']}" if c.get("data") else ""
    base = f"Atualização jurídica a conferir (tese «{c['tese']}»): {c['referencia']} ({c.get('tribunal') or 'fonte oficial'}{quando})"
    if c.get("efeito"):
        base += f" — {c['efeito']}"
    if c["situacao"] == ACERVO_DIVERGE:
        base += ". O Acervo marca esta autoridade como fora de vigência: confira qual informação está atualizada"
    elif c["situacao"] == AGUARDANDO_VERIFICACAO:
        base += ". Já está no Acervo Jurídico aguardando verificação"
    return f"{base}. Fonte: {c['url']}. Não foi citada na peça; confira na fonte e cadastre no Acervo Jurídico para as próximas."[:700]


def pesquisar(
    teses: list[str], data_referencia: date, *, registro: aut.Registro | None = None,
    pesquisador: Callable[[str], dict[str, Any]] | None = None, max_workers: int = 4, tempo_limite_s: float = 120.0,
) -> dict[str, Any]:
    """Uma busca por tese, em paralelo. Devolve candidatos classificados contra o Acervo e as pendências para o advogado."""
    saida: dict[str, Any] = {"executada": False, "motivo": "", "data_referencia": data_referencia.isoformat(),
                             "teses": [], "candidatos": [], "pendencias": [], "descartados_sem_fonte_oficial": 0}
    if not teses:
        saida["motivo"] = "sem teses no plano"
        return saida
    if pesquisador is None:
        from .. import pesquisa_web
        if not pesquisa_web.configurada():
            saida["motivo"] = "pesquisa na web desligada (sem OPENROUTER_API_KEY)"
            return saida
        pesquisador = pesquisa_web.pesquisar

    def uma(tese: str) -> dict[str, Any]:
        try:
            resultado = pesquisador(pergunta(tese, data_referencia))
        except Exception as erro:  # noqa: BLE001 - a falha de uma tese não derruba as outras
            return {"tese": tese, "falhou": True, "motivo": str(erro)[:200], "achados": [], "descartados": 0}
        achados, descartados = achados_com_fonte_oficial(resultado)
        return {"tese": tese, "falhou": False, "motivo": "", "achados": achados, "descartados": descartados,
                "tem_fonte_oficial": bool(resultado.get("tem_fonte_oficial"))}

    executor = ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(teses))), thread_name_prefix="atualizacao-juridica")
    futuros = [executor.submit(uma, t) for t in teses]
    try:
        for tese, futuro in zip(teses, futuros):
            try:
                saida["teses"].append(futuro.result(timeout=tempo_limite_s))
            except Exception as erro:  # noqa: BLE001 - inclui TimeoutError
                saida["teses"].append({"tese": tese, "falhou": True, "motivo": f"sem resposta: {type(erro).__name__}", "achados": [], "descartados": 0})
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    vistos: set[str] = set()
    for t in saida["teses"]:
        saida["descartados_sem_fonte_oficial"] += t.get("descartados", 0)
        for a in t["achados"]:
            chave = _chave_da_referencia(a["referencia"])
            identidade = chave or norm(a["referencia"])
            if identidade in vistos:
                continue
            vistos.add(identidade)
            c = {**a, "tese": t["tese"], "chave": chave}
            c["situacao"] = classificar(c, registro, data_referencia)
            saida["candidatos"].append(c)
    saida["pendencias"] = [pendencia(c) for c in saida["candidatos"] if c["situacao"] != JA_VERIFICADA]
    saida["executada"] = any(not t["falhou"] for t in saida["teses"])
    if not saida["executada"]:
        saida["motivo"] = "nenhuma busca concluiu: " + "; ".join(sorted({t["motivo"] for t in saida["teses"]}))[:300]
    return saida


def registrar_alertas(candidatos: list[dict[str, Any]], armazenamento: Any, *, agora: datetime) -> int:
    """Um alerta por candidato ainda não verificado no Acervo (o índice único evita repetir alerta aberto)."""
    novos = 0
    for c in candidatos:
        if c.get("situacao") == JA_VERIFICADA:
            continue
        identidade = c.get("chave") or re.sub(r"[^a-z0-9]+", "-", norm(c["referencia"])).strip("-")[:80]
        alerta = {
            "tipo": TIPO_ALERTA, "severidade": "alta" if c.get("situacao") == ACERVO_DIVERGE else "media",
            "authority_id": f"candidato:{identidade}",
            "titulo": f"Pesquisa da petição encontrou: {c['referencia']}"[:300],
            "detalhe": (f"Tese «{c['tese']}». {c.get('efeito') or ''} Fonte: {c['url']}. "
                        "Confira na fonte oficial e, se for o caso, cadastre pela importação de jurisprudência.")[:1000],
            "dados": {k: c.get(k) for k in ("referencia", "tribunal", "data", "efeito", "url", "tese", "chave", "situacao")},
        }
        try:
            novos += bool(armazenamento.alertar(alerta, agora=agora))
        except Exception as erro:  # noqa: BLE001 - sem tabela de alertas (migration 011 não aplicada) a peça segue
            log.warning("atualização jurídica: alerta não gravado: %s", erro)
            break
    return novos
