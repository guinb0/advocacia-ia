"""Pesquisa na web para tirar dúvida rápida, ao lado da petição.

POR QUE PELA OPENROUTER E NÃO PELA API DA DEEPSEEK

A busca na web que aparece no chat da DeepSeek **não existe na API dela**: o
`api.deepseek.com/chat/completions` só conhece o que está no prompt. Quem busca
é a OpenRouter, com o plugin `web` — ela pesquisa, injeta os resultados no
contexto e devolve as fontes em `annotations` (`url_citation`). O modelo que
redige continua sendo o DeepSeek, só que servido pela OpenRouter, com a chave
que já existe para a transcrição (`OPENROUTER_API_KEY`).

O QUE ISTO NÃO É

Não alimenta a petição nem o dossiê. A resposta vem da internet, e a internet
erra — no primeiro teste o modelo afirmou "2 anos" de prescrição para acidente de
trabalho sem distinguir contrato em curso de contrato extinto. Por isso a tela
mostra as fontes junto e pede conferência; nada daqui é gravado no caso.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from . import ambiente

ambiente.carregar()

log = logging.getLogger("pesquisa-web")

URL = "https://openrouter.ai/api/v1/chat/completions"

#: Modelo servido pela OpenRouter. Trocável sem mexer no código.
MODELO = os.getenv("OPENROUTER_MODELO_PESQUISA", "").strip() or "deepseek/deepseek-chat"

#: Quantas páginas o plugin traz para o contexto. Cada uma custa tokens de entrada.
MAX_RESULTADOS = int(ambiente.numero("PESQUISA_WEB_MAX_RESULTADOS", 5))

#: A busca + redação levou ~14s no teste; 90s cobre dia ruim sem prender para sempre.
TEMPO_LIMITE_S = ambiente.numero("PESQUISA_WEB_TIMEOUT_S", 90.0)

#: Pergunta de dúvida, não documento colado.
LIMITE_PERGUNTA = 1000

#: O formato é livre de propósito. A primeira versão pedia "curta, até ~250
#: palavras" e saía sempre o mesmo bloco engessado — um parágrafo e uma lista de
#: "Fontes:" repetindo o que a tela já mostra. Agora o tamanho e a estrutura
#: acompanham a pergunta; a tela (`RespostaFormatada`) entende markdown.
INSTRUCAO = (
    "Você apoia advogados brasileiros que estão redigindo uma petição e precisam "
    "tirar uma dúvida. Responda em português do Brasil usando os resultados da "
    "busca na web.\n\n"
    "Forma da resposta:\n"
    "- Comece pela resposta direta, em uma ou duas frases, sem preâmbulo.\n"
    "- Ajuste o tamanho à pergunta: dúvida simples cabe em um parágrafo; tema "
    "com requisitos, prazos, exceções ou divergência pede mais detalhe.\n"
    "- Use markdown quando ajudar a leitura: subtítulos (###), listas, **negrito** "
    "para o dado principal (prazo, valor, número de súmula ou artigo) e citação "
    "(>) para transcrever trecho de lei ou ementa. Não force estrutura em "
    "resposta curta.\n"
    "- Cite as fontes em linha, como links markdown junto da afirmação. NÃO "
    "termine com uma lista de fontes — a tela já mostra as fontes consultadas.\n\n"
    "Conteúdo:\n"
    "- Prefira fontes oficiais: planalto.gov.br, tribunais (STF, STJ, TST, TRFs, "
    "TJs, TRTs), CNJ e órgãos públicos.\n"
    "- Quando houver divergência jurisprudencial, exceções ou a resposta "
    "depender de detalhe do caso, diga isso explicitamente.\n"
    "- Se os resultados não sustentarem uma resposta segura, diga que não "
    "encontrou em vez de responder de memória."
)


class ErroPesquisa(Exception):
    """Falha que a tela mostra como está — mensagens já escritas para quem lê."""


def configurada() -> bool:
    return bool(os.getenv("OPENROUTER_API_KEY", "").strip())


def pesquisar(pergunta: str) -> dict[str, Any]:
    """Resposta + fontes. Levanta `ErroPesquisa` com texto pronto para a tela."""
    pergunta = (pergunta or "").strip()
    if not pergunta:
        raise ErroPesquisa("Escreva a pergunta que deseja pesquisar.")
    if len(pergunta) > LIMITE_PERGUNTA:
        raise ErroPesquisa(
            f"Pergunta longa demais ({len(pergunta)} caracteres; máximo {LIMITE_PERGUNTA})."
        )
    chave = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not chave:
        raise ErroPesquisa("Pesquisa na web desligada: falta OPENROUTER_API_KEY no .env.")

    try:
        resposta = httpx.post(
            URL,
            headers={
                "Authorization": f"Bearer {chave}",
                "Content-Type": "application/json",
                "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "http://localhost:3000"),
                "X-Title": "Acervo - pesquisa web",
            },
            json={
                "model": MODELO,
                "temperature": 0.2,
                "plugins": [{"id": "web", "max_results": MAX_RESULTADOS}],
                "messages": [
                    {"role": "system", "content": INSTRUCAO},
                    {"role": "user", "content": pergunta},
                ],
            },
            timeout=TEMPO_LIMITE_S,
        )
        resposta.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detalhe = exc.response.text[:800] if exc.response is not None else ""
        log.warning("OpenRouter recusou a pesquisa (%s): %s", exc.response.status_code, detalhe)
        raise ErroPesquisa(
            f"O serviço de pesquisa respondeu {exc.response.status_code}. {detalhe}"
        ) from exc
    except httpx.HTTPError as exc:
        log.warning("OpenRouter fora do ar na pesquisa: %s", str(exc)[:160])
        raise ErroPesquisa("O serviço de pesquisa não respondeu a tempo. Tente de novo.") from exc

    try:
        corpo = resposta.json()
        mensagem = corpo["choices"][0]["message"]
    except Exception as exc:
        raise ErroPesquisa("Resposta ilegível do serviço de pesquisa.") from exc

    conteudo = mensagem.get("content") or ""
    if isinstance(conteudo, list):
        conteudo = "".join(p.get("text", "") for p in conteudo if isinstance(p, dict))

    return {
        "pergunta": pergunta,
        "resposta": str(conteudo).strip(),
        "fontes": _fontes(mensagem.get("annotations")),
        "modelo": corpo.get("model") or MODELO,
    }


def _fontes(anotacoes: Any) -> list[dict[str, str]]:
    """`url_citation` da OpenRouter, sem repetir URL e sem o texto inteiro da página."""
    fontes: list[dict[str, str]] = []
    vistas: set[str] = set()
    for item in anotacoes or []:
        if not isinstance(item, dict) or item.get("type") != "url_citation":
            continue
        citacao = item.get("url_citation") or {}
        url = str(citacao.get("url") or "").strip()
        if not url.startswith(("http://", "https://")) or url in vistas:
            continue
        vistas.add(url)
        trecho = " ".join(str(citacao.get("content") or "").split())
        fontes.append(
            {
                "url": url,
                "titulo": str(citacao.get("title") or "").strip(),
                "trecho": trecho[:300] + ("…" if len(trecho) > 300 else ""),
            }
        )
    return fontes
