"""O chat da petição: a fronteira entre o que ele lê e o que ele NÃO faz sozinho.

Sem banco, sem rede e sem modelo — o modelo é um dublê que devolve exatamente os pedaços
que cada caso precisa exercitar, e o armazenamento é um dicionário na memória.

O QUE ESTE TESTE PROTEGE

1. **nenhuma ferramenta do modelo altera a peça.** As que mexeriam (revisar, gerar,
   redigir outra peça, reanalisar) só registram proposta. Se alguém trocar isso por uma
   execução direta "para economizar um clique", um documento jurídico passa a mudar sem
   ninguém ter lido o que mudou;
2. **a falha vira mensagem na transcrição**, e não exceção. A conversa é o registro do
   que foi pedido: um erro que derruba o fluxo apaga da tela a própria pergunta;
3. **o que veio da web chega marcado**, com as fontes separadas do que veio dos autos;
4. **as chamadas de ferramenta picadas pelo fluxo são remontadas** — em streaming o nome
   vem num pedaço e os argumentos em vários outros.

    .venv\\Scripts\\python.exe -m tests.test_chat_peticao
"""

import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.agente import chat_peticao, rotas  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str) -> None:
    global falhas
    print(f"   {'OK  ' if condicao else 'FALHA'} {descricao}")
    if not condicao:
        falhas += 1


# --------------------------------------------------------------- dublês da casa


class ArmazenamentoFalso:
    """O bastante para a conversa existir: uma conversa e a lista de mensagens."""

    def __init__(self) -> None:
        self.mensagens: list[dict] = []
        self.conversa = {
            "id": "conversa-1",
            "usuario": "advogado-1",
            "caso_id": "caso-1",
            "escopo": "PETICAO",
            "criado_em": "2026-09-17T12:00:00",
            "atualizado_em": "2026-09-17T12:00:00",
        }

    def conversa_do_caso(self, usuario, caso_id, *, escopo="PETICAO"):
        return self.conversa

    def obter_caso(self, caso_id):
        return {"id": caso_id, "cliente": "Maria Santos", "categoria": "acidente_trabalho"}

    def criar_conversa(self, titulo, **kwargs):
        return self.conversa

    def registrar_mensagem(self, conversa_id, *, papel, conteudo, natureza, payload=None):
        registro = {
            "id": f"msg-{len(self.mensagens) + 1}",
            "conversa_id": conversa_id,
            "papel": papel,
            "conteudo": conteudo,
            "natureza": natureza,
            "payload": payload or {},
            "criado_em": "2026-09-17T12:00:00",
        }
        self.mensagens.append(registro)
        return registro

    def mensagens_da_conversa(self, conversa_id):
        return list(self.mensagens)

    def atualizar_conversa(self, conversa_id, **kwargs):
        return True


def instalar_armazenamento() -> ArmazenamentoFalso:
    falso = ArmazenamentoFalso()
    chat_peticao.armazenamento = falso  # type: ignore[assignment]
    return falso


#: O fluxo de verdade, guardado antes do primeiro dublê — a seção 9 o exercita.
transmitir_de_verdade = chat_peticao._transmitir
#: Idem para o contexto e o executor, que as seções do fluxo trocam por dublês.
contexto_de_verdade = chat_peticao._contexto_do_caso
executar_de_verdade = chat_peticao.executar_ferramenta


def rodadas(*roteiro: dict):
    """Troca o fluxo do modelo por um roteiro fixo, rodada a rodada.

    Cada item é `{"texto": ..., "chamadas": [...]}` — o que o modelo "responderia"
    naquela volta. Com o modelo de verdade o teste mediria o humor dele.
    """
    sequencia = iter(roteiro)

    def falso(mensagens):
        atual = next(sequencia)
        for pedaco in (atual.get("texto") or ""):
            yield {"tipo": "delta", "texto": pedaco}
        yield {
            "tipo": "mensagem",
            "mensagem": {
                "role": "assistant",
                "content": atual.get("texto") or "",
                "tool_calls": atual.get("chamadas") or [],
            },
        }

    chat_peticao._transmitir = falso  # type: ignore[assignment]


def chamada(nome: str, argumentos: dict) -> dict:
    return {
        "id": f"call-{nome}",
        "function": {"name": nome, "arguments": json.dumps(argumentos, ensure_ascii=False)},
    }


# ------------------------------------------------- 1. o catálogo e a fronteira

print("\n1. O catálogo: quem lê e quem só propõe")

acoes = {nome for nome, (_f, _e, altera) in chat_peticao.CATALOGO.items() if altera}
leituras = {nome for nome, (_f, _e, altera) in chat_peticao.CATALOGO.items() if not altera}

