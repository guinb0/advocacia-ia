"""CANONICAL CASE DATA: a fonte única dos dados do caso.

Toda seção, tabela, cálculo e auditor lê daqui — nunca de um valor que o modelo reescreveu no texto:
- chave FIXA por dado (`claimant.birth_date`, `employment.start_date`, `current_salary`…), resolvida a partir
  da matriz de fatos pelos apelidos que o issue spotting e o CASE_FACTS usam;
- nível de CERTEZA explícito por dado (enum abaixo);
- idade e tempo de serviço CALCULADOS pelo código a partir das datas canônicas, com `calculation_id`;
- `petition_date` = a data da geração (nunca a de um modelo antigo de petição).

Dado contraditório não tem valor canônico: fica CONTRADICTED com as versões, até o humano resolver.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from . import calculos
from .autoridades import _data, norm
from .fatos import ALEGADO, CONFIRMADO, INFERIDO, valor_canonico

CONFIRMED = "CONFIRMED"
INDICATED_BY_DOCUMENTS = "INDICATED_BY_DOCUMENTS"
ALLEGED = "ALLEGED"
REQUIRES_EXPERT_CONFIRMATION = "REQUIRES_EXPERT_CONFIRMATION"
INFERRED = "INFERRED"
CONTRADICTED = "CONTRADICTED"
#: Da mais forte para a mais fraca; dado derivado herda a certeza mais fraca dos insumos.
CERTEZAS = (CONFIRMED, INDICATED_BY_DOCUMENTS, ALLEGED, REQUIRES_EXPERT_CONFIRMATION, INFERRED, CONTRADICTED)
ROTULOS_CERTEZA = {
    CONFIRMED: "confirmado por documento",
    INDICATED_BY_DOCUMENTS: "indicado pelos documentos (indício, não prova cabal)",
    ALLEGED: "alegado pelo autor",
    REQUIRES_EXPERT_CONFIRMATION: "depende de confirmação pericial",
    INFERRED: "inferido (não afirmar)",
    CONTRADICTED: "contraditório entre fontes (não usar sem resolver)",
}
#: O que pode ser AFIRMADO no corpo da peça sem ressalva.
AFIRMAVEIS = {CONFIRMED}
#: O que pode ser usado (com a redação adequada à certeza).
UTILIZAVEIS = {CONFIRMED, INDICATED_BY_DOCUMENTS, ALLEGED}

#: Vocabulários antigos → enum único.
_DE_ESTADO = {CONFIRMADO: CONFIRMED, ALEGADO: ALLEGED, INFERIDO: INFERRED}
_DE_PLANO = {"CONFIRMED": CONFIRMED, "ALLEGED": ALLEGED, "NOT_FOUND_IN_AVAILABLE_DOCUMENTS": INFERRED}
_DE_CONFIANCA = {"alta": CONFIRMED, "media": ALLEGED, "baixa": INFERRED, "nenhuma": INFERRED}


def certeza(valor: Any) -> str:
    """Normaliza qualquer vocabulário de certeza do sistema para o enum único."""
    s = str(valor or "").strip()
    if s.upper() in CERTEZAS:
        return s.upper()
    return _DE_ESTADO.get(s.lower()) or _DE_PLANO.get(s.upper()) or _DE_CONFIANCA.get(s.lower()) or INFERRED


def mais_fraca(*certezas: str) -> str:
    return max(certezas, key=CERTEZAS.index) if certezas else INFERRED


def certeza_do_fato(fato: dict[str, Any]) -> str:
    """Estado da matriz + o que o issue spotting declarou. A declaração do modelo só REBAIXA, nunca promove."""
    if fato.get("contradicoes"):
        return CONTRADICTED
    base = certeza(fato.get("estado"))
    declarada = str(fato.get("certeza_declarada") or "").strip().upper()
    if declarada in CERTEZAS and CERTEZAS.index(declarada) > CERTEZAS.index(base):
        return declarada
    return base


@dataclass(frozen=True)
class Campo:
    chave: str
    tipo: str          # data | dinheiro | percentual | documento | texto | anos | meses
    rotulo: str
    apelidos: tuple[str, ...] = ()


CAMPOS: tuple[Campo, ...] = (
    Campo("claimant.name", "texto", "nome do autor", ("autor.nome", "reclamante.nome")),
    Campo("claimant.cpf", "documento", "CPF do autor", ("autor.cpf", "reclamante.cpf")),
    Campo("claimant.birth_date", "data", "data de nascimento do autor",
          ("autor.data_nascimento", "autor.nascimento", "autor.data_de_nascimento", "reclamante.data_nascimento", "reclamante.nascimento")),
    Campo("claimant.cep", "documento", "CEP do autor", ("autor.cep", "reclamante.cep")),
    Campo("claimant.city", "texto", "cidade do autor", ("autor.cidade", "autor.municipio", "reclamante.cidade")),
    Campo("defendant.name", "texto", "nome da ré", ("reu.nome", "reu.razao_social", "reclamada.nome", "reclamada.razao_social", "empregador.nome")),
    Campo("defendant.cnpj", "documento", "CNPJ da ré", ("reu.cnpj", "reclamada.cnpj", "empregador.cnpj")),
    Campo("defendant.cep", "documento", "CEP da ré", ("reu.cep", "reclamada.cep")),
    Campo("employment.start_date", "data", "data de admissão",
          ("contrato.admissao", "contrato.data_admissao", "contrato.data_de_admissao", "contrato.inicio", "vinculo.admissao", "autor.data_admissao")),
    Campo("employment.end_date", "data", "data de término do contrato",
          ("contrato.demissao", "contrato.dispensa", "contrato.data_demissao", "contrato.data_dispensa", "contrato.termino", "contrato.fim",
           "contrato.rescisao", "contrato.data_rescisao", "vinculo.dispensa", "autor.data_demissao")),
    Campo("employment.role", "texto", "função", ("contrato.funcao", "contrato.cargo")),
    Campo("employment.workplace", "texto", "local de trabalho", ("contrato.local_de_trabalho", "contrato.local_trabalho", "contrato.lotacao")),
    Campo("event.accident_date", "data", "data do evento (acidente/sinistro)",
          ("acidente.data", "acidente.data_acidente", "evento.data", "sinistro.data", "assalto.data", "cat.data_acidente", "autor.data_acidente")),
    Campo("current_salary", "dinheiro", "salário atual",
          ("contrato.salario", "contrato.ultimo_salario", "contrato.salario_atual", "contrato.salario_base", "salario.atual", "remuneracao.salario_base")),
    Campo("compensation_base", "dinheiro", "remuneração (base de cálculo)",
          ("contrato.remuneracao", "contrato.base_de_calculo", "contrato.maior_remuneracao", "remuneracao.total")),
    Campo("disability_percentage", "percentual", "percentual de incapacidade",
          ("incapacidade.percentual", "incapacidade.grau", "laudo.percentual_incapacidade", "pericia.percentual")),
    Campo("pension_value", "dinheiro", "valor do pensionamento", ("pensionamento.valor", "pensao.valor")),
)
DERIVADOS: tuple[Campo, ...] = (
    Campo("claimant.age_at_event", "anos", "idade do autor na data do evento"),
    Campo("claimant.age_at_petition", "anos", "idade do autor na data da petição"),
    Campo("employment.tenure_months", "meses", "tempo de serviço"),
    Campo("petition_date", "data", "data da petição"),
)
POR_CHAVE: dict[str, Campo] = {c.chave: c for c in (*CAMPOS, *DERIVADOS)}
_POR_APELIDO: dict[str, str] = {a: c.chave for c in CAMPOS for a in (c.chave, *c.apelidos)}

#: Parâmetro de calculadora ← chave canônica (preenche o que o issue spotting não informou; nunca sobrescreve).
PARAMETRO_DE_CALCULO: dict[str, tuple[str, ...]] = {
    "salario": ("current_salary",),
    "base_mensal": ("compensation_base", "current_salary"),
    "admissao": ("employment.start_date",),
    "dispensa": ("employment.end_date",),
    "nascimento": ("claimant.birth_date",),
    "data_evento": ("event.accident_date",),
    "idade_no_evento": ("claimant.age_at_event",),
    "percentual_incapacidade": ("disability_percentage",),
}


def chave_canonica(chave_da_matriz: str) -> str:
    return _POR_APELIDO.get(norm(chave_da_matriz).replace(" ", "_"), "")


def _valor_tipado(tipo: str, bruto: Any) -> Any:
    if tipo == "data":
        d = _data(bruto)
        return d.isoformat() if d else None
    if tipo == "dinheiro":
        c = valor_canonico(bruto)
        return round(int(c[2:]) / 100, 2) if c.startswith("R$") else None
    if tipo == "percentual":
        try:
            return float(calculos._fracao(bruto))  # noqa: SLF001
        except Exception:  # noqa: BLE001 - valor ilegível fica sem forma canônica
            return None
    return str(bruto).strip() or None


def exibir(campo: dict[str, Any]) -> str:
    """Forma de ESCRITA do valor canônico (a mesma em toda a peça)."""
    v, tipo = campo.get("valor"), campo.get("tipo")
    if v in (None, ""):
        return ""
    if tipo == "data":
        return date.fromisoformat(v).strftime("%d/%m/%Y")
    if tipo == "dinheiro":
        return calculos.brl(v)
    if tipo == "percentual":
        return f"{float(v) * 100:g}%".replace(".", ",")
    if tipo == "anos":
        return f"{int(v)} anos"
    if tipo == "meses":
        return f"{int(v) // 12} ano(s) e {int(v) % 12} mês(es)"
    return str(v)


def montar(matriz: dict[str, Any], *, petition_date: date) -> dict[str, Any]:
    """Dados canônicos a partir da matriz de fatos (que já reúne plano, CASE_FACTS e fatos chaveados)."""
    grupos: dict[str, list[dict[str, Any]]] = {}
    for f in matriz.get("fatos") or []:
        alvo = chave_canonica(str(f.get("chave") or ""))
        if alvo and str(f.get("valor") or "").strip():
            grupos.setdefault(alvo, []).append(f)
    campos: dict[str, dict[str, Any]] = {}
    conflitos: list[dict[str, Any]] = []
    for c in CAMPOS:
        lista = grupos.get(c.chave) or []
        if not lista:
            continue
        validos = [f for f in lista if certeza_do_fato(f) != INFERRED]
        versoes: dict[Any, list[dict[str, Any]]] = {}
        for f in validos or lista:
            versoes.setdefault(_valor_tipado(c.tipo, f["valor"]) or norm(f["valor"]), []).append(f)
        if len(versoes) > 1 or any(f.get("contradicoes") for f in validos):
            campos[c.chave] = {"chave": c.chave, "rotulo": c.rotulo, "tipo": c.tipo, "valor": None, "certeza": CONTRADICTED,
                               "fonte": "", "documento": "", "fato_ids": [f["id"] for f in lista], "derivado": False,
                               "versoes": [{"valor": g[0]["valor"], "fontes": sorted({f.get("fonte") or "" for f in g}),
                                            "certeza": certeza_do_fato({**g[0], "contradicoes": []})} for g in versoes.values()]}
            conflitos.append({"chave": c.chave, "versoes": campos[c.chave]["versoes"]})
            continue
        melhor = min(validos or lista, key=lambda f: CERTEZAS.index(certeza_do_fato(f)))
        campos[c.chave] = {"chave": c.chave, "rotulo": c.rotulo, "tipo": c.tipo, "valor": _valor_tipado(c.tipo, melhor["valor"]),
                           "valor_original": str(melhor["valor"]), "certeza": certeza_do_fato(melhor), "fonte": melhor.get("fonte") or "",
                           "documento": melhor.get("documento") or "", "pagina": melhor.get("pagina") or "",
                           "fato_ids": [f["id"] for f in lista], "derivado": False}
    derivados: list[dict[str, Any]] = []

    def derivar(chave: str, rubrica: str, parametros: dict[str, Any], insumos: list[str]) -> None:
        calc = calculos.calcular(rubrica, parametros, calculation_id=f"CALC_D{len(derivados) + 1:02d}").como_dict()
        derivados.append(calc)
        if calc["erro"]:
            return
        campo = POR_CHAVE[chave]
        campos[chave] = {"chave": chave, "rotulo": campo.rotulo, "tipo": campo.tipo, "valor": int(calc["valor"]),
                         "certeza": mais_fraca(*(campos[i]["certeza"] for i in insumos if i in campos)) if insumos else CONFIRMED,
                         "fonte": "calculado pelo sistema", "documento": "", "fato_ids": [i for i in insumos], "derivado": True,
                         "calculation_id": calc["calculation_id"], "memoria": calc["memoria"]}

    def usavel(chave: str) -> Any:
        e = campos.get(chave)
        return e["valor"] if e and e["valor"] not in (None, "") and e["certeza"] not in (CONTRADICTED, INFERRED) else None

    nascimento, evento = usavel("claimant.birth_date"), usavel("event.accident_date")
    admissao, termino = usavel("employment.start_date"), usavel("employment.end_date")
    if nascimento and evento:
        derivar("claimant.age_at_event", "idade", {"nascimento": nascimento, "referencia": evento}, ["claimant.birth_date", "event.accident_date"])
    if nascimento:
        derivar("claimant.age_at_petition", "idade", {"nascimento": nascimento, "referencia": petition_date.isoformat()}, ["claimant.birth_date"])
    if admissao:
        derivar("employment.tenure_months", "tempo_de_servico",
                {"admissao": admissao, **({"dispensa": termino} if termino else {"referencia": petition_date.isoformat()})},
                ["employment.start_date", *(["employment.end_date"] if termino else [])])
    campos["petition_date"] = {"chave": "petition_date", "rotulo": "data da petição", "tipo": "data", "valor": petition_date.isoformat(),
                               "certeza": CONFIRMED, "fonte": "data da geração", "documento": "", "fato_ids": [], "derivado": True}
    return {
        "petition_date": petition_date.isoformat(),
        "campos": campos,
        "calculos": derivados,
        "conflitos": conflitos,
        "ausentes": [c.chave for c in (*CAMPOS, *DERIVADOS) if c.chave not in campos],
        "resumo": {k: sum(1 for e in campos.values() if e["certeza"] == k) for k in CERTEZAS},
    }


def valor(canon: dict[str, Any] | None, chave: str, *, so_utilizavel: bool = True) -> Any:
    e = ((canon or {}).get("campos") or {}).get(chave)
    if not e or e.get("valor") in (None, ""):
        return None
    if so_utilizavel and e["certeza"] in (CONTRADICTED, INFERRED):
        return None
    return e["valor"]


def parametros_aceitos(rubrica: str) -> set[str]:
    funcao = calculos.CALCULADORAS.get(str(rubrica or ""))
    if funcao is None:
        return set()
    return {p.name for p in inspect.signature(funcao).parameters.values() if p.kind == p.KEYWORD_ONLY}


def completar_parametros(rubrica: str, parametros: dict[str, Any], canon: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """Parâmetros que a calculadora aceita e o issue spotting não deu, preenchidos da fonte única. Nunca sobrescreve."""
    aceitos = parametros_aceitos(rubrica)
    if not aceitos or not canon:
        return dict(parametros or {}), []
    saida, preenchidos = dict(parametros or {}), []
    for nome, chaves in PARAMETRO_DE_CALCULO.items():
        if nome not in aceitos or saida.get(nome) not in (None, ""):
            continue
        for chave in chaves:
            v = valor(canon, chave)
            if v not in (None, ""):
                saida[nome] = v
                preenchidos.append(f"{nome}←{chave}")
                break
    return saida, preenchidos


#: Ressalva de certeza na memória de cálculo (sem "prova cabal": a memória não afirma o que o documento só indica).
_RESSALVA_NA_MEMORIA = {INDICATED_BY_DOCUMENTS: "indicado pelos documentos", ALLEGED: "alegado pelo autor",
                        REQUIRES_EXPERT_CONFIRMATION: "a ser confirmado por perícia"}


def _mesmo_valor(campo: dict[str, Any] | None, v: Any) -> bool:
    if not campo or campo.get("valor") in (None, "") or v in (None, ""):
        return False
    if campo["tipo"] in ("anos", "meses"):
        return str(campo["valor"]) == str(v).strip()
    return _valor_tipado(campo["tipo"], v) == campo["valor"]


def fontes_dos_parametros(parametros: dict[str, Any], preenchidos: list[str], canon: dict[str, Any] | None,
                          *, extras: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Parâmetros do cálculo que vieram da fonte única (ou batem com ela), com rótulo, valor e documento de origem."""
    origem = dict(p.split("←", 1) for p in preenchidos if "←" in p)
    campos = (canon or {}).get("campos") or {}
    saida: dict[str, dict[str, Any]] = {}
    for nome, v in (parametros or {}).items():
        if nome in (extras or {}):
            saida[nome] = extras[nome]
            continue
        chave = origem.get(nome) or next((k for k in PARAMETRO_DE_CALCULO.get(nome, ()) if _mesmo_valor(campos.get(k), v)), "")
        campo = campos.get(chave)
        if not campo or campo.get("certeza") in (CONTRADICTED, INFERRED):
            continue
        fonte = (f"calculado, {campo['calculation_id']}" if campo.get("derivado") and campo.get("calculation_id")
                 else str(campo.get("documento") or campo.get("fonte") or "documentos do caso"))
        if campo.get("pagina"):
            fonte += f", p. {campo['pagina']}"
        if campo["certeza"] in _RESSALVA_NA_MEMORIA:
            fonte += f"; {_RESSALVA_NA_MEMORIA[campo['certeza']]}"
        saida[nome] = {"chave": chave, "rotulo": campo["rotulo"], "exibir": exibir(campo), "valor": campo["valor"],
                       "tipo": campo["tipo"], "fonte": fonte}
    return saida


