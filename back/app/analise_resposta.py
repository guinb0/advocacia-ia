"""Confere, resposta a resposta, o que a entrevista ainda não trouxe.

Quando o cliente termina de contar o acidente, a atendente não tem como saber, na
hora, que faltou perguntar se houve CAT, se houve testemunha e há quanto tempo
ele está afastado. Descobrir isso depois é ligar de volta — e o cliente que já
contou a história uma vez não a conta igual na segunda. Este módulo lê a resposta
recém-dada e devolve, em segundos, o que um processo parecido mostrou ser
necessário e esta resposta não tem.

TEM DE SER CURTO, E É POR ISSO QUE NÃO É O `/api/estrategia`

O `rag.sugerir_acoes` existe e é bom, mas produz um parecer: resumo, ações,
riscos, lacunas, estatística da amostra. Isso se lê uma vez por caso, com calma.
Aqui roda uma vez por PERGUNTA — várias por entrevista, várias entrevistas por
dia. O que cabe na tela entre uma pergunta e a seguinte são no máximo duas
perguntas de acompanhamento, prontas para ler em voz alta — e, na maioria das
respostas, nenhuma. Quem conduz pode não ser advogado: sugestão que não muda o
caso (cadastro, detalhe por detalhe, o que outra pergunta do roteiro já cobre)
só ensina a pessoa a ignorar o painel.

QUANDO O BANCO DE PRECEDENTES NÃO RESPONDE

Ele é remoto, compartilhado, e já ficou fora do ar (CONTEXTO.md). Duas defesas:

1. **Prazo curto** — 4s para o embedding, 3s para conectar. O padrão da ingestão
   é 120s/10s, prazos de quem não tem ninguém esperando.
2. **Disjuntor** — falhou, para de tentar por alguns minutos. Sem isso, cada
   pergunta da entrevista pagaria o timeout inteiro de novo, e o advogado
   atribuiria a lentidão ao sistema, não ao banco.

Sem precedente a análise ainda sai, e sai **marcada**: `com_precedentes: false`.
Análise sem precedente é a leitura do modelo sobre o texto — útil para achar
lacuna óbvia, mas não é "o que os outros processos mostram", e a tela não pode
deixar as duas coisas parecerem a mesma.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from typing import Any

import httpx

from . import rag

log = logging.getLogger("analise-resposta")

#: Prazos de quem tem cliente esperando. Ver o cabeçalho.
#:
#: 6s para conectar, e não 3: medido em 13/08/2026, o servidor responde em 0,06s
#: na maior parte das sondagens e leva 7,09s em algumas. Cortar em 3s descartava
#: precedente por causa de um pico, com o banco vivo. Não é queda — é latência
#: que varia uma ordem de grandeza, e o prazo tem de caber na variação, não na
#: mediana.
TEMPO_EMBEDDING_S = 6.0
TEMPO_CONEXAO_S = 6
TEMPO_MODELO_S = 25.0

#: Quantos precedentes entram no contexto. Poucos de propósito: o que sai é uma
#: lista de até duas perguntas, e oito processos só encareceriam a mesma resposta.
PRECEDENTES = 4

#: Resposta curta demais não rende análise — e a pergunta ainda está sendo
#: respondida. Abaixo disto o pedido é recusado sem gastar chamada nenhuma.
MINIMO_CARACTERES = 40

#: Teto de lacunas e de perguntas por resposta. A instrução pede o mesmo, mas o
#: modelo nem sempre obedece, e o corte aqui é o que a tela garante.
MAXIMO_SUGESTOES = 2

#: Até onde o contexto do caso entra no prompt. Cabe o roteiro ativo, as
#: respostas curtas já dadas e a lista das outras perguntas do roteiro — é essa
#: lista que impede a conferência de cobrar o que vem na pergunta seguinte.
MAXIMO_CONTEXTO = 3_500

#: Dados de cadastro. São colhidos em outra etapa, e a conferência não pode
#: pedi-los mesmo quando o modelo insiste. Ficam de fora de propósito carteira
#: (carteira assinada é fato do caso), e-mail, WhatsApp e telefone soltos
#: (mensagem da empresa é prova): só o uso cadastral deles é filtrado.
_QUALIFICACAO = re.compile(
    r"\bcpf\b|\brg\b|carteira de identidade|\bcep\b|estado civil|nacionalidade|"
    r"naturalidade|data de nascimento|\bnasceu\b|nome completo|nome d[ao] (m[aã]e|pai)|"
    r"nome dos pais|filia[cç][aã]o|\bpis\b|\bnit\b|pasep|t[ií]tulo de eleitor|"
    r"profiss[aã]o|escolaridade|renda familiar|"
    r"(seu|sua|n[uú]mero de) (telefone|celular|e-?mail)|(telefone|e-?mail) (de|para) contato|"
    r"(seu|sua) endere[cç]o|endere[cç]o (residencial|completo|atual)|onde (o senhor|a senhora|voc[eê]) mora",
    re.IGNORECASE,
)


def _e_qualificacao(texto: str) -> bool:
    return bool(_QUALIFICACAO.search(texto))

#: Quantas falhas abrem o disjuntor.
#:
#: UMA — porque quem absorve o pico agora é o `TENTATIVAS_RAG` lá embaixo. Uma
#: falha aqui já significa duas tentativas seguidas malsucedidas, e isso é
#: evidência bastante de que o banco não está respondendo.
#:
#: Antes eram duas, quando a busca tentava uma vez só e uma falha podia ser
#: engasgo. Com a retentativa interna, exigir duas falhas custaria ~40s de
#: espera acumulada antes de o disjuntor agir — com o cliente na frente.
FALHAS_PARA_ABRIR = 1

#: Depois de abrir, o banco de precedentes fica de molho por este tempo.
#:
#: 90s e não 300: o descanso longo faz sentido para servidor morto, e o que se
#: mediu foi intermitência. Cinco minutos de "sem precedentes" por causa de um
#: mau momento é caro demais numa entrevista que dura vinte.
DESCANSO_RAG_S = 90.0

_trava = threading.Lock()
_rag_indisponivel_ate = 0.0
_falhas_seguidas = 0
_cache: dict[str, dict[str, Any]] = {}
#: Entrevista longa com muitas perguntas graváveis; o teto evita o cache crescer
#: sem limite num processo que fica dias no ar.
LIMITE_CACHE = 500


class ErroAnalise(Exception):
    """Falha que o usuário precisa ver na tela."""


# ------------------------------------------------------------------ disjuntor


def _rag_disponivel() -> bool:
    with _trava:
        return time.monotonic() >= _rag_indisponivel_ate


def _marcar_falha(motivo: str) -> None:
    """Conta a falha e abre o disjuntor só quando elas se repetem."""
    global _rag_indisponivel_ate, _falhas_seguidas
    with _trava:
        _falhas_seguidas += 1
        abriu = _falhas_seguidas >= FALHAS_PARA_ABRIR
        if abriu:
            _rag_indisponivel_ate = time.monotonic() + DESCANSO_RAG_S
        seguidas = _falhas_seguidas

    if abriu:
        log.warning(
            "Precedentes indisponíveis (%d falhas seguidas), pausando por %.0fs: %s",
            seguidas,
            DESCANSO_RAG_S,
            motivo[:160],
        )
    else:
        log.info("Falha isolada ao buscar precedentes, seguindo sem abrir: %s", motivo[:160])


def _marcar_sucesso() -> None:
    """Uma consulta boa apaga o histórico: o que conta é falha SEGUIDA."""
    global _falhas_seguidas
    with _trava:
        _falhas_seguidas = 0


def religar_precedentes() -> None:
    """Zera o disjuntor. Para o teste e para quem acabou de subir o banco."""
    global _rag_indisponivel_ate, _falhas_seguidas
    with _trava:
        _rag_indisponivel_ate = 0.0
        _falhas_seguidas = 0


# --------------------------------------------------------------------- cache


def _chave(pergunta_id: str, pergunta: str, resposta: str) -> str:
    bruto = f"{pergunta_id}\x00{pergunta}\x00{resposta.strip()}"
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def limpar_cache() -> None:
    with _trava:
        _cache.clear()


# --------------------------------------------------------------- precedentes


#: Tentativas por consulta. DUAS, e é o número que faz a diferença entre a
#: conferência citar processo e nunca citar.
#:
#: Medido ao longo de 13-14/08, em toda ferramenta que fala com este servidor: a
#: PRIMEIRA conexão estoura e a segunda conecta em décimos de segundo. Aparece
#: igual no `estado_rag`, no diagnóstico de plano, na contagem de pendentes —
#: todos retentam e todos passam na segunda. A conferência tentava uma vez só, e
#: por isso saía "sem precedentes" com o banco 100% vetorizado e respondendo.
TENTATIVAS_RAG = 2


def _buscar_precedentes(consulta: str) -> list[rag.TrechoSimilar]:
    """Processos parecidos, ou lista vazia se o banco não estiver de pé."""
    if not _rag_disponivel():
        return []

    ultimo: Exception | None = None
    for tentativa in range(1, TENTATIVAS_RAG + 1):
        try:
            achados = rag.buscar_similares(
                consulta,
                limite=PRECEDENTES,
                timeout=TEMPO_EMBEDDING_S,
                connect_timeout=TEMPO_CONEXAO_S,
            )
        except Exception as exc:
            ultimo = exc
            if tentativa < TENTATIVAS_RAG:
                # Sem pausa entre as duas: o que trava é o aperto de mão, e a
                # segunda tentativa costuma conectar na hora. Dormir aqui só
                # somaria espera com o cliente na frente.
                log.info(
                    "Precedentes: tentativa %d falhou (%s), tentando de novo.",
                    tentativa,
                    type(exc).__name__,
                )
            continue
        _marcar_sucesso()
        return achados

    _marcar_falha(f"{type(ultimo).__name__}: {ultimo}")
    return []


# ------------------------------------------------------------------ o modelo

INSTRUCAO = """Você ajuda quem conduz a entrevista inicial de um escritório trabalhista.
Essa pessoa pode não ser advogada e está com o cliente na frente: ela precisa bater
o olho e saber o que perguntar, sem pensar. Acabou de ser dada UMA resposta. Diga
se falta algo IMPORTANTE sobre ESSE ponto — e só isso.