checar(
    all(nome.startswith("propor_") for nome in acoes),
    "toda ferramenta que altera a peça se chama propor_*",
)
checar(
    not any(nome.startswith("propor_") for nome in leituras),
    "e nenhuma ferramenta de leitura se disfarça de proposta",
)
checar(
    {"ler_minuta", "ler_analise", "ler_documentos", "pesquisar_na_web"} <= leituras,
    "a minuta, a análise, os documentos e a web são leituras",
)
checar(len(chat_peticao.esquemas()) == len(chat_peticao.CATALOGO), "todas vão para o modelo")

proposta = chat_peticao.executar_ferramenta(
    "propor_revisao_da_peticao", "caso-1", {"pedido": "retire o pedido de dano material"}
)
checar(proposta["registrada"] and proposta["tipo"] == "REVISAR", "propor devolve a ação, não a executa")
checar(proposta["sensivel"] is True, "retirar um pedido é alteração sensível")
checar(
    chat_peticao.executar_ferramenta(
        "propor_revisao_da_peticao", "caso-1", {"pedido": "troque reclamante por autor"}
    )["sensivel"]
    is False,
    "e uma troca de palavra não é",
)
checar(
    chat_peticao.executar_ferramenta("propor_revisao_da_peticao", "caso-1", {"pedido": " "})[
        "registrada"
    ]
    is False,
    "pedido vazio não vira proposta",
)

# O esquema que vai ao modelo e a função que executa precisam falar do mesmo: um
# parâmetro anunciado e inexistente vira `TypeError` no meio da resposta, e o advogado
# recebe "argumentos inválidos" sem ter feito nada errado.
for nome, (funcao, esquema, _altera) in chat_peticao.CATALOGO.items():
    parametros = list(inspect.signature(funcao).parameters)
    anunciados = set(esquema["parameters"].get("properties") or {})
    checar(parametros[0] == "caso_id", f"{nome} recebe o caso explicitamente")
    checar(anunciados <= set(parametros[1:]), f"{nome} só anuncia parâmetros que aceita")

# Nome inventado pelo modelo é DADO, não exceção: estourar aqui derrubaria a resposta.
inexistente = chat_peticao.executar_ferramenta("ler_o_futuro", "caso-1", {})
checar("erro" in inexistente, "ferramenta inexistente devolve erro em vez de estourar")
ruim = chat_peticao.executar_ferramenta("ler_minuta", "caso-1", {"inventado": 1})
checar("erro" in ruim, "argumento que não existe também vira erro legível")


# --------------------------------------------- 2. as chamadas picadas pelo fluxo

print("\n2. O streaming: remontar a chamada que veio em pedaços")

acumulado: dict[int, dict] = {}
chat_peticao._juntar_chamadas(acumulado, [{"index": 0, "id": "c1", "function": {"name": "ler_minuta"}}])
chat_peticao._juntar_chamadas(acumulado, [{"index": 0, "function": {"arguments": '{"comp'}}])
chat_peticao._juntar_chamadas(acumulado, [{"index": 0, "function": {"arguments": 'leto": true}'}}])
montada = acumulado[0]
checar(montada["function"]["name"] == "ler_minuta", "o nome sobrevive aos pedaços")
# Regressão medida contra a API de verdade: sem `type`, a rodada seguinte — que reenvia
# esta mensagem — volta 400 ("missing field `type`") e a resposta morre no meio.
checar(montada["type"] == "function", "e a chamada remontada leva o `type` que a API exige")
checar(
    json.loads(montada["function"]["arguments"]) == {"completo": True},
    "e os argumentos remontam um JSON válido",
)


# ------------------------------------------------------- 3. a conversa completa

print("\n3. A conversa: consulta, propõe e grava o que sustenta a resposta")

falso = instalar_armazenamento()
chat_peticao._contexto_do_caso = lambda caso_id: "Caso: Maria Santos"  # type: ignore[assignment]
chat_peticao.executar_ferramenta = lambda nome, caso_id, argumentos: (  # type: ignore[assignment]
    {
        "falhou": False,
        "origem": "web",
        "resposta": "A súmula 378 do TST trata disso.",
        "fontes": [{"url": "https://tst.jus.br/sumula-378", "titulo": "Súmula 378", "trecho": "…"}],
    }
    if nome == "pesquisar_na_web"
    else {"registrada": True, "tipo": "REVISAR", "pedido": "cite a súmula 378", "sensivel": False}
)
rodadas(
    {"chamadas": [chamada("pesquisar_na_web", {"pergunta": "súmula 378"})]},
    {"chamadas": [chamada("propor_revisao_da_peticao", {"pedido": "cite a súmula 378"})]},
    {"texto": "Achei a súmula na web e preparei a alteração para você confirmar."},
)

eventos = list(chat_peticao.conversar("caso-1", "procura jurisprudência e cita na peça", "advogado-1"))
tipos = [e["tipo"] for e in eventos]
final = eventos[-1]

checar(tipos[0] == "conversa", "o primeiro evento entrega a pergunta já gravada")
checar("etapa" in tipos, "as consultas aparecem como andamento na tela")
checar(tipos[-1] == "fim", "e a conversa termina com a mensagem gravada")

