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

`PETICAO_MOTOR_JURIDICO` (padrão 1) — modo ASSISTIDO do fluxo legado (só quando o modo acima é off): o motor
(grafo, prova, contrateses, proposições, scores) roda em segundo plano; se ficar pronto a tempo, orienta o
aprofundamento dos capítulos vulneráveis; no fim, audita a peça e põe lacunas, defesas e CRÍTICOS no relatório
do advogado. Nunca derruba nem atrasa a geração além do teto curto de espera.
`PETICAO_MODELO_RACIOCINIO`: modelo do issue spotting, contrateses e classificação de proposições (padrão:
o mesmo da redação).
"""

from __future__ import annotations

import os

DESLIGADO, SHADOW, STRICT = "off", "shadow", "strict"
ASSISTIDO = "assistido"


def assistido() -> bool:
    if modo() != DESLIGADO:
        return False
    return os.getenv("PETICAO_MOTOR_JURIDICO", "1").strip().lower() in ("1", "true", "sim", "on")


def modelo_raciocinio() -> str:
    return os.getenv("PETICAO_MODELO_RACIOCINIO", "").strip()


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
