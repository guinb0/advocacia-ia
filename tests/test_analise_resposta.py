"""Conferência automática de cada resposta narrativa da entrevista.

O modelo e o banco de precedentes são dublês. Bater no DeepSeek de verdade
gastaria crédito a cada execução, e o pgvector é remoto e já esteve fora do ar —
a suíte não pode depender de nenhum dos dois.

O que está coberto é o que estraga a entrevista: o painel quebrar por causa de
um item mal formatado, a análise sem precedente se passar por análise com
precedente, e o banco morto custar dez segundos por pergunta.

Rodar: .venv\\Scripts\\python.exe -m tests.test_analise_resposta
"""

from __future__ import annotations

import json
import os
import time

import httpx

from app import analise_resposta, rag


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


RESPOSTA = (
    "Eu estava descarregando a caçamba quando o cabo do guincho arrebentou e a "
    "carga caiu no meu pé esquerdo. Fui levado ao pronto-socorro e fiquei "
    "afastado depois disso."
)

#: O que o modelo devolve. Mistura as duas formas de `faltam` de propósito — ele
#: alterna entre string e objeto mesmo com `response_format` de JSON, e uma
#: string chegando onde a tela espera objeto derrubaria o painel inteiro.
RETORNO_MODELO = {
    "suficiente": False,
    "faltam": [
        {"item": "CAT não mencionada", "precedentes": ["P1"]},
        "Não diz se houve testemunha",
        {"item": "Tempo de afastamento indefinido", "precedentes": ["P9", "P2"]},
        {"item": "quarto item que deve ser cortado", "precedentes": []},
    ],
    "perguntar": [
        "A empresa chegou a emitir a CAT?",
        "Alguém viu o cabo arrebentar?",
        "Quantos dias o senhor ficou afastado?",
        "pergunta a mais que deve ser cortada",
    ],
    "observacao": "  Afastamento   sem data\n  dificulta o cálculo. ",
}

chamadas: dict[str, object] = {}


def _resposta_do_modelo(retorno: dict) -> httpx.Response:
    # O `request` não é decoração: sem ele o `raise_for_status` do httpx estoura
    # com RuntimeError em vez de deixar a resposta passar.
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(retorno)}}]},
        request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
    )


def instalar_modelo_falso(retorno: dict | None = None, erro: Exception | None = None):
    """Troca o `httpx.post` que o módulo usa para falar com o DeepSeek."""
    def falso(url, **kwargs):
        chamadas["url"] = url
        chamadas["corpo"] = kwargs.get("json")
        chamadas["timeout"] = kwargs.get("timeout")
        if erro is not None:
            raise erro
        return _resposta_do_modelo(retorno or RETORNO_MODELO)

    analise_resposta.httpx.post = falso  # type: ignore[assignment]


def instalar_precedentes(trechos: list | None = None, erro: Exception | None = None):
    def falso(consulta, **kwargs):
        chamadas["rag_kwargs"] = kwargs
        chamadas["rag_consulta"] = consulta
        if erro is not None:
            raise erro
        return trechos or []

    rag.buscar_similares = falso  # type: ignore[assignment]
    analise_resposta.rag.buscar_similares = falso  # type: ignore[assignment]


def precedente(numero: str, resultado: str = "PROCEDENTE") -> rag.TrechoSimilar:
    return rag.TrechoSimilar(
        texto="Sentença que reconheceu o acidente e deferiu indenização.",
        similaridade=0.83,
        titulo="TRT8 — sentença",
        identificador=numero,
        url="https://exemplo/processo",
        metadados={
            "numero_processo": numero,
            "rotulo": resultado,
            "orgao_julgador": "3ª Vara do Trabalho de Belém",
        },
    )


# ------------------------------------------------------------------- testes


