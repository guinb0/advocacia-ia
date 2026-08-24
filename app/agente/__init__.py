"""Módulo do agente jurídico dentro do Acervo.

O agente é o serviço `ia-juridica`: ele guarda o Case State (fato com proveniência,
classificação, pendência do playbook, jurisprudência) e roda os modelos. Este pacote
é a **ponte** — nada de regra jurídica mora aqui.

    OCR (este repositório)                 agente (ia-juridica)
    ─────────────────────                  ────────────────────
    caso, cliente, checklist      ──push──▶ caso espelhado
    extração de cada documento    ──push──▶ fato com proveniência
    contrato preenchido           ──confere▶ divergência com os documentos
    painel do advogado            ◀──read── classificação, pendência, precedentes

Por que ponte e não cópia do agente aqui dentro: o OCR satura CPU com PaddleOCR e o
agente espera I/O de LLM e banco. No mesmo processo, um segura o outro — e as 15
migrations e a suíte do agente viriam junto para dentro de um repositório que hoje
sobe com `iniciar.ps1` numa máquina de escritório.
"""

from .cliente import (
    AgenteIndisponivel,
    AgenteNaoConfigurado,
    Cliente,
    ErroDoAgente,
)
from .config import config
from .rotas import roteador

__all__ = [
    "AgenteIndisponivel",
    "AgenteNaoConfigurado",
    "Cliente",
    "ErroDoAgente",
    "config",
    "roteador",
]