#: Rubricas que pressupõem o contrato ENCERRADO (dispensa, pedido de demissão ou rescisão indireta pedida na ação).
RUBRICAS_RESCISORIAS = frozenset({"aviso_previo", "multa_477", "multa_467", "multa_fgts", "saldo_salario"})
_RESCISAO_INDIRETA = re.compile(r"rescis[aã]o\s+indireta|\bart\.?\s*483\b", re.I)
PEDIDO_RESCISORIO = re.compile(
    r"multa\s+(?:do|prevista\s+no|por\s+atraso[^.;\n]{0,60}?)\s*(?:art\.?|artigo)\s*4(?:67|77)\b|\bart\.?\s*4(?:67|77)\b"
    r"|verbas\s+rescis[oó]rias|aviso[\s-]+pr[eé]vio|multa\s+(?:de|dos)\s+40\s*%|seguro[\s-]+desemprego|saldo\s+de\s+sal[aá]rio",
    re.I)


_REFLEXO = re.compile(r"reflex", re.I)


def menciona_verba_rescisoria(texto: str) -> bool:
    """Pede verba rescisória como objeto — não como reflexo de outra parcela ("com reflexos em aviso prévio")."""
    return any(not _REFLEXO.search(texto[max(0, m.start() - 160):m.start()]) for m in PEDIDO_RESCISORIO.finditer(texto or ""))


