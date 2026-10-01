"""Camada jurídica verificada da geração de petições.

Três camadas que nunca se misturam:

A. FATOS DO CASO — só documentos, entrevista, cadastro e confirmação humana (`fatos`).
B. BASE JURÍDICA OFICIAL — normas e precedentes com vigência, versão e fonte oficial (`autoridades`).
C. ESTILO E ESTRATÉGIA — skill do escritório e peças do acervo. Dizem COMO escrever e QUAIS teses
   considerar; nunca são fonte da existência, do texto ou da vigência de uma norma.

Fluxo: matriz de fatos → issue spotting → pesquisa jurídica → cálculos → PETITION_PLAN → redação →
quatro auditores.

`PETICAO_PIPELINE_JURIDICO_MODE`:
  off     (padrão) fluxo legado, sem a camada.
  shadow  a peça entregue é a do fluxo legado; a camada roda ao lado, audita essa peça e grava no
          trace o que mudaria (teses, citações, valor da causa). Não altera prontidão nem texto.
  strict  a peça é gerada pela camada. Falha em fatos, teses, autoridades, cálculos ou auditores
          impede a peça de ser marcada como pronta — nunca há queda silenciosa para o legado.
`PETICAO_PIPELINE_JURIDICO=1` (nome antigo) equivale a strict.
"""

from __future__ import annotations

import os

DESLIGADO, SHADOW, STRICT = "off", "shadow", "strict"


def modo() -> str:
    bruto = os.getenv("PETICAO_PIPELINE_JURIDICO_MODE", "").strip().lower()
    if bruto in (DESLIGADO, SHADOW, STRICT):
        return bruto
    if os.getenv("PETICAO_PIPELINE_JURIDICO", "0").strip().lower() in ("1", "true", "sim", "on"):
        return STRICT
    return DESLIGADO


def ativo() -> bool:
    return modo() != DESLIGADO


def estrito() -> bool:
    return modo() == STRICT


def sombra() -> bool:
    return modo() == SHADOW
