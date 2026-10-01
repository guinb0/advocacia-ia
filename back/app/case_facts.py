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


#: Peso da CLASSE da fonte. Fonte primária/oficial (documento de identificação) pesa mais que documento
#: comprobatório, que pesa mais que entrevista; o dado confirmado por um humano pesa mais que tudo.
PESO_DA_CLASSE = {"confirmado_por_humano": 1.2, "documento_oficial": 1.0, "documento_comprobatorio": 0.6, "cadastro": 0.5, "entrevista": 0.4}
#: Um vencedor precisa superar o segundo colocado por esta margem; senão é conflito (ninguém escolhe no chute).
MARGEM_PARA_VENCER = 1.25
PESO_MINIMO_PARA_VENCER = 0.6
EXTRA_POR_FONTE_INDEPENDENTE_DA_MESMA_CLASSE = 0.15

CAMPOS_NUMERICOS |= {"data_admissao", "data_demissao", "data_acidente", "data_nascimento"}


def _classe_do_documento(nome: str, tipo_do_documento: str, oficiais: list[str]) -> str:
    alvo = pp.norm(f"{nome} {tipo_do_documento}")
    return "documento_oficial" if any(pp.norm(o) in alvo for o in oficiais) else "documento_comprobatorio"


def _fontes_independentes(fontes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cópia do mesmo documento NÃO é fonte nova: fontes com o mesmo texto (ou marcadas "duplicado") colapsam em uma."""
    vistas: dict[str, dict[str, Any]] = {}
    for f in fontes:
        chave = pp.norm(f.get("texto", ""))[:4000] or pp.norm(f.get("nome", ""))
        if chave in vistas:
            vistas[chave]["_copias"] = vistas[chave].get("_copias", 0) + 1
            continue
        vistas[chave] = dict(f)
    return list(vistas.values())


def _candidatos(fontes: list[dict[str, Any]], proposta: dict[str, Any] | None, cadastro: dict[str, Any],
                extraidos: list[dict[str, Any]], oficiais: list[str]) -> dict[tuple[str, str], list[dict[str, str]]]:
    """(papel, campo) → lista de {valor, fonte, classe}. Só o que consta de fonte do caso."""
    saida: dict[tuple[str, str], list[dict[str, str]]] = {}

    def add(papel: str, campo: str, valor: str, fonte: str, classe: str) -> None:
        if str(valor or "").strip():
            saida.setdefault((papel, campo), []).append({"valor": str(valor).strip(), "fonte": fonte, "classe": classe})

    def classe_de(f: dict[str, Any]) -> str:
        return f.get("classe") or ("entrevista" if f["tipo"] == "entrevista" else _classe_do_documento(f.get("nome", ""), f.get("tipo_documento", ""), oficiais))

    textos_docs = "\n".join(f.get("texto") or "" for f in fontes if f.get("tipo") == "documento")
    blob_norm = pp.norm(textos_docs)
    blob_dig = pp._so_digitos(textos_docs)  # noqa: SLF001
    for campo, valor in cadastro.items():
        # Endereço, CEP e CNPJ do cadastro só entram se um documento DESTE caso
        # os trouxer. Cadastro copiado de outro processo (Tucuruí, outra filial)
        # não é fonte.
        if campo in ("endereco", "cep", "cnpj") and blob_norm and not pp._valor_consta(campo, str(valor), blob_norm, blob_dig):  # noqa: SLF001
            continue
        add("autor", campo, valor, "cadastro", "cadastro")
    for f in fontes:
        texto, nome = f.get("texto", ""), f.get("nome", f["tipo"])
        for m in _CPF.finditer(texto):
            add("autor", "cpf", m.group(0), nome, classe_de(f))
        for m in _CNPJ.finditer(texto):
            add("reu", "cnpj", m.group(0), nome, classe_de(f))
        for papel, campo, valor in f.get("dados") or []:  # dado estruturado extraído DAQUELE documento
            add(papel, campo, valor, nome, classe_de(f))
    for e in extraidos:  # dado informado/confirmado manualmente
        add(e["papel"], e["campo"], e["valor"], e.get("fonte", "manual"), e.get("classe", "confirmado_por_humano"))
    for papel, campos in (proposta or {}).items():
        if isinstance(campos, dict):
            for campo, valor in campos.items():
                # a proposta do modelo só vale onde o TEXTO de uma fonte a confirma (senão é dado inventado)
                for f in fontes[:30]:
                    if pp._valor_consta(campo, str(valor), pp.norm(f.get("texto", "")), pp._so_digitos(f.get("texto", ""))):  # noqa: SLF001
                        add(papel, campo, str(valor), f.get("nome", f["tipo"]), classe_de(f))
    return saida


def _pontuar(grupo: list[dict[str, str]]) -> float:
    """Peso do grupo = melhor fonte de cada CLASSE (+ pouco por fontes independentes extras da mesma classe)."""
    por_classe: dict[str, list[str]] = {}
    for c in grupo:
        por_classe.setdefault(c["classe"], []).append(c["fonte"])
    total = 0.0
    for classe, fontes in por_classe.items():
        extras = min(2, len(set(fontes)) - 1)
        total += PESO_DA_CLASSE.get(classe, 0.4) + EXTRA_POR_FONTE_INDEPENDENTE_DA_MESMA_CLASSE * extras
    return round(total, 3)


def montar(
    *, fontes: list[dict[str, Any]], cadastro: dict[str, Any] | None = None, proposta_partes: dict[str, Any] | None = None,
    eventos: list[dict[str, Any]] | None = None, evidencias: list[dict[str, Any]] | None = None,
    extraidos: list[dict[str, Any]] | None = None, documentos_oficiais: list[str] | None = None,
) -> dict[str, Any]:
    """CASE_FACTS a partir de fontes do caso. `fontes` = [{tipo, nome, texto, classe?, dados?}]."""
    for f in fontes:
        if f.get("tipo") not in TIPOS_DE_FONTE_ACEITOS:
            raise FonteRecusada(f"«{f.get('tipo')}» não é fonte de fato do caso (só {sorted(TIPOS_DE_FONTE_ACEITOS)}).")
    oficiais = documentos_oficiais or ["rg", "cnh", "cpf", "ctps", "certidao", "identidade"]
    cadastro = {k: v for k, v in (cadastro or {}).items() if v}
    independentes = _fontes_independentes(fontes)
    cand = _candidatos(independentes, proposta_partes, cadastro, extraidos or [], oficiais)
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
        pesos = sorted(((_pontuar(g), g) for g in grupos), key=lambda x: (x[0], len(x[1][0]["valor"])), reverse=True)
        peso0, principal = pesos[0]
        melhor = max(principal, key=lambda x: len(x["valor"]))
        entrada = {"valor": melhor["valor"], "fontes": sorted({x["fonte"] for x in principal}), "peso": peso0,
                   "confianca": "alta" if peso0 >= 1.0 else "media", "alternativas": [], "conflito": False}
        if len(pesos) > 1:
            entrada["alternativas"] = [{"valor": g[0]["valor"], "fontes": sorted({x["fonte"] for x in g}), "peso": p} for p, g in pesos[1:]]
            peso1 = pesos[1][0]
            mesma_raiz = campo == "cnpj" and all(pp._so_digitos(g[0]["valor"])[:8] == pp._so_digitos(entrada["valor"])[:8] for _, g in pesos[1:])  # noqa: SLF001
            if mesma_raiz:
                resolucoes.append({"campo": f"{papel}.{campo}", "regra": "mesma raiz de CNPJ (matriz/filial): vale o de maior peso", "escolhido": entrada["valor"]})
            elif any(c["classe"] == "confirmado_por_humano" for c in principal) or (peso0 >= PESO_MINIMO_PARA_VENCER and peso0 >= peso1 * MARGEM_PARA_VENCER):
                resolucoes.append({"campo": f"{papel}.{campo}", "regra": f"maior peso de fonte independente ({peso0} × {peso1})", "escolhido": entrada["valor"]})
                incertezas.append({"tipo": "divergencia_resolvida", "campo": f"{papel}.{campo}",
                                   "detalhe": f"adotado «{entrada['valor']}» (peso {peso0}) em vez de «{pesos[1][1][0]['valor']}» (peso {peso1}); confirmar"})
            else:
                entrada["valor"], entrada["conflito"], entrada["confianca"] = None, True, "nenhuma"
                incertezas.append({"tipo": "conflito", "campo": f"{papel}.{campo}",
                                   "detalhe": " × ".join(f"«{g[0]['valor']}» (peso {p}; {', '.join(sorted({x['fonte'] for x in g}))})" for p, g in pesos)})
        partes[papel][campo] = entrada
    return {
        "PARTIES": partes, "EVENTS": eventos or [],
        "DOCUMENTS": [{"nome": f.get("nome"), "tipo": f["tipo"], "copias": f.get("_copias", 0)} for f in independentes if f["tipo"] == "documento"],
        "EVIDENCE": evidencias or [], "UNCERTAINTIES": incertezas, "RESOLUTIONS": resolucoes,
    }


def partes_resolvidas(cf: dict[str, Any]) -> dict[str, Any]:
    """Formato do plano (`plano_da_peticao`): só campos com valor resolvido; conflito fica de fora."""
    saida: dict[str, Any] = {"autor": {}, "reu": {}, "descartados": [], "origem": {}, "pendentes_por_conflito": []}
    for papel, campos in (cf.get("PARTIES") or {}).items():
        if not isinstance(campos, dict):
            continue
        for campo, e in campos.items():
            if not isinstance(e, dict):
                continue
            if e.get("valor"):
                saida[papel][campo] = e["valor"]
                saida["origem"][f"{papel}.{campo}"] = ",".join(e.get("fontes") or [])
            elif e["conflito"]:
                saida["pendentes_por_conflito"].append(f"{papel}.{campo}")
    return saida
