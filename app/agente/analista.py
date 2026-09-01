"""O agente analista do acervo: pensa, consulta e responde com o que mediu.

O que ele é: um modelo com um catálogo de consultas (`ferramentas.py`) e permissão para
escolher quais usar, em que ordem, quantas vezes. Pergunta aberta ("temos algum caso
travado por documento do INSS?", "resuma o caso da Maria e diga se dá para peticionar")
vira uma sequência de leituras determinísticas e uma resposta escrita sobre elas.

O que ele **não** é: um roteador de respostas prontas. Ele decide o caminho; o que não se
negocia é a origem do número — medir é das ferramentas, e afirmar exige lastro.

DUAS FASES, E O MOTIVO
======================

1. **investigação** — o modelo conversa com o catálogo: chama ferramenta, lê o resultado,
   chama outra. Aqui ele é livre e a saída é texto solto;
2. **redação** — com o material na mão, uma segunda chamada escreve a resposta no formato
   fechado (afirmação + natureza + referências).

Separado porque misturar as duas coisas numa chamada só produz o pior dos dois mundos:
ou o modelo devolve JSON no meio da investigação (e para de consultar cedo demais), ou
devolve prosa no fim (e o guardrail não tem o que conferir). Custa uma chamada a mais e
paga em previsibilidade.

O GUARDRAIL
===========

Toda afirmação carrega `nature`. As factuais — `PROVEN_FACT`, `STATISTICAL_PATTERN` —
precisam citar em `refs` alguma coisa que uma ferramenta realmente devolveu; sem isso são
descartadas, porque "63 casos estão parados" soa idêntico esteja certo ou inventado.

`INFERENCE`, `HYPOTHESIS` e `RECOMMENDATION` passam sem referência de propósito: são
leitura, não medição, e a tela já as mostra com selo próprio. Exigir lastro delas seria
o erro que este repositório já cometeu três vezes — reprovar a resposta certa por excesso
de zelo, e ensinar o advogado a ignorar o guardrail.

Quando NADA sobra, a resposta não é entregue: vira recusa honesta dizendo o que faltou.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import ferramentas

log = logging.getLogger("agente")

__all__ = ["Analise", "ErroDoAnalista", "responder"]


class ErroDoAnalista(RuntimeError):
    """O analista não pôde trabalhar — modelo fora do ar, sem chave, prazo estourado."""


#: Quantas rodadas de ferramenta antes de parar e responder com o que houver.
#:
#: Seis cobre o caminho mais longo que faz sentido (achar o caso → dossiê → documentos →
#: entrevista → jurimetria) com folga. Sem teto, uma pergunta mal formulada faz o modelo
#: consultar em círculo enquanto o advogado espera.
MAXIMO_DE_PASSOS = 6

#: Prazo de cada chamada ao modelo. Alto porque a fase de investigação encadeia leituras.
TEMPO_DO_MODELO_S = 90

#: Naturezas que EXIGEM lastro. As demais são leitura declarada como tal.
_FACTUAIS = frozenset({"PROVEN_FACT", "STATISTICAL_PATTERN"})

_NATUREZAS = (
    "PROVEN_FACT",
    "ALLEGED_FACT",
    "STATISTICAL_PATTERN",
    "INFERENCE",
    "HYPOTHESIS",
    "RECOMMENDATION",
    "PRECEDENT",
)

INSTRUCAO = """\
Você é o analista do acervo de um escritório de advocacia trabalhista. Responde ao
ADVOGADO, sobre os casos do escritório dele.

Como você trabalha:

1. PRIMEIRO CONSULTE, DEPOIS FALE. Você não sabe nada sobre este acervo de memória. Todo
   número, nome, data e estado vem de uma ferramenta. Se a pergunta pede algo que nenhuma
   ferramenta alcança, diga isso — é resposta melhor do que uma aproximação.
2. ENCADEIE. Se só souber o nome do cliente, ache o caso com `listar_casos` e depois abra
   o `dossie_do_caso`. Se a resposta depende de documentos, consulte os documentos. Use
   quantas ferramentas precisar.
