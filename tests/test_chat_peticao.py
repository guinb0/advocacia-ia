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


if __name__ == "__main__":
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    raise SystemExit(1 if falhas else 0)
