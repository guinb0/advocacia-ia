"""Ouve a entrevista correndo e preenche o roteiro sozinho.

O QUE MUDA EM RELAÇÃO AO MODELO ANTERIOR

Antes, cada pergunta tinha o seu botão: o entrevistador apertava "gravar", fazia
a pergunta, ouvia, apertava "finalizar". Oitenta e seis vezes. O escritório
descreveu isso como "fluxo quebrado, fechado e restrito", e a descrição é justa —
quem conduz a entrevista fica administrando botões em vez de conversar, e o
cliente que responde três perguntas de uma vez tem duas jogadas fora.

Agora o microfone abre uma vez, no "podemos começar?", e não fecha mais. Este
módulo recebe os trechos transcritos conforme saem e decide, a cada trecho, o que
dali responde qual pergunta do roteiro.

POR QUE ISTO NÃO PREENCHE CPF, RG NEM DATA

`roteiros.py` já registrava o motivo, e ele continua valendo: o Whisper erra
dígito, e ninguém confere número lido de ouvido. Um CPF errado atravessa o
contrato, a procuração e a petição sem que nada acuse.

A decisão do escritório fechou a questão de outro jeito: a qualificação saiu da
entrevista. Ela passou a ser etapa do Departamento de Documentação, digitada. Do
que é dado, aqui só entram **nome e CPF**, e mesmo esses como SUGESTÃO — quem
confirma é quem está ouvindo.

O que este módulo preenche de verdade são os relatos: o que aconteceu, quando,
quem viu, como a empresa reagiu. Errar uma palavra num relato é diferente de
errar um dígito, e o relato fica na tela para o entrevistador corrigir enquanto
o cliente ainda fala.

O QUE ELE DEVOLVE, E POR QUE OS TRÊS

    preenchidas  o que este trecho respondeu, com o pedaço da fala que sustenta
    lembretes    o que a resposta tocou pela metade e precisa ser aprofundado
    faltando     o que o roteiro ainda pede e ninguém falou

Os três juntos são o painel que o escritório pediu: "ver em tempo real tudo que
foi preenchido e tudo que necessita ser perguntado". Separados, não servem —
saber o que falta sem saber o que já entrou faz repetir pergunta, e é justamente
disso que o cliente reclamou.

CUSTO

Uma chamada ao modelo por trecho de fala consolidado, não por parcial. Vão só as
perguntas AINDA ABERTAS, não as 86 — numa entrevista adiantada isso é a
diferença entre um prompt de 400 e um de 4.000 tokens. Ver `_perguntas_abertas`.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

from . import roteiros

log = logging.getLogger("escuta")

#: A entrevista está acontecendo: o entrevistador espera o painel se mexer entre
#: uma frase e a seguinte. Passar disto, o trecho já não é mais o assunto.
TEMPO_MODELO_S = 20.0

#: Trecho curto demais não vale uma chamada ao modelo. "sim" e "não" explícitos
#: têm um caminho determinístico próprio; interjeições ambíguas continuam fora.
MINIMO_CARACTERES = 25

#: Teto de perguntas mandadas por vez. Um roteiro de 86 perguntas com tudo em
#: aberto encheria o prompt de coisa que não tem chance de ser respondida agora.
#: A ordem do roteiro é do escritório, então as primeiras abertas são as certas.
MAXIMO_PERGUNTAS = 18

#: Nome e CPF são DIGITADOS, e a escuta não encosta neles.
#:
#: Já foram sugestão — a fala virava um palpite que alguém confirmava com um
#: clique. Medido no áudio real, não funcionava: o Whisper escrevia "Guilherme
#: Inunes" no lugar de "Guilherme Nunes", e o modelo, corretamente, se recusava
#: a preencher a partir de texto ilegível. O resultado na tela era um campo
#: vazio sem explicação.
#:
#: A regra do escritório fechou a questão: os dois são digitados ANTES de a
#: transcrição começar, e é o preenchimento deles que libera o microfone (ver
#: `Roteiro.tsx`). Não há o que ouvir aqui — quando a escuta abre, eles já estão
#: respondidos.
#:
#: A lista existe para o caso de o roteiro mudar de forma: campo destes nunca
#: sai de fala, esteja no bloco que estiver.
DADOS_DIGITADOS = {"nome", "cpf"}


def _binaria_curta(trecho: str, abertas: list[roteiros.Pergunta]) -> dict[str, Any] | None:
    """Aplica um `sim`/`não` explícito à pergunta que está na vez.

    O frontend e `_perguntas_abertas` seguem a mesma ordem do roteiro, portanto
    a primeira aberta é a pergunta mostrada. Não aceitamos "aham", "acho" ou
    outras formas ambíguas: velocidade não pode virar preenchimento falso.
    """
    palavras = re.findall(r"[a-záàâãéêíóôõúç]+", trecho.casefold())
    if not palavras or not abertas:
        return None
    if all(p == "sim" for p in palavras):
        valor = "sim"
    elif all(p in {"não", "nao"} for p in palavras):
        valor = "não"
    else:
        return None

    pergunta = abertas[0]
    inicio = pergunta.texto.casefold().lstrip()
    parece_binaria = pergunta.tipo == "sim_nao" or inicio.startswith(
        ("ainda ", "já ", "houve ", "teve ", "foi ", "ficou ", "recebeu ", "procurou ")
    )
    if not parece_binaria:
        return None
    return {
        "pergunta_id": pergunta.id,
        "pergunta": pergunta.texto,
        "valor": valor,
        "trecho": trecho,
    }


class ErroEscuta(Exception):
    """Falha que o entrevistador precisa ver — sem parar a entrevista."""


# ------------------------------------------------------------------ roteiro


def _respondida(valor: Any) -> bool:
    if isinstance(valor, list):
        return len(valor) > 0
    return bool(str(valor or "").strip())


def _perguntas_abertas(
    roteiro: roteiros.Roteiro, respostas: dict[str, Any]
) -> list[roteiros.Pergunta]:
    """As que ainda faltam, na ordem do escritório, cortadas no teto.

    Os módulos que o rastreio não abriu ficam de fora: quem não sofreu assalto
    não tem pergunta de assalto para responder, e oferecê-las ao modelo é
    convidá-lo a inventar resposta para pergunta que nem foi feita.
    """
    # `MAPA_RASTREIO` é do módulo, não do roteiro: é a mesma tabela que a rota
    # `/api/roteiros/{codigo}` anexa à resposta para a tela decidir o que exibir.
    positivos = {
        modulo
        for pergunta_id, modulo in roteiros.MAPA_RASTREIO.items()
        if str(respostas.get(pergunta_id, "")).strip().lower() == "sim"
    }

    abertas: list[roteiros.Pergunta] = []
    for bloco in roteiro.blocos:
        if bloco.modulo and bloco.modulo not in positivos:
            continue
        # Bloco entregue a outra equipe não é assunto desta conversa.
        if bloco.delegado_a:
            continue
        for pergunta in bloco.perguntas:
            if _respondida(respostas.get(pergunta.id)):
                continue
            # Rede de segurança para quando o roteiro mudar de forma: campo com
            # dígito verificador, e os que são digitados por regra, nunca saem
            # de fala — esteja no bloco que estiver.
            if pergunta.validacao or pergunta.id in DADOS_DIGITADOS:
                continue
            abertas.append(pergunta)
    return abertas[:MAXIMO_PERGUNTAS]


def _descrever(pergunta: roteiros.Pergunta) -> str:
    partes = [f"{pergunta.id}: {pergunta.texto}"]
    if pergunta.tipo == "sim_nao":
        partes.append("(responda apenas sim ou não)")
    elif pergunta.opcoes:
        partes.append(f"(uma de: {', '.join(pergunta.opcoes)})")
    if pergunta.dica:
        partes.append(f"[orientação ao entrevistador: {pergunta.dica}]")
    return " ".join(partes)


# ------------------------------------------------------------------- modelo

INSTRUCAO = """Você acompanha, AO VIVO, a entrevista de acolhimento de um escritório
trabalhista. Recebe um trecho recém-transcrito da conversa e a lista de perguntas
do roteiro que ainda estão em aberto.

