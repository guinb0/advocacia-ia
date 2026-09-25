"""DOCUMENT_LEDGER — documento LÓGICO × arquivo FÍSICO, com identificador canônico único.

O PROBLEMA (v11)

A peça numerava os anexos pela ordem de upload. Duas cópias da mesma LISA (uploads 09 e 11) viravam "Documento 09/11";
o contracheque e o boletim de ocorrência apareciam sob números que se cruzavam ("Documento 15 = BO" e "Documentos
13-15 = contracheques"). O mesmo identificador apontava para duas coisas e a mesma coisa tinha dois identificadores.

O QUE ESTE MÓDULO GARANTE

- Cópias (mesmo conteúdo, mesmo documento enviado de novo, "(Duplicado)") colapsam em UM documento lógico; o rótulo
  canônico é "Documento NN" (sequencial, NN → exatamente um documento lógico) e os arquivos de origem ficam registrados.
- O texto da peça usa SÓ o rótulo canônico. `validar_referencias` acusa número inexistente e referência cujo descritor
  ("— Contracheques") não bate com o documento que o número designa.
- Cópia não é evidência independente: o CASE_FACTS consome os documentos lógicos (não os arquivos).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from . import plano_da_peticao as pp
from .conferencia_peticao import Violacao

_REF = re.compile(
    r"\bDocumentos?\s+(\d{1,3}(?:\s*(?:[/,–—-]|\se\s|\sa\s)\s*\d{1,3})*)(?:\s*(?:—|–|-)\s*([^.;:\n]{3,80}))?",
    re.IGNORECASE,
)
_INTERNO = re.compile(r"checklist|check list|triagem|relat[óo]rio\s+interno|anota[cç][ãa]o\s+interna|entrevista|contrato\s+de\s+honor", re.IGNORECASE)


def uso_do_documento(documento: dict[str, Any], tipos: dict[str, str] | None = None) -> str:
    """`interno` ou `probatorio`: classificação antes de qualquer numeração."""
    tipos = tipos or {}
    texto = f"{documento.get('arquivo', '')} {tipos.get(documento.get('arquivo', ''), '')}"
    return "interno" if _INTERNO.search(texto) else "probatorio"


def _hash(texto: str) -> str:
    return hashlib.sha256(pp.norm(texto)[:6000].encode("utf-8")).hexdigest()[:16]


def _tokens(texto: str) -> set[str]:
    return {w for w in pp.norm(texto).split() if len(w) >= 4}


def _base_do_nome(nome: str) -> str:
    """Nome sem a marca de cópia: 'Doc 3. RG (Duplicado 2).pdf' → 'doc 3 rg'."""
    n = pp.norm(re.sub(r"\((?:duplicad[oa]|c[óo]pia)[^)]*\)", " ", nome, flags=re.IGNORECASE))
    return re.sub(r"\bpdf|jpe?g|png\b", "", n).strip()


def _mesmo_documento(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if _hash(a["texto"]) == _hash(b["texto"]) and a["texto"].strip():
        return True
    marca_copia = re.search(r"duplicad|copia", pp.norm(a["arquivo"] + " " + b["arquivo"]))
    if marca_copia and _base_do_nome(a["arquivo"]) == _base_do_nome(b["arquivo"]):
        return True
    # Similaridade de texto NÃO basta: contracheques de meses diferentes compartilham quase todo o vocabulário
    # e são documentos distintos. Só conteúdo idêntico ou cópia declarada no nome colapsa.
    return False


def montar(documentos: list[dict[str, Any]], tipos: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Ledger canônico: um item por documento LÓGICO, na ordem do primeiro upload de cada grupo."""
    tipos = tipos or {}
    # Checklists, triagens e relatórios do escritório orientam a equipe; não são
    # prova do cliente nem anexo protocolável. Excluí-los antes da numeração
    # impede que ganhem um "Documento NN" e contaminem fatos ou pedidos.
    documentos = [d for d in documentos if uso_do_documento(d, tipos) == "probatorio"]
    grupos: list[list[dict[str, Any]]] = []
    for d in documentos:
        for g in grupos:
            if _mesmo_documento(g[0], d):
                g.append(d)
                break
        else:
            grupos.append([d])
    # Numeração: a do próprio arquivo ("Doc 3. Procuração.pdf" → 3), que é a da pasta de protocolo e a que o
    # advogado vê no checklist; sem número no nome (ou com número repetido), o próximo livre.
    numeros: list[int | None] = []
    usados: set[int] = set()
    for g in grupos:
        m = re.match(r"^\s*doc(?:umento)?\s*0*(\d{1,3})\b", g[0]["arquivo"].replace("\\", "/").split("/")[-1], re.IGNORECASE)
        n = int(m.group(1)) if m else None
        if n is not None and n in usados:
            n = None
        numeros.append(n)
        if n is not None:
            usados.add(n)
    proximo = 1
    for i, n in enumerate(numeros):
        if n is None:
            while proximo in usados:
                proximo += 1
            numeros[i] = proximo
            usados.add(proximo)
    saida = []
    for n, g in sorted(zip(numeros, grupos), key=lambda x: x[0]):
        principal = g[0]
        saida.append({
            "document_id": f"DOC_{n:03d}", "numero": n, "canonical_label": f"Documento {n:02d}",
            "document_type": tipos.get(principal["arquivo"], ""), "canonical_file": principal["arquivo"],
            "source_files": [x["arquivo"] for x in g], "content_hash": _hash(principal["texto"]), "duplicate_group": f"G{n:03d}" if len(g) > 1 else "",
        })
    return saida