payload = final["mensagem"]["payload"]
checar(
    payload["fontes"] == [{"url": "https://tst.jus.br/sumula-378", "titulo": "Súmula 378", "trecho": "…"}],
    "a fonte da web viaja com a mensagem — é o que sobrevive ao reload",
)
checar(
    payload["acoes"] and payload["acoes"][0]["tipo"] == "REVISAR",
    "a proposta sobe junto, para virar botão",
)
checar(
    "registrada" not in payload["acoes"][0],
    "e sem o campo interno que só servia ao executor",
)
checar(
    [m["papel"] for m in falso.mensagens] == ["USER", "ASSISTANT"],
    "as duas pontas ficaram na transcrição",
)
checar(falso.mensagens[-1]["natureza"] == "RESPOSTA", "a resposta entra como resposta")


print("\n4. A falha do modelo vira mensagem, não exceção")

falso = instalar_armazenamento()


def modelo_fora_do_ar(mensagens):
    raise chat_peticao.ErroDoChat("O modelo não respondeu a tempo.")
    yield  # pragma: no cover — só para a função ser um gerador


chat_peticao._transmitir = modelo_fora_do_ar  # type: ignore[assignment]
eventos = list(chat_peticao.conversar("caso-1", "e agora?", "advogado-1"))
checar(eventos[-1]["tipo"] == "erro", "o fluxo termina em erro, sem derrubar a chamada")
checar(
    falso.mensagens[-1]["natureza"] == "ERRO"
    and falso.mensagens[-1]["payload"]["pode_repetir"] is True,
    "a falha fica na transcrição, com o que permite tentar de novo",
)
checar(
    falso.mensagens[-1]["payload"]["pergunta"] == "e agora?",
    "e guarda a pergunta original — é ela que o «tentar de novo» reenvia",
)


# ------------------------------------------------------- 5. a IA falando sozinha

print("\n5. Os eventos: a IA conta o que os botões fizeram")

falso = instalar_armazenamento()
chat_peticao._resumo_da_minuta = lambda caso_id: (3, ["passagem de R$ 700,00 sem comprovante"])  # type: ignore[assignment]

mensagem = chat_peticao.registrar_evento("caso-1", "advogado-1", "peticao_gerada", {})
checar(mensagem is not None and "versão 3" in mensagem["conteudo"], "diz em que versão a peça ficou")
checar("R$ 700,00" in mensagem["conteudo"], "e cobra o ponto que continua sem comprovação")
checar(mensagem["natureza"] == "EVENTO", "entra como mensagem da IA, não como resposta")

falha = chat_peticao.registrar_evento(
    "caso-1", "advogado-1", "falha", {"acao": "Gerar a petição", "erro": "502 no modelo"}
)
checar(falha is not None and falha["natureza"] == "ERRO", "a falha de um botão também vira mensagem")
checar("502 no modelo" in falha["conteudo"], "com o motivo que o servidor deu")

checar(
    chat_peticao.registrar_evento("caso-1", "advogado-1", "acontecimento_qualquer", {}) is None,
    "evento sem texto não polui a transcrição",
)


# ----------------------------------------------------- 6. o corte do documento

print("\n6. A leitura da minuta")

peticao = {
    "title": "Petição inicial",
    "version": 2,
    "sections": [
        {"code": "FACTS", "label": "Dos fatos", "content": "x" * 900},
        {"code": "PEDIDOS", "label": "Dos pedidos", "content": "condenação"},
    ],
}
resumida = chat_peticao._texto_da_minuta(peticao, completo=False)
inteira = chat_peticao._texto_da_minuta(peticao, completo=True)
checar("[…]" in resumida and len(resumida) < len(inteira), "sem `completo`, a seção longa vem cortada")
checar("x" * 900 in inteira, "com `completo`, vem inteira")
checar("Dos pedidos" in resumida, "e o rótulo de cada seção sempre acompanha o texto")


# ------------------------------------------------------------- 7. a rota em SSE

print("\n7. A rota: o fluxo chega à tela como Server-Sent Events")


def eventos_falsos(caso_id, pergunta, usuario):
    yield {"tipo": "etapa", "texto": "Lendo a minuta"}
    yield {"tipo": "delta", "texto": "Olha só: «aspas» e acento"}
    yield {"tipo": "fim", "mensagem": {"id": "m1", "papel": "ASSISTANT", "conteudo": "pronto"}}


conversar_de_verdade = chat_peticao.conversar
chat_peticao.conversar = eventos_falsos  # type: ignore[assignment]

app = FastAPI()
app.include_router(rotas.roteador)
resposta = TestClient(app).post(
    "/api/agente/casos/caso-1/chat-peticao/mensagens", json={"mensagem": "e aí?"}
)

checar(resposta.status_code == 200, "a rota responde 200")
checar(
    resposta.headers["content-type"].startswith("text/event-stream"),
    "e declara o tipo que o navegador lê em fluxo",
)
# `X-Accel-Buffering` é o que impede o nginx da frente de juntar os pedaços e entregar
# tudo no fim — o fluxo existiria no servidor e não na tela.
checar(resposta.headers.get("x-accel-buffering") == "no", "com o buffer do proxy desligado")