Sua tarefa é dizer o que ESTE trecho respondeu — nada além disso.

REGRAS
- Só preencha o que foi DITO. Não deduza, não complete, não normalize para o que
  seria plausível. Se a pessoa disse "faz uns três anos", o valor é "uns três
  anos", não uma data.
- A fala é de transcrição automática: pode vir truncada ou com palavra trocada.
  Na dúvida sobre o que foi dito, NÃO preencha — registre em `lembretes`.
- Um trecho pode responder várias perguntas de uma vez, ou nenhuma. Nenhuma é
  resposta legítima e comum: boa parte da conversa é saudação e rapport.
- `sim_nao` só aceita "sim" ou "não". Se a pessoa foi ambígua, não preencha.
- NUNCA preencha CPF, RG, datas de nascimento ou qualquer número de documento a
  partir da fala, mesmo que apareça claramente. Esses campos são digitados por
  outra equipe.
- `valor` é o que vai ficar escrito no campo: a fala organizada em texto corrido,
  na terceira pessoa ou como foi dita, SEM inventar detalhe que não foi falado.
- `trecho` é a citação literal do que sustenta o preenchimento, para o
  entrevistador conferir de relance.
- `lembretes` é o que ficou pela metade: o cliente tocou no assunto mas faltou
  data, nome, número ou documento. Escreva como PERGUNTA pronta para ser lida em
  voz alta, na segunda pessoa.