def testar_formato() -> int:
    falhas = 0
    analise_resposta.limpar_cache()
    analise_resposta.religar_precedentes()
    instalar_precedentes([precedente("0001"), precedente("0002", "IMPROCEDENTE")])
    instalar_modelo_falso()

    r = analise_resposta.analisar("en_acidente", "O que exatamente aconteceu?", RESPOSTA)

    falhas += not checar(len(r["faltam"]) == 3, f"no máximo 3 lacunas ({len(r['faltam'])})")
    falhas += not checar(
        len(r["perguntar"]) == 3, f"no máximo 3 perguntas ({len(r['perguntar'])})"
    )
    falhas += not checar(
        all(isinstance(f, dict) and "item" in f for f in r["faltam"]),
        "lacuna em string vira objeto — o painel não quebra por causa de um item",
    )
    falhas += not checar(
        r["faltam"][1]["item"] == "Não diz se houve testemunha",
        f"o texto da lacuna em string é preservado ({r['faltam'][1]['item']!r})",
    )

    # P9 não existe entre os dois precedentes enviados: é referência alucinada.
    # O item fica (a lacuna pode ser real); a referência falsa sai.
    terceiro = r["faltam"][2]
    falhas += not checar(
        terceiro["precedentes"] == ["P2"],
        f"índice de precedente inexistente é descartado ({terceiro['precedentes']})",
    )
    falhas += not checar(
        r["observacao"] == "Afastamento sem data dificulta o cálculo.",
        f"a observação vem numa linha só ({r['observacao']!r})",
    )
    falhas += not checar(r["suficiente"] is False, "com lacunas, não está suficiente")
    falhas += not checar(r["com_precedentes"] is True, "marcado como tendo precedentes")
    falhas += not checar(
        [p["indice"] for p in r["precedentes"]] == ["P1", "P2"],
        "os precedentes usados voltam para a tela",
    )
    falhas += not checar(
        r["precedentes"][0]["processo"] == "0001",
        "com número do processo, para o advogado ir olhar",
    )

    # O teto de tokens é parte do "sucinto": sem ele o modelo escreve parecer.
    corpo = chamadas["corpo"]
    falhas += not checar(corpo["max_tokens"] <= 500, "o teto de tokens segura o tamanho")
    falhas += not checar(corpo["temperature"] == 0, "temperatura zero: conferência, não redação")
    return falhas


def testar_suficiente() -> int:
    falhas = 0
    analise_resposta.limpar_cache()
    instalar_modelo_falso({"suficiente": True, "faltam": [], "perguntar": [], "observacao": ""})
    r = analise_resposta.analisar("en_x", "Pergunta", RESPOSTA)
    falhas += not checar(r["suficiente"] is True, "resposta completa sai como suficiente")

    # O modelo às vezes diz "suficiente" E lista lacunas. Quem manda é a lista,
    # que é o que a tela mostra — senão o painel diria "está completo" com três
    # lacunas embaixo.
    analise_resposta.limpar_cache()
    instalar_modelo_falso(
        {"suficiente": True, "faltam": [{"item": "falta a data"}], "perguntar": [], "observacao": ""}
    )
    r = analise_resposta.analisar("en_x", "Pergunta", RESPOSTA)
    falhas += not checar(
        r["suficiente"] is False,
        "modelo se contradizendo: a lista de lacunas vence o 'suficiente'",
    )
    return falhas


def testar_sem_precedentes() -> int:
    """O banco fora do ar não pode passar por 'o que os processos mostram'."""
    falhas = 0
    analise_resposta.limpar_cache()
    analise_resposta.religar_precedentes()
    instalar_precedentes(erro=TimeoutError("connection timeout expired"))
    instalar_modelo_falso()

    r = analise_resposta.analisar("en_acidente", "O que aconteceu?", RESPOSTA)
    falhas += not checar(r["com_precedentes"] is False, "marcado como SEM precedentes")
    falhas += not checar(r["precedentes"] == [], "nenhum precedente na resposta")
    falhas += not checar(
        "Sem precedentes" in r["aviso"],
        f"o aviso diz que a análise não veio dos processos ({r['aviso'][:60]}…)",
    )
    falhas += not checar(
        all(f["precedentes"] == [] for f in r["faltam"]),
        "sem precedente enviado, nenhuma lacuna cita índice",
    )
    falhas += not checar(
        "nenhum disponível" in chamadas["corpo"]["messages"][1]["content"],
        "o modelo é avisado de que não há precedente",
    )
    return falhas


