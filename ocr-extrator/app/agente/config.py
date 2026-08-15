"""Configuração da ligação com o agente jurídico.

O agente é **outro serviço**, com repositório, banco e ciclo de vida próprios. Aqui
só mora o endereço dele e os prazos com que este processo aceita esperar.

Vazio DESLIGA a integração, como já acontece com a ZapSign e o Keycloak: sem
`AGENTE_API_URL` o OCR continua inteiro — lê documento, monta checklist, gera
contrato —, e as telas do agente explicam que a ligação não está configurada em vez
de mostrar tela vazia.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = ["Config", "config"]


@dataclass(frozen=True)
class Config:
    url: str
    token: str
    organizacao: str
    #: Prazo das chamadas que o advogado espera olhando a tela.
    timeout: float
    #: Prazo do envio de documento, que roda em segundo plano e pode esperar mais.
    timeout_envio: float

    @property
    def ligado(self) -> bool:
        return bool(self.url)


def config() -> Config:
    """Lida a cada chamada, não no import.

    O `.env` é carregado por `app.rag.carregar_env()` durante o import do pacote, e
    congelar a configuração aqui faria o valor depender da ordem dos imports — o tipo
    de defeito que só aparece em produção, onde a ordem é outra.
    """
    return Config(
        url=os.getenv("AGENTE_API_URL", "").rstrip("/"),
        token=os.getenv("AGENTE_TOKEN", "").strip(),
        # Enquanto o Keycloak não emite `organization_id` (ver o plano em
        # docs/PLANO-BANCOS.md), o agente roda com AUTH_ENABLED=false e usa a
        # organização de desenvolvimento. Este valor existe para o dia em que o token
        # do advogado carregar a claim — aí ele passa a vir do token, não daqui.
        organizacao=os.getenv("AGENTE_ORGANIZACAO", "").strip(),
        timeout=float(os.getenv("AGENTE_TIMEOUT", "20")),
        timeout_envio=float(os.getenv("AGENTE_TIMEOUT_ENVIO", "60")),
    )