def pede_rescisao_indireta(teses_incluidas: list[dict[str, Any]]) -> bool:
    return any(_RESCISAO_INDIRETA.search(f"{t.get('tese') or ''} {t.get('pedido') or ''}") for t in teses_incluidas)


def termino_do_contrato(canon: dict[str, Any] | None) -> Any:
    return valor(canon, "employment.end_date")


def pressuposto_rescisorio(tese: dict[str, Any], canon: dict[str, Any] | None, *, rescisao_indireta: bool) -> str:
    """Motivo pelo qual a tese NÃO pode ser pedida ('' = pode). Aviso prévio, saldo de salário, multas dos arts.
    467/477 e 40% do FGTS só existem com o contrato encerrado; vínculo ativo sem rescisão indireta não os sustenta."""
    if canon is None:
        return ""
    rubrica = str((tese.get("calculo") or {}).get("rubrica") or "")
    rescisoria = rubrica in RUBRICAS_RESCISORIAS or menciona_verba_rescisoria(f"{tese.get('tese') or ''} {tese.get('pedido') or ''}")
    if not rescisoria or rescisao_indireta or termino_do_contrato(canon):
        return ""
    campo = ((canon or {}).get("campos") or {}).get("employment.end_date") or {}
    if campo.get("certeza") == CONTRADICTED:
        return "pressuposto fático em conflito: a data de término do contrato tem versões divergentes nos documentos"
    return ("pressuposto fático ausente: não há término do contrato nos documentos (vínculo ativo?) — aviso prévio, saldo de "
            "salário, 40% do FGTS e multas dos arts. 467/477 da CLT só cabem com dispensa, pedido de demissão ou rescisão "
            "indireta pedida na ação")


