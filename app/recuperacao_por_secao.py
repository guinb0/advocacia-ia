"""Recuperação POR TÓPICO da peça, reranking híbrido, densidade do acervo e telemetria.

O acervo de peças do escritório (803 peças, 9 958 trechos de ~1,5 mil caracteres, embeddings
`gemini-embedding-001` de 1 536 dimensões, todos indexados) só ajuda a redação se for consultado
CONFORME cada argumento é construído. Uma busca única para a petição inteira devolve a "média" do
caso; aqui cada tópico (ex.: "Da responsabilidade objetiva", "Do dano moral") tem as próprias
consultas, e o que volta passa por um reranking antes de entrar no contexto daquele tópico.

FLUXO (por tópico)
    caso + título + texto atual do tópico + tese do plano
      → 2–3 consultas → busca vetorial (40 candidatos, todas as peças de mérito)
      → reranking híbrido (vetor + termos + assunto + subteses + tipo)
      → diversidade (≥ 3 peças distintas, ≤ 2 trechos por peça)
      → material do tópico (+ julgados e legislação buscados para o MESMO tópico)

SEPARAÇÃO DE FONTES: as peças do acervo entram como MEMÓRIA ARGUMENTATIVA E DE ESTILO. Fato do
caso vem dos documentos; autoridade jurídica vem dos blocos de julgados/legislação/skill.

DENSIDADE: as medidas de estilo (palavras por parágrafo, citações por mil palavras) vêm das
petições iniciais reais do mesmo assunto — são SINAL para o revisor, não limite rígido.
"""

from __future__ import annotations

import logging
import re
import statistics
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from . import rag, recuperacao_por_tese

log = logging.getLogger("recuperacao_por_secao")

CANDIDATOS_POR_CONSULTA = 40
EXEMPLOS_POR_TOPICO = 6
MAXIMO_POR_PECA = 2
MINIMO_DE_PECAS_DISTINTAS = 3

_STOP = frozenset(
    "sobre entre quando sendo desde ainda depois antes durante contra pelos pelas essa esse esta este seus suas partir "
    "para pela pelo como mais menos tambem assim porque portanto contudo entao onde qual quais cujo cuja dessa desse "
    "deste desta daquele daquela mesmo mesma reclamante reclamada reclamado autor autora".split()
)