def descritor(doc: dict[str, Any]) -> set[str]:
    nome = re.sub(r"^doc\s*\d+\.?", "", doc["canonical_file"], flags=re.IGNORECASE)
    return _tokens(doc.get("document_type", "") + " " + nome)


def validar_bijecao(ledger: list[dict[str, Any]]) -> list[Violacao]:
    """NN → exatamente um documento lógico, e cada documento lógico com UM identificador."""
    saida = []
    por_numero: dict[int, list[str]] = {}
    por_arquivo: dict[str, list[int]] = {}
    for d in ledger:
        por_numero.setdefault(d["numero"], []).append(d["document_id"])
        for f in d["source_files"]:
            por_arquivo.setdefault(f, []).append(d["numero"])
    for n, ids in por_numero.items():
        if len(ids) > 1:
            saida.append(Violacao("IDENTIFICADOR_DOCUMENTAL_DUPLICADO", "", f"Documento {n:02d}", f"O identificador Documento {n:02d} aponta para {len(ids)} documentos lógicos.", "Renumere: um número, um documento.", True))
    for f, ns in por_arquivo.items():
        if len(set(ns)) > 1:
            saida.append(Violacao("DOCUMENTO_COM_VARIOS_IDENTIFICADORES", "", f, f"O arquivo «{f}» aparece sob mais de um identificador ({sorted(set(ns))}).", "Consolide num único identificador canônico.", True))
    return saida


def _numeros(bruto: str) -> list[int]:
    if re.search(r"\d\s*(?:[–—-]|\sa\s)\s*\d", bruto):  # faixa "13-15" / "13 a 15"
        nums = [int(x) for x in re.findall(r"\d{1,3}", bruto)]
        return list(range(nums[0], nums[-1] + 1)) if len(nums) == 2 and nums[0] < nums[1] else nums
    return [int(x) for x in re.findall(r"\d{1,3}", bruto)]


def validar_referencias(secoes: list[dict[str, Any]], ledger: list[dict[str, Any]]) -> list[Violacao]:
    """Toda referência "Documento NN — descrição" tem de existir e o descritor tem de bater com o documento designado."""
    por_numero = {d["numero"]: d for d in ledger}
    saida: list[Violacao] = []
    descritores_por_numero: dict[int, list[set[str]]] = {}
    for s in secoes:
        for m in _REF.finditer(str(s.get("content") or "")):
            numeros, descr = _numeros(m.group(1)), (m.group(2) or "").strip()
            for n in numeros:
                if n not in por_numero:
                    saida.append(Violacao("DOCUMENTO_INEXISTENTE_NO_LEDGER", str(s.get("code")), m.group(0)[:100], f"«Documento {n:02d}» não existe entre os documentos lógicos do caso.", "Use só o rótulo canônico.", True))
            tk = _tokens(descr)
            if not tk:
                continue
            for n in numeros:
                if n in por_numero:
                    descritores_por_numero.setdefault(n, []).append(tk)
            # o descritor ("— Contracheques") tem de bater com ALGUM documento designado; e, se bate melhor com OUTRO, é conflito
            designados = [por_numero[n] for n in numeros if n in por_numero]
            # Uma faixa só recebe descritor coletivo quando TODOS os números citados
            # designam documentos daquele tipo; um acerto isolado mascara conflito.
            if designados and any(not (tk & descritor(d)) for d in designados):
                melhores = [d for d in ledger if tk & descritor(d)]
                destino = (
                    f"; esse descritor corresponde ao {melhores[0]['canonical_label']}"
                    if melhores else ""
                )
                saida.append(Violacao("REFERENCIA_DOCUMENTAL_CONFLITANTE", str(s.get("code")), m.group(0)[:110],
                                      f"«{m.group(0)[:80]}» descreve «{descr[:40]}», mas os números citados designam outro(s) documento(s){destino}.",
                                      "Corrija o número para o rótulo canônico do documento descrito.", True))
    for n, lista in descritores_por_numero.items():
        for i, a in enumerate(lista):
            for b in lista[i + 1:]:
                if not (a & b) and n in por_numero and not (a & descritor(por_numero[n]) and b & descritor(por_numero[n])):
                    saida.append(Violacao("IDENTIFICADOR_DOCUMENTAL_DUPLICADO", "", f"Documento {n:02d}", f"Documento {n:02d} é descrito de duas formas incompatíveis ({', '.join(sorted(a))[:30]} × {', '.join(sorted(b))[:30]}).", "Um número, um documento.", True))
                    break
    return saida


def aviso_de_copias(ledger: list[dict[str, Any]]) -> str:
    """Linha para o prompt: o modelo vê o rótulo canônico e sabe que as cópias são o MESMO documento."""
    linhas = [f"- {d['canonical_label']} = {d['canonical_file']}" + (f" (mesmo documento enviado também como: {', '.join(d['source_files'][1:])})" if len(d["source_files"]) > 1 else "") for d in ledger]
    return "DOCUMENTOS LÓGICOS DO CASO (cite SOMENTE estes rótulos; cópias são o mesmo documento):\n" + "\n".join(linhas)
