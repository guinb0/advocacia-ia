"""Cliente único para os modelos de linguagem usados no sistema.

ANTES, três chamadores (`triagem.py`, `valor_documento.py`, `rag.py`) reimplementavam
a MESMA chamada HTTP à DeepSeek cada um do seu jeito — três lugares para trocar de
provedor, três formatos de tratar chave ausente, três timeouts escolhidos à mão.

Este módulo padroniza só o TRANSPORTE: ler a chave certa, montar a chamada no
formato do provedor, decodificar a resposta e levantar um erro único e claro. O
PROMPT continua em cada chamador — escolher categoria, interpretar um documento
e cruzar precedentes são pedidos diferentes, e forçar um prompt genérico aqui
pioraria os três.

TROCAR DE PROVEDOR É UMA VARIÁVEL, NÃO UM DEPLOY
    LLM_PROVEDOR=deepseek     (padrão — mais barato, já em uso)
    LLM_PROVEDOR=openai
    LLM_PROVEDOR=anthropic

Cada provedor lê sua própria chave e modelo (`DEEPSEEK_API_KEY`/`DEEPSEEK_MODEL`,
`OPENAI_API_KEY`/`OPENAI_MODEL`, `ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL`) — dá para
deixar todas configuradas e só virar `LLM_PROVEDOR` quando quiser comparar
custo/qualidade, sem tocar em código.

DOIS FORMATOS DE API, NÃO UM
    DeepSeek e OpenAI falam o mesmo dialeto (`chat/completions`, mensagens
    system/user, `response_format: json_object`). A Anthropic fala outro
    (`/v1/messages`, header `x-api-key` em vez de `Authorization: Bearer`,
    `max_tokens` OBRIGATÓRIO, e sem modo JSON nativo — o contrato de "responda
    só JSON" depende do prompt, que todos os chamadores já escrevem assim).
    Por isso os dois formatos têm função de chamada própria; o que os três
    chamadores veem continua sendo só `chamar(instrucao, mensagem)`.

SOBRE OS MODELOS DA OPENAI: os nomes que aparecem no Codex (GPT-5.6
Terra/Sol/Luna) são apelidos de produto, não necessariamente o identificador
que a API pública aceita em `model`. Confirme o identificador real no painel
da OpenAI antes de apontar `OPENAI_MODEL` para ele.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("llm")

#: Quando quem chama não pede um teto, este é o usado. Existe sobretudo pela
#: Anthropic, que EXIGE `max_tokens` em toda chamada — sem isto a primeira
#: troca para `anthropic` quebraria toda análise que não passa o parâmetro.
MAX_TOKENS_PADRAO = 4096


class ErroLLM(Exception):
    """Falha ao chamar o modelo — chave ausente, provedor fora do ar, resposta ilegível."""


@dataclass(frozen=True)
class _Provedor:
    codigo: str
    formato: str  # "openai" | "anthropic"
    base_url_padrao: str
    modelo_padrao: str
    variavel_chave: str
    variavel_modelo: str
    variavel_base_url: str


PROVEDORES: dict[str, _Provedor] = {
    "deepseek": _Provedor(
        codigo="deepseek",
        formato="openai",
        base_url_padrao="https://api.deepseek.com",
        modelo_padrao="deepseek-chat",
        variavel_chave="DEEPSEEK_API_KEY",
        variavel_modelo="DEEPSEEK_MODEL",
        variavel_base_url="DEEPSEEK_BASE_URL",
    ),
    "openai": _Provedor(
        codigo="openai",
        formato="openai",
        base_url_padrao="https://api.openai.com/v1",
        # Sem padrão de propósito: "gpt-5.6-terra" é o apelido do Codex, não
        # confirmado como identificador de API. Forçar um valor aqui seria
        # adivinhar — melhor falhar com uma mensagem clara do que chamar o
        # modelo errado sem ninguém perceber.
        modelo_padrao="",
        variavel_chave="OPENAI_API_KEY",
        variavel_modelo="OPENAI_MODEL",
        variavel_base_url="OPENAI_BASE_URL",
    ),
    "anthropic": _Provedor(
        codigo="anthropic",
        formato="anthropic",
        base_url_padrao="https://api.anthropic.com/v1",
        # Haiku 4.5 — o mais barato/rápido da família, para os primeiros testes.
        # Troque via ANTHROPIC_MODEL quando quiser comparar com Sonnet/Opus.
        modelo_padrao="claude-haiku-4-5-20251001",
        variavel_chave="ANTHROPIC_API_KEY",
        variavel_modelo="ANTHROPIC_MODEL",
        variavel_base_url="ANTHROPIC_BASE_URL",
    ),
}


def _env_local() -> Path:
    return Path(__file__).resolve().parent.parent / "dados" / ".env.local"


def _chave_do_arquivo_local(variavel: str) -> str:
    """Fallback de desenvolvimento: `dados/.env.local` não entra no versionamento.

    Existia só dentro de `triagem.py`; generalizado aqui para os chamadores
    ganharem o mesmo atalho sem precisar exportar a variável no shell.
    """
    caminho = _env_local()
    if not caminho.is_file():
        return ""
    prefixo = f"{variavel}="
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.startswith(prefixo):
            return linha[len(prefixo):].strip()
    return ""


def provedor_ativo() -> str:
    return os.getenv("LLM_PROVEDOR", "deepseek").strip().lower()


def _provedor() -> _Provedor:
    codigo = provedor_ativo()
    provedor = PROVEDORES.get(codigo)
    if provedor is None:
        raise ErroLLM(
            f"LLM_PROVEDOR='{codigo}' desconhecido. Use um de: {', '.join(PROVEDORES)}."
        )
    return provedor


def _chave(provedor: _Provedor) -> str:
    return os.getenv(provedor.variavel_chave, "").strip() or _chave_do_arquivo_local(
        provedor.variavel_chave
    )


def disponivel() -> bool:
    """O provedor ativo tem chave configurada? Quem chama decide o fallback."""
    try:
        return bool(_chave(_provedor()))
    except ErroLLM:
        return False


def _extrair_json(texto: str) -> dict[str, Any]:
    """Decodifica o JSON da resposta, tolerando o que os modelos fazem mesmo
    quando a instrução pede "responda só JSON": cercar com ```json ... ``` ou
    acrescentar uma frase antes/depois do objeto.
    """
    bruto = texto.strip()
    if bruto.startswith("```"):
        bruto = re.sub(r"^```(?:json)?\s*", "", bruto)
        bruto = re.sub(r"\s*```$", "", bruto)
    try:
        return json.loads(bruto)
    except json.JSONDecodeError:
        inicio, fim = bruto.find("{"), bruto.rfind("}")
        if inicio != -1 and fim > inicio:
            return json.loads(bruto[inicio : fim + 1])
        raise


def _chamar_openai(
    provedor: _Provedor, chave: str, modelo: str, base_url: str,
    instrucao: str, mensagem: str, temperatura: float, max_tokens: int, timeout: float,
) -> str:
    resposta = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {chave}"},
        json={
            "model": modelo,
            "temperature": temperatura,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": instrucao},
                {"role": "user", "content": mensagem},
            ],
        },
        timeout=timeout,
    )
    resposta.raise_for_status()
    return resposta.json()["choices"][0]["message"]["content"]


def _chamar_anthropic(
    provedor: _Provedor, chave: str, modelo: str, base_url: str,
    instrucao: str, mensagem: str, temperatura: float, max_tokens: int, timeout: float,
) -> str:
    resposta = httpx.post(
        f"{base_url}/messages",
        headers={
            "x-api-key": chave,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": modelo,
            "max_tokens": max_tokens,
            "temperature": temperatura,
            "system": instrucao,
            "messages": [{"role": "user", "content": mensagem}],
        },
        timeout=timeout,
    )
    resposta.raise_for_status()
    bloco = resposta.json().get("content") or []
    texto = "".join(p.get("text", "") for p in bloco if p.get("type") == "text")
    if not texto:
        raise ErroLLM("Resposta da Anthropic sem bloco de texto.")
    return texto


_CHAMADORES = {"openai": _chamar_openai, "anthropic": _chamar_anthropic}


def chamar(
    instrucao: str,
    mensagem: str,
    *,
    temperatura: float = 0,
    max_tokens: int | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    """Chama o provedor ativo pedindo JSON. Levanta `ErroLLM` em qualquer falha.

    Não decide fallback — isso é do domínio de quem chama (cair nas pistas
    locais, marcar o documento como "sem leitura automática" etc.). Este
    módulo só garante que a falha vem com um motivo claro.
    """
    provedor = _provedor()
    chave = _chave(provedor)
    if not chave:
        raise ErroLLM(
            f"{provedor.variavel_chave} não configurada "
            f"(provedor ativo: LLM_PROVEDOR={provedor.codigo})."
        )
    modelo = os.getenv(provedor.variavel_modelo, provedor.modelo_padrao).strip()
    if not modelo:
        raise ErroLLM(
            f"{provedor.variavel_modelo} não configurada para o provedor '{provedor.codigo}'."
        )
    base_url = os.getenv(provedor.variavel_base_url, provedor.base_url_padrao).rstrip("/")

    try:
        texto = _CHAMADORES[provedor.formato](
            provedor, chave, modelo, base_url,
            instrucao, mensagem, temperatura, max_tokens or MAX_TOKENS_PADRAO, timeout,
        )
    except httpx.HTTPError as exc:
        log.warning("chamada ao provedor '%s' falhou: %s", provedor.codigo, str(exc)[:200])
        raise ErroLLM(f"O modelo ({provedor.codigo}) não respondeu: {exc}") from exc

    try:
        return _extrair_json(texto)
    except Exception as exc:
        raise ErroLLM(f"Resposta ilegível do modelo ({provedor.codigo}).") from exc
