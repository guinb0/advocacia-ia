"""PETITION LINTER — validação determinística ANTES de a peça virar DOCX.

Complementa `conferencia_peticao` (que confere o texto contra os autos) com o que só o PLANO
estruturado permite verificar: partes qualificadas, pedidos únicos e vindos do plano, fatos de uma
tese não vazando para outra e nenhum dado de petição antiga (acervo) tratado como fato do cliente.

Tudo aqui é código: o LLM redige e revisa semântica; o linter garante presença de blocos, ids,
relacionamentos e integridade. Regras jurídicas/editoriais ficam na SKILL (`validacoes.md`,
parâmetros `qualificacao` e `estrutura`): este módulo lê de lá QUAIS campos a qualificação exige.
"""

from __future__ import annotations

import re
from typing import Any

from . import plano_da_peticao as pp
from .conferencia_peticao import Violacao
from .recuperacao_por_secao import dividir_em_topicos

_DATA = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
_VALOR = re.compile(r"R\$\s*[\d.]+,\d{2}")
_NUMERO = re.compile(r"(?<![\d,])\d[\d./-]{4,}\d(?![\d,])")
_ITEM = re.compile(r"^\s*(?:\*\*)?([a-z])\)\s*(.+)$", re.MULTILINE)


def _especificos(texto: str) -> set[str]:
    """Marcadores que identificam UM caso: datas, valores em reais e números longos (CPF, CNPJ, NB…)."""
    achados = {m.group(0) for m in _DATA.finditer(texto)}
    achados |= {re.sub(r"\s+", "", m.group(0)) for m in _VALOR.finditer(texto)}
    achados |= {pp._so_digitos(m.group(0)) for m in _NUMERO.finditer(texto) if len(pp._so_digitos(m.group(0))) >= 6}  # noqa: SLF001
    return achados


def _presente(marcador: str, texto: str) -> bool:
    if "/" in marcador or marcador.startswith("R$"):
        return marcador in texto or marcador in re.sub(r"\s+", "", texto)
    return marcador in pp._so_digitos(texto)  # noqa: SLF001


def _secao(secoes: list[dict[str, Any]], codigo: str) -> dict[str, Any] | None:
    return next((s for s in secoes if s.get("code") == codigo), None)


def _achado(codigo: str, secao: str, trecho: str, motivo: str, correcao: str, bloqueia: bool = True) -> Violacao:
    return Violacao(codigo, secao, trecho[:220], motivo, correcao, bloqueia)


# ------------------------------------------------------------------ estrutura + qualificação

def _estrutura_e_qualificacao(secoes: list[dict[str, Any]], plano: dict[str, Any], params: dict[str, Any]) -> list[Violacao]:
    saida: list[Violacao] = []
    q = params.get("qualificacao") or {}
    # A abertura é a PRIMEIRA seção da peça (posição estrutural), qualquer que seja o `code` que o redator lhe deu:
    # procurar por "HEADING" fazia o corretor criar uma 2ª abertura quando o code era outro.
    abertura = secoes[0] if secoes else None
    codigo_abertura = str((abertura or {}).get("code") or q.get("secao", "HEADING"))
    texto = str((abertura or {}).get("content") or "")
    regex_ender = (params.get("estrutura") or {}).get("enderecamento_regex")
    if regex_ender and not re.search(regex_ender, texto, re.IGNORECASE):
        saida.append(_achado("ENDERECAMENTO_AUSENTE", codigo_abertura, texto[:80], "A peça não abre com o endereçamento exigido pela skill.",
                             "Abra a peça com o endereçamento conforme a skill (estrutura_peca.md)."))
    if not q.get("exigida"):
        return saida
    partes = plano.get("partes") or {}
    autor = partes.get("autor") or {}
    reu = partes.get("reu") or {}
    norm_texto, dig_texto = pp.norm(texto), pp._so_digitos(texto)  # noqa: SLF001
    ausentes: list[str] = []
    for papel, dados in (("autor", autor), ("reu", reu)):
        for campo in ((q.get("campos") or {}).get(papel) or []):
            valor = dados.get(campo)
            if valor and not pp._valor_consta(campo, valor, norm_texto, dig_texto):  # noqa: SLF001
                ausentes.append(f"{papel}.{campo}")
    nome = autor.get("nome", "")
    sem_bloco = not texto.strip() or (nome and pp.norm(nome) not in norm_texto)
    # Qualquer dado canônico disponível (em especial CNPJ/endereço da ré) é
    # obrigatório na abertura. Tolerar uma "maioria" deixava regressões passar.
    if sem_bloco or ausentes:
        dados = "; ".join(f"{p}.{k}: {v}" for p in ("autor", "reu") for k, v in (partes.get(p) or {}).items())
        saida.append(_achado(
            "QUALIFICACAO_AUSENTE", codigo_abertura, texto[:120],
            "Este tipo de peça exige a qualificação das partes na abertura e ela não está (ou está incompleta): "
            + (", ".join(ausentes) or "nome do autor ausente"),
            "Inclua a qualificação com EXATAMENTE estes dados do caso, sem inventar nenhum: " + dados
            + ". Campo que não consta vira [PENDENTE: <campo>].",
        ))
    return saida


