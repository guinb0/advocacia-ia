"""DOCUMENTO FINAL — higiene determinística + FINAL_DOCUMENT_VALIDATOR sobre o que será EFETIVAMENTE renderizado.

POR QUE ESTE MÓDULO EXISTE (v11)

Os validadores anteriores rodavam sobre o rascunho e sobre seções "como o modelo as devolveu". Erros chegavam ao PDF
porque nasciam DEPOIS ou ONDE o validador não olhava: um título escrito em texto corrido (sem `#`) dentro da seção de
pedidos passava por "título" no documento mas não na numeração; um título de ação vinha de um bloco e de um parágrafo
em negrito ao mesmo tempo; a instrução de registro de alterações do chat virava uma seção da peça.

Aqui a regra é: `higienizar` aplica só correções SEGURAS e determinísticas (metadado interno sai do documento,
numeração é estrutural, título/abertura repetidos saem) e `validar_documento_final` confere o resultado sobre a
MESMA representação que `montar_docx` imprime (rótulos impressos + conteúdo, após a migração de peças legadas).
Depois disso nada pode mudar as seções: `impressao_hash` é conferido antes de gravar.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from . import auditoria_estrutural as ae
from . import document_ledger, peticao_migracao_legado, petition_linter, plano_da_peticao as pp
from .conferencia_peticao import Violacao
from .recuperacao_por_secao import paragrafos

_TITULO_ROMANO = re.compile(r"^\s*(?:#{1,3}\s*)?(?:\*\*)?([IVXLC]+)\s*[.\-–—)]\s+(\S.{2,90}?)(?:\*\*)?\s*$")
_SUBTITULO_ROMANO = re.compile(r"^(\s*(?:#{2,6}\s*)?(?:\*\*)?)([IVXLC]+)\.(\d+)(\.?\s+\S.*)$")
_MARCADOR_ESTRUTURAL = re.compile(r"^\s*:::\s*(?:[\w-]+)?\s*$", re.MULTILINE)
_FECHAMENTO = re.compile(r"(?im)^\s*termos\s+em\s+que\s*,?\s*\n\s*pede\s+deferimento\s*\.?\s*$")
_DA_SE_CAUSA = re.compile(
    r"(?im)^\s*D[aá]-se\s+[àa]\s+causa[^\n]*\n?",
)
_ROMANOS = [(100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def _v(codigo: str, secao: str, trecho: str, motivo: str, correcao: str, bloqueia: bool = True) -> Violacao:
    return Violacao(codigo, secao, str(trecho)[:220], motivo, correcao, bloqueia)


def para_romano(n: int) -> str:
    saida = ""
    for v, s in _ROMANOS:
        while n >= v:
            saida += s
            n -= v
    return saida


def _titulo_sem_numero(texto: str) -> str:
    m = _TITULO_ROMANO.match(texto)
    return pp.norm(m.group(2) if m else texto)


# ------------------------------------------------------------------ representação FINAL (o que sai no DOCX)

def _sem_marcadores_estruturais(secoes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Marcadores do parser são metadados, nunca texto de editor/exportação."""
    removidos = 0
    saida = []
    for s in secoes:
        conteudo = str(s.get("content") or "")
        limpo, n = _MARCADOR_ESTRUTURAL.subn("", conteudo)
        removidos += n
        saida.append({**s, "content": re.sub(r"\n{3,}", "\n\n", limpo).strip()})
    return saida, removidos


def preparar_para_renderizacao(secoes: list[dict[str, Any]], params: dict[str, Any]) -> list[dict[str, Any]]:
    """Representação persistível/renderizável, sem transformações ocultas no DOCX."""
    migradas = peticao_migracao_legado.migrar_secoes(secoes)
    sem_metadata, _ = _cortar_metadata(migradas, params)
    limpas, _ = _sem_marcadores_estruturais(sem_metadata)
    return limpas


