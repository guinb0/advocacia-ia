"""A que item do checklist um documento pertence — decidido pelo documento, e não pelo campo em que ele foi enviado.

O QUE MUDA

Antes, o item era escolhido pelo cliente na hora do envio, e essa escolha era
final: um comprovante de residência mandado no campo do CPF virava
`tipo_confere=False`, o item caía em "a conferir" e a tela dizia "precisa
reenviar" — para um documento perfeitamente válido, que só estava na linha
errada. O comprovante ficava preso no item errado, e o item certo, vazio.

Aqui a escolha de quem envia passa a ser um palpite, e o documento decide.

AS DUAS FONTES, NESTA ORDEM

1. `extractors.classificar` — determinístico, por palavras-chave com peso.
   Conhece os nove tipos cadastrais (RG, CPF, CIN, CNH, CTPS, título, SUS,
   comprovante de residência, certidão) e só afirma acima do próprio limiar.
   Quando ele fala, é ele quem manda: não é opinião de modelo, é o mesmo
   classificador de que o checklist já dependia para acusar troca de arquivo.

2. `valor_documento.ler` — o modelo de linguagem lendo o texto do OCR. É a
   ÚNICA fonte para os documentos que decidem a ação (CAT, laudo, atestado,
   CNIS, contracheque, boletim), porque para esses não existe classificador.
   O que vem daqui entra rotulado como `semantico` e carrega o motivo, para a
   tela do advogado poder dizer "classificado automaticamente — confira".

O QUE ELE NÃO FAZ

Não inventa destino: sem evidência de nenhuma das duas fontes, o documento fica
EM TRIAGEM — visível ao advogado, com o arquivo guardado, esperando um clique.
Chutar um item marcaria um obrigatório como cumprido sem documento que o
cumprisse, e a petição sairia com o documento errado.

Não sobrepõe a escolha de quem enviou por opinião fraca: havendo item escolhido,
o desvio automático exige ou o classificador determinístico, ou uma indicação
semântica única e sem ambiguidade.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from . import casos, valor_documento
from .categorias import ITEM_TRIAGEM, Categoria, ItemChecklist

log = logging.getLogger("roteamento")

__all__ = [
    "ITEM_TRIAGEM", "Destino", "decidir",
    "ESCOLHA", "DETERMINISTICO", "SEMANTICO", "HUMANO", "TRIAGEM",
]

ESCOLHA = "escolha"                # o item veio de quem enviou, e o documento não o desmente
DETERMINISTICO = "deterministico"  # o classificador de tipos reconheceu o documento
SEMANTICO = "semantico"            # só o modelo de linguagem soube dizer
HUMANO = "humano"                  # alguém do escritório atribuiu à mão
TRIAGEM = "triagem"                # ninguém soube: espera na fila de triagem


@dataclass(frozen=True)
class Destino:
    """A que itens o documento responde, e por causa de quem."""

    itens: list[str] = field(default_factory=list)
    origem: str = TRIAGEM
    confianca: int = 0
    motivo: str = ""
    #: A leitura do modelo, quando houve — a task a reaproveita como
    #: `classificacao_semantica` em vez de pagar uma segunda chamada.
    analise: dict[str, Any] | None = None

    @property
    def em_triagem(self) -> bool:
        return not self.itens


def _itens_por_tipo(categoria: Categoria, tipo: str) -> list[ItemChecklist]:
    return [i for i in categoria.itens if i.tipo_ocr == tipo]


def _deterministico(
    extracao: dict[str, Any], categoria: Categoria
) -> tuple[list[str], int, str] | None:
    """O que o classificador de tipos afirma, traduzido em itens do checklist."""
    tipo = extracao.get("tipo", {}) or {}
    detectado = tipo.get("detectado")
    if not detectado or detectado == "desconhecido":
        return None

    # CIN e CNH trazem identidade e CPF no mesmo arquivo, e só valem pelos dois
    # quando os dados saíram legíveis — a mesma regra do envio manual.
    if casos.cobre_rg_e_cpf(extracao):
        rg_cpf = [i.codigo for i in categoria.itens if i.tipo_ocr in {"rg", "cpf"}]
        if len(rg_cpf) == 2:
            rotulo = tipo.get("descricao_detectado") or detectado
            return rg_cpf, 95, f"{rotulo} legível: vale como identidade e como CPF."

    encontrados = _itens_por_tipo(categoria, detectado)
    if not encontrados:
        return None

    pontos = int(tipo.get("confianca_classificacao") or 0)
    # O classificador só devolve tipo acima de 10 pontos; daí para cima a
    # confiança sobe com a evidência, sem nunca virar certeza absoluta.
    confianca = max(70, min(95, 60 + pontos))
    rotulo = tipo.get("descricao_detectado") or detectado
    return (
        [i.codigo for i in encontrados],
        confianca,
        f"O documento foi reconhecido como {rotulo}.",
    )


def _semantico(
    extracao: dict[str, Any], categoria: Categoria
) -> tuple[list[str], int, str, dict[str, Any]] | None:
    """A leitura do modelo, restrita aos itens DESTE checklist.

    Diferente da leitura sob demanda da tela, aqui vão TODOS os itens, e não só
    os pendentes: um segundo atestado médico continua sendo atestado médico, e
    esconder o item já entregue faria o modelo procurar outro lugar para ele.
    """
    if not (extracao.get("validacao", {}) or {}).get("texto_utilizavel"):
        return None

    itens = [{"codigo": i.codigo, "nome": i.nome} for i in categoria.itens]
    try:
        analise = valor_documento.ler(extracao, itens, categoria.nome)
    except valor_documento.ErroValor as exc:
        # Modelo fora do ar, ou texto curto demais: o documento fica em triagem,
        # que é honesto. Derrubar a leitura inteira por isso perderia o OCR.
        log.info("leitura semântica indisponível: %s", str(exc)[:160])
        return None

    # Saída de modelo nunca vira chave estrangeira por confiança. Mesmo instruído
    # com os itens válidos, ele pode inventar um código ou repetir o mesmo item;
    # ambos fariam o arquivo desaparecer da tela (não estaria nem no checklist,
    # nem na triagem). Filtramos pelo checklist real antes de decidir o destino.
    validos = {i.codigo for i in categoria.itens}
    codigos = list(
        dict.fromkeys(
            str(s.get("item"))
            for s in analise.get("serve_para", [])
            if s.get("item") and str(s.get("item")) in validos
        )
    )
    if not codigos:
        return None

    porque = next(
        (str(s.get("porque")) for s in analise.get("serve_para", []) if s.get("porque")),
        "",
    )
    documento = analise.get("documento") or "documento"
    motivo = f"Lido como {documento}" + (f": {porque}" if porque else ".")
    # A confiança não passa de 65: é leitura de modelo, e a tela precisa poder dizê-lo.
    return codigos[:2], 65, motivo[:600], analise


def decidir(
    extracao: dict[str, Any],
    categoria: Categoria,
    item_escolhido: ItemChecklist | None = None,
) -> Destino:
    """Para onde vai este documento.

    `item_escolhido` é o que o cliente marcou na tela, quando marcou alguma
    coisa. Ele é respeitado enquanto o documento não o desmentir.
    """
    det = _deterministico(extracao, categoria)
    if det is not None:
        itens, confianca, motivo = det
        if item_escolhido is None:
            return Destino(itens, DETERMINISTICO, confianca, motivo)
        if item_escolhido.codigo in itens:
            return Destino(itens, ESCOLHA, confianca, motivo)
        # Divergência com evidência: o arquivo é de outro item, e é para lá que vai.
        return Destino(
            itens,
            DETERMINISTICO,
            confianca,
            f"Enviado em '{item_escolhido.nome}'. {motivo}"[:600],
        )

    sem = _semantico(extracao, categoria)
    if sem is not None:
        itens, confianca, motivo, analise = sem
        if item_escolhido is None:
            return Destino(itens, SEMANTICO, confianca, motivo, analise)
        if item_escolhido.codigo in itens:
            return Destino([item_escolhido.codigo], ESCOLHA, confianca, motivo, analise)
        # Só desvia da escolha de quem enviou quando a leitura aponta UM item, e
        # sem ambiguidade. Duas indicações fracas não derrubam uma escolha humana.
        if len(itens) == 1:
            return Destino(
                itens,
                SEMANTICO,
                confianca,
                f"Enviado em '{item_escolhido.nome}'. {motivo}"[:600],
                analise,
            )
        return Destino([item_escolhido.codigo], ESCOLHA, 40, motivo, analise)

    if item_escolhido is not None:
        # Nada a acrescentar: fica onde quem enviou o pôs, como sempre foi.
        return Destino([item_escolhido.codigo], ESCOLHA, 30, "")

    return Destino(
        [],
        TRIAGEM,
        0,
        "Não foi possível identificar a que documento do checklist este arquivo responde.",
    )