# ------------------------------------------------------------------ pedidos

def _itens_de_pedidos(secoes: list[dict[str, Any]], codigo: str = "CLAIMS") -> list[str]:
    s = _secao(secoes, codigo)
    return [m.group(2).strip() for m in _ITEM.finditer(str((s or {}).get("content") or ""))]


def _pedidos(secoes: list[dict[str, Any]], plano: dict[str, Any]) -> list[Violacao]:
    saida: list[Violacao] = []
    itens = _itens_de_pedidos(secoes)
    tokens = [pp._tokens(i[:200]) for i in itens]  # noqa: SLF001
    for a in range(len(itens)):
        for b in range(a + 1, len(itens)):
            if pp._jaccard(tokens[a], tokens[b]) >= 0.55:  # noqa: SLF001
                saida.append(_achado("PEDIDO_DUPLICADO", "CLAIMS", itens[b], "O mesmo pedido aparece duas vezes na seção de pedidos.",
                                     "Mantenha um só e funda os fundamentos; a seção é montada a partir do plano estruturado."))
    por_id = plano.get("pedidos") or []
    uso: dict[str, int] = {}
    for texto, tk in zip(itens, tokens):
        melhor, pontos = None, 0.0
        for p in por_id:
            s = pp._jaccard(tk, pp._tokens(f"{p['tipo']} {p['objeto']} {p['fundamento']}"))  # noqa: SLF001
            if s > pontos:
                melhor, pontos = p, s
        if melhor is None or pontos < 0.12:
            saida.append(_achado("PEDIDO_FORA_DO_PLANO", "CLAIMS", texto, "Pedido que não nasce de nenhuma tese do plano do caso (possível pedido trazido de outra petição).",
                                 "Remova: pedido só existe se decorre de tese fundamentada com fatos DESTE caso."))
        else:
            uso[melhor["id"]] = uso.get(melhor["id"], 0) + 1
    for id_, n in uso.items():
        if n > 1:
            saida.append(_achado("PEDIDO_DUPLICADO", "CLAIMS", id_, f"O pedido {id_} do plano foi escrito {n} vezes.", "Um pedido do plano, uma linha na seção."))
    teses = {t["id"]: t for t in plano.get("teses") or []}
    for p in por_id:
        if p["de_praxe"]:
            continue
        tese = teses.get(p["tese_origem"])
        if not tese:
            saida.append(_achado("PEDIDO_SEM_TESE", "CLAIMS", f"{p['id']} {p['tipo']}", "Pedido sem tese de origem.", "Vincule a uma tese fundamentada ou remova."))
        elif not tese["fatos_ids"]:
            saida.append(_achado("PEDIDO_SEM_FATO_NO_CASO", "CLAIMS", f"{p['id']} {p['tipo']}", f"A tese {tese['id']} do pedido não tem nenhum fato do caso que a sustente.",
                                 "Sem fato do caso não há pedido — nunca aproveite pedido de peça antiga."))
        if not p["fundamento"]:
            saida.append(_achado("PEDIDO_SEM_FUNDAMENTO", "CLAIMS", f"{p['id']} {p['tipo']}", "Pedido sem fundamento registrado.", "Registre o fundamento legal/tese.", False))
    return saida


