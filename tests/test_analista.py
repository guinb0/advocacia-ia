"""O guardrail do analista: o que ele deixa passar, o que descarta e quando recusa.

Sem banco, sem rede e sem modelo — o modelo é um dublê que devolve exatamente o que cada
caso precisa exercitar. É a única forma de provar a regra: com o modelo de verdade, a
resposta muda a cada rodada e o teste passaria a medir o humor dele.

O QUE ESTE TESTE PROTEGE

Duas falhas opostas, e as duas já aconteceram neste repositório:

1. **deixar passar sem lastro** — "63 casos estão parados" soa idêntico esteja certo ou
   inventado, e é a falácia mais fácil de produzir numa pergunta de agregação;
2. **recusar demais** — três vezes um guard deste sistema reprovou a resposta CERTA por
   exigir lastro de quem não devia. Uma recomendação é leitura, não medição, e exigir
   referência dela ensina o advogado a ignorar o guardrail.

    .venv\\Scripts\\python.exe -m tests.test_analista
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agente import analista, ferramentas  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str) -> None:
    global falhas
    print(f"   {'OK  ' if condicao else 'FALHA'} {descricao}")
    if not condicao:
        falhas += 1


def dublê(*, investigacao: list[dict] | None = None, redacao: dict) -> None:
    """Troca o modelo por um roteiro fixo: o que ele 'responderia' em cada chamada."""
    rodadas = list(investigacao or [{"role": "assistant", "content": "já sei responder"}])
    rodadas.append({"role": "assistant", "content": json.dumps(redacao, ensure_ascii=False)})
    sequencia = iter(rodadas)

    def falso(mensagens, *, ferramentas_do_modelo, json_puro):
        return next(sequencia)

    analista._chamar = falso  # type: ignore[assignment]


def ferramenta_falsa(nome_esperado: str, dados: dict, refs: set[str]) -> None:
    """Substitui o catálogo: o teste é do guardrail, não da leitura do banco."""

    def executar(nome, argumentos):
        assert nome == nome_esperado, f"o analista chamou {nome}"
        return ferramentas.Resultado(dados=dados, refs=set(refs))

    analista.ferramentas.executar = executar  # type: ignore[assignment]


def chamada_de_ferramenta(nome: str, argumentos: dict) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "chamada-1",
                "type": "function",
                "function": {"name": nome, "arguments": json.dumps(argumentos)},
            }
        ],
    }


print("\n1. A afirmação factual precisa de lastro")
ferramenta_falsa("panorama_do_escritorio", {"parados": 63}, {"panorama"})
dublê(
    investigacao=[chamada_de_ferramenta("panorama_do_escritorio", {}), {"role": "assistant", "content": "pronto"}],
    redacao={
        "resposta": "63 casos estão parados.",
        "afirmacoes": [
            {"statement": "63 casos parados", "nature": "STATISTICAL_PATTERN", "refs": ["panorama"]},
            # A mesma frase sem lastro: é ela que não pode chegar ao advogado.
            {"statement": "e 12 vencem esta semana", "nature": "PROVEN_FACT", "refs": []},
            # Lastro que NENHUMA ferramenta devolveu — inventar a referência não vale.
            {"statement": "o faturamento caiu", "nature": "PROVEN_FACT", "refs": ["financeiro"]},
        ],
        "pendencias": [],
    },
)
analise = analista.responder("quantos casos estão parados?")
statements = [a["statement"] for a in analise.afirmacoes]
checar(statements == ["63 casos parados"], "só a afirmação com lastro sobrevive")
checar(analise.recusa is None, "e a resposta continua sendo entregue")
checar(
    any("retirada" in p for p in analise.pendencias),
    "o advogado é avisado de que algo foi retirado — descarte silencioso seria pior",
)
checar(
    analise.consultas == [{"ferramenta": "panorama_do_escritorio", "argumentos": {}, "passo": 1}],
    "a consulta feita fica registrada, para a tela poder mostrar o caminho",
)


print("\n2. Leitura NÃO precisa de lastro — o guard não pode recusar demais")
ferramenta_falsa("panorama_do_escritorio", {"parados": 63}, {"panorama"})
dublê(
    investigacao=[chamada_de_ferramenta("panorama_do_escritorio", {}), {"role": "assistant", "content": "ok"}],
    redacao={
        "resposta": "O gargalo é a entrevista.",
        "afirmacoes": [
            {"statement": "63 casos parados", "nature": "STATISTICAL_PATTERN", "refs": ["panorama"]},
            {"statement": "o gargalo é a entrevista", "nature": "INFERENCE", "refs": []},
            {"statement": "vale cobrar os documentos hoje", "nature": "RECOMMENDATION", "refs": []},
            {"statement": "o cliente relatou dor no ombro", "nature": "ALLEGED_FACT", "refs": []},
        ],
        "pendencias": [],
    },
)
analise = analista.responder("o que está travando?")
naturezas = [a["nature"] for a in analise.afirmacoes]
checar(len(analise.afirmacoes) == 4, "inferência, recomendação e alegação passam sem referência")
checar("RECOMMENDATION" in naturezas and "ALLEGED_FACT" in naturezas, "com a natureza intacta")
checar(not analise.pendencias, "e nada é declarado como retirado, porque nada foi")


print("\n3. Quando NADA se sustenta, a resposta não é entregue")
ferramenta_falsa("panorama_do_escritorio", {}, set())
dublê(
    investigacao=[{"role": "assistant", "content": "não consultei nada"}],
    redacao={
        "resposta": "São 412 casos e o faturamento subiu 20%.",
        "afirmacoes": [
            {"statement": "são 412 casos", "nature": "PROVEN_FACT", "refs": []},
            {"statement": "o faturamento subiu 20%", "nature": "STATISTICAL_PATTERN", "refs": []},
        ],
        "pendencias": [],
    },
)
analise = analista.responder("como estamos?")
checar(analise.recusa == "sem lastro", "a resposta inteira é reprovada")
checar(
    "412" not in analise.conteudo,
    "e o número reprovado NÃO chega à tela — entregar o texto anularia o guardrail",
)
checar(bool(analise.pendencias), "com o motivo declarado")


print("\n4. Natureza desconhecida vira a que promete menos")
ferramenta_falsa("panorama_do_escritorio", {"x": 1}, {"panorama"})
dublê(
    investigacao=[chamada_de_ferramenta("panorama_do_escritorio", {}), {"role": "assistant", "content": "ok"}],
    redacao={
        "resposta": "texto",
        "afirmacoes": [{"statement": "algo", "nature": "CERTEZA_ABSOLUTA", "refs": ["panorama"]}],
        "pendencias": [],
    },
)
analise = analista.responder("?")
checar(
    analise.afirmacoes[0]["nature"] == "INFERENCE",
    "natureza inventada pelo modelo cai em INFERENCE, nunca em PROVEN_FACT",
)


print("\n5. Os casos citados viram caminho até o dossiê")
ferramenta_falsa("listar_casos", {"casos": []}, {"caso:aaa", "caso:bbb", "panorama"})
dublê(
    investigacao=[chamada_de_ferramenta("listar_casos", {"termo": "maria"}), {"role": "assistant", "content": "ok"}],
    redacao={
        "resposta": "dois casos",
        "afirmacoes": [
            {"statement": "um", "nature": "PROVEN_FACT", "refs": ["caso:bbb", "panorama"]},
            {"statement": "dois", "nature": "PROVEN_FACT", "refs": ["caso:aaa", "caso:bbb"]},
        ],
        "pendencias": [],
    },
)
analise = analista.responder("quais casos da maria?")
checar(analise.casos == ["bbb", "aaa"], "na ordem em que aparecem, sem repetir")
checar(
    analise.afirmacoes[0]["refs"] == ["caso:bbb", "panorama"],
    "a referência que não é caso continua sustentando a afirmação",
)


print("\n6. Argumento ilegível do modelo não derruba a conversa")
recebidos: list[dict] = []


def registrar(nome, argumentos):
    recebidos.append({"nome": nome, "argumentos": argumentos})
    return ferramentas.Resultado(dados={"ok": True}, refs={"panorama"})


analista.ferramentas.executar = registrar  # type: ignore[assignment]
quebrado = chamada_de_ferramenta("panorama_do_escritorio", {})
quebrado["tool_calls"][0]["function"]["arguments"] = "{isto não é json"
dublê(
    investigacao=[quebrado, {"role": "assistant", "content": "ok"}],
    redacao={"resposta": "segue", "afirmacoes": [], "pendencias": []},
)
analise = analista.responder("?")
checar(recebidos and recebidos[0]["argumentos"] == {}, "argumento ilegível vira dicionário vazio")
checar(analise.conteudo == "segue", "e a resposta continua sendo produzida")


# O placar e a saída ficam sob a guarda de `__main__`, como nos demais testes da casa
# (ver `tests/test_perfis.py`). Solto no nível do módulo, o `SystemExit` era disparado
# durante o IMPORT do arquivo — e como o nome começa com `test_`, qualquer `pytest`
# que varresse a pasta morria em `INTERNALERROR` ao coletar este arquivo, levando
# junto a suíte inteira. O jeito de rodar continua o mesmo: `python -m tests.<nome>`.
if __name__ == "__main__":
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    raise SystemExit(1 if falhas else 0)