blocos = [b for b in resposta.text.split("\n\n") if b.strip()]
lidos = [json.loads(b[len("data:") :]) for b in blocos]
checar([e["tipo"] for e in lidos] == ["etapa", "delta", "fim"], "os três eventos chegam na ordem")
checar(
    lidos[1]["texto"] == "Olha só: «aspas» e acento",
    "e o texto atravessa o SSE sem virar escape — a tela mostra o que o modelo escreveu",
)

# O dublê era da rota, não da conversa: quem vier depois exercita a função de verdade.
chat_peticao.conversar = conversar_de_verdade  # type: ignore[assignment]

# --------------------------------------------- 8. prometer não é propor

print("\n8. O modelo diz que propôs, mas não chamou a ferramenta")

falso = instalar_armazenamento()
chat_peticao._contexto_do_caso = lambda caso_id: "Caso: Maria Santos"  # type: ignore[assignment]
chat_peticao.executar_ferramenta = lambda nome, caso_id, argumentos: {  # type: ignore[assignment]
    "registrada": True,
    "tipo": "REVISAR",
    "pedido": "aumente o valor para R$ 60.000",
    "sensivel": True,
}
rodadas(
    # A resposta que o modelo deu de verdade na décima pergunta de uma peça real: o texto
    # perfeito, a ferramenta nunca chamada.
    {"texto": "Registrei o pedido de revisão. Ele não altera nada por si só."},
    {"chamadas": [chamada("propor_revisao_da_peticao", {"pedido": "aumente o valor"})]},
    {"texto": "Preparei a alteração: confirme no cartão acima."},
)

eventos = list(chat_peticao.conversar("caso-1", "aumenta o valor para 60 mil", "advogado-1"))
final = eventos[-1]
acoes = (final["mensagem"]["payload"] or {}).get("acoes") or []
checar(final["tipo"] == "fim", "a conversa termina normalmente")
checar(
    [a["tipo"] for a in acoes] == ["REVISAR"],
    "a cobrança arranca a chamada que faltava, e o cartão de confirmação existe",
)
checar(
    "Registrei o pedido de revisão. Ele não altera nada por si só."
    not in final["mensagem"]["conteudo"],
    "e a mensagem gravada é a corrigida, não a que prometia sem cumprir",
)
checar(
    any(e["tipo"] == "recomeco" for e in eventos),
    "a tela é avisada de que o parcial não vale mais",
)

# Sem promessa, nada é cobrado: uma resposta que só explica não pode custar outra volta.
falso = instalar_armazenamento()
rodadas({"texto": "A minuta está na versão 3 e tem oito seções."})
eventos = list(chat_peticao.conversar("caso-1", "em que versão está?", "advogado-1"))
checar(
    eventos[-1]["mensagem"]["conteudo"] == "A minuta está na versão 3 e tem oito seções.",
    "resposta sem promessa passa direto, sem rodada extra",
)


# ------------------------------------- 9. o corpo que sai pela rede, de verdade

print("\n9. O que é enviado ao modelo (sem dublê de `_transmitir`)")

falso = instalar_armazenamento()
chat_peticao._contexto_do_caso = lambda caso_id: "Caso: Maria Santos"  # type: ignore[assignment]
chat_peticao.executar_ferramenta = lambda nome, caso_id, argumentos: {  # type: ignore[assignment]
    "existe": True,
    "versao": 3,
}

chat_peticao._transmitir = transmitir_de_verdade  # type: ignore[assignment]

corpos_enviados: list[dict] = []


class FluxoFalso:
    """O `httpx.stream` da DeepSeek, com o roteiro de SSE que cada rodada devolve."""

    def __init__(self, linhas):
        self.status_code = 200
        self._linhas = linhas

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def iter_lines(self):
        for linha in self._linhas:
            yield linha


def sse(pedaco: dict) -> str:
    return "data: " + json.dumps({"choices": [{"delta": pedaco}]}, ensure_ascii=False)


ROTEIRO = [
    # 1ª rodada: o modelo chama uma leitura — e o nome vem num pedaço, os argumentos noutro.
    [
        sse({"tool_calls": [{"index": 0, "id": "c1", "type": "function", "function": {"name": "ler_minuta"}}]}),
        sse({"tool_calls": [{"index": 0, "function": {"arguments": "{}"}}]}),
        "data: [DONE]",
    ],
    # 2ª rodada: a resposta, em pedaços.
    [sse({"content": "A minuta "}), sse({"content": "está na versão 3."}), "data: [DONE]"],
]


def stream_falso(metodo, url, *, headers=None, json=None, timeout=None):
    corpos_enviados.append(json)
    return FluxoFalso(ROTEIRO[len(corpos_enviados) - 1])


