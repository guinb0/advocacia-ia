"""CASE_FACTS — a fonte canônica dos fatos do caso, consolidada ANTES de qualquer redação.

O PROBLEMA

Cadastro, OCR dos documentos, entrevista e análise documental eram concatenados no prompt. Quando duas
fontes divergiam (nome do cliente no cadastro × nome nos documentos; dois CNPJs da mesma empresa), o modelo
usava uma versão num ponto da peça e outra em outro: qualificação preenchida num lugar e "[PENDENTE]" em
outro. Nada no código sabia que aquilo era UM dado com duas versões.

O QUE ESTE MÓDULO FAZ

Consolida em blocos estruturados — PARTIES, EVENTS, DOCUMENTS, EVIDENCE, UNCERTAINTIES — em que todo
dado tem valor, fonte, confiança e as alternativas conflitantes. Divergência é resolvida SÓ por regra segura:
(1) variações de formato do mesmo dado se fundem; (2) CNPJ da mesma raiz (matriz/filial) é compatível e
vale o de mais fontes; (3) o valor confirmado por 2+ fontes independentes vence o de uma só. Fora disso, o
campo fica SEM valor e entra em UNCERTAINTIES: a peça mostra UMA pendência, nunca as duas versões.

ISOLAMENTO: só entram fontes do CASO (documento, entrevista, cadastro, análise, manual). Peça do acervo
(outro cliente) é recusada aqui, por construção — é inspiração de argumento, não fonte de fato.
"""

from __future__ import annotations

import re
from typing import Any

from . import plano_da_peticao as pp

TIPOS_DE_FONTE_ACEITOS = {"documento", "entrevista", "cadastro", "analise_documental", "manual"}

CAMPOS_NUMERICOS = {"cpf", "cnpj", "rg", "pis", "ctps", "cep", "telefone"}
_CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
_CNPJ = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")


class FonteRecusada(ValueError):
    """Tentativa de usar como fato do caso algo que não é fonte do caso (ex.: peça do acervo)."""


def _forma_canonica(campo: str, valor: str) -> str:
    return pp._so_digitos(valor) if campo in CAMPOS_NUMERICOS else pp.norm(valor)  # noqa: SLF001


def _mesmo_dado(campo: str, a: str, b: str) -> bool:
    ca, cb = _forma_canonica(campo, a), _forma_canonica(campo, b)
    if campo in CAMPOS_NUMERICOS:
        return ca == cb or (campo in ("rg", "pis", "ctps") and bool(ca) and (ca in cb or cb in ca))
    ta, tb = set(ca.split()), set(cb.split())
    return bool(ta and tb) and (ta <= tb or tb <= ta or len(ta & tb) / len(ta | tb) >= 0.7)


def _candidatos(fontes: list[dict[str, Any]], proposta: dict[str, Any] | None, cadastro: dict[str, Any]) -> dict[tuple[str, str], list[dict[str, str]]]:
    """(papel, campo) → lista de {valor, fonte, tipo}. Só o que consta de fonte do caso."""
    saida: dict[tuple[str, str], list[dict[str, str]]] = {}

    def add(papel: str, campo: str, valor: str, fonte: str, tipo: str) -> None:
        if str(valor or "").strip():
            saida.setdefault((papel, campo), []).append({"valor": str(valor).strip(), "fonte": fonte, "tipo": tipo})

    for campo, valor in cadastro.items():
        if campo in pp.CAMPOS_DE_PARTE["autor"]:
            add("autor", campo, valor, "cadastro", "cadastro")
    for f in fontes:
        texto, nome = f.get("texto", ""), f.get("nome", f["tipo"])
        for m in _CPF.finditer(texto):
            add("autor", "cpf", m.group(0), nome, f["tipo"])
        for m in _CNPJ.finditer(texto):
            add("reu", "cnpj", m.group(0), nome, f["tipo"])
    for papel, campos in (proposta or {}).items():
        if isinstance(campos, dict):
            for campo, valor in campos.items():
                # proposta do modelo só vale se o TEXTO do caso a confirma (senão é dado inventado)
                textos = [f for f in fontes if pp._valor_consta(campo, str(valor), pp.norm(f.get("texto", "")), pp._so_digitos(f.get("texto", "")))]  # noqa: SLF001
                for f in textos[:3]:
                    add(papel, campo, str(valor), f.get("nome", f["tipo"]), f["tipo"])
    return saida