def testar_disjuntor() -> int:
    """Banco morto não pode custar o timeout a cada pergunta — mas um pico de
    latência isolado também não pode custar uma entrevista inteira."""
    falhas = 0
    analise_resposta.limpar_cache()
    analise_resposta.religar_precedentes()
    instalar_modelo_falso()

    tentativas = {"n": 0}

    def lento(consulta, **kwargs):
        tentativas["n"] += 1
        time.sleep(0.05)
        raise TimeoutError("connection timeout expired")

    rag.buscar_similares = lento  # type: ignore[assignment]
    analise_resposta.rag.buscar_similares = lento  # type: ignore[assignment]

    for i in range(5):
        analise_resposta.analisar("en_x", f"Pergunta {i}", RESPOSTA + f" variação {i}")

    # A 1ª pergunta gasta as duas tentativas internas e abre o disjuntor; da 2ª
    # em diante nem tenta.
    falhas += not checar(
        tentativas["n"] == analise_resposta.TENTATIVAS_RAG,
        f"a 1ª pergunta tenta {analise_resposta.TENTATIVAS_RAG}x e as seguintes nem "
        f"tentam ({tentativas['n']} tentativas ao todo)",
    )

    # --- o pico isolado é absorvido pela retentativa INTERNA ---------------
    # É o padrão medido em 13-14/08 contra este servidor: a 1ª conexão estoura,
    # a 2ª conecta. Antes isso custava um "sem precedentes"; agora a própria
    # busca tenta de novo e a pergunta sai COM processos citados.
    analise_resposta.religar_precedentes()
    analise_resposta.limpar_cache()
    chamadas = {"n": 0}

    def instavel(consulta, **kwargs):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise TimeoutError("pico de latência na primeira conexão")
        return [precedente("0007")]

    rag.buscar_similares = instavel  # type: ignore[assignment]
    analise_resposta.rag.buscar_similares = instavel  # type: ignore[assignment]

    a = analise_resposta.analisar("en_a", "Primeira", RESPOSTA + " um")
    falhas += not checar(
        a["com_precedentes"] is True,
        "o pico da 1ª conexão não custa mais os precedentes — a busca retenta",
    )
    falhas += not checar(chamadas["n"] == 2, f"foram 2 tentativas ({chamadas['n']})")

    b = analise_resposta.analisar("en_b", "Segunda", RESPOSTA + " dois")
    falhas += not checar(
        b["com_precedentes"] is True, "e o disjuntor segue fechado para as seguintes"
    )
    return falhas


def testar_prazos() -> int:
    """Os prazos aqui são de quem tem cliente na frente, não os da ingestão."""
    falhas = 0
    analise_resposta.limpar_cache()
    analise_resposta.religar_precedentes()
    instalar_precedentes([precedente("0003")])
    instalar_modelo_falso()
    analise_resposta.analisar("en_x", "Pergunta", RESPOSTA)

    kw = chamadas["rag_kwargs"]
    # Curto o bastante para não travar a entrevista, largo o bastante para o pico
    # de ~7s medido em 13/08 não descartar precedente com o banco vivo.
    falhas += not checar(
        4 <= kw["connect_timeout"] <= 10 and kw["timeout"] <= 10,
        f"o prazo do banco cabe no pico medido ({kw['timeout']}s / {kw['connect_timeout']}s)",
    )
    falhas += not checar(
        chamadas["timeout"] <= 30, f"o modelo também ({chamadas['timeout']}s)"
    )
    falhas += not checar(kw["limite"] <= 4, f"poucos precedentes ({kw['limite']})")

    # A busca precisa carregar a pergunta junto: "ele caiu" sozinho não recupera
    # nada parecido; "acidente de trabalho — ele caiu" recupera.
    falhas += not checar(
        "Pergunta" in chamadas["rag_consulta"] and "caçamba" in chamadas["rag_consulta"],
        "a busca usa pergunta e resposta juntas",
    )
    return falhas