chat_peticao.os.environ.setdefault("DEEPSEEK_API_KEY", "chave-de-teste")
chat_peticao.httpx.stream = stream_falso  # type: ignore[assignment]

eventos = list(chat_peticao.conversar("caso-1", "em que versão está?", "advogado-1"))
final = eventos[-1]

checar(final["tipo"] == "fim", "a conversa completa com o transporte real")
checar(
    final["mensagem"]["conteudo"] == "A minuta está na versão 3.",
    "os pedaços do fluxo remontam o texto",
)
checar(
    [e["texto"] for e in eventos if e["tipo"] == "delta"] == ["A minuta ", "está na versão 3."],
    "e cada pedaço chegou à tela conforme saiu do modelo",
)

enviadas = [m for corpo in corpos_enviados for m in corpo["messages"]]
checar(
    all(corpo.get("stream") is True and corpo.get("tools") for corpo in corpos_enviados),
    "toda rodada vai em fluxo e com o catálogo de ferramentas",
)
# A regressão medida contra a API: `tool_calls: []` numa mensagem do assistente faz a
# rodada seguinte voltar 400, e a resposta morre no meio. Três de seis pedidos reais
# morreram assim.
checar(
    all("tool_calls" not in m or m["tool_calls"] for m in enviadas),
    "nenhuma mensagem sai com `tool_calls` vazio",
)
checar(
    any(m.get("role") == "tool" for m in enviadas),
    "o resultado da ferramenta volta ao modelo como mensagem `tool`",
)


# ------------------------------------- 10. citar súmula de memória não passa

print("\n10. Citação de norma e de súmula sem ter consultado nada")

checar(
    chat_peticao.citou_sem_conferir("A Súmula 378 do TST garante a estabilidade.", [], []),
    "súmula citada sem consulta alguma é cobrada",
)
checar(
    not chat_peticao.citou_sem_conferir(
        "A Súmula 378 do TST garante.", ["pesquisar_na_web"], [{"url": "https://tst.jus.br/x"}]
    ),
    "com a busca feita e fonte na mão, passa",
)
checar(
    chat_peticao.citou_sem_conferir(
        "A Súmula 378 do TST garante.", ["ler_minuta"], []
    ),
    "ler a minuta NÃO autoriza citar jurisprudência — número de súmula muda",
)
checar(
    not chat_peticao.citou_sem_conferir(
        "O art. 118 da Lei 8.213/1991 está na fundamentação.", ["ler_minuta"], []
    ),
    "mas a norma que está na própria peça, sim: ela já foi conferida na redação",
)
checar(
    chat_peticao.citou_sem_conferir("O art. 118 da Lei 8.213/1991 garante.", [], []),
    "e a mesma norma sem abrir nada é cobrada",
)
checar(
    not chat_peticao.citou_sem_conferir("A minuta tem 8 seções e está na versão 3.", [], []),
    "resposta sem citação nenhuma não paga pedágio",
)

# O laço cobra UMA vez e a resposta gravada é a corrigida — mesmo mecanismo da promessa.
falso = instalar_armazenamento()
chat_peticao._contexto_do_caso = lambda caso_id: "Caso: Maria Santos"  # type: ignore[assignment]
chat_peticao.executar_ferramenta = lambda nome, caso_id, argumentos: {  # type: ignore[assignment]
    "falhou": False,
    "origem": "web",
    "resposta": "Súmula 378 do TST.",
    "fontes": [{"url": "https://www.tst.jus.br/sumulas", "titulo": "TST", "confianca": "TRIBUNAL"}],
    "tem_fonte_oficial": True,
}
rodadas(
    # O que ele fez na prova de fogo: transcreveu a súmula de cabeça e ofereceu um link
    # que nunca abriu.
    {"texto": "A Súmula 378 do TST trata da estabilidade acidentária."},
    {"chamadas": [chamada("pesquisar_na_web", {"pergunta": "Súmula 378 TST"})]},
    {"texto": "Súmula 378 do TST, confirmada no site do tribunal."},
)
eventos = list(chat_peticao.conversar("caso-1", "qual a súmula da estabilidade?", "advogado-1"))
final = eventos[-1]
checar(final["tipo"] == "fim", "a conversa termina normalmente")
checar(
    "pesquisar_na_web" in (final["mensagem"]["payload"] or {}).get("consultas", []),
    "a cobrança leva o modelo à busca que faltava",
)
checar(
    (final["mensagem"]["payload"] or {}).get("fontes"),
    "e a resposta gravada já vai com a fonte",
)


# ----------------------------------- 11. oferecer a consulta não é fazer a consulta

print("\n11. A oferta que não vira consulta")

checar(
    chat_peticao.ofereceu_sem_fazer("O que eu poderia fazer é consultar a jurimetria.", []),
    "«eu poderia consultar» sem ter consultado é cobrado",
)
checar(
    chat_peticao.ofereceu_sem_fazer("Posso pesquisar na web, se você quiser.", []),
    "e «posso pesquisar se você quiser» também — a pergunta já foi feita uma vez",
)
checar(
    not chat_peticao.ofereceu_sem_fazer(
        "Consultei a jurimetria: 12 processos analisados.", ["ler_jurimetria"]
    ),
    "quem consultou não é cobrado",
)
checar(
    not chat_peticao.ofereceu_sem_fazer("Não posso aplicar a alteração sozinho.", []),
    "e a recusa de aplicar sozinho não é oferta de consulta",
)