O QUE É IMPORTANTE
- Só o que muda o caso: o que o advogado precisa para decidir se entra com a ação
  ou para escrever a petição sobre ESTE ponto. Se a falta não muda isso, não cobre.
- Resposta que já conta o essencial do ponto É SUFICIENTE, mesmo curta. Não cobre
  detalhe por cobrar (horário exato, nome de cada colega, dia da semana).
- Pergunta composta respondida pela metade: cobre só a parte sem resposta.

NUNCA COBRE
- Dado de cadastro: nome, CPF, RG, PIS, endereço, CEP, telefone ou e-mail para
  contato, estado civil, nacionalidade, profissão, data de nascimento, nome dos
  pais, escolaridade. Isso é colhido em outra etapa.
- O que outra pergunta do roteiro trata (veja OUTRAS PERGUNTAS DO ROTEIRO e JÁ
  RESPONDIDO no contexto): ela será feita na hora dela.
- Tema que nem esta pergunta nem o roteiro ativo tratam.
- O que a resposta já trouxe.
- Pedido genérico sem ligação com o que foi contado ("mais detalhes", "tem algum
  documento?", "tem testemunha?").

FORMATO
- No máximo 2 perguntas, e só se forem mesmo necessárias. Nenhuma é uma ótima
  resposta: devolva `suficiente=true` e as listas vazias.
- Cada pergunta curta, em português simples, pronta para ler em voz alta ao
  cliente ("O senhor lembra em que mês isso aconteceu?"). Sem jargão, sem
  "verificar se...".
- `faltam` traz o nome curto (até 6 palavras) de cada coisa perguntada, na mesma
  ordem de `perguntar`.
- Havendo PRECEDENTES, use-os só para saber o que costuma decidir casos assim e
  cite o índice em `precedentes`. Sem precedentes, deixe a lista vazia.
- Não invente fato, não sugira o que responder, não prometa resultado.
- O texto vem de transcrição de voz. Se vier embolado, sem sentido, ou for teste
  de microfone ou conversa paralela, diga isso em `observacao` e peça para repetir
  só o que se perdeu.
- `observacao` também serve, em uma frase, para contradição na própria resposta.
  Fora isso, deixe vazia.

Responda APENAS JSON:
{"suficiente":true|false,
 "faltam":[{"item":"mês em que aconteceu","precedentes":[]}],
 "perguntar":["O senhor lembra em que mês isso aconteceu?"],
 "observacao":""}"""


def _chamar_modelo(mensagem: str) -> dict[str, Any]:
    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not chave:
        raise ErroAnalise(
            "Análise desligada: falta DEEPSEEK_API_KEY no .env. A entrevista segue "
            "normalmente — só não há conferência automática das respostas."
        )

    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    try:
        resposta = httpx.post(
            base_url + "/chat/completions",
            headers={"Authorization": f"Bearer {chave}"},
            json={
                "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                "temperature": 0,
                "response_format": {"type": "json_object"},
                # Teto baixo é parte do "sucinto": sem ele o modelo escreve um
                # parecer, e o parecer não é lido durante a entrevista.
                "max_tokens": 500,
                "messages": [
                    {"role": "system", "content": INSTRUCAO},
                    {"role": "user", "content": mensagem},
                ],
            },
            timeout=TEMPO_MODELO_S,
        )
        resposta.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Análise da resposta falhou: %s", str(exc)[:160])
        raise ErroAnalise("O modelo não respondeu a tempo. A entrevista pode seguir.") from exc

    try:
        return json.loads(resposta.json()["choices"][0]["message"]["content"])
    except Exception as exc:
        raise ErroAnalise("Resposta ilegível do modelo.") from exc


# ------------------------------------------------------------------- formato


def _texto_curto(valor: Any, limite: int = 180) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip()[:limite]


def _normalizar_faltam(bruto: Any, validos: set[str]) -> list[dict[str, Any]]:
    """Aceita tanto `["texto"]` quanto `[{"item":..,"precedentes":[..]}]`.

    O modelo alterna entre as duas formas mesmo com `response_format` de JSON, e
    uma lista de strings chegando onde a tela espera objeto quebraria o painel
    inteiro por causa de um item.
    """
    itens = []
    for entrada in bruto if isinstance(bruto, list) else []:
        if isinstance(entrada, dict):
            texto = _texto_curto(entrada.get("item") or entrada.get("texto"))
            refs = entrada.get("precedentes")
        else:
            texto, refs = _texto_curto(entrada), []
        if not texto or _e_qualificacao(texto):
            continue
        # A chave pode vir ausente (None) ou como string solta em vez de lista —
        # normalizar ANTES de percorrer, senão o item derruba a análise inteira.
        if isinstance(refs, str):
            refs = [refs]
        elif not isinstance(refs, list):
            refs = []
        # Índice citado que não existe entre os precedentes enviados é alucinação
        # de referência: o item fica, a referência falsa sai.
        itens.append({"item": texto, "precedentes": [str(r) for r in refs if str(r) in validos]})
    return itens[:MAXIMO_SUGESTOES]


def _referencias(precedentes: list[rag.TrechoSimilar]) -> list[dict[str, Any]]:
    """Só o que a tela mostra ao lado da lacuna — número, resultado, vara."""
    saida = []
    for i, trecho in enumerate(precedentes, 1):
        ref = trecho.referencia()
        saida.append(
            {
                "indice": f"P{i}",
                "processo": ref["processo"],
                "resultado": ref["resultado"],
                "vara": ref["vara"],
                "url": ref["url"],
                "similaridade": ref["similaridade"],
            }
        )
    return saida


# -------------------------------------------------------------------- ação


def analisar(
    pergunta_id: str,
    pergunta: str,
    resposta: str,
    contexto: str = "",
) -> dict[str, Any]:
    """O que falta nesta resposta. Curto, e marcado quando sai sem precedente.

    `contexto` é o pouco que já se sabe do caso (a categoria triada, por
    exemplo). Entra para o modelo não perguntar o que outra pergunta do roteiro
    já respondeu.
    """
    resposta = (resposta or "").strip()
    pergunta = (pergunta or "").strip()
    if len(resposta) < MINIMO_CARACTERES:
        raise ErroAnalise(
            f"Resposta curta demais para analisar (mínimo {MINIMO_CARACTERES} caracteres)."
        )

    chave = _chave(pergunta_id, pergunta, resposta)
    with _trava:
        if chave in _cache:
            # Sair da caixa de texto e voltar não deve custar outra chamada — e
            # é o que mais acontece: o entrevistador clica fora, lê, clica dentro.
            return {**_cache[chave], "do_cache": True}

    precedentes = _buscar_precedentes(f"{pergunta}\n{resposta}")

    partes = [f"PERGUNTA DO ROTEIRO:\n{pergunta}", f"RESPOSTA DO CLIENTE:\n{resposta[:6000]}"]
    if contexto.strip():
        partes.append(f"CONTEXTO:\n{contexto.strip()[:MAXIMO_CONTEXTO]}")
    if precedentes:
        blocos = [
            f"[P{i}] processo={t.referencia()['processo']} "
            f"resultado={t.referencia()['resultado']}\n{t.texto[:1200]}"
            for i, t in enumerate(precedentes, 1)
        ]
        partes.append("PRECEDENTES:\n" + "\n\n".join(blocos))
    else:
        partes.append(
            "PRECEDENTES: nenhum disponível. Analise apenas a resposta e deixe "
            "`precedentes` vazio em todos os itens."
        )

    bruto = _chamar_modelo("\n\n".join(partes))
    validos = {f"P{i}" for i in range(1, len(precedentes) + 1)}

    faltam = _normalizar_faltam(bruto.get("faltam"), validos)
    perguntar = [
        _texto_curto(p)
        for p in (bruto.get("perguntar") or [])
        if _texto_curto(p) and not _e_qualificacao(_texto_curto(p))
    ][:MAXIMO_SUGESTOES]

    resultado = {
        # O modelo às vezes diz `suficiente: true` e lista lacunas na mesma
        # resposta. Quem manda é a lista: ela é o que a tela mostra.
        "suficiente": not faltam and not perguntar,
        "faltam": faltam,
        "perguntar": perguntar,
        "observacao": _texto_curto(bruto.get("observacao"), 240),
        "com_precedentes": bool(precedentes),
        "precedentes": _referencias(precedentes),
        "aviso": (
            "Conferência assistiva sobre esta resposta; a decisão é do advogado."
            if precedentes
            else "Sem precedentes disponíveis: leitura do modelo sobre a resposta, "
            "não o que os processos semelhantes mostram."
        ),
    }

    with _trava:
        if len(_cache) >= LIMITE_CACHE:
            _cache.clear()
        _cache[chave] = resultado
    return {**resultado, "do_cache": False}