def _norm(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def _termos(texto: str) -> list[str]:
    vistos: dict[str, None] = {}
    for p in re.findall(r"[a-z0-9]{5,}", _norm(texto)):
        if p not in _STOP:
            vistos.setdefault(p, None)
    return list(vistos)


# ------------------------------------------------------------------ tópicos

_RE_CABECALHO = re.compile(r"^(#{2,3})\s+(.*\S)\s*$")
#: Subtítulo que o redator escreveu sem `#`: "V.1. Da Prescrição", "a) Da competência", "**Da prova**".
_RE_SUBTITULO_SOLTO = re.compile(r"^\s*(?:\*\*)?(?:[IVXLC]+\.\d+[.\-–—)]?|[a-z]\)|\d+\.\d+[.)]?)\s+\S.{2,90}?(?:\*\*)?\s*$")


def dividir_em_topicos(conteudo: str) -> list[dict[str, str]]:
    """Blocos que começam num cabeçalho `##`/`###` (subcapítulo). Sem cabeçalhos: um bloco só."""
    linhas = conteudo.split("\n")
    topicos: list[dict[str, str]] = []
    atual: dict[str, Any] = {"titulo": "", "cabecalho": "", "linhas": []}
    for linha in linhas:
        m = _RE_CABECALHO.match(linha)
        solto = None if m or len(linha) > 100 or linha.rstrip().endswith((".", ";", ":")) and not re.match(r"^\s*[IVXLC]+\.\d+\.", linha) else _RE_SUBTITULO_SOLTO.match(linha)
        if m:
            topicos.append(atual)
            atual = {"titulo": m.group(2), "cabecalho": linha, "linhas": []}
        elif solto:
            topicos.append(atual)
            atual = {"titulo": linha.strip().strip("*"), "cabecalho": linha, "linhas": []}
        else:
            atual["linhas"].append(linha)
    topicos.append(atual)
    return [
        {"titulo": t["titulo"], "cabecalho": t["cabecalho"], "corpo": "\n".join(t["linhas"]).strip()}
        for t in topicos
        if t["titulo"] or "\n".join(t["linhas"]).strip()
    ]


def remontar(topicos: list[dict[str, str]]) -> str:
    partes = []
    for t in topicos:
        if t["cabecalho"]:
            partes.append(t["cabecalho"])
        if t["corpo"]:
            partes.append(t["corpo"])
    return "\n\n".join(partes)


# ------------------------------------------------------------------ métricas de densidade

def paragrafos(texto: str) -> list[str]:
    """Parágrafos de CORPO: sem títulos, blocos `:::` e citações `>` (esses têm outro ritmo)."""
    saida = []
    for bloco in re.split(r"\n\s*\n", texto):
        b = bloco.strip()
        if not b or b.startswith(("#", ">", ":::", "|")):
            continue
        saida.append(re.sub(r"\s+", " ", b))
    return saida


def metricas(texto: str) -> dict[str, Any]:
    ps = paragrafos(texto)
    ws = [len(p.split()) for p in ps]
    corpo = [w for w in ws if w >= 8]
    palavras = sum(ws)
    return {
        "paragrafos": len(ws), "palavras": palavras,
        "mediana": statistics.median(corpo) if corpo else 0,
        "fragmentacao": round(sum(1 for w in corpo if w < 25) / len(corpo), 2) if corpo else 0.0,
        "artigos_por_mil": round(len(re.findall(r"\bart(?:igo)?s?\.?\s*\d", texto, re.IGNORECASE)) / max(palavras, 1) * 1000, 1),
        "referencias_a_documentos": len(re.findall(r"\bDocumento\s+\d", texto)),
    }


_CACHE_DENSIDADE: dict[tuple[str, ...], dict[str, Any]] = {}


def sinal_de_estilo(assuntos: list[str]) -> dict[str, Any]:
    """Densidade das petições INICIAIS reais do mesmo assunto (fallback: todas as iniciais)."""
    chave = tuple(sorted(assuntos))
    if chave in _CACHE_DENSIDADE:
        return _CACHE_DENSIDADE[chave]
    sinal: dict[str, Any] = {"disponivel": False}
    try:
        for filtro, params in (("AND metadados->>'assunto' = ANY(%s)", (list(assuntos),)), ("", ())):
            linhas = rag._consultar_pgvector(  # noqa: SLF001 - mesma infraestrutura de consulta
                f"SELECT texto_integral FROM pecas_conteudo WHERE metadados->>'tipo_peca'='peticao_inicial' {filtro}",
                params, connect_timeout=20, tentativas_maximas=3,
            )
            if len(linhas) >= 5 or not filtro:
                break
        ws: list[int] = []
        total_palavras = 0
        artigos = 0
        for l in linhas:
            texto = l["texto_integral"]
            total_palavras += len(texto.split())
            artigos += len(re.findall(r"\bart(?:igo)?s?\.?\s*\d", texto, re.IGNORECASE))
            ws += [len(p.split()) for p in paragrafos(texto) if len(p.split()) >= 30]
        if len(ws) >= 30:
            q = statistics.quantiles(ws, n=4)
            sinal = {
                "disponivel": True, "pecas": len(linhas), "paragrafos": len(ws),
                "mediana": statistics.median(ws), "p25": q[0], "p75": q[2],
                "palavras_por_inicial": round(total_palavras / len(linhas)),
                "artigos_por_mil": round(artigos / max(total_palavras, 1) * 1000, 1),
                "assuntos": list(assuntos),
            }
    except Exception as erro:  # noqa: BLE001 - sem o sinal, a revisão usa só os critérios qualitativos
        log.warning("densidade do acervo indisponível: %s", str(erro)[:160])
    _CACHE_DENSIDADE[chave] = sinal
    return sinal


def precisa_de_revisao(m: dict[str, Any], sinal: dict[str, Any]) -> list[str]:
    """Motivos (mensuráveis) para o revisor de profundidade agir; vazio = não mexer."""
    motivos = []
    if m["paragrafos"] == 0:
        return motivos
    piso = sinal.get("p25", 38)
    if m["mediana"] < piso:
        motivos.append(f"parágrafos curtos (mediana {m['mediana']:.0f} palavras; o acervo tem p25={piso:.0f})")
    if m["fragmentacao"] > 0.35:
        motivos.append(f"raciocínio fragmentado ({m['fragmentacao']:.0%} dos parágrafos com menos de 25 palavras)")
    if m["palavras"] >= 120 and m["artigos_por_mil"] == 0:
        motivos.append("nenhum dispositivo legal citado")
    return motivos


# ------------------------------------------------------------------ reranking híbrido

def rerank(
    candidatos: list[dict[str, Any]], consultas: list[str], assuntos: list[str], subteses_alvo: list[str]
) -> list[dict[str, Any]]:
    """Reordena por vetor + termos + assunto + subtese + tipo; guarda as parcelas (auditoria)."""
    termos = set()
    for c in consultas:
        termos.update(_termos(c))
    sub_alvo = set(_termos(" ".join(subteses_alvo)))
    saida = []
    for c in candidatos:
        texto = _norm(c["texto"])
        lexical = sum(1 for t in termos if t in texto) / max(len(termos), 1)
        sub = {p for s in (c.get("subteses") or []) for p in _termos(str(s))}
        bonus_sub = 0.04 if sub_alvo and sub & sub_alvo else 0.0
        bonus_assunto = 0.05 if c.get("assunto") in assuntos else 0.0
        bonus_tipo = 0.04 if c.get("tipo_peca") == "peticao_inicial" else 0.0
        # penaliza trecho que é quase só lista de artigos/endereçamento (pouco argumento)
        argumento = len(re.findall(r"[a-zà-ú]{4,}", texto)) / max(len(texto.split()), 1)
        final = 0.62 * c["similaridade"] + 0.28 * lexical + bonus_sub + bonus_assunto + bonus_tipo + 0.03 * argumento
        saida.append({**c, "lexical": round(lexical, 3), "final": round(final, 4)})
    return sorted(saida, key=lambda c: c["final"], reverse=True)


def diversificar(ordenados: list[dict[str, Any]], limite: int = EXEMPLOS_POR_TOPICO) -> list[dict[str, Any]]:
    escolhidos: list[dict[str, Any]] = []
    por_peca: Counter[str] = Counter()
    for c in ordenados:
        if por_peca[c["peca_id"]] >= MAXIMO_POR_PECA:
            continue
        escolhidos.append(c)
        por_peca[c["peca_id"]] += 1
        if len(escolhidos) >= limite:
            break
    return escolhidos


# ------------------------------------------------------------------ consultas do tópico

def consultas_do_topico(titulo: str, corpo: str, secao_label: str, plano: dict[str, Any] | None, categoria: str) -> list[str]:
    """Consultas curtas, ancoradas no caso: título+categoria; o argumento atual; a tese do plano."""
    ancora = re.sub(r"\s+", " ", f"{categoria}. {(plano or {}).get('cronologia', [{}])[0].get('fato', '') if (plano or {}).get('cronologia') else ''}")[:180]
    nome = re.sub(r"^[a-z]\)\s*|^[IVXLC]+(?:\.\d+)*\.?\s*[–—-]?\s*", "", titulo or secao_label or "", flags=re.IGNORECASE)
    consultas = [f"{ancora}. {nome}".strip()[:450]]
    resumo = re.sub(r"\s+", " ", corpo)[:420]
    if resumo:
        consultas.append(f"{nome}. {resumo}"[:600])
    alvo = set(_termos(f"{nome} {resumo}"))
    melhor = None
    for t in (plano or {}).get("teses") or []:
        if isinstance(t, dict) and t.get("tese"):
            afinidade = len(alvo & set(_termos(str(t["tese"]))))
            if afinidade and (melhor is None or afinidade > melhor[0]):
                melhor = (afinidade, t)
    if melhor:
        t = melhor[1]
        consultas.append(f"{ancora}. {t['tese']}. {'; '.join(map(str, (t.get('fatos_que_sustentam') or [])[:2]))}"[:600])
    return consultas


# ------------------------------------------------------------------ material do tópico + telemetria

@dataclass
class MaterialDoTopico:
    texto: str = ""
    telemetria: dict[str, Any] = field(default_factory=dict)
    itens: list[tuple[Any, str]] = field(default_factory=list)  # (Proveniencia, texto) para medir influência


def material_do_topico(
    titulo: str, corpo: str, secao_label: str, *, plano: dict[str, Any] | None, categoria: str,
    assuntos: list[str], contexto_uf: str,
) -> MaterialDoTopico:
    consultas = consultas_do_topico(titulo, corpo, secao_label, plano, categoria)
    tel: dict[str, Any] = {"topico": titulo or secao_label, "consultas": consultas}
    subteses = [t.get("tese", "") for t in (plano or {}).get("teses") or [] if isinstance(t, dict)]

    # 1) acervo de peças: todas as consultas, união dos candidatos, reranking, diversidade
    candidatos: dict[str, dict[str, Any]] = {}
    erros: list[str] = []

    def buscar(q: str):
        return q, rag.candidatos_de_pecas(q, limite=CANDIDATOS_POR_CONSULTA)

    with ThreadPoolExecutor(max_workers=3) as pool:
        for fut in [pool.submit(buscar, q) for q in consultas]:
            try:
                q, achados = fut.result()
                for c in achados:
                    atual = candidatos.get(c["chunk_id"])
                    if atual is None or c["similaridade"] > atual["similaridade"]:
                        candidatos[c["chunk_id"]] = c
            except Exception as erro:  # noqa: BLE001
                erros.append(f"{type(erro).__name__}: {str(erro)[:100]}")
    ordenados = rerank(list(candidatos.values()), consultas, assuntos, subteses)
    escolhidos = diversificar(ordenados)
    tel["acervo"] = {
        "candidatos": len(candidatos), "pecas_distintas_candidatas": len({c["peca_id"] for c in candidatos.values()}),
        "escolhidos": [{"peca": c["nome_arquivo"][:60], "tipo": c["tipo_peca"], "assunto": c["assunto"], "vetor": round(c["similaridade"], 3),
                        "lexical": c["lexical"], "final": c["final"]} for c in escolhidos],
        "pecas_distintas_escolhidas": len({c["peca_id"] for c in escolhidos}), "erros": erros,
    }
    linhas = []
    itens: list[tuple[Any, str]] = []
    for i, c in enumerate(escolhidos, 1):
        linhas.append(f"[E{i}] peça do escritório ({c['tipo_peca']}; assunto {c['assunto']}; arquivo {c['nome_arquivo'][:70]})\n{c['texto'][:1400]}")
        itens.append((recuperacao_por_tese.Proveniencia("peca", c["nome_arquivo"], c["categoria"], c["final"], [titulo or secao_label],
                                                        min(len(c["texto"]), 1400), c["tipo_peca"] or ""), c["texto"]))
    # dispositivos que o escritório costuma invocar neste tipo de tópico (SINAL — citar só se estiver no bloco de legislação/skill)
    contagem = Counter(m.group(0).lower().replace("º", "").replace("°", "") for c in escolhidos
                       for m in re.finditer(r"\bart\.?\s*\d+[a-z]?(?:[,\s]+(?:§\s*\d+|inciso\s+[IVX]+|[IVX]+))?", c["texto"], re.IGNORECASE))
    frequentes = [a for a, n in contagem.most_common(8) if n >= 2]
    tel["dispositivos_frequentes_no_acervo"] = frequentes

    # 2) julgados e legislação do MESMO tópico
    cons_tese = [{"tese": titulo or secao_label, "consulta": q} for q in consultas]
    prec, prov_p, err_p = recuperacao_por_tese.precedentes(cons_tese, contexto_uf, por_tese=3, total=6)
    leis, prov_l, err_l = recuperacao_por_tese.legislacao(cons_tese, por_tese=2, total=5)
    tel["julgados"] = [{"id": p.id, "score": round(p.score, 3), "natureza": p.natureza[:40]} for p in prov_p]
    tel["legislacao"] = [{"id": p.id, "score": round(p.score, 3)} for p in prov_l]
    tel["erros_julgados_legislacao"] = err_p + err_l
    itens += list(zip(prov_p, [t.texto[:1500] for t in prec])) + list(zip(prov_l, [t.texto[:1500] for t in leis]))

    partes = ["=== MATERIAL DESTE TÓPICO (recuperado só para ele) ==="]
    if linhas:
        partes.append(
            "EXEMPLOS DO ESCRITÓRIO — memória de como o escritório desenvolve teses semelhantes. Use como PADRÃO de "
            "argumentação, ordem das ideias, profundidade e vocabulário; SINTETIZE vários, não copie nenhum. "
            "NUNCA transporte fatos, nomes, valores, datas, documentos ou citações de um exemplo: fato vem dos "
            "documentos do caso; norma/precedente só dos blocos abaixo ou da skill.\n" + "\n\n".join(linhas)
        )
    if frequentes:
        partes.append("Dispositivos que o escritório costuma invocar em tópicos parecidos (cite SOMENTE se constarem da legislação abaixo ou da skill): " + "; ".join(frequentes))
    if prec:
        partes.append("JULGADOS (reais, do acervo; distinga vinculante de persuasivo; explique por que alcançam ESTES fatos):\n" + "\n\n".join(
            f"[J{i}] processo={p.id} natureza={p.natureza}\n{t.texto[:1500]}" for i, (t, p) in enumerate(zip(prec, prov_p), 1)))
    if leis:
        partes.append("LEGISLAÇÃO (texto oficial):\n" + "\n\n".join(f"[L{i}] {t.titulo}\n{t.texto[:1300]}" for i, t in enumerate(leis, 1)))
    texto = "\n\n".join(partes)
    tel["chars_enviados"] = len(texto)
    return MaterialDoTopico(texto, tel, itens)