# A cobrança é BASTIDOR: a resposta gravada não pode comentar a própria correção.
for cobranca in (chat_peticao.COBRANCA, chat_peticao.COBRANCA_FONTE, chat_peticao.COBRANCA_OFERTA):
    checar(
        "primeira e única resposta" in cobranca and "RESPOSTA INTEIRA" in cobranca,
        "a cobrança manda responder à pergunta original, sem narrar a correção",
    )

falso = instalar_armazenamento()
chat_peticao._contexto_do_caso = lambda caso_id: "Caso: Maria Santos"  # type: ignore[assignment]
chat_peticao.executar_ferramenta = lambda nome, caso_id, argumentos: {  # type: ignore[assignment]
    "existe": True,
    "processos_analisados": 12,
    "desfechos_merito": {"favoraveis": 7, "processos": 12},
}
rodadas(
    {"texto": "O que eu poderia fazer é consultar a jurimetria do escritório."},
    {"chamadas": [chamada("ler_jurimetria", {})]},
    {"texto": "Em 12 casos parecidos, 7 foram favoráveis no mérito."},
)
eventos = list(chat_peticao.conversar("caso-1", "qual a chance deste caso?", "advogado-1"))
final = eventos[-1]
checar(
    "ler_jurimetria" in (final["mensagem"]["payload"] or {}).get("consultas", []),
    "a cobrança transforma a oferta na consulta que faltava",
)
checar(
    final["mensagem"]["conteudo"].startswith("Em 12 casos"),
    "e o que fica gravado é a resposta medida, não a promessa de medir",
)


# ------------------------- 12. achar o documento que existe e pedir o que falta

print("\n12. Achar o dado no documento, e pedir o anexo em vez de recusar")

from app import peticao_local  # noqa: E402


class ArmazenamentoDeAnexos:
    """Três entregas: a CTPS com nome de foto, um RG ainda na fila, um holerite."""

    def listar_entregas(self, caso_id):
        return [
            {"id": 1, "arquivo": "IMG_4411.jpg", "tipo_detectado": "CTPS", "status_proc": "pronto"},
            {"id": 2, "arquivo": "WhatsApp Image 2026.jpeg", "tipo_detectado": "desconhecido", "status_proc": "na_fila"},
            {"id": 3, "arquivo": "scan_003.pdf", "tipo_detectado": "HOLERITE", "status_proc": "pronto"},
        ]

    def listar_extracoes_do_caso(self, caso_id):
        cabecalho = "MINISTERIO DO TRABALHO E EMPREGO " * 40  # empurra o número para longe do começo
        return [
            {
                "id": "1",
                "arquivo": "IMG_4411.jpg",
                "extracao": {
                    "tipo": {"descricao": "Carteira de Trabalho (CTPS)"},
                    "campos": [{"nome": "numero", "rotulo": "Número", "valor": "1234567"},
                               {"nome": "serie", "rotulo": "Série", "valor": "0012"}],
                    "texto_completo": cabecalho + "CARTEIRA DE TRABALHO Nº 1234567 SÉRIE 0012-DF PIS 123.45678.90-1",
                },
            },
            {
                "id": "3",
                "arquivo": "scan_003.pdf",
                "extracao": {
                    "tipo": {"descricao": "Holerite"},
                    "campos": [],
                    "texto_completo": "RECIBO DE PAGAMENTO cargo AUXILIAR salário 2.100,00",
                },
            },
        ]


peticao_local.armazenamento = ArmazenamentoDeAnexos()  # type: ignore[assignment]
anexos = peticao_local.anexos_do_caso("caso-1")
checar(len(anexos) == 3, "o anexo ainda sem OCR continua na lista (antes sumia)")
checar(anexos[1]["situacao"] == "na_fila", "e sai marcado como aguardando leitura")
checar(anexos[0]["tipo"].startswith("Carteira de Trabalho"), "o tipo classificado acompanha o arquivo")
checar(len(anexos[0]["texto"]) > 1000, "o texto vem inteiro, sem o corte de quem lê")
checar(anexos[0]["id"] == "1", "o anexo leva o id da entrega — é ele que abre o arquivo")

citaveis = chat_peticao.documentos_citaveis("caso-1")
checar(len(citaveis) == 3, "a tela recebe TODOS os anexos como citáveis, lidos ou não")
checar(
    citaveis[0] == {"id": "1", "arquivo": "IMG_4411.jpg", "tipo": anexos[0]["tipo"], "situacao": "lido"},
    "com id, arquivo, tipo e situação — e sem o texto do OCR",
)

