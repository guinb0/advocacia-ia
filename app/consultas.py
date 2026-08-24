"""Consultas a bases públicas para adiantar o preenchimento da entrevista.

Hoje só CEP → endereço. É o único campo do roteiro que uma base pública e
gratuita resolve de verdade, e resolve bem: digitado o CEP, saem logradouro,
bairro, cidade e UF, e a atendente só confirma número e complemento com o
cliente. Em oito dígitos ela deixa de datilografar quatro campos.

O QUE NÃO DÁ PARA FAZER, e é bom estar escrito:

- **CPF não vira nome.** Não existe API pública e gratuita que devolva os dados
  de um CPF. A consulta oficial é da Receita Federal, exige certificado digital
  e convênio; os sites que prometem isso vendem base vazada, e usar uma delas
  põe o escritório do lado errado da LGPD. O que dá para fazer com o CPF é o que
  já está feito: conferir o dígito verificador (ver `validators.validar_cpf`).
- **PIS/NIT não vira vínculo.** O CNIS é do INSS e pede procuração e login gov.br
  do próprio cliente — não é consulta de servidor.

Por que passa pelo nosso backend, e não direto do navegador:

1. O provedor pode cair. Com dois (BrasilAPI e ViaCEP), a queda de um não trava a
   entrevista — e a troca fica num lugar só.
2. Cache. O mesmo CEP é consultado várias vezes por dia num escritório; guardar
   evita bater na base pública a cada tecla.
3. O navegador do advogado não fala com terceiros. Sai daqui apenas o CEP —
   nenhum nome, CPF ou identificador do caso acompanha a consulta.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

import httpx

log = logging.getLogger("consultas")

TEMPO_LIMITE_S = 4.0
#: Cache simples de processo. CEP muda com obra na cidade, não durante o dia.
LIMITE_CACHE = 2_000

_cache: dict[str, dict[str, Any]] = {}
_trava = threading.Lock()


class ErroConsulta(Exception):
    """Falha que o usuário precisa ver — CEP inexistente ou base fora do ar."""


def normalizar_cep(cep: str) -> str:
    return re.sub(r"\D", "", cep or "")


def formatar_cep(cep: str) -> str:
    d = normalizar_cep(cep)
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else cep


def _montar_endereco(logradouro: str, bairro: str, cidade: str, uf: str, cep: str) -> str:
    """O texto que cai no campo de endereço do roteiro.

    O número fica marcado como pendente de propósito: o CEP não o entrega, e um
    endereço sem número não serve para citação nem para petição. Melhor um
    espaço visível para preencher do que um endereço que parece completo.
    """
    partes = [p for p in (logradouro, "nº ___") if p]
    resto = [p for p in (bairro, f"{cidade}/{uf}".strip("/"), f"CEP {formatar_cep(cep)}") if p]
    return ", ".join([", ".join(partes), *resto]) if partes else ", ".join(resto)


def _da_brasilapi(dados: dict[str, Any]) -> dict[str, Any]:
    return {
        "cep": formatar_cep(dados.get("cep", "")),
        "logradouro": (dados.get("street") or "").strip(),
        "bairro": (dados.get("neighborhood") or "").strip(),
        "cidade": (dados.get("city") or "").strip(),
        "uf": (dados.get("state") or "").strip(),
        "fonte": "BrasilAPI",
    }


def _do_viacep(dados: dict[str, Any]) -> dict[str, Any]:
    return {
        "cep": formatar_cep(dados.get("cep", "")),
        "logradouro": (dados.get("logradouro") or "").strip(),
        "bairro": (dados.get("bairro") or "").strip(),
        "cidade": (dados.get("localidade") or "").strip(),
        "uf": (dados.get("uf") or "").strip(),
        "fonte": "ViaCEP",
    }


def limpar_cache() -> None:
    with _trava:
        _cache.clear()


async def _tentar_provedores(
    http: httpx.AsyncClient, d: str
) -> tuple[dict[str, Any] | None, bool]:
    """Devolve (endereço, cep_inexistente). O segundo separa 'não existe' de
    'não respondeu' — a mensagem na tela é bem diferente nos dois casos."""
    inexistente = False
    for url, converter in (
        (f"https://brasilapi.com.br/api/cep/v2/{d}", _da_brasilapi),
        (f"https://viacep.com.br/ws/{d}/json/", _do_viacep),
    ):
        try:
            r = await http.get(url)
            if r.status_code == 404:
                inexistente = True
                continue
            r.raise_for_status()
            corpo = r.json()
            # O ViaCEP responde 200 com {"erro": true} para CEP inexistente.
            if isinstance(corpo, dict) and str(corpo.get("erro", "")).lower() in ("true", "1"):
                inexistente = True
                continue
            return converter(corpo), inexistente
        except Exception as exc:
            log.warning("Consulta de CEP falhou em %s: %s", url, str(exc)[:120])
    return None, inexistente


async def buscar_cep(cep: str, http: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Endereço do CEP, do primeiro provedor que responder.

    Levanta `ErroConsulta` quando o CEP não existe em nenhuma das bases ou
    quando as duas estão inacessíveis — a mensagem é para a tela.

    `http` existe para o teste injetar um transporte falso: bater na base
    pública de verdade faria a suíte depender de rede e do humor de terceiros.
    """
    d = normalizar_cep(cep)
    if len(d) != 8:
        raise ErroConsulta("CEP precisa ter 8 dígitos.")

    with _trava:
        if d in _cache:
            return _cache[d]

    if http is not None:
        achado, inexistente = await _tentar_provedores(http, d)
    else:
        async with httpx.AsyncClient(timeout=TEMPO_LIMITE_S) as cliente:
            achado, inexistente = await _tentar_provedores(cliente, d)

    if achado is None:
        if inexistente:
            raise ErroConsulta("CEP não encontrado. Confira o número com o cliente.")
        raise ErroConsulta("As bases de CEP não responderam. Preencha o endereço à mão.")

    achado["endereco_formatado"] = _montar_endereco(
        achado["logradouro"], achado["bairro"], achado["cidade"], achado["uf"], d
    )

    with _trava:
        if len(_cache) >= LIMITE_CACHE:
            _cache.clear()  # cache de escritório: esvaziar é mais barato que LRU
        _cache[d] = achado
    return achado