# ------------------------------------------------------------------ fontes: nada do acervo como fato do caso

def _contaminacao(secoes: list[dict[str, Any]], texto_do_caso: str, textos_do_acervo: list[str]) -> list[Violacao]:
    saida: list[Violacao] = []
    acervo = "\n".join(textos_do_acervo)
    if not acervo:
        return saida
    vistos: set[str] = set()
    for s in secoes:
        for m in sorted(_especificos(str(s.get("content") or ""))):
            if m in vistos or _presente(m, texto_do_caso):
                continue
            if _presente(m, acervo):
                vistos.add(m)
                saida.append(_achado("CONTAMINACAO_DO_ACERVO", str(s.get("code")), m,
                                     f"«{m}» aparece na peça, não consta dos documentos/entrevista do caso e consta de petição do acervo (outro cliente).",
                                     "Retire ou troque pelo dado do caso atual; peça do acervo é inspiração de argumento, nunca fonte de fato, valor ou data."))
    return saida


# ------------------------------------------------------------------ isolamento entre teses

def _isolamento(secoes: list[dict[str, Any]], plano: dict[str, Any]) -> list[Violacao]:
    saida: list[Violacao] = []
    teses = plano.get("teses") or []
    if len(teses) < 2:
        return saida
    por_id = {f["id"]: f for f in plano["fatos"]}
    comuns = pp.fatos_comuns(plano)

    def especificos(ids: set[str]) -> set[str]:
        return set().union(*[_especificos(f"{por_id[i]['data']} {por_id[i]['fato']}") for i in ids if i in por_id]) if ids else set()

    for s in secoes:
        if s.get("code") in ("HEADING", "CLOSING", "VALUE", "CLAIMS"):
            continue
        for t in dividir_em_topicos(str(s.get("content") or "")):
            tese = pp.tese_do_topico(plano, t["titulo"], t["corpo"]) if t["titulo"] else None
            if not tese or not tese.get("fatos_ids"):
                continue  # sem fatos declarados a tese não tem contra o que ser julgada (o plano é que está incompleto)
            proprios = set(tese.get("fatos_ids") or []) | comuns
            permitidos = especificos(proprios)
            de_outras = especificos({i for o in teses if o["id"] != tese["id"] for i in (o.get("fatos_ids") or [])} - proprios)
            for m in sorted(_especificos(t["corpo"]) & de_outras - permitidos):
                saida.append(_achado("MISTURA_DE_TESES", str(s.get("code")), f"{t['titulo'][:50]}: {m}",
                                     f"«{m}» é dado de OUTRA tese e aparece no tópico «{t['titulo'][:60]}» ({tese['id']}), cujos fatos não o incluem.",
                                     "Retire o dado deste tópico ou, se o fato realmente serve às duas teses, declare-o nas duas no plano."))
    return saida


# ------------------------------------------------------------------ coerência