def representacao_final(secoes: list[dict[str, Any]], params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """As seções exatamente como `montar_docx` as imprime: migração de legado aplicada e rótulo impresso como `# `."""
    migradas = preparar_para_renderizacao(secoes, params or {})
    saida = []
    for s in migradas:
        conteudo = str(s.get("content") or "")
        rotulo = str(s.get("label") or "").strip()
        if petition_linter.deve_imprimir_rotulo(rotulo, conteudo):
            conteudo = f"# {rotulo}\n\n{conteudo}"
        saida.append({**s, "content": conteudo})
    return saida


def impressao_hash(secoes: list[dict[str, Any]]) -> str:
    return hashlib.sha256("\n␞".join(str(s.get("content") or "") for s in representacao_final(secoes)).encode("utf-8")).hexdigest()[:16]


def headings_reais(secoes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Todo título de capítulo como ele aparece — com `#`, em negrito ou em texto corrido (o que a v11 escondia)."""
    saida = []
    for s in representacao_final(secoes):
        for linha in str(s.get("content") or "").split("\n"):
            m = _TITULO_ROMANO.match(linha.strip())
            if m and len(linha.strip()) <= 100 and not linha.rstrip().endswith((".", ";", ":")) or (m and re.match(r"^\s*#", linha)):
                saida.append({"secao": str(s.get("code")), "texto": linha.strip("# *"), "numero": m.group(1), "titulo": pp.norm(m.group(2))})
    return saida


# ------------------------------------------------------------------ higiene determinística

def _cortar_metadata(secoes: list[dict[str, Any]], params: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Metadado interno de geração (registro de alterações, relatório) NÃO é conteúdo da peça: sai e vai para o relatório."""
    meta = params.get("metadata_interna") or {}
    titulos = [re.compile(r, re.IGNORECASE) for r in meta.get("titulos", [])]
    rotulos = [re.compile(r, re.IGNORECASE | re.MULTILINE) for r in meta.get("rotulos", [])]
    removidos: list[dict[str, str]] = []
    saida = []
    for s in secoes:
        conteudo, rotulo = str(s.get("content") or ""), str(s.get("label") or "")
        if any(t.search(rotulo) for t in titulos):
            removidos.append({"secao": str(s.get("code")), "texto": conteudo[:4000]})
            continue
        linhas = conteudo.split("\n")
        corte = None
        for i, linha in enumerate(linhas):
            limpa = linha.strip("# *:")
            if len(limpa) <= 80 and any(t.search(limpa) for t in titulos):
                corte = i
                break
        if corte is None and len({i for i, r in enumerate(rotulos) if r.search(conteudo)}) >= 3:
            # o bloco só aparece como "Formatação: … Organização: … Inclusões: …" sem título: corta a partir do 1º rótulo
            primeiros = [m.start() for r in rotulos for m in [r.search(conteudo)] if m]
            inicio = min(primeiros)
            corte = conteudo[:inicio].count("\n")
        if corte is not None:
            removidos.append({"secao": str(s.get("code")), "texto": "\n".join(linhas[corte:])[:4000]})
            conteudo = "\n".join(linhas[:corte]).rstrip()
            if not conteudo.strip():
                continue
        saida.append({**s, "content": conteudo})
    return saida, removidos


def _remover_titulos_repetidos(secoes: list[dict[str, Any]], params: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Uma seção lógica = um heading: título estrutural cujo texto (sem o número) já apareceu sai; o título da ação fica uma vez.

    Pega também o título escrito como PRIMEIRA LINHA de um parágrafo (sem `#`), que era como o «III. Dos Pedidos» da v11
    escapava da validação de numeração. Do título da ação, fica o que vem logo após «propor a presente» (a fórmula
    narrativa da skill); os demais saem.
    """
    regex_acao = (params.get("estrutura") or {}).get("titulo_da_acao_regex")
    vistos: set[str] = set()
    removidos = 0
    novas: list[dict[str, Any]] = []
    acoes: list[tuple[int, int, bool]] = []  # (secao, indice do trecho, vem após "propor a presente")
    blocos_por_secao: list[list[str]] = []
    for si, s in enumerate(secoes):
        rotulo = str(s.get("label") or "")
        if rotulo and _TITULO_ROMANO.match(rotulo) and petition_linter.deve_imprimir_rotulo(rotulo, str(s.get("content") or "")):
            chave = _titulo_sem_numero(rotulo)
            vistos.add(chave)
        pars = re.split(r"(\n\s*\n)", str(s.get("content") or ""))
        anterior = ""
        for pi, trecho in enumerate(pars):
            if re.fullmatch(r"\n\s*\n", trecho) or not trecho.strip():
                continue
            linhas = trecho.strip().split("\n")
            primeira = linhas[0].strip()
            if _TITULO_ROMANO.match(primeira) and len(primeira) <= 100 and not primeira.endswith((".", ";", ":")) or re.match(r"^#\s", primeira):
                chave = _titulo_sem_numero(primeira.lstrip("# "))
                if chave in vistos and s.get("code") != "HEADING" and _TITULO_ROMANO.match(primeira.lstrip("# ")):
                    resto = "\n".join(linhas[1:]).strip()
                    pars[pi] = resto
                    removidos += 1
                    trecho = resto
                else:
                    vistos.add(chave)
            visivel = re.sub(r"^:::.*$", "", trecho, flags=re.MULTILINE).strip().strip("*# ")
            if regex_acao and visivel and len(visivel.split()) <= 16 and re.match(regex_acao, visivel, re.IGNORECASE):
                acoes.append((si, pi, bool(re.search(r"propor\s+a\s+presente\s*:?\s*$", anterior.strip(), re.IGNORECASE))))
            anterior = trecho
        blocos_por_secao.append(pars)
    if len(acoes) > 1:
        manter = next((a for a in acoes if a[2]), acoes[0])
        for si, pi, _ in acoes:
            if (si, pi) != manter[:2]:
                blocos_por_secao[si][pi] = ""
                removidos += 1
    for s, pars in zip(secoes, blocos_por_secao):
        texto = re.sub(r"\n{3,}", "\n\n", "".join(pars)).strip()
        novas.append({**s, "content": texto})
    return novas, removidos


def _renumerar_capitulos(secoes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deriva número e pai dos títulos da ordem estrutural; conteúdo não escolhe capítulo."""
    n = 0
    novas = []
    for s in secoes:
        rotulo, conteudo = str(s.get("label") or "").strip(), str(s.get("content") or "")
        m = _TITULO_ROMANO.match(rotulo)
        if m and petition_linter.deve_imprimir_rotulo(rotulo, conteudo):
            n += 1
            rotulo = f"{para_romano(n)}. {m.group(2)}"
        primeira = conteudo.lstrip().split("\n", 1)[0]
        mc = _TITULO_ROMANO.match(primeira)
        if mc:
            n += 1
            conteudo = conteudo.replace(primeira, f"{para_romano(n)}. {mc.group(2)}", 1)
        # Um subtítulo `VII.1` é filho do capítulo atual, não um novo capítulo
        # livre que o redator possa numerar por conta própria.
        pai = para_romano(n) if n else ""
        if pai:
            conteudo = "\n".join(
                _SUBTITULO_ROMANO.sub(lambda x: f"{x.group(1)}{pai}.{x.group(3)}{x.group(4)}", linha)
                for linha in conteudo.split("\n")
            )
        novas.append({**s, "label": rotulo, "content": conteudo})
    return novas


def _deduplicar_fechamento(secoes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Um único owner: conserva o último fechamento estrutural no fluxo da peça."""
    ocorrencias = [
        (i, m.start(), m.end())
        for i, s in enumerate(secoes)
        for m in _FECHAMENTO.finditer(str(s.get("content") or ""))
    ]
    if len(ocorrencias) <= 1:
        return secoes, 0
    manter = ocorrencias[-1]
    removidos = 0
    novas = []
    for i, s in enumerate(secoes):
        texto = str(s.get("content") or "")
        partes = []
        ultimo = 0
        for m in _FECHAMENTO.finditer(texto):
            partes.append(texto[ultimo:m.start()])
            if (i, m.start(), m.end()) == manter:
                partes.append(m.group(0))
            else:
                removidos += 1
            ultimo = m.end()
        partes.append(texto[ultimo:])
        novas.append({**s, "content": re.sub(r"\n{3,}", "\n\n", "".join(partes)).strip()})
    return novas, removidos


def _deduplicar_valor_causa(secoes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Uma só linha «Dá-se à causa» — a v15 duplicava valor + assinatura no final."""
    ocorrencias = [
        (i, m.start(), m.end())
        for i, s in enumerate(secoes)
        for m in _DA_SE_CAUSA.finditer(str(s.get("content") or ""))
    ]
    if len(ocorrencias) <= 1:
        return secoes, 0
    manter = ocorrencias[-1]
    removidos = 0
    novas = []
    for i, s in enumerate(secoes):
        texto = str(s.get("content") or "")
        partes = []
        ultimo = 0
        for m in _DA_SE_CAUSA.finditer(texto):
            partes.append(texto[ultimo:m.start()])
            if (i, m.start(), m.end()) == manter:
                partes.append(m.group(0))
            else:
                removidos += 1
            ultimo = m.end()
        partes.append(texto[ultimo:])
        novas.append({**s, "content": re.sub(r"\n{3,}", "\n\n", "".join(partes)).strip()})
    return novas, removidos


def aplicar_qualificacao_canonica(
    secoes: list[dict[str, Any]], partes: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Qualificação do autor/réu vem do CASE_FACTS (código), não do livre-arbítrio do modelo.

    O modelo ainda redige o endereçamento e a narrativa; nomes e CPF resolvidos são
    SUBSTITUÍDOS aqui para a peça não oscillar (v14 certo → v15 «BEZERRA TESTE»).
    """
    autor = partes.get("autor") or {}
    reu = partes.get("reu") or {}
    rel: dict[str, Any] = {"aplicado": False, "substituicoes": []}
    nome = str(autor.get("nome") or "").strip()
    if not nome or not secoes:
        return secoes, rel

    novas = [dict(s) for s in secoes]
    texto = str(novas[0].get("content") or "")
    original = texto

    for m in list(ae._DADO_DE_TESTE.finditer(texto)):  # noqa: SLF001
        texto = texto[: m.start()] + nome + texto[m.end() :]
        rel["substituicoes"].append({"de": m.group(0), "para": nome})

    for campo in ("cpf", "endereco", "rg", "cnpj"):
        papel = "reu" if campo == "cnpj" else "autor"
        valor = str((reu if papel == "reu" else autor).get(campo) or "").strip()
        if not valor:
            continue
        texto2, n = re.subn(
            rf"\[PENDENTE:[^\]]*{campo}[^\]]*\]",
            valor,
            texto,
            flags=re.IGNORECASE,
        )
        if n:
            texto = texto2
            rel["substituicoes"].append({"de": f"[PENDENTE:{campo}]", "para": valor})

    cpf = str(autor.get("cpf") or "").strip()
    if (
        cpf
        and pp.norm(nome) in pp.norm(texto)
        and pp._so_digitos(cpf) not in pp._so_digitos(texto)  # noqa: SLF001
    ):
        texto2, n = re.subn(
            r"(inscrit[oa]\s+no\s+CPF[^\d\[]{0,40})(\d{3}\.?\d{3}\.?\d{3}-?\d{2}|\[\s*PENDENTE[^\]]*\])",
            rf"\g<1>{cpf}",
            texto,
            count=1,
            flags=re.IGNORECASE,
        )
        if n:
            texto = texto2
            rel["substituicoes"].append({"de": "cpf_divergente", "para": cpf})

    if texto != original:
        novas[0]["content"] = texto
        rel["aplicado"] = True
    return novas, rel


def higienizar(secoes: list[dict[str, Any]], plano: dict[str, Any], params: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rel: dict[str, Any] = {}
    secoes = peticao_migracao_legado.migrar_secoes(secoes)
    secoes, metadata = _cortar_metadata(secoes, params)
    rel["metadata_interna_removida"] = metadata
    secoes, n_marcadores = _sem_marcadores_estruturais(secoes)
    rel["marcadores_estruturais_removidos"] = n_marcadores
    secoes, n_fechamentos = _deduplicar_fechamento(secoes)
    rel["fechamentos_duplicados_removidos"] = n_fechamentos
    secoes, n_valores = _deduplicar_valor_causa(secoes)
    rel["valores_causa_duplicados_removidos"] = n_valores
    secoes, n_repetidos = _remover_titulos_repetidos(secoes, params)
    rel["titulos_repetidos_removidos"] = n_repetidos
    if plano.get("partes"):
        secoes, n_ab = ae.remover_aberturas_duplicadas(secoes, plano["partes"], params)
        rel["aberturas_duplicadas_removidas"] = n_ab
        secoes, rel_quali = aplicar_qualificacao_canonica(secoes, plano["partes"])
        rel["qualificacao_canonica"] = rel_quali
    secoes = [s for s in secoes if str(s.get("content") or "").strip() or str(s.get("label") or "").strip() == ""] or secoes
    secoes = _renumerar_capitulos(secoes)
    return secoes, rel


# ------------------------------------------------------------------ FINAL_DOCUMENT_VALIDATOR

def _frases(texto: str) -> list[str]:
    return [f.strip() for f in re.split(r"(?<=[.;!?])\s+|\n+", texto) if len(f.strip()) > 20]


def epistemica(secoes: list[dict[str, Any]], params: dict[str, Any], plano: dict[str, Any]) -> list[Violacao]:
    """Ausência de prova ≠ prova de ausência — no nível da FRASE, com a classificação de evidência do plano."""
    ep = params.get("epistemica") or {}
    if not ep:
        return []
    neg, cert = re.compile(ep["negacao"], re.IGNORECASE), re.compile(ep["certeza"], re.IGNORECASE)
    qual = re.compile(ep["qualificador"], re.IGNORECASE)
    req = re.compile(ep.get("requerimento_probatorio", "$^"), re.IGNORECASE)
    saida: list[Violacao] = []
    categoricas: list[tuple[str, set[str]]] = []
    frases = [(str(s.get("code")), f) for s in secoes for f in _frases(str(s.get("content") or ""))]
    ausencias = [pp._tokens(a.get("afirmacao", "")) for a in plano.get("ausencias") or []]  # noqa: SLF001
    for codigo, f in frases:
        eh_ausencia = bool(neg.search(f)) or any(len(a & pp._tokens(f)) >= 3 for a in ausencias)  # noqa: SLF001
        normalizada = pp.norm(f)
        eh_ausencia = eh_ausencia or bool(re.search(r"\b(ausencia|inexistencia|falta) de\b", normalizada))
        categorica = bool(cert.search(f)) or bool(re.search(r"documentalmente (demonstr|comprov)|esta (comprov|demonstr)|restou (comprov|demonstr)|comprova.* que nao", normalizada))
        qualificada = bool(qual.search(f)) or bool(re.search(r"documentos? (disponiveis|juntados)|nao (consta|registra|ha registro)|segundo o relato", normalizada))
        # "não mera alegação" não é qualificador: é precisamente afirmação categórica.
        qualificada = qualificada and "mera alegacao" not in normalizada
        if eh_ausencia and categorica and not qualificada:
            saida.append(_v("AUSENCIA_REDIGIDA_COMO_CONFIRMADA", codigo, f, "Fato «não encontrado nos documentos disponíveis» foi redigido como ausência CONFIRMADA/demonstrada.",
                            "Reescreva como: «os documentos disponíveis não registram …», e — se importa — requeira a prova; nunca «está comprovado que não havia …»."))
            categoricas.append((codigo, {t for t in pp._tokens(f) if len(t) >= 6}))  # noqa: SLF001
    if categoricas:
        for codigo, f in frases:
            if req.search(f) or re.search(r"\b(exibi|exib|prova|esclarec|pericia)\w*", pp.norm(f)):
                tk = {t for t in pp._tokens(f) if len(t) >= 6}  # noqa: SLF001
                for cod2, tokens in categoricas:
                    if len(tk & tokens) >= 2:
                        saida.append(_v("AFIRMACAO_CATEGORICA_X_PROVA_REQUERIDA", codigo, f, f"A peça afirma como demonstrado (seção {cod2}) o que depois requer prova para esclarecer.",
                                        "Ou o fato está provado (e não se requer a prova para apurá-lo) ou é alegação/ausência documental (e a afirmação categórica sai)."))
                        break
    return saida


def metadata_no_documento(secoes: list[dict[str, Any]], params: dict[str, Any]) -> list[Violacao]:
    _, removidos = _cortar_metadata(secoes, params)
    return [_v("METADATA_INTERNA_NO_DOCUMENTO", r["secao"], r["texto"][:100], "Metadado interno de geração (ex.: registro de alterações) no documento da peça.", "Remova: relatório interno não faz parte da peça.") for r in removidos]


def pedidos_no_texto(secoes: list[dict[str, Any]]) -> list[Violacao]:
    """Sobreposição econômica no que foi EFETIVAMENTE escrito: item de majoração com valor próprio ao lado do pedido que ele majora."""
    saida = []
    itens = []
    for s in secoes:
        if s.get("code") == "CLAIMS":
            itens += [m.group(2) for m in re.finditer(r"^\s*(?:\*\*)?([a-z])\)\s*(.+)$", str(s.get("content") or ""), re.MULTILINE)]
    monetarios = [i for i in itens if re.search(r"R\$\s*[\d.]+,\d{2}", i)]
    for i, a in enumerate(monetarios):
        if ae._MAJORACAO.search(a[:200]):  # noqa: SLF001
            for b in monetarios:
                if b is not a and pp._jaccard(pp._tokens(a[:220]), pp._tokens(b[:220])) >= 0.15 and not ae._MAJORACAO.search(b[:200]):  # noqa: SLF001
                    saida.append(_v("MAJORACAO_COMO_SEGUNDA_INDENIZACAO", "CLAIMS", a[:120], "Um pedido de MAJORAÇÃO com valor próprio ao lado do pedido que ele majora: o agravante virou segunda indenização.",
                                    "O agravante entra na quantificação do pedido principal (um só valor, com o critério), não como pedido econômico separado."))
                    break
    return saida


def _de_romano(valor: str) -> int:
    mapa = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    total, anterior = 0, 0
    for simbolo in reversed(valor):
        atual = mapa[simbolo]
        total += -atual if atual < anterior else atual
        anterior = max(anterior, atual)
    return total


def invariantes_estruturais(secoes: list[dict[str, Any]]) -> list[Violacao]:
    """Invariantes do artefato visível: estrutura e numeração têm uma só fonte."""
    saida: list[Violacao] = []
    principal_atual = ""
    esperado = 1
    principais: list[tuple[str, str]] = []
    for s in secoes:
        for linha in str(s.get("content") or "").splitlines():
            limpa = linha.strip().lstrip("# ").strip("* ")
            sub = re.match(r"^([IVXLC]+)\.(\d+)\.?\s+", limpa)
            if sub:
                if principal_atual and sub.group(1) != principal_atual:
                    saida.append(_v("SUBSECAO_COM_PAI_INCONSISTENTE", str(s.get("code")), limpa,
                                    f"A subseção {sub.group(1)}.{sub.group(2)} não pertence ao capítulo atual {principal_atual}.",
                                    "Derive a subseção do capítulo-pai canônico."))
                continue
            main = _TITULO_ROMANO.match(limpa)
            if not main:
                continue
            numero = _de_romano(main.group(1))
            if numero != esperado:
                saida.append(_v("SEQUENCIA_DE_HEADINGS_INVALIDA", str(s.get("code")), limpa,
                                f"O capítulo {main.group(1)} aparece onde se esperava {para_romano(esperado)}.",
                                "A numeração é derivada da ordem canônica das seções."))
            principal_atual = main.group(1)
            esperado = numero + 1
            principais.append((str(s.get("code")), _titulo_sem_numero(limpa)))
    codigos_logicos = {"OPENING", "FACTS", "LEGAL_GROUNDS", "CLAIMS", "CLOSING"}
    for codigo in codigos_logicos:
        n = sum(1 for s in secoes if str(s.get("code") or "") == codigo)
        if n > 1:
            saida.append(_v("SECAO_ESTRUTURAL_DUPLICADA", codigo, codigo,
                            f"A seção estrutural {codigo} aparece {n} vezes.", "Mantenha uma única seção canônica."))
    fechamentos = sum(len(_FECHAMENTO.findall(str(s.get("content") or ""))) for s in secoes)
    if fechamentos != 1:
        codigo = "CLOSING" if fechamentos else ""
        saida.append(_v("EXACTLY_ONE_CLOSING_BLOCK", codigo, str(fechamentos),
                        f"O documento visível possui {fechamentos} fechamento(s).", "Mantenha exatamente um bloco de fechamento."))
    if any(_MARCADOR_ESTRUTURAL.search(str(s.get("content") or "")) for s in secoes):
        saida.append(_v("MARCADOR_ESTRUTURAL_VISIVEL", "", ":::",
                        "Marcador interno chegou à representação visível.", "Remova marcadores estruturais antes de persistir/renderizar."))
    return saida


def consistencia_procedimental(secoes: list[dict[str, Any]]) -> list[Violacao]:
    """Julgamento sem instrução não coexiste com prova instrutória declarada necessária."""
    texto = "\n".join(str(s.get("content") or "") for s in secoes)
    normalizado = pp.norm(texto)
    cedo = bool(re.search(r"julgamento antecipado|desnecessidade de (realizacao de )?audiencia|dispensa.{0,30}(audiencia|instrucao)|sem necessidade de instrucao", normalizado))
    prova = bool(re.search(r"prova testemunhal|oitiva de testemun|depoimento pessoal|prova pericial|pericia|inspecao judicial", normalizado))
    necessidade = bool(re.search(r"(necessari|precis|depend).{0,45}(prova|pericia|instrucao|confirm)", normalizado))
    if cedo and prova and necessidade:
        return [_v("ESTRATEGIA_PROCESSUAL_INCONSISTENTE", "", "julgamento antecipado × prova instrutória necessária",
                   "A peça dispensa instrução, mas declara necessária prova que a exige.",
                   "Retire a dispensa, torne-a subsidiária se a estratégia assim permitir, ou sinalize a pendência para revisão." )]
    return []


def validar_documento_final(
    secoes: list[dict[str, Any]], plano: dict[str, Any], params: dict[str, Any], ledger: list[dict[str, Any]] | None = None,
) -> list[Violacao]:
    """Tudo o que precisa ser verdade no artefato final — rodado sobre `representacao_final` (o que sai no DOCX)."""
    final = representacao_final(secoes, params)
    hs = headings_reais(secoes)
    saida: list[Violacao] = []
    # headings: título estrutural repetido / numeração real
    por_titulo: dict[str, list[dict[str, Any]]] = {}
    for h in hs:
        por_titulo.setdefault(h["titulo"], []).append(h)
    for t, lista in por_titulo.items():
        if len(lista) > 1:
            saida.append(_v("HEADING_DUPLICADO", lista[1]["secao"], " / ".join(h["texto"] for h in lista), f"O capítulo «{t}» aparece {len(lista)} vezes como título.", "Uma seção lógica = um heading estrutural."))
    saida += ae.numeracao([(h["secao"], f"{h['numero']}. {h['titulo']}") for h in hs])
    if sum(1 for s in final if s.get("code") == "CLAIMS") > 1:
        saida.append(_v("PEDIDOS_EM_MAIS_DE_UMA_SECAO", "CLAIMS", "", "A seção de pedidos aparece mais de uma vez.", "Só uma seção estrutural de pedidos."))
    saida += ae.abertura_unica(final, plano.get("partes") or {}, params)
    saida += metadata_no_documento(secoes, params)
    # Placeholders e dados de teste BLOQUEIAM a entrega — a peça não pode
    # oscillar entre versões com «BEZERRA TESTE» ou «[PENDENTE]» no corpo.
    saida += ae.dado_de_teste_no_texto(final)
    saida += ae.placeholders_proibidos(final)
    saida += ae.cidade_endereco_vs_vara(final, plano.get("partes") or {})
    saida += [_v("PLACEHOLDER_NO_DOCUMENTO_FINAL", c, m, f"Marcador {m[:60]} no documento final.", "Resolva o dado ou registre a pendência para revisão humana antes de considerar a peça pronta.", False) for c, m in ae.pendencias(final) if not ae._PLACEHOLDER_PROIBIDO.search(m)]  # noqa: SLF001
    saida += ae.pendencia_com_dado_canonico(final, plano.get("partes") or {})
    saida += ae.dado_rejeitado_no_texto(final, plano.get("case_facts") or {})
    if ledger:
        saida += document_ledger.validar_bijecao(ledger) + document_ledger.validar_referencias(final, ledger)
        saida += ae.ausencia_falsa_de_documento_listado(final, ledger)
    saida += pedidos_no_texto(final) + ae.ledger(plano) + ae.valor_da_causa(final, plano) + ae.criterio_de_calculo(final, params)
    saida += epistemica(final, params, plano)
    saida += invariantes_estruturais(final)
    saida += consistencia_procedimental(final)
    saida += ae.repeticao_de_conteudo(final, params)
    return saida
