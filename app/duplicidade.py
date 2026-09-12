"""Quando dois documentos do mesmo caso são o mesmo documento.

A REGRA, EM TRÊS NÍVEIS — do certo ao provável

1. IDÊNTICO: os bytes são os mesmos (SHA-256 do arquivo, que toda entrega já grava em
   `conteudo_sha256`). Não há falso positivo possível — é o mesmo arquivo, com outro
   nome ou não.
2. MESMO NÚMERO: o classificador reconheceu os dois como o MESMO tipo cadastral e os
   dois trazem o mesmo número de documento válido (CPF, RG, registro da CNH, título de
   eleitor, Cartão SUS). É a segunda foto do mesmo RG, que tem bytes diferentes.
3. MESMO CONTEÚDO: os dois têm o mesmo tipo no glossário e o texto lido é praticamente
   o mesmo — pelo menos 90% dos trigramas de palavras em comum, com 30 palavras ou mais
   em cada um. É o PDF reexportado e a segunda cópia de um documento digital.

O QUE NÃO CONTA COMO DUPLICIDADE, DE PROPÓSITO

- Documento de OUTRO caso. O mesmo PCMSO serve a dois clientes da mesma empresa, e
  procurar fora do caso ainda contaria a quem envia pelo portal que outro cliente já
  mandou aquele papel.
- Mesmo tipo e nada mais. Dois atestados são dois atestados. Dois contracheques de
  meses diferentes dividem quase todo o cabeçalho — por isso a comparação é por
  TRIGRAMAS, e não por palavras soltas: cada valor que muda derruba os três trigramas
  em volta dele, e a semelhança de dois meses distintos fica longe dos 90%.
- RG e CNH da mesma pessoa. Trazem o mesmo número de RG, mas são documentos
  diferentes; a regra 2 exige o mesmo tipo reconhecido.

O QUE ELA NÃO PEGA, e fica dito para ninguém confiar além da conta: duas fotos de um
laudo manuscrito ou mal digitalizado, que o OCR lê de jeitos diferentes. Baixar o
limiar para alcançá-las passaria a acusar atestados do mesmo médico, que são
documentos distintos.

O QUE CADA NÍVEL FAZ

O nível 1 é verificado ANTES de gravar o envio (`identicos`), porque só depende dos
bytes: o arquivo repetido é recusado, e só a equipe pode insistir, com confirmação
registrada. Os níveis 2 e 3 dependem da leitura, então são verificados depois do OCR e
antes de o documento contar no checklist: a suspeita segura o documento na triagem,
com o motivo. Na reclassificação os três são verificados antes de gravar, e a
conclusão exige confirmação.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from . import tipos_documento
from .banco import conectar
from .categorias import Categoria
from .extractors import normalizar

__all__ = [
    "CODIGO_ERRO",
    "DocumentoDuplicado",
    "Duplicidade",
    "IDENTICO",
    "MESMO_CONTEUDO",
    "MESMO_NUMERO",
    "comparar",
    "identicos",
    "mensagem",
    "procurar",
    "sha_da_entrega",
    "similaridade",
    "tipo_da_entrega",
]

IDENTICO = "identico"
MESMO_NUMERO = "mesmo_numero"
MESMO_CONTEUDO = "mesmo_conteudo"

#: Quanto do texto precisa coincidir para dois documentos serem o mesmo.
LIMIAR_TEXTO = 0.9

#: Abaixo disto não há texto para comparar: uma foto de RG com dez palavras lidas
#: "coincide" com qualquer outra foto de RG com as mesmas dez palavras de modelo.
MINIMO_PALAVRAS = 30

#: Número de documento com menos dígitos que isto é leitura parcial, não número.
MINIMO_DIGITOS_CHAVE = 5

#: Tipo reconhecido pelo classificador → campo que identifica o documento.
CAMPO_CHAVE = {
    "cpf": "cpf",
    "cin": "cpf",
    "cnh": "cnh",
    "rg": "rg",
    "titulo_eleitor": "titulo_eleitor",
    "cartao_sus": "cns",
}

_ROTULO_CAMPO = {
    "cpf": "CPF",
    "rg": "RG",
    "cnh": "registro da CNH",
    "titulo_eleitor": "título de eleitor",
    "cns": "Cartão SUS",
}

#: Código que acompanha o 409, para a tela distinguir duplicidade de outro conflito.
CODIGO_ERRO = "DOCUMENTO_DUPLICADO"


@dataclass(frozen=True)
class Duplicidade:
    """Um documento do caso que parece ser o mesmo, e por qual regra."""

    entrega_id: str
    arquivo: str
    regra: str
    explicacao: str
    itens: tuple[str, ...] = ()
    criado_em: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "entrega_id": self.entrega_id,
            "arquivo": self.arquivo,
            "regra": self.regra,
            "explicacao": self.explicacao,
            "itens": list(self.itens),
            "criado_em": self.criado_em,
        }


class DocumentoDuplicado(HTTPException):
    """409 com a lista de documentos parecidos.

    É `HTTPException` para os caminhos que já tratam uma — o envio em lote transforma
    a exceção no motivo de recusa do arquivo, sem saber de duplicidade. O corpo
    completo (`corpo`) sai pelo tratador registrado em `app/main.py`.
    """

    def __init__(self, duplicidades: list[Duplicidade], detalhe: str):
        super().__init__(status_code=409, detail=detalhe)
        self.duplicidades = list(duplicidades)

    def corpo(self) -> dict[str, Any]:
        return {
            "detail": self.detail,
            "codigo": CODIGO_ERRO,
            "duplicidades": [d.to_dict() for d in self.duplicidades],
        }


# ------------------------------------------------------------- regras puras


def _itens(bruto: Any) -> list[str]:
    if isinstance(bruto, (list, tuple)):
        return [str(i) for i in bruto]
    try:
        valor = json.loads(bruto or "[]")
    except (TypeError, ValueError):
        return []
    return [str(i) for i in valor] if isinstance(valor, list) else []


def _data(iso: Any) -> str:
    achado = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(iso or ""))
    return f"{achado.group(3)}/{achado.group(2)}/{achado.group(1)}" if achado else ""


def _detectado(entrega: dict[str, Any]) -> str | None:
    """O tipo que o classificador (ou a correção humana) gravou no documento."""
    tipo = entrega.get("tipo_detectado") or (
        ((entrega.get("extracao") or {}).get("tipo") or {}).get("detectado")
    )
    return None if not tipo or tipo == "desconhecido" else str(tipo)


def tipo_da_entrega(
    entrega: dict[str, Any], categoria: Categoria | None, conhecidos: set[str]
) -> str | None:
    """O tipo do glossário deste documento.

    Em ordem de autoridade: o tipo pedido explicitamente (reclassificação em curso);
    o tipo gravado por uma pessoa; o tipo do item de checklist em que o documento
    está; o tipo reconhecido pelo classificador. O item vem antes do classificador
    porque o roteamento pode ter corrigido o palpite dele — a CAT que o classificador
    leu como CTPS e a leitura semântica levou para o item da CAT.
    """
    explicito = entrega.get("tipo_documento")
    if explicito:
        return str(explicito)
    detectado = _detectado(entrega)
    if entrega.get("roteamento_origem") == "humano" and detectado in conhecidos:
        return detectado
    itens = _itens(entrega.get("itens_atendidos"))
    if categoria is not None and itens:
        item = next((i for i in categoria.itens if i.codigo == itens[0]), None)
        if item is not None and item.tipo_documento:
            return item.tipo_documento
    if detectado in conhecidos:
        return detectado
    return None


def chave_do_documento(extracao: dict[str, Any], tipo_detectado: str | None) -> str | None:
    """O número que identifica o documento, quando ele foi lido e é válido."""
    campo = CAMPO_CHAVE.get(tipo_detectado or "")
    if not campo:
        return None
    for lido in extracao.get("campos") or []:
        if not isinstance(lido, dict) or lido.get("nome") != campo:
            continue
        if lido.get("valido") is False:
            continue
        numero = re.sub(r"[^0-9X]", "", str(lido.get("valor") or "").upper())
        if len(re.sub(r"\D", "", numero)) >= MINIMO_DIGITOS_CHAVE:
            return f"{campo}:{numero}"
    return None


def texto_da_extracao(extracao: dict[str, Any]) -> str:
    texto = str(extracao.get("texto_completo") or "")
    if texto.strip():
        return texto
    return "\n".join(
        str(linha.get("texto") or "")
        for linha in extracao.get("texto_linhas") or []
        if isinstance(linha, dict)
    )


def _palavras(texto: str) -> list[str]:
    return re.findall(r"[A-Z0-9]+", normalizar(texto))


def similaridade(texto_a: str, texto_b: str) -> float | None:
    """Jaccard dos trigramas de palavras. `None` quando falta texto para comparar."""
    palavras_a, palavras_b = _palavras(texto_a), _palavras(texto_b)
    if len(palavras_a) < MINIMO_PALAVRAS or len(palavras_b) < MINIMO_PALAVRAS:
        return None
    trigramas_a = {tuple(palavras_a[i : i + 3]) for i in range(len(palavras_a) - 2)}
    trigramas_b = {tuple(palavras_b[i : i + 3]) for i in range(len(palavras_b) - 2)}
    uniao = trigramas_a | trigramas_b
    return len(trigramas_a & trigramas_b) / len(uniao) if uniao else None


def comparar(
    nova: dict[str, Any],
    existente: dict[str, Any],
    categoria: Categoria | None,
    conhecidos: set[str],
) -> Duplicidade | None:
    """Aplica as três regras, na ordem, e devolve a primeira que casar."""
    base = {
        "entrega_id": str(existente.get("id") or ""),
        "arquivo": str(existente.get("arquivo") or ""),
        "itens": tuple(_itens(existente.get("itens_atendidos"))),
        "criado_em": str(existente.get("criado_em") or ""),
    }

    sha_nova = str(nova.get("conteudo_sha256") or "").strip().lower()
    if sha_nova and sha_nova == str(existente.get("conteudo_sha256") or "").strip().lower():
        return Duplicidade(regra=IDENTICO, explicacao="arquivo idêntico", **base)

    extracao_nova = nova.get("extracao") or {}
    extracao_existente = existente.get("extracao") or {}

    detectado = _detectado(nova)
    if detectado and detectado == _detectado(existente):
        chave = chave_do_documento(extracao_nova, detectado)
        if chave and chave == chave_do_documento(extracao_existente, detectado):
            campo = chave.split(":", 1)[0]
            return Duplicidade(
                regra=MESMO_NUMERO,
                explicacao=f"mesmo número de {_ROTULO_CAMPO.get(campo, campo)}",
                **base,
            )

    tipo = tipo_da_entrega(nova, categoria, conhecidos)
    if tipo and tipo == tipo_da_entrega(existente, categoria, conhecidos):
        indice = similaridade(
            texto_da_extracao(extracao_nova), texto_da_extracao(extracao_existente)
        )
        if indice is not None and indice >= LIMIAR_TEXTO:
            return Duplicidade(
                regra=MESMO_CONTEUDO,
                explicacao=f"mesmo tipo e {round(indice * 100)}% do texto em comum",
                **base,
            )
    return None


def mensagem(duplicidades: list[Duplicidade]) -> str:
    """A frase para quem enviou ou reclassificou. Vazia quando não há suspeita."""
    if not duplicidades:
        return ""
    primeira = duplicidades[0]
    quando = _data(primeira.criado_em)
    referencia = f"“{primeira.arquivo}”" + (f", enviado em {quando}" if quando else "")
    if primeira.regra == IDENTICO:
        texto = f"Este arquivo já está no caso: {referencia}."
    else:
        texto = f"Este documento parece repetir {referencia} ({primeira.explicacao})."
    if len(duplicidades) > 1:
        texto += f" Há mais {len(duplicidades) - 1} documento(s) parecido(s) no caso."
    return texto


# ------------------------------------------------------------- consultas


def sha_da_entrega(entrega_id: str) -> str | None:
    with conectar() as con:
        linha = con.execute(
            "SELECT conteudo_sha256 FROM entregas WHERE id = ?", (entrega_id,)
        ).fetchone()
    return str(linha["conteudo_sha256"]).strip() if linha and linha["conteudo_sha256"] else None


def identicos(
    caso_id: str, sha256: str | None, ignorar: str | None = None
) -> list[Duplicidade]:
    """Documentos do caso com exatamente estes bytes — em qualquer estado de leitura."""
    if not sha256:
        return []
    with conectar() as con:
        linhas = con.execute(
            """
            SELECT id, arquivo, itens_atendidos, criado_em
              FROM entregas
             WHERE caso_id = ? AND conteudo_sha256 = ? AND id <> ?
             ORDER BY criado_em
            """,
            (caso_id, sha256.strip().lower(), ignorar or ""),
        ).fetchall()
    return [
        Duplicidade(
            entrega_id=str(linha["id"]),
            arquivo=str(linha["arquivo"]),
            regra=IDENTICO,
            explicacao="arquivo idêntico",
            itens=tuple(_itens(linha["itens_atendidos"])),
            criado_em=str(linha["criado_em"] or ""),
        )
        for linha in linhas
    ]


def _json_ou_vazio(bruto: Any) -> dict[str, Any]:
    try:
        valor = json.loads(bruto or "{}")
    except (TypeError, ValueError):
        return {}
    return valor if isinstance(valor, dict) else {}


def procurar(
    caso_id: str, nova: dict[str, Any], categoria: Categoria | None
) -> list[Duplicidade]:
    """Documentos já lidos do caso que parecem ser o mesmo que `nova`.

    `nova` precisa de `id` (para não comparar o documento consigo mesmo),
    `conteudo_sha256`, `tipo_detectado`, `itens_atendidos`, `roteamento_origem` e
    `extracao`; `tipo_documento` entra quando a reclassificação já escolheu o tipo.

    O texto só é carregado para quem pode casar pela regra 2 ou 3: a extração é o
    maior campo da tabela, e um caso com cinquenta documentos não precisa trazer as
    cinquenta para comparar com um RG.
    """
    conhecidos = tipos_documento.codigos_conhecidos()
    tipo_nova = tipo_da_entrega(nova, categoria, conhecidos)
    detectado_nova = _detectado(nova)

    with conectar() as con:
        linhas = con.execute(
            """
            SELECT id, arquivo, item_codigo, itens_atendidos, tipo_detectado,
                   roteamento_origem, conteudo_sha256, criado_em
              FROM entregas
             WHERE caso_id = ? AND id <> ? AND status_proc = 'pronto'
             ORDER BY criado_em
            """,
            (caso_id, str(nova.get("id") or "")),
        ).fetchall()
        existentes = [
            {**dict(linha), "itens_atendidos": _itens(linha["itens_atendidos"])}
            for linha in linhas
        ]
        candidatos = [
            str(e["id"])
            for e in existentes
            if (detectado_nova and e.get("tipo_detectado") == detectado_nova)
            or (tipo_nova and tipo_da_entrega(e, categoria, conhecidos) == tipo_nova)
        ]
        textos: dict[str, Any] = {}
        if candidatos:
            marcadores = ",".join("?" for _ in candidatos)
            textos = {
                str(linha["id"]): linha["extracao_json"]
                for linha in con.execute(
                    f"SELECT id, extracao_json FROM entregas WHERE id IN ({marcadores})",
                    candidatos,
                ).fetchall()
            }

    achados: list[Duplicidade] = []
    for existente in existentes:
        existente["extracao"] = _json_ou_vazio(textos.get(str(existente["id"])))
        encontrada = comparar(nova, existente, categoria, conhecidos)
        if encontrada is not None:
            achados.append(encontrada)
    return achados