def _coerencia(secoes: list[dict[str, Any]], texto_do_caso: str) -> list[Violacao]:
    saida: list[Violacao] = []
    for s in secoes:
        for m in re.finditer(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", str(s.get("content") or "")):
            if pp._so_digitos(m.group(0)) not in pp._so_digitos(texto_do_caso):  # noqa: SLF001
                saida.append(_achado(
                    "CPF_CNPJ_SEM_ORIGEM", str(s.get("code")), m.group(0),
                    f"{m.group(0)} não consta dos documentos deste caso (é dado de outro processo ou do modelo).",
                    "Troque pelo CNPJ/CPF que está na CAT, no contracheque ou no documento de identidade. Não copie filial, endereço ou número de outra peça.",
                ))
    return saida


_CIDADE_UF = re.compile(r"\b([A-Za-zÀ-ÿ][\wÀ-ÿ'-]{3,})\s*[-/–—]\s*[A-Z]{2}\b")
_REAIS = re.compile(r"R\$\s*([\d.]+,\d{2})")
_NAO_CIDADE = {"oab", "cpf", "cnpj", "cep"}


def _reais(valor: str) -> float:
    return float(valor.replace(".", "").replace(",", "."))


def revisao_de_protocolo(secoes: list[dict[str, Any]], texto_dos_autos: str) -> list[Violacao]:
    """O que a revisão humana marcou como impedimento de protocolo, em código.

    Cidade e número só valem se estiverem no OCR dos autos — não no outline,
    no acervo nem no cadastro de outro caso. Valores da mesma indenização têm
    de ser um só. Pedido condenatório sem valor não se salva com art. 322 nem
    com [PENDENTE].
    """
    saida: list[Violacao] = []
    autos_norm = pp.norm(texto_dos_autos)
    texto_todo = "\n".join(str(s.get("content") or "") for s in secoes)
    abertura = str((secoes[0].get("content") if secoes else "") or "")

    for m in _CIDADE_UF.finditer(abertura):
        cidade = pp.norm(m.group(1))
        if not cidade or cidade in _NAO_CIDADE or cidade in autos_norm:
            continue
        saida.append(_achado(
            "CIDADE_DE_OUTRO_CASO", str(secoes[0].get("code") or "HEADING"), m.group(0),
            f"«{m.group(0)}» está na qualificação e não aparece nos documentos deste caso.",
            "Use a cidade da CAT, do comprovante de residência ou do contracheque. Não reaproveite endereço de outra peça (ex.: Tucuruí quando o fato é em Belém).",
        ))

    for s in secoes:
        conteudo = str(s.get("content") or "")
        for frase in re.split(r"[.\n]", conteudo):
            if not re.search(r"desconto|imposto de renda|contribui[cç]|seguro|\birrf\b|\bir\b", frase, re.IGNORECASE):
                continue
            for valor in _REAIS.findall(frase):
                digitos = re.sub(r"\D", "", valor)
                if digitos and digitos not in re.sub(r"\D", "", texto_dos_autos):
                    saida.append(_achado(
                        "VALOR_DE_CONTRACHEQUE_SEM_LASTRO", str(s.get("code")), f"R$ {valor}",
                        f"R$ {valor} é citado como desconto/encargo e não está nos contracheques deste caso.",
                        "Copie o valor do mês correspondente e diga qual contracheque (mês). Não misture junho, julho e agosto.",
                    ))

        for paragrafo in re.split(r"\n\s*\n", conteudo):
            if re.search(r"incidente de resolu[cç][aã]o de demandas repetitivas|\bIRDR\b", paragrafo, re.IGNORECASE) and re.search(
                r"\bTST\b|Tema\s*n", paragrafo, re.IGNORECASE
            ):
                saida.append(_achado(
                    "INSTITUTO_ERRADO", str(s.get("code")), paragrafo[:160],
                    "Tema do TST foi chamado de incidente de resolução de demandas repetitivas (IRDR). O instituto é o IRR.",
                    "Escreva Incidente de Recursos de Revista Repetitivos (IRR). IRDR é outro incidente, de tribunal regional.",
                ))
            if re.search(r"tema\s*n?[ºo°.]?\s*21\b", paragrafo, re.IGNORECASE) and re.search(r"aloysio", paragrafo, re.IGNORECASE):
                saida.append(_achado(
                    "RELATOR_DO_TEMA_21", str(s.get("code")), paragrafo[:180],
                    "O Tema 21/TST foi atribuído ao Min. Aloysio Corrêa da Veiga. Ele é relator do Tema 84, não do Tema 21.",
                    "Tema 21: relator Min. Breno Medeiros, redator designado Min. Alberto Bastos Balazeiro. Não invente relator.",
                ))
            juros = re.search(r"correcao.{0,80}883", pp.norm(paragrafo))
            if juros and "juro" not in juros.group(0):
                saida.append(_achado(
                    "JUROS_CITADOS_COMO_CORRECAO", str(s.get("code")), paragrafo[:180],
                    "O art. 883 da CLT foi citado como fundamento da correção monetária. Ele trata de juros.",
                    "Juros desde o ajuizamento: art. 883 da CLT. Correção do dano moral: desde o evento lesivo, Súmula 439 do TST — não desde o ajuizamento pelo art. 883.",
                ))
            if re.search(r"m[eé]dico do trabalho da (?:pr[oó]pria )?reclamada|m[eé]dico da pr[oó]pria reclamada", paragrafo, re.IGNORECASE):
                if "medico do trabalho" not in autos_norm and "medico da reclamada" not in autos_norm:
                    saida.append(_achado(
                        "MEDICO_ATRIBUIDO_A_RECLAMADA", str(s.get("code")), paragrafo[:180],
                        "A peça diz que o médico é do trabalho da reclamada. Os documentos não dizem isso.",
                        "Diga o nome e a clínica como no documento (ex.: Brasmede). Não afirme vínculo com a ECT sem documento.",
                    ))
            if re.search(r"continuidade do tratamento|cl[ií]nica de psiquiatria", paragrafo, re.IGNORECASE):
                trecho_norm = pp.norm(paragrafo)
                if "continuidade do tratamento" in trecho_norm and "continuidade" not in autos_norm:
                    saida.append(_achado(
                        "RECEITA_ALEM_DO_DOCUMENTO", str(s.get("code")), paragrafo[:180],
                        "A peça afirma continuidade de tratamento psiquiátrico que o documento não registra.",
                        "Descreva só o que a receita diz (data, se houver, e a especialidade escrita no papel). Clínica de dependência química não vira prova de tratamento psiquiátrico contínuo.",
                    ))
                elif "clinica de psiquiatria" in trecho_norm and "psiquiatria" not in autos_norm:
                    saida.append(_achado(
                        "RECEITA_ALEM_DO_DOCUMENTO", str(s.get("code")), paragrafo[:180],
                        "A peça chama o serviço de clínica de psiquiatria. Isso não está no documento.",
                        "Use a especialidade que o papel declara. Não reclassifique o documento.",
                    ))
            if re.search(r"\bart\.?\s*322\b", paragrafo, re.IGNORECASE) and re.search(r"\bCPC\b|pedido gen[eé]ric|PENDENTE", paragrafo, re.IGNORECASE):
                saida.append(_achado(
                    "PEDIDO_GENERICO_ART_322", str(s.get("code")), paragrafo[:180],
                    "O art. 322 do CPC foi usado para justificar pedido sem valor. Ele trata de interpretação do pedido, não de pedido genérico.",
                    "Pedido de pagamento sem valor documental sai da peça. Art. 840, §1º, da CLT. A lacuna fica só no relatório interno, sem [PENDENTE] no corpo.",
                ))

    quant = ""
    for s in secoes:
        for topico in dividir_em_topicos(str(s.get("content") or "")):
            if re.search(r"quantifica", topico["titulo"], re.IGNORECASE):
                quant += "\n" + topico["corpo"]
    valores_quant = [_reais(v) for v in _REAIS.findall(quant)]
    item_moral = next((i for i in _itens_de_pedidos(secoes) if re.search(r"dano moral", i, re.IGNORECASE)), "")
    valores_pedido = [_reais(v) for v in _REAIS.findall(item_moral)]
    if valores_quant and valores_pedido and abs(max(valores_quant) - valores_pedido[0]) > 0.05:
        saida.append(_achado(
            "VALORES_DA_INDENIZACAO_DIVERGENTES", "CLAIMS", item_moral[:160],
            f"A quantificação chega a R$ {max(valores_quant):,.2f} e o pedido de dano moral pede R$ {valores_pedido[0]:,.2f}.",
            "Um só quantum, o mesmo na fundamentação, no pedido e no valor da causa. TEPT agrava esse único pedido pelo art. 944 do CC; não é segunda indenização nem outro multiplicador.",
        ))
    morais = [i for i in _itens_de_pedidos(secoes) if re.search(r"dano moral|indeniza[cç][aã]o por dano", i, re.IGNORECASE)]
    if len(morais) >= 2:
        saida.append(_achado(
            "BIS_IN_IDEM_DANO_MORAL", "CLAIMS", morais[1][:160],
            "Há mais de um pedido de indenização por dano moral. O TEPT não é segunda condenação.",
            "Um pedido só. A gravidade (TEPT, sequela) entra na quantificação pelo art. 944 do CC, como majoração do mesmo dano, sem valor autônomo.",
        ))

    norm_todo = pp.norm(texto_todo)
    faltam = []
    if not re.search(r"\bcita", norm_todo):
        faltam.append("citação da reclamada (art. 841 da CLT)")
    if not re.search(r"\brito\b", norm_todo):
        faltam.append("rito processual")
    if "comunicac" not in norm_todo:
        faltam.append("comunicações processuais (art. 272, §5º, do CPC e Súmula 427 do TST)")
    if "procedencia" not in norm_todo:
        faltam.append("procedência dos pedidos")
    if "intimacao exclusiva" not in norm_todo and "exclusivamente em nome" not in norm_todo:
        faltam.append("intimação exclusiva em nome do advogado")
    if faltam:
        saida.append(_achado(
            "PEDIDOS_DE_PRAXE_AUSENTES", "CLAIMS", "; ".join(faltam)[:200],
            "Faltam requerimentos obrigatórios da inicial: " + "; ".join(faltam) + ".",
            "Inclua, uma vez: comunicações processuais na preliminar; nos pedidos, citação, rito, intimação exclusiva em nome do advogado e procedência. Um só fechamento, depois do valor da causa.",
        ))
    return saida


def lintar(
    secoes: list[dict[str, Any]], plano: dict[str, Any], *, texto_do_caso: str, textos_do_acervo: list[str], params: dict[str, Any],
    texto_dos_autos: str = "",
) -> list[Violacao]:
    """Achados do linter (BLOQUEANTES e avisos), na ordem: estrutura, pedidos, fontes, teses, coerência.

    `texto_dos_autos` é o OCR deste caso, sem outline e sem acervo. CPF, CNPJ e
    cidade conferem contra ele. Sem esse argumento, vale `texto_do_caso`.
    """
    autos = texto_dos_autos or texto_do_caso
    plano = {**plano, "_fontes": [texto_do_caso]}
    return [
        *_estrutura_e_qualificacao(secoes, plano, params),
        *_pedidos(secoes, plano),
        *_contaminacao(secoes, texto_do_caso, textos_do_acervo),
        *_isolamento(secoes, plano),
        *_coerencia(secoes, autos),
        *revisao_de_protocolo(secoes, autos),
    ]


def deve_imprimir_rotulo(rotulo: str, conteudo: str) -> bool:
    """Decisão ÚNICA (renderer e auditoria) de imprimir o título da seção."""
    if not rotulo or not conteudo.strip():
        return False
    primeira = conteudo.lstrip().split("\n", 1)[0].strip()
    if primeira.startswith(":::") or re.match(r"^#\s", primeira):
        return False
    return rotulo.casefold() not in primeira.casefold()


def titulos_impressos(secoes: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Os títulos de capítulo NA ORDEM em que saem no documento (rótulo impresso ou `# ` do conteúdo)."""
    saida = []
    for s in secoes:
        rotulo, conteudo = str(s.get("label") or "").strip(), str(s.get("content") or "")
        if deve_imprimir_rotulo(rotulo, conteudo):
            saida.append((str(s.get("code")), rotulo))
        primeira = conteudo.lstrip().split("\n", 1)[0].strip()
        if re.match(r"^#\s", primeira):
            saida.append((str(s.get("code")), primeira))
    return saida