def para_prompt(canon: dict[str, Any] | None) -> str:
    if not canon:
        return ""
    linhas = ["=== DADOS CANÔNICOS DO CASO (fonte única — escreva EXATAMENTE estes valores; não recalcule idade, datas nem salário) ==="]
    for chave, e in (canon.get("campos") or {}).items():
        if e["certeza"] == CONTRADICTED:
            linhas.append(f"- {chave} ({e['rotulo']}): CONTRADITÓRIO — " + " × ".join(f"«{v['valor']}» ({', '.join(v['fontes'])})" for v in e.get("versoes") or [])
                          + " → NÃO use este dado no corpo.")
            continue
        origem = f"calculado ({e['calculation_id']})" if e.get("calculation_id") else (e.get("documento") or e.get("fonte") or "-")
        linhas.append(f"- {chave} ({e['rotulo']}) = {exibir(e)} | certeza: {e['certeza']} | fonte: {origem}")
    linhas.append(
        "Redação conforme a certeza: CONFIRMED se afirma; INDICATED_BY_DOCUMENTS como indício («os documentos indicam»); "
        "ALLEGED como alegação do autor; REQUIRES_EXPERT_CONFIRMATION nunca como fato certo — diga que será apurado em perícia; "
        "INFERRED não se escreve; CONTRADICTED não se usa.")
    return "\n".join(linhas)


def para_trace(canon: dict[str, Any] | None) -> dict[str, Any] | None:
    if not canon:
        return None
    return {**canon, "campos": [{**e, "exibicao": exibir(e), "rotulo_certeza": ROTULOS_CERTEZA.get(e["certeza"], e["certeza"])}
                                for e in canon["campos"].values()]}