def montar(
    *, fontes: list[dict[str, Any]], cadastro: dict[str, Any] | None = None, proposta_partes: dict[str, Any] | None = None,
    eventos: list[dict[str, Any]] | None = None, evidencias: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """CASE_FACTS a partir de fontes do caso. `fontes` = [{tipo, nome, texto}]."""
    for f in fontes:
        if f.get("tipo") not in TIPOS_DE_FONTE_ACEITOS:
            raise FonteRecusada(f"«{f.get('tipo')}» não é fonte de fato do caso (só {sorted(TIPOS_DE_FONTE_ACEITOS)}).")
    cadastro = {k: v for k, v in (cadastro or {}).items() if v}
    cand = _candidatos(fontes, proposta_partes, cadastro)
    partes: dict[str, dict[str, Any]] = {"autor": {}, "reu": {}}
    incertezas: list[dict[str, Any]] = []
    resolucoes: list[dict[str, Any]] = []
    for (papel, campo), lista in cand.items():
        grupos: list[list[dict[str, str]]] = []
        for c in lista:
            for g in grupos:
                if _mesmo_dado(campo, g[0]["valor"], c["valor"]):
                    g.append(c)
                    break
            else:
                grupos.append([c])
        grupos.sort(key=lambda g: (len({x["fonte"] for x in g}), len(g[0]["valor"])), reverse=True)
        principal = grupos[0]
        melhor = max(principal, key=lambda x: len(x["valor"]))
        entrada = {"valor": melhor["valor"], "fontes": sorted({x["fonte"] for x in principal}),
                   "confianca": "alta" if len({x["fonte"] for x in principal}) >= 2 or principal[0]["tipo"] == "cadastro" else "media",
                   "alternativas": [], "conflito": False}
        if len(grupos) > 1:
            outros = grupos[1:]
            entrada["alternativas"] = [{"valor": g[0]["valor"], "fontes": sorted({x["fonte"] for x in g})} for g in outros]
            mesma_raiz = campo == "cnpj" and all(pp._so_digitos(g[0]["valor"])[:8] == pp._so_digitos(entrada["valor"])[:8] for g in outros)  # noqa: SLF001
            n0, n1 = len({x["fonte"] for x in principal}), len({x["fonte"] for x in outros[0]})
            if mesma_raiz:
                resolucoes.append({"campo": f"{papel}.{campo}", "regra": "mesma raiz de CNPJ (matriz/filial): vale o de mais fontes", "escolhido": entrada["valor"]})
            elif n0 > n1:
                resolucoes.append({"campo": f"{papel}.{campo}", "regra": "valor confirmado por mais fontes independentes", "escolhido": entrada["valor"]})
                incertezas.append({"tipo": "divergencia_resolvida", "campo": f"{papel}.{campo}", "detalhe": f"adotado «{entrada['valor']}» ({n0} fontes) em vez de «{outros[0][0]['valor']}» ({n1}); confirmar"})
            else:
                entrada["valor"], entrada["conflito"], entrada["confianca"] = None, True, "nenhuma"
                incertezas.append({"tipo": "conflito", "campo": f"{papel}.{campo}",
                                   "detalhe": " × ".join(f"«{g[0]['valor']}» ({', '.join(sorted({x['fonte'] for x in g}))})" for g in grupos)})
        partes[papel][campo] = entrada
    return {
        "PARTIES": partes,
        "EVENTS": eventos or [],
        "DOCUMENTS": [{"nome": f.get("nome"), "tipo": f["tipo"]} for f in fontes if f["tipo"] == "documento"],
        "EVIDENCE": evidencias or [],
        "UNCERTAINTIES": incertezas,
        "RESOLUTIONS": resolucoes,
    }


def partes_resolvidas(cf: dict[str, Any]) -> dict[str, Any]:
    """Formato do plano (`plano_da_peticao`): só campos com valor resolvido; conflito fica de fora."""
    saida: dict[str, Any] = {"autor": {}, "reu": {}, "descartados": [], "origem": {}, "pendentes_por_conflito": []}
    for papel, campos in cf["PARTIES"].items():
        for campo, e in campos.items():
            if e["valor"]:
                saida[papel][campo] = e["valor"]
                saida["origem"][f"{papel}.{campo}"] = ",".join(e["fontes"])
            elif e["conflito"]:
                saida["pendentes_por_conflito"].append(f"{papel}.{campo}")
    return saida