busca = executar_de_verdade("buscar_nos_documentos", "caso-1", {"termo": "número da CTPS"})
checar(busca["encontrado"], "«número da CTPS» acha a CTPS cujo arquivo se chama IMG_4411.jpg")
checar(busca["resultados"][0]["arquivo"] == "IMG_4411.jpg", "e ela vem em primeiro")
checar(
    any("1234567" in t for t in busca["resultados"][0]["trechos"]),
    "com o trecho EM VOLTA do achado, mesmo depois de 1.300 caracteres de cabeçalho",
)
checar(
    any(c["valor"] == "1234567" for c in busca["resultados"][0]["campos_extraidos"]),
    "e com os campos já extraídos pelo OCR",
)
checar(
    any(a["arquivo"].startswith("WhatsApp") for a in busca.get("anexos_sem_texto_lido", [])),
    "o anexo sem leitura é avisado — pode ser o documento",
)

sinonimo = executar_de_verdade("buscar_nos_documentos", "caso-1", {"termo": "carteira de trabalho"})
checar(sinonimo["resultados"][0]["arquivo"] == "IMG_4411.jpg", "«carteira de trabalho» acha a mesma CTPS")

numero = executar_de_verdade("buscar_nos_documentos", "caso-1", {"termo": "12345678901"})
checar(numero["encontrado"], "o PIS digitado sem pontuação acha o PIS que o OCR leu com pontos")

sigla = executar_de_verdade("buscar_nos_documentos", "caso-1", {"termo": "RG"})
checar(
    not any(r["arquivo"] == "scan_003.pdf" for r in sigla["resultados"]),
    "«RG» não casa dentro de «cargo»",
)
checar(not sigla["encontrado"] and "orientacao" in sigla, "e o não-achado vem com a orientação de pedir o anexo")

por_tipo = executar_de_verdade("ler_documentos", "caso-1", {"arquivo": "CTPS"})
checar(
    len(por_tipo["documentos"]) == 1 and por_tipo["documentos"][0]["arquivo"] == "IMG_4411.jpg",
    "ler_documentos também acha pelo tipo, não só pelo nome",
)

chat_peticao.peticao_local.carregar = lambda caso_id: None  # type: ignore[assignment]
contexto = contexto_de_verdade("caso-1")
checar("IMG_4411.jpg (Carteira de Trabalho (CTPS))" in contexto, "o contexto mostra o tipo junto do arquivo")
checar("SEM texto lido" in contexto and "WhatsApp" in contexto, "e os anexos que existem mas não foram lidos")
checar("NÃO está nos autos" not in contexto, "e não manda mais negar o que não está na lista")

print("\n   a recusa")
checar(
    chat_peticao.recusou("Não encontrei o documento, então não vou incluir o número.", []),
    "«não vou incluir» é recusa",
)
checar(
    chat_peticao.recusou("O número da CTPS não consta nos autos.", []),
    "negar o documento sem ter buscado é cobrado",
)
checar(
    not chat_peticao.recusou(
        "Procurei nos 3 anexos e o número da CTPS não consta. Pode anexar a CTPS ou me informar o número?",
        ["buscar_nos_documentos"],
    ),
    "buscou, não achou e pediu o anexo: é a resposta certa",
)
checar(
    not chat_peticao.recusou("Não há prova documental das horas extras; testemunha resolveria.", []),
    "«não há prova» é análise, não recusa",
)
checar(
    not chat_peticao.recusou("Não posso aplicar a alteração sozinho.", []),
    "e a regra de não aplicar sozinho também não",
)
checar("primeira e única resposta" in chat_peticao.COBRANCA_RECUSA, "a cobrança da recusa também é bastidor")
checar("NÃO EXISTE" not in chat_peticao.INSTRUCAO, "a instrução não manda mais tratar ausência como inexistência")

falso = instalar_armazenamento()
chat_peticao._contexto_do_caso = lambda caso_id: "Caso: Maria Santos"  # type: ignore[assignment]
chat_peticao.executar_ferramenta = executar_de_verdade  # type: ignore[assignment]
rodadas(
    {"texto": "Não encontrei esse documento no caso, então não vou incluir o número."},
    {"chamadas": [chamada("buscar_nos_documentos", {"termo": "CTPS"})]},
    {"chamadas": [chamada("propor_revisao_da_peticao", {"pedido": "inclua na qualificação a CTPS nº 1234567, série 0012-DF"})]},
    {"texto": "Achei na CTPS (IMG_4411.jpg): nº 1234567, série 0012-DF. Deixei a inclusão pronta para você confirmar."},
)
eventos = list(chat_peticao.conversar("caso-1", "coloca o número da CTPS, está no caso", "advogado-1"))
final = eventos[-1]
payload = final["mensagem"]["payload"] or {}
checar("buscar_nos_documentos" in payload.get("consultas", []), "a recusa vira busca")
checar(any(a.get("tipo") == "REVISAR" for a in payload.get("acoes", [])), "e a busca vira a proposta pedida")
checar("não vou" not in final["mensagem"]["conteudo"].lower(), "e a recusa não fica gravada")


