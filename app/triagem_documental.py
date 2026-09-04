"""Sugere a categoria do caso a partir de um lote de documentos, antes de o caso existir.

MESMO MOTOR DA TRIAGEM DA ENTREVISTA (`app/triagem.py`): concatena o texto que o
OCR leu de cada documento e chama `triagem.triar` sobre esse texto agregado — as
mesmas pistas por palavra-chave e a mesma chamada ao modelo que já classificam um
relato servem aqui, porque o que muda é só a origem do texto (documento em vez de
entrevista falada).

Só sugere. Não cria caso nem escolhe sozinho — mesmo princípio de
`app/roteamento.py`: quem confirma é o advogado.
"""

from __future__ import annotations

from typing import Any

from . import triagem

#: Quanto do texto de CADA documento entra no resumo. Um processo de INSS
#: inteiro tem páginas de tabela que não ajudam a classificar e só empurrariam
#: para fora do resumo o texto de documentos de outros itens.
CARACTERES_POR_DOCUMENTO = 1500

#: Teto do resumo inteiro — o mesmo limite que `triagem.classificar_com_llm` já
#: aplica ao relato de entrevista (12000 caracteres), com folga para o preâmbulo.
CARACTERES_TOTAL = 11000

PREAMBULO = (
    "O texto abaixo não é uma entrevista: é a leitura por OCR de vários "
    "documentos que o cliente entregou para o mesmo caso. Cada seção começa "
    "com '### Documento:' e o tipo que o sistema já reconheceu naquele "
    "arquivo, quando reconheceu. Decida a categoria pelo CONJUNTO dos "
    "documentos, não por um único arquivo isolado.\n\n"
)


def _descricao_tipo(extracao: dict[str, Any]) -> str:
    tipo = extracao.get("tipo") or {}
    return tipo.get("descricao_detectado") or tipo.get("detectado") or "não identificado"


def _resumo(arquivos: list[dict[str, Any]]) -> str:
    partes = []
    for item in arquivos:
        texto = (item.get("texto_completo") or "").strip()
        if not texto:
            continue
        nome = item.get("nome") or "documento"
        partes.append(
            f"### Documento: {nome}\n"
            f"Tipo reconhecido: {_descricao_tipo(item)}\n"
            f"{texto[:CARACTERES_POR_DOCUMENTO]}"
        )
    return "\n\n".join(partes)[:CARACTERES_TOTAL]


def sugerir_por_documentos(arquivos: list[dict[str, Any]]) -> dict[str, Any]:
    """`arquivos`: saída de `pipeline.processar` para cada arquivo do lote, com `nome` acrescentado.

    Devolve o mesmo formato de `triagem.triar` (sugestões, confiança, motivo),
    acrescido de `documentos`: o que foi lido de cada arquivo, para o advogado
    conferir a evidência por trás da sugestão.
    """
    documentos = [
        {"nome": a.get("nome"), "tipo_detectado": (a.get("tipo") or {}).get("detectado")}
        for a in arquivos
    ]

    resumo = _resumo(arquivos)
    if not resumo.strip():
        return {
            "sugestoes": [],
            "confiante": False,
            "motivo": "Nenhum dos documentos teve texto legível pelo OCR.",
            "documentos": documentos,
        }

    resultado = triagem.triar(PREAMBULO + resumo)
    resultado["documentos"] = documentos
    return resultado
