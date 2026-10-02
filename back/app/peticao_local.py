"""Petição inicial gerada no Acervo — entrevista + OCR, sem agente."""

from __future__ import annotations

import contextvars
import functools
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor
from concurrent.futures import wait as futures_wait
import io
import json
import statistics
import time
from contextvars import ContextVar
import logging
import os
import re
import unicodedata
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
from xml.etree import ElementTree

import httpx

from . import (
    analise_documentos,
    armazenamento,
    case_brief,
    analise_documental,
    conferencia_peticao,
    custos_api,
    jurimetria_caso,
    peticao_aprendizado,
    peticao_criticas,
    peticao_migracao_legado,
    auditor_final,
    auditoria_estrutural,
    document_ledger,
    documento_final,
    case_facts,
    contrato_secoes,
    petition_linter,
    plano_da_peticao,
    recuperacao_por_secao,
    recuperacao_por_tese,
    peticao_skill_arquivos,
    peticao_skills,
    rag,
    skill_peticao,
    tribunais,
)
from . import casos as casos_ocr
from . import juridico
from .juridico import atualizacao as juridico_atualizacao
from .juridico import auditores as juridico_auditores
from .juridico import autoridades as juridico_aut
from .juridico import orquestrador as juridico_orq
from .juridico import raciocinio as juridico_raciocinio
from .juridico import render as juridico_render
from .juridico import repositorio as juridico_repo
from .juridico import teses as juridico_teses
from .juridico import imutabilidade as juridico_imutabilidade

log = logging.getLogger("peticao_local")

#: Diagnóstico da geração em curso (por thread/tarefa). Cada etapa de contexto que
#: pode falhar em silêncio — precedentes, legislação, acervo — registra AQUI o que
#: aconteceu, inclusive o motivo da falha. Antes só sobrava um booleano "veio ou não
#: veio": uma peça saída SEM o acervo dizia "o acervo não respondeu", sem dizer por
#: quê, e ninguém conseguia distinguir chave sem crédito de banco fora do ar.
#: Texto do caso corrente: a skill escolhe o arquivo de assunto pelo que o caso DIZ.
_TEXTO_DO_CASO: contextvars.ContextVar[str] = contextvars.ContextVar("texto_do_caso", default="")

_DIAG: ContextVar[dict[str, Any] | None] = ContextVar("peticao_diag", default=None)


def _diag(canal: str, **dados: Any) -> None:
    corrente = _DIAG.get()
    if corrente is not None:
        corrente.setdefault("recuperacao", {}).setdefault(canal, {}).update(dados)


#: Sinais de que o SISTEMA (e não a skill) voltou a ditar estrutura de peça no prompt final.
_SINAIS_DE_ESTRUTURA_FIXA = (
    "ONDE CADA COISA ENTRA",
    '"label":"Dos fatos"',
    '"label": "Dos fatos"',
    '"code":"LEGAL_GROUNDS","label"',
    "ENDEREÇAMENTO (seção HEADING)",
)


def _estrutura_fixa_no_prompt(instrucao: str) -> list[str]:
    return [sinal for sinal in _SINAIS_DE_ESTRUTURA_FIXA if sinal in instrucao]


def pureza_da_skill(nome_categoria: str = "", codigo_categoria: str = "", texto_caso: str = "") -> dict[str, Any]:
    """Modo diagnóstico: de onde vêm as instruções de uma geração, sem gerar nada.

    Monta a instrução exatamente como `gerar` (mesmas funções) e procura sinais de que o
    SISTEMA voltou a ditar estrutura. Esperado numa geração pura: skill carregada,
    `formatacao.md` carregada, skill legada fora, nenhuma estrutura fixa, nenhum template.
    """
    resumo = peticao_skill_arquivos.resumo(nome_categoria, codigo_categoria, texto_caso)
    cfg = peticao_skill_arquivos.configuracao_visual_padrao()
    try:
        legada_cadastrada = bool(peticao_skills.instrucoes_gerais().strip())
    except Exception:  # noqa: BLE001 — diagnóstico não pode falhar por causa do banco
        legada_cadastrada = None
    prompt_do_motor = CONTRATO_DE_REDACAO + _INSTRUCAO_REVISAO + _INSTRUCAO_CONFERENCIA
    skill_carregada = peticao_skill_arquivos.carregar(nome_categoria, codigo_categoria, texto_caso)
    sinais = _estrutura_fixa_no_prompt(prompt_do_motor)
    return {
        "active_skill": resumo["skill"],
        "skill_loaded": resumo["carregada"],
        "skill_files_loaded": resumo["arquivos"],
        "skill_version": resumo["sha256"],
        "formatacao_loaded": "formatacao.md" in resumo["arquivos"],
        "estilos_definidos_pela_skill": sorted((cfg.get("estilos") or {}).keys()),
        "layout_rules_source": cfg.get("fonte_das_regras"),
        "renderer_defaults_used": cfg.get("campos_sem_definicao"),
        "legacy_skill_configured_in_db": legada_cadastrada,
        # Com skill de arquivo carregada a legada NÃO entra (ver `_com_skill_do_escritorio`).
        "legacy_skill_loaded": bool(legada_cadastrada) and not skill_carregada,
        "legacy_prompt_loaded": False,
        "hardcoded_structure_detected": bool(sinais),
        "hardcoded_structure_signals": sinais,
        "external_template_loaded": False,
        "generation_instruction_sources": [
            "motor: CONTRATO_DE_REDACAO (integridade de dados + formato JSON)",
            *[f"skill: references/{a}" for a in resumo["arquivos"]],
        ],
    }


def _cadastro_estruturado(caso_id: str) -> dict[str, Any]:
    try:
        q = armazenamento.obter_qualificacao(caso_id) or {}
    except Exception:  # noqa: BLE001
        q = {}
    caso = armazenamento.obter_caso(caso_id) or {}
    dados = {k: v for k, v in q.items() if v}
    if caso.get("cliente"):
        dados.setdefault("nome", caso["cliente"])
    # Fixture / dado de teste NÃO pode virar identidade do autor (v15: «BEZERRA TESTE»).
    # Sem isso o CASE_FACTS trata o cadastro como fonte e a peça oscila entre versões.
    nome = str(dados.get("nome") or "")
    if re.search(r"\bTESTE\b", nome, re.IGNORECASE) or "(TESTE)" in nome.upper():
        log.error(
            "petição local: cadastro do caso %s tem nome de teste «%s» — ignorado; use documentos/entrevista",
            caso_id,
            nome,
        )
        dados = {k: v for k, v in dados.items() if k != "nome"}
    return dados


def _uf_jurisprudencia_do_caso(caso_id: str, contexto: str = "") -> str:
    """UF do foro a partir do cadastro do caso, com OCR/entrevista só como reserva.

    A jurisdição não é uma preferência do escritório: é atributo do processo.
    Priorizar o dado estruturado evita que a cidade de um médico, de uma empresa
    ou de um documento de terceiro desvie a pesquisa para outro TRT.
    """
    try:
        qualificacao = armazenamento.obter_qualificacao(caso_id) or {}
        caso = armazenamento.obter_caso(caso_id) or {}
    except Exception:  # noqa: BLE001 - busca ainda pode inferir o local do material do caso
        qualificacao, caso = {}, {}
    for dados in (caso, qualificacao):
        for campo in ("uf", "estado", "foro_uf", "vara_uf"):
            uf = tribunais.normalizar_uf(dados.get(campo))
            if uf:
                return uf
    return jurimetria_caso._detectar_uf(contexto)  # noqa: SLF001 - fallback do próprio motor territorial


_DOC_PRIORITARIO = re.compile(
    r"contracheque|holerite|folha\s+de\s+pagamento|cat\b|comunicado\s+de\s+acidente|"
    r"boletim|bo\b|ctps|carteira\s+de\s+trabalho|\brg\b|cnh|identidade|atestado|"
    r"laudo|cnis|ppp\b|procura[cç][aã]o|contrato\s+de\s+trabalho",
    re.IGNORECASE,
)


def _indice_e_textos_documentais(
    ledger: list[dict[str, Any]], documentos: list[dict[str, str]], *, max_docs_texto: int = 60, max_chars: int = 100_000,
    max_chars_leituras: int = 40_000,
) -> list[str]:
    """Índice COMPLETO (todos os números) + texto OCR priorizado.

    A v15 afirmava que contracheques «não integram os documentos» porque o
    dump cortava em 20 e o modelo não via a lista canônica. O índice sempre
    lista Documento NN → arquivo/tipo; o texto completo prioriza
    contracheque/CAT/BO/CTPS etc. dentro do orçamento de caracteres.
    """
    por_arquivo = {d["arquivo"]: d for d in documentos}
    linhas = [
        "=== ÍNDICE CANÔNICO DE DOCUMENTOS (use EXATAMENTE estes números; "
        "documento listado AQUI existe — não diga que «não integra» os autos) ===",
    ]
    for item in ledger:
        tipo = (item.get("document_type") or "").strip()
        rotulo = item["canonical_label"]
        arquivo = item["canonical_file"]
        extra = f" — {tipo}" if tipo else ""
        linhas.append(f"{rotulo}{extra}: {arquivo}")
    if not ledger:
        return linhas

    leituras = []
    usado_leituras = 0
    for item in ledger:
        leitura = str((por_arquivo.get(item["canonical_file"]) or {}).get("leitura") or "").strip()
        if not leitura:
            continue
        bloco = f"\n--- {item['canonical_label'].upper()} ---\n{leitura}"
        if usado_leituras + len(bloco) > max_chars_leituras:
            break
        leituras.append(bloco)
        usado_leituras += len(bloco)
    if leituras:
        linhas.append(
            "\n=== O QUE A LEITURA DE CADA DOCUMENTO ENCONTROU (dados já extraídos; "
            "use TODOS os que servirem aos fatos e pedidos, citando o número do documento) ==="
        )
        linhas.extend(leituras)

    linhas.append(
        "\n=== TEXTOS EXTRAÍDOS (OCR) — prioridade a prova de remuneração, "
        "acidente, identidade e afastamento ==="
    )
    linhas.append(document_ledger.aviso_de_copias(ledger))

    def peso(item: dict[str, Any]) -> tuple[int, int]:
        chave = f"{item.get('document_type', '')} {item.get('canonical_file', '')}"
        return (0 if _DOC_PRIORITARIO.search(chave) else 1, item.get("numero", 999))

    ordenados = sorted(ledger, key=peso)
    usados = 0
    chars = 0
    for item in ordenados:
        if usados >= max_docs_texto:
            break
        doc = por_arquivo.get(item["canonical_file"])
        if not doc or not doc.get("texto"):
            continue
        bloco = f"\n--- {item['canonical_label'].upper()}: {doc['arquivo']} ---\n{doc['texto']}"
        if chars + len(bloco) > max_chars and usados > 0:
            # Ainda assim garante contracheques/CAT se ainda não entraram
            if _DOC_PRIORITARIO.search(f"{item.get('document_type', '')} {item['canonical_file']}"):
                if chars + len(bloco) > max_chars + 20_000:
                    continue
            else:
                continue
        linhas.append(bloco)
        chars += len(bloco)
        usados += 1
    omitidos = len(ledger) - usados
    if omitidos > 0:
        linhas.append(
            f"\n({omitidos} documento(s) lógico(s) constam só no ÍNDICE acima — "
            "existem nos autos; cite-os pelo número do índice quando relevantes.)"
        )
    return linhas


def _fatos_documentais(caso_id: str) -> list[dict[str, Any]]:
    try:
        registro = analise_documental.obter(caso_id)
    except Exception:  # noqa: BLE001
        return []
    resultado = registro.get("resultado") if registro and registro.get("status") == "ready" else None
    if not isinstance(resultado, dict):
        return []
    return [f for f in (resultado.get("fatos_extraidos") or []) if isinstance(f, dict) and f.get("estado") != "REJECTED"]


def _dados_por_documento(caso_id: str) -> dict[str, dict[str, Any]]:
    """arquivo → {tipo, dados:[(papel, campo, valor)]} extraídos pela análise documental (dado estruturado de UM documento)."""
    try:
        registro = analise_documental.obter(caso_id)
    except Exception:  # noqa: BLE001
        return {}
    resultado = registro.get("resultado") if registro and registro.get("status") == "ready" else None
    if not isinstance(resultado, dict):
        return {}
    campos = {"nome": ("autor", "nome"), "cpf": ("autor", "cpf"), "rg": ("autor", "rg"), "endereco": ("autor", "endereco"), "endereço": ("autor", "endereco"),
              "cnpj": ("reu", "cnpj"), "cargo": ("autor", "cargo"), "funcao": ("autor", "cargo"), "função": ("autor", "cargo"),
              "data de admissao": ("autor", "data_admissao"), "data de admissão": ("autor", "data_admissao")}
    saida: dict[str, dict[str, Any]] = {}
    for d in resultado.get("documentos") or []:
        if not isinstance(d, dict) or not d.get("arquivo"):
            continue
        dados = []
        for c in d.get("dados_principais") or []:
            if not isinstance(c, dict):
                continue
            chave = str(c.get("campo") or "").strip().lower()
            if chave in campos and c.get("valor"):
                dados.append((*campos[chave], c["valor"]))
        saida[d["arquivo"]] = {"tipo": d.get("tipo", ""), "dados": dados}
    return saida


def _redigir_pedidos_do_plano(caso_id: str, plano_est: dict[str, Any]):
    """Callable que dá ao renderizador a REDAÇÃO de cada pedido do plano (o modelo não escolhe os pedidos)."""
    def redigir(pedidos: list[dict[str, Any]]) -> dict[str, Any]:
        instrucao = _com_skill_do_escritorio(caso_id, (
            "Você redige a seção de PEDIDOS de uma peça, seguindo a skill (forma, valores, pedidos de praxe). "
            "Recebe a lista ÚNICA de pedidos do plano; redija UM texto para cada id, sem criar, juntar, dividir "
            "nem omitir pedidos. Preserve valores e critérios (`valor_ou_base`). O valor do dano moral é UM SÓ, "
            "igual ao da quantificação; TEPT agrava esse pedido pelo art. 944 do CC e não vira segunda indenização. "
            "Pedido de pagamento sem valor nos documentos NÃO entra: não use [PENDENTE] nem o art. 322 do CPC para "
            "deixá-lo genérico (art. 840, §1º, da CLT). Inclua no fecho, uma vez: citação da reclamada, rito, "
            "intimação exclusiva em nome do advogado e procedência. Cada pedido é a CONSEQUÊNCIA, em uma frase, com o "
            "fundamento entre parênteses: NÃO reproduza a argumentação nem requerimentos já desenvolvidos noutras seções (provas, comunicações, "
            "gratuidade, competência): para esses, só a referência. Devolva APENAS JSON: "
            '{"abertura":"frase de abertura da seção conforme a skill","itens":{"P01":"texto do pedido sem a letra da alínea"},'
            '"fecho":"frase final da seção conforme a skill, ou vazio"}.'
        ))
        try:
            return _llm_json(instrucao, json.dumps({"pedidos": pedidos, "partes": plano_est.get("partes")}, ensure_ascii=False), timeout=240.0)
        except ErroPeticao:
            log.warning("petição local: redação dos pedidos falhou; usando o texto do plano", exc_info=True)
            return {}
    return redigir


def _similaridade_de_pedidos(a: str, b: str) -> float:
    try:
        va, vb = rag.gerar_embeddings([a, b])
        num = sum(x * y for x, y in zip(va, vb))
        den = (sum(x * x for x in va) ** 0.5) * (sum(y * y for y in vb) ** 0.5)
        return num / den if den else 0.0
    except Exception:  # noqa: BLE001 - sem embeddings, só a deduplicação determinística
        return 0.0


def _pedidos_do_plano_na_secao(caso_id: str, secoes: list[dict[str, Any]], plano_est: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """A seção de pedidos é RENDERIZADA do plano (fonte única), depois de deduplicar por tipo/tese/objeto/base."""
    if not plano_est.get("pedidos"):
        return secoes, {"aplicado": False, "motivo": "o plano não trouxe pedidos"}

    def juiz(u: dict[str, Any], p: dict[str, Any]) -> bool:
        try:
            saida = _llm_json(
                "Dois pedidos de uma petição parecem iguais. Diga se são o MESMO pedido (sem diferença juridicamente relevante de "
                'objeto, período, base de cálculo, beneficiário ou natureza). JSON: {"mesmo_pedido": true|false, "motivo": ""}',
                json.dumps({"a": u, "b": p}, ensure_ascii=False), timeout=90.0)
            return bool(saida.get("mesmo_pedido"))
        except ErroPeticao:
            return False  # na dúvida NÃO elimina pedido legítimo

    unicos, fundidos = plano_da_peticao.deduplicar(plano_est["pedidos"], similaridade=_similaridade_de_pedidos, adjudicar=juiz)
    plano_est["pedidos"] = unicos
    plano_est["pedidos_fundidos"] = fundidos
    texto, rel = plano_da_peticao.renderizar_pedidos(plano_est, _redigir_pedidos_do_plano(caso_id, plano_est))
    novas, achou = [], False
    for x in secoes:
        if x.get("code") == "CLAIMS":
            novas.append({**x, "content": texto})
            achou = True
        else:
            novas.append(x)
    if not achou:
        pos = next((i for i, x in enumerate(novas) if x.get("code") in ("VALUE", "CLOSING")), len(novas))
        novas.insert(pos, {"code": "CLAIMS", "label": "", "content": texto, "formato": 2})
    return novas, {"aplicado": True, "fundidos": fundidos, **rel}


def _revisao_semantica_de_teses(caso_id: str, secoes: list[dict[str, Any]], plano_est: dict[str, Any]) -> list[Any]:
    """Revisão por LLM da mistura entre teses (a parte que o código não decide): devolve Violacoes de aviso."""
    from .conferencia_peticao import Violacao

    topicos = []
    for x in secoes:
        if x.get("code") in ("HEADING", "CLOSING", "VALUE", "CLAIMS"):
            continue
        for t in recuperacao_por_secao.dividir_em_topicos(str(x.get("content") or "")):
            if t["titulo"]:
                topicos.append({"secao": x.get("code"), "topico": t["titulo"], "texto": t["corpo"][:1800]})
    if len(plano_est.get("teses") or []) < 2 or not topicos:
        return []
    try:
        saida = _llm_json(
            "Você revisa uma petição tópico a tópico contra o PLANO (teses, fatos permitidos e pedidos). Para cada tópico responda: "
            "todos os fatos citados pertencem ou são relevantes para ESTA tese? algum fundamento jurídico pertence a outra tese? alguma "
            "jurisprudência é de outra matéria? algum pedido de outra tese apareceu aqui? há informação contraditória com outro tópico? "
            "Referências legítimas entre teses relacionadas e fato comum a várias teses NÃO são problema. "
            'Devolva APENAS JSON: {"problemas":[{"secao":"","topico":"","categoria":"fato_de_outra_tese|fundamento_de_outra_tese|'
            'jurisprudencia_de_outra_materia|pedido_indevido|contradicao","trecho":"","por_que":""}]} (lista vazia se não há).',
            json.dumps({"plano": {k: plano_est[k] for k in ("fatos", "teses", "pedidos")}, "topicos": topicos}, ensure_ascii=False)[:90_000],
            timeout=240.0)
    except ErroPeticao:
        return []
    return [
        Violacao("REVISAO_SEMANTICA_" + str(p.get("categoria", "")).upper(), str(p.get("secao") or ""), str(p.get("trecho") or "")[:220],
                 f"Revisão de isolamento entre teses: {p.get('por_que', '')}", "Retire ou reescreva o trecho para que fique só com o que pertence a esta tese.", False)
        for p in saida.get("problemas") or [] if isinstance(p, dict)
    ]


def _ocr_do_caso(caso_id: str) -> str:
    """Só o texto dos documentos deste caso. Outline, acervo e cadastro não entram."""
    try:
        _, docs = documentos_logicos(caso_id)
    except Exception:  # noqa: BLE001
        return ""
    return "\n".join(str(d.get("texto") or "") for d in docs)


def _lintar_e_corrigir(
    caso_id: str, secoes: list[dict[str, Any]], plano_est: dict[str, Any], *, texto_do_caso: str, textos_do_acervo: list[str],
    material: str = "", texto_dos_autos: str = "", permitir_mutacoes: bool = True,
) -> tuple[list[dict[str, Any]], list[Any], dict[str, Any]]:
    """AUDITOR FINAL: verificações determinísticas + auditoria semântica independente, com correção e limite de iterações."""
    params = peticao_skill_arquivos.validacoes_da_skill()["parametros"]
    cf = plano_est.get("case_facts") or {"PARTIES": {}, "UNCERTAINTIES": []}
    fontes = _fontes_da_conferencia(caso_id, material=material)

    autos = texto_dos_autos or _ocr_do_caso(caso_id) or texto_do_caso

    def verificacoes(sec: list[dict[str, Any]], plano: dict[str, Any]) -> list[Any]:
        return [
            *petition_linter.lintar(
                sec, plano, texto_do_caso=texto_do_caso, textos_do_acervo=textos_do_acervo, params=params,
                texto_dos_autos=autos,
            ),
            *auditoria_estrutural.auditar(sec, plano, params, petition_linter.titulos_impressos(sec), embed=lambda textos: rag.gerar_embeddings(textos, timeout=60)),
            *conferencia_peticao.conferir(sec, fontes),
        ]

    def chamar(instrucao: str, entrada: str) -> dict[str, Any]:
        if _sem_tempo(folga_s=180):
            return {}  # sem tempo: o auditor por modelo cede lugar às verificações determinísticas
        return _llm_json(instrucao, entrada, timeout=240.0)

    # No fluxo estrito, auditor é detector. Ele não reescreve prose nem troca o
    # ledger: uma mudança jurídica exige voltar ao planejador e criar um novo
    # PETITION_PLAN, com novo hash e rastreabilidade.
    if not permitir_mutacoes:
        achados = verificacoes(secoes, plano_est)
        semanticos = auditor_final.auditar_com_modelo(chamar, cf, plano_est, secoes,
                                                       [a for a in achados if a.codigo == "SOBREPOSICAO_SEMANTICA_CANDIDATA"])
        achados += semanticos
        criticos = [a for a in achados if a.bloqueia]
        return secoes, achados, {
            "iteracoes": [{"n": 1, "modo": "read_only", "criticos": [f"{a.codigo}:{a.secao}" for a in criticos]}],
            "pendencias_humanas": [f"{a.codigo}:{a.secao} — {a.motivo}"[:260] for a in criticos],
            "liberada": not criticos,
            "mutacoes_desligadas": True,
        }

    return auditor_final.executar(
        secoes, plano_est, cf, params=params, verificacoes=verificacoes, max_iteracoes=2,
        chamar=chamar,
        reescrever=lambda secao, orientacao: None if _sem_tempo(folga_s=150) else _reescrever_secao(caso_id, secao, orientacao, texto_do_caso),
        rerenderizar_pedidos=lambda sec, plano: _pedidos_do_plano_na_secao(caso_id, sec, plano)[0],
    )


def _validar_documento_final(
    caso_id: str, secoes: list[dict[str, Any]], plano_est: dict[str, Any], texto_do_caso: str, *, max_rodadas: int = 1,
    permitir_mutacoes: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[Any]]:
    """higieniza (determinístico) → valida o artefato final → corrige o que for corrigível → higieniza e valida de NOVO.

    A última coisa que acontece é SEMPRE higienizar+validar; o que sobrar de crítico vai para revisão humana (peça retida).
    """
    params = peticao_skill_arquivos.validacoes_da_skill()["parametros"]
    try:
        ledger, _ = documentos_logicos(caso_id)
    except Exception:  # noqa: BLE001
        ledger = []
    rel: dict[str, Any] = {"rodadas": []}
    for rodada in range(max_rodadas + 1):
        secoes, higiene = documento_final.higienizar(secoes, plano_est, params, texto_dos_autos=_ocr_do_caso(caso_id))
        achados = documento_final.validar_documento_final(secoes, plano_est, params, ledger)
        _, achados_contrato = contrato_secoes.canonicalizar(
            secoes, plano_est.get("contrato_secoes") or {}
        )
        achados += achados_contrato
        criticos = [a for a in achados if a.bloqueia]
        rel["rodadas"].append({"higiene": {k: (len(v) if isinstance(v, list) else v) for k, v in higiene.items()},
                               "criticos": [f"{a.codigo}:{a.secao}" for a in criticos]})
        if higiene.get("metadata_interna_removida"):
            rel.setdefault("metadata_interna", []).extend(higiene["metadata_interna_removida"])
        if not permitir_mutacoes or not criticos or rodada == max_rodadas or _sem_tempo(folga_s=120):
            break
        por_secao: dict[str, list[Any]] = {}
        for a in criticos:
            por_secao.setdefault(a.secao or "CLAIMS", []).append(a)
        if any(a.codigo in ("MAJORACAO_COMO_SEGUNDA_INDENIZACAO", "AGRAVANTE_COM_VALOR_PROPRIO", "MESMA_REPARACAO_DUAS_VEZES", "PEDIDOS_SOBREPOSTOS") for a in criticos):
            novos = auditor_final.revisar_ledger(lambda i, e: _llm_json(i, e, timeout=240.0), plano_est, criticos)
            if novos:
                plano_est["pedidos"] = novos
                secoes = _pedidos_do_plano_na_secao(caso_id, secoes, plano_est)[0]
        novas = []
        for x in secoes:
            do_x = por_secao.get(str(x.get("code")))
            texto = _reescrever_secao(caso_id, x, "CORRIJA EXATAMENTE (sem inventar; ausência de documento não é prova de ausência):\n" + "\n".join(
                f"- [{a.codigo}] {a.motivo} Trecho: {a.trecho}. Correção: {a.correcao}" for a in do_x), texto_do_caso) if do_x and x.get("code") != "CLAIMS" else None
            novas.append({**x, "content": texto} if texto else x)
        secoes = novas
    rel["pendencias_humanas"] = [f"{a.codigo}:{a.secao} — {a.motivo}"[:260] for a in achados if a.bloqueia]
    rel["checklist"] = [
        {"codigo": a.codigo, "secao": a.secao, "bloqueia": a.bloqueia,
         "resultado": "FALHOU", "motivo": a.motivo}
        for a in achados
    ]
    rel["liberada"] = not rel["pendencias_humanas"]
    return secoes, rel, achados


def _nome_da_secao(secao: dict[str, Any]) -> str:
    """Nome para MOSTRAR: o título do redator; sem título (a skill não deu), o papel da seção."""
    return str(secao.get("label") or str(secao.get("code") or "").replace("_", " ").title())


def _guardar_trechos(canal: str, trechos: list[Any]) -> None:
    """Os trechos recuperados, com metadados, para a camada jurídica converter em autoridades."""
    corrente = _DIAG.get()
    if corrente is not None:
        corrente.setdefault("_trechos", {})[canal] = list(trechos or [])


def _registrar_proveniencia(provs: list[Any], textos: list[str]) -> None:
    """Guarda, por item recuperado, o registro e o texto enviado (para medir influência depois)."""
    corrente = _DIAG.get()
    if corrente is None:
        return
    corrente.setdefault("proveniencia", []).extend(zip(provs, textos))


#: Orçamento de tempo de UMA geração. A tela espera 20 min; passado o limite "suave", as etapas
#: opcionais (aprofundamento por tópico, revisor de profundidade, auditor por modelo, correções) são
#: puladas e a peça segue direto para as validações DETERMINÍSTICAS e a gravação — melhor uma peça
#: validada e marcada para revisão do que uma geração que a tela abandona (o 504 da produção).
ORCAMENTO_SUAVE_S = float(os.getenv("PETICAO_ORCAMENTO_SUAVE_S", "780"))
_INICIO_DA_GERACAO: ContextVar[float | None] = ContextVar("inicio_da_geracao", default=None)


def _tempo_decorrido() -> float:
    inicio = _INICIO_DA_GERACAO.get()
    return time.monotonic() - inicio if inicio else 0.0


def _sem_tempo(folga_s: float = 0.0) -> bool:
    """True quando as etapas opcionais devem ser puladas para a geração caber no tempo da tela."""
    estourou = bool(_INICIO_DA_GERACAO.get()) and _tempo_decorrido() + folga_s > ORCAMENTO_SUAVE_S
    if estourou:
        corrente = _DIAG.get()
        if corrente is not None:
            corrente.setdefault("etapas_puladas_por_tempo", 0)
            corrente["etapas_puladas_por_tempo"] += 1
    return estourou


def _em_paralelo_com_contexto(funcao: Any, itens: list[Any], max_workers: int = 6) -> list[Any]:
    """`map` em threads PRESERVANDO os contextvars (diagnóstico, orçamento de tempo, texto do caso) em cada tarefa.

    Thread do pool não herda contextvars: sem copiar o contexto, o orçamento de tempo e o trace ficavam cegos
    justamente nas etapas paralelas.
    """
    if not itens:
        return []
    contextos = [contextvars.copy_context() for _ in itens]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(lambda par: par[0].run(funcao, par[1]), zip(contextos, itens)))


def _erro_curto(erro: BaseException) -> str:
    return f"{type(erro).__name__}: {str(erro)[:240]}"


def _tentar_etapa(nome: str, funcao: Any, fallback: Any, diag: dict[str, Any] | None = None) -> Any:
    """Uma etapa que falha não pode apagar a minuta já redigida.

    JSON do modelo e da análise documental às vezes traz `null` onde o código
    espera lista. Isso virava ``'NoneType' object is not iterable`` e a tela
    dizia que a petição não foi gerada, mesmo com o texto pronto.
    """
    try:
        return funcao()
    except Exception as erro:  # noqa: BLE001 - a peça segue; o motivo fica no trace
        log.exception("petição local: etapa '%s' falhou; a geração segue", nome)
        if diag is not None:
            diag.setdefault("fallbacks", []).append(f"{nome}: {_erro_curto(erro)}")
        return fallback

ID_LOCAL = "local"
#: Sobe a cada mudança no LAYOUT do .docx. `ler_docx` regrava o binário quando a
#: versão salva é menor (ver o fim do módulo): sem incrementar aqui, as petições
#: já geradas continuariam saindo com o layout antigo, e a mudança pareceria não
#: ter surtido efeito justamente em quem já tem peça no sistema.
#:
#: 5 — layout medido na petição de referência do escritório (Auxílio-Acidente,
#: 8 páginas): corpo serifado, margens 3,0 / 1,89 cm e texto começando em 4,66 cm,
#: abaixo do timbre.
#: 6 — recuo de 1,25 cm na primeira linha de cada parágrafo, medido na mesma
#: peça de referência (corpo em 3,0 cm, primeira linha em 4,25 cm), e negrito
#: inline no nome do autor.
#: 10 — formatação vinda do editor da tela (itálico, sublinhado, tamanho, cor e
#: alinhamento por parágrafo) interpretada no .docx.
DOCX_STYLE_VERSION = 10
LOGO_LARA_MELO = Path(__file__).with_name("assets") / "lara-melo-logo.png"

#: Solicitação em curso nesta thread (setada pelo POST 202). Sem isto cada etapa
#: de `gerar` não saberia qual linha de `solicitacoes_peticao` atualizar.
_SOLICITACAO_EM_CURSO: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "solicitacao_peticao", default=None
)

# Progresso ponderado, e não contagem de funções. A chamada ao redator e a
# conferência posterior são as fases que de fato consomem tempo; mostrar 7/8
# enquanto elas ainda trabalham fazia a barra prometer uma conclusão iminente.
PASSOS_GERACAO = 100


_EM_EXECUCAO: set[str] = set()
#: Passado este tempo sem concluir, a solicitação é dada como perdida (thread travada ou processo reiniciado).
LIMITE_SOLICITACAO_S = float(os.getenv("PETICAO_LIMITE_SOLICITACAO_S", "1500"))
_CARENCIA_ORFA_S = 20.0


def marcar_solicitacao_em_curso(solicitacao_id: str | None) -> contextvars.Token[str | None]:
    """Usado pela rota assíncrona: a thread de fundo aponta o progresso para este id."""
    if solicitacao_id:
        _EM_EXECUCAO.add(solicitacao_id)
    return _SOLICITACAO_EM_CURSO.set(solicitacao_id)


def limpar_solicitacao_em_curso(token: contextvars.Token[str | None]) -> None:
    _EM_EXECUCAO.discard(_SOLICITACAO_EM_CURSO.get() or "")
    _SOLICITACAO_EM_CURSO.reset(token)


def _solicitacao_perdida(solicitacao: dict[str, Any]) -> str:
    """A geração roda numa thread deste processo: reinício ou travamento deixam a linha em andamento para sempre."""
    try:
        idade = (datetime.now(timezone.utc) - datetime.fromisoformat(str(solicitacao.get("solicitada_em")))).total_seconds()
    except (TypeError, ValueError):
        return ""
    if idade > LIMITE_SOLICITACAO_S:
        return "A geração passou do tempo limite sem concluir. Gere a petição novamente."
    if idade > _CARENCIA_ORFA_S and str(solicitacao.get("id")) not in _EM_EXECUCAO:
        return "A geração foi interrompida (o servidor foi reiniciado durante a redação). Gere a petição novamente."
    return ""


def avancar_etapa(etapa: str, passo: int, total: int = PASSOS_GERACAO) -> None:
    """Grava o andamento para o polling da tela. Sem solicitação aberta, é no-op."""
    sid = _SOLICITACAO_EM_CURSO.get()
    if not sid:
        return
    try:
        armazenamento.atualizar_progresso_solicitacao(sid, etapa, passo, total)
    except Exception:  # noqa: BLE001 — progresso não pode derrubar a redação
        log.warning("petição local: falha ao gravar progresso solicitacao=%s", sid, exc_info=True)


def _fonte_padrao() -> str:
    """Fonte usada quando o escritório ainda não subiu um modelo visual próprio.

    Vem de `peticao_skill_arquivos` (extraída de `formatacao.md`), não mais
    fixa em Python — conferido contra a fonte REAL embutida no PDF da petição
    de referência do escritório (LiberationSans, a métrica livre do Arial):
    bate com o que a skill lista primeiro ("Arial ou Times New Roman"). Um
    valor fixo aqui ficava desatualizado quando o padrão do escritório mudava
    e ninguém lembrava de atualizar esta linha — foi o que aconteceu antes,
    quando esta constante dizia "Times New Roman" contra uma peça de
    referência mais antiga.
    """
    return str(peticao_skill_arquivos.configuracao_visual_padrao().get("fonte") or "Arial")


MODELO_VISUAL_GERAL = "peticao_visual_geral"
MODELO_VISUAL_CONFIG = "peticao_visual_config"
MODELO_VISUAL_LOGO = "peticao_visual_logo"


class ErroPeticao(RuntimeError):
    pass


def extrair_identidade_visual(conteudo: bytes) -> tuple[bytes, str, str]:
    """Extrai logo e fonte do modelo geral sem copiar fatos ou texto da peça."""
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
            nomes = set(arquivo.namelist())
            imagens = [
                nome
                for nome in nomes
                if nome.startswith("word/media/")
                and nome.lower().endswith((".png", ".jpg", ".jpeg"))
            ]
            if not imagens:
                raise ErroPeticao("O modelo geral precisa ter uma logo PNG ou JPEG.")

            # Logos normalmente estão no cabeçalho. Se houver mais imagens no
            # documento, prioriza a que está relacionada por um header.
            alvos_cabecalho: list[str] = []
            for nome in sorted(nomes):
                if not nome.startswith("word/_rels/header") or not nome.endswith(".rels"):
                    continue
                raiz = ElementTree.fromstring(arquivo.read(nome))
                for relacao in raiz:
                    alvo = relacao.attrib.get("Target", "")
                    if "image" in relacao.attrib.get("Type", "") and alvo:
                        alvos_cabecalho.append("word/" + alvo.lstrip("/"))
            candidatos = [nome for nome in alvos_cabecalho if nome in nomes] or imagens
            logo_nome = candidatos[0]
            logo = arquivo.read(logo_nome)

            # Reserva de quando o .docx enviado não declara `rFonts`: cai no mesmo
            # padrão serifado do resto do sistema, e não mais em Arial.
            fonte = _fonte_padrao()
            if "word/styles.xml" in nomes:
                raiz = ElementTree.fromstring(arquivo.read("word/styles.xml"))
                ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
                for fontes in raiz.iter(f"{ns}rFonts"):
                    encontrada = fontes.attrib.get(f"{ns}ascii") or fontes.attrib.get(f"{ns}hAnsi")
                    if encontrada and len(encontrada) <= 80:
                        fonte = encontrada
                        break
            logo_nome_minusculo = logo_nome.lower()
            extensao = ".jpg" if logo_nome_minusculo.endswith((".jpg", ".jpeg")) else ".png"
            return logo, fonte, extensao
    except ErroPeticao:
        raise
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as erro:
        raise ErroPeticao("Não foi possível ler a identidade visual deste .docx.") from erro


def extrair_fonte_visual(conteudo: bytes) -> str:
    """Lê a fonte mesmo quando o arquivo de referência não traz uma logo."""
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
            if "word/styles.xml" not in arquivo.namelist():
                return _fonte_padrao()
            raiz = ElementTree.fromstring(arquivo.read("word/styles.xml"))
            for fontes in raiz.iter(f"{_NS_W}rFonts"):
                fonte = fontes.attrib.get(f"{_NS_W}ascii") or fontes.attrib.get(f"{_NS_W}hAnsi")
                if fonte and len(fonte) <= 80:
                    return fonte
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError):
        pass
    return _fonte_padrao()


_NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _primeiro_val(raiz, tag: str, attr: str = "val") -> str | None:
    for el in raiz.iter(f"{_NS_W}{tag}"):
        v = el.attrib.get(f"{_NS_W}{attr}")
        if v:
            return v
    return None


def analisar_estilo(conteudo: bytes) -> dict[str, Any]:
    """O que dá para captar do padrão do escritório, além de logo e fonte.

    Tamanho da fonte, espaçamento entre linhas, alinhamento e margens — é o que a
    tela mostra como "identificamos isto no seu documento". Tudo best-effort: o
    atributo que não estiver no arquivo simplesmente não entra, e nada aqui
    interrompe o cadastro do modelo.
    """
    atributos: dict[str, Any] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
            nomes = set(arquivo.namelist())
            if "word/styles.xml" in nomes:
                estilos = ElementTree.fromstring(arquivo.read("word/styles.xml"))
                sz = _primeiro_val(estilos, "sz")  # em meios-pontos
                if sz and sz.isdigit():
                    atributos["tamanho_fonte_pt"] = round(int(sz) / 2, 1)
                linha = None
                for sp in estilos.iter(f"{_NS_W}spacing"):
                    linha = sp.attrib.get(f"{_NS_W}line")
                    if linha:
                        break
                if linha and linha.isdigit():
                    # 240 = simples, 360 = 1,5, 480 = duplo.
                    atributos["espacamento_linha"] = round(int(linha) / 240, 2)
                jc = _primeiro_val(estilos, "jc")
                if jc:
                    atributos["alinhamento"] = {
                        "both": "justificado",
                        "left": "à esquerda",
                        "center": "centralizado",
                        "right": "à direita",
                    }.get(jc, jc)
            if "word/document.xml" in nomes:
                doc = ElementTree.fromstring(arquivo.read("word/document.xml"))
                tabelas = list(doc.iter(f"{_NS_W}tbl"))
                if tabelas:
                    colunas = []
                    for tabela in tabelas:
                        primeira_linha = next(iter(tabela.iter(f"{_NS_W}tr")), None)
                        if primeira_linha is not None:
                            colunas.append(len(list(primeira_linha.iter(f"{_NS_W}tc"))))
                    atributos["tabelas"] = {
                        "quantidade": len(tabelas),
                        "colunas_detectadas": sorted({n for n in colunas if n}),
                    }
                for mar in doc.iter(f"{_NS_W}pgMar"):
                    def cm(lado: str) -> float | None:
                        v = mar.attrib.get(f"{_NS_W}{lado}")
                        return round(int(v) / 1440 * 2.54, 1) if v and v.lstrip("-").isdigit() else None

                    margens = {lado: cm(lado) for lado in ("top", "right", "bottom", "left")}
                    if any(v is not None for v in margens.values()):
                        atributos["margens_cm"] = margens
                    break
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
        return atributos
    return atributos


def identidade_visual() -> tuple[bytes, str, str, str]:
    """Identidade vigente: logo da skill de petição, depois banco; Lara & Melo como reserva segura."""
    skill = skill_peticao.ativa()
    if skill.logo:
        dados, extensao, caminho = skill.logo
        return dados, _fonte_padrao(), extensao, f"{Path(caminho).name} (skill {skill.nome})"
    try:
        registro = armazenamento.obter_modelo(MODELO_VISUAL_GERAL)
    except Exception:
        log.warning("modelo visual indisponível no banco; usando Lara & Melo", exc_info=True)
        registro = None
    try:
        logo_separada = armazenamento.obter_modelo(MODELO_VISUAL_LOGO)
    except Exception:
        # O modelo geral acima já confirmou que o banco pode estar inacessível.
        # A logo opcional não pode quebrar o mesmo fallback offline.
        logo_separada = None
    if logo_separada:
        extensao = Path(str(logo_separada["nome_arquivo"])).suffix.lower()
        extensao = ".jpg" if extensao in {".jpg", ".jpeg"} else ".png"
        fonte = extrair_fonte_visual(registro["conteudo"]) if registro else _fonte_padrao()
        return bytes(logo_separada["conteudo"]), fonte, extensao, logo_separada["nome_arquivo"]
    if registro:
        try:
            logo, fonte, extensao = extrair_identidade_visual(registro["conteudo"])
            return logo, fonte, extensao, registro["nome_arquivo"]
        except ErroPeticao:
            return LOGO_LARA_MELO.read_bytes(), extrair_fonte_visual(registro["conteudo"]), ".png", "Logo padrão"
    return LOGO_LARA_MELO.read_bytes(), _fonte_padrao(), ".png", "Padrão Lara & Melo"


def configuracao_visual() -> dict[str, Any]:
    """Formatação da peça: a SKILL manda, o resto é preferência do escritório.

    Fonte, tamanho, espaçamento, recuo, margens e alinhamento do corpo vêm de
    `peticao_skill_arquivos.configuracao_visual_padrao()` (extraído de
    `references/formatacao.md`) e NÃO são sobrescritos por um modelo visual ou
    configuração enviados antes: o escritório mudou o padrão (a peça de
    referência atual é Arial/LiberationSans, e a que serviu de medida antes era
    serifada) e a geração tem de seguir a skill vigente, não a última medição
    guardada. O que a skill não define — altura do logo, alinhamento dos títulos,
    preferência por tabelas — continua vindo da configuração salva.
    """
    padrao = peticao_skill_arquivos.configuracao_visual_padrao()
    configuracao = dict(padrao)
    try:
        registro = armazenamento.obter_modelo(MODELO_VISUAL_CONFIG)
        if registro:
            recebida = json.loads(bytes(registro["conteudo"]).decode("utf-8"))
            if isinstance(recebida, dict):
                configuracao.update({
                    k: v for k, v in recebida.items()
                    if k in configuracao and k not in _CAMPOS_DA_SKILL
                })
    except Exception:
        log.warning("configuração visual indisponível; usando padrão da skill", exc_info=True)
    for campo in ("tamanho_fonte_pt", "espacamento_linha", "recuo_primeira_linha_cm", "margem_superior_cm", "margem_direita_cm", "margem_inferior_cm", "margem_esquerda_cm"):
        try:
            configuracao[campo] = float(configuracao[campo])
        except (TypeError, ValueError):
            configuracao[campo] = padrao[campo]
    return configuracao


#: Campos que a skill (`formatacao.md`) define e que, portanto, nenhum modelo
#: visual ou configuração salva pode sobrescrever.
_CAMPOS_DA_SKILL = frozenset({
    "fonte", "tamanho_fonte_pt", "espacamento_linha", "recuo_primeira_linha_cm",
    "margem_superior_cm", "margem_direita_cm", "margem_inferior_cm",
    "margem_esquerda_cm", "alinhamento_corpo",
})


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def existe(caso_id: str) -> bool:
    return armazenamento.obter_peticao_local(caso_id) is not None


def carregar(caso_id: str) -> dict[str, Any] | None:
    dados = armazenamento.obter_peticao_local(caso_id)
    if dados is None:
        return None
    dados.pop("_docx", None)
    return dados


@skill_peticao.com_skill_do_caso
def _salvar(caso_id: str, dados: dict[str, Any]) -> dict[str, Any]:
    # Nenhum caminho de edição/exportação pode conservar READY de uma versão
    # anterior: revalida o texto que efetivamente será persistido. A geração
    # completa já fez auditorias mais profundas; isto é a rede determinística
    # comum a geração, edição humana e revisões automáticas.
    secoes = [s for s in dados.get("sections") or [] if s.get("code") != "JURIMETRY"]
    if secoes:
        try:
            _, violacoes, _ = _conferir_contra_os_autos(caso_id, secoes, corrigir=False)
            _aplicar_conferencia(dados, secoes, violacoes)
            if any(v.bloqueia for v in violacoes):
                prontidao = dados.setdefault("readiness", {})
                prontidao["ready"] = False
                prontidao["status"] = "BLOCKED"
                prontidao.setdefault("blocking_issues", []).extend(
                    f"[{v.codigo}] {v.motivo}"[:200] for v in violacoes if v.bloqueia
                )
        except Exception:  # noqa: BLE001 - falha de conferência também não autoriza READY
            dados.setdefault("readiness", {})["ready"] = False
            dados["readiness"]["status"] = "BLOCKED"
            dados["readiness"].setdefault("blocking_issues", []).append(
                "Conferência final não executou; protocolo bloqueado."
            )
    dados["updated_at"] = _agora()
    dados["docx_style_version"] = DOCX_STYLE_VERSION
    armazenamento.salvar_peticao_local(
        caso_id,
        dados,
        montar_docx(dados.get("sections") or []),
    )
    return dados


#: Teto de saída do modelo, em tokens.
#:
#: NÃO estava definido, e era ESTE o motivo real das peças curtas. Sem o campo, a
#: DeepSeek aplica o padrão dela (4096 tokens), e nenhuma instrução de "escreva
#: mais" vence um corte no transporte: o prompt podia pedir quatro parágrafos por
#: tese e doze julgados que a resposta parava no mesmo tamanho. A mediana do
#: acervo do escritório é de 144 parágrafos por peça — não cabe em 4096.
#:
#: E 8192 também não coube (18/09): a revisão devolve a peça INTEIRA em JSON, e numa
#: inicial de 23 mil caracteres com uma seção nova pedida pelo chat a resposta
#: parou em exatos 8192 tokens, no meio dos pedidos. JSON sem fechar virava "o
#: modelo não respondeu" — três vezes seguidas no mesmo caso. Por isso 100000 (a
#: API aceita até 393216, medido). Omitir o campo NÃO serve — volta ao padrão de 4096.
MAX_TOKENS_RESPOSTA = int(os.getenv("PETICAO_MAX_TOKENS", "100000"))


#: O plano é reforço da redação, não a peça: teto de saída e prazo TOTAL próprios. O timeout do httpx vale por
#: leitura de socket, e uma resposta que pinga devagar passava dos 18% por minutos sem fim.
MAX_TOKENS_PLANO = int(os.getenv("PETICAO_MAX_TOKENS_PLANO", "16000"))
PRAZO_PLANO_S = float(os.getenv("PETICAO_PRAZO_PLANO_S", "150"))
_EXECUTOR_PRAZO = ThreadPoolExecutor(max_workers=4, thread_name_prefix="llm-prazo")
_EXECUTOR_PROVEDOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="llm-provedor")


def _com_prazo_total(chamada: Any, prazo_s: float) -> Any:
    """Roda a chamada e desiste dela depois de `prazo_s` de relógio, qualquer que seja o estado do socket."""
    futuro = _EXECUTOR_PRAZO.submit(contextvars.copy_context().run, chamada)
    try:
        return futuro.result(timeout=prazo_s)
    except TimeoutError as erro:
        futuro.cancel()
        raise ErroPeticao(f"a chamada ao modelo passou de {prazo_s:.0f}s e foi abandonada") from erro


#: DeepSeek lento ou fora do ar não pode parar a peça (18/09 e 01/10: um "oi" levava mais de 40 s). Passado este
#: tempo sem resposta, a OpenAI é chamada em paralelo e vale quem responder primeiro com sucesso.
ATRASO_RESERVA_S = float(os.getenv("PETICAO_ATRASO_RESERVA_S", "60"))
#: Pedido grande demora de verdade (140 mil caracteres de entrada levam ~90 s): o atraso cresce com ele.
ATRASO_POR_MIL_CARACTERES_S = float(os.getenv("PETICAO_ATRASO_POR_MIL_S", "0.4"))
MODELO_RESERVA = os.getenv("PETICAO_MODELO_RESERVA", "") or os.getenv("OPENAI_CHAT_MODEL", "gpt-5-mini")


def _reserva_configurada() -> tuple[str, str] | None:
    chave = os.getenv("OPENAI_API_KEY", "").strip()
    if not chave:
        return None
    return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"), chave


def _chamar_provedor(fornecedor: str, base: str, chave: str, modelo: str, instrucao: str, entrada: str,
                     max_tokens: int | None, timeout: float) -> dict[str, Any]:
    teto = max_tokens or MAX_TOKENS_RESPOSTA
    corpo: dict[str, Any] = {
        "model": modelo,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": instrucao}, {"role": "user", "content": entrada[:120_000]}],
    }
    if fornecedor == "openai":
        corpo["max_completion_tokens"] = min(teto, 64000)
    else:
        corpo["temperature"] = 0.2
        corpo["max_tokens"] = teto
    inicio = time.monotonic()
    resposta = httpx.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {chave}"}, json=corpo,
                          timeout=timeout)
    resposta.raise_for_status()
    custos_api.registrar(fornecedor, modelo, "geracao_peticao", resposta,
                         latencia_ms=round((time.monotonic() - inicio) * 1000))
    return resposta.json()["choices"][0]


def _escolha_com_reserva(base: str, chave: str, modelo: str, instrucao: str, entrada: str,
                         max_tokens: int | None, timeout: float, *, reserva_permitida: bool) -> dict[str, Any]:
    reserva = _reserva_configurada() if reserva_permitida else None
    if reserva is None:
        return _chamar_provedor("deepseek", base, chave, modelo, instrucao, entrada, max_tokens, timeout)

    def lancar(fornecedor: str, b: str, c: str, m: str) -> Any:
        return _EXECUTOR_PROVEDOR.submit(contextvars.copy_context().run, _chamar_provedor, fornecedor, b, c, m,
                                      instrucao, entrada, max_tokens, timeout)

    atraso = ATRASO_RESERVA_S + ATRASO_POR_MIL_CARACTERES_S * (len(instrucao) + len(entrada)) / 1000
    pendentes = {lancar("deepseek", base, chave, modelo)}
    reserva_lancada = False
    limite = time.monotonic() + timeout
    ultimo_erro: Exception | None = None
    while pendentes:
        espera = limite - time.monotonic()
        if espera <= 0:
            break
        prazo = min(espera, atraso) if not reserva_lancada else espera
        prontos, pendentes = futures_wait(pendentes, timeout=prazo, return_when=FIRST_COMPLETED)
        for futuro in prontos:
            try:
                return futuro.result()
            except Exception as erro:  # noqa: BLE001
                ultimo_erro = erro
        if not reserva_lancada and (not prontos or not pendentes):
            reserva_lancada = True
            log.warning("petição local: DeepSeek lento ou com erro (%s); chamando a OpenAI em paralelo", ultimo_erro or "sem resposta")
            pendentes.add(lancar("openai", reserva[0], reserva[1], MODELO_RESERVA))
    for futuro in pendentes:
        futuro.cancel()
    raise ultimo_erro or httpx.ReadTimeout("nenhum provedor respondeu a tempo")


def _llm_json(
    instrucao: str, entrada: str, *, timeout: float = 180.0, modelo: str | None = None,
    repetir_apos_timeout: bool = True, max_tokens: int | None = None,
) -> dict[str, Any]:
    # Homologação e contingência: permite usar OpenAI como provedor primário,
    # sem iniciar nem aguardar uma chamada DeepSeek degradada.
    if os.getenv("PETICAO_FORNECEDOR", "").strip().lower() == "openai":
        reserva = _reserva_configurada()
        if reserva is None:
            raise ErroPeticao("OPENAI_API_KEY ausente — não é possível usar OpenAI como provedor primário.")
        base_openai, chave_openai = reserva
        modelo_openai = modelo or os.getenv("OPENAI_CHAT_MODEL", "gpt-5-mini")
        escolha = _chamar_provedor("openai", base_openai, chave_openai, modelo_openai,
                                   instrucao, entrada, max_tokens, timeout)
        conteudo = escolha["message"]["content"]
        try:
            return json.loads(conteudo)
        except json.JSONDecodeError as erro:
            raise ErroPeticao("OpenAI retornou JSON inválido.") from erro
    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not chave:
        raise ErroPeticao("DEEPSEEK_API_KEY ausente — configure no .env.")
    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    reserva_permitida = modelo is None
    modelo = modelo or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    # Duas tentativas, não uma: um pedido grande — criar um tópico novo reescreve
    # a peça inteira — já leva dezenas de segundos, e um timeout de rede isolado
    # (a resposta estava a caminho, a conexão caiu) derrubava o pedido inteiro na
    # hora, sem tentar de novo. Quem lia via "o modelo não respondeu" depois de
    # já ter esperado o tempo todo — e tinha de repetir o pedido do zero. Não
    # cobre o corte por tamanho (`finish_reason == "length"`): repetir um pedido
    # que já estourou o teto falharia do mesmo jeito, então esse caso sai direto
    # com a mensagem própria, sem consumir a segunda tentativa.
    ultimo_erro: Exception | None = None
    for tentativa in (1, 2):
        inicio_chamada = time.monotonic()
        try:
            escolha = _escolha_com_reserva(base, chave, modelo, instrucao, entrada, max_tokens, timeout,
                                           reserva_permitida=reserva_permitida)
            conteudo = escolha["message"]["content"]
            if escolha.get("finish_reason") == "length":
                # Cortado pelo teto de saída: o JSON chega sem fechar. Dizer "não
                # respondeu" mandava tentar de novo um pedido que falha igual.
                log.warning(
                    "petição local: resposta cortada no teto de %s tokens", MAX_TOKENS_RESPOSTA
                )
                raise ErroPeticao(
                    "A resposta do modelo passou do tamanho máximo e foi cortada. Peça a"
                    " alteração em partes menores."
                )
            saida = json.loads(conteudo)
        except ErroPeticao:
            raise
        # `IndexError` e `TypeError` não estavam aqui, e é justamente o que um
        # provedor devolve quando filtra a resposta: HTTP 200 com `choices: []`. O
        # erro subia cru e a tela mostrava 500 sem dizer nada ao advogado, que ficava
        # sem saber se devia tentar de novo — e devia.
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError, TypeError) as erro:
            custos_api.registrar_falha("deepseek", modelo, "geracao_peticao", erro,
                                      latencia_ms=round((time.monotonic() - inicio_chamada) * 1000))
            ultimo_erro = erro
            log.warning(
                "petição local: LLM falhou (tentativa %s/2): %s", tentativa, erro
            )
            # Etapa opcional que já esperou o prazo inteiro: repetir dobraria a espera com a tela parada.
            if not repetir_apos_timeout and isinstance(erro, httpx.TimeoutException):
                break
            continue
        if not isinstance(saida, dict):
            # JSON válido que não é objeto (uma lista, um número) quebraria adiante,
            # no `.get` de quem chamou, longe daqui.
            log.warning("petição local: LLM devolveu %s em vez de objeto", type(saida).__name__)
            ultimo_erro = None
            break
        return saida

    if ultimo_erro is not None:
        raise ErroPeticao("O modelo não respondeu — tente de novo.") from ultimo_erro
    raise ErroPeticao("O modelo não respondeu no formato esperado — tente de novo.")


def _categoria_do_caso(caso_id: str) -> str:
    caso = armazenamento.obter_caso(caso_id) or {}
    return str(caso.get("categoria") or "")


def _nome_e_codigo_da_categoria(caso_id: str) -> tuple[str, str]:
    """(nome legível, código) da categoria do caso — usado para casar com o
    assunto da skill de arquivo (`peticao_skill_arquivos`) e do acervo
    classificado (`scripts/classificar_pecas.py`), que reconhecem por nome."""
    codigo = _categoria_do_caso(caso_id)
    try:
        nome = ((casos_ocr.montar_situacao(caso_id) or {}).get("categoria") or {}).get("nome") or codigo
    except Exception:
        nome = codigo
    return str(nome), codigo


#: Quantas lições de uma categoria entram automaticamente no prompt das próximas
#: gerações — a retroalimentação da issue "Permitir alteração da petição por
#: prompt com rastreabilidade" ("a IA vai aprendendo até sair do jeitinho que
#: eles querem").
#:
#: Era 5, e 5 quebrava a promessa: medido contra o banco, gravadas 7 correções na
#: mesma categoria, a IA lembrava da 3ª à 7ª e ESQUECIA as duas primeiras — o
#: escritório reensinava o que já tinha ensinado. 20 cabe no prompt e cobre o que
#: uma categoria acumula em meses; repetidas não gastam vaga (`_chave`), e o que
#: for marcado "só deste caso" nem chega aqui.
CRITICAS_RECENTES_POR_CATEGORIA = 20


def _com_skill_do_escritorio(caso_id: str, instrucao: str, *, revisao: bool = False) -> str:
    """Acrescenta o que o escritório já ensinou sobre esta categoria de caso.

    Duas fontes, nesta ordem — configuração explícita primeiro, aprendizado
    implícito depois:

    1. A skill cadastrada em `peticao_skills` (issue "Configurar skill por
       modelo de petição") — instrução deliberada, escrita pra isso.
    2. As últimas críticas que advogados fizeram em petições desta MESMA
       categoria, mesmo em OUTROS casos (`peticao_criticas`) — retroalimentação
       automática: o escritório não precisa repetir a mesma correção caso após
       caso, porque a próxima geração já nasce considerando as anteriores.

    Vem DEPOIS do contrato do prompt (papel, formato do JSON), nunca antes: as
    duas são conteúdo — o que destacar, como abordar a categoria —, e não podem
    mudar o formato que `_normalizar_secoes` espera receber de volta. Sem nada
    cadastrado, `instrucao` volta intocada — mesmo comportamento de antes desta
    configuração existir.
    """
    nome_categoria, categoria = _nome_e_codigo_da_categoria(caso_id)
    # A orientação GERAL vem primeiro; a da categoria, se existir, complementa.
    #
    # A configuração da tela passou a ser única (ver `peticao_skills.CATEGORIA_GERAL`):
    # o que o escritório ensina sobre como redigir não muda com o tipo da ação, e
    # manter uma cópia por categoria obrigava a reescrever a mesma instrução cinco
    # vezes — e a lembrar de atualizar as cinco.
    #
    # As skills já escritas por categoria continuam sendo LIDAS de propósito.
    # Parar de lê-las sumiria em silêncio com o que o escritório já tinha
    # ensinado: não haveria aviso na tela, e o sintoma apareceria semanas depois,
    # como petição saindo diferente sem ninguém saber por quê.
    skill = "\n\n".join(
        parte
        for parte in (
            peticao_skills.instrucoes_gerais().strip(),
            peticao_skills.instrucoes_da_categoria(categoria).strip(),
        )
        if parte
    )
    # A skill de arquivo (`escritorio-trabalhista`, a mesma que produziu a peça
    # de referência do escritório fora deste sistema) entra ANTES da orientação
    # cadastrada em `peticao_skills` e do acervo — ver `peticao_skill_arquivos`
    # para o porquê. Falha de leitura (deploy sem os arquivos) não derruba a
    # geração: cai para o comportamento anterior, só com a tabela.
    try:
        skill_arquivo = peticao_skill_arquivos.carregar(nome_categoria, categoria, _TEXTO_DO_CASO.get())
    except Exception:
        log.warning("petição local: skill de arquivo indisponível", exc_info=True)
        skill_arquivo = ""
    regras = peticao_aprendizado.regras_para_contexto(categoria=categoria)
    try:
        # Compatibilidade com as correções históricas anteriores ao aprendizado
        # estruturado. Assim que existirem regras ativas, histórico cru não entra
        # no prompt: uma lista de comentários não é uma base de conhecimento.
        criticas = []
        if not regras:
            peticao_criticas.inicializar()
            criticas = peticao_criticas.ultimas_da_categoria(
                categoria, limite=CRITICAS_RECENTES_POR_CATEGORIA
            )
    except Exception:
        # Mesma régua de `instrucoes_da_categoria`: uma oscilação de rede no
        # pgvector não pode derrubar a geração por causa de um reforço opcional.
        criticas = []

    blocos = [instrucao]
    # ORDEM = PRIORIDADE: o que vem por último pesa mais para o modelo. A orientação
    # cadastrada na tela (`peticao_skills`, no banco) é anterior à skill de arquivo e
    # fixava outra estrutura — "Juízo 100% Digital" e "Gratuidade" obrigatórias,
    # "Das Provas", honorários como seção própria — que vencia a skill por vir
    # DEPOIS dela no prompt. Agora ela vai ANTES, rotulada como complementar, e a
    # skill de arquivo fecha o bloco com a regra de precedência explícita.
    # AUTORIDADE ÚNICA: com a skill de arquivo carregada, a orientação cadastrada em
    # `peticao_skills` (a "skill GERAL" legada, que fixava outra estrutura) NÃO entra.
    # Só volta como fallback se a skill de arquivo não pôde ser lida.
    legada_carregada = bool(skill) and not skill_arquivo
    if not legada_carregada:
        skill = ""
    if skill:
        cabecalho = (
            "=== ORIENTAÇÃO CADASTRADA NA TELA (complementar — em conflito de estrutura, "
            "ordem de capítulos, preliminares ou formato com a SKILL DO ESCRITÓRIO abaixo, "
            "a skill vence) ===\n"
            if not revisao
            else "=== ORIENTAÇÃO CADASTRADA NA TELA (padrão de redação do trecho que for alterado; a SKILL DO ESCRITÓRIO prevalece em conflito) ===\n"
        )
        blocos.append(cabecalho + skill)
    if skill_arquivo:
        blocos.append(skill_arquivo)
    diag = _DIAG.get()
    if diag is not None:
        diag.setdefault("fontes_de_instrucao", {}).update({
            "skill_de_arquivo": bool(skill_arquivo),
            "legacy_skill_loaded": legada_carregada,
            "regras_aprendidas": bool(regras),
            "criticas_historicas": bool(criticas),
        })
    if regras:
        listadas = "\n".join(
            f"- [{r.get('tipo', 'PREFERENCE')}; confiança {float(r.get('confidence') or 0):.2f}; "
            f"{int(r.get('observacoes') or 0)} confirmação(ões)] {r.get('texto', '')}"
            for r in regras
        )
        if revisao:
            blocos.append(
                "=== REGRAS APRENDIDAS ATIVAS DO ESCRITÓRIO (referência contextual) ===\n"
                + listadas
                + "\nA crítica atual prevalece; não use regra aprendida para alterar seção não pedida."
            )
        else:
            blocos.append(
                "=== REGRAS APRENDIDAS ATIVAS DO ESCRITÓRIO ===\n"
                + listadas
                + "\nAplique apenas quando compatíveis com os fatos, a área e este tipo de peça."
            )
    if criticas:
        listadas = "\n".join(f"- {c}" for c in criticas)
        if revisao:
            blocos.append(
                "=== CORREÇÕES JÁ PEDIDAS EM PETIÇÕES DESTA CATEGORIA (somente referência) ===\n"
                f"{listadas}\n"
                "Nesta revisão NÃO aplique estas correções por conta própria: elas só orientam "
                "a redação do trecho que a CRÍTICA DO ADVOGADO mandar mudar."
            )
        else:
            blocos.append(
                "=== CORREÇÕES QUE O ESCRITÓRIO JÁ PEDIU EM PETIÇÕES DESTA CATEGORIA ===\n"
                f"{listadas}\n"
                "Aplique estas correções diretamente, sem repetir o erro que motivou cada uma."
            )
    if bool(configuracao_visual().get("preferir_tabelas")):
        blocos.append(
            "=== PREFERÊNCIA VISUAL DO ESCRITÓRIO ===\n"
            "Os modelos de referência usam tabelas. Quando houver dados comprovados "
            "naturalmente estruturados (cronologia, contrato, valores, documentos ou "
            "histórico médico), prefira uma tabela Markdown no ponto apropriado. Isso "
            "é preferência, não obrigação; não crie tabela sem utilidade nem invente células."
        )
    if len(blocos) == 1:
        return instrucao
    if revisao:
        blocos.append(
            "A CRÍTICA DO ADVOGADO tem prioridade sobre tudo acima: o que ela não pede não muda. "
            "Responda no formato pedido."
        )
    else:
        blocos.append("Aplique o que vier acima sem contrariar o formato de resposta pedido.")
    return "\n\n".join(blocos)


#: Leitura dos documentos guardada durante UMA geração (`gerar` liga): a mesma geração consultava o inventário e
#: todas as extrações do caso no SQL Server seis ou mais vezes. Fora de `gerar` não há cache.
_DOCUMENTOS_DA_GERACAO: ContextVar[dict[str, Any] | None] = ContextVar("documentos_da_geracao", default=None)


def documentos_logicos(caso_id: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    guardados = _DOCUMENTOS_DA_GERACAO.get()
    if guardados is not None and caso_id in guardados:
        ledger, documentos = guardados[caso_id]
        return list(ledger), list(documentos)
    resultado = _ler_documentos_logicos(caso_id)
    if guardados is not None:
        guardados[caso_id] = resultado
    return list(resultado[0]), list(resultado[1])


def _com_documentos_da_geracao(funcao: Any) -> Any:
    @functools.wraps(funcao)
    def envolvida(*args: Any, **kwargs: Any) -> Any:
        marca = _DOCUMENTOS_DA_GERACAO.set({})
        try:
            return funcao(*args, **kwargs)
        finally:
            _DOCUMENTOS_DA_GERACAO.reset(marca)
    return envolvida


def _ler_documentos_logicos(caso_id: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """(DOCUMENT_LEDGER, texto de cada documento LÓGICO na ordem do ledger).

    O ledger é o inventário dos anexos, não o inventário do OCR.  Antes, um
    arquivo que ainda aguardava leitura simplesmente não existia para a
    geração; isso permitia afirmar que um contracheque anexado "não integrava"
    os autos.  O texto vazio apenas deixa de ser enviado como OCR, mas o anexo
    conserva o seu número canônico e continua visível no índice.
    """
    try:
        extracoes = {
            str(e.get("id") or ""): e.get("extracao") or {}
            for e in armazenamento.listar_extracoes_do_caso(caso_id)
        }
        entregas = armazenamento.listar_entregas(caso_id)
    except Exception:  # noqa: BLE001 - o caminho legado abaixo ainda preserva OCR disponível
        log.warning("petição local: não leu o inventário completo de anexos do caso %s", caso_id, exc_info=True)
        extracoes, entregas = {}, []
    brutos = []
    for entrega in entregas:
        extracao = extracoes.get(str(entrega.get("id") or "")) or {}
        brutos.append({
            "arquivo": str(entrega.get("arquivo") or ""),
            "texto": str(extracao.get("texto_completo") or "").strip()[:MAX_CARACTERES_TEXTO_DOCUMENTO],
            "leitura": leitura_da_ia(extracao),
        })
    # Há instalações legadas em que a extração foi persistida antes da entrega.
    # Preserve esse material no ledger em vez de perdê-lo durante a migração.
    arquivos = {d["arquivo"] for d in brutos}
    brutos.extend(d for d in documentos_ocr(caso_id) if d["arquivo"] not in arquivos)
    ledger = document_ledger.montar(brutos, {a: d.get("tipo", "") for a, d in _dados_por_documento(caso_id).items()})
    por_arquivo = {d["arquivo"]: d for d in brutos}
    return ledger, [
        {
            "arquivo": d["canonical_file"],
            "texto": por_arquivo[d["canonical_file"]]["texto"],
            "rotulo": d["canonical_label"],
            "leitura": por_arquivo[d["canonical_file"]].get("leitura", ""),
        }
        for d in ledger
    ]


#: Teto do texto de UM documento no contexto da petição. Era 8 mil — duas
#: páginas —, e o resto do laudo, do TRCT ou do processo do INSS não chegava à
#: redação. O orçamento do conjunto continua em `_indice_e_textos_documentais`.
MAX_CARACTERES_TEXTO_DOCUMENTO = 20_000


def leitura_da_ia(extracao: dict[str, Any]) -> str:
    """O que a leitura do modelo tirou de UM documento, em texto compacto.

    Resumo e cada achado (campo: valor). Vai para a petição ANTES do texto cru
    do OCR: é o dado já nomeado e conferível, e sobrevive mesmo quando o texto
    integral do documento não cabe no orçamento.
    """
    semantica = extracao.get("classificacao_semantica") or {}
    if not isinstance(semantica, dict):
        return ""
    partes: list[str] = []
    tipo = str(semantica.get("tipo_semantico") or semantica.get("documento") or "").strip()
    if tipo and tipo.lower() != "indefinido":
        partes.append(f"Tipo: {tipo}")
    resumo = str(semantica.get("resumo") or "").strip()
    if resumo:
        partes.append(f"Resumo: {resumo}")
    for achado in semantica.get("achados") or []:
        if not isinstance(achado, dict):
            continue
        campo = str(achado.get("campo") or "").strip()
        valor = str(achado.get("valor") or "").strip()
        if campo and valor:
            partes.append(f"- {campo}: {valor}")
    for alerta in semantica.get("atencao") or []:
        if str(alerta or "").strip():
            partes.append(f"- Atenção: {str(alerta).strip()}")
    return "\n".join(partes)


def documentos_ocr(caso_id: str) -> list[dict[str, str]]:
    """O texto de OCR de cada anexo, em UMA consulta (ver `_documentos_do_caso`).

    Pública porque o chat da petição (`agente/chat_peticao.py`) lê os mesmos anexos
    para responder "o que o laudo diz?". Duas leituras do mesmo OCR divergiriam no
    dia em que uma delas passasse a cortar o texto noutro ponto.

    Era um `obter_entrega` por arquivo, e a geração da petição abre este caminho
    junto com o da análise: num caso de 46 anexos davam ~180 idas ao banco antes de
    a primeira palavra ir para o modelo.
    """
    documentos = []
    for entrega in armazenamento.listar_extracoes_do_caso(caso_id):
        texto = str((entrega.get("extracao") or {}).get("texto_completo") or "").strip()
        if not texto:
            continue
        documentos.append(
            {
                "arquivo": str(entrega.get("arquivo") or ""),
                "texto": texto[:MAX_CARACTERES_TEXTO_DOCUMENTO],
                "leitura": leitura_da_ia(entrega.get("extracao") or {}),
            }
        )
    return documentos


def anexos_do_caso(caso_id: str) -> list[dict[str, Any]]:
    """TODOS os anexos do caso, lidos ou não, com o que o OCR já organizou.

    `documentos_ocr` serve à geração: só o texto, e só de quem tem texto. O chat da
    petição precisa de mais, e a falta disso foi medida numa reclamação real: o
    advogado pediu o número de um documento que estava no caso, o chat procurou pelo
    NOME do arquivo (`IMG_….jpg`), não achou, e afirmou que o documento não existia —
    porque o anexo sem texto sumia da lista e o prompt dizia que o que não está na
    lista não existe.

    Aqui vai cada entrega com o tipo classificado ("CTPS", "RG"), os campos já
    extraídos (número, série, data) e a situação da leitura (`lido`, `na_fila`,
    `processando`, `erro`, `sem_texto`). O texto vai INTEIRO: quem busca precisa achar
    o número no fim do documento, e o corte é feito por quem mostra o trecho.
    Duas consultas, como `documentos_ocr` — não uma por arquivo.
    """
    extracoes = {e["id"]: e.get("extracao") or {} for e in armazenamento.listar_extracoes_do_caso(caso_id)}
    anexos: list[dict[str, Any]] = []
    for entrega in armazenamento.listar_entregas(caso_id):
        extracao = extracoes.get(str(entrega.get("id"))) or {}
        texto = str(extracao.get("texto_completo") or "").strip()
        tipo = extracao.get("tipo") if isinstance(extracao.get("tipo"), dict) else {}
        semantica = extracao.get("classificacao_semantica")
        semantica = semantica if isinstance(semantica, dict) else {}
        # A leitura semântica descreve o DOCUMENTO inteiro; o classificador por
        # palavras serve de apoio. Um checklist interno pode mencionar “certidão”
        # dezenas de vezes e, ainda assim, não ser uma certidão. Dar prioridade ao
        # segundo fazia o chat contrariar a classificação já registrada na tela.
        # Se não houver leitura semântica, o tipo determinístico segue sendo o
        # melhor rótulo disponível para documento de identidade/comprovante.
        candidatos = (
            semantica.get("documento"),
            entrega.get("identificacao_ia"),
            tipo.get("descricao") if str(tipo.get("codigo") or "") not in ("", "desconhecido") else "",
            tipo.get("descricao"),
            entrega.get("tipo_detectado"),
        )
        descricao = next(
            (
                str(c).strip()
                for c in candidatos
                if str(c or "").strip()
                and str(c).strip().lower() not in ("desconhecido", "documento não identificado", "indefinido")
            ),
            "",
        )
        campos = [
            {"rotulo": str(c.get("rotulo") or c.get("nome") or ""), "valor": str(c.get("valor") or "")}
            for c in (extracao.get("campos") or [])
            if isinstance(c, dict) and str(c.get("valor") or "").strip()
        ]
        status = str(entrega.get("status_proc") or "").lower()
        if texto:
            situacao = "lido"
        elif status in ("na_fila", "processando", "erro"):
            situacao = status
        else:
            situacao = "sem_texto"
        anexos.append(
            {
                "id": str(entrega.get("id") or ""),
                "arquivo": str(entrega.get("arquivo") or ""),
                "tipo": descricao,
                "campos": campos,
                "texto": texto,
                "situacao": situacao,
            }
        )
    return anexos


def _identidade_do_reclamante(caso_id: str, caso: dict[str, Any]) -> list[str]:
    """Quem é o autor da ação, com a autoridade do CADASTRO — não da transcrição.

    O CASO QUE OBRIGOU ISTO

    Caso `da5a030b`: cliente GUILHERME NUNES BEZERRA, com CPF no cadastro. A
    transcrição da entrevista tem, de passagem, "...tado chamado Roosevelt e aí
    eles machucaram com a moto da empresa..." — um terceiro citado na conversa, ou
    um erro do reconhecimento de voz. A petição saiu qualificando "ROOSEVELT
    RIVERS DA SILVA" como reclamante, e com "CPF [PENDENTE]" logo ao lado, num
    caso em que o CPF estava gravado.

    O nome do autor é a única coisa de uma petição que não se pode errar, e o
    sistema já o sabe. Antes ele ia como uma linha solta ("CLIENTE: ...") no alto
    de 4 mil caracteres de transcrição, sem dizer que aquilo era a fonte da
    verdade; o modelo preferiu o nome que aparecia no meio da conversa.

    Aqui a identidade vai num bloco próprio, dito como autoritativo, com o que o
    cadastro tem (o CPF vem da consulta por CPF da entrevista, ver
    `app/consultas.py`). Duas instruções acompanham: nome diferente deste é de
    TERCEIRO, e dado que está nesta lista não sai como [PENDENTE].
    """
    try:
        qualificacao = armazenamento.obter_qualificacao(caso_id) or {}
    except Exception:  # noqa: BLE001 - cadastro ausente não impede a geração
        log.warning("qualificação indisponível para o caso %s", caso_id, exc_info=True)
        qualificacao = {}

    campos = (
        ("Nome completo", caso.get("cliente")),
        ("CPF", qualificacao.get("cpf")),
        ("Data de nascimento", qualificacao.get("nascimento")),
        ("Sexo", qualificacao.get("sexo")),
        ("Nome da mãe", qualificacao.get("nome_mae")),
        ("Endereço", qualificacao.get("endereco")),
        ("CEP", qualificacao.get("cep")),
        ("Telefone", caso.get("telefone")),
        ("E-mail", qualificacao.get("email")),
    )
    conhecidos = [f"- {rotulo}: {valor}" for rotulo, valor in campos if str(valor or "").strip()]
    # Nome de fixture no cadastro: não instrua o modelo a usá-lo.
    conhecidos = [
        linha for linha in conhecidos
        if not re.search(r"\bTESTE\b", linha, re.IGNORECASE)
    ]
    # Endereço e CEP do cadastro só instruem a peça se um documento DESTE caso
    # os trouxer. Sem isso o modelo qualificava o autor (e, por arrasto, a ré)
    # com a cidade de outro processo — Tucuruí voltou três vezes.
    try:
        _, docs = documentos_logicos(caso_id)
        ocr = "\n".join(str(d.get("texto") or "") for d in docs)
    except Exception:  # noqa: BLE001
        ocr = ""
    if ocr.strip():
        norm_ocr, dig_ocr = plano_da_peticao.norm(ocr), plano_da_peticao._so_digitos(ocr)  # noqa: SLF001
        filtrados = []
        for linha in conhecidos:
            if linha.startswith("- Endereço:") or linha.startswith("- CEP:"):
                valor = linha.split(":", 1)[1].strip()
                campo = "cep" if linha.startswith("- CEP:") else "endereco"
                if not plano_da_peticao._valor_consta(campo, valor, norm_ocr, dig_ocr):  # noqa: SLF001
                    log.error("petição local: %s do cadastro não está nos documentos do caso %s — ignorado", campo, caso_id)
                    continue
            filtrados.append(linha)
        conhecidos = filtrados
    if not conhecidos:
        return []

    return [
        "=== IDENTIDADE DO RECLAMANTE (vem do CADASTRO do caso) ===",
        *conhecidos,
        "",
        "O NOME e o CPF desta lista qualificam o autor. Nome que apareça na transcrição "
        "ou nos documentos e seja diferente do nome acima é de TERCEIRO (colega, condutor, "
        "médico, testemunha, vítima) — nunca do autor. Endereço, CEP e CNPJ só podem ser "
        "os que estão nos DOCUMENTOS deste caso: não use cidade, filial ou número de outra "
        "peça, nem do cadastro se o documento não confirmar. Não escreva [PENDENTE] no corpo.",
        "",
    ]


def _montar_contexto(caso_id: str, texto_entrevista: str, *, brief: dict[str, Any] | None = None) -> str:
    caso = armazenamento.obter_caso(caso_id) or {}
    situacao = casos_ocr.montar_situacao(caso_id) or {}
    categoria = (
        (situacao.get("categoria") or {}).get("nome") or caso.get("categoria") or ""
    )
    progresso = situacao.get("progresso") or {}

    linhas = [
        *_identidade_do_reclamante(caso_id, caso),
        f"CATEGORIA: {categoria}",
        "",
        "=== ENTREVISTA (transcrição) ===",
        texto_entrevista[:55_000],
    ]

    # O case brief é o MESMO objeto que alimenta a tela de revisão do caso —
    # antes daqui só entravam os achados (sem cronologia nenhuma: um "afastamento
    # previdenciário identificado" com data e prova aparecia na tela e nunca
    # chegava à petição, porque só a lista de achados vinha para o contexto de
    # redação). Trocar por `case_brief.para_prompt` fecha essa desconexão: é a
    # mesma leitura, cronologia incluída, com id por fato/evento para rastrear
    # depois quem citou o quê.
    #
    # Vem ANTES do dump de OCR de propósito: `_precedentes_para_redigir` e as
    # outras buscas do acervo usam só `contexto[:12_000]` como consulta — com
    # o case brief antes dos vinte documentos inteiros, a busca por embeddings
    # parte dos fatos e provas do CASO, não do texto cru dos anexos.
    try:
        linhas.append("\n" + case_brief.para_prompt(brief if brief is not None else case_brief.montar(caso_id)))
    except Exception as erro:
        log.warning("petição local: case brief indisponível no contexto: %s", erro)
    # A ANÁLISE DOCUMENTAL (skill documental) chega à geração como MATERIAL do caso — fatos com
    # documento de origem, inconsistências, provas, faltantes e as respostas do escritório. Ela não
    # define estrutura nem estilo da peça: isso continua sendo da skill da peça.
    try:
        documental = analise_documental.contexto_para_peticao(caso_id)
        if documental:
            linhas.append("\n" + documental)
    except Exception as erro:  # noqa: BLE001
        log.warning("petição local: análise documental indisponível no contexto: %s", erro)

    # DOCUMENT_LEDGER: índice canônico de TODOS + OCR priorizado (contracheques
    # não podem sumir do contexto só porque o caso tem 58 anexos).
    ledger, documentos = documentos_logicos(caso_id)
    if documentos or ledger:
        linhas.append("\n" + "\n".join(_indice_e_textos_documentais(ledger, documentos)))

    obrig = progresso.get("obrigatorios_total")
    entregues = progresso.get("obrigatorios_entregues")
    if obrig is not None:
        linhas.append(
            f"\n=== CHECKLIST ===\n{entregues}/{obrig} obrigatórios entregues"
        )

    return "\n".join(linhas)[:MAX_CARACTERES_CONTEXTO]


#: Teto do contexto inteiro da redação. Era 120 mil, e com a entrevista, o
#: brief e a análise documental na frente, os textos dos documentos eram os
#: primeiros a serem cortados no fim. 170 mil (~50 mil tokens) ainda deixa
#: espaço, na janela de 128 mil tokens da DeepSeek, para a skill da peça, os
#: precedentes e a resposta.
MAX_CARACTERES_CONTEXTO = 170_000


@skill_peticao.com_skill_do_caso
def analisar(caso_id: str, *, texto_entrevista: str) -> dict[str, Any]:
    contexto = _montar_contexto(caso_id, texto_entrevista)
    saida = _llm_json(
        _com_skill_do_escritorio(
            caso_id,
            """Você é advogado. Cruze a ENTREVISTA com os DOCUMENTOS (OCR) e identifique
a natureza jurídica mais adequada aos fatos, sem presumir relação de trabalho.
Devolva JSON:
{
  "resumo": "síntese jurídica em 4-8 frases",
  "cruzamento_entrevista_documentos": "o que a entrevista diz vs. documentos",
  "pontos_fortes": ["pontos com prova ou relato consistente"],
  "lacunas": ["o que falta provar ou documentar"],
  "fatos_confirmados": ["fatos sustentados por documento"],
  "fatos_so_na_entrevista": ["alegações sem prova documental"],
  "observacoes": "alertas ao advogado"
}
Não invente fatos. Diferencie alegação de fato documentado.""",
        ),
        contexto,
    )
    return {
        "resumo": str(saida.get("resumo") or "").strip(),
        "cruzamento_entrevista_documentos": str(
            saida.get("cruzamento_entrevista_documentos") or ""
        ).strip(),
        "pontos_fortes": [
            str(x) for x in (saida.get("pontos_fortes") or []) if str(x).strip()
        ],
        "lacunas": [str(x) for x in (saida.get("lacunas") or []) if str(x).strip()],
        "fatos_confirmados": [
            str(x) for x in (saida.get("fatos_confirmados") or []) if str(x).strip()
        ],
        "fatos_so_na_entrevista": [
            str(x)
            for x in (saida.get("fatos_so_na_entrevista") or [])
            if str(x).strip()
        ],
        "observacoes": str(saida.get("observacoes") or "").strip(),
        "contexto": contexto[:80_000],
    }


def _normalizar_secoes(brutas: list[dict[str, Any]] | None, contrato: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Seções na ordem e na quantidade que a SKILL fez o modelo devolver — nada é imposto."""
    secoes = _normalizar_secoes_da_revisao(brutas or [])
    return contrato_secoes.canonicalizar(secoes, contrato)[0] if contrato else secoes


def _normalizar_secoes_da_revisao(brutas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normaliza as seções devolvidas pelo modelo, sem impor quantidade, ordem nem títulos."""
    resultado: list[dict[str, Any]] = []
    usados: set[str] = set()
    for indice, item in enumerate(brutas):
        if not isinstance(item, dict):
            continue
        conteudo = str(item.get("content") or item.get("texto") or "").strip()
        if not conteudo:
            continue
        base = re.sub(r"[^A-Z0-9_]+", "_", str(item.get("code") or item.get("label") or "SECAO").upper()).strip("_")
        codigo = base[:48] or "SECAO"
        if codigo in usados:
            codigo = f"{codigo[:42]}_{indice + 1}"
        usados.add(codigo)
        resultado.append({
            "code": codigo,
            # Sem título dado pelo redator = sem título (a skill decide se a seção tem um).
            "label": str(item.get("label") or "").strip(),
            "content": conteudo,
            "written_by": "agent",
            "supporting_fact_ids": [],
            "cited_precedent_ids": [],
            "formato": peticao_migracao_legado.FORMATO_ATUAL,
        })
    return resultado


def _analisar_jurimetria_da_minuta(
    secoes: list[dict[str, Any]], *, texto_para_uf: str = ""
) -> tuple[dict[str, Any], str]:
    """Compara a minuta pronta com decisões reais e gera apêndice auditável.

    `texto_para_uf` foca a busca no TRT do estado do caso (mesmo critério do
    painel), para o apêndice da peça citar precedentes daquela jurisdição — e
    não do acervo nacional — quando o estado é identificável nos documentos.
    """
    consulta = "\n\n".join(
        str(secao.get("content") or "")
        for secao in secoes
        if secao.get("code") not in ("HEADING", "CLOSING", "VALUE", "JURIMETRY")
    ).strip()
    jurisdicao = ""
    try:
        similares, jurisdicao, _uf = jurimetria_caso.buscar_focada(
            consulta, texto_para_uf=texto_para_uf
        )
    except Exception as erro:
        # O TIPO do erro vai para o log, e não só a mensagem: "timeout de
        # conexão" e "senha recusada" apareciam iguais aqui, e mandavam procurar
        # o problema em lugares opostos (rede x credencial). A busca já tenta as
        # três camadas de jurisdição com repetição (ver `jurimetria_caso`), então
        # chegar aqui significa que nenhuma delas respondeu.
        log.warning(
            "petição local: jurimetria indisponível (%s): %s",
            type(erro).__name__,
            str(erro)[:200],
        )
        aviso = (
            "A base de processos semelhantes não respondeu durante a geração, "
            "nem no acervo nacional. Nenhum percentual ou conclusão jurimétrica "
            "foi estimado — a minuta segue válida, sem o apêndice comparativo."
        )
        return {"disponivel": False, "aviso": aviso, "precedentes": []}, aviso
    if not similares:
        aviso = "Nenhum processo suficientemente semelhante foi localizado."
        return {"disponivel": False, "aviso": aviso, "precedentes": []}, aviso

    estatisticas = rag._estatisticas_amostra(similares)
    usados = similares[:10]
    referencias = {
        f"P{indice}": trecho.referencia()
        for indice, trecho in enumerate(usados, start=1)
    }
    contexto = []
    for indice, trecho in enumerate(usados, start=1):
        ref = referencias[f"P{indice}"]
        contexto.append(
            f"[P{indice}] processo={ref.get('processo') or ref.get('identificador')} "
            f"resultado={ref.get('resultado') or 'INDEFINIDO'} "
            f"órgão={ref.get('vara') or 'não informado'} "
            f"tipo={ref.get('tipo_documento') or 'não informado'} "
            f"similaridade={ref.get('similaridade')}\n{trecho.texto[:2800]}"
        )

    leitura: dict[str, Any] = {}
    try:
        leitura = _llm_json(
            """Compare a MINUTA somente com as DECISÕES fornecidas. Identifique
fundamentos recorrentes, distinções e riscos. Não trate frequência como probabilidade
de êxito nem atribua causa ao desfecho sem texto expresso. Toda conclusão deve citar
P1, P2 etc. Não invente referência. Responda JSON:
{"sintese":"...","fundamentos":[{"ponto":"...","impacto":"...","processos":["P1"]}],
"riscos":[{"ponto":"...","distincao":"...","processos":["P2"]}]}""",
            f"MINUTA:\n{consulta[:30_000]}\n\nDECISÕES:\n" + "\n\n".join(contexto),
            timeout=150,
        )
    except ErroPeticao as erro:
        log.warning("petição local: leitura jurimétrica falhou: %s", erro)

    validos = set(referencias)

    def itens_validos(chave: str) -> list[dict[str, Any]]:
        itens = []
        for bruto in leitura.get(chave) or []:
            if not isinstance(bruto, dict):
                continue
            refs = [
                str(ref) for ref in bruto.get("processos") or [] if str(ref) in validos
            ]
            if refs:
                itens.append({**bruto, "processos": refs})
        return itens[:6]

    fundamentos = itens_validos("fundamentos")
    riscos = itens_validos("riscos")
    merito = estatisticas["desfechos_merito"]
    semelhanca = estatisticas["similaridade_amostra"]
    linhas = [
        (
            f"Amostra: {estatisticas['processos_analisados']} processos; similaridade "
            f"mediana {semelhanca['mediana']:.3f} (mínima {semelhanca['minima']:.3f}; "
            f"máxima {semelhanca['maxima']:.3f})."
        ),
    ]
    if merito["processos"]:
        linhas.append(
            f"Desfechos de mérito: {merito['processos']}; procedentes ou parcialmente "
            f"procedentes: {merito['favoraveis']} ({merito['percentual']:.1f}%)."
        )
    linhas.extend(
        [estatisticas["aviso"], "", str(leitura.get("sintese") or "").strip()]
    )
    if fundamentos:
        linhas.extend(["", "Fundamentos que orientaram a minuta:"])
        for item in fundamentos:
            linhas.append(
                f"• {item.get('ponto', '')}: {item.get('impacto', '')} "
                f"[{', '.join(item['processos'])}]"
            )
    if riscos:
        linhas.extend(["", "Riscos e distinções relevantes:"])
        for item in riscos:
            linhas.append(
                f"• {item.get('ponto', '')}: {item.get('distincao', '')} "
                f"[{', '.join(item['processos'])}]"
            )
    linhas.extend(["", "Decisões consultadas:"])
    for indice, trecho in enumerate(usados, start=1):
        ref = referencias[f"P{indice}"]
        processo = ref.get("processo") or ref.get("identificador") or "não informado"
        linhas.append(
            f"[P{indice}] Processo {processo} — {ref.get('resultado') or 'desfecho não informado'}; "
            f"{ref.get('vara') or 'órgão não informado'}; similaridade {trecho.similaridade:.3f}."
        )
    resultado = {
        "disponivel": True,
        "origem": "embeddings_advocacia_ia",
        "consulta_vetorial": True,
        "jurisdicao": jurisdicao,
        "estatisticas": estatisticas,
        "sintese": str(leitura.get("sintese") or "").strip(),
        "fundamentos": fundamentos,
        "riscos": riscos,
        "precedentes": [
            {"indice": indice, **referencia}
            for indice, referencia in referencias.items()
        ],
        "aviso": estatisticas["aviso"],
    }
    return resultado, "\n".join(linhas).strip()


def redigir(
    caso_id: str, *, analise: dict[str, Any], texto_entrevista: str
) -> tuple[list[dict[str, Any]], list[str]]:
    contexto = analise.get("contexto") or _montar_contexto(caso_id, texto_entrevista)
    contexto += _precedentes_para_redigir(contexto)
    contexto += _legislacao_para_redigir(contexto)
    saida = _llm_json(
        _com_skill_do_escritorio(
            caso_id,
            CONTRATO_DE_REDACAO
            + """Redija a peça indicada pelos fatos e pela análise, executando a SKILL DO ESCRITÓRIO
(estrutura, argumentação e formatação), em português formal.
Use SOMENTE fatos da entrevista e documentos — não invente.
Marque com [PENDENTE: motivo] o que depender só de alegação sem prova.

PADRÃO DO ESCRITÓRIO: a ORIENTAÇÃO DO ESCRITÓRIO (skill) é a fonte de FORMATO
e manda sobre tudo — inclusive sobre a estrutura de qualquer peça de referência
do acervo que aparecer acima. Peça de referência mostra nível de profundidade
e raciocínio a igualar, nunca título, ordem de seção ou formato: nisso, quando
divergir da orientação do escritório, a orientação do escritório vence sempre.
Onde a orientação não disser nada sobre estrutura ou formato, NÃO crie seção, título nem elemento novo; escolha só a forma mais simples para a
peça, sem inventar fato.

TABELAS: você pode usar tabela quando ela tornar dados comprovados mais claros
(cronologia, contrato, documentos, valores ou histórico médico), ou quando o
advogado pedir. Escreva-a em Markdown, com cabeçalho e linha separadora, no
EXATO ponto do `content` em que ela deve aparecer. O sistema a converterá em
tabela nativa e editável do Word. Não simule tabela com tabs/espaços, não
invente dados para preencher célula e omita linhas sem informação comprovada.
JSON:
{
  "secoes": [
    {"code":"<PAPEL_DA_SECAO>","label":"<título da seção como a SKILL manda; \"\" se a skill não dá título>","content":"<texto, com a marcação definida em formatacao.md>"}
    /* UMA entrada por seção que a SKILL determinar, na ordem e na quantidade que ela determinar.
       PAPEL_DA_SECAO deve ser um papel do CONTRATO DE BLOCOS abaixo. Nunca crie código livre,
       capítulo autônomo, análise interna, lista de lacunas ou estratégia processual não prevista pela skill. */
  ],
  "pendencias": ["fatos sem comprovação documental"]
}
Cada content em parágrafos separados por linha em branco.""",
        ),
        (
            f"ANÁLISE:\n{analise.get('resumo', '')}\n"
            f"Cruzamento: {analise.get('cruzamento_entrevista_documentos', '')}\n"
            f"Lacunas: {', '.join(analise.get('lacunas') or [])}\n"
            f"Confirmados: {', '.join(analise.get('fatos_confirmados') or [])}\n\n"
            f"MATERIAL:\n{contexto[:90_000]}"
        ),
        # 360s e não 240s: com o teto de saída dobrado a resposta é fisicamente
        # maior, e manter o prazo antigo trocaria "peça curta" por "o modelo não
        # respondeu" — que é pior, porque perde o trabalho inteiro.
        timeout=360.0,
    )
    secoes = _normalizar_secoes(saida.get("secoes") or [])
    if not any(s["content"] for s in secoes):
        raise ErroPeticao("O modelo não devolveu texto da petição.")
    return secoes, [str(p) for p in (saida.get("pendencias") or []) if str(p).strip()]


def _precedentes_para_redigir(
    contexto: str, consultas: list[dict[str, str]] | None = None, *, uf: str = ""
) -> str:
    """Julgados semelhantes ANTES de redigir, para a IA poder citá-los.

    A jurimetria já existia, mas rodava depois (`_analisar_jurimetria_da_minuta`,
    chamada com a minuta pronta): ela virava um apêndice auditável e NUNCA
    chegava ao prompt. Por isso o advogado pedia jurisprudência e o texto saía
    sem nenhuma — o modelo não tinha como citar o que não recebeu.

    A consulta aqui é o próprio material do caso (entrevista + documentos), e não
    a minuta, justamente porque a minuta ainda não existe neste ponto.

    Falha não interrompe a geração: sem base, a peça sai como saía antes.
    """
    erros_tese: list[str] = []
    try:
        if consultas:
            similares, provs, erros_tese = recuperacao_por_tese.precedentes(consultas, contexto, uf=uf)
            if not similares and erros_tese:
                raise RuntimeError("; ".join(erros_tese[:3]))
            _registrar_proveniencia(provs, [t.texto[:1800] for t in similares])
            _guardar_trechos("precedentes", similares)
        else:
            similares, _jurisdicao, _uf = jurimetria_caso.buscar_focada(
                contexto[:12_000], uf=uf,
                texto_para_uf=contexto
            )
            similares = recuperacao_por_tese.apenas_verificados(similares)
    except Exception as erro:
        log.warning("petição local: precedentes indisponíveis na redação: %s", erro)
        _diag("precedentes", ok=False, n=0, erro=_erro_curto(erro))
        return ""
    if not similares:
        _diag("precedentes", ok=True, n=0)
        return ""
    # DOZE julgados, e não seis: com seis o modelo citava um ou dois e dava a
    # fundamentação por cumprida. O trecho de cada um caiu de 2200 para 1800
    # caracteres de propósito — dobrar a quantidade sem encolher o recorte
    # empurraria o prompt para perto do teto e o que entra por último é
    # justamente o que o modelo menos aproveita.
    linhas = ["\n\n=== JULGADOS SEMELHANTES (use no DO DIREITO) ==="]
    usados = list(similares[:18])
    _diag("precedentes", ok=True, n=len(usados), por_tese=bool(consultas),
          consultas=len(consultas or []), erros_por_tese=erros_tese,
          scores=[round(float(t.similaridade), 4) for t in usados])
    for indice, trecho in enumerate(usados, start=1):
        ref = trecho.referencia()
        natureza = recuperacao_por_tese._natureza(trecho.metadados)  # noqa: SLF001 - mesmo pacote
        linhas.append(
            f"\n[J{indice}] processo={ref.get('processo') or ref.get('identificador')} "
            f"natureza={natureza} "
            f"resultado={ref.get('resultado') or 'não informado'} "
            f"órgão={ref.get('vara') or 'não informado'}\n{trecho.texto[:1800]}"
        )
    linhas.append(
        f"\nSão {len(usados)} julgados REAIS, vindos do acervo do escritório. Use os "
        "que de fato se aplicarem a estes fatos, citados pelo número do processo e "
        "com a razão de decidir explicada — e diga em uma frase por que cada um "
        "alcança este caso. NÃO cite julgado só porque tem palavras parecidas: "
        "compare atividade, questão decidida e fundamento determinante, e reconheça "
        "a distinção quando houver. Se nenhum destes servir para um ponto, escreva "
        "[PESQUISAR PRECEDENTE ATUAL E APLICÁVEL SOBRE ESTE PONTO] em vez de forçar "
        "um precedente pouco aderente. Nunca invente processo, ementa ou número."
    )
    return "\n".join(linhas)


def _legislacao_para_redigir(contexto: str, consultas: list[dict[str, str]] | None = None) -> str:
    """O texto legal oficial do acervo, ANTES de redigir.

    Mesmo buraco que `_precedentes_para_redigir` fechou para os julgados, e pelo
    mesmo motivo: a legislação federal está vetorizada e completa no pgvector
    (CLT com 819 trechos, CF/88, CPC, Código Civil, CPP e outras), mas NADA dela
    chegava ao prompt. A IA fundamentava de memória — e artigo citado de memória
    é artigo que sai com número errado numa peça que vai a protocolo.

    `rag.buscar_legislacao` já filtra `f.tipo='lei'`, então acórdão não entra
    aqui: julgado tem o canal dele e os dois não se misturam no prompt.

    Falha não interrompe a geração: sem base, a peça sai como saía antes.
    """
    try:
        # Mais de um núcleo jurídico costuma coexistir na mesma inicial
        # (competência, mérito, prova, consectários). Dez trechos favoreciam a
        # primeira tese e deixavam as demais com fundamentação de memória.
        if consultas:
            trechos, provs, erros_tese = recuperacao_por_tese.legislacao(consultas)
            if not trechos and erros_tese:
                raise RuntimeError("; ".join(erros_tese[:3]))
            _registrar_proveniencia(provs, [t.texto[:1500] for t in trechos])
            _guardar_trechos("legislacao", trechos)
        else:
            trechos = rag.buscar_legislacao(contexto[:12_000], limite=14)
    except Exception as erro:
        log.warning("petição local: legislação indisponível na redação: %s", erro)
        _diag("legislacao", ok=False, n=0, erro=_erro_curto(erro))
        return ""
    if not trechos:
        _diag("legislacao", ok=True, n=0)
        return ""
    _diag("legislacao", ok=True, n=len(trechos), por_tese=bool(consultas),
          scores=[round(float(t.similaridade), 4) for t in trechos])
    linhas = ["\n\n=== LEGISLAÇÃO DO ACERVO (use no DO DIREITO) ==="]
    for indice, trecho in enumerate(trechos, start=1):
        titulo = trecho.titulo or trecho.identificador or "lei"
        linhas.append(f"\n[L{indice}] {titulo}\n{trecho.texto[:1500]}")
    linhas.append(
        f"\nSão {len(trechos)} dispositivos legais OFICIAIS do acervo do "
        "escritório. Para CADA norma que usar, identifique a espécie, número e "
        "denominação (quando houver), o artigo/parágrafo/inciso, sintetize com "
        "precisão o comando normativo e explique a consequência dele PARA ESTES "
        "fatos; uma referência solta como 'art. 927 do CC' é insuficiente. "
        "Transcreva só o excerto indispensável quando ele sustentar diretamente a "
        "tese, sem colar lei em bloco. Nunca invente número de artigo nem cite "
        "dispositivo que não esteja acima — se o que você precisa não estiver aqui, "
        "fundamente sem inventar."
    )
    return "\n".join(linhas)


def _padroes_conteudisticos_para_redigir(
    contexto: str, *, categoria_nome: str = "", categoria_codigo: str = "",
    consultas: list[dict[str, str]] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Traz técnica de peças do escritório para influenciar diretamente a minuta.

    Não são fontes jurídicas nem fatos do novo caso. Entram como exemplos de
    densidade argumentativa, ordem de teses e completude de pedidos, com barreira
    explícita contra contaminação entre clientes.

    O assunto do CASO (mesmo identificador de `peticao_skill_arquivos`, ex.
    "doenca_ocupacional_acidente_trabalho") prefere peças classificadas no mesmo
    assunto (`scripts/classificar_pecas.py`) — sem isso, um caso de acidente nos
    Correios competia igual contra as 700+ peças misturadas, só pela similaridade
    do texto inteiro.

    Devolve também a lista de referências usadas (arquivo, categoria,
    similaridade, mesmo_assunto) — sem isso, saber quais das 700+ peças
    alimentaram uma geração específica exigia ler o log do servidor linha a linha.
    """
    assunto = peticao_skill_arquivos.assuntos_relacionados(categoria_nome, categoria_codigo, contexto[:20_000])
    try:
        if consultas:
            trechos, provs, erros_tese = recuperacao_por_tese.pecas(consultas, assunto)
            if not trechos and erros_tese:
                raise RuntimeError("; ".join(erros_tese[:3]))
            _registrar_proveniencia(provs, [t["texto"][:1800] for t in trechos])
        else:
            trechos = rag.buscar_pecas_conteudisticas(contexto[:12_000], limite=8, assunto=assunto)
    except Exception as erro:
        log.warning("petição local: acervo de peças indisponível na redação: %s", erro)
        _diag("pecas", ok=False, n=0, assunto=assunto, erro=_erro_curto(erro))
        return "", []
    if not trechos:
        _diag("pecas", ok=True, n=0, assunto=assunto)
        return "", []
    linhas = ["\n\n=== PADRÕES CONTEUDÍSTICOS DO ACERVO DO ESCRITÓRIO ==="]
    referencias: list[dict[str, Any]] = []
    for indice, trecho in enumerate(trechos, start=1):
        classe = "peça complexa" if trecho["categoria"] == "pecas_complexas" else "peça simples"
        linhas.append(f"\n[P{indice}] referência interna ({classe}; arquivo: {trecho['arquivo']})\n{trecho['texto'][:1_800]}")
        referencias.append({
            "arquivo": trecho["arquivo"], "categoria": trecho["categoria"],
            "similaridade": round(float(trecho["similaridade"]), 4),
            "mesmo_assunto": bool(trecho.get("mesmo_assunto")),
            "eh_inicial": bool(trecho.get("eh_inicial")),
            "chars_peca": int(trecho.get("chars_peca") or 0),
        })
    linhas.append(
        "\nEstas referências internas servem APENAS para elevar a qualidade: aproveite a "
        "estrutura lógica, a profundidade, os contrapontos, a explicação de cada fundamento "
        "e a completude dos pedidos quando forem compatíveis com ESTE caso. NUNCA copie ou "
        "transporte nomes, CPF, endereço, empresa, datas, valores, documentos, fatos, pedido "
        "ou citação jurídica de outra referência. Toda afirmação da nova peça deve nascer do "
        "material deste caso e toda norma ou precedente deve estar no bloco oficial próprio. "
        # Peça antiga do acervo é AMOSTRA de profundidade, não gabarito de formato — o
        # escritório muda como redige com o tempo, e a orientação atual (skill) é
        # sempre mais nova que qualquer uma destas referências. Sem esta frase o
        # modelo tratava as duas fontes como igual peso e às vezes seguia a
        # ESTRUTURA de uma peça velha em vez da orientação vigente.
        "Se a ORIENTAÇÃO DO ESCRITÓRIO (skill, abaixo) indicar título, ordem de seção, "
        "formato de tabela ou qualquer critério estrutural diferente do que aparece "
        "nestas referências, a orientação do escritório PREVALECE — estas referências "
        "não definem formato, só mostram nível de profundidade e raciocínio a igualar."
    )
    _diag(
        "pecas", ok=True, n=len(referencias), assunto=assunto,
        mesmo_assunto=sum(1 for r in referencias if r["mesmo_assunto"]),
        arquivos=[r["arquivo"] for r in referencias],
        scores=[r["similaridade"] for r in referencias],
        chars_injetados=sum(min(len(t["texto"]), 1_800) for t in trechos),
    )
    return "\n".join(linhas), referencias


def _outline_juridico(contexto: str, caso_id: str = "") -> dict[str, Any] | None:
    """Planeja a peça ANTES de redigir: cronologia, teses e o que cada seção deve trazer.

    A redação em uma única chamada (`gerar`) pedia ao modelo para organizar o
    material e escrever a petição inteira ao mesmo tempo — e em textos longos
    isso produz seções mais curtas e genéricas, sobretudo FACTS e LEGAL_GROUNDS,
    porque planejar e redigir competem pela mesma passada de atenção. Aqui o
    plano sai de uma chamada própria, menor e mais barata, e vira mais um bloco
    do material da chamada de redação — o modelo lê o próprio roteiro antes de
    escrever, em vez de inventar a estrutura sobre a hora.

    Mesma régua das outras funções de contexto (`_precedentes_para_redigir` e
    companhia): falha aqui não pode derrubar a geração. Sem plano, a peça sai
    como saía antes — só perde o roteiro, não a petição inteira.
    """
    instrucao = (
        "Você é advogado trabalhista organizando o material de um caso ANTES de "
        "redigir a petição inicial. Não redija a peça agora — planeje.\n\n"
        "Leia a entrevista e os documentos a seguir e devolva APENAS o plano, em "
        "JSON, com:\n"
        "{\n"
        '  "cronologia": [{"id":"C1","data":"data ou período, como consta no material",'
        ' "fato":"o que aconteceu", "fonte":"documento ou entrevista de onde veio"}],\n'
        '  "teses": [{"id":"T1","tese":"tese jurídica a sustentar",'
        ' "fatos_ids":["C1","C3"], "fatos_que_sustentam":["fato da cronologia acima"],'
        ' "fundamentos_legais":["dispositivo"], "jurisprudencias":["precedente do material"], "consequencia":"consequência jurídica desta tese",'
        ' "funcao_argumentativa":"o papel desta tese na peça (diferente das outras)", "gera_pedido":true|false,'
        ' "provas":["documento/trecho que comprova"],'
        ' "pedidos_relacionados":["pedido que decorre desta tese"]}],\n'
        '  "pedidos": ["cada pedido a formular, na ordem"],\n'
        '  "secoes": [{"code":"papel da seção (FACTS, LEGAL_GROUNDS, CLAIMS…) — só as que a skill manda",'
        ' "pontos":["o que esta seção precisa cobrir, em ordem"]}],\n'
        '  "riscos_ou_lacunas": ["fato relevante sem prova, contradição, dado faltante"],\n'
        '  "partes": {"autor": {"nome":"","nacionalidade":"","estado_civil":"","profissao":"","cpf":"","rg":"","pis":"","ctps":"",'
        '"endereco":"","cep":"","telefone":"","email":""}, "reu": {"nome":"","cnpj":"","endereco":"","cep":""}},\n'
        '  "pedidos_estruturados": [{"tipo":"categoria jurídica curta (ex.: dano moral)", "tese_id":"T1", "tese":"a tese do plano de que este pedido nasce",'
        ' "objeto":"o que exatamente se pede", "causa_de_pedir":"a lesão/fato jurídico que fundamenta (mesma lesão = mesma causa)",'
        ' "natureza":"cumulativo|subsidiario|alternativo", "fundamento":"norma/tese", "valor_ou_base":"valor em R$ com o critério, ou vazio",'
        ' "valor_numerico":número ou null, "metodo_calculo":{"base":número,"multiplicador":número,"resultado":número,"criterio":"ex.: salário líquido do contracheque"},'
        ' "tipo_de_item":"autonomo|agravante|criterio_de_quantificacao|consequencia|acessorio", "agrava":"tipo do pedido que este agrava (se agravante)",'
        ' "bem_juridico":"", "evento_causador":"", "dano":"o dano concreto reparado", "objeto_economico":"o que se paga",'
        ' "de_praxe":true se for pedido de praxe exigido pela skill (gratuidade, honorários, juros, provas...)}]\n'
        "}\n"
        "Um AGRAVANTE (ex.: sequela, adoecimento, duração que aumenta a extensão do MESMO dano) NÃO é pedido econômico próprio: "
        "registre-o com tipo_de_item=agravante, agrava=<pedido principal>, sem valor, e considere-o no metodo_calculo do principal; "
        "só é pedido autônomo se o DANO for outro e isso estiver fundamentado. "
        "Todo pedido de PAGAMENTO autônomo leva `valor_numerico` e `metodo_calculo` (base do documento, multiplicador, resultado, "
        "criterio dizendo de onde saiu a base): no processo do trabalho o pedido é líquido (art. 840, § 1º, da CLT) e a peça traz a "
        "memória de cálculo — nunca «a apurar em liquidação». Sem dado para calcular, o pedido não entra e vai para "
        "`riscos_ou_lacunas`. Verba rescisória (multa do art. 477, multa do art. 467, aviso prévio, 40% do FGTS, seguro-desemprego, "
        "saldo de salário) só existe com o contrato ENCERRADO nos documentos ou com rescisão indireta pedida nesta ação: com o "
        "vínculo ativo, não peça. "
        "`ausencias`: [{\"afirmacao\":\"o que os documentos disponíveis NÃO registram\",\"estado\":\"NOT_FOUND_IN_AVAILABLE_DOCUMENTS|UNKNOWN|DISPUTED\"}] — "
        "nunca como ausência comprovada. "
        "`partes`: SOMENTE dados que constam dos documentos, da entrevista ou do cadastro — campo desconhecido fica vazio, "
        "NUNCA inventado. `pedidos_estruturados` é a ÚNICA lista de pedidos da peça: cada pedido decorre de uma tese com fatos "
        "do caso (ou é de praxe pela skill); não repita o mesmo pedido em dois itens.\n"
        "Baseie-se só no material recebido — não invente fato, data nem documento. "
        "Fato sem fonte identificável não entra na cronologia. Uma tese sem fato "
        "que a sustente não entra em `teses`."
    )
    try:
        if caso_id:
            instrucao = _com_skill_do_escritorio(caso_id, instrucao)
        plano = _com_prazo_total(
            lambda: _llm_json(instrucao, contexto[:60_000], timeout=90.0, repetir_apos_timeout=False,
                              max_tokens=MAX_TOKENS_PLANO),
            PRAZO_PLANO_S)
    except Exception as erro:  # noqa: BLE001 - roteiro é reforço, não pode travar a redação
        log.warning("petição local: outline jurídico indisponível na redação: %s", erro)
        return None
    if not isinstance(plano, dict) or not (plano.get("cronologia") or plano.get("teses")):
        return None
    return plano


def _outline_para_redigir(plano: dict[str, Any] | None) -> str:
    """O plano acima, em texto, para entrar no material da chamada de redação."""
    if not plano:
        return ""
    linhas = ["\n\n=== PLANO DA PEÇA (elaborado antes da redação — siga este roteiro) ==="]
    cronologia = plano.get("cronologia") or []
    if cronologia:
        linhas.append("\nCronologia:")
        for item in cronologia:
            if not isinstance(item, dict):
                continue
            linhas.append(
                f"- {item.get('data', '?')}: {item.get('fato', '')} (fonte: {item.get('fonte', '?')})"
            )
    teses = plano.get("teses") or []
    if teses:
        linhas.append("\nTeses e o que as sustenta:")
        for item in teses:
            if not isinstance(item, dict):
                continue
            fatos = ", ".join(str(f) for f in item.get("fatos_que_sustentam") or [])
            provas = ", ".join(str(p) for p in item.get("provas") or [])
            pedidos = ", ".join(str(p) for p in item.get("pedidos_relacionados") or [])
            linhas.append(
                f"- {item.get('tese', '')} | fatos: {fatos} | provas: {provas} | pedidos: {pedidos}"
            )
    pedidos = plano.get("pedidos") or []
    if pedidos:
        linhas.append("\nPedidos, na ordem sugerida:")
        linhas.extend(f"- {p}" for p in pedidos)
    secoes = plano.get("secoes") or []
    if secoes:
        linhas.append("\nO que cada seção precisa cobrir:")
        for item in secoes:
            if not isinstance(item, dict):
                continue
            pontos = "; ".join(str(p) for p in item.get("pontos") or [])
            linhas.append(f"- {item.get('code', '?')}: {pontos}")
    riscos = plano.get("riscos_ou_lacunas") or []
    if riscos:
        linhas.append("\nRiscos e lacunas identificados no planejamento:")
        linhas.extend(f"- {r}" for r in riscos)
    linhas.append(
        "\nEste roteiro foi montado a partir do MESMO material que você está lendo — "
        "use-o como estrutura, desenvolvendo cada ponto com a profundidade que a "
        "peça exige. Se, ao redigir, um item do roteiro não se sustentar no material, "
        "prevalece o material: não invente fato para encaixar no plano."
    )
    return "\n".join(linhas)


# ------------------------------------------------ conferência contra os autos


def _fontes_da_conferencia(
    caso_id: str, *, texto_entrevista: str | None = None, material: str = ""
) -> conferencia_peticao.Fontes:
    """O que a peça pode afirmar: anexos, entrevista, cadastro e o material do acervo.

    `numerados` repete a numeração do bloco DOCUMENTOS de `_montar_contexto` — é por
    ela que a peça cita "Documento NN", e é contra ela que a citação é conferida.
    """
    if texto_entrevista is None:
        entrevistas = [e for e in armazenamento.listar_entrevistas(caso_id) if str(e.get("texto") or "").strip()]
        texto_entrevista = str(entrevistas[0]["texto"]) if entrevistas else ""
    caso = armazenamento.obter_caso(caso_id) or {}
    try:
        qualificacao = armazenamento.obter_qualificacao(caso_id) or {}
    except Exception:  # noqa: BLE001 — cadastro ausente só estreita as fontes
        qualificacao = {}
    try:
        nome_cat, cod_cat = _nome_e_codigo_da_categoria(caso_id)
        # O que a SKILL traz (precedentes vinculantes, modelos) é fonte citável, como o acervo.
        material = material + "\n" + peticao_skill_arquivos.carregar(nome_cat, cod_cat, _TEXTO_DO_CASO.get())
    except Exception:  # noqa: BLE001 - sem a skill, só o material recebido conta
        pass
    return conferencia_peticao.Fontes(
        anexos=anexos_do_caso(caso_id),
        numerados=[d["arquivo"] for d in documentos_logicos(caso_id)[1]],
        numeros=[d["numero"] for d in documentos_logicos(caso_id)[0]],
        entrevista=texto_entrevista,
        cadastro=" ".join(str(v) for v in [caso.get("cliente"), *qualificacao.values()] if v),
        material=material,
    )


def _achados_da_peca(secoes: list[dict[str, Any]], violacoes: list[Any]) -> list[dict[str, Any]]:
    """Os achados de forma (`avaliar_documento`) e os da conferência, no formato da tela."""
    return [
        *(_achado_legivel(a) for a in peticao_aprendizado.avaliar_documento(secoes)),
        *conferencia_peticao.como_achados(violacoes),
    ]


def _achado_legivel(achado: dict[str, Any]) -> dict[str, Any]:
    """Achado antigo (`code`, `critic`) no formato que a tela espera.

    A tela faz `achado.category.toLowerCase()`: achado sem `category` derrubava o
    cartão inteiro da petição. Os de `avaliar_documento` nasciam assim.
    """
    if achado.get("category") and achado.get("message"):
        return achado
    codigo = str(achado.get("code") or achado.get("critic") or "AVISO")
    mensagens = {
        "MISSING_SECTION": "Seção obrigatória sem texto.",
        "FACTS_TOO_SHORT": "Os fatos estão curtos demais para sustentar os pedidos.",
        "GROUNDS_TOO_SHORT": "A fundamentação está curta demais.",
        "PENDING_INFORMATION": "A peça tem pontos marcados como [PENDENTE] para completar antes do protocolo.",
    }
    return {
        "severity": "BLOCKING" if str(achado.get("severity") or "").upper() == "BLOCKING" else "WARNING",
        "category": codigo,
        "section": str(achado.get("section") or ""),
        "message": str(achado.get("message") or mensagens.get(codigo, codigo)),
        "detail": achado.get("detail"),
    }


def _conferir_contra_os_autos(
    caso_id: str,
    secoes: list[dict[str, Any]],
    *,
    texto_entrevista: str | None = None,
    material: str = "",
    corrigir: bool = True,
) -> tuple[list[dict[str, Any]], list[Any], dict[str, Any]]:
    """Confere a peça contra os autos e corrige cada achado corrigível.

    Devolve as seções (corrigidas e com as citações não verificadas carimbadas), as
    violações que SOBRARAM e o registro do que aconteceu, para o trace da geração.

    A correção é uma revisão com a lista exata dos defeitos — não uma nova geração —
    para não trocar um defeito conhecido por outro desconhecido. Se ela falhar ou não
    resolver, a peça sai RETIDA com os achados: nunca em silêncio.
    """
    fontes = _fontes_da_conferencia(caso_id, texto_entrevista=texto_entrevista, material=material)
    violacoes = conferencia_peticao.conferir(secoes, fontes)
    iniciais = [v.codigo for v in violacoes if v.bloqueia]
    corrigiu = False
    rodadas = 0
    secoes_puladas: list[str] = []
    # Um gate não pode ser parcial: deixar VALUE ou CLAIMS fora da correção por
    # limite de conveniência foi exatamente o que permitiu valores incompatíveis
    # chegarem à minuta. Cada rodada trata todas as seções afetadas, em lotes
    # pequenos para não sobrecarregar o provedor; o resultado é sempre conferido
    # de novo antes de avançar.
    max_rodadas = int(os.getenv("PETICAO_CONFERENCIA_MAX_RODADAS", "3"))
    tamanho_lote = int(os.getenv("PETICAO_CONFERENCIA_LOTE_SECOES", "3"))
    while corrigir and any(v.bloqueia for v in violacoes) and rodadas < max_rodadas and not _sem_tempo(folga_s=120):
        rodadas += 1
        por_secao = {
            str(secao.get("code") or ""): [v for v in violacoes if v.bloqueia and v.secao == secao.get("code")]
            for secao in secoes
        }
        alvos = [s for s in secoes if por_secao.get(str(s.get("code") or ""))]
        alvos.sort(
            key=lambda s: (
                str(s.get("code") or "") not in {"LEGAL_GROUNDS", "FACTS", "CLAIMS"},
                -len(por_secao[str(s.get("code") or "")]),
            )
        )
        secoes_puladas = []
        novas_por_codigo: dict[str, dict[str, Any]] = {}
        for inicio in range(0, len(alvos), max(1, tamanho_lote)):
            lote = alvos[inicio:inicio + max(1, tamanho_lote)]
            extra = _material_para_resolver_pesquisas(violacoes, lote)

            def corrigir_secao(secao: dict[str, Any]) -> dict[str, Any]:
                da_secao = por_secao.get(str(secao.get("code") or ""), [])
                novo = _reescrever_secao(
                    caso_id, secao,
                    conferencia_peticao.instrucao_de_correcao(da_secao, fontes) + extra,
                    material[:35_000],
                )
                return {**secao, "content": novo} if novo and novo != secao.get("content") else secao

            novas_por_codigo.update({
                str(secao.get("code") or ""): corrigida
                for secao, corrigida in zip(lote, _em_paralelo_com_contexto(corrigir_secao, lote, max_workers=len(lote)))
            })
        novas = [novas_por_codigo.get(str(secao.get("code") or ""), secao) for secao in secoes]
        if novas == secoes:
            break
        secoes, corrigiu = novas, True
        violacoes = conferencia_peticao.conferir(secoes, fontes)
    # NÃO se carimba mais "[CONFERIR: …]" no corpo: marcador no texto final é exatamente o que o
    # portão de qualidade proíbe. O que sobrou de citação sem fonte fica nos achados bloqueantes.
    registro = {
        "violacoes_iniciais": iniciais,
        "rodada_de_correcao": corrigiu,
        "rodadas_de_correcao": rodadas,
        "secoes_sem_correcao_por_limite": secoes_puladas,
        "violacoes_restantes": [v.codigo for v in violacoes if v.bloqueia],
        "citacoes_nao_verificadas": sum(1 for v in violacoes if v.codigo == "CITACAO_NAO_VERIFICADA"),
    }
    if iniciais:
        log.warning("petição local: conferência do caso %s: %s", caso_id, registro)
    return secoes, violacoes, registro


#: Marcador de "ponto sem fonte" que o modelo deixa no corpo.
_RE_PONTO_SEM_FONTE = re.compile(r"\[(?:PESQUISAR|CONFERIR)[^\]]*\]", re.IGNORECASE)


def _material_para_resolver_pesquisas(violacoes: list[Any], secoes: list[dict[str, Any]]) -> str:
    """Julgados do acervo para cada `[PESQUISAR …]` que o modelo deixou — a pesquisa que faltou.

    A consulta é o parágrafo que antecede o marcador (é ele que diz QUAL ponto precisa de
    precedente). Vazio se não há marcador ou o acervo não responde; nesse caso a correção
    manda remover a afirmação, nunca inventar.
    """
    consultas: list[dict[str, str]] = []
    for secao in secoes:
        texto = str(secao.get("content") or "")
        for m in _RE_PONTO_SEM_FONTE.finditer(texto):
            trecho = " ".join(texto[max(0, m.start() - 700) : m.start()].split())
            if len(trecho) > 80:
                consultas.append({"tese": trecho[-90:], "consulta": trecho[-600:]})
    if not consultas:
        return ""
    try:
        trechos, provs, _erros = recuperacao_por_tese.precedentes(consultas[:6], "", por_tese=3, total=8)
    except Exception:  # noqa: BLE001 - sem acervo, a correção remove o ponto
        return ""
    if not trechos:
        return "\n\nNenhum julgado do acervo respondeu a estes pontos: REMOVA a afirmação que dependia de precedente ou reescreva-a sem citar precedente. Não deixe marcador."
    _registrar_proveniencia(provs, [t.texto[:1800] for t in trechos])
    linhas = ["\n\nMATERIAL ADICIONAL — julgados REAIS do acervo para resolver os pontos marcados (cite só se alcançarem os fatos; explique por que; não invente número):"]
    for i, t in enumerate(trechos, 1):
        ref = t.referencia()
        linhas.append(f"[R{i}] processo={ref.get('processo') or ref.get('identificador')} natureza={recuperacao_por_tese._natureza(t.metadados)}\n{t.texto[:1500]}")  # noqa: SLF001
    linhas.append("Se nenhum servir, REMOVA a afirmação sem precedente. A peça final não pode conter marcador [PESQUISAR]/[CONFERIR].")
    return "\n".join(linhas)


#: Caracteres médios por palavra em português, contando o espaço — converte o
#: tamanho em texto das peças do acervo em palavras.
_CHARS_POR_PALAVRA = 6.2


_INSTRUCAO_SECAO = """Você reescreve UMA seção de uma peça jurídica, EXECUTANDO a SKILL DO ESCRITÓRIO que
acompanha esta instrução (estrutura, método de argumentação, formatação e regras de conteúdo).
Devolva APENAS JSON: {"content": "<a seção inteira reescrita, com a mesma marcação de formatação>"}.
Preserve o que já está correto; não mude pedidos, valores, datas, nomes nem números de documento.
Não crie fato, valor, documento, norma ou julgado que o MATERIAL não traga. Sem marcadores
[PESQUISAR]/[CONFERIR]: sem fonte para um ponto, reescreva sem citar precedente."""


def _reescrever_secao(
    caso_id: str, secao: dict[str, Any], orientacao: str, contexto: str = ""
) -> str | None:
    """Reescreve UMA seção (JSON pequeno) — falha de uma seção não perde as outras.

    A passada anterior reescrevia a peça inteira num único JSON de dezenas de milhares de
    caracteres; quando ele vinha malformado ou cortado, a passada inteira era descartada em
    silêncio ("aprofundamento falhou") e a peça ficava rasa. Aqui cada seção tem a própria
    chamada, com o material do caso e da pesquisa junto.
    """
    instrucao = _com_skill_do_escritorio(caso_id, _INSTRUCAO_SECAO, revisao=True)
    entrada = (
        f"MATERIAL DO CASO E DA PESQUISA:\n{contexto[:80_000]}\n\n"
        f"SEÇÃO ATUAL ({secao.get('code')} — {secao.get('label') or 'sem título'}):\n"
        f"{secao.get('content', '')}\n\nORIENTAÇÃO:\n{orientacao}"
    )
    try:
        # Correção pontual não deve competir com a redação principal por cinco
        # minutos. Se o provedor não responder neste teto, a seção original fica
        # preservada e o achado continua visível para revisão humana.
        saida = _llm_json(instrucao, entrada, timeout=150.0)
    except ErroPeticao:
        log.warning("petição local: reescrita da seção %s falhou (caso %s)", secao.get("code"), caso_id, exc_info=True)
        return None
    novo = str(saida.get("content") or "").strip()
    return novo or None


#: Seções que não são argumentação: não se "aprofunda" endereçamento, fecho nem valor da causa.
_SECOES_SEM_ARGUMENTO = {"HEADING", "CLOSING", "VALUE", "JURIMETRY", "CLAIMS"}

_ORIENTACAO_DE_PROFUNDIDADE = (
    "REDIJA ESTE TÓPICO COM ARGUMENTAÇÃO DESENVOLVIDA, como nas petições reais do escritório. Cada "
    "argumento é um bloco COESO onde, quando fizer sentido, fato concreto → enquadramento jurídico → "
    "fundamento legal → aplicação da norma ao caso → prova (\"Documento NN\") → jurisprudência (só a do "
    "material) → conclusão daquele argumento vivem no MESMO parágrafo; NÃO quebre uma linha de raciocínio em "
    "frases soltas (\"O autor sofreu assalto. A empresa responde. Aplica-se o art. X.\"). Junte o que é uma "
    "só ideia; separe parágrafos quando muda o raciocínio. O tamanho vem do padrão medido nas peças reais "
    "(abaixo), não de cota.\n"
    "TODA expansão tem de acrescentar ao menos UMA destas coisas: relação mais precisa entre fato e norma; "
    "dispositivo pertinente; explicação da aplicação do dispositivo; julgado do material com a razão de decidir "
    "aplicada ao caso; documento/prova concreta do caso; consequência jurídica; enfrentamento de argumento "
    "contrário previsível; ligação com o pedido. PROIBIDO aumentar por paráfrase, repetição ou linguagem "
    "jurídica vazia.\n"
    "Aproveite dos EXEMPLOS DO ESCRITÓRIO o modo de desenvolver a tese, a ordem das ideias, os fundamentos que "
    "aparecem com frequência e o vocabulário — sintetizando vários, sem copiar. Os exemplos NÃO são fonte de fato "
    "nem de citação. Transcrição de julgado, súmula ou lei vai em bloco `>` próprio com a identificação ao final "
    "do bloco, conforme a skill (formatacao.md), nunca entre aspas no meio do parágrafo."
)

_ORIENTACAO_DO_REVISOR = (
    "REVISÃO DE PROFUNDIDADE. Antes de reescrever, responda a si mesmo: a tese foi desenvolvida ou só afirmada? há fatos "
    "concretos do caso? há prova relacionada? a norma foi APLICADA ao caso ou só citada? há argumento do acervo "
    "(exemplos) ou julgado do material que ficou de fora? o raciocínio está fragmentado em parágrafos pequenos demais? "
    "há parágrafo genérico que possa virar fundamentação concreta? há repetição? Reescreva SOMENTE onde houver ganho "
    "jurídico real: una parágrafos que são uma só linha de raciocínio, troque o genérico por fato/prova/norma/precedente "
    "específicos e elimine a repetição. Se o tópico já está bem desenvolvido, devolva-o igual."
)


def _plano_do_topico(titulo: str, plano: dict[str, Any] | None, material: Any) -> str:
    alvo = set(recuperacao_por_secao._termos(titulo))  # noqa: SLF001
    melhor = None
    for t in (plano or {}).get("teses") or []:
        if isinstance(t, dict) and t.get("tese"):
            af = len(alvo & set(recuperacao_por_secao._termos(str(t["tese"]))))  # noqa: SLF001
            if af and (melhor is None or af > melhor[0]):
                melhor = (af, t)
    linhas = ["PLANO DO TÓPICO:"]
    if melhor:
        t = melhor[1]
        linhas.append(f"- Tese a defender: {t['tese']}")
        linhas.append(f"- Fatos que a sustentam: {'; '.join(map(str, t.get('fatos_que_sustentam') or []))}")
        linhas.append(f"- Provas: {'; '.join(map(str, t.get('provas') or []))}")
    else:
        linhas.append(f"- Tópico: {titulo or '(seção inteira)'} — defina a tese a partir do texto atual e dos fatos do caso.")
    tel = material.telemetria
    linhas.append(f"- Exemplos do escritório recuperados: {len(tel.get('acervo', {}).get('escolhidos', []))} trechos de "
                  f"{tel.get('acervo', {}).get('pecas_distintas_escolhidas', 0)} peças; julgados: {len(tel.get('julgados', []))}; "
                  f"leis: {len(tel.get('legislacao', []))}")
    linhas.append("- Conclusão jurídica a construir: a que decorre da tese e conecta ao pedido correspondente.")
    return "\n".join(linhas)


def _sinal_em_texto(sinal: dict[str, Any], atual: dict[str, Any]) -> str:
    if not sinal.get("disponivel"):
        return "Densidade do acervo indisponível: siga o critério qualitativo."
    return (
        f"PADRÃO MEDIDO nas {sinal['pecas']} petições iniciais reais do escritório deste assunto (SINAL de estilo, não limite): "
        f"parágrafo argumentativo com mediana de {sinal['mediana']:.0f} palavras (faixa usual {sinal['p25']:.0f}–{sinal['p75']:.0f}); "
        f"cerca de {sinal['artigos_por_mil']} citações de artigo por mil palavras. Este tópico hoje: mediana {atual['mediana']:.0f}, "
        f"{atual['paragrafos']} parágrafos, {atual['fragmentacao']:.0%} de parágrafos curtos."
    )


def _contexto_isolado(contexto_caso: str, plano_est: dict[str, Any], tese: dict[str, Any]) -> str:
    """Cabeçalho do caso + só os documentos que esta tese usa (se nenhum casar, mantém tudo)."""
    blocos = re.split(r"(?=\n--- DOCUMENTO \d+:)", contexto_caso)
    if len(blocos) < 2:
        return contexto_caso
    por_id = {f["id"]: f for f in plano_est.get("fatos") or [] if isinstance(f, dict) and f.get("id")}
    ids = [*(tese.get("fatos_ids") or []), *plano_da_peticao.fatos_comuns(plano_est)]
    alvos = " ".join(str(p) for p in (tese.get("provas") or [])) + " " + " ".join(
        d for i in ids for d in ((por_id.get(i) or {}).get("documentos") or [])
    )
    alvo_norm = plano_da_peticao.norm(alvos)
    manter = [b for b in blocos[1:] if (m := re.match(r"\n--- DOCUMENTO (\d+): (.*?) ---", b))
              and (plano_da_peticao.norm(m.group(2))[:40] in alvo_norm or f"documento {int(m.group(1))}" in alvo_norm)]
    return blocos[0] + "".join(manter) if manter else contexto_caso


def _aprofundar_topico(
    caso_id: str, secao: dict[str, Any], topico: dict[str, str], *, contexto_caso: str, plano: dict[str, Any] | None,
    categoria: str, assuntos: list[str], sinal: dict[str, Any], apoio: str, contexto_uf: str,
    plano_est: dict[str, Any] | None = None, orientacoes_motor: dict[str, dict[str, str]] | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    titulo, corpo = topico["titulo"], topico["corpo"]
    tese = plano_da_peticao.tese_do_topico(plano_est, titulo, corpo) if plano_est and titulo else None
    do_motor = juridico_raciocinio.orientacao_para_topico(orientacoes_motor, titulo, corpo)
    if tese:  # cada tese só vê os fatos dela (+ os comuns) e os documentos que a provam
        contexto_caso = _contexto_isolado(contexto_caso, plano_est, tese)  # type: ignore[arg-type]
        apoio = plano_da_peticao.contexto_da_tese(plano_est, tese)  # type: ignore[arg-type]
    material = recuperacao_por_secao.material_do_topico(
        titulo, corpo, str(secao.get("label") or ""), plano=plano, categoria=categoria, assuntos=assuntos, contexto_uf=contexto_uf,
    )
    antes = recuperacao_por_secao.metricas(corpo)
    orientacao = "\n\n".join([
        _ORIENTACAO_DE_PROFUNDIDADE, _plano_do_topico(titulo, plano, material), _sinal_em_texto(sinal, antes), apoio,
        *([do_motor] if do_motor else []),
    ])
    base = {"code": secao.get("code"), "label": titulo or secao.get("label"), "content": corpo}
    contexto = contexto_caso + "\n\n" + material.texto
    tel = {**material.telemetria, "secao": secao.get("code"), "antes": antes, "etapas": [],
           "tese": tese["id"] if tese else None, "textos_acervo": [t for p, t in material.itens if p.canal == "peca"],
           "orientacao_do_motor": bool(do_motor)}

    def aceitar(novo: str | None) -> bool:
        return bool(novo) and len(novo.split()) >= len(corpo.split()) * 0.9 and not _RE_PONTO_SEM_FONTE.search(novo or "")

    atual = corpo
    novo = _reescrever_secao(caso_id, base, orientacao, contexto)
    if aceitar(novo):
        atual = novo  # type: ignore[assignment]
    tel["etapas"].append({"etapa": "redacao_do_topico", "aceito": atual is not corpo})
    depois = recuperacao_por_secao.metricas(atual)
    motivos = recuperacao_por_secao.precisa_de_revisao(depois, sinal)
    if motivos and not _sem_tempo(folga_s=300):  # revisor de profundidade: só onde a medida aponta problema
        revisado = _reescrever_secao(
            caso_id, {**base, "content": atual},
            _ORIENTACAO_DO_REVISOR + "\nMotivos medidos: " + "; ".join(motivos) + "\n" + _sinal_em_texto(sinal, depois), contexto,
        )
        ganho = False
        if aceitar(revisado):
            m2 = recuperacao_por_secao.metricas(revisado)  # type: ignore[arg-type]
            ganho = m2["fragmentacao"] <= depois["fragmentacao"] and (m2["mediana"] >= depois["mediana"] or m2["artigos_por_mil"] > depois["artigos_por_mil"])
            if ganho:
                atual = revisado  # type: ignore[assignment]
        tel["etapas"].append({"etapa": "revisor_de_profundidade", "motivos": motivos, "aceito": ganho})
    final = recuperacao_por_secao.metricas(atual)
    # influência: o que do material deixou marca no tópico final (e quais dispositivos entraram vindos do acervo)
    recuperacao_por_tese.medir_influencia(material.itens, [{"code": secao.get("code"), "content": atual}])
    contribuiu = Counter(p.canal for p, _ in material.itens if p.contribuiu)
    executou = Counter(p.canal for p, _ in material.itens)
    novos_artigos = sorted(set(re.findall(r"art\.?\s*\d+", atual, re.IGNORECASE)) - set(re.findall(r"art\.?\s*\d+", corpo, re.IGNORECASE)))
    tel.update({"depois": final, "contribuiu": dict(contribuiu), "executou": dict(executou), "artigos_novos": novos_artigos,
                "influencia": [{"id": p.id[:50], "canal": p.canal, "score": round(p.score, 3)} for p, _ in material.itens if p.contribuiu]})
    log.info("aprofundamento [%s / %s]: exemplos=%s julgados=%s leis=%s | palavras %s→%s mediana %s→%s | usados=%s",
             secao.get("code"), (titulo or "")[:40], executou.get("peca", 0), executou.get("precedente", 0), executou.get("legislacao", 0),
             antes["palavras"], final["palavras"], antes["mediana"], final["mediana"], dict(contribuiu))
    return {**topico, "corpo": atual}, tel


def _aprofundar_pela_referencia(
    caso_id: str,
    secoes: list[dict[str, Any]],
    brief: dict[str, Any] | None,
    referencias: list[dict[str, Any]],
    *,
    contexto: str = "",
    plano: dict[str, Any] | None = None,
    categoria: str = "",
    assuntos: list[str] | None = None,
    plano_est: dict[str, Any] | None = None,
    orientacoes_motor: dict[str, dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Redige/aprofunda TÓPICO A TÓPICO, com recuperação própria no acervo para cada um.

    `orientacoes_motor`: por tese, o que o motor jurídico (modo assistido) pede ao capítulo — requisitos frágeis,
    prova a usar primeiro, tom pela certeza jurídica e defesas a neutralizar com prova.

    Para cada subcapítulo argumentativo: consultas do tópico → busca vetorial no acervo (todas as peças de
    mérito) → reranking híbrido → exemplos diversificados + julgados e legislação do mesmo tópico → redação com
    plano do tópico e o padrão de densidade MEDIDO nas iniciais reais → revisor de profundidade (só onde a medida
    aponta fragmentação/rasura) → medição de influência. Falha de um tópico não derruba os outros.
    """
    assuntos = assuntos or []
    palavras = sum(len(str(x.get("content") or "").split()) for x in secoes)
    info: dict[str, Any] = {"palavras_antes": palavras, "aplicado": False, "por_topico": []}
    sinal = recuperacao_por_secao.sinal_de_estilo(assuntos) if assuntos else {"disponivel": False}
    info["sinal_de_estilo"] = sinal
    fatos = [f"{f['id']}: {f['descricao']}" for f in (brief or {}).get("facts") or [] if not f.get("contradiz_entrevista")]
    eventos = [f"{e['id']} ({e['data']}): {e['evento']}" for e in (brief or {}).get("timeline") or []]
    cronologia = [f"{c.get('data', '')}: {c.get('fato', '')} [{c.get('fonte', '')}]"
                  for c in (plano or {}).get("cronologia") or [] if isinstance(c, dict)]
    apoio = ("Fatos apurados: " + " | ".join(fatos) + "\n" if fatos else "") \
        + ("Cronologia do brief: " + " | ".join(eventos) + "\n" if eventos else "") \
        + ("Cronologia do plano: " + " | ".join(cronologia) if cronologia else "")
    # Só a parte do CASO (fatos, documentos, análise documental): o material recuperado é montado por tópico.
    contexto_caso = contexto.split("\n\n=== JULGADOS SEMELHANTES")[0][:70_000]

    jobs: list[tuple[int, int, dict[str, Any], dict[str, str]]] = []
    topicos_por_secao: dict[int, list[dict[str, str]]] = {}
    for i, secao in enumerate(secoes):
        conteudo = str(secao.get("content") or "")
        if secao.get("code") in _SECOES_SEM_ARGUMENTO or len(conteudo.split()) < 80:
            continue
        topicos = recuperacao_por_secao.dividir_em_topicos(conteudo)
        topicos_por_secao[i] = topicos
        for k, t in enumerate(topicos):
            if len(t["corpo"].split()) >= 60:
                jobs.append((i, k, secao, t))

    # Só os tópicos mais longos (os que carregam a argumentação) e no máximo 8 — cada um custa 1–2 chamadas.
    jobs = sorted(jobs, key=lambda j: len(j[3]["corpo"].split()), reverse=True)[:8]

    def trabalhar(job):
        i, k, secao, t = job
        if _sem_tempo(folga_s=240):
            return i, k, t, {"topico": t["titulo"], "pulado": "orçamento de tempo"}
        try:
            return i, k, *_aprofundar_topico(
                caso_id, secao, t, contexto_caso=contexto_caso, plano=plano, categoria=categoria, assuntos=assuntos,
                sinal=sinal, apoio=apoio, contexto_uf=contexto, plano_est=plano_est, orientacoes_motor=orientacoes_motor,
            )
        except Exception as erro:  # noqa: BLE001 - um tópico que falha fica como estava
            log.warning("aprofundamento do tópico %s falhou: %s", t["titulo"][:40], erro, exc_info=True)
            return i, k, t, {"topico": t["titulo"], "erro": f"{type(erro).__name__}: {str(erro)[:120]}"}

    for i, k, novo, tel in _em_paralelo_com_contexto(trabalhar, jobs, max_workers=6):
        if True:  # noqa: SIM108 - bloco mantido para preservar o corpo do laço original
            topicos_por_secao[i][k] = novo
            extra = tel.pop("textos_acervo", []) if isinstance(tel, dict) else []
            info.setdefault("textos_acervo", []).extend(extra or [])
            info["por_topico"].append(tel)
    novas = []
    for i, secao in enumerate(secoes):
        if i in topicos_por_secao:
            novas.append({**secao, "content": recuperacao_por_secao.remontar(topicos_por_secao[i])})
        else:
            novas.append(secao)
    info["aplicado"] = any(t.get("depois") and t["depois"]["palavras"] != t["antes"]["palavras"] for t in info["por_topico"])
    info["palavras_depois"] = sum(len(str(x.get("content") or "").split()) for x in novas)
    info["metricas_finais"] = recuperacao_por_secao.metricas("\n\n".join(str(x.get("content") or "") for x in novas
                                                                        if x.get("code") not in _SECOES_SEM_ARGUMENTO))
    return novas, info


def _validar_contra_skill_e_brief(
    caso_id: str, secoes: list[dict[str, Any]], brief: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Segunda leitura da peça PRONTA, contra o case brief e a skill — não contra o
    material bruto (isso é `_conferir_contra_os_autos`, que já roda antes desta).

    `_conferir_contra_os_autos` prova invenção — documento citado que não existe,
    número sem origem. Esta função prova OMISSÃO E DESVIO — fato relevante que a
    análise confirmou e a peça não usou, seção que ficou rasa apesar do material
    disponível, regra da skill (estrutura, valor mínimo da causa, prescrição
    sempre tratada) que não foi seguida. As duas juntas cobrem o que o item 18 do
    pedido chama de "alucinações", "omissões" e "descumprimento da skill".

    Uma chamada para DETECTAR, e só se houver problema real uma segunda para
    CORRIGIR — reaproveitando `_revisar_secoes_via_llm`, o mesmo motor que já
    aplica a crítica de um advogado humano. Sem case brief (leitura de documentos
    fora do ar), não há contra o que validar: devolve a peça como está.
    """
    if not brief:
        return secoes, []
    if not (brief.get("facts") or brief.get("timeline")):
        # Sem fatos apurados não há contra o que validar — e validar assim fabrica
        # problemas: com o brief vazio o revisor acusava "nome divergente" e
        # "alucinação" em tudo o que a peça tirou legitimamente da entrevista e do
        # OCR, e a correção automática reescrevia a peça por cima dessas acusações
        # falsas. Melhor não rodar e dizer por quê (ver `pipeline.fallbacks`).
        _diag("validacao", ok=False, motivo="brief sem fatos — validação pulada")
        return secoes, []
    minuta = "\n\n".join(f"### {s.get('code')}\n{s.get('content') or ''}" for s in secoes)
    instrucao = (
        "Você é um revisor jurídico sênior conferindo uma petição trabalhista já "
        "pronta contra o CASE BRIEF do caso (fatos e provas já apurados dos "
        "documentos) e as regras de redação do escritório, abaixo. Aponte SOMENTE "
        "problemas reais — não reescreva nada agora, só liste.\n\n"
        + peticao_skill_arquivos._ler("regras_redacao.md")  # noqa: SLF001 - mesmo pacote
        + "\n\n"
        + peticao_skill_arquivos._ler("regras_complementares.md")  # noqa: SLF001
        + '\n\nDevolva JSON: {"problemas": [{"tipo": '
        '"omissao|contradicao|alucinacao|data_divergente|nome_divergente|'
        'valor_divergente|secao_rasa|descumprimento_da_skill|placeholder", '
        '"descricao": "o problema, específico e acionável", "secao": "CODE ou '
        'null"}], "correcao_necessaria": true|false}\n'
        '"correcao_necessaria" só é true se houver problema que realmente '
        "prejudique a peça — fato do brief irrelevante para a tese não é "
        "omissão; parágrafo curto mas completo não é seção rasa."
    )
    entrada = (
        f"CASE BRIEF:\n{case_brief.para_prompt(brief)[:20_000]}\n\n"
        f"PETIÇÃO GERADA:\n{minuta[:70_000]}"
    )
    try:
        saida = _llm_json(instrucao, entrada, timeout=180.0)
    except Exception as erro:
        log.warning("petição local: validação skill/brief indisponível: %s", erro)
        return secoes, []
    problemas = [
        p for p in (saida.get("problemas") or [])
        if isinstance(p, dict) and str(p.get("descricao") or "").strip()
    ]
    if not problemas or not saida.get("correcao_necessaria"):
        return secoes, problemas

    prompt_critica = (
        "Revisão automática encontrou os problemas abaixo — corrija cada um "
        "sem alterar o que já está certo:\n"
        + "\n".join(f"- [{p.get('tipo', '?')}] {p.get('descricao', '')}" for p in problemas)
    )
    try:
        corrigidas, info = _revisar_secoes_via_llm(caso_id, secoes, prompt_critica)
        if info.get("alterou"):
            por_codigo = {s["code"]: s["content"] for s in corrigidas}
            secoes = [
                {**s, "content": por_codigo[s["code"]]} if s["code"] in por_codigo else s
                for s in secoes
            ]
    except ErroPeticao:
        log.warning("petição local: correção pós-validação falhou (caso %s)", caso_id, exc_info=True)
    return secoes, problemas


def _aplicar_conferencia(dados: dict[str, Any], secoes: list[dict[str, Any]], violacoes: list[Any]) -> None:
    """Grava na peça os achados e quantos deles a retêm."""
    achados = _achados_da_peca(secoes, violacoes)
    bloqueantes = sum(1 for a in achados if a["severity"] == "BLOCKING")
    dados["review"] = {**(dados.get("review") or {}), "findings": achados, "blocking": bloqueantes}
    dados["blocking_findings"] = bloqueantes


@skill_peticao.com_skill_do_caso
def _reconferir(caso_id: str, dados: dict[str, Any]) -> None:
    """Depois de edição humana: confere de novo, sem correção automática.

    Quem editou foi o advogado — reescrever por cima dele seria pior que o defeito.
    Mas o achado volta a refletir o texto que ELE deixou, inclusive sumindo quando
    ele corrige.
    """
    secoes = [s for s in dados.get("sections") or [] if s.get("code") != "JURIMETRY"]
    try:
        _, violacoes, _ = _conferir_contra_os_autos(caso_id, secoes, corrigir=False)
    except Exception:  # noqa: BLE001 — conferência não pode impedir salvar a edição
        log.warning("petição local: reconferência falhou (caso %s)", caso_id, exc_info=True)
        return
    _aplicar_conferencia(dados, secoes, violacoes)


@skill_peticao.com_skill_do_caso
@_com_documentos_da_geracao
def gerar(caso_id: str, *, texto_entrevista: str) -> dict[str, Any]:
    """Analisa e redige em uma chamada única à DeepSeek."""
    generation_id = str(uuid.uuid4())
    data_da_peticao = date.today()
    diag: dict[str, Any] = {"recuperacao": {}, "fallbacks": []}
    _DIAG.set(diag)
    _INICIO_DA_GERACAO.set(time.monotonic())
    avancar_etapa("Lendo entrevista e documentos…", 5)
    regras_aplicadas = peticao_aprendizado.regras_para_contexto(
        categoria=_categoria_do_caso(caso_id)
    ) or []
    peticao_aprendizado.registrar_execucao(
        generation_id=generation_id, caso_id=caso_id,
        skill_name="learned_preferences_retrieval", itens_recuperados=[
            {"id": r.get("id"), "tipo": r.get("tipo"), "confidence": r.get("confidence")}
            for r in regras_aplicadas
        ], confidence=max((float(r.get("confidence") or 0) for r in regras_aplicadas), default=None),
    )
    try:
        brief = case_brief.montar(caso_id)
    except Exception as erro:
        log.warning("petição local: case brief indisponível para trace/cobertura: %s", erro)
        brief = None
    contexto = _montar_contexto(caso_id, texto_entrevista, brief=brief)
    avancar_etapa("Montando o resumo jurídico do caso…", 12)
    nome_categoria, codigo_categoria = _nome_e_codigo_da_categoria(caso_id)
    # O plano (teses + fatos + provas) vem ANTES da recuperação: é dele que saem as consultas.
    avancar_etapa("Planejando teses, fatos e provas…", 18)
    plano = _outline_juridico(contexto, caso_id)
    avancar_etapa("Cruzando o plano com os documentos do caso…", 20)
    outline = _outline_para_redigir(plano)
    # PETITION_PLAN: partes verificadas, fatos com id, teses isoladas, pedidos únicos (fonte única).
    texto_do_caso = contexto
    # CASE_FACTS: UMA fonte canônica (valor, fonte, confiança, conflito) — a peça inteira consulta os mesmos dados.
    def _montar_plano() -> tuple[dict[str, Any], str]:
        dados_docs = _dados_por_documento(caso_id)
        fontes_do_caso = [{"tipo": "documento", "nome": d["arquivo"], "texto": d["texto"],
                           "tipo_documento": (dados_docs.get(d["arquivo"]) or {}).get("tipo", ""),
                           "dados": (dados_docs.get(d["arquivo"]) or {}).get("dados") or []}
                          for d in documentos_logicos(caso_id)[1]]
        fontes_do_caso.append({"tipo": "entrevista", "nome": "entrevista", "texto": texto_entrevista or ""})
        fatos_canonicos = case_facts.montar(
            fontes=fontes_do_caso, cadastro=_cadastro_estruturado(caso_id), proposta_partes=(plano or {}).get("partes"),
            eventos=(plano or {}).get("cronologia") or [],
        )
        estruturado = plano_da_peticao.montar(
            plano, partes=case_facts.partes_resolvidas(fatos_canonicos), fatos_documentais=_fatos_documentais(caso_id),
        )
        estruturado["case_facts"] = fatos_canonicos
        estruturado["contrato_secoes"] = contrato_secoes.montar(peticao_skill_arquivos.estrutura_da_skill() or [])
        estruturado["_funcoes_de_conteudo"] = peticao_skill_arquivos.validacoes_da_skill()["parametros"].get("funcoes_de_conteudo") or {}
        return estruturado, plano_da_peticao.para_prompt(estruturado)

    plano_vazio = {
        "partes": {"autor": {}, "reu": {}}, "fatos": [], "teses": [], "pedidos": [], "ausencias": [],
        "case_facts": {"PARTIES": {"autor": {}, "reu": {}}, "UNCERTAINTIES": []},
        "contrato_secoes": contrato_secoes.montar(peticao_skill_arquivos.estrutura_da_skill() or []),
        "_funcoes_de_conteudo": {},
    }
    plano_est, texto_plano = _tentar_etapa("plano estruturado", _montar_plano, (plano_vazio, ""), diag)
    # A data é uma entrada de geração, não uma decisão do redator. Ela acompanha
    # o plano até o higienizador final para nenhuma etapa trocar o fechamento por
    # `date.today()` de outro processo/dia.
    plano_est["petition_date"] = data_da_peticao.isoformat()
    if texto_plano:
        outline += "\n\n" + texto_plano
    # CAMADA JURÍDICA (PETICAO_PIPELINE_JURIDICO_MODE): issue spotting sobre o catálogo inteiro da skill.
    # strict: ANTES da recuperação (as teses viram consultas) e a peça nasce do PETITION_PLAN; falha não cai
    #         em silêncio para o legado — vai a `falhas_juridicas` e a peça não é marcada como pronta.
    # shadow: em paralelo à geração legada, sem tocar texto, prontidão nem avisos da peça entregue.
    # assistido: o legado (modo off) com o motor jurídico em segundo plano — orienta o aprofundamento se ficar
    #            pronto a tempo e, no fim, põe lacunas/defesas/críticos nas pendências do advogado.
    modo_juridico = juridico.modo()
    estrito, sombra = modo_juridico == juridico.STRICT, modo_juridico == juridico.SHADOW
    assistido = juridico.assistido()
    falhas_juridicas: list[str] = []
    prep_juridico: dict[str, Any] | None = None
    analise_em_sombra = None
    if estrito:
        avancar_etapa("Identificando todas as teses possíveis do caso…", 22)
        prep_juridico = _etapa_juridica(
            "análise (fatos, teses, cálculos)", lambda: _analise_juridica(caso_id, plano_est, contexto, texto_entrevista, data_da_peticao),
            falhas_juridicas, diag)
    elif sombra or assistido:
        analise_em_sombra = _em_sombra(lambda: _analise_juridica(caso_id, plano_est, contexto, texto_entrevista, data_da_peticao))
    plano_para_consultas = plano
    if estrito and prep_juridico:
        plano_para_consultas = {**(plano or {}), "teses": [*juridico_orq.consultas_das_teses(prep_juridico), *((plano or {}).get("teses") or [])]}
    consultas = recuperacao_por_tese.consultas_do_plano(
        plano_para_consultas, contexto, nome_categoria, consulta_fixa_legada=not estrito)
    _diag("plano", ok=bool(plano), n=len((plano or {}).get("teses") or []),
          teses=[c["tese"] for c in consultas[1:]])
    # Pesquisa externa é lenta. Dispara antes das recuperações locais e da
    # redação para que ela use todo esse tempo em paralelo. Achados novos nunca
    # entram como citação automática: continuam sujeitos ao Citation Gate.
    atualizacao_futura, bloco_atualizacao = _iniciar_atualizacao_juridica(
        plano_est, plano_para_consultas, data_da_peticao
    )
    avancar_etapa("Buscando precedentes, legislação e modelos por tese…", 30)
    uf_jurisprudencia = _uf_jurisprudencia_do_caso(caso_id, contexto)
    precedentes = _precedentes_para_redigir(contexto, consultas, uf=uf_jurisprudencia)
    legislacao = _legislacao_para_redigir(contexto, consultas)
    _TEXTO_DO_CASO.set(contexto[:20_000])
    padroes, referencias_acervo = _padroes_conteudisticos_para_redigir(
        contexto, categoria_nome=nome_categoria, categoria_codigo=codigo_categoria, consultas=consultas
    )
    if estrito and prep_juridico:
        prep_juridico = _etapa_juridica(
            "autoridades e PETITION_PLAN", lambda: _fundamentacao_juridica(
                prep_juridico, diag, uf_jurisprudencia, falhas_juridicas,
                llm_proposicoes=_llm_raciocinio(120.0) if _ligado("PETICAO_MOTOR_PROPOSICOES_LLM") else None),
            falhas_juridicas, diag)
    if estrito and (prep_juridico is None or falhas_juridicas):
        # strict não tem redação degradada: sem a camada jurídica completa, não há peça.
        raise ErroPeticao(
            "Modo strict: a camada jurídica não concluiu — " + "; ".join(falhas_juridicas or ["análise não produzida"])
            + ". Nenhuma peça foi gerada; corrija a causa (ex.: base do Acervo Jurídico) ou use o modo shadow.")
    if estrito and prep_juridico:
        plano_est = prep_juridico["plano_est"]
        outline = _outline_para_redigir(plano) + "\n\n" + plano_da_peticao.para_prompt(plano_est)
        erros_do_plano = juridico_imutabilidade.validar(plano_est)
        # Durante a migração dos planos legados, vínculos de fato/autoridade
        # ainda podem vir incompletos e serão expostos pelos gates no artefato.
        # Os defeitos que alterariam dinheiro ou estrutura, porém, nunca passam.
        erros_fatais = [e for e in erros_do_plano if any(chave in e for chave in (
            "request_id", "sem calculation_id", "valor_da_causa", "pedido inválido",
        ))]
        if erros_fatais:
            raise ErroPeticao("PETITION_PLAN inválido: " + "; ".join(erros_fatais))
        if erros_do_plano:
            diag.setdefault("avisos_do_plano", []).extend(erros_do_plano)
        plano_finalizado = juridico_imutabilidade.congelar(plano_est)
    else:
        plano_finalizado = None
    tamanho_caso = len(contexto)
    contexto += precedentes + legislacao + bloco_atualizacao + padroes + outline
    # O QUE FALTOU, DITO AO MODELO E GRAVADO NA PEÇA.
    #
    # As três buscas caem para "" em silêncio (banco fora, embeddings sem crédito — o
    # 402 do OpenRouter de 18/09/2026). O contrato de redação continuava dizendo "você
    # trabalha com o ACERVO", o modelo acreditava ter fonte e citava súmula de memória.
    insumos = {
        "precedentes": bool(precedentes),
        "legislacao": bool(legislacao),
        "pecas_modelo": bool(padroes),
        "outline": bool(outline),
    }
    resumo_skill = peticao_skill_arquivos.resumo(nome_categoria, codigo_categoria, _TEXTO_DO_CASO.get())
    for canal, info in (diag.get("recuperacao") or {}).items():
        if canal == "validacao":
            continue
        if not info.get("ok"):
            diag["fallbacks"].append(f"{canal}: FALHOU — {info.get('erro', 'sem detalhe')}")
        elif not info.get("n"):
            diag["fallbacks"].append(f"{canal}: consulta funcionou mas não devolveu nada")
    if not resumo_skill["carregada"]:
        diag["fallbacks"].append("skill de arquivo NÃO carregada (arquivos ausentes no deploy?)")
    if not brief or not (brief.get("facts") or brief.get("timeline")):
        diag["fallbacks"].append(
            "case brief vazio — " + ((brief or {}).get("analise_erro") or "a análise não achou fatos")
        )
    for aviso in diag["fallbacks"]:
        log.error("petição local: FALLBACK na geração do caso %s — %s", caso_id, aviso)
    if estrito and diag["fallbacks"]:
        raise ErroPeticao(
            "Modo strict: houve fallback antes da redação — " + "; ".join(diag["fallbacks"])
            + ". Nenhuma peça degradada foi entregue."
        )
    pipeline = {
        "generation_id": generation_id,
        "caso_id": caso_id,
        "tipo_detectado": "INITIAL_PETITION",
        "categoria": {"nome": nome_categoria, "codigo": codigo_categoria},
        "jurisdicao_preferida": tribunais.UF_PARA_TRT.get(uf_jurisprudencia, []),
        "uf_jurisprudencia": uf_jurisprudencia,
        "skill": resumo_skill,
        "layout_rules_source": (peticao_skill_arquivos.configuracao_visual_padrao() or {}).get("fonte_das_regras"),
        "layout_campos_sem_definicao": (peticao_skill_arquivos.configuracao_visual_padrao() or {}).get("campos_sem_definicao"),
        "external_template_loaded": False,
        "active_skill": resumo_skill["skill"],
        "skill_loaded": resumo_skill["carregada"],
        "skill_files_loaded": resumo_skill["arquivos"],
        "skill_version": resumo_skill["sha256"],
        "formatacao_loaded": "formatacao.md" in resumo_skill["arquivos"],
        "renderer_defaults_used": peticao_skill_arquivos.configuracao_visual_padrao().get("campos_sem_definicao"),
        "documentos_do_caso": len((brief or {}).get("evidence") or []),
        "fatos_no_brief": len((brief or {}).get("facts") or []),
        "eventos_no_brief": len((brief or {}).get("timeline") or []),
        "recuperacao": diag.get("recuperacao"),
        "tokens_aprox": {
            "caso": tamanho_caso // 4,
            "skill": resumo_skill["chars"] // 4,
            "acervo_pecas": len(padroes) // 4,
            "precedentes": len(precedentes) // 4,
            "legislacao": len(legislacao) // 4,
            "outline": len(outline) // 4,
        },
        "modelo": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "fallback_acionado": bool(diag["fallbacks"]),
        "fallbacks": diag["fallbacks"],
        "petition_plan_finalized": {
            "ativo": bool(plano_finalizado),
            "hash": juridico_imutabilidade.impressao(plano_est) if plano_finalizado else None,
        },
    }
    if not precedentes and not legislacao:
        contexto += (
            "\n\n=== AVISO: NENHUMA FONTE DO ACERVO FOI RECUPERADA NESTA GERAÇÃO ===\n"
            "Não há julgado, súmula, tema nem texto de lei no material. NÃO cite súmula,"
            " OJ, tema ou processo por número: onde a tese precisar de precedente, escreva"
            " [PESQUISAR PRECEDENTE ATUAL E APLICÁVEL SOBRE ESTE PONTO]. Artigo de lei só"
            " quando for indispensável e de redação notória; na dúvida, [CONFERIR: art. ...]."
        )

    # As críticas DESTE caso, já aplicadas na geração.
    #
    # `_com_skill_do_escritorio` injeta as críticas da CATEGORIA (lições que valem
    # para todo caso parecido). As deste caso específico — inclusive as marcadas
    # "só deste caso", que de propósito não instruem a categoria — ficavam de
    # fora, e gerar de novo desfazia tudo o que o advogado já tinha corrigido
    # aqui. Ele reescrevia as mesmas críticas a cada geração.
    try:
        peticao_criticas.inicializar()
        deste_caso = [
            str(c.get("prompt") or "").strip()
            for c in peticao_criticas.listar_por_caso(caso_id)
            if str(c.get("prompt") or "").strip()
        ][-20:]
    except Exception:
        log.warning("petição local: críticas do caso indisponíveis", exc_info=True)
        deste_caso = []
    if deste_caso:
        contexto += (
            "\n\n=== CORREÇÕES JÁ PEDIDAS NESTE CASO (aplique TODAS desde já) ===\n"
            + "\n".join(f"- {c}" for c in deste_caso)
            + "\nEstas correções já foram cobradas nesta peça. A minuta nova deve "
            "nascer com todas aplicadas, sem precisar que sejam pedidas de novo."
        )
    contexto += _INTEGRIDADE_JURIDICA.format(hoje=data_da_peticao.strftime('%d/%m/%Y')) if estrito else (
        # Só INTEGRIDADE DE DADOS aqui (data, fonte, marcador de pendência). Estrutura,
        # capítulos, valores, prescrição, fechamento e demais regras do ofício moram na
        # SKILL (`references/regras_de_geracao.md`, `estrutura_peca.md`, `formatacao.md`).
        "\n\n=== INTEGRIDADE DOS DADOS ===\n"
        f"DATA DE HOJE: {datetime.now().strftime('%d/%m/%Y')} — use-a para prazos e prescrição. "
        "Os julgados e os dispositivos do material abaixo são REAIS e vieram do acervo: "
        "prefira-os à memória e cite só os que alcançarem estes fatos. Artigo ou processo "
        "citado de memória, fora do material, é erro grave; sem precedente verificável, "
        "escreva [PESQUISAR PRECEDENTE ATUAL E APLICÁVEL SOBRE ESTE PONTO]. "
        "Qualificação (cidade, endereço, CNPJ, CPF) só com dado que esteja nos DOCUMENTOS deste caso; "
        "não copie de outra peça nem do cadastro se o documento não confirmar. "
        "Pedido de pagamento sem valor nos documentos não entra no corpo — nem com [PENDENTE], nem como pedido "
        "genérico pelo art. 322 do CPC. A lacuna vai só em `pendencias`. Um só valor de dano moral, o mesmo na "
        "fundamentação, no pedido e no valor da causa. A narrativa do assalto segue a CAT e o BO: não inverta "
        "quem abordou o autor e quem entrou na área interna."
    )
    instrucao_base = (
            CONTRATO_DE_REDACAO
            + """Você executa a SKILL DO ESCRITÓRIO para redigir a peça do caso.
Em UMA resposta, organize o material do caso e redija uma minuta completa.
Use a entrevista como ALEGAÇÃO e os documentos como prova. Não invente fatos.
Onde faltar dado de qualificação indispensável que a skill exija, omita o campo. Não escreva [PENDENTE] no corpo da peça.

PADRÃO DO ESCRITÓRIO: a ORIENTAÇÃO DO ESCRITÓRIO (skill) é a fonte de FORMATO
e manda sobre tudo — inclusive sobre a estrutura de qualquer peça de referência
do acervo que aparecer acima. Peça de referência mostra nível de profundidade
e raciocínio a igualar, nunca título, ordem de seção ou formato: nisso, quando
divergir da orientação do escritório, a orientação do escritório vence sempre.
Onde a orientação não disser nada, escolha a forma que julgar melhor para a
peça, sem inventar fato.

Devolva JSON exatamente com:
{
  "analise": {
    "resumo": "síntese jurídica",
    "cruzamento_entrevista_documentos": "confronto entre relato e provas",
    "pontos_fortes": ["..."], "lacunas": ["..."],
    "fatos_confirmados": ["..."], "fatos_so_na_entrevista": ["..."],
    "observacoes": "alertas para revisão",
    "decisoes_estrategicas": [{"decisao":"o que foi decidido", "motivo":"base documental/jurídica"}],
    "divergencias": [{"campo":"dado divergente", "fontes":"Documento NN × Documento MM", "detalhe":"valores registrados"}],
    "acoes_sugeridas": [
      {"titulo":"nome da ação adicional ou conexa", "motivo":"por que os fatos podem justificar esta peça", "pedidos":["pedido possível"], "prioridade":"principal|alternativa|avaliar"}
    ]
  },
  "secoes": [
    {"code":"<PAPEL_DA_SECAO>","label":"<título da seção como a SKILL manda; \"\" se a skill não dá título>","content":"<texto, com a marcação definida em formatacao.md>"}
    /* UMA entrada por seção que a SKILL determinar, na ordem e na quantidade que ela determinar.
       PAPEL_DA_SECAO: identificador curto em MAIÚSCULAS. Quando a seção cumprir um destes papéis,
       use exatamente o nome — os validadores automáticos as localizam por ele: HEADING, PRELIMINARY,
       FACTS, LEGAL_GROUNDS, CLAIMS, VALUE, CLOSING. Qualquer outra seção: código livre. Crie SÓ as seções que a skill manda. */
  ],
  "pendencias": ["..."]
}
Em `acoes_sugeridas`, inclua de zero a três peças DIFERENTES da minuta principal,
somente se os fatos realmente apontarem para elas. Não sugira duplicata, recurso,
ou peça sem base mínima; quando não houver outra ação cabível, devolva [].
Cada content deve conter parágrafos separados por linha em branco."""
    )
    instrucao_base += (
        "\n\n=== CONTRATO DE BLOCOS (extraído de references/estrutura_peca.md) ===\n"
        + "\n".join(
            f"- {b['ordem']}. {b['titulo']} => {b['code']}"
            for b in plano_est["contrato_secoes"]["blocos"]
        )
        + "\nUse somente esses papéis, nessa ordem, cada um UMA vez e com conteúdo próprio. PRELIMINARY é obrigatória e deve trazer a gratuidade quando houver declaração/elemento de hipossuficiência. Preserve a marcação visual exigida pela skill (# para capítulo, > para citação curta verificável, ::: para blocos centralizados). Análise, lacunas, alertas e pendências são metadados internos e nunca podem aparecer no content das seções."
    )
    instrucao_base += (
        "\n\n=== FONTE CANONICA OBRIGATORIA ===\n"
        "O PETITION_PLAN fornecido na entrada e a unica fonte para datas, valores, "
        "percentuais e fatos no corpo. Nao complete cronologia por inferencia. "
        "Em FACTS, so escreva uma data se ela estiver identificada no plano com fonte; "
        "caso contrario, omita o marco e registre a lacuna apenas em pendencias. "
        "Nao escreva valores monetarios em CLAIMS ou VALUE: o renderer os substitui "
        "pelos objetos de calculo e pelo valor da causa canonicos."
        "\n\n=== PADRAO DE RACIOCINIO FORENSE ===\n"
        "Para cada tese aproveitada, conecte fato documental especifico -> regra ou precedente verificado -> "
        "consequencia juridica -> pedido correspondente. Antecipe a defesa previsivel apenas quando os autos "
        "derem base e responda com prova ou regra aplicavel; nao crie uma controversia artificial. Diferencie "
        "o que esta provado, o que e alegacao e o que depende de pericia. Prefira uma fundamentacao precisa "
        "e aderente aos fatos a uma lista de artigos ou julgados. Toda citacao deve explicar, em linguagem "
        "propria, por que a sua razao de decidir alcanca este caso."
    )
    if estrito and prep_juridico:
        instrucao_base += _CONTRATO_JURIDICO
    instrucao = _com_skill_do_escritorio(caso_id, instrucao_base)
    _estrutura_fixa = _estrutura_fixa_no_prompt(instrucao)
    pipeline.update({
        "hardcoded_override_detected": bool(_estrutura_fixa),
        "hardcoded_structure_detected": bool(_estrutura_fixa),
        "hardcoded_structure_signals": _estrutura_fixa,
        "legacy_skill_loaded": bool((diag.get("fontes_de_instrucao") or {}).get("legacy_skill_loaded")),
        "generation_instruction_sources": diag.get("fontes_de_instrucao"),
    })
    # Sem orientação do escritório a instrução volta intocada — e a peça sai do
    # prompt genérico. Isso tem de constar da peça, não só do log.
    insumos["orientacao_do_escritorio"] = instrucao != instrucao_base
    avancar_etapa("Redigindo a petição — esta é a etapa mais demorada…", 35)
    entrada_redacao = plano_da_peticao.para_prompt(plano_est) + "\n\n" + contexto
    if estrito and prep_juridico:
        # Plano, base jurídica e regras PRIMEIRO; o corte de tamanho cai no fim do material do caso, nunca no plano.
        extras = contexto[tamanho_caso + len(precedentes) + len(legislacao) + len(padroes) + len(outline):]
        entrada_redacao, corte = juridico_orq.montar_entrada(
            "\n\n".join([prep_juridico["texto_plano"], outline, legislacao, precedentes, extras]), contexto[:tamanho_caso] + padroes)
        prep_juridico["rastro"].etapas.append({"etapa": "entrada_da_redacao", "ok": True, **corte})
    saida = _llm_json(
        instrucao,
        entrada_redacao,
        # 360s e não 240s: com o teto de saída dobrado a resposta é fisicamente
        # maior, e manter o prazo antigo trocaria "peça curta" por "o modelo não
        # respondeu" — que é pior, porque perde o trabalho inteiro.
        timeout=360.0,
    )
    avancar_etapa("Organizando as seções da minuta…", 68)
    _secoes_previas = _normalizar_secoes(saida.get("secoes") or [], plano_est["contrato_secoes"])
    _itens = diag.get("proveniencia") or []
    recuperacao_por_tese.medir_influencia(_itens, _secoes_previas)
    pipeline["proveniencia"] = [p.como_dict() for p, _ in _itens]
    pipeline["retrieval_contribuiu"] = {
        canal: sum(1 for p, _ in _itens if p.canal == canal and p.contribuiu)
        for canal in ("precedente", "legislacao", "peca")
    }
    pipeline["retrieval_executou"] = {
        canal: sum(1 for p, _ in _itens if p.canal == canal)
        for canal in ("precedente", "legislacao", "peca")
    }
    bruto_analise = saida.get("analise") or {}
    analise = {
        "resumo": str(bruto_analise.get("resumo") or "").strip(),
        "cruzamento_entrevista_documentos": str(
            bruto_analise.get("cruzamento_entrevista_documentos") or ""
        ).strip(),
        "pontos_fortes": [str(x) for x in bruto_analise.get("pontos_fortes") or []],
        "lacunas": [str(x) for x in bruto_analise.get("lacunas") or []],
        "fatos_confirmados": [
            str(x) for x in bruto_analise.get("fatos_confirmados") or []
        ],
        "fatos_so_na_entrevista": [
            str(x) for x in bruto_analise.get("fatos_so_na_entrevista") or []
        ],
        "observacoes": str(bruto_analise.get("observacoes") or "").strip(),
        "decisoes_estrategicas": [
            {"decisao": str(item.get("decisao") or "").strip(), "motivo": str(item.get("motivo") or "").strip()}
            for item in bruto_analise.get("decisoes_estrategicas") or []
            if isinstance(item, dict) and str(item.get("decisao") or "").strip()
        ],
        "divergencias": [
            {"campo": str(item.get("campo") or "").strip(), "fontes": str(item.get("fontes") or "").strip(),
             "detalhe": str(item.get("detalhe") or "").strip()}
            for item in bruto_analise.get("divergencias") or []
            if isinstance(item, dict) and str(item.get("campo") or "").strip()
        ],
        "acoes_sugeridas": [
            {
                "titulo": str(item.get("titulo") or "").strip(),
                "motivo": str(item.get("motivo") or "").strip(),
                "pedidos": [str(p).strip() for p in item.get("pedidos") or [] if str(p).strip()],
                "prioridade": str(item.get("prioridade") or "avaliar").strip().lower(),
            }
            for item in bruto_analise.get("acoes_sugeridas") or []
            if isinstance(item, dict) and str(item.get("titulo") or "").strip()
        ][:3],
    }
    secoes = _normalizar_secoes(saida.get("secoes") or [], plano_est["contrato_secoes"])
    if not any(secao["content"] for secao in secoes):
        raise ErroPeticao("O modelo não devolveu texto da petição.")
    # Antes de qualquer coisa ler a peça: o que ela afirma e os autos não sustentam
    # (documento inexistente, número sem origem, pedido sem valor, tópico contra o
    # cliente, súmula de memória). Ver `conferencia_peticao`.
    avancar_etapa("Aprofundando a peça pelo padrão do acervo…", 74)
    orientacoes_motor, motor_no_aprofundamento = _orientacoes_do_motor(analise_em_sombra) if assistido else ({}, None)
    if estrito:
        # O redator já recebeu o plano e a base jurídica. Reescrever capítulos
        # depois disso seria uma segunda decisão jurídica sem novo plano.
        aprofundamento = {"aplicado": False, "motivo": "desligado no modo strict", "por_topico": [], "textos_acervo": []}
    else:
        secoes, aprofundamento = _tentar_etapa(
            "aprofundamento",
            lambda: _aprofundar_pela_referencia(
                caso_id, secoes, brief, referencias_acervo, contexto=contexto, plano=plano, categoria=nome_categoria,
                assuntos=peticao_skill_arquivos.assuntos_relacionados(nome_categoria, codigo_categoria, _TEXTO_DO_CASO.get()),
                plano_est=plano_est, orientacoes_motor=orientacoes_motor,
            ),
            (secoes, {"por_topico": [], "textos_acervo": []}),
            diag,
        )
    if motor_no_aprofundamento is not None:
        aprofundamento["motor_juridico"] = motor_no_aprofundamento
    textos_acervo = [padroes, *(aprofundamento.pop("textos_acervo", []) or [])]
    # A seção "Dos pedidos" é RENDERIZADA do plano (fonte única), não pedida de novo ao modelo.
    avancar_etapa("Consolidando os pedidos a partir do plano…", 80)
    if estrito and prep_juridico:
        secoes, rel_pedidos = _renderizar_juridico(secoes, prep_juridico, falhas_juridicas, diag)
    else:
        secoes, rel_pedidos = _tentar_etapa(
            "pedidos do plano",
            lambda: _pedidos_do_plano_na_secao(caso_id, secoes, plano_est),
            (secoes, {"aplicado": False, "motivo": "etapa falhou"}),
            diag,
        )
    aprofundamento["pedidos_do_plano"] = rel_pedidos
    if plano_finalizado is not None:
        juridico_imutabilidade.verificar(plano_finalizado, plano_est, etapa="renderização dos pedidos")
    pipeline["aprofundamento"] = {k: v for k, v in aprofundamento.items() if k != "por_topico"}
    pipeline["proveniencia_por_secao"] = aprofundamento.get("por_topico")
    avancar_etapa("Conferindo a peça contra os autos…", 85)
    # O material citável NÃO inclui o acervo: peça de outro cliente não é fonte de fato do caso.
    material_sem_acervo = texto_do_caso + precedentes + legislacao + outline
    secoes, violacoes, conferencia = _tentar_etapa(
        "conferência contra os autos",
        lambda: _conferir_contra_os_autos(
            caso_id, secoes, texto_entrevista=texto_entrevista, material=material_sem_acervo, corrigir=not estrito
        ),
        (secoes, [], {"erro": "etapa falhou"}),
        diag,
    )
    # Segunda leitura, agora contra o CASE BRIEF e a SKILL (não contra o material
    # bruto — isso a conferência acima já fez): omissão de fato relevante, seção
    # rasa, regra da skill não seguida. Pode reescrever seções; por isso vem
    # antes da cobertura, que precisa medir o texto FINAL.
    if estrito:
        achados_validacao = []
    else:
        secoes, achados_validacao = _validar_contra_skill_e_brief(caso_id, secoes, brief)
    # PETITION LINTER: qualificação, pedidos únicos, isolamento entre teses e nada do acervo como fato,
    # com correção automática controlada e nova validação — ANTES de a peça ir para o DOCX.
    avancar_etapa("Validando a peça (linter)…", 91)
    secoes, achados_linter, rel_linter = _tentar_etapa(
        "linter",
        lambda: _lintar_e_corrigir(
            caso_id, secoes, plano_est,
            # fonte PERMITIDA: caso + julgados/lei recuperados + skill (precedentes vinculantes); o acervo fica de fora
            # com a camada jurídica ativa a skill deixa de ser fonte citável: norma vem da base verificada
            texto_do_caso=material_sem_acervo + ("" if estrito else peticao_skill_arquivos.carregar(nome_categoria, codigo_categoria, _TEXTO_DO_CASO.get())),
            textos_do_acervo=textos_acervo, material=material_sem_acervo,
            permitir_mutacoes=not estrito,
        ),
        (secoes, [], {"erro": "etapa falhou"}),
        diag,
    )
    # o auditor já inclui a conferência contra os autos: os achados finais SUBSTITUEM os da 1ª conferência
    violacoes = list(achados_linter)
    pipeline["linter"] = rel_linter
    pipeline["auditor_final"] = rel_linter
    pipeline["plano_estruturado"] = plano_est
    pipeline["case_facts"] = plano_est.get("case_facts")
    if plano_finalizado is not None:
        juridico_imutabilidade.verificar(plano_finalizado, plano_est, etapa="auditorias pré-documento")
    # Cobertura: quais fatos e eventos que a análise dos documentos já validou
    # (o mesmo material que virou `case_brief`, acima) efetivamente aparecem no
    # texto final. Não bloqueia nem corrige nada — só torna visível quando a
    # peça deixou de fora algo que a leitura dos documentos tinha encontrado,
    # em vez de a omissão passar batido sem ninguém notar.
    # ===== FINAL_DOCUMENT_VALIDATOR — ÚLTIMA etapa que pode mudar o texto. Roda sobre a representação que o DOCX imprime.
    avancar_etapa("Validação final do documento…", 96)
    if estrito:
        plano_est["_juridico_estrito"] = True
        if prep_juridico:
            # As revisões por LLM acima podem ter tocado pedidos, valor ou data: o código os renderiza de novo.
            secoes, pipeline["renderizacao_final"] = _renderizar_juridico(secoes, prep_juridico, falhas_juridicas, diag)
    secoes, rel_final, achados_finais = _tentar_etapa(
        "validação final",
        lambda: _validar_documento_final(caso_id, secoes, plano_est, texto_do_caso, permitir_mutacoes=not estrito),
        (secoes, {"pendencias_humanas": [], "rodadas": []}, []),
        diag,
    )
    violacoes = _mesclar_achados_finais(violacoes, achados_finais, secoes)
    if plano_finalizado is not None:
        juridico_imutabilidade.verificar(plano_finalizado, plano_est, etapa="validação final")
    pipeline["documento_final"] = rel_final
    hash_validado = documento_final.impressao_hash(secoes)
    cobertura = _tentar_etapa(
        "cobertura", lambda: case_brief.cobertura(brief, secoes) if brief else None, None, diag,
    )
    jurimetria, _ = _analisar_jurimetria_da_minuta(secoes, texto_para_uf=contexto)
    pendencias = [str(p) for p in saida.get("pendencias") or [] if str(p).strip()]
    pendencias += _pendencias_do_auditor(rel_linter)
    pendencias += [p for p in _pendencias_criticas(violacoes) if p not in pendencias]
    atualizacao = _resultado_da_atualizacao(atualizacao_futura)
    if atualizacao:
        pendencias += [p for p in atualizacao.get("pendencias") or [] if p not in pendencias]
    auditoria_juridica: dict[str, Any] | None = None
    if sombra:
        pipeline["juridico"] = _juridico_em_sombra(
            analise_em_sombra, secoes, plano_est, pendencias, texto_do_caso, diag, uf_jurisprudencia)
    elif assistido:
        pipeline["juridico"] = _juridico_em_sombra(
            analise_em_sombra, secoes, plano_est, pendencias, texto_do_caso, diag, uf_jurisprudencia, modo=juridico.ASSISTIDO)
        pendencias += [p for p in _pendencias_do_motor(pipeline["juridico"]) if p not in pendencias]
    if estrito:
        if prep_juridico:
            avancar_etapa("Auditoria jurídica (citações, fatos, cálculos, consistência)…", 97)
            pendencias += [p for p in prep_juridico["pendencias"] if p not in pendencias]
            ausentes = documento_final.pedidos_obrigatorios_ausentes(
                secoes, peticao_skill_arquivos.validacoes_da_skill()["parametros"])
            auditoria_juridica = _etapa_juridica(
                "auditoria",
                lambda: juridico_orq.auditar(secoes, prep_juridico, pendencias=pendencias, texto_das_fontes=texto_do_caso,
                                             carregar_dispositivos=juridico_repo.carregar_dispositivos,
                                             pedidos_obrigatorios_ausentes=ausentes, llm=_verificador_juridico()),
                falhas_juridicas, diag)
            pendencias += [p for p in juridico_orq.pendencias_do_motor(prep_juridico) if p not in pendencias]
            pipeline["juridico"] = _etapa_juridica(
                "rastro", lambda: juridico_orq.trace(prep_juridico, auditoria_juridica, modo=juridico.STRICT, falhas=falhas_juridicas),
                falhas_juridicas, diag)
        pipeline["juridico"] = pipeline.get("juridico") or juridico_orq.trace_de_falha(juridico.STRICT, falhas_juridicas)
        if falhas_juridicas or auditoria_juridica is None:
            raise ErroPeticao(
                "Modo strict: a verificação jurídica da peça não concluiu — " + "; ".join(falhas_juridicas or ["auditoria não executou"])
                + ". A peça não foi entregue.")
    if estrito and diag["fallbacks"]:
        raise ErroPeticao(
            "Modo strict: uma etapa posterior acionou fallback — " + "; ".join(diag["fallbacks"])
            + ". Nenhuma peça degradada foi entregue."
        )
    achados_criticos = peticao_aprendizado.avaliar_documento(secoes)
    peticao_aprendizado.registrar_avaliacao(
        generation_id=generation_id, caso_id=caso_id, tipo="post_generation", achados=achados_criticos
    )
    for nome in ("legal_critic", "style_critic", "consistency_check", "document_generation"):
        peticao_aprendizado.registrar_execucao(
            generation_id=generation_id, caso_id=caso_id, skill_name=nome,
            status="DONE", itens_recuperados=achados_criticos if nome != "document_generation" else [],
            confidence=1.0 if not achados_criticos else .72,
        )
    agora = _agora()
    anterior = carregar(caso_id) or {}
    versao = int(anterior.get("version") or 0) + 1
    # A versão que está sendo substituída vai para o histórico ANTES de ser
    # sobrescrita — `peticoes_locais` guarda só a atual (chave é o caso).
    #
    # `revisar_com_prompt` já fazia isto e gerar de novo não: o advogado clicava
    # "Gerar de novo" (a tela até avisa que "cria uma nova versão") e a minuta
    # anterior — com as correções que ele já tinha feito à mão — desaparecia sem
    # deixar cópia. O painel de rastreabilidade mostrava um salto de versão sem
    # nada atrás dele. Vem antes de `_salvar` de propósito: se o histórico falhar,
    # a petição anterior continua inteira no lugar e é só tentar de novo.
    if anterior:
        armazenamento.registrar_versao_peticao(caso_id, anterior)
    avancar_etapa("Gravando a minuta no dossiê…", 99)
    dados = {
        "id": ID_LOCAL,
        "generation_id": generation_id,
        "document_type": "INITIAL_PETITION",
        "status": "IN_REVIEW",
        "version": versao,
        "title": "Petição inicial",
        "created_at": anterior.get("created_at") or agora,
        "updated_at": agora,
        # Gerar de novo não desfaz o protocolo já feito no tribunal.
        "protocolo": anterior.get("protocolo") or None,
        "analise": analise,
        # Produto interno, deliberadamente separado de `sections`: a peça que
        # vai ao juízo nunca recebe lacunas, estratégia ou divergências brutas.
        "relatorio_advogado": {
            "pendencias": pendencias or analise.get("lacunas") or [],
            "decisoes_estrategicas": analise.get("decisoes_estrategicas") or [],
            "divergencias": analise.get("divergencias") or [],
        },
        "jurimetria": jurimetria,
        "sections": secoes,
        "readiness": {
            # Uma minuta com qualquer violação factual, cálculo sem origem ou
            # total divergente jamais é elegível a protocolo, inclusive no fluxo
            # legado. Antes, essas falhas ficavam só em `review.findings` e a
            # prontidão podia permanecer verdadeira.
            "ready": not (
                any(v.bloqueia for v in violacoes)
                or auditoria_estrutural.pendencias(secoes)
                or pipeline.get("documento_final", {}).get("pendencias_humanas")
            ),
            "blocking_issues": [
                *(f"[{v.codigo}] {v.motivo}"[:200] for v in violacoes if v.bloqueia),
                *(f"[PENDENTE] no texto ({c}): {m}"[:200] for c, m in auditoria_estrutural.pendencias(secoes)),
                *((pipeline.get("documento_final") or {}).get("pendencias_humanas") or []),
            ],
            "warnings": [
                *_avisos_de_pipeline(pipeline),
                *_avisos_de_insumo(insumos),
                *(analise.get("lacunas") or []),
                *_avisos_de_cobertura(cobertura),
                *_avisos_de_validacao(achados_validacao),
                *_avisos_de_atualizacao(atualizacao),
            ],
            "pendencias": pendencias or analise.get("fatos_so_na_entrevista") or [],
            "completo": not pendencias and not analise.get("lacunas"),
        },
        "review": {"summary": analise.get("observacoes", "")},
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        # Trace é explicabilidade operacional: fontes/regras/etapas. Não contém
        # cadeia de pensamento privada do modelo nem texto sensível do caso.
        "trace": {
            "generation_id": generation_id,
            "learned_rules": [
                {"id": r.get("id"), "tipo": r.get("tipo"), "confidence": r.get("confidence"),
                 "observacoes": r.get("observacoes")}
                for r in regras_aplicadas
            ],
            "skills": ["learned_preferences_retrieval", "outline_planning", "legal_critic",
                       "style_critic", "consistency_check", "skill_brief_validation",
                       "document_generation"],
            "evaluations": achados_criticos,
            "insumos": insumos,
            "conferencia": conferencia,
            "outline": plano,
            "referencias_do_acervo": referencias_acervo,
            "pipeline": pipeline,
            "case_brief": brief,
            "cobertura": cobertura,
            "validacao_skill_brief": achados_validacao,
            "atualizacao_juridica": {**(atualizacao or {"executada": False, "motivo": "desligada ou sem teses"}),
                                     "acervo_verificado_no_prompt": bool(bloco_atualizacao)},
        },
    }
    if atualizacao and atualizacao.get("executada"):
        dados["trace"]["skills"].append("legal_update_research")
    _aplicar_conferencia(dados, secoes, violacoes)
    if estrito:
        dados["trace"]["skills"] += ["fact_matrix", "issue_spotting", "legal_research", "deterministic_calculation",
                                     "citation_gate", "legal_audit", "fact_audit", "calculation_audit", "consistency_audit"]
        _aplicar_veredito_juridico(dados, auditoria_juridica, falhas_juridicas)
    elif sombra:
        dados["trace"]["skills"].append("legal_pipeline_shadow")
    # Nada pode ter mudado o conteúdo depois do validador final (o que foi validado é o que será impresso).
    if documento_final.impressao_hash(dados["sections"]) != hash_validado:
        raise ErroPeticao("O documento mudou depois da validação final — geração interrompida para não entregar peça não validada.")
    _salvar(caso_id, dados)
    return dados


#: Integridade quando a camada jurídica está ativa: genérica, sem caso nem tese embutidos.
_INTEGRIDADE_JURIDICA = (
    "\n\n=== INTEGRIDADE DOS DADOS ===\n"
    "DATA DE HOJE: {hoje} — é a data de referência da vigência das normas e precedentes. "
    "Teses, pedidos e valores são os do PETITION_PLAN; tese marcada para o relatório do advogado não vai ao corpo. "
    "Cite SOMENTE autoridades da BASE JURÍDICA VERIFICADA, pelo que ela diz; sem autoridade, escreva "
    "[REQUIRES_LEGAL_RESEARCH: <o que pesquisar>] — nunca número de artigo, súmula, OJ, tema ou processo de memória, "
    "nem fundamento copiado da skill ou de peça antiga. Fato «alegado» se narra como alegação; «inferido» não se afirma; "
    "fato em contradição não se usa. Qualificação só com dado da matriz de fatos. A narrativa segue a ordem e os "
    "agentes registrados nos documentos oficiais do caso."
)

_CONTRATO_JURIDICO = (
    "\n\n=== CAMADA JURÍDICA ===\n"
    "A escolha das teses JÁ FOI FEITA (PETITION_PLAN): desenvolva todas as teses do plano, cada uma com fatos da matriz, "
    "prova e autoridade; não acrescente nem retire tese. A única marcação permitida no corpo é "
    "[REQUIRES_LEGAL_RESEARCH: …], onde o plano não trouxer autoridade. Use exatamente os valores e os DADOS CANÔNICOS do plano. "
    "NÃO redija a lista de pedidos nem o valor da causa: o sistema os monta a partir do plano — em CLAIMS escreva só a frase "
    "de abertura; em VALUE, nada. Não escreva data no fechamento: o sistema insere a data da petição. Tabela só pelo marcador "
    "[[TABELA:<categoria>]] que o plano indicar; nunca digite tabela."
)


def _analise_juridica(caso_id: str, plano_est: dict[str, Any], contexto: str, texto_entrevista: str,
                      data_da_peticao: date | None = None) -> dict[str, Any]:
    fontes = [{"tipo": "documento", "nome": d["arquivo"], "texto": d["texto"]} for d in documentos_logicos(caso_id)[1]]
    fontes.append({"tipo": "entrevista", "nome": "entrevista", "texto": texto_entrevista or ""})
    modelo = juridico.modelo_raciocinio() or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    return juridico_orq.analisar(
        # A matriz de fontes vai separada e completa; limitar o resumo evita que
        # uma única chamada de issue-spotting com >120 mil caracteres expire antes
        # de qualquer auditoria rodar.
        plano_est=plano_est, contexto_caso=contexto[:80_000], fontes=fontes, llm=_llm_raciocinio(300.0),
        textos_skill=juridico_teses.textos_da_skill_ativa(), modelo=modelo, data_referencia=data_da_peticao,
        llm_contrateses=_llm_raciocinio(180.0) if _ligado("PETICAO_MOTOR_CONTRATESES_LLM") else None, modelo_contrateses=modelo,
    )


def _ligado(variavel: str, padrao: str = "1") -> bool:
    return os.getenv(variavel, padrao).strip().lower() in ("1", "true", "sim", "on")


def _llm_raciocinio(timeout: float) -> Any:
    """LLM do raciocínio jurídico (issue spotting, contrateses, proposições): `PETICAO_MODELO_RACIOCINIO` ou o da redação."""
    modelo = juridico.modelo_raciocinio()
    if not modelo:
        return lambda instrucao, entrada: _llm_json(instrucao, entrada, timeout=timeout)
    return lambda instrucao, entrada: _llm_json(instrucao, entrada, timeout=timeout, modelo=modelo)


def _fundamentacao_juridica(prep: dict[str, Any], diag: dict[str, Any], uf: str, falhas: list[str], *,
                            llm_proposicoes: Any = None) -> dict[str, Any]:
    base, erro = juridico_repo.carregar_autoridades()
    if erro:
        falhas.append(f"autoridades: {erro}")
    elif not base:
        falhas.append("autoridades: base verificada vazia (autoridades_juridicas sem registros)")
    trechos = diag.get("_trechos") or {}
    return juridico_orq.fundamentar(
        prep, autoridades_base=base, alertas_base=[erro] if erro else [],
        trechos_legislacao=trechos.get("legislacao") or [], trechos_precedentes=trechos.get("precedentes") or [],
        trt_competente=str((tribunais.UF_PARA_TRT.get(uf) or [""])[0]),
        llm_proposicoes=llm_proposicoes, modelo_proposicoes=juridico.modelo_raciocinio() or os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    )


def _verificador_juridico() -> Any:
    """LLM dos gates (sustentação das citações e 2ª camada semântica): JSON estrito, prazo curto."""
    return lambda instrucao, entrada: _llm_json(instrucao, entrada, timeout=180.0)


def _renderizar_juridico(secoes: list[dict[str, Any]], prep: dict[str, Any], falhas: list[str],
                         diag: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Strict: pedidos, valor da causa, data do fechamento e tabelas saem do código (`juridico.render`)."""
    resultado = _etapa_juridica("renderização por código", lambda: juridico_render.renderizar(secoes, prep), falhas, diag)
    if resultado is None:
        return secoes, {"aplicado": False, "motivo": "renderização falhou"}
    novas, rel = resultado
    return novas, {"aplicado": True, **rel}


def _etapa_juridica(nome: str, funcao: Any, falhas: list[str], diag: dict[str, Any]) -> Any:
    """Etapa da camada jurídica em strict: a falha é registrada e impede a peça de ser pronta (sem queda silenciosa)."""
    try:
        return funcao()
    except Exception as erro:  # noqa: BLE001 - registrada em `falhas` e no veredito
        log.exception("petição local: camada jurídica — etapa '%s' falhou", nome)
        falhas.append(f"{nome}: {_erro_curto(erro)}")
        diag.setdefault("fallbacks", []).append(f"camada jurídica — {nome}: {_erro_curto(erro)}")
        return None


_EXECUTOR_SOMBRA = ThreadPoolExecutor(max_workers=2, thread_name_prefix="juridico-sombra")
#: Quanto a peça legada, já pronta, pode esperar o modo shadow terminar.
ESPERA_MAXIMA_SOMBRA_S = float(os.getenv("PETICAO_JURIDICO_SOMBRA_ESPERA_S", "45"))
#: No assistido o motor só acrescenta pendências: a peça pronta não fica parada esperando por ele.
ESPERA_ASSISTIDO_S = float(os.getenv("PETICAO_ASSISTIDO_ESPERA_S", "10"))


def _em_sombra(funcao: Any) -> Any:
    """Roda a análise da camada em paralelo à geração legada, sem escrever no diagnóstico da peça entregue."""
    contexto = contextvars.copy_context()

    def rodar() -> Any:
        _DIAG.set(None)
        return funcao()

    try:
        return _EXECUTOR_SOMBRA.submit(contexto.run, rodar)
    except Exception:  # noqa: BLE001 - shadow nunca afeta a geração
        log.exception("petição local: modo shadow não iniciou")
        return None


def _juridico_em_sombra(
    futuro: Any, secoes: list[dict[str, Any]], plano_legado: dict[str, Any], pendencias_legado: list[str],
    texto_do_caso: str, diag: dict[str, Any], uf: str, *, modo: str = juridico.SHADOW,
) -> dict[str, Any]:
    """Modo shadow (e assistido): audita a peça legada com a camada e grava as diferenças. Nunca levanta exceção.

    No assistido a verificação por LLM no fim fica desligada por padrão (`PETICAO_ASSISTIDO_VERIFICACAO_LLM`): a
    auditoria do motor é por código e a peça não espera chamadas extras."""
    falhas: list[str] = []
    prep = None
    if futuro is None:
        falhas.append("análise: não iniciou")
    else:
        espera = ESPERA_ASSISTIDO_S if modo == juridico.ASSISTIDO else ESPERA_MAXIMA_SOMBRA_S
        try:
            prep = futuro.result(timeout=max(1.0, min(espera, ORCAMENTO_SUAVE_S - _tempo_decorrido() - 30)))
        except TimeoutError:
            falhas.append("análise: não terminou a tempo; a peça legada não esperou")
        except Exception as erro:  # noqa: BLE001
            falhas.append(f"análise: {_erro_curto(erro)}")
    if prep is None:
        return juridico_orq.trace_de_falha(modo, falhas)
    try:
        variavel, padrao = (("PETICAO_ASSISTIDO_VERIFICACAO_LLM", "0") if modo == juridico.ASSISTIDO
                            else ("PETICAO_SOMBRA_VERIFICACAO_LLM", "1"))
        com_llm = _ligado(variavel, padrao) and ORCAMENTO_SUAVE_S - _tempo_decorrido() > 150
        prep = _fundamentacao_juridica(prep, diag, uf, falhas, llm_proposicoes=_llm_raciocinio(120.0) if com_llm else None)
        ausentes = documento_final.pedidos_obrigatorios_ausentes(secoes, peticao_skill_arquivos.validacoes_da_skill()["parametros"])
        if not com_llm:
            falhas.append("verificação de sustentação das citações e 2ª camada semântica não rodaram (desligadas ou sem tempo)")
        auditoria = juridico_orq.auditar(secoes, prep, pendencias=list(pendencias_legado), texto_das_fontes=texto_do_caso,
                                         carregar_dispositivos=juridico_repo.carregar_dispositivos, pedidos_obrigatorios_ausentes=ausentes,
                                         llm=_verificador_juridico() if com_llm else None)
        comparacao = juridico_orq.comparar_com_legado(secoes, prep, auditoria, plano_legado=plano_legado, pendencias_legado=pendencias_legado)
        return juridico_orq.trace(prep, auditoria, modo=modo, falhas=falhas, comparacao=comparacao)
    except Exception as erro:  # noqa: BLE001 - shadow nunca afeta a geração
        log.exception("petição local: modo %s falhou", modo)
        falhas.append(f"auditoria/comparação: {_erro_curto(erro)}")
        return juridico_orq.trace_de_falha(modo, falhas)


#: Quanto o aprofundamento (modo assistido) espera a análise do motor antes de seguir sem a orientação dele.
ESPERA_MOTOR_NO_APROFUNDAMENTO_S = float(os.getenv("PETICAO_MOTOR_ESPERA_S", "5"))
#: Autoridade "inexistente" contra uma base verificada vazia não é erro da peça: não vira pendência CRÍTICA.
_CRITICOS_QUE_DEPENDEM_DA_BASE = {"AUTORIDADE_INEXISTENTE", "DISPOSITIVO_INEXISTENTE", "AUTORIDADE_POSTERIOR_A_PETICAO"}


def _orientacoes_do_motor(futuro: Any) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    """Orientação por tese para o aprofundamento, se a análise em segundo plano já terminou. Nunca levanta exceção."""
    if futuro is None:
        return {}, {"aplicado": False, "motivo": "análise não iniciou"}
    try:
        prep = futuro.result(timeout=ESPERA_MOTOR_NO_APROFUNDAMENTO_S)
        rac = (prep or {}).get("raciocinio")
        orient = juridico_raciocinio.orientacoes(rac)
    except TimeoutError:
        return {}, {"aplicado": False, "motivo": "análise do motor ainda não terminou"}
    except Exception as erro:  # noqa: BLE001 - sem orientação o aprofundamento segue como antes
        return {}, {"aplicado": False, "motivo": f"análise falhou: {_erro_curto(erro)}"}
    return orient, {"aplicado": bool(orient), "teses_orientadas": len(orient),
                    "capitulos_vulneraveis": len((rac or {}).get("capitulos_vulneraveis") or [])}


def _pendencias_do_motor(trace: dict[str, Any] | None, *, limite_criticos: int = 8) -> list[str]:
    """Lacunas de prova, defesas sem resposta/prova e alertas de score + os achados CRÍTICOS da auditoria."""
    if not trace:
        return []
    saida = list(trace.get("pendencias_do_motor") or [])
    sem_base = any(str(f).startswith("autoridades:") for f in trace.get("falhas") or [])
    criticos = [a for a in ((trace.get("auditoria") or {}).get("achados") or [])
                if juridico_auditores.nivel(a) == juridico_auditores.CRITICAL
                and not (sem_base and a.get("codigo") in _CRITICOS_QUE_DEPENDEM_DA_BASE)]
    saida += [f"CRÍTICO (auditoria jurídica) [{a['codigo']}] {a.get('detalhe') or a.get('trecho') or ''}"[:260]
              for a in criticos[:limite_criticos]]
    return list(dict.fromkeys(saida))


_EXECUTOR_ATUALIZACAO = ThreadPoolExecutor(max_workers=2, thread_name_prefix="atualizacao-juridica")
#: Quanto a peça, já redigida, espera a pesquisa de atualização jurídica (ela roda em paralelo à redação).
ESPERA_MAXIMA_ATUALIZACAO_S = float(os.getenv("PETICAO_ATUALIZACAO_ESPERA_S", "60"))


def _iniciar_atualizacao_juridica(plano_est: dict[str, Any], plano: dict[str, Any] | None, data_da_peticao: date) -> tuple[Any, str]:
    """O Acervo verificado vai ao prompt agora; a pesquisa em fontes oficiais roda em paralelo e só gera pendência e alerta."""
    if not juridico_atualizacao.ativa():
        return None, ""
    teses = juridico_atualizacao.teses_do_plano(plano_est, plano)
    if not teses:
        return None, ""
    registro, bloco = None, ""
    try:
        base, _ = juridico_repo.carregar_autoridades()
        if base:
            registro = juridico_aut.Registro(base)
            bloco = juridico_atualizacao.bloco_verificado(teses, registro, data_da_peticao)
    except Exception as erro:  # noqa: BLE001 - sem Acervo a redação segue como antes
        log.warning("petição local: Acervo verificado indisponível para a atualização jurídica: %s", _erro_curto(erro))

    def rodar() -> dict[str, Any]:
        _DIAG.set(None)
        resultado = juridico_atualizacao.pesquisar(teses, data_da_peticao, registro=registro)
        if any(c["situacao"] != juridico_atualizacao.JA_VERIFICADA for c in resultado["candidatos"]):
            try:
                from .acervo import armazenamento as acervo_armazenamento
                resultado["alertas_gravados"] = juridico_atualizacao.registrar_alertas(
                    resultado["candidatos"], acervo_armazenamento.padrao(), agora=acervo_armazenamento.agora_utc())
            except Exception as erro:  # noqa: BLE001
                log.warning("petição local: alertas da atualização jurídica não gravados: %s", _erro_curto(erro))
        return resultado

    try:
        return _EXECUTOR_ATUALIZACAO.submit(contextvars.copy_context().run, rodar), bloco
    except Exception:  # noqa: BLE001 - a pesquisa nunca impede a peça
        log.exception("petição local: atualização jurídica não iniciou")
        return None, bloco


def _resultado_da_atualizacao(futuro: Any) -> dict[str, Any] | None:
    if futuro is None:
        return None
    try:
        return futuro.result(timeout=max(1.0, min(ESPERA_MAXIMA_ATUALIZACAO_S, ORCAMENTO_SUAVE_S - _tempo_decorrido() - 30)))
    except Exception as erro:  # noqa: BLE001 - inclui TimeoutError
        return {"executada": False, "motivo": f"não concluiu a tempo ou falhou: {_erro_curto(erro)}", "candidatos": [], "pendencias": []}


def _mesclar_achados_finais(anteriores: list[Any], finais: list[Any], secoes: list[dict[str, Any]]) -> list[Any]:
    """Achados do auditor (linter) + os da validação final, sem perder bloqueante que a validação final não reavaliou.

    O bloqueante do auditor que a validação final não repetiu e cujo trecho ainda está na peça segue em
    `review.findings` como alerta (a validação final é quem decide a retenção); o que já saiu do texto, não.
    """
    vistos = {(v.codigo, v.secao) for v in finais}
    corpo = " ".join(" ".join(str(s.get("content") or "").split()) for s in secoes)
    mantidos = []
    for v in anteriores:
        if not v.bloqueia:
            mantidos.append(v)
            continue
        nucleo = " ".join(str(v.trecho or "").strip("… ").split())[:80]
        if (v.codigo, v.secao) in vistos or (nucleo and nucleo not in corpo):
            continue
        mantidos.append(conferencia_peticao.Violacao(
            v.codigo, v.secao, v.trecho, "Apontado pelo auditor e não reavaliado na validação final — confira. " + v.motivo,
            v.correcao, bloqueia=False, citacao=v.citacao))
    return [*mantidos, *finais]


def _pendencias_criticas(violacoes: list[Any]) -> list[str]:
    """Achado de nível CRITICAL no legado vira pendência destacada (o legado não retém a peça por ele)."""
    saida = []
    for v in violacoes:
        if juridico_auditores.nivel_de(v.codigo, "bloqueia" if v.bloqueia else "alerta") == juridico_auditores.CRITICAL:
            item = f"CRÍTICO [{v.codigo}] {v.motivo}"[:300]
            if item not in saida:
                saida.append(item)
    return saida


def _pendencias_do_auditor(relatorio: dict[str, Any] | None) -> list[str]:
    retirados = (relatorio or {}).get("pedidos_retirados") or []
    return [f"Pedido retirado: «{r}» é verba rescisória e os documentos indicam o contrato ativo, sem rescisão indireta pedida. "
            "Se o contrato terminou ou a estratégia for a rescisão indireta, informe e gere de novo." for r in retirados]


def _avisos_de_atualizacao(atualizacao: dict[str, Any] | None) -> list[str]:
    if not atualizacao or atualizacao.get("executada"):
        return []
    return [f"Atualização jurídica por tese não foi pesquisada nesta geração ({atualizacao.get('motivo') or 'sem motivo registrado'}); "
            "confira julgados e leis recentes das teses antes de protocolar."]


def _aplicar_veredito_juridico(dados: dict[str, Any], auditoria: dict[str, Any] | None, falhas: list[str] | None = None) -> None:
    """Strict: a peça só é PRONTA se nenhuma etapa da camada falhou e os quatro auditores passaram."""
    prontidao = dados.setdefault("readiness", {})
    if falhas:
        prontidao["ready"] = False
        prontidao.setdefault("blocking_issues", []).extend(
            f"Camada jurídica falhou — {f}. A peça não passou pela verificação jurídica completa."[:260] for f in falhas)
    if not auditoria:
        prontidao["ready"] = False
        prontidao.setdefault("blocking_issues", []).append("Auditoria jurídica não executou — revisão humana obrigatória.")
        return
    criticos = juridico_auditores.criticos(auditoria["achados"])
    bloqueios = criticos + [a for a in auditoria["achados"] if a["severidade"] == "bloqueia" and a not in criticos]
    prontidao["ready"] = bool(prontidao.get("ready")) and auditoria["veredito"]["pronta"] and not criticos
    prontidao["critico"] = bool(criticos)
    prontidao.setdefault("blocking_issues", []).extend(
        f"{'CRÍTICO ' if a in criticos else ''}[{a['auditor']}] {a['codigo']}: {a['trecho'] or a['detalhe']}"[:220] for a in bloqueios[:40])
    prontidao.setdefault("warnings", []).extend(
        f"[{a['auditor']}] {a['codigo']}: {a['trecho'] or a['detalhe']}"[:220] for a in auditoria["achados"] if a["severidade"] != "bloqueia")
    prontidao["auditoria_juridica"] = auditoria["veredito"]
    # READY só quando a peça inteira (estrutura + todos os gates) passou; qualquer bloqueio → BLOCKED.
    prontidao["status"] = "READY" if prontidao["ready"] else "BLOCKED"
    prontidao["achados_juridicos"] = [{"gate": a["auditor"], "codigo": a["codigo"], "severidade": a["severidade"],
                                       "nivel": juridico_auditores.nivel(a), "secao": a["secao"],
                                       "trecho": a["trecho"], "detalhe": a["detalhe"]} for a in auditoria["achados"]]


def _avisos_de_pipeline(pipeline: dict[str, Any]) -> list[str]:
    """Cada fallback da geração, com o MOTIVO — nunca um aviso genérico."""
    return [f"Geração com fallback: {f}" for f in pipeline.get("fallbacks") or []]


def _avisos_de_insumo(insumos: dict[str, bool]) -> list[str]:
    """O que faltou na geração, em frase — aparece em «O que faltava quando a peça foi gerada»."""
    nomes = {
        "orientacao_do_escritorio": "a orientação do escritório (skill e regras aprendidas)",
        "pecas_modelo": "as peças-modelo do acervo do escritório",
        "precedentes": "os julgados do acervo",
        "legislacao": "o texto de lei do acervo",
    }
    faltou = [nomes[chave] for chave, presente in insumos.items() if not presente and chave in nomes]
    if not faltou:
        return []
    return [
        "Gerada SEM " + ", ".join(faltou) + " — o acervo não respondeu. A peça saiu do modelo"
        " genérico; gere de novo quando o acervo voltar."
    ]


def _avisos_de_cobertura(cobertura: dict[str, Any] | None) -> list[str]:
    """Fato ou evento que a leitura dos documentos confirmou e a peça não usou.

    Não é erro — parte do que a análise encontra é mesmo irrelevante para a
    petição — mas é o tipo de omissão que precisa ser DELIBERADA, não
    acidental. Um limiar (3+) evita alarme em toda geração: um ou dois pontos
    de fora é normal; muitos de fora é sinal de que a peça não aproveitou o
    que já tinha sido apurado.
    """
    if not cobertura:
        return []
    fora = len(cobertura.get("fatos_nao_usados") or []) + len(cobertura.get("eventos_nao_usados") or [])
    if fora < 3:
        return []
    return [
        f"{fora} ponto(s) que a análise dos documentos confirmou não aparecem claramente no "
        "texto da peça (ver `trace.cobertura`) — confira se foram considerados de propósito."
    ]


def _avisos_de_validacao(achados: list[dict[str, Any]]) -> list[str]:
    """O que a segunda leitura (peça × case brief × skill) encontrou.

    Uma correção automática já foi tentada (`_validar_contra_skill_e_brief`), mas
    não há uma TERCEIRA chamada para confirmar que ela resolveu cada item —
    custaria mais uma volta ao modelo por geração, para conferir algo que o
    advogado vai ler de qualquer forma. O aviso existe para dizer "olhe aqui",
    não para garantir que já está corrigido.
    """
    if not achados:
        return []
    tipos = ", ".join(sorted({str(a.get("tipo") or "problema") for a in achados}))
    return [
        f"A revisão automática contra o case brief e a skill encontrou {len(achados)} "
        f"ponto(s) ({tipos}) e tentou corrigi-los — confira `trace.validacao_skill_brief` "
        "e revise antes de protocolar."
    ]


#: Quantas peças anexas um caso pode ter. Três é o teto do que a análise sugere
#: (`acoes_sugeridas`), e é também o limite do que um advogado revisa de uma vez —
#: peça que ninguém lê é token gasto e risco de ir a protocolo sem conferência.
MAX_ANEXAS_POR_CASO = 3


def id_da_anexa(caso_id: str, titulo: str) -> str:
    """Identificador estável da peça a partir do título.

    Determinístico de propósito: mandar redigir "Ação de danos morais" duas vezes
    substitui a peça em vez de criar uma segunda igual. O caso entra no id porque
    o mesmo título aparece em casos diferentes.
    """
    limpo = re.sub(r"[^a-z0-9]+", "-", _sem_acento(titulo).lower()).strip("-")
    return f"{caso_id}:{limpo[:60] or 'peca'}"


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", str(texto or "")) if unicodedata.category(c) != "Mn"
    )


def listar_anexas(caso_id: str) -> list[dict[str, Any]]:
    """As outras peças já redigidas deste caso, como a tela as mostra."""
    saida = []
    for linha in armazenamento.listar_peticoes_anexas(caso_id):
        dados = linha.get("dados") or {}
        saida.append(
            {
                "id": linha["id"],
                "titulo": linha.get("titulo") or "",
                "motivo": linha.get("motivo") or "",
                "gerada_por": linha.get("gerada_por") or "",
                "criado_em": linha.get("criado_em"),
                "atualizado_em": linha.get("atualizado_em"),
                "pendencias": dados.get("pendencias") or [],
                "secoes": len(dados.get("sections") or []),
            }
        )
    return saida


def obter_anexa(peca_id: str) -> dict[str, Any] | None:
    """Uma peça anexa com as seções, no mesmo formato que `para_api` devolve para
    a petição inicial — é o que a tela usa para abrir a peça em edição."""
    registro = armazenamento.obter_peticao_anexa(peca_id)
    if not registro:
        return None
    return para_api(registro["dados"])


def salvar_secoes_anexa(
    peca_id: str,
    secoes: list[dict[str, str]],
    usuario: str = "",
    titulo: str | None = None,
) -> dict[str, Any]:
    """Grava o texto editado de uma peça anexa. Mesma lógica de `salvar_secoes`,
    para a peça irmã em vez da petição inicial — ver `armazenamento.salvar_peticao_anexa`.

    Renomear a peça troca o título nos DOIS lugares: em `dados["title"]`, que é o
    que a tela mostra, e na coluna do registro, que é o que a listagem e o nome
    do arquivo baixado usam. `peca_id` não muda — é a chave da peça, não o nome.
    """
    registro = armazenamento.obter_peticao_anexa(peca_id)
    if not registro:
        raise ErroPeticao("Peça não encontrada.")

    dados, anterior, _alterou = _aplicar_edicao_manual(
        dict(registro["dados"]), secoes, usuario, titulo
    )
    if anterior is not None:
        armazenamento.registrar_versao_peticao(registro["caso_id"], anterior, chave=peca_id)
    dados["updated_at"] = _agora()

    with skill_peticao.do_caso(registro["caso_id"]):
        docx = montar_docx(dados.get("sections") or [])
    armazenamento.salvar_peticao_anexa(
        registro["caso_id"],
        peca_id,
        titulo=str(dados.get("title") or registro.get("titulo") or ""),
        motivo=str(registro.get("motivo") or ""),
        dados=dados,
        docx=docx,
        gerada_por=str(registro.get("gerada_por") or ""),
    )
    return para_api(dados)


@skill_peticao.com_skill_do_caso
def gerar_anexa(
    caso_id: str,
    *,
    titulo: str,
    motivo: str = "",
    pedidos: list[str] | None = None,
    texto_entrevista: str,
    gerada_por: str = "",
) -> dict[str, Any]:
    """Redige UMA das outras ações sugeridas, a partir do material do mesmo caso.

    POR QUE NÃO É A MESMA FUNÇÃO DA PETIÇÃO INICIAL

    `gerar` produz A peça do caso: versiona, guarda o anterior no histórico, entra
    em revisão, é revisada por prompt e aprovada. Estas são peças irmãs, redigidas
    do mesmo material para OUTRA ação — o escritório quer levar duas ações do mesmo
    acidente, e até aqui o banco não permitia (a chave de `peticoes_locais` é o
    caso, então a segunda peça apagava a primeira).

    A minuta principal NÃO é tocada aqui. É o ponto: quem clica em "gerar esta
    peça" na sugestão não pode perder a petição inicial que já revisou.

    O TÍTULO DA SUGESTÃO VAI NO PROMPT COMO ALVO

    Sem isso o modelo redigiria outra petição inicial — o material é o mesmo, e é
    o pedido que muda. O título e os pedidos que a análise sugeriu entram como o
    que esta peça deve postular, e o resto do contexto (identidade do reclamante,
    entrevista, documentos, achados) é o mesmo de `_montar_contexto`.
    """
    titulo = (titulo or "").strip()
    if not titulo:
        raise ErroPeticao("Diga qual peça deve ser redigida.")

    peca_id = id_da_anexa(caso_id, titulo)
    existentes = {linha["id"] for linha in armazenamento.listar_peticoes_anexas(caso_id)}
    if peca_id not in existentes and len(existentes) >= MAX_ANEXAS_POR_CASO:
        raise ErroPeticao(
            f"Este caso já tem {MAX_ANEXAS_POR_CASO} peças além da petição inicial. "
            "Baixe e apague uma antes de redigir outra."
        )

    contexto = _montar_contexto(caso_id, texto_entrevista)
    contexto += _precedentes_para_redigir(contexto)
    contexto += _legislacao_para_redigir(contexto)
    # A ação alternativa parte também da minuta principal: só a entrevista
    # bruta faz o modelo perder datas, valores, documentos e nomes já extraídos.
    principal = carregar(caso_id)
    secoes_principais = (principal or {}).get("sections") or []
    if secoes_principais:
        contexto += "\n\n=== MINUTA PRINCIPAL (referência factual; não copie pedidos) ===\n"
        contexto += "\n\n".join(
            f"### {secao.get('label') or secao.get('code')}\n{secao.get('content') or ''}"
            for secao in secoes_principais
            if secao.get("code") != "JURIMETRY"
        )
    alvo = [f"PEÇA A REDIGIR: {titulo}"]
    if motivo.strip():
        alvo.append(f"POR QUE ELA CABE NESTE CASO: {motivo.strip()}")
    if pedidos:
        alvo.append("PEDIDOS QUE A ANÁLISE APONTOU: " + "; ".join(p for p in pedidos if p))

    saida = _llm_json(
        _com_skill_do_escritorio(
            caso_id,
            CONTRATO_DE_REDACAO
            + """Você é advogado e vai redigir UMA peça específica, indicada
em "PEÇA A REDIGIR", usando o material do caso (entrevista, documentos, achados).

Esta NÃO é a petição inicial do caso — ela já existe. Redija a peça pedida, com os
pedidos próprios dela. Se o material não sustentar a peça, diga isso em `pendencias`
e escreva o que for possível com [PENDENTE: explicação] no que faltar.

Use SOMENTE fatos da entrevista e dos documentos — não invente. A qualificação do
autor sai do bloco IDENTIDADE DO RECLAMANTE, nunca de nome citado na conversa.

QUALIDADE INEGOCIÁVEL: esta peça alternativa deve ter a mesma profundidade,
estrutura e padrão profissional da petição principal. Não entregue resumo,
modelo genérico ou esqueleto só porque é uma ação concorrente. Desenvolva
integralmente fatos, provas, nexo, dispositivos legais, subsunção e consequência
jurídica. Inclua todas as preliminares cabíveis, cada tese específica da ação,
pedidos individualizados coerentes com a fundamentação, provas requeridas, valor
da causa calculado e fechamento. Reaproveite a riqueza factual da minuta principal
quando pertinente, mas não copie pedidos de outra ação nem reduza o texto ao
mínimo. Se uma tese não couber nesta ação, não a invente: explique a distinção
em `pendencias`.

JSON:
{
  "secoes": [
    {"code":"<PAPEL_DA_SECAO>","label":"<título da seção como a SKILL manda; \"\" se a skill não dá título>","content":"<texto, com a marcação definida em formatacao.md>"}
    /* UMA entrada por seção que a SKILL determinar, na ordem e na quantidade que ela determinar.
       PAPEL_DA_SECAO: identificador curto em MAIÚSCULAS. Quando a seção cumprir um destes papéis,
       use exatamente o nome — os validadores automáticos as localizam por ele: HEADING, PRELIMINARY,
       FACTS, LEGAL_GROUNDS, CLAIMS, VALUE, CLOSING. Qualquer outra seção: código livre. Crie SÓ as seções que a skill manda. */
  ],
  "pendencias": ["o que falta para esta peça em particular"]
}
Cada content em parágrafos separados por linha em branco.""",
        ),
        "\n".join(alvo) + "\n\n" + contexto,
        # 360s e não 240s: com o teto de saída dobrado a resposta é fisicamente
        # maior, e manter o prazo antigo trocaria "peça curta" por "o modelo não
        # respondeu" — que é pior, porque perde o trabalho inteiro.
        timeout=360.0,
    )

    secoes = _normalizar_secoes(saida.get("secoes") or [])
    if not any(secao["content"] for secao in secoes):
        raise ErroPeticao("O modelo não devolveu texto desta peça.")

    agora = _agora()
    existente = armazenamento.obter_peticao_anexa(peca_id)
    versao_anexa = 1
    if existente and existente.get("dados"):
        armazenamento.registrar_versao_peticao(caso_id, existente["dados"], chave=peca_id)
        versao_anexa = int(existente["dados"].get("version") or 1) + 1
    dados = {
        "id": peca_id,
        "document_type": "ADDITIONAL_CLAIM",
        "title": titulo,
        "motivo": motivo.strip(),
        "version": versao_anexa,
        "created_at": agora,
        "updated_at": agora,
        "sections": secoes,
        "pendencias": [str(p) for p in saida.get("pendencias") or [] if str(p).strip()],
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "docx_style_version": DOCX_STYLE_VERSION,
        "revisao": {"tipo": "geracao", "usuario": gerada_por, "em": agora, "alteradas": []},
    }
    armazenamento.salvar_peticao_anexa(
        caso_id,
        peca_id,
        titulo=titulo,
        motivo=motivo,
        dados=dados,
        docx=montar_docx(secoes),
        gerada_por=gerada_por,
    )
    return {
        "id": peca_id,
        "titulo": titulo,
        "motivo": motivo.strip(),
        "pendencias": dados["pendencias"],
        "secoes": len(secoes),
        "criado_em": agora,
        "atualizado_em": agora,
        "gerada_por": gerada_por,
    }


def ler_docx_anexa(peca_id: str) -> tuple[str, bytes]:
    """Título e .docx de uma peça anexa, para o download."""
    registro = armazenamento.obter_peticao_anexa(peca_id)
    if not registro:
        raise ErroPeticao("Peça não encontrada.")
    conteudo = bytes(registro.get("_docx") or b"")
    dados = registro.get("dados") or {}
    with skill_peticao.do_caso(registro["caso_id"]):
        if int(dados.get("docx_style_version") or 0) < DOCX_STYLE_VERSION:
            conteudo = montar_docx(dados.get("sections") or [])
        if not conteudo:
            # Regrava a partir do JSON: o texto é a verdade, o binário é derivado.
            conteudo = montar_docx(dados.get("sections") or [])
    return str(registro.get("titulo") or "Peça"), conteudo


def ler_pdf_anexa(peca_id: str) -> tuple[str, bytes]:
    from . import docx_pdf

    titulo, docx = ler_docx_anexa(peca_id)
    try:
        return titulo, docx_pdf.converter(docx)
    except docx_pdf.ErroConversaoDocx as erro:
        raise ErroPeticao(str(erro)) from erro


#: Contrato de redação do escritório, escrito pelo advogado responsável.
#:
#: Vale para os TRÊS pontos que redigem peça — geração principal, `redigir` e peça
#: anexa. Constante única de propósito: quando isto morava copiado em cada
#: instrução, uma mudança pegava num lugar e nos outros não, e a diferença só
#: aparecia semanas depois numa peça que saiu fora do padrão.
#: Contrato do MOTOR (integridade de dados e formato de resposta) — nada de doutrina,
#: estrutura ou estilo de peça. Esses vivem na skill: `references/regras_de_geracao.md`.
CONTRATO_DE_REDACAO = """Você redige peças jurídicas para revisão e protocolo por advogado, EXECUTANDO a SKILL DO ESCRITÓRIO
que acompanha esta instrução: estrutura, argumentação, regras de conteúdo e formatação vêm dela.

INTEGRIDADE (vale para qualquer skill):
- Nunca invente fato, lei, artigo, súmula, tema, ementa, acórdão, relator, tribunal, data, número de
  documento do cliente ou de processo. Só cite o que está no material recebido; sem fonte, [PENDENTE: <dado>].
- Fato extraído de anexo leva "Documento NN — nome do arquivo", com a numeração do bloco DOCUMENTOS.
  Fato só da entrevista leva "conforme relato do autor". Nunca diga que um documento está anexo se
  ele não estiver no bloco DOCUMENTOS.
- Use a entrevista como ALEGAÇÃO e os documentos como PROVA; não trate fato controvertido como provado.
- Toda citação será conferida depois contra o material; a que não constar dele é marcada como não verificada.
- Não crie pedido de dano material sem valor e método de cálculo documentalmente sustentado. Sem ambos, registre a lacuna fora da peça e não formule o pedido.
- CAT, atestado e receita só provam o que efetivamente registram: não presuma nexo, data, tratamento ou vínculo entre médico/clínica e reclamada. Receita sem data não serve para cronologia ou agravamento.
- Tema, precedente e artigo devem ser usados apenas para a hipótese que efetivamente disciplinam. Ao usar precedente por analogia, declare a analogia; art. 195 da CLT não fundamenta perícia médica e revelia é matéria do art. 844 da CLT.
- Antes de entregar, confira que todo pedido tem correspondente no ledger, que documento interno não é citado, que não há duplicação de capítulos/fecho e que a numeração romana é contínua.

"""


_INSTRUCAO_REVISAO = """Você é advogado revisando uma peça jurídica já redigida.
Aplique a CRÍTICA DO ADVOGADO sobre a MINUTA ATUAL.

Linhas no formato [[FOTO:…]] são fotos inseridas na peça. Copie-as IGUAIS, na mesma
posição em relação ao texto em volta, salvo se a crítica pedir para tirar ou mover a
foto.

Linhas que começam com «> » são CITAÇÕES LITERAIS de documento (com a fonte entre
parênteses). Copie-as IGUAIS, palavra por palavra, salvo se a crítica pedir para tirar,
mover ou alterar a citação. Nunca resuma nem reescreva o que o documento diz.

Marcações de formatação feitas pelo advogado — [[i]]…[[/i]], [[u]]…[[/u]],
[[tam=14]]…[[/tam]], [[cor=#c00000]]…[[/cor]] e [[alin=centro]] no começo da linha —
são parte do texto: mantenha-as em volta das mesmas palavras e no mesmo parágrafo. Se
reescrever um trecho marcado, leve a marcação junto; não crie marcações novas.

ANTES DE ESCREVER, CLASSIFIQUE O PEDIDO:

(a) PONTUAL — troca um nome, separa um pedido, corrige uma data, ajusta um trecho
    determinado. Aqui mude SOMENTE o que foi pedido e preserve o restante palavra
    por palavra.

(b) APROFUNDAMENTO — "fundamentação rasa", "deixa mais robusto", "explique
    melhor", "desenvolve mais", "coloca uma parte maior dos julgados", "melhora
    em todos os pontos". Aqui NÃO faça retoque: REESCREVA as seções envolvidas com
    fundamentação mais completa. Cada parágrafo raso vira argumentação
    desenvolvida na estrutura fato -> prova -> norma -> subsunção -> consequência.
    Desenvolva os julgados e súmulas JÁ citados na minuta, explicando por que
    alcançam estes fatos. Se a crítica disser "em todos os pontos" ou não nomear
    seção, aprofunde TODAS as seções argumentativas da peça.

    Aprofundar é ganhar PRECISÃO, não linhas: o que falta é subsunção, prova
    apontada e consequência jurídica, não volume. Devolver o mesmo raciocínio com
    outras palavras é FALHAR no pedido — e inflar o texto com parágrafo genérico
    para parecer maior também é.

Em (b) o "preserve palavra por palavra" NÃO se aplica: expandir, reorganizar e
reescrever é justamente o que foi pedido. O limite é outro — nunca invente fato,
prova, número de processo, valor ou data que não estejam na minuta atual. Sem
material novo, aprofunde o RACIOCÍNIO JURÍDICO sobre o que já existe.

NUNCA devolva a minuta inteira igual ao que recebeu. Se o pedido for vago, ambíguo
ou parecer já atendido, NÃO pare: aplique a melhor interpretação possível — o
advogado pediu uma mudança e espera vê-la — e registre em "perguntas" o que
precisaria confirmar com ele. Perguntar é bem-vindo; devolver o texto intacto, não.

Você tem poder total sobre a peça. Pode reescrever, criar, excluir ou reordenar
seções inteiras quando isso decorrer da crítica, inclusive alterar praticamente
100% do documento. Se o pedido for pontual, calibre a alteração para ele; se for
profundo, entregue uma nova versão profunda e completa. Você pode criar e renumerar os títulos e
subtítulos internos (I –, II –, I.1 –) e mover matéria de uma seção para outra —
por exemplo tirar as preliminares do DO DIREITO e levá-las para DAS PRELIMINARES.
Nada aqui é intocável, desde que a crítica do advogado sustente a mudança.

TABELAS: quando a crítica pedir uma tabela, ou quando uma tabela tornar fatos
comprovados mais claros, use Markdown com cabeçalho e linha separadora no ponto
exato da seção solicitado. A exportação transforma esse bloco em tabela Word
nativa e editável. Preserve os parágrafos que vêm antes e depois; nunca use
espaços, tabs ou dados inventados para simular/preencher uma tabela.

Devolva a NOVA PEÇA COMPLETA como lista ordenada de seções. Não há quantidade,
ordem ou código fixos: inclua todas as seções necessárias, inclusive as mantidas.
Cada `code` deve ser estável, curto e único. JSON:
{
  "secoes": [
    {"code":"<PAPEL_DA_SECAO>","label":"<título da seção como a SKILL manda; \"\" se a skill não dá título>","content":"<texto, com a marcação definida em formatacao.md>"}
    /* UMA entrada por seção que a SKILL determinar, na ordem e na quantidade que ela determinar.
       PAPEL_DA_SECAO: identificador curto em MAIÚSCULAS. Quando a seção cumprir um destes papéis,
       use exatamente o nome — os validadores automáticos as localizam por ele: HEADING, PRELIMINARY,
       FACTS, LEGAL_GROUNDS, CLAIMS, VALUE, CLOSING. Qualquer outra seção: código livre. Crie SÓ as seções que a skill manda. */
  ],
  "perguntas": ["o que você precisaria confirmar com o advogado; [] se nada"]
}
Cada content em parágrafos separados por linha em branco."""

_INSTRUCAO_CONFERENCIA = """Você confere se a revisão de uma peça jurídica foi feita corretamente.
Recebe o PEDIDO DO ADVOGADO e, para cada seção alterada, o texto ANTES e DEPOIS.
Seja rigoroso: "atendeu" só é true se TUDO o que o pedido manda estiver no texto DEPOIS.

Quando o pedido for de APROFUNDAMENTO ("fundamentação rasa", "mais robusto",
"explique melhor", "em todos os pontos"), duas regras mudam:

- "atendeu" só é true se o texto DEPOIS estiver de fato mais DESENVOLVIDO que o
  ANTES. Mesmo tamanho com palavras trocadas é false.
- "alteradas_sem_pedido" fica VAZIO. Pedido global autoriza mexer em qualquer
  seção argumentativa, e marcar seção ali faria o sistema DESFAZER exatamente a
  ampliação que o advogado pediu.

Responda APENAS JSON:
{"atendeu": true, "faltou": "o que do pedido não foi feito, em uma frase; vazio se atendeu",
 "alteradas_sem_pedido": ["code de seção alterada que o pedido não justifica"]}"""


#: Como o advogado pede APROFUNDAMENTO, e não um retoque pontual.
#:
#: Colhido dos pedidos reais que não estavam funcionando: "Fundamentação muito
#: rasa, melhora isso em todos os pontos", "Deixa os parágrafos mais robustos",
#: "Coloca uma parte maior dos julgados e explique melhor os parágrafos".
#:
#: Sem acento e em minúsculas — a comparação passa por `_sem_acento`.
_SINAIS_DE_APROFUNDAMENTO = (
    "todos os pontos", "em tudo", "mais robust", "robustez", "aprofund",
    "mais denso", "rasa", "raso", "superficial", "explique melhor",
    "explica melhor", "desenvolv", "mais longo", "mais extenso", "amplie",
    "amplia", "detalhe mais", "detalha mais", "mais complet", "enriquec",
    "melhora isso", "melhore isso", "parte maior", "mais fundament",
)


def _pedido_global(prompt_critica: str) -> bool:
    """O advogado pediu para APROFUNDAR, e não para mexer num ponto específico?

    Isto decide se a trava de `alteradas_sem_pedido` vale. Num pedido pontual
    ela protege o texto: impede a IA de reescrever o que ninguém mandou. Num
    pedido de aprofundamento ela fazia o oposto do pedido — a conferência
    marcava as seções como "não pedidas" e o código RESTAURAVA o texto raso.
    O advogado via "Seções alteradas: Dos fatos, Do direito" e um texto do mesmo
    tamanho de antes. Foi o defeito relatado nas versões 8, 9 e 10 da peça.

    Errar para o lado de considerar global é o lado barato: no máximo a IA
    aprofunda uma seção a mais, e o advogado revisa o texto de qualquer forma.
    O caro é o contrário — desfazer em silêncio o que ele pediu três vezes.
    """
    texto = _sem_acento(prompt_critica).lower()
    return any(sinal in texto for sinal in _SINAIS_DE_APROFUNDAMENTO)


def _texto_normalizado(texto: Any) -> str:
    return " ".join(str(texto or "").split())


def _mesclar_revisao(
    secoes_atuais: list[dict[str, Any]], revisadas: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    por_codigo = {str(s.get("code") or ""): s for s in revisadas}
    resultado = []
    for atual in secoes_atuais:
        nova = por_codigo.get(str(atual.get("code") or "")) or {}
        conteudo = str(nova.get("content") or "").strip()
        resultado.append({**atual, "content": conteudo, "written_by": "agent"} if conteudo else dict(atual))
    return resultado


def _identidade_da_secao(secao: dict[str, Any]) -> tuple[str, str]:
    """O que, numa seção, conta como "mudou": o corpo E o título do tópico.

    O rótulo não é enfeite de tela — é ele que vira o parágrafo em negrito do
    .docx (ver `montar_docx`). Trocar "DO CONTRATO DE TRABALHO" por outro título
    é uma edição da peça como outra qualquer; comparando só `content`, a troca
    não criava versão nem chegava a ser gravada.
    """
    return _texto_normalizado(secao.get("content")), _texto_normalizado(secao.get("label"))


def _secoes_alteradas(
    antes: list[dict[str, Any]], depois: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    anteriores = {s.get("code"): _identidade_da_secao(s) for s in antes}
    return [s for s in depois if _identidade_da_secao(s) != anteriores.get(s.get("code"))]


def _conferir_revisao(
    prompt_critica: str,
    antes: list[dict[str, Any]],
    alteradas: list[dict[str, Any]],
) -> dict[str, Any]:
    anteriores = {s.get("code"): s for s in antes}
    trechos = "\n\n".join(
        f"### {s.get('code')} — {s.get('label')}\n"
        f"ANTES:\n{(anteriores.get(s.get('code')) or {}).get('content', '')}\n"
        f"DEPOIS:\n{s.get('content', '')}"
        for s in alteradas
    )
    try:
        saida = _llm_json(
            _INSTRUCAO_CONFERENCIA,
            f"PEDIDO DO ADVOGADO:\n{prompt_critica}\n\nSEÇÕES ALTERADAS:\n{trechos}",
            timeout=120.0,
        )
    except ErroPeticao:
        return {"atendeu": None, "faltou": "", "alteradas_sem_pedido": []}
    atendeu = saida.get("atendeu")
    indevidas = saida.get("alteradas_sem_pedido")
    return {
        "atendeu": atendeu if isinstance(atendeu, bool) else None,
        "faltou": str(saida.get("faltou") or "").strip()[:500],
        "alteradas_sem_pedido": [str(c) for c in indevidas if isinstance(c, str)]
        if isinstance(indevidas, list)
        else [],
    }


@skill_peticao.com_skill_do_caso
def _revisar_secoes_via_llm(
    caso_id: str, secoes_atuais: list[dict[str, Any]], prompt_critica: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    instrucao = _com_skill_do_escritorio(caso_id, _INSTRUCAO_REVISAO, revisao=True)
    minuta_atual = "\n\n".join(
        f"### {s.get('code')} — {s.get('label', s.get('code'))}\n{s.get('content', '')}"
        for s in secoes_atuais
    )
    observacao = ""
    perguntas: list[str] = []
    melhor: tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], int] | None = None

    # Três tentativas, e não duas: a SEGUNDA revisão de uma peça é o caso difícil
    # — a minuta já foi corrigida uma vez, e o modelo tende a concluir que "já
    # está bom" e devolver tudo igual. Era exatamente aí que a tela quebrava.
    for tentativa in (1, 2, 3):
        entrada = f"MINUTA ATUAL:\n{minuta_atual}\n\nCRÍTICA DO ADVOGADO:\n{prompt_critica}"
        if observacao:
            entrada += (
                f"\n\nATENÇÃO — A TENTATIVA ANTERIOR FALHOU: {observacao}\n"
                # NÃO repita aqui "mude somente o que a crítica pede": era o que
                # estava escrito, e num pedido de aprofundamento essa frase
                # mandava o modelo fazer o MÍNIMO justamente na segunda chance,
                # depois de a primeira já ter sido rasa demais.
                "Corrija isso agora. Se a crítica pede aprofundamento, reescreva "
                "as seções envolvidas de forma substancialmente mais longa e "
                "densa — não basta trocar palavras."
            )
        # 360s como nas de redação: esta chamada REESCREVE a peça inteira, e com o
        # teto de saída em 8192 a resposta ficou do mesmo tamanho. Pior, ela roda em
        # laço de até três tentativas — estourar o prazo aqui perde a crítica que o
        # advogado acabou de escrever, que é o erro mais caro deste fluxo.
        saida = _llm_json(instrucao, entrada, timeout=360.0)
        perguntas = [
            str(p).strip()
            for p in (saida.get("perguntas") or [])
            if str(p).strip()
        ][:5]
        secoes = _normalizar_secoes_da_revisao(saida.get("secoes") or [])
        alteradas = _secoes_alteradas(secoes_atuais, secoes)
        mudou_estrutura = [s.get("code") for s in secoes_atuais] != [s.get("code") for s in secoes]
        if not alteradas and not mudou_estrutura:
            observacao = (
                "você devolveu a minuta inteira igual. Aplique a melhor interpretação do "
                "pedido e registre em 'perguntas' o que precisar confirmar."
            )
            continue

        conferencia = _conferir_revisao(prompt_critica, secoes_atuais, alteradas)
        # Pedido GLOBAL não tem seção indevida — e isto não é detalhe: era esta
        # trava que desfazia o trabalho. Em "melhora a fundamentação em todos os
        # pontos", a conferência marcava seções como "não pedidas" e o código
        # restaurava o texto raso original. O advogado via "Seções alteradas:
        # Dos fatos, Do direito" e um texto que continuava do mesmo tamanho.
        melhor = (secoes, alteradas, conferencia, tentativa)
        if conferencia["atendeu"] is not False:
            break
        observacao = conferencia["faltou"] or "a revisão não fez tudo o que a crítica pede."

    if melhor is None:
        # NÃO é mais erro, e a diferença importa: levantar aqui abortava a tela e
        # perdia o pedido do advogado. Agora a peça volta intacta com o aviso —
        # quem chama decide não criar versão nova — e as perguntas da IA sobem
        # junto, que é o caminho para destravar o pedido ambíguo.
        return list(secoes_atuais), {
            "alteradas": [],
            "alterou": False,
            "atendeu": None,
            "faltou": "",
            "perguntas": perguntas,
            "tentativas": 3,
        }

    secoes, alteradas, conferencia, tentativas = melhor
    secoes = _preservar_fotos(secoes_atuais, secoes, prompt_critica)
    secoes = _preservar_citacoes(secoes_atuais, secoes, prompt_critica)
    return secoes, {
        "alteradas": [_nome_da_secao(s) for s in alteradas],
        "alterou": True,
        "atendeu": conferencia["atendeu"],
        "faltou": "" if conferencia["atendeu"] is not False else conferencia["faltou"],
        "perguntas": perguntas,
        "tentativas": tentativas,
    }


def revisar_anexa_com_prompt(
    peca_id: str, *, prompt_critica: str, usuario: str = ""
) -> dict[str, Any]:
    prompt_critica = prompt_critica.strip()
    if not prompt_critica:
        raise ErroPeticao("Escreva o que deve mudar nesta peça.")

    registro = armazenamento.obter_peticao_anexa(peca_id)
    if not registro:
        raise ErroPeticao("Peça não encontrada.")

    anterior = json.loads(json.dumps(registro["dados"]))
    dados = dict(registro["dados"])
    secoes_atuais = dados.get("sections") or []
    if not secoes_atuais:
        raise ErroPeticao("Esta peça não tem seções para revisar.")

    secoes, conferencia = _revisar_secoes_via_llm(registro["caso_id"], secoes_atuais, prompt_critica)

    # Mesma regra da petição inicial: sem alteração, sem versão nova. Ver o
    # comentário em `revisar_com_prompt`.
    if not conferencia.get("alterou"):
        return para_api({**dados, "revisao": {
            "tipo": "prompt",
            "prompt": prompt_critica,
            "usuario": usuario,
            "em": _agora(),
            **conferencia,
        }})

    armazenamento.registrar_versao_peticao(registro["caso_id"], anterior, chave=peca_id)
    agora = _agora()
    dados["sections"] = secoes
    dados["updated_at"] = agora
    dados["version"] = int(anterior.get("version") or 1) + 1
    dados["revisao"] = {
        "tipo": "prompt",
        "prompt": prompt_critica,
        "usuario": usuario,
        "em": agora,
        **conferencia,
    }

    with skill_peticao.do_caso(registro["caso_id"]):
        docx = montar_docx(secoes)
    armazenamento.salvar_peticao_anexa(
        registro["caso_id"],
        peca_id,
        titulo=str(registro.get("titulo") or dados.get("title") or ""),
        motivo=str(registro.get("motivo") or ""),
        dados=dados,
        docx=docx,
        gerada_por=str(registro.get("gerada_por") or ""),
    )
    return para_api(dados)


@skill_peticao.com_skill_do_caso
def revisar_com_prompt(
    caso_id: str,
    *,
    prompt_critica: str,
    usuario: str,
    generaliza: bool = True,
    origem: str = "painel",
) -> dict[str, Any]:
    """Reescreve a petição a partir de uma crítica em linguagem natural.

    Issue "Permitir alteração da petição por prompt com rastreabilidade":
    advogado ou gestor descreve o que quer mudar ("os pedidos estão fracos,
    separe dano moral do material") e o sistema aplica sobre a petição ATUAL —
    não gera do zero, então o que já estava bom continua igual.

    Três coisas ficam registradas, em ordem:

    1. A versão anterior vai para `peticao_versoes` **antes** de ser
       sobrescrita — rastreabilidade por caso, requisito da issue.
    2. A crítica em si vai para `peticao_criticas`, com quem pediu e em cima de
       qual versão — o "log" e a "instrução armazenada" que a issue pede, e
       também o que alimenta a retroalimentação automática entre casos (ver
       `_com_skill_do_escritorio`). Com `generaliza=False` ela fica só na
       rastreabilidade deste caso e NÃO instrui as próximas petições: é o que
       impede um "troque o nome do cliente" de virar regra da categoria.
    3. A nova versão volta **sempre** para `IN_REVIEW`, mesmo que a anterior já
       estivesse `APPROVED` — decisão do escritório: revisão por prompt nunca
       substitui uma versão aprovada sem passar de novo pela aprovação humana.
    """
    prompt_critica = prompt_critica.strip()
    if not prompt_critica:
        raise ErroPeticao("Escreva o que deve mudar na petição.")

    atual = carregar(caso_id)
    if not atual:
        raise ErroPeticao("Nenhuma petição gerada para este caso.")

    secoes_atuais = [
        s for s in atual.get("sections") or [] if s.get("code") != "JURIMETRY"
    ]
    if not secoes_atuais:
        raise ErroPeticao("Esta petição não tem seções para revisar.")

    secoes, conferencia = _revisar_secoes_via_llm(caso_id, secoes_atuais, prompt_critica)

    # Nada mudou: devolve a peça como está, SEM versão nova.
    #
    # Antes isto levantava erro e a tela morria — era o defeito da "segunda
    # revisão". Agora é aviso. Mas também não pode virar versão: gravar snapshot
    # e incrementar `version` com o texto idêntico encheria o histórico de
    # versões falsas, e o advogado perderia a referência de quando a peça
    # realmente mudou. As perguntas da IA sobem junto — é com elas que ele
    # reescreve o pedido e destrava.
    if conferencia.get("alterou"):
        # A revisão pedida pelo advogado (ou pelo chat) também passa pela conferência.
        # Sem correção automática: o pedido foi DELE, e reescrever por cima mudaria o
        # que ele pediu. Mas a súmula de memória sai carimbada e o achado aparece na
        # comparação, antes de ele aceitar.
        try:
            secoes, violacoes, _ = _conferir_contra_os_autos(caso_id, secoes, corrigir=False)
            conferencia["conferencia_autos"] = conferencia_peticao.como_achados(violacoes)
        except Exception:  # noqa: BLE001 — conferência não pode perder o pedido do advogado
            log.warning("petição local: conferência da revisão falhou (caso %s)", caso_id, exc_info=True)
        candidato = {
            "id": uuid.uuid4().hex, "status": "PENDING_REVIEW",
            "base_version": int(atual.get("version") or 1), "sections": secoes,
            "prompt": prompt_critica, "usuario": usuario, "generaliza": generaliza,
            "created_at": _agora(), "revisao": {"tipo": "prompt", "prompt": prompt_critica,
                "usuario": usuario, "origem": origem, "em": _agora(), **conferencia},
        }
        novos_dados = {**atual, "revisao_pendente": candidato}
        _salvar(caso_id, novos_dados)
        return novos_dados

    if not conferencia.get("alterou"):
        return {**atual, "revisao": {
            "tipo": "prompt",
            "prompt": prompt_critica,
            "usuario": usuario,
            "origem": origem,
            "em": _agora(),
            **conferencia,
        }}

    # 1) snapshot da versão anterior — antes de sobrescrever.
    armazenamento.registrar_versao_peticao(caso_id, atual)

    versao_origem = int(atual.get("version") or 1)
    versao_resultado = versao_origem + 1
    novos_dados = {
        **atual,
        "version": versao_resultado,
        "status": "IN_REVIEW",
        "sections": secoes,
        "revisao": {
            "tipo": "prompt",
            "prompt": prompt_critica,
            "usuario": usuario,
            # De onde veio o pedido: o campo do painel ou o chat ao lado da peça.
            # Documento jurídico não pode ter edição de origem desconhecida.
            "origem": origem,
            "em": _agora(),
            **conferencia,
        },
    }
    _salvar(caso_id, novos_dados)

    # 2) a crítica em si — log + instrução armazenada + insumo da retroalimentação.
    try:
        peticao_criticas.inicializar()
        peticao_criticas.registrar(
            caso_id=caso_id,
            categoria=_categoria_do_caso(caso_id),
            versao_origem=versao_origem,
            versao_resultado=versao_resultado,
            prompt=prompt_critica,
            usuario=usuario,
            generaliza=generaliza,
        )
    except Exception:
        # A revisão já foi salva — perder o registro da crítica é ruim, mas não pode
        # desfazer o trabalho do advogado por uma oscilação do pgvector. Fica no log
        # do servidor; quem ler a rastreabilidade do caso vai notar a lacuna.
        log.exception("crítica de petição não pôde ser registrada (caso %s)", caso_id)

    return novos_dados


@skill_peticao.com_skill_do_caso
def aceitar_revisao_pendente(caso_id: str, revisao_id: str) -> dict[str, Any]:
    atual = carregar(caso_id)
    candidata = (atual or {}).get("revisao_pendente") or {}
    if not atual or candidata.get("id") != revisao_id:
        raise ErroPeticao("Revisão pendente não encontrada.")
    if int(candidata.get("base_version") or 0) != int(atual.get("version") or 1):
        raise ErroPeticao("A peça mudou após a revisão; gere uma nova comparação.")
    secoes = candidata.get("sections") or []
    if not secoes:
        raise ErroPeticao("A revisão pendente não contém uma peça válida.")
    diff_aprovado = peticao_aprendizado.diff_semantico(atual.get("sections") or [], secoes)
    armazenamento.registrar_versao_peticao(caso_id, {k: v for k, v in atual.items() if k != "revisao_pendente"})
    agora = _agora()
    dados = {k: v for k, v in atual.items() if k != "revisao_pendente"}
    dados.update({
        "sections": secoes, "version": int(atual.get("version") or 1) + 1,
        "status": "IN_REVIEW", "updated_at": agora,
        "revisao": {"tipo": "prompt", "status": "ACCEPTED", "id": revisao_id,
            "prompt": candidata.get("prompt", ""), "usuario": candidata.get("usuario", ""),
            "em": agora, "semantic_diff": diff_aprovado, **(candidata.get("revisao") or {})},
    })
    _reconferir(caso_id, dados)
    _salvar(caso_id, dados)
    try:
        peticao_criticas.inicializar()
        peticao_criticas.registrar(caso_id=caso_id, categoria=_categoria_do_caso(caso_id),
            versao_origem=int(atual.get("version") or 1), versao_resultado=int(dados["version"]),
            prompt=str(candidata.get("prompt") or ""), usuario=str(candidata.get("usuario") or ""),
            generaliza=bool(candidata.get("generaliza", True)))
    except Exception:
        log.exception("crítica aceita não pôde ser registrada (caso %s)", caso_id)
    try:
        peticao_aprendizado.registrar_feedback(
            caso_id=caso_id, categoria=_categoria_do_caso(caso_id),
            advogado=str(candidata.get("usuario") or ""), texto=str(candidata.get("prompt") or ""),
            geral=bool(candidata.get("generaliza", True)),
            versao_origem=int(atual.get("version") or 1), versao_resultado=int(dados["version"]),
        )
        peticao_aprendizado.registrar_execucao(
            generation_id=str(atual.get("generation_id") or revisao_id), caso_id=caso_id,
            skill_name="semantic_diff", itens_recuperados=diff_aprovado, confidence=1.0,
        )
    except Exception:
        log.exception("aprendizado da revisão aceita não pôde ser registrado (caso %s)", caso_id)
    return dados


def descartar_revisao_pendente(caso_id: str, revisao_id: str) -> dict[str, Any]:
    atual = carregar(caso_id)
    candidata = (atual or {}).get("revisao_pendente") or {}
    if not atual or candidata.get("id") != revisao_id:
        raise ErroPeticao("Revisão pendente não encontrada.")
    dados = {k: v for k, v in atual.items() if k != "revisao_pendente"}
    descartadas = list(dados.get("revisoes_descartadas") or [])[-19:]
    descartadas.append({**candidata, "status": "REJECTED", "rejected_at": _agora()})
    dados["revisoes_descartadas"] = descartadas
    dados["revisao"] = {"tipo": "prompt", "status": "REJECTED", "id": revisao_id,
        "prompt": candidata.get("prompt", ""), "usuario": candidata.get("usuario", ""), "em": _agora()}
    try:
        # Rejeição é evidência auditável, mas nunca vira preferência reaproveitável.
        peticao_aprendizado.registrar_feedback(
            caso_id=caso_id, categoria=_categoria_do_caso(caso_id),
            advogado=str(candidata.get("usuario") or ""), texto=str(candidata.get("prompt") or ""),
            geral=False, versao_origem=int(atual.get("version") or 1),
            versao_resultado=int(atual.get("version") or 1),
        )
    except Exception:
        log.exception("evento de revisão rejeitada não pôde ser registrado (caso %s)", caso_id)
    return _salvar(caso_id, dados)


def historico_de_criticas(caso_id: str) -> list[dict[str, Any]]:
    """A rastreabilidade que a issue pede: cada crítica deste caso, quem pediu, quando."""
    try:
        peticao_criticas.inicializar()
        return peticao_criticas.listar_por_caso(caso_id)
    except Exception:
        log.warning("histórico de críticas indisponível (caso %s)", caso_id, exc_info=True)
        return []


def historico_de_versoes(caso_id: str, peca_id: str | None = None) -> list[dict[str, Any]]:
    """As versões anteriores desta petição — o que ela era antes de cada revisão."""
    if peca_id:
        return armazenamento.listar_versoes_peticao(caso_id, chave=peca_id)
    return armazenamento.listar_versoes_peticao(caso_id)


#: Quanto tempo sem digitar encerra uma "sessão de edição".
#:
#: A tela grava sozinha a cada pausa na digitação. Sem agrupar, cada pausa viraria
#: uma versão nova no histórico — dezenas por parágrafo reescrito, e o histórico
#: deixaria de servir para achar "o que a peça era antes de eu mexer". Edições
#: manuais seguidas do MESMO usuário, com intervalo menor que isto, somam-se na
#: mesma versão; a versão anterior à sessão já foi arquivada na primeira gravação.
JANELA_EDICAO_MANUAL = timedelta(
    minutes=float(os.getenv("PETICAO_JANELA_EDICAO_MINUTOS", "10"))
)


def _continua_sessao_manual(revisao: Any, usuario: str, agora: datetime) -> bool:
    if not isinstance(revisao, dict) or revisao.get("tipo") != "manual":
        return False
    if str(revisao.get("usuario") or "") != usuario:
        return False
    try:
        ultima = datetime.fromisoformat(str(revisao.get("em") or ""))
    except ValueError:
        return False
    if ultima.tzinfo is None:
        ultima = ultima.replace(tzinfo=timezone.utc)
    return timedelta(0) <= agora - ultima <= JANELA_EDICAO_MANUAL


def _secao_editada(secao: dict[str, Any], enviada: dict[str, str]) -> dict[str, Any]:
    """Aplica sobre a seção gravada o que a tela mandou.

    `label` só é tocado quando o campo VEM no envio: `decidir_peticao` e os
    clientes antigos mandam só `code`/`content`, e por omissão apagariam o
    título do tópico. O rótulo vazio, por outro lado, é escolha legítima — é
    assim que se tira o título de um tópico sem apagar o texto dele.
    """
    nova = {**secao, "content": enviada.get("content", "")}
    if "label" in enviada:
        nova["label"] = str(enviada.get("label") or "").strip()
    return nova


def _aplicar_edicao_manual(
    dados: dict[str, Any],
    secoes: list[dict[str, str]],
    usuario: str,
    titulo: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None, bool]:
    """Aplica o texto editado. Devolve `(dados, anterior, alterou_secoes)`.

    `anterior` é a versão a arquivar — `None` quando nada mudou OU quando a edição
    continua a sessão manual em curso (ver `JANELA_EDICAO_MANUAL`), caso em que a
    versão já está aberta e o arquivo do "antes" já foi feito.

    `alterou_secoes` é só sobre as seções, e não sobre o título da peça: quem lê
    esse retorno usa-o para reconferir a minuta contra os autos, e renomear a
    peça não muda um fato dentro dela.
    """
    anterior = json.loads(json.dumps(dados))
    por_codigo = {s["code"]: s for s in secoes if s.get("code")}
    atuais = [secao for secao in dados.get("sections") or [] if secao.get("code") != "JURIMETRY"]
    novas = [
        _secao_editada(secao, por_codigo[secao["code"]]) if secao.get("code") in por_codigo else secao
        for secao in atuais
    ]
    alteradas = _secoes_alteradas(atuais, novas)
    dados["sections"] = novas

    titulo_novo = (titulo or "").strip()
    titulo_mudou = bool(titulo_novo) and titulo_novo != str(dados.get("title") or "").strip()
    if titulo_mudou:
        dados["title"] = titulo_novo

    if not alteradas and not titulo_mudou:
        return dados, None, False
    # Uma edição manual muda a versão-base; a candidata anterior não pode mais
    # ser aceita por cima dela.
    dados.pop("revisao_pendente", None)
    agora = datetime.now(timezone.utc)
    rotulos = [_nome_da_secao(s) for s in alteradas]
    if titulo_mudou:
        rotulos.append("Título da peça")
    revisao_atual = anterior.get("revisao")
    if _continua_sessao_manual(revisao_atual, usuario, agora):
        ja_alteradas = list(revisao_atual.get("alteradas") or [])
        dados["revisao"] = {
            **revisao_atual,
            "em": agora.isoformat(),
            "alteradas": ja_alteradas + [r for r in rotulos if r not in ja_alteradas],
        }
        return dados, None, bool(alteradas)
    dados["version"] = int(anterior.get("version") or 1) + 1
    dados["revisao"] = {
        "tipo": "manual",
        "usuario": usuario,
        "em": agora.isoformat(),
        "alteradas": rotulos,
    }
    return dados, anterior, bool(alteradas)


@skill_peticao.com_skill_do_caso
def salvar_secoes(
    caso_id: str,
    secoes: list[dict[str, str]],
    usuario: str = "",
    titulo: str | None = None,
) -> dict[str, Any]:
    dados = carregar(caso_id)
    if not dados:
        raise ErroPeticao("Nenhuma petição gerada para este caso.")
    dados, anterior, alterou = _aplicar_edicao_manual(dados, secoes, usuario, titulo)
    if anterior is not None:
        armazenamento.registrar_versao_peticao(caso_id, anterior)
    if alterou:
        _reconferir(caso_id, dados)
    return _salvar(caso_id, dados)


@skill_peticao.com_skill_do_caso
def atualizar_status(caso_id: str, *, status: str) -> dict[str, Any]:
    dados = carregar(caso_id)
    if not dados:
        raise ErroPeticao("Nenhuma petição gerada para este caso.")
    dados["status"] = status
    return _salvar(caso_id, dados)


_DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@skill_peticao.com_skill_do_caso
def marcar_protocolo(
    caso_id: str, *, protocolada: bool, numero: str = "", data: str = "", por: str = ""
) -> dict[str, Any]:
    """Marca (ou desmarca) a petição como protocolada, com o número do processo.

    Fica à parte de `status`: aprovação é a revisão do advogado; protocolo é o
    envio ao tribunal, e a peça pode ser protocolada sem passar pela aprovação.

    O número é obrigatório: digitá-lo é a confirmação de que a peça foi mesmo
    protocolada, e é por ele que a lista de peças protocoladas é consultada.
    """
    dados = carregar(caso_id)
    if not dados:
        raise ErroPeticao("Nenhuma petição gerada para este caso.")
    if not protocolada:
        dados["protocolo"] = None
        return _salvar(caso_id, dados)
    numero = " ".join(str(numero or "").split())
    if not numero:
        raise ValueError("Digite o número do protocolo para confirmar.")
    if len(numero) > 60:
        raise ValueError("O número do protocolo passou de 60 caracteres.")
    data = str(data or "").strip()
    if data:
        try:
            if not _DATA_ISO.match(data):
                raise ValueError(data)
            date.fromisoformat(data)
        except ValueError as erro:
            raise ValueError("Data do protocolo inválida: use AAAA-MM-DD.") from erro
    dados["protocolo"] = {
        "numero": numero,
        "data": data or datetime.now(timezone(timedelta(hours=-3))).date().isoformat(),
        "marcado_por": str(por or "")[:200],
        "marcado_em": _agora(),
    }
    return _salvar(caso_id, dados)


def para_api(dados: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": dados.get("id", ID_LOCAL),
        "generation_id": dados.get("generation_id"),
        "document_type": dados.get("document_type", "INITIAL_PETITION"),
        "status": dados.get("status", "IN_REVIEW"),
        "version": dados.get("version", 1),
        "title": dados.get("title", "Petição inicial"),
        "readiness": dados.get("readiness") or {},
        # Petições gravadas antes da conferência têm achados sem `category`, e a tela
        # faz `category.toLowerCase()`: normaliza aqui para não derrubar o cartão.
        "review": {
            **(dados.get("review") or {}),
            "findings": [_achado_legivel(a) for a in (dados.get("review") or {}).get("findings") or []],
        },
        "jurimetria": dados.get("jurimetria") or {},
        "blocking_findings": dados.get("blocking_findings", 0),
        "model": dados.get("model"),
        "created_at": dados.get("created_at", _agora()),
        "revisao": dados.get("revisao") or None,
        "revisao_pendente": dados.get("revisao_pendente") or None,
        "protocolo": dados.get("protocolo") or None,
        "trace": dados.get("trace") or {},
        "sections": [
            secao
            for secao in dados.get("sections") or []
            if secao.get("code") != "JURIMETRY"
        ],
    }


def progresso(caso_id: str, desde: str) -> dict[str, Any]:
    """Andamento da geração local — não prende a request HTTP no LLM.

    A geração assíncrona grava `solicitacoes_peticao` no início. Sem isto, um
    502 do Traefik (timeout ~60s) cortava a tela enquanto o modelo ainda
    escrevia por até 6 minutos — e a peça às vezes nascia sem o advogado ver.
    """
    dados = carregar(caso_id)
    criado = str((dados or {}).get("updated_at") or (dados or {}).get("created_at") or "")
    if dados and criado and criado >= desde:
        return {
            "status": "DONE",
            "completed_steps": len(dados.get("sections") or []),
            "generation_id": ID_LOCAL,
            "blocking_findings": dados.get("blocking_findings", 0),
            "etapa": "Petição pronta.",
            "passo": PASSOS_GERACAO,
            "passos_totais": PASSOS_GERACAO,
        }

    solicitacao = armazenamento.ultima_solicitacao_peticao(caso_id)
    if solicitacao and str(solicitacao.get("solicitada_em") or "") >= desde:
        etapa = str(solicitacao.get("etapa") or "").strip() or "Redigindo a petição…"
        passo = int(solicitacao.get("passo") or 0)
        total = int(solicitacao.get("passos_totais") or PASSOS_GERACAO) or PASSOS_GERACAO
        if solicitacao.get("status") == "failed":
            return {
                "status": "FAILED",
                "completed_steps": passo,
                "generation_id": None,
                "blocking_findings": 0,
                "erro": solicitacao.get("erro") or "A geração da petição falhou.",
                "etapa": etapa,
                "passo": passo,
                "passos_totais": total,
            }
        if solicitacao.get("status") == "completed":
            # Peça gravada mas `updated_at` às vezes não bate com `desde`
            # (formato/fuso). Sem isto o polling ficava em RUNNING para sempre.
            secoes = len((dados or {}).get("sections") or [])
            return {
                "status": "DONE",
                "completed_steps": secoes,
                "generation_id": ID_LOCAL if dados else None,
                "blocking_findings": (dados or {}).get("blocking_findings", 0),
                "etapa": "Petição pronta.",
                "passo": total,
                "passos_totais": total,
            }
        perdida = _solicitacao_perdida(solicitacao) if solicitacao.get("status") != "failed" else ""
        if perdida:
            log.warning("petição local: solicitação %s encerrada como perdida em '%s' (%s%%)", solicitacao.get("id"), etapa, passo)
            armazenamento.concluir_solicitacao_peticao(str(solicitacao["id"]), perdida)
            return {
                "status": "FAILED", "completed_steps": passo, "generation_id": None, "blocking_findings": 0,
                "erro": perdida, "etapa": etapa, "passo": passo, "passos_totais": total,
            }
        return {
            "status": "RUNNING",
            "completed_steps": passo,
            "generation_id": None,
            "blocking_findings": 0,
            "etapa": etapa,
            "passo": passo,
            "passos_totais": total,
        }

    return {
        "status": "RUNNING",
        "completed_steps": 0,
        "generation_id": None,
        "blocking_findings": 0,
        "etapa": "Preparando a geração…",
        "passo": 0,
        "passos_totais": PASSOS_GERACAO,
    }


#: Linha de citação: `> texto`. É como um trecho de documento entra na peça.
_RE_TRECHO = re.compile(r"^\s*>\s?(.*\S.*)$")


# ------------------------------------------------------------- formatação no texto
#
# O editor da tela deixa a pessoa formatar trechos (itálico, sublinhado, tachado,
# tamanho, cor) e parágrafos (alinhamento, recuos, entrelinha, espaço antes e
# depois). A formatação vive NO TEXTO da seção, como marcações, pelo mesmo motivo
# das fotos: assim ela atravessa versão, histórico, revisão por IA e chat sem
# caminho paralelo. Só o .docx sabe o que elas significam.
#
#   **negrito**                      (já existia)
#   [[i]]…[[/i]]   [[u]]…[[/u]]      itálico, sublinhado
#   [[s]]…[[/s]]                     tachado
#   [[tam=14]]…[[/tam]]              tamanho em pontos
#   [[cor=#c00000]]…[[/cor]]         cor do texto
#   uma tabulação literal            vira <w:tab/> dentro da linha
#   [[alin=centro]] no início da linha   esquerda | centro | direita | justificado
#   [[par=esq:2;pri:-1.25;dir:0]] no início da linha
#       os recuos em centímetros; `pri` aceita negativo, que é o deslocamento
#       do Word — a primeira linha saindo à esquerda do resto do parágrafo.
#   [[pagina]]  sozinho na linha    quebra de página
#
# `[[par]]` é um marcador NOVO em vez de mais campos dentro de `[[alin]]`: há
# peças gravadas com `[[alin]]`, e dobrar o significado de um marcador em uso
# obriga a tela e o gerador a mudarem no mesmo instante, sob pena de uma peça
# antiga abrir errada. O espelho deste bloco está em
# `front/src/lib/formatacaoPeticao.ts` — os dois leitores andam juntos.
#
# As marcações não atravessam linhas: cada linha é interpretada sozinha. Marcação
# sem par é ignorada em vez de sair literal no documento entregue ao juízo.
_RE_MARCACAO = re.compile(r"\*\*|\[\[(/?)(i|u|s|tam|cor)(?:=([^\]\s]*))?\]\]")
_RE_ALINHAMENTO_LINHA = re.compile(r"^\s*\[\[alin=(esquerda|centro|direita|justificado)\]\]")
_RE_PARAGRAFO_LINHA = re.compile(r"^\s*\[\[par=([^\]]*)\]\]")
#: Quebra de página: a linha inteira é o marcador, e nada mais cabe nela.
_RE_QUEBRA_DE_PAGINA = re.compile(r"^\s*\[\[pagina\]\]\s*$")
_ALINHAMENTOS_DOCX = {"esquerda": "left", "centro": "center", "direita": "right", "justificado": "both"}
_RE_COR = re.compile(r"^#?[0-9a-fA-F]{6}$")
_TAMANHO_MIN_PT, _TAMANHO_MAX_PT = 6.0, 72.0

#: Os limites dos recuos e espaçamentos, iguais aos da tela.
_RECUO_MAX_CM, _RECUO_PRIMEIRA_MIN_CM = 10.0, -5.0


def _twips_de_cm(centimetros: float) -> int:
    return round(centimetros / 2.54 * 1440)


def _sem_alinhamento(linha: str) -> tuple[str | None, str]:
    """Separa o `[[alin=…]]` do começo da linha: (valor do docx ou None, resto)."""
    achado = _RE_ALINHAMENTO_LINHA.match(linha)
    if not achado:
        return None, linha
    return _ALINHAMENTOS_DOCX[achado.group(1)], linha[achado.end():]


def _sem_paragrafo(linha: str) -> tuple[dict[str, float], str]:
    """Separa o `[[par=…]]` do começo da linha: (medidas em cm/pt, resto)."""
    achado = _RE_PARAGRAFO_LINHA.match(linha)
    if not achado:
        return {}, linha
    limites = {
        "esq": (0.0, _RECUO_MAX_CM),
        "pri": (_RECUO_PRIMEIRA_MIN_CM, _RECUO_MAX_CM),
        "dir": (0.0, _RECUO_MAX_CM),
    }
    medidas: dict[str, float] = {}
    for par in achado.group(1).split(";"):
        chave, _, valor = par.partition(":")
        chave = chave.strip()
        if chave not in limites:
            continue
        try:
            numero = float(valor.strip())
        except ValueError:
            continue  # `[[par=esq:abc]]` não vale: a medida some, o texto fica.
        minimo, maximo = limites[chave]
        medidas[chave] = max(minimo, min(maximo, numero))
    return medidas, linha[achado.end():]


def _marcadores_de_linha(linha: str) -> tuple[str | None, dict[str, float], str]:
    """Tira do começo da linha tudo o que vale para o parágrafo inteiro.

    Em qualquer ordem e quantidade: o editor escreve `[[alin]]` e depois
    `[[par]]`, mas um texto vindo do chat ou de uma revisão da IA pode chegar na
    outra ordem, e o marcador não pode sair literal no documento.
    """
    alinhamento: str | None = None
    medidas: dict[str, float] = {}
    resto = linha
    while True:
        achado_alin, resto_alin = _sem_alinhamento(resto)
        if achado_alin is not None:
            alinhamento, resto = achado_alin, resto_alin
            continue
        achado_par, resto_par = _sem_paragrafo(resto)
        if resto_par != resto:
            medidas, resto = achado_par, resto_par
            continue
        return alinhamento, medidas, resto


def _ind_xml(medidas: dict[str, float], *, primeira_linha_zero: bool = False) -> str:
    """O `<w:ind>` de um parágrafo, a partir das medidas arrastadas na régua.

    `primeira_linha_zero` é o que os títulos, o fechamento e as linhas
    centralizadas já faziam: anular o recuo padrão da peça, que num texto
    centralizado empurraria tudo para a direita. Uma medida vinda da régua vence
    esse padrão — foi a pessoa que a arrastou, olhando a peça.
    """
    recuo = ""
    if "esq" in medidas:
        recuo += f'w:left="{_twips_de_cm(medidas["esq"])}" '
    if "dir" in medidas:
        recuo += f'w:right="{_twips_de_cm(medidas["dir"])}" '
    if "pri" in medidas:
        # Deslocamento (primeira linha à ESQUERDA do resto) é `w:hanging`, em
        # valor positivo: `w:firstLine` negativo o Word simplesmente ignora.
        twips = _twips_de_cm(medidas["pri"])
        recuo += f'w:hanging="{-twips}" ' if twips < 0 else f'w:firstLine="{twips}" '
    elif primeira_linha_zero:
        recuo += 'w:firstLine="0" '
    return f"<w:ind {recuo.strip()}/>" if recuo else ""


def _trechos_formatados(linha: str) -> list[tuple[str, dict[str, Any]]]:
    """Quebra uma linha (sem o `[[alin]]`) em trechos de texto com a formatação de cada um."""
    pedacos = list(_RE_MARCACAO.finditer(linha))
    # `**` sem par no fim da linha é texto, como sempre foi (o `re.split` antigo
    # também não o casava): tratá-lo como abertura de negrito apagaria o resto.
    negritos = [m for m in pedacos if m.group(0) == "**"]
    sem_par = negritos[-1] if len(negritos) % 2 else None

    negrito = italico = sublinhado = tachado = False
    tamanhos: list[float] = []
    cores: list[str] = []
    saida: list[tuple[str, dict[str, Any]]] = []

    def emitir(texto: str) -> None:
        if not texto:
            return
        formato = {
            "b": negrito,
            "i": italico,
            "u": sublinhado,
            "s": tachado,
            "tam": tamanhos[-1] if tamanhos else None,
            "cor": cores[-1] if cores else None,
        }
        if saida and saida[-1][1] == formato:
            saida[-1] = (saida[-1][0] + texto, formato)
        else:
            saida.append((texto, formato))

    posicao = 0
    for m in pedacos:
        emitir(linha[posicao:m.start()])
        posicao = m.end()
        if m.group(0) == "**":
            if m is sem_par:
                # Sem par: some, exatamente como o `.replace("**", "")` de antes.
                continue
            negrito = not negrito
            continue
        fechando, nome, valor = m.group(1) == "/", m.group(2), m.group(3)
        if nome == "i":
            italico = not fechando
        elif nome == "u":
            sublinhado = not fechando
        elif nome == "s":
            tachado = not fechando
        elif nome == "tam":
            if fechando:
                if tamanhos:
                    tamanhos.pop()
            else:
                try:
                    tamanhos.append(max(_TAMANHO_MIN_PT, min(_TAMANHO_MAX_PT, float(valor or ""))))
                except ValueError:
                    pass  # `[[tam=abc]]` não vale: a marcação some, o texto fica.
        elif nome == "cor":
            if fechando:
                if cores:
                    cores.pop()
            elif valor and _RE_COR.match(valor):
                cores.append(valor.lstrip("#").upper())
    emitir(linha[posicao:])
    return saida


def _sem_formatacao(texto: str) -> str:
    """O texto da linha sem marcação nenhuma — para detectar título."""
    _, _, resto = _marcadores_de_linha(texto)
    return "".join(pedaco for pedaco, _ in _trechos_formatados(resto))


def _runs_xml(
    trechos: list[tuple[str, dict[str, Any]]],
    *,
    negrito: bool = False,
    tamanho_pt: float | None = None,
    maiusculas: bool = False,
    italico: bool = False,
    cor: str | None = None,
    fonte: str | None = None,
) -> str:
    """Os `<w:r>` de uma linha. `negrito`/`italico`/`cor`/`fonte`/`tamanho_pt` vêm do ESTILO."""
    runs: list[str] = []
    for texto, formato in trechos:
        if maiusculas:
            texto = texto.upper()
        # Ordem do esquema (CT_RPr): b, i, strike, color, sz, szCs, u. O Word
        # tolera trocas, mas o LibreOffice e o validador não são obrigados a
        # tolerar.
        props = ""
        if fonte:
            nome_fonte = escape(fonte, {'"': "&quot;"})
            props += f'<w:rFonts w:ascii="{nome_fonte}" w:hAnsi="{nome_fonte}" w:cs="{nome_fonte}"/>'
        if negrito or formato["b"]:
            props += "<w:b/>"
        if italico or formato["i"]:
            props += "<w:i/>"
        if formato.get("s"):
            props += "<w:strike/>"
        if formato["cor"] or cor:
            props += f'<w:color w:val="{formato["cor"] or cor}"/>'
        tamanho = formato["tam"] or tamanho_pt
        if tamanho:
            meio_pontos = round(tamanho * 2)
            props += f'<w:sz w:val="{meio_pontos}"/><w:szCs w:val="{meio_pontos}"/>'
        if formato["u"]:
            props += '<w:u w:val="single"/>'
        abertura = f'<w:r>{f"<w:rPr>{props}</w:rPr>" if props else ""}'
        # A TABULAÇÃO é um elemento, não um caractere: dentro de um `<w:t>` o
        # Word a trata como espaço comum e o alinhamento que a pessoa montou na
        # tela se desfaz. Partir o texto nas tabulações e intercalar `<w:tab/>`
        # é o que faz a parada existir de verdade no documento.
        pedacos = escape(texto).split("\t")
        conteudo = '<w:tab/>'.join(
            f'<w:t xml:space="preserve">{pedaco}</w:t>' if pedaco else "" for pedaco in pedacos
        )
        runs.append(f"{abertura}{conteudo}</w:r>")
    return "".join(runs)


#: Marcação estrutural que o REDATOR usa e o motor apenas traduz em estilo. Quais
#: elementos existem (`titulo1`, `objeto`, `fechamento`...) e como cada um parece é
#: da SKILL (bloco ```estilo``` de `formatacao.md`); o motor não conhece nenhum nome.
_RE_TITULO_MD = re.compile(r"^\s*(#{1,6})\s+(.*\S)\s*$")
# O redator às vezes devolve "II. DO DIREITO" sem `#`. É título estrutural,
# não parágrafo de corpo; reconhecer isso no renderer garante o negrito que a
# skill definiu para `titulo1` mesmo quando a marcação Markdown foi omitida.
_RE_TITULO_ROMANO_RENDER = re.compile(r"^\s*[IVXLC]+[.\-–—)]\s+\S.{2,90}?\s*$", re.IGNORECASE)
_RE_ABRE_BLOCO = re.compile(r"^\s*:::\s*([\w-]+)\s*$")
_RE_FECHA_BLOCO = re.compile(r"^\s*:::\s*$")
_ALINHAMENTOS = {"esquerda": "left", "centro": "center", "centralizado": "center",
                 "direita": "right", "justificado": "both", "left": "left",
                 "center": "center", "right": "right", "both": "both"}


def _estilo_resolvido(visual: dict[str, Any], nome: str) -> dict[str, Any]:
    """`corpo` da skill + as propriedades do elemento `nome` (herança do corpo).

    Só junta o que a skill escreveu. Elemento que a skill não definiu (o redator usou um
    nome inexistente) cai no corpo, e o desvio vai para o log — nunca se inventa aparência.
    """
    estilos = visual.get("estilos") or {}
    resolvido: dict[str, Any] = {
        "tamanho_pt": visual.get("tamanho_fonte_pt"),
        "alinhamento": visual.get("alinhamento_corpo"),
        "espacamento_linha": visual.get("espacamento_linha"),
        "depois_pt": visual.get("espacamento_paragrafo_pt"),
        "recuo_primeira_linha_cm": visual.get("recuo_primeira_linha_cm"),
    }
    resolvido.update(estilos.get("corpo") or {})
    if nome != "corpo":
        if isinstance(estilos.get(nome), dict):
            resolvido.update(estilos[nome])
        else:
            log.warning("peticao: elemento '%s' não existe nos estilos da skill; usando corpo", nome)
    return resolvido


def _paragrafo_estilizado_xml(
    trechos: list[tuple[str, dict[str, Any]]],
    estilo: dict[str, Any],
    *,
    base: dict[str, Any],
    alinhamento_pedido: str | None = None,
    medidas: dict[str, float] | None = None,
) -> str:
    """Um `<w:p>` a partir de um estilo. Primitiva genérica: não sabe o que é petição.

    O `corpo` da skill mora em `docDefaults` (styles.xml); aqui só sai o que o estilo do
    elemento muda em relação a ele — o parágrafo comum sai sem `<w:pPr>`.
    """
    medidas = medidas or {}

    def muda(chave: str) -> bool:
        return chave in estilo and estilo.get(chave) != base.get(chave)

    propriedades = ""
    if estilo.get("manter_com_proxima"):
        propriedades += "<w:keepNext/>"
    cor_borda = str(estilo.get("borda_cor") or "").lstrip("#")
    if cor_borda:
        lado = f'w:val="single" w:sz="4" w:space="4" w:color="{cor_borda}"'
        propriedades += f"<w:pBdr><w:top {lado}/><w:left {lado}/><w:bottom {lado}/><w:right {lado}/></w:pBdr>"
    preenchimento = str(estilo.get("preenchimento") or "").lstrip("#")
    if preenchimento:
        propriedades += f'<w:shd w:val="clear" w:color="auto" w:fill="{preenchimento}"/>'
    if muda("espacamento_linha") or muda("antes_pt") or muda("depois_pt"):
        antes = round(float(estilo.get("antes_pt") or 0) * 20)
        depois = round(float(estilo.get("depois_pt") or 0) * 20)
        linha = float(estilo.get("espacamento_linha") or 1.0)
        propriedades += f'<w:spacing w:before="{antes}" w:after="{depois}" w:line="{round(linha * 240)}" w:lineRule="auto"/>'
    recuo = ""
    esquerdo = medidas.get("esq", estilo.get("recuo_esquerdo_cm"))
    direito = medidas.get("dir", estilo.get("recuo_direito_cm"))
    if esquerdo:
        recuo += f'w:left="{_twips_de_cm(float(esquerdo))}" '
    if direito:
        recuo += f'w:right="{_twips_de_cm(float(direito))}" '
    if "pri" in medidas or muda("recuo_primeira_linha_cm") or (
        alinhamento_pedido in ("center", "right") and base.get("recuo_primeira_linha_cm")
    ):
        primeira = medidas.get("pri", estilo.get("recuo_primeira_linha_cm") if muda("recuo_primeira_linha_cm") else 0)
        twips = _twips_de_cm(float(primeira or 0))
        recuo += f'w:hanging="{-twips}" ' if twips < 0 else f'w:firstLine="{twips}" '
    if recuo:
        propriedades += f"<w:ind {recuo.strip()}/>"
    alinhamento = alinhamento_pedido or (
        _ALINHAMENTOS.get(_normalizar_chave(str(estilo.get("alinhamento") or ""))) if muda("alinhamento") else None
    )
    if alinhamento:
        propriedades += f'<w:jc w:val="{alinhamento}"/>'
    runs = _runs_xml(
        trechos,
        negrito=bool(estilo.get("negrito")),
        italico=bool(estilo.get("italico")),
        tamanho_pt=estilo.get("tamanho_pt") if muda("tamanho_pt") else None,
        maiusculas=bool(estilo.get("caixa_alta")),
        cor=str(estilo.get("cor") or "").lstrip("#") or None,
        fonte=str(estilo.get("fonte") or "") or None,
    )
    return f"<w:p>{f'<w:pPr>{propriedades}</w:pPr>' if propriedades else ''}{runs}</w:p>"


def _normalizar_chave(valor: str) -> str:
    return valor.strip().lower()


def _paragrafo_xml(texto: str, *, visual: dict[str, Any] | None = None) -> str:
    """Traduz a marcação do redator em parágrafos, segundo os estilos da SKILL.

    `# ` a `###` → `titulo1..3`; `> ` → `blockquote`; `::: nome` … `:::` → bloco `nome`;
    o resto → `corpo`. Linha em branco separa parágrafos e NÃO gera parágrafo vazio
    (o respiro vem de `antes_pt`/`depois_pt` do estilo de cada bloco, não de linhas em branco),
    a menos que a skill peça `linhas_em_branco_entre_paragrafos`.

    O ritmo vertical nasce da TRANSIÇÃO entre blocos semânticos: cada tipo (corpo, título,
    citação) traz o próprio espaço da skill, e o Word soma o depois de um com o antes do
    seguinte. Linhas `>` consecutivas formam UM bloco de citação; uma linha em branco separa
    uma citação da outra.
    """
    visual = visual or {}
    base = _estilo_resolvido(visual, "corpo")
    partes: list[str] = []
    bloco: str | None = None
    citacao_acumulada: list[str] = []
    marcas_da_citacao: tuple[str | None, dict[str, float]] = (None, {})

    def emitir(nome: str, linha: str, alinhamento: str | None, medidas: dict[str, float]) -> None:
        trechos = _trechos_formatados(linha)
        if nome == "blockquote":
            # A citação é o que o documento diz: `**` da IA não vira destaque na transcrição.
            trechos = [(t, {**f, "b": False}) for t, f in trechos]
        partes.append(
            _paragrafo_estilizado_xml(
                trechos, _estilo_resolvido(visual, nome), base=base,
                alinhamento_pedido=alinhamento, medidas=medidas,
            )
        )

    def descarregar_citacao() -> None:
        nonlocal citacao_acumulada
        if citacao_acumulada:
            emitir("blockquote", " ".join(citacao_acumulada), *marcas_da_citacao)
            citacao_acumulada = []

    for linha_bruta in texto.split("\n"):
        if bloco is None:
            abre = _RE_ABRE_BLOCO.match(linha_bruta)
            if abre:
                descarregar_citacao()
                bloco = abre.group(1)
                continue
        elif _RE_FECHA_BLOCO.match(linha_bruta):
            bloco = None
            continue
        if not linha_bruta.strip():
            descarregar_citacao()
            if visual.get("linhas_em_branco_entre_paragrafos"):
                partes.append("<w:p/>")
            continue
        if _RE_QUEBRA_DE_PAGINA.match(linha_bruta):
            descarregar_citacao()
            partes.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
            continue
        alinhamento_pedido, medidas, linha = _marcadores_de_linha(linha_bruta)
        if not linha.strip():
            continue
        if bloco is not None:
            emitir(bloco, linha, alinhamento_pedido, medidas)
            continue
        if linha.strip() == ">":  # `>` sozinho separa duas citações
            descarregar_citacao()
            continue
        citacao = _RE_TRECHO.match(linha)
        if citacao:
            if not citacao_acumulada:
                marcas_da_citacao = (alinhamento_pedido, medidas)
            citacao_acumulada.append(citacao.group(1).strip())
            continue
        descarregar_citacao()
        titulo = _RE_TITULO_MD.match(linha)
        if titulo:
            emitir(f"titulo{min(len(titulo.group(1)), 3)}", titulo.group(2), alinhamento_pedido, medidas)
        elif _RE_TITULO_ROMANO_RENDER.match(linha):
            emitir("titulo1", linha.strip(), alinhamento_pedido, medidas)
        else:
            emitir("corpo", linha, alinhamento_pedido, medidas)
    descarregar_citacao()
    return "".join(partes)


# ------------------------------------------------------------------ fotos na peça
#
# A foto vive no TEXTO da seção, como uma linha `[[FOTO:<id do anexo>|legenda]]`.
# Assim ela passa por tudo o que já existe para texto sem caminho paralelo: versão,
# histórico, comparação antes × depois, edição manual (mover ou apagar a linha move ou
# apaga a foto) e peças anexas. Só `montar_docx` sabe que a linha é imagem.

#: Linha inteira de foto. O id é o da ENTREGA — é ele que acha o arquivo no acervo.
_RE_FOTO = re.compile(r"^\s*\[\[FOTO:([\w-]+)(?:\|([^\]]*))?\]\]\s*$")
_EXTENSOES_DE_FOTO = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif")
#: Foto de celular chega com 4000 px e 5 MB; numa peça, 1600 px bastam e o .docx
#: continua anexável no PJe.
_LADO_MAXIMO_PX = 1600
#: Uma foto de pé não pode ocupar a página inteira e empurrar o texto para a próxima.
_ALTURA_MAXIMA_FOTO_CM = 12.0


def eh_foto(arquivo: str) -> bool:
    return Path(str(arquivo or "")).suffix.lower() in _EXTENSOES_DE_FOTO


def marcador_de_foto(anexo_id: str, legenda: str = "") -> str:
    # `]` e `|` fechariam o marcador antes da hora e a legenda sairia cortada.
    legenda = " ".join(str(legenda or "").replace("]", ")").replace("|", "/").split())
    return f"[[FOTO:{anexo_id}|{legenda}]]" if legenda else f"[[FOTO:{anexo_id}]]"


def _marcadores_de_foto(conteudo: Any) -> list[str]:
    return [linha.strip() for linha in str(conteudo or "").split("\n") if _RE_FOTO.match(linha)]


def preparar_foto(anexo_id: str) -> tuple[bytes, int, int] | None:
    """A foto como JPEG pronto para o Word: `(bytes, largura_px, altura_px)`.

    Gira pelo EXIF antes de tudo: foto de celular vem "deitada" no arquivo com a
    rotação só anotada, e o Word não lê essa anotação — o machucado sairia de lado.
    Transparência vira fundo branco e o lado maior cai para 1600 px. `None` quando
    o anexo não existe ou não abre como imagem (PDF, HEIC sem decodificador).
    """
    entrega = armazenamento.obter_entrega(anexo_id)
    if not entrega:
        return None
    caminho = armazenamento.caminho_duravel_da_entrega(anexo_id)
    bruto = caminho.read_bytes() if caminho else armazenamento.conteudo_arquivo_entrega(entrega)
    if not bruto:
        return None
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(bruto)) as original:
            imagem = ImageOps.exif_transpose(original)
            if imagem.mode not in ("RGB", "L"):
                rgba = imagem.convert("RGBA")
                imagem = Image.new("RGB", rgba.size, "white")
                imagem.paste(rgba, mask=rgba.getchannel("A"))
            imagem = imagem.convert("RGB")
            imagem.thumbnail((_LADO_MAXIMO_PX, _LADO_MAXIMO_PX))
            saida = io.BytesIO()
            imagem.save(saida, "JPEG", quality=85)
            return saida.getvalue(), imagem.width, imagem.height
    except Exception as erro:  # noqa: BLE001 — anexo ilegível vira pendência na peça
        log.warning("foto %s não abriu como imagem: %s", anexo_id, erro)
        return None


def _largura_util_cm(visual: dict[str, Any]) -> float:
    esquerda = max(1, min(6, float(visual["margem_esquerda_cm"])))
    direita = max(1, min(6, float(visual["margem_direita_cm"])))
    return 21.0 - esquerda - direita


def _foto_xml(linha: str, *, fotos: list[tuple[str, bytes]], visual: dict[str, Any]) -> str:
    """A foto centralizada, com a legenda em itálico logo abaixo.

    `fotos` acumula `(rId, jpeg)` para `montar_docx` gravar em `word/media`.
    """
    achado = _RE_FOTO.match(linha)
    anexo_id, legenda = achado.group(1), (achado.group(2) or "").strip()
    sem_recuo = '<w:ind w:firstLine="0"/>'
    foto = preparar_foto(anexo_id)
    if foto is None:
        # Nunca some em silêncio: o advogado precisa ver que ali faltou a foto.
        aviso = escape(f"[PENDENTE: foto não encontrada nos anexos{' — ' + legenda if legenda else ''}]")
        return (
            f'<w:p><w:pPr>{sem_recuo}<w:jc w:val="center"/></w:pPr>'
            f'<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">{aviso}</w:t></w:r></w:p>'
        )
    jpeg, largura_px, altura_px = foto
    # Não amplia além de ~150 dpi: foto pequena esticada até a margem fica borrada.
    largura_cm = min(_largura_util_cm(visual), largura_px / 150 * 2.54)
    altura_cm = largura_cm * altura_px / largura_px
    if altura_cm > _ALTURA_MAXIMA_FOTO_CM:
        altura_cm = _ALTURA_MAXIMA_FOTO_CM
        largura_cm = altura_cm * largura_px / altura_px
    cx, cy = round(largura_cm * 360000), round(altura_cm * 360000)
    numero = len(fotos) + 1
    rel_id = f"rIdFoto{numero}"
    fotos.append((rel_id, jpeg))
    # id 1 é a logo do cabeçalho; as fotos começam em 100 para nunca colidir.
    doc_id = 100 + numero
    nome = escape(legenda or f"Foto {numero}", {'"': "&quot;"})
    xml = (
        f'<w:p><w:pPr><w:keepNext/>{sem_recuo}<w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
        f'<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{doc_id}" name="{nome}"/>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{doc_id}" name="foto-{numero}.jpeg"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{rel_id}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
        "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
    )
    if legenda:
        xml += (
            f'<w:p><w:pPr>{sem_recuo}<w:jc w:val="center"/></w:pPr>'
            f'<w:r><w:rPr><w:i/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr>'
            f'<w:t xml:space="preserve">{escape(legenda)}</w:t></w:r></w:p>'
        )
    return xml


def _preservar_fotos(
    antes: list[dict[str, Any]], depois: list[dict[str, Any]], critica: str
) -> list[dict[str, Any]]:
    """Devolve à revisão as fotos que a IA deixou cair.

    O modelo reescreve a seção inteira e trata `[[FOTO:…]]` como ruído; sem isto,
    pedir "melhore os fatos" apagava a foto do machucado. Se a crítica fala de foto
    ou imagem, quem decide é ela (tirar ou mover é pedido legítimo).
    """
    if re.search(r"\b(fotos?|imagens?|figuras?)\b", critica or "", re.IGNORECASE):
        return depois
    resultado = [dict(s) for s in depois]
    if not resultado:
        return resultado
    presentes = {m for s in resultado for m in _marcadores_de_foto(s.get("content"))}
    por_codigo = {s.get("code"): s for s in resultado}
    for secao in antes:
        faltando = [m for m in _marcadores_de_foto(secao.get("content")) if m not in presentes]
        if not faltando:
            continue
        destino = por_codigo.get(secao.get("code")) or resultado[-1]
        destino["content"] = str(destino.get("content") or "").rstrip() + "\n\n" + "\n".join(faltando)
        presentes.update(faltando)
    return resultado


def _preservar_citacoes(
    antes: list[dict[str, Any]], depois: list[dict[str, Any]], critica: str
) -> list[dict[str, Any]]:
    """Devolve à revisão as citações literais de documento que a IA parafraseou ou deixou cair.

    Mesma ideia das fotos: o modelo reescreve a seção inteira e trata `> …` como texto
    seu. Citação alterada deixa de ser citação — e ninguém percebe, porque parece igual.
    Se a crítica fala de citação/trecho, quem decide é ela.
    """
    if re.search(r"\b(cita[çc][ãa]o|cita[çc][õo]es|trechos?|transcri[çc][ãa]o|transcri[çc][õo]es)\b", critica or "", re.IGNORECASE):
        return depois
    resultado = [dict(s) for s in depois]
    if not resultado:
        return resultado

    def citacoes(conteudo: Any) -> list[str]:
        return [linha.strip() for linha in str(conteudo or "").split("\n") if _RE_TRECHO.match(linha)]

    presentes = {c for s in resultado for c in citacoes(s.get("content"))}
    por_codigo = {s.get("code"): s for s in resultado}
    for secao in antes:
        faltando = [c for c in citacoes(secao.get("content")) if c not in presentes]
        if not faltando:
            continue
        destino = por_codigo.get(secao.get("code")) or resultado[-1]
        destino["content"] = str(destino.get("content") or "").rstrip() + "\n\n" + "\n\n".join(faltando)
        presentes.update(faltando)
    return resultado


def _achar_secao(secoes: list[dict[str, Any]], secao: str) -> dict[str, Any]:
    """Pelo código ("FACTS") ou pelo rótulo ("Dos fatos"); vazio = última seção."""
    procurado = _sem_acento(secao).strip().lower()
    if procurado:
        for candidata in secoes:
            codigo = str(candidata.get("code") or "").lower()
            rotulo = _sem_acento(str(candidata.get("label") or "")).lower()
            if procurado in (codigo, rotulo) or (len(procurado) >= 4 and procurado in rotulo):
                return candidata
        raise ErroPeticao(
            f"Não achei a seção «{secao}» na petição. Seções: "
            + "; ".join(_nome_da_secao(s) for s in secoes)
        )
    return secoes[-1]


def inserir_foto(
    caso_id: str,
    anexo_id: str,
    *,
    secao: str = "",
    depois_de: str = "",
    legenda: str = "",
    usuario: str = "",
) -> dict[str, Any]:
    """Põe uma foto do caso dentro da petição, sem IA no meio.

    `secao` vazio = fim da petição (última seção). `depois_de` é um trecho do texto:
    a foto entra logo abaixo do parágrafo que o contém; sem ele, no fim da seção.
    Vira edição manual comum — versão nova, histórico, desfazível.
    """
    dados = carregar(caso_id)
    if not dados:
        raise ErroPeticao("Nenhuma petição gerada para este caso.")
    entrega = armazenamento.obter_entrega(anexo_id)
    if not entrega or str(entrega.get("caso_id")) != str(caso_id):
        raise ErroPeticao("Esse anexo não é deste caso.")
    arquivo = str(entrega.get("arquivo") or "")
    if not eh_foto(arquivo):
        raise ErroPeticao(f"«{arquivo}» não é uma foto (jpg, png…).")
    if preparar_foto(anexo_id) is None:
        raise ErroPeticao(f"Não consegui abrir «{arquivo}» como imagem.")

    secoes = [s for s in dados.get("sections") or [] if s.get("code") != "JURIMETRY"]
    if not secoes:
        raise ErroPeticao("A petição não tem seções.")
    alvo = _achar_secao(secoes, secao)
    marcador = marcador_de_foto(anexo_id, legenda)
    linhas = str(alvo.get("content") or "").rstrip().split("\n")
    posicao = "no fim da seção"
    trecho = _sem_acento(" ".join(depois_de.split())).lower()
    indice = next(
        (i for i, linha in enumerate(linhas) if trecho and trecho in _sem_acento(" ".join(linha.split())).lower()),
        None,
    )
    if indice is not None:
        linhas[indice + 1:indice + 1] = ["", marcador, ""]
        posicao = "logo abaixo do parágrafo indicado"
    else:
        if depois_de.strip():
            posicao = "no fim da seção (não achei o trecho indicado)"
        linhas += ["", marcador]
    conteudo = "\n".join(linhas)
    peticao = salvar_secoes(caso_id, [{"code": str(alvo.get("code")), "content": conteudo}], usuario)
    return {
        "peticao": peticao,
        "secao": _nome_da_secao(alvo),
        "posicao": posicao,
        "arquivo": arquivo,
    }


#: Teto de um trecho citado: acima disso é transcrever o documento, não citá-lo.
LIMITE_TRECHO = 1500


def _compacto(texto: str) -> str:
    """Sem acento, sem caixa e com espaço/quebra de linha colapsados: a base da conferência
    de um trecho contra o texto que o OCR leu (que quebra linha no meio da frase)."""
    return " ".join(_sem_acento(str(texto or "")).lower().split())


def trecho_esta_no_documento(texto_do_documento: str, trecho: str) -> bool:
    """`True` só quando o trecho aparece, palavra por palavra, no texto lido do documento.

    A citação vai para uma peça entregue ao juízo: um trecho «de memória», mesmo quase
    igual, é citação falsa. Espaço e acento não contam; palavra trocada conta.
    """
    alvo = _compacto(trecho)
    return len(alvo) >= 8 and alvo in _compacto(texto_do_documento)


def inserir_trecho(
    caso_id: str,
    anexo_id: str,
    trecho: str,
    *,
    secao: str = "",
    depois_de: str = "",
    usuario: str = "",
) -> dict[str, Any]:
    """Põe um trecho LITERAL de um documento do caso dentro da petição, sem IA no meio.

    Entra como citação (`> trecho (Fonte: tipo — arquivo)`), com a fonte ao lado. Recusa
    o que não está no texto lido do documento. Vira edição manual comum: versão nova,
    histórico, desfazível.
    """
    trecho = " ".join(str(trecho or "").split())
    if not trecho:
        raise ErroPeticao("Diga qual trecho do documento deve entrar na petição.")
    if len(trecho) > LIMITE_TRECHO:
        raise ErroPeticao(
            f"O trecho tem {len(trecho)} caracteres; o máximo é {LIMITE_TRECHO}. Cite só a passagem que interessa."
        )
    dados = carregar(caso_id)
    if not dados:
        raise ErroPeticao("Nenhuma petição gerada para este caso.")
    anexo = next((a for a in anexos_do_caso(caso_id) if a["id"] == str(anexo_id)), None)
    if not anexo:
        raise ErroPeticao("Esse anexo não é deste caso.")
    if not trecho_esta_no_documento(anexo["texto"], trecho):
        raise ErroPeticao(
            f"Esse trecho não aparece no texto lido de «{anexo['arquivo']}». Só entra na petição"
            " o que o documento diz, palavra por palavra."
        )
    secoes = [s for s in dados.get("sections") or [] if s.get("code") != "JURIMETRY"]
    if not secoes:
        raise ErroPeticao("A petição não tem seções.")
    alvo = _achar_secao(secoes, secao)
    fonte = f"{anexo['tipo']} — {anexo['arquivo']}" if anexo["tipo"] else anexo["arquivo"]
    citacao = f"> {trecho} (Fonte: {fonte})"
    linhas = str(alvo.get("content") or "").rstrip().split("\n")
    posicao = "no fim da seção"
    procurado = _compacto(depois_de)
    indice = next((i for i, linha in enumerate(linhas) if procurado and procurado in _compacto(linha)), None)
    if indice is not None:
        linhas[indice + 1:indice + 1] = ["", citacao, ""]
        posicao = "logo abaixo do parágrafo indicado"
    else:
        if depois_de.strip():
            posicao = "no fim da seção (não achei o trecho indicado)"
        linhas += ["", citacao]
    peticao = salvar_secoes(caso_id, [{"code": str(alvo.get("code")), "content": "\n".join(linhas)}], usuario)
    return {
        "peticao": peticao,
        "secao": _nome_da_secao(alvo),
        "posicao": posicao,
        "arquivo": anexo["arquivo"],
    }


_RE_SEPARADOR_TABELA = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _celulas_tabela_markdown(linha: str) -> list[str]:
    """Lê uma linha de tabela Markdown sem deixar ``|`` virar texto no Word."""
    limpa = linha.strip()
    if limpa.startswith("|"):
        limpa = limpa[1:]
    if limpa.endswith("|"):
        limpa = limpa[:-1]
    return [celula.strip() for celula in limpa.split("|")]


#: Área útil de uma A4 com margens de 3 cm e 2 cm, quando a configuração visual não chega.
LARGURA_TABELA_PADRAO = 9070
#: Nenhuma coluna fica mais estreita que isto (≈1,6 cm), nem a de um código curto.
LARGURA_MINIMA_COLUNA = 900
#: Acima disto o texto quebra de qualquer jeito; não adianta a coluna crescer mais.
_TETO_CARACTERES_COLUNA = 70


def _larguras_das_colunas(cabecalho: list[str], linhas: list[list[str]], largura_total: int) -> list[int]:
    """Colunas proporcionais ao texto que carregam: a coluna da conta ganha espaço e a do código, não."""
    colunas = len(cabecalho)
    pesos = []
    for i in range(colunas):
        textos = [cabecalho[i], *(linha[i] for linha in linhas)]
        maior = max((len(parte) for t in textos for parte in str(t or "").split("\n")), default=0)
        pesos.append(max(6, min(_TETO_CARACTERES_COLUNA, maior)))
    minimo = min(LARGURA_MINIMA_COLUNA, largura_total // colunas)
    livre = largura_total - minimo * colunas
    larguras = [minimo + int(livre * p / sum(pesos)) for p in pesos]
    larguras[pesos.index(max(pesos))] += largura_total - sum(larguras)
    return larguras


def _tabela_xml(cabecalho: list[str], linhas: list[list[str]], *, largura_total: int | None = None) -> str:
    """Uma tabela Word nativa, com bordas e expansão automática de linhas.

    O conteúdo chega da IA em Markdown somente como uma representação transitória.
    O DOCX final recebe ``w:tbl`` editável, nunca barras, tabs ou imagem.

    Compacta de propósito: ocupa a largura útil da página, com colunas proporcionais ao
    conteúdo, fonte menor que a do corpo e linha simples — sem herdar o espaçamento de
    1,5 e o recuo de parágrafo da peça, que deixavam cada linha da memória de cálculo alta.
    """
    colunas = max(2, len(cabecalho), *(len(linha) for linha in linhas))
    cabecalho = (cabecalho + [""] * colunas)[:colunas]
    linhas = [(linha + [""] * colunas)[:colunas] for linha in linhas]
    largura_total = largura_total or LARGURA_TABELA_PADRAO
    larguras = _larguras_das_colunas(cabecalho, linhas, largura_total)
    tamanho = 20 if colunas <= 3 else 18

    def celula(texto: str, largura: int, *, destaque: bool = False) -> str:
        # A célula é texto simples: formatação de trecho feita na tela sobre uma
        # linha de tabela não pode sair literal (`[[i]]`) dentro da grade.
        texto = "\n".join(_sem_formatacao(parte) for parte in str(texto or "").split("\n"))
        partes = texto.split("\n") or [""]
        rpr = f'<w:rPr>{"<w:b/>" if destaque else ""}<w:sz w:val="{tamanho}"/><w:szCs w:val="{tamanho}"/></w:rPr>'
        runs = "".join(
            f'<w:r>{rpr}<w:t xml:space="preserve">{escape(parte)}</w:t></w:r>'
            + ("<w:r><w:br/></w:r>" if indice < len(partes) - 1 else "")
            for indice, parte in enumerate(partes)
        )
        alinhamento = "right" if not destaque and re.fullmatch(r"R\$\s*[\d.]+,\d{2}", texto.strip()) else "left"
        return (
            f'<w:tc><w:tcPr><w:tcW w:w="{largura}" w:type="dxa"/>'
            '<w:vAlign w:val="center"/></w:tcPr>'
            f'<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
            f'<w:ind w:left="0" w:right="0" w:firstLine="0"/><w:jc w:val="{alinhamento}"/></w:pPr>{runs}</w:p></w:tc>'
        )

    def linha(valores: list[str], *, destaque: bool = False) -> str:
        return ("<w:tr><w:trPr><w:tblHeader/></w:trPr>" if destaque else "<w:tr>") + "".join(
            celula(valor, larguras[indice], destaque=destaque)
            for indice, valor in enumerate(valores)
        ) + "</w:tr>"

    return (
        f'<w:tbl><w:tblPr><w:tblW w:w="{largura_total}" w:type="dxa"/><w:jc w:val="center"/>'
        '<w:tblLayout w:type="fixed"/>'
        '<w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="000000"/></w:tblBorders>'
        '<w:tblCellMar><w:top w:w="15" w:type="dxa"/><w:left w:w="60" w:type="dxa"/>'
        '<w:bottom w:w="15" w:type="dxa"/><w:right w:w="60" w:type="dxa"/></w:tblCellMar>'
        '</w:tblPr><w:tblGrid>'
        + "".join(f'<w:gridCol w:w="{largura}"/>' for largura in larguras)
        + "</w:tblGrid>"
        + linha(cabecalho, destaque=True)
        + "".join(linha(valores) for valores in linhas)
        + "</w:tbl>"
    )


def _largura_da_tabela(visual: dict[str, Any]) -> int:
    try:
        return _twips_de_cm(_largura_util_cm(visual))
    except (KeyError, TypeError, ValueError):
        return LARGURA_TABELA_PADRAO


def _conteudo_com_tabelas_xml(
    conteudo: str,
    *,
    visual: dict[str, Any],
    fotos: list[tuple[str, bytes]] | None = None,
) -> str:
    """Converte blocos Markdown de tabela (e linhas de foto), mantendo a posição."""
    # Linha de tabela ou de foto pode ter ganhado um `[[alin=…]]` ou um
    # `[[par=…]]` na tela; o marcador não pode esconder a `|` nem o `[[FOTO:…]]`
    # do reconhecimento. As linhas comuns seguem com os marcadores, que
    # `_paragrafo_xml` sabe ler.
    def _sem_marcadores(linha: str) -> str:
        sem = _marcadores_de_linha(linha)[2].lstrip()
        return sem if ("|" in sem or "[[FOTO:" in sem) else linha

    linhas = [_sem_marcadores(linha) for linha in conteudo.split("\n")]
    partes: list[str] = []
    comum: list[str] = []

    def descarregar_comum() -> None:
        nonlocal comum
        if comum:
            partes.append(_paragrafo_xml("\n".join(comum), visual=visual))
            comum = []

    indice = 0
    while indice < len(linhas):
        atual = linhas[indice]
        proxima = linhas[indice + 1] if indice + 1 < len(linhas) else ""
        if fotos is not None and _RE_FOTO.match(atual):
            descarregar_comum()
            partes.append(_foto_xml(atual, fotos=fotos, visual=visual))
            indice += 1
            continue
        if "|" in atual and _RE_SEPARADOR_TABELA.match(proxima):
            cabecalho = _celulas_tabela_markdown(atual)
            tabela: list[list[str]] = []
            indice += 2
            while indice < len(linhas) and "|" in linhas[indice] and linhas[indice].strip():
                tabela.append(_celulas_tabela_markdown(linhas[indice]))
                indice += 1
            if len(cabecalho) >= 2 and tabela:
                descarregar_comum()
                partes.append(_tabela_xml(cabecalho, tabela, largura_total=_largura_da_tabela(visual)))
                partes.append("<w:p/>")
                continue
            comum.extend([atual, proxima])
            continue
        comum.append(atual)
        indice += 1
    descarregar_comum()
    return "".join(partes)


def _rodape_xml(visual: dict[str, Any]) -> str:
    """Rodapé a partir do estilo `rodape` da skill: `formato` com {pagina} e {total}.

    Sem `rodape.formato` na skill o rodapé sai vazio — o motor não inventa paginação.
    """
    estilo = (visual.get("estilos") or {}).get("rodape") or {}
    formato = str(estilo.get("formato") or "")
    alinhamento = _ALINHAMENTOS.get(_normalizar_chave(str(estilo.get("alinhamento") or "")), "left")
    tamanho = float(estilo.get("tamanho_pt") or visual.get("tamanho_fonte_pt") or 10)
    tamanho_numero = float(estilo.get("tamanho_numero_pt") or tamanho)

    def run(conteudo: str, pt: float) -> str:
        meio = round(pt * 2)
        return f'<w:r><w:rPr><w:sz w:val="{meio}"/><w:szCs w:val="{meio}"/></w:rPr>{conteudo}</w:r>'

    def campo(instrucao: str) -> str:
        return (
            run('<w:fldChar w:fldCharType="begin"/>', tamanho_numero)
            + run(f'<w:instrText xml:space="preserve"> {instrucao} </w:instrText>', tamanho_numero)
            + run('<w:fldChar w:fldCharType="separate"/>', tamanho_numero)
            + run("<w:t>1</w:t>", tamanho_numero)
            + run('<w:fldChar w:fldCharType="end"/>', tamanho_numero)
        )

    corpo = ""
    if formato:
        for pedaco in re.split(r"(\{pagina\}|\{total\})", formato):
            if pedaco == "{pagina}":
                corpo += campo("PAGE")
            elif pedaco == "{total}":
                corpo += campo("NUMPAGES")
            elif pedaco:
                corpo += run(f'<w:t xml:space="preserve">{escape(pedaco)}</w:t>', tamanho)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:p><w:pPr><w:jc w:val="{alinhamento}"/><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
        f'<w:ind w:firstLine="0"/></w:pPr>{corpo}</w:p></w:ftr>'
    )


def montar_docx(secoes: list[dict[str, Any]]) -> bytes:
    # Usa a mesma representação já conferida pelo FINAL_DOCUMENT_VALIDATOR. Assim
    # o DOCX não introduz limpeza estrutural que o editor/validador não enxergaram.
    secoes = documento_final.preparar_para_renderizacao(
        secoes, peticao_skill_arquivos.validacoes_da_skill()["parametros"], preservar_marcadores=True,
    )
    logo, fonte, logo_extensao, _origem_visual = identidade_visual()
    visual = configuracao_visual()
    fonte = str(visual.get("fonte") or fonte).strip() or fonte
    fonte_xml = escape(fonte, {'"': "&quot;"})
    def twips(cm: float) -> int:
        return round(cm / 2.54 * 1440)
    tamanho = max(8, min(24, float(visual["tamanho_fonte_pt"])))
    entrelinha = max(1, min(3, float(visual["espacamento_linha"])))
    recuo = max(0, min(5, float(visual["recuo_primeira_linha_cm"])))
    margem_topo = max(1.5, min(7, float(visual["margem_superior_cm"])))
    margem_direita = max(1, min(6, float(visual["margem_direita_cm"])))
    margem_inferior = max(1, min(6, float(visual["margem_inferior_cm"])))
    margem_esquerda = max(1, min(6, float(visual["margem_esquerda_cm"])))
    altura_logo = max(0.5, min(5, float(visual.get("altura_logo_cm") or 2.36)))
    logo_cy = round(altura_logo * 360000)
    logo_cx = round(logo_cy * 1.774)
    corpo_estilo = _estilo_resolvido(visual, "corpo")
    alinhamento_corpo = {"justificado": "both", "esquerda": "left", "direita": "right"}.get(str(visual.get("alinhamento_corpo")), "both")
    logo_arquivo = f"logo-escritorio{logo_extensao}"
    logo_content_type = "image/jpeg" if logo_extensao == ".jpg" else "image/png"
    corpo: list[str] = []
    fotos: list[tuple[str, bytes]] = []
    for secao in secoes:
        if secao.get("code") == "JURIMETRY":
            continue
        rotulo = str(secao.get("label") or "").strip()
        conteudo = str(secao.get("content") or "").strip()
        # VALUE entra junto de HEADING e CLOSING: o valor da causa NÃO tem título
        # na peça do escritório — é uma frase solta ("Dá-se à causa o valor de
        # ..."). O rótulo continua existindo em `SECOES` porque a tela e o prompt
        # se orientam por ele; só não vira parágrafo no .docx.
        # O título da seção é o `label` do redator (vazio se a skill não dá título). Só se omite quando o
        # conteúdo já abre com um título de NÍVEL 1 (ou bloco nomeado) — um `##`/`###` é SUBcapítulo, e tratá-lo
        # como "o título da seção" fazia o capítulo (ex.: "V. Do Direito") sumir e a numeração pular.
        if petition_linter.deve_imprimir_rotulo(rotulo, conteudo):
            corpo.append(_paragrafo_xml(f"# {rotulo}", visual=visual))
        if conteudo:
            corpo.append(_conteudo_com_tabelas_xml(conteudo, visual=visual, fotos=fotos))
        if visual.get("linhas_em_branco_entre_paragrafos"):
            corpo.append("<w:p/>")

    documento_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <w:body>
    {"".join(corpo)}
    <w:sectPr>
      <w:headerReference w:type="default" r:id="rIdHeader"/>
      <w:footerReference w:type="default" r:id="rIdFooter"/>
      <w:pgSz w:w="11906" w:h="16838"/>
      <!-- Medido na petição de referência do escritório, página a página (as
           quatro primeiras dão exatamente o mesmo recorte):

             esquerda  3,00 cm = 1701 twips
             direita   1,89 cm = 1069 twips
             rodapé    1,25 cm =  708 twips
             header    1,25 cm =  708 twips  (onde o timbre começa)
             topo      4,66 cm = 2642 twips  (onde o TEXTO começava)

           `w:top` é onde o corpo começa, não a borda do papel: entre 1,25 cm e
           `w:top` fica a logo, que é cabeçalho e se repete em toda página. Com
           `w:top` menor que isso o texto subiria por cima do timbre.

           Com a logo reduzida a 2,36 cm de altura, o timbre acaba em 3,61 cm.
           Mantendo a mesma folga de 0,13 cm da peça de referência, o texto passa
           a começar em 3,74 cm = 2120 twips. Sem descer `w:top` junto sobraria
           quase 1 cm de ar entre a logo e o primeiro parágrafo. -->
      <w:pgMar w:top="{twips(margem_topo)}" w:right="{twips(margem_direita)}" w:bottom="{twips(margem_inferior)}" w:left="{twips(margem_esquerda)}" w:header="708" w:footer="708"/>
    </w:sectPr>
  </w:body>
</w:document>"""

    # f-string: sem o `f`, `{logo_cx}` ia literal para o XML e o Word recusava abrir
    # o arquivo inteiro (o LibreOffice, que gera o PDF, tolerava e escondia o defeito).
    # Paginação contínua "Página X de Y", discreta e sem cobrir o texto — exigida por
    # `formatacao.md` (item 4). Campos PAGE/NUMPAGES: o Word e o LibreOffice
    # recalculam ao abrir. Tamanho de nota (10 pt), como a skill define para
    # elementos secundários.
    rodape_xml = _rodape_xml(visual)
    cabecalho_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <!-- A logo já era centralizada, mas na ÁREA ÚTIL — e as margens são
       assimétricas (3,00 cm à esquerda, 1,89 cm à direita, medidas na peça de
       referência). O centro da área útil cai 0,55 cm à direita do centro da
       FOLHA, e é isso que se vê como logo fora do meio.

       `w:right="629"` (1,11 cm, a diferença entre as margens) devolve o
       parágrafo ao centro do papel, que é onde o olho espera o timbre. -->
  <w:p><w:pPr><w:jc w:val="center"/><w:ind w:right="{twips(margem_esquerda - margem_direita)}"/></w:pPr><w:r><w:drawing>
    <wp:inline distT="0" distB="0" distL="0" distR="0">
      <!-- 4,19 × 2,36 cm em EMU (1 cm = 360000). O timbre da peça de referência
           tem 5,82 × 3,28 cm; este é ele a 72%, por pedido do escritório. Os dois
           lados usam o mesmo fator, então a proporção 1,77 se mantém e a imagem
           encolhe sem distorcer. Mexer aqui obriga a mexer no `w:top` do sectPr. -->
      <wp:extent cx="{logo_cx}" cy="{logo_cy}"/><wp:docPr id="1" name="Logo do escritório"/>
      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
        <pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="logo-escritorio"/><pic:cNvPicPr/></pic:nvPicPr>
          <pic:blipFill><a:blip r:embed="rIdLogo"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
          <pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{logo_cx}" cy="{logo_cy}"/></a:xfrm>
            <a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
        </pic:pic>
      </a:graphicData></a:graphic>
    </wp:inline>
  </w:drawing></w:r></w:p>
</w:hdr>"""

    estilos_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault><w:rPr>
      <w:rFonts w:ascii="{fonte_xml}" w:hAnsi="{fonte_xml}" w:eastAsia="{fonte_xml}" w:cs="{fonte_xml}"/>
      <w:sz w:val="{round(tamanho * 2)}"/><w:szCs w:val="{round(tamanho * 2)}"/><w:lang w:val="pt-BR"/>
    </w:rPr></w:rPrDefault>
    <!-- `firstLine="709"` = 1,25 cm de recuo na primeira linha de cada parágrafo.
         Medido na petição de referência: o corpo começa em 3,0 cm e a primeira
         linha de cada parágrafo em 4,25 cm — 20 linhas do documento confirmam
         essa segunda coluna. Sem isso o texto sai em bloco corrido, que foi a
         diferença apontada ao comparar a peça gerada com a do escritório. -->
    <w:pPrDefault><w:pPr><w:jc w:val="{alinhamento_corpo}"/><w:spacing w:before="{round(float(corpo_estilo.get("antes_pt") or 0) * 20)}" w:after="{round(float(corpo_estilo.get("depois_pt") or 0) * 20)}" w:line="{round(entrelinha * 240)}" w:lineRule="auto"/><w:ind w:firstLine="{twips(recuo)}"/></w:pPr></w:pPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
</w:styles>"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as arquivo:
        arquivo.writestr(
            "[Content_Types].xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="{logo_extensao.lstrip('.')}" ContentType="{logo_content_type}"/>
  {'<Default Extension="jpeg" ContentType="image/jpeg"/>' if fotos else ""}
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
  <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>""",
        )
        arquivo.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
        )
        arquivo.writestr("word/document.xml", documento_xml)
        arquivo.writestr("word/header1.xml", cabecalho_xml)
        arquivo.writestr("word/footer1.xml", rodape_xml)
        arquivo.writestr("word/styles.xml", estilos_xml)
        arquivo.writestr(f"word/media/{logo_arquivo}", logo)
        # `.jpeg`, e não `.jpg`: a logo pode ser `.jpg`, e dois <Default> para a
        # mesma extensão tornam o pacote inválido para o Word.
        relacoes_fotos = ""
        for rel_id, jpeg in fotos:
            numero = rel_id.removeprefix("rIdFoto")
            arquivo.writestr(f"word/media/foto-{numero}.jpeg", jpeg)
            relacoes_fotos += (
                f'\n  <Relationship Id="{rel_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/foto-{numero}.jpeg"/>'
            )
        arquivo.writestr(
            "word/_rels/document.xml.rels",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdHeader" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
  <Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
  <Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>{relacoes_fotos}
</Relationships>""",
        )
        arquivo.writestr(
            "word/_rels/header1.xml.rels",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdLogo" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{logo_arquivo}"/>
</Relationships>""",
        )
    return buffer.getvalue()


@skill_peticao.com_skill_do_caso
def ler_docx(caso_id: str) -> bytes:
    dados = armazenamento.obter_peticao_local(caso_id)
    if not dados:
        raise ErroPeticao("Petição não encontrada.")
    conteudo = bytes(dados.get("_docx") or b"")
    if int(dados.get("docx_style_version") or 0) < DOCX_STYLE_VERSION:
        return montar_docx(dados.get("sections") or [])
    return conteudo or montar_docx(dados.get("sections") or [])


@skill_peticao.com_skill_do_caso
def ler_pdf(caso_id: str) -> bytes:
    from . import docx_pdf

    try:
        return docx_pdf.converter(ler_docx(caso_id))
    except docx_pdf.ErroConversaoDocx as erro:
        raise ErroPeticao(str(erro)) from erro