- No máximo 4 lembretes. Menos é melhor: isto é lido durante a conversa.

Responda APENAS JSON:
{"preenchidas":[{"pergunta_id":"...","valor":"...","trecho":"..."}],
 "lembretes":[{"pergunta_id":"...","pergunte":"..."}]}"""


def _chamar_modelo(mensagem: str) -> dict[str, Any]:
    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not chave:
        raise ErroEscuta(
            "Escuta automática desligada: falta DEEPSEEK_API_KEY no .env. "
            "A entrevista segue, e os campos podem ser preenchidos à mão."
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
                "max_tokens": 700,
                "messages": [
                    {"role": "system", "content": INSTRUCAO},
                    {"role": "user", "content": mensagem},
                ],
            },
            timeout=TEMPO_MODELO_S,
        )
        resposta.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Escuta falhou: %s", str(exc)[:160])
        raise ErroEscuta("O modelo não respondeu a tempo. A entrevista pode seguir.") from exc

    try:
        return json.loads(resposta.json()["choices"][0]["message"]["content"])
    except Exception as exc:
        raise ErroEscuta("Resposta ilegível do modelo.") from exc


# ------------------------------------------------------------------ formato


def _texto(valor: Any, limite: int = 600) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip()[:limite]


def _normalizar(
    bruto: dict[str, Any], abertas: list[roteiros.Pergunta]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Descarta o que o modelo inventou e separa o que precisa de confirmação.

    Devolve (preenchidas, sugestões, lembretes).
    """
    por_id = {p.id: p for p in abertas}

    preenchidas: list[dict[str, Any]] = []
    #: Hoje sai sempre vazia: nome e CPF passaram a ser digitados antes de a
    #: transcrição começar, e eram os únicos campos que viravam sugestão. A
    #: chave fica no formato porque a tela e os testes a esperam — e porque o
    #: dia em que um campo voltar a depender de confirmação humana, o caminho
    #: já existe.
    sugestoes: list[dict[str, Any]] = []
    extras: list[dict[str, Any]] = []

    for item in bruto.get("preenchidas") or []:
        if not isinstance(item, dict):
            continue
        pergunta = por_id.get(str(item.get("pergunta_id", "")))
        # Pergunta que não estava aberta é alucinação de id, ou pergunta de um
        # módulo que o rastreio não abriu. Nos dois casos, fora.
        if pergunta is None:
            continue
        valor = _texto(item.get("valor"))
        if not valor:
            continue

        # `_perguntas_abertas` já não oferece estes campos ao modelo. Esta
        # segunda barreira existe porque prompt é melhor-esforço: se um dia a
        # lista mudar e um `cpf` escapar para cá, ele morre aqui também.
        if pergunta.validacao or pergunta.id in DADOS_DIGITADOS:
            log.info("Escuta tentou preencher campo digitado %r; descartado.", pergunta.id)
            continue

        if pergunta.tipo == "sim_nao":
            v = valor.strip().lower().rstrip(".")
            if v not in ("sim", "não", "nao"):
                continue
            valor = "sim" if v == "sim" else "não"
        elif pergunta.opcoes and valor not in pergunta.opcoes:
            continue

        registro = {
            "pergunta_id": pergunta.id,
            "pergunta": pergunta.texto,
            "valor": valor,
            "trecho": _texto(item.get("trecho"), 240),
        }

        preenchidas.append(registro)

    lembretes = list(extras)
    for item in bruto.get("lembretes") or []:
        if isinstance(item, dict):
            pergunte, pid = _texto(item.get("pergunte"), 240), str(item.get("pergunta_id", ""))
        else:
            pergunte, pid = _texto(item, 240), ""
        if pergunte:
            lembretes.append({"pergunta_id": pid if pid in por_id else "", "pergunte": pergunte})

    return preenchidas, sugestoes, lembretes[:4]


def _abertas_pelo_rastreio(
    roteiro: roteiros.Roteiro,
    respostas: dict[str, Any],
    preenchidas: list[dict[str, Any]],
    ja_oferecidas: list[roteiros.Pergunta],
) -> list[roteiros.Pergunta]:
    """As perguntas que NASCERAM por causa deste trecho.

    Só um rastreio respondido "sim" abre módulo (ver `roteiros.MAPA_RASTREIO`),
    então nada disto roda numa volta comum — é a diferença entre uma chamada por
    trecho e duas só quando a entrevista muda de forma.
    """
    positivos = [
        p
        for p in preenchidas
        if p["pergunta_id"] in roteiros.MAPA_RASTREIO and p["valor"] == "sim"
    ]
    if not positivos:
        return []

    depois = {**respostas, **{p["pergunta_id"]: p["valor"] for p in preenchidas}}
    conhecidas = {p.id for p in ja_oferecidas}
    return [p for p in _perguntas_abertas(roteiro, depois) if p.id not in conhecidas]