# ------------------------------- 13. a pesquisa feita não é refeita na pergunta seguinte

print("\n13. Pesquisas na web lembradas entre perguntas")

sumula = {
    "pergunta": "Súmula 378 TST estabilidade",
    "resposta": "A Súmula 378 do TST garante estabilidade ao acidentado.",
    "fontes": [{"url": "https://www.tst.jus.br/sumulas", "titulo": "TST", "confianca": "TRIBUNAL"}],
}
checar(
    not chat_peticao.citou_sem_conferir("A Súmula nº 378 do TST garante.", [], [], [sumula]),
    "súmula confirmada numa pesquisa anterior não é cobrada de novo",
)
checar(
    chat_peticao.citou_sem_conferir("A Súmula 443 do TST protege.", [], [], [sumula]),
    "mas outra súmula, que a pesquisa não cobriu, é",
)
checar(
    chat_peticao.citou_sem_conferir(
        "A Súmula 378 e a Súmula 443 do TST protegem.", [], [], [sumula]
    ),
    "e uma citação coberta não salva a outra no mesmo texto",
)
checar(
    chat_peticao.citou_sem_conferir(
        "A Súmula 378 do TST e o art. 927 do Código Civil.", [], [], [sumula]
    ),
    "nem salva a norma que ninguém conferiu",
)

falso = instalar_armazenamento()
chat_peticao._contexto_do_caso = lambda caso_id: "Caso: Maria Santos"  # type: ignore[assignment]
idas_a_internet: list[str] = []


def executar_contando(nome, caso_id, argumentos):
    if nome == "pesquisar_na_web":
        idas_a_internet.append(argumentos.get("pergunta"))
        return {"falhou": False, "origem": "web", **{k: v for k, v in sumula.items() if k != "pergunta"}}
    return {}


chat_peticao.executar_ferramenta = executar_contando  # type: ignore[assignment]
rodadas(
    {"chamadas": [chamada("pesquisar_na_web", {"pergunta": "Súmula 378 TST estabilidade"})]},
    {"texto": "A Súmula 378 do TST garante a estabilidade."},
)
primeira = list(chat_peticao.conversar("caso-1", "qual a súmula da estabilidade?", "advogado-1"))[-1]
checar(len(idas_a_internet) == 1, "a primeira pergunta vai à internet")
checar(
    (primeira["mensagem"]["payload"] or {}).get("pesquisas", [{}])[0].get("pergunta")
    == "Súmula 378 TST estabilidade",
    "e a pesquisa fica gravada na resposta",
)

sistemas: list[str] = []
roteiro = iter([
    {"chamadas": [chamada("pesquisar_na_web", {"pergunta": "súmula 378  tst ESTABILIDADE"})]},
    {"texto": "Confirmado: Súmula 378 do TST."},
])


def transmitir_espiando(mensagens):
    sistemas.append(mensagens[0]["content"])
    atual = next(roteiro)
    yield {
        "tipo": "mensagem",
        "mensagem": {"role": "assistant", "content": atual.get("texto") or "", "tool_calls": atual.get("chamadas") or []},
    }


chat_peticao._transmitir = transmitir_espiando  # type: ignore[assignment]
segunda = list(chat_peticao.conversar("caso-1", "e confirma essa súmula?", "advogado-1"))
checar(len(idas_a_internet) == 1, "a mesma pesquisa pedida de novo NÃO vai à internet")
checar(
    any(e.get("texto") == "Reaproveitando a pesquisa já feita" for e in segunda if e["tipo"] == "etapa"),
    "e a tela diz que reaproveitou",
)
checar(
    "PESQUISAS NA WEB JÁ FEITAS" in sistemas[0] and "tst.jus.br/sumulas" in sistemas[0],
    "a pesquisa anterior entra no contexto, com a fonte",
)
checar(not (segunda[-1]["mensagem"]["payload"] or {}).get("pesquisas"), "e não é gravada duas vezes")

rodadas({"texto": "Como vimos, a Súmula 378 do TST garante a estabilidade."})
terceira = list(chat_peticao.conversar("caso-1", "resume pra mim", "advogado-1"))[-1]
carga = terceira["mensagem"]["payload"] or {}
checar(terceira["tipo"] == "fim" and not carga.get("consultas"), "citar o que já foi pesquisado não gera cobrança")
checar(
    any(f.get("url") == "https://www.tst.jus.br/sumulas" for f in carga.get("fontes") or []),
    "e a resposta leva a fonte da pesquisa anterior",
)

for m in falso.mensagens:
    if (m.get("payload") or {}).get("pesquisas"):
        m["criado_em"] = "2020-01-01T00:00:00"
checar(chat_peticao._pesquisas_da_conversa("conversa-1") == [], "pesquisa vencida não é lembrada")


if __name__ == "__main__":
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    raise SystemExit(1 if falhas else 0)