3. SEJA CRÍTICO. O advogado não quer um relatório do que você leu; quer a leitura. Aponte
   o que está travado, o que não fecha, o que falta para o caso andar, o que chama
   atenção. Compare quando fizer sentido.
4. NUNCA CONFUNDA RELATO COM PROVA. Fato com estado ALLEGED é o que o cliente contou e
   nenhum documento comprova. Dizer que está "comprovado" é o erro mais grave possível
   aqui.
5. NÃO DÊ CONSELHO JURÍDICO CONCLUSIVO. Você não decide tese, não afirma que a ação
   ganha, não estima valor. Aponta o que o material sustenta.

Responda em português do Brasil, direto, sem saudação e sem repetir a pergunta.\
"""

FORMATO = """\
Escreva a resposta final como JSON, exatamente nesta forma:

{
  "resposta": "O texto que o advogado lê. Direto, com a leitura crítica do que você achou.",
  "afirmacoes": [
    {
      "statement": "63 casos estão sem movimentação há mais de 5 dias",
      "nature": "STATISTICAL_PATTERN",
      "refs": ["panorama"]
    },
    {
      "statement": "O caso de Maria Santos está travado na coleta por falta de CAT",
      "nature": "PROVEN_FACT",
      "refs": ["caso:8b4a903b-1111-2222-3333-444455556666"]
    },
    {
      "statement": "Cobrar a CAT antes da perícia provavelmente destrava o caso",
      "nature": "RECOMMENDATION",
      "refs": []
    }
  ],
  "pendencias": [
    "Valor de causa não é medido por nenhuma ferramenta deste sistema."
  ]
}

Regras do formato, todas obrigatórias:

- `nature` é uma destas: NATUREZAS_VALIDAS.
- `PROVEN_FACT` e `STATISTICAL_PATTERN` SÓ podem ser usados com `refs` preenchido, e cada
  referência tem de ser uma das que as ferramentas devolveram (a lista vai abaixo). Uma
  afirmação factual sem referência válida é DESCARTADA antes de chegar ao advogado.
- `ALLEGED_FACT` é o que o cliente relatou e nenhum documento comprova — use quando o
  fato do caso estiver com estado ALLEGED.
- `INFERENCE`, `HYPOTHESIS` e `RECOMMENDATION` são sua leitura, e podem ir sem referência.
- `pendencias` é o que faltou para responder melhor: dado que nenhuma ferramenta alcança,
  consulta que falhou, ou informação que só o advogado tem. Vazio se não faltou nada.