def testar_cache() -> int:
    falhas = 0
    analise_resposta.limpar_cache()
    analise_resposta.religar_precedentes()
    instalar_precedentes([precedente("0004")])

    vezes = {"n": 0}

    def contando(url, **kwargs):
        vezes["n"] += 1
        chamadas["corpo"] = kwargs.get("json")
        return _resposta_do_modelo(RETORNO_MODELO)

    analise_resposta.httpx.post = contando  # type: ignore[assignment]

    a = analise_resposta.analisar("en_x", "Pergunta", RESPOSTA)
    b = analise_resposta.analisar("en_x", "Pergunta", RESPOSTA)
    falhas += not checar(vezes["n"] == 1, f"texto igual não gasta outra chamada ({vezes['n']})")
    falhas += not checar(a["do_cache"] is False and b["do_cache"] is True, "a 2ª vem do cache")
    falhas += not checar(a["faltam"] == b["faltam"], "e traz o mesmo conteúdo")

    analise_resposta.analisar("en_x", "Pergunta", RESPOSTA + " E ainda tem mais uma coisa.")
    falhas += not checar(vezes["n"] == 2, "resposta alterada analisa de novo")

    # Complemento gravado depois muda o texto — e é justamente aí que a análise
    # precisa rodar outra vez, senão o painel congela na versão incompleta.
    return falhas


def testar_recusas() -> int:
    falhas = 0
    analise_resposta.limpar_cache()
    instalar_precedentes([])
    instalar_modelo_falso()

    try:
        analise_resposta.analisar("en_x", "Pergunta", "Sim.")
        falhas += not checar(False, "resposta curta é recusada")
    except analise_resposta.ErroAnalise as exc:
        falhas += not checar("curta demais" in str(exc), f"e diz por quê ({exc})")

    guardada = os.environ.get("DEEPSEEK_API_KEY")
    os.environ["DEEPSEEK_API_KEY"] = ""
    try:
        analise_resposta.analisar("en_x", "Pergunta", RESPOSTA)
        falhas += not checar(False, "sem chave, recusa explicando")
    except analise_resposta.ErroAnalise as exc:
        falhas += not checar(
            "DEEPSEEK_API_KEY" in str(exc) and "entrevista segue" in str(exc),
            f"o erro diz o que falta E que a entrevista não para ({exc})",
        )
    finally:
        if guardada is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = guardada

    analise_resposta.limpar_cache()
    instalar_modelo_falso(erro=httpx.ConnectTimeout("estourou"))
    try:
        analise_resposta.analisar("en_x", "Pergunta", RESPOSTA)
        falhas += not checar(False, "modelo fora do ar vira ErroAnalise")
    except analise_resposta.ErroAnalise as exc:
        falhas += not checar(
            "entrevista pode seguir" in str(exc),
            f"e a mensagem não sugere parar a entrevista ({exc})",
        )
    return falhas


def main_teste() -> int:
    guardada = os.environ.get("DEEPSEEK_API_KEY")
    os.environ.setdefault("DEEPSEEK_API_KEY", "chave-de-teste")
    if not os.environ["DEEPSEEK_API_KEY"]:
        os.environ["DEEPSEEK_API_KEY"] = "chave-de-teste"

    post_original = analise_resposta.httpx.post
    busca_original = rag.buscar_similares

    falhas = 0
    for titulo, teste in (
        ("formato do que vai para a tela", testar_formato),
        ("resposta completa", testar_suficiente),
        ("banco de precedentes fora do ar", testar_sem_precedentes),
        ("disjuntor do banco", testar_disjuntor),
        ("prazos de quem tem cliente na frente", testar_prazos),
        ("cache entre cliques", testar_cache),
        ("recusas com mensagem útil", testar_recusas),
    ):
        print(f"\n{titulo}")
        falhas += teste()

    analise_resposta.httpx.post = post_original
    rag.buscar_similares = busca_original
    analise_resposta.rag.buscar_similares = busca_original
    if guardada is None:
        os.environ.pop("DEEPSEEK_API_KEY", None)
    else:
        os.environ["DEEPSEEK_API_KEY"] = guardada

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
