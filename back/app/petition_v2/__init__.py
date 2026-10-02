"""Pipeline V2 de petições.

Esta árvore não importa os higienizadores, auditores mutáveis ou construtores
de pedidos da V1. A entrada HTTP escolhe esta pipeline por feature flag.
"""

from .state import CaseStateV2, finalizar_plano

__all__ = ["CaseStateV2", "finalizar_plano"]