- Não repita no `resposta` nada que você não consiga sustentar em `afirmacoes`.\
"""


@dataclass
class Analise:
    """O que o analista produziu — já conferido contra o que foi medido."""

    conteudo: str
    afirmacoes: list[dict[str, Any]] = field(default_factory=list)
    pendencias: list[str] = field(default_factory=list)
    #: Cada consulta feita, na ordem. É o "como cheguei nisso" que a tela mostra.
    consultas: list[dict[str, Any]] = field(default_factory=list)
    #: Casos citados por alguma afirmação — o que vira caminho para o dossiê.
    casos: list[str] = field(default_factory=list)
    #: Preenchido quando o guardrail reprovou a resposta inteira.
    recusa: str | None = None


# ------------------------------------------------------------------- o modelo


def _configurado() -> tuple[str, str, str]:
    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not chave:
        raise ErroDoAnalista(
            "O analista está desligado: falta DEEPSEEK_API_KEY no .env. As perguntas "
            "sobre um caso específico continuam sendo respondidas pelo agente jurídico."
        )
    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    modelo = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    return chave, base, modelo


def _chamar(mensagens: list[dict[str, Any]], *, ferramentas_do_modelo: bool, json_puro: bool) -> dict[str, Any]:
    chave, base, modelo = _configurado()
    corpo: dict[str, Any] = {
        "model": modelo,
        # Zero porque a mesma pergunta, no mesmo acervo, tem de dar a mesma resposta.
        # Variação aqui vira "o número mudou" para quem lê, e não há como saber qual valia.
        "temperature": 0,
        "messages": mensagens,
    }
    if ferramentas_do_modelo:
        corpo["tools"] = ferramentas.esquemas()
        corpo["tool_choice"] = "auto"
    if json_puro:
        corpo["response_format"] = {"type": "json_object"}

    try:
        resposta = httpx.post(
            base + "/chat/completions",
            headers={"Authorization": f"Bearer {chave}"},
            json=corpo,
            timeout=TEMPO_DO_MODELO_S,
        )
        resposta.raise_for_status()
    except httpx.HTTPError as erro:
        log.warning("analista: modelo não respondeu: %s", str(erro)[:200])
        raise ErroDoAnalista(
            "O modelo não respondeu a tempo. Tente de novo em instantes."
        ) from erro

    return resposta.json()["choices"][0]["message"]


# ------------------------------------------------------------- a investigação


def _investigar(
    pergunta: str, historico: list[dict[str, str]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    """Deixa o modelo consultar até se dar por satisfeito (ou até o teto).

    Devolve a conversa inteira (para a fase de redação reaproveitá-la), o registro das
    consultas e todas as referências comprovadas.
    """
    mensagens: list[dict[str, Any]] = [{"role": "system", "content": INSTRUCAO}]
    mensagens.extend(historico)
    mensagens.append({"role": "user", "content": pergunta})

    consultas: list[dict[str, Any]] = []
    refs: set[str] = set()

    for passo in range(MAXIMO_DE_PASSOS):
        mensagem = _chamar(mensagens, ferramentas_do_modelo=True, json_puro=False)
        chamadas = mensagem.get("tool_calls") or []
        mensagens.append(mensagem)

        if not chamadas:
            # Parou de consultar: ou já sabe responder, ou não há o que consultar.
            break

        for chamada in chamadas:
            nome = (chamada.get("function") or {}).get("name") or ""
            bruto = (chamada.get("function") or {}).get("arguments") or "{}"
            try:
                argumentos = json.loads(bruto) if isinstance(bruto, str) else dict(bruto)
            except json.JSONDecodeError:
                argumentos = {}
                log.warning("analista: argumentos ilegíveis para %s: %s", nome, bruto[:120])

            resultado = ferramentas.executar(nome, argumentos)
            refs |= resultado.refs
            consultas.append({"ferramenta": nome, "argumentos": argumentos, "passo": passo + 1})
            mensagens.append(
                {
                    "role": "tool",
                    "tool_call_id": chamada.get("id"),
                    "content": json.dumps(resultado.dados, ensure_ascii=False, default=str),
                }
            )
    else:
        # Esgotou o teto ainda querendo consultar: o modelo é avisado, para responder com
        # o que tem em vez de continuar tentando.
        mensagens.append(
            {
                "role": "user",
                "content": (
                    "Você atingiu o limite de consultas. Responda com o que já apurou e "
                    "registre em `pendencias` o que ficou sem consultar."
                ),
            }
        )

    return mensagens, consultas, refs


def _redigir(mensagens: list[dict[str, Any]], refs: set[str]) -> dict[str, Any]:
    """A segunda chamada: o mesmo material, agora no formato fechado."""
    disponiveis = sorted(refs)
    instrucao = FORMATO.replace("NATUREZAS_VALIDAS", ", ".join(_NATUREZAS))
    if disponiveis:
        instrucao += (
            "\n\nReferências que as consultas comprovaram (só estas valem em `refs`):\n"
            + "\n".join(f"- {ref}" for ref in disponiveis[:120])
        )
    else:
        instrucao += (
            "\n\nNENHUMA consulta comprovou referência alguma. Portanto não use "
            "`PROVEN_FACT` nem `STATISTICAL_PATTERN`: diga o que não foi possível apurar."
        )

    conversa = [*mensagens, {"role": "user", "content": instrucao}]
    mensagem = _chamar(conversa, ferramentas_do_modelo=False, json_puro=True)
    try:
        return json.loads(mensagem.get("content") or "{}")
    except json.JSONDecodeError as erro:
        raise ErroDoAnalista("O modelo devolveu uma resposta ilegível.") from erro


# --------------------------------------------------------------- o guardrail


def _conferir(bruto: dict[str, Any], refs: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Separa o que tem lastro do que não tem. Devolve as afirmações e o que caiu."""
    aprovadas: list[dict[str, Any]] = []
    descartadas: list[str] = []

    for item in bruto.get("afirmacoes") or []:
        if not isinstance(item, dict):
            continue
        texto = str(item.get("statement") or "").strip()
        if not texto:
            continue
        natureza = str(item.get("nature") or "INFERENCE").upper()
        if natureza not in _NATUREZAS:
            natureza = "INFERENCE"

        citadas = [str(r) for r in (item.get("refs") or []) if str(r)]
        validas = [r for r in citadas if r in refs]

        if natureza in _FACTUAIS and not validas:
            # O caso que este guardrail existe para pegar: contagem sobre o acervo sem
            # nada que a sustente. Cai, e o advogado é avisado de que caiu.
            descartadas.append(texto)
            continue

        aprovadas.append({"statement": texto, "nature": natureza, "refs": validas})

    return aprovadas, descartadas