# -------------------------------------------------------------------- ação


def escutar(
    trecho: str,
    respostas: dict[str, Any],
    codigo_roteiro: str = "empregado_publico",
) -> dict[str, Any]:
    """O que este trecho de fala respondeu, e o que ainda falta perguntar.

    `respostas` é o estado atual da entrevista — entra para o modelo não repetir
    o que já está preenchido, e para o rastreio decidir quais módulos existem.
    """
    trecho = _texto(trecho, 4000)
    roteiro = roteiros.obter(codigo_roteiro)
    if roteiro is None:
        raise ErroEscuta(f"Roteiro {codigo_roteiro!r} não existe.")

    abertas = _perguntas_abertas(roteiro, respostas)
    faltando = [
        {"pergunta_id": p.id, "pergunta": p.texto, "obrigatoria": p.obrigatoria}
        for p in abertas
    ]

    binaria = _binaria_curta(trecho, abertas)
    if binaria is not None:
        return {
            "preenchidas": [binaria],
            "sugestoes": [],
            "lembretes": [],
            "faltando": [f for f in faltando if f["pergunta_id"] != binaria["pergunta_id"]],
            "analisado": True,
        }

    # Sem trecho útil, ainda assim devolve o que falta: é o painel abrindo no
    # começo da entrevista, antes de alguém falar qualquer coisa.
    if len(trecho) < MINIMO_CARACTERES or not abertas:
        return {
            "preenchidas": [],
            "sugestoes": [],
            "lembretes": [],
            "faltando": faltando,
            "analisado": False,
        }

    ja_respondido = [
        f"{pid}: {v}"
        for pid, v in respostas.items()
        if _respondida(v) and len(str(v)) <= 120
    ][:20]

    partes = [
        "PERGUNTAS EM ABERTO:\n" + "\n".join(f"- {_descrever(p)}" for p in abertas),
        f"TRECHO RECÉM-FALADO:\n{trecho}",
    ]
    if ja_respondido:
        partes.append("JÁ RESPONDIDO (não repita):\n" + "\n".join(ja_respondido))

    preenchidas, sugestoes, lembretes = _normalizar(
        _chamar_modelo("\n\n".join(partes)), abertas
    )

    # O trecho que ABRE um módulo costuma trazer o módulo inteiro junto.
    #
    # "Fui assaltado, tenho o BO e a CAT, e fiquei afastado pelo INSS" é uma
    # frase só, e o cliente a diz muito antes de alguém perguntar. Quando ela
    # chega, as perguntas do módulo de assalto ainda NÃO EXISTEM — o rastreio é
    # que as abre — e o modelo não tinha onde pôr o resto: media-se isso, e a
    # mesma frase preenchia 1 campo antes e 3 depois.
    #
    # Então, quando um rastreio dá positivo, o mesmo trecho é lido de novo
    # contra as perguntas que acabaram de nascer. É uma chamada a mais, e ela
    # acontece no máximo uma vez por módulo — quatro por entrevista, no pior
    # caso — em troca de não perder a história que o cliente já contou.
    novas = _abertas_pelo_rastreio(roteiro, respostas, preenchidas, abertas)
    if novas:
        extras, sug_extras, lem_extras = _normalizar(
            _chamar_modelo(
                "\n\n".join(
                    [
                        "PERGUNTAS EM ABERTO:\n"
                        + "\n".join(f"- {_descrever(p)}" for p in novas),
                        f"TRECHO RECÉM-FALADO:\n{trecho}",
                    ]
                )
            ),
            novas,
        )
        preenchidas += extras
        sugestoes += sug_extras
        # O mesmo trecho lido duas vezes gera o mesmo lembrete duas vezes, e
        # duas linhas idênticas num painel lido de relance, no meio de uma
        # conversa, é pior que ruído: parece que são dois assuntos.
        vistos = {l["pergunte"].casefold() for l in lembretes}
        lembretes = (
            lembretes
            + [l for l in lem_extras if l["pergunte"].casefold() not in vistos]
        )[:4]
        faltando += [
            {"pergunta_id": p.id, "pergunta": p.texto, "obrigatoria": p.obrigatoria}
            for p in novas
        ]

    # O que este trecho acabou de responder sai da lista de pendências na mesma
    # volta — senão o painel mostraria como faltando algo que já está na tela.
    #
    # Sugestão NÃO sai: enquanto ninguém confirmou o CPF, ele continua pendente.
    respondidas_agora = {p["pergunta_id"] for p in preenchidas}
    return {
        "preenchidas": preenchidas,
        "sugestoes": sugestoes,
        "lembretes": lembretes,
        "faltando": [f for f in faltando if f["pergunta_id"] not in respondidas_agora],
        "analisado": True,
    }
