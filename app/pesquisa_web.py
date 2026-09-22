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
    "HIERARQUIA DAS FONTES — não é preferência de estilo, é o que sustenta a peça:\n"
    "1. Texto oficial da norma (planalto.gov.br, in.gov.br, senado, câmara) e "
    "jurisprudência no site do PRÓPRIO tribunal (stf, stj, tst, trf, trt, tj).\n"
    "2. Órgãos públicos e CNJ.\n"
    "3. Qualquer outra coisa — portal, blog, escritório, banco de ementas privado — "
    "só serve para ACHAR a fonte oficial, nunca para substituí-la. Se a resposta "
    "depender só disso, diga isso com todas as letras.\n"
    "Nunca cite número de súmula, artigo ou tese sem a fonte oficial junto. Um "
    "número de súmula errado numa petição é erro que o juiz vê antes do advogado.\n\n"
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
    "- Use as fontes na ordem da hierarquia acima e diga quando a melhor que você "
    "achou não for oficial.\n"
    "- Quando houver divergência jurisprudencial, exceções ou a resposta "
    "depender de detalhe do caso, diga isso explicitamente.\n"
    "- Se os resultados não sustentarem uma resposta segura, diga que não "
    "encontrou em vez de responder de memória.\n"
    # Medido em 22/09: pedido um vídeo da receita, o modelo respondeu com
    # `youtube.com/watch?v=exemplo` — um endereço que ele inventou. Link fabricado é
    # pior que link nenhum: parece conferível e só falha depois do clique.
    "- NUNCA escreva um endereço que não esteja nos resultados da busca. Nem como "
    "exemplo, nem como ilustração, nem com o final trocado. Se pedirem um vídeo e "
    "não houver link nos resultados, diga que não encontrou."
)


class ErroPesquisa(Exception):
    """Falha que a tela mostra como está — mensagens já escritas para quem lê."""


def configurada() -> bool:
    return bool(os.getenv("OPENROUTER_API_KEY", "").strip())


#: Quantas trocas anteriores acompanham a pergunta. Quatro (duas perguntas e duas
#: respostas) é o que faz "e como faz?" continuar o assunto de antes.
_TROCAS_DE_CONTEXTO = 4

#: Quanto de cada mensagem antiga vai junto. A resposta anterior inteira são milhares de
#: caracteres, e o que se quer dela é o ASSUNTO, não o texto.
_TRECHO_DA_TROCA = 600


def pesquisar(
    pergunta: str, historico: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    """Resposta + fontes. Levanta `ErroPesquisa` com texto pronto para a tela.

    `historico` são as últimas trocas da conversa, no formato do modelo. Sem ele,
    "e como faz?" chegava sozinho ao buscador — e voltava uma aula de gramática sobre a
    expressão "como faz", porque era literalmente isso que estava sendo perguntado. A
    pergunta de acompanhamento é a forma mais natural de conversar, e era justamente a
    que não funcionava.
    """
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
                    *_trocas(historico),
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

    fontes = _fontes(mensagem.get("annotations"))
    return {
        "pergunta": pergunta,
        "resposta": str(conteudo).strip(),
        "fontes": fontes,
        # Medido aqui, e não pelo modelo: é o que permite à tela e ao chat dizerem
        # "isto não tem fonte oficial" sem depender de o modelo confessar.
        "tem_fonte_oficial": any(
            f["confianca"] in ("OFICIAL", "TRIBUNAL") for f in fontes
        ),
        "modelo": corpo.get("model") or MODELO,
    }


#: A resolução de referência — entender "videos sobre" como "videos sobre bolo de
#: chocolate" — NÃO mora mais aqui.
#:
#: Ela viveu neste arquivo por uma tarde, colando a pergunta anterior na atual quando a
#: atual era curta. Quebrava com duas perguntas dependentes seguidas, e não tinha como
#: saber para onde a conversa vinha indo. Virou estado da sessão (`app/chat/contexto.py`),
#: que é onde assunto de conversa mora. A pergunta chega aqui já resolvida.

def _trocas(historico: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """As mensagens anteriores, cortadas e no formato que a API aceita.

    Só `user` e `assistant`, e nada além do texto: o lastro, as fontes e os atalhos da
    resposta anterior não ajudam a buscar e custariam a janela inteira.
    """
    limpas: list[dict[str, str]] = []
    for troca in (historico or [])[-_TROCAS_DE_CONTEXTO:]:
        papel = "user" if troca.get("role") == "user" else "assistant"
        conteudo = " ".join(str(troca.get("content") or "").split())[:_TRECHO_DA_TROCA]
        if conteudo:
            limpas.append({"role": papel, "content": conteudo})
    return limpas


#: Domínios de NORMA e de ATO OFICIAL — o texto da lei como ele é publicado.
_OFICIAIS = (
    "planalto.gov.br",
    "in.gov.br",
    "senado.leg.br",
    "camara.leg.br",
    "senado.gov.br",
    "camara.gov.br",
    "normas.leg.br",
    "lexml.gov.br",
)

#: Sufixos restritos por quem os concede. `.jus.br` é do Judiciário, `.mp.br` do
#: Ministério Público, `.gov.br`/`.leg.br` do Executivo e do Legislativo — ninguém
#: registra um deles para hospedar um blog.
_JUDICIARIO = "jus.br"
_PUBLICOS = ("gov.br", "leg.br", "mp.br", "def.br")


def _sob(dominio: str, sufixo: str) -> bool:
    """O domínio É o sufixo ou está debaixo dele.

    A comparação precisa das duas pontas: `gov.br` sozinho (o portal único do governo)
    e `www.planalto.gov.br`. Só o `endswith` deixava `gov.br` cair em "secundária", que
    é o oposto do que ele é.
    """
    return dominio == sufixo or dominio.endswith("." + sufixo)


def _confianca(url: str) -> str:
    """Em que camada da hierarquia esta fonte está.

    `OFICIAL` é o texto da norma; `TRIBUNAL` é a jurisprudência no site de quem julgou;
    `PUBLICA` é outro órgão público; `SECUNDARIA` é todo o resto — portal, blog,
    escritório, banco de ementas privado.

    Por DOMÍNIO e determinística de propósito: perguntar ao modelo se a fonte dele é
    confiável é perguntar à parte interessada. O domínio é o único sinal que não depende
    de quem escreveu a resposta.
    """
    dominio = url.split("//", 1)[-1].split("/", 1)[0].lower().removeprefix("www.")
    if any(_sob(dominio, oficial) for oficial in _OFICIAIS):
        return "OFICIAL"
    if _sob(dominio, _JUDICIARIO):
        return "TRIBUNAL"
    if any(_sob(dominio, publico) for publico in _PUBLICOS):
        return "PUBLICA"
    return "SECUNDARIA"


#: A ordem em que as fontes aparecem para quem lê. Oficial primeiro, sempre.
_PESO = {"OFICIAL": 0, "TRIBUNAL": 1, "PUBLICA": 2, "SECUNDARIA": 3}


def _fontes(anotacoes: Any) -> list[dict[str, str]]:
    """`url_citation` da OpenRouter, sem repetir URL e sem o texto inteiro da página.

    Cada fonte sai classificada e a lista sai ORDENADA pela hierarquia: quem lê de cima
    para baixo lê primeiro o que sustenta a peça. Sem isso, um blog jurídico bem escrito
    chegava na primeira posição com a mesma cara do Planalto.
    """
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
                "confianca": _confianca(url),
            }
        )
    fontes.sort(key=lambda f: _PESO.get(f["confianca"], 9))
    return fontes