def _casos_citados(afirmacoes: list[dict[str, Any]]) -> list[str]:
    """Os casos que a resposta cita, na ordem em que aparecem — sem repetir."""
    vistos: list[str] = []
    for afirmacao in afirmacoes:
        for ref in afirmacao["refs"]:
            if ref.startswith("caso:"):
                caso_id = ref.split(":", 1)[1]
                if caso_id not in vistos:
                    vistos.append(caso_id)
    return vistos


# ------------------------------------------------------------------- entrada


def responder(pergunta: str, historico: list[dict[str, str]] | None = None) -> Analise:
    """Investiga, redige e confere. É o que a conversa geral chama.

    `historico` são as últimas trocas da conversa, no formato do modelo — é o que faz
    "e o dela?" continuar a pergunta anterior em vez de recomeçar do zero.
    """
    mensagens, consultas, refs = _investigar(pergunta, historico or [])
    bruto = _redigir(mensagens, refs)

    texto = str(bruto.get("resposta") or "").strip()
    afirmacoes, descartadas = _conferir(bruto, refs)
    pendencias = [str(p) for p in (bruto.get("pendencias") or []) if str(p).strip()]

    if descartadas:
        log.warning("analista: %d afirmação(ões) sem lastro descartada(s)", len(descartadas))
        pendencias.append(
            f"{len(descartadas)} afirmação(ões) foram retiradas por não se apoiarem em "
            "nada que tenha sido consultado."
        )

    # Resposta que afirma coisas factuais e não sobrou nenhuma é pior que resposta
    # nenhuma: o texto continuaria dizendo o número que o guardrail acabou de reprovar.
    if descartadas and not afirmacoes:
        return Analise(
            conteudo=(
                "Não consigo sustentar essa resposta com o que consultei.\n\n"
                "Cheguei a produzir uma, mas nenhuma das afirmações se apoiava no que as "
                "consultas devolveram — e um número sobre o acervo que não veio de "
                "medição é exatamente o que este sistema não pode entregar."
            ),
            pendencias=pendencias,
            consultas=consultas,
            recusa="sem lastro",
        )

    if not texto:
        return Analise(
            conteudo="Não consegui formular a resposta desta vez. Tente reformular a pergunta.",
            consultas=consultas,
            recusa="sem texto",
        )

    return Analise(
        conteudo=texto,
        afirmacoes=afirmacoes,
        pendencias=pendencias,
        consultas=consultas,
        casos=_casos_citados(afirmacoes),
    )
