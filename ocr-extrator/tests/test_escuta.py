"""Escuta contínua: o roteiro se preenchendo atrás da conversa.

O modelo é dublado — bater no DeepSeek gastaria crédito a cada execução e faria a
suíte depender de rede.

O que está coberto é o que estraga uma entrevista: o modelo preenchendo campo de
documento a partir de fala, inventando id de pergunta, respondendo pergunta de
módulo que o rastreio não abriu, e o painel mostrando como pendente algo que
acabou de ser respondido.

Rodar: .venv\\Scripts\\python.exe -m tests.test_escuta
"""

from __future__ import annotations

import json
import os

import httpx

from app import escuta


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


FALA = (
    "Eu trabalho nos Correios faz uns oito anos, sou carteiro motociclista. "
    "Fui assaltado duas vezes no ano passado entregando na periferia, e depois "
    "disso não consigo mais dormir direito."
)

visto: dict[str, object] = {}


def _resposta(retorno: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(retorno)}}]},
        request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
    )


def instalar_modelo(retorno: dict):
    def falso(url, **kwargs):
        visto["corpo"] = kwargs.get("json")
        visto["prompt"] = kwargs.get("json", {}).get("messages", [{}, {}])[1].get("content", "")
        return _resposta(retorno)

    escuta.httpx.post = falso  # type: ignore[assignment]


# ------------------------------------------------------------------- testes


def testar_preenchimento() -> int:
    falhas = 0
    instalar_modelo(
        {
            "preenchidas": [
                {"pergunta_id": "tempo_casa", "valor": "cerca de oito anos",
                 "trecho": "trabalho nos Correios faz uns oito anos"},
                {"pergunta_id": "r_assalto", "valor": "sim",
                 "trecho": "Fui assaltado duas vezes"},
            ],
            "lembretes": [
                {"pergunta_id": "r_assalto",
                 "pergunte": "Em que meses aconteceram os assaltos?"},
            ],
        }
    )

    r = escuta.escutar(FALA, {})
    falhas += not checar(r["analisado"] is True, "o trecho foi analisado")
    ids = {p["pergunta_id"] for p in r["preenchidas"]}
    falhas += not checar("tempo_casa" in ids, f"preencheu o tempo de casa ({ids})")
    falhas += not checar("r_assalto" in ids, "e o rastreio de assalto")
    falhas += not checar(
        all(p["trecho"] for p in r["preenchidas"]),
        "cada preenchimento traz o pedaço da fala que o sustenta",
    )
    falhas += not checar(len(r["lembretes"]) == 1, "o lembrete veio junto")
    falhas += not checar(
        r["lembretes"][0]["pergunte"].endswith("?"),
        "e está escrito como pergunta para ler em voz alta",
    )

    # O que acabou de ser respondido não pode continuar na lista de pendências.
    faltando = {f["pergunta_id"] for f in r["faltando"]}
    falhas += not checar(
        not (ids & faltando),
        f"o que entrou agora sai do 'falta perguntar' ({ids & faltando})",
    )
    return falhas


def testar_recusa_documentos() -> int:
    """A regra que protege o contrato: fala não vira número de documento."""
    falhas = 0
    instalar_modelo(
        {
            "preenchidas": [
                {"pergunta_id": "rg", "valor": "1234567", "trecho": "RG mil duzentos..."},
                {"pergunta_id": "nascimento", "valor": "02/05/1980", "trecho": "nasci em..."},
                {"pergunta_id": "rg_orgao", "valor": "SSP", "trecho": "SSP"},
                {"pergunta_id": "tempo_casa", "valor": "oito anos", "trecho": "faz oito"},
            ],
            "lembretes": [],
        }
    )
    r = escuta.escutar(FALA, {})
    ids = {p["pergunta_id"] for p in r["preenchidas"]}
    falhas += not checar("rg" not in ids, "RG ouvido NÃO é preenchido")
    falhas += not checar("nascimento" not in ids, "data de nascimento ouvida NÃO é preenchida")
    falhas += not checar("rg_orgao" not in ids, "órgão expedidor NÃO é preenchido")
    falhas += not checar(
        "tempo_casa" in ids,
        "mas 'oito anos' entra — é resposta de entrevista, não de documentação",
    )

    # E o modelo nem chega a ver essas perguntas: elas saem da lista mandada.
    prompt = str(visto["prompt"])
    falhas += not checar(
        "\n- rg:" not in prompt and "\n- nascimento:" not in prompt,
        "a qualificação nem é oferecida ao modelo",
    )
    # Nome e CPF passaram a ser DIGITADOS antes de a transcrição abrir, e por
    # isso saem da lista também: medido no áudio real, a fala virava "Guilherme
    # Inunes" e o modelo — certo — recusava-se a preencher a partir daquilo.
    falhas += not checar(
        "\n- nome:" not in prompt and "\n- cpf:" not in prompt,
        "nome e CPF nem são oferecidos: são digitados antes de começar",
    )
    return falhas


def testar_nome_e_cpf_sao_digitados() -> int:
    """Nome e CPF NUNCA saem de fala — são digitados antes de a escuta abrir.

    Já foram sugestão, com um clique para confirmar. Medido no áudio real da
    entrevista, não funcionava: o Whisper escrevia "Guilherme Inunes" no lugar
    de "Guilherme Nunes", e o modelo — corretamente — recusava-se a preencher a
    partir de texto ilegível. O campo ficava vazio sem explicação, e o contrato,
    a procuração e a declaração nasciam sem os dois dados que identificam o
    cliente.

    A regra do escritório fechou a questão: os dois são digitados, e é o
    preenchimento deles que libera o microfone.
    """
    falhas = 0
    instalar_modelo(
        {
            "preenchidas": [
                {"pergunta_id": "nome", "valor": "Maria Aparecida da Silva",
                 "trecho": "meu nome é Maria Aparecida"},
                {"pergunta_id": "cpf", "valor": "111.444.777-35", "trecho": "cento e onze..."},
                {"pergunta_id": "tempo_casa", "valor": "oito anos", "trecho": "faz oito"},
            ],
            "lembretes": [],
        }
    )
    r = escuta.escutar(FALA, {})
    preenchidos = {p["pergunta_id"] for p in r["preenchidas"]}

    falhas += not checar(
        preenchidos == {"tempo_casa"}, f"só o relato entra ({preenchidos})"
    )
    # Nem como sugestão: o modelo insistindo neles é descartado nas duas
    # barreiras — a lista que ele recebe e a conferência do que ele devolveu.
    falhas += not checar(
        r["sugestoes"] == [], f"nada vira sugestão ({r['sugestoes']})"
    )
    return falhas


def testar_alucinacao() -> int:
    falhas = 0
    instalar_modelo(
        {
            "preenchidas": [
                {"pergunta_id": "pergunta_que_nao_existe", "valor": "x", "trecho": "y"},
                {"pergunta_id": "tempo_casa", "valor": "", "trecho": "vazio"},
                {"pergunta_id": "r_assalto", "valor": "talvez", "trecho": "sei lá"},
            ],
            "lembretes": ["um lembrete em string solta, não em objeto"],
        }
    )
    r = escuta.escutar(FALA, {})
    falhas += not checar(
        r["preenchidas"] == [],
        f"id inventado, valor vazio e sim_nao ambíguo são descartados ({r['preenchidas']})",
    )
    falhas += not checar(
        len(r["lembretes"]) == 1 and r["lembretes"][0]["pergunta_id"] == "",
        "lembrete em string solta vira objeto sem quebrar o painel",
    )
    return falhas


def testar_modulos_fechados() -> int:
    """Módulo que o rastreio não abriu não entra — nem para preencher."""
    falhas = 0
    instalar_modelo({"preenchidas": [], "lembretes": []})

    # Ninguém respondeu "sim" a assalto: as perguntas do módulo não existem.
    escuta.escutar(FALA, {})
    sem_rastreio = str(visto["prompt"])
    falhas += not checar(
        "as_ocorrencias" not in sem_rastreio,
        "sem rastreio positivo, o módulo de assalto nem é oferecido",
    )

    # Com o "sim", elas passam a existir — mas só depois que as anteriores saem
    # do caminho, porque o teto corta na ordem do roteiro.
    respostas = {"r_assalto": "sim", "tempo_casa": "8 anos", "funcao": "Carteiro Pedestre",
                 "desligamento": "ainda trabalho", "nome": "Maria", "cpf": "111.444.777-35",
                 "r_acidente": "não", "r_doenca": "não", "r_sequela": "não", "r_acao": "não"}
    escuta.escutar(FALA, respostas)
    com_rastreio = str(visto["prompt"])
    falhas += not checar(
        "as_ocorrencias" in com_rastreio,
        "com o rastreio positivo, o módulo de assalto entra",
    )

    # E o teto existe para o prompt não virar as 86 perguntas.
    n = sem_rastreio.count("\n- ")
    falhas += not checar(
        n <= escuta.MAXIMO_PERGUNTAS,
        f"no máximo {escuta.MAXIMO_PERGUNTAS} perguntas por chamada ({n})",
    )
    return falhas


def testar_trecho_curto() -> int:
    falhas = 0
    chamou = {"n": 0}

    def contando(url, **kwargs):
        chamou["n"] += 1
        return _resposta({"preenchidas": [], "lembretes": []})

    escuta.httpx.post = contando  # type: ignore[assignment]

    r = escuta.escutar("aham", {})
    falhas += not checar(chamou["n"] == 0, "'aham' não gasta chamada ao modelo")
    falhas += not checar(r["analisado"] is False, "e sai marcado como não analisado")
    falhas += not checar(
        len(r["faltando"]) > 0,
        "mas o painel do que falta vem mesmo assim — é ele abrindo a entrevista",
    )
    return falhas


def testar_sem_chave() -> int:
    falhas = 0
    guardada = os.environ.get("DEEPSEEK_API_KEY")
    os.environ["DEEPSEEK_API_KEY"] = ""
    try:
        escuta.escutar(FALA, {})
        falhas += not checar(False, "sem chave, recusa explicando")
    except escuta.ErroEscuta as exc:
        falhas += not checar(
            "DEEPSEEK_API_KEY" in str(exc) and "à mão" in str(exc),
            f"o erro diz o que falta E que a entrevista continua ({exc})",
        )
    finally:
        if guardada is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = guardada
    return falhas


def main_teste() -> int:
    guardada = os.environ.get("DEEPSEEK_API_KEY")
    if not guardada:
        os.environ["DEEPSEEK_API_KEY"] = "chave-de-teste"
    original = escuta.httpx.post

    falhas = 0
    for titulo, teste in (
        ("preenchimento e lembretes", testar_preenchimento),
        ("fala NÃO vira número de documento", testar_recusa_documentos),
        ("nome e CPF são digitados, nunca ouvidos", testar_nome_e_cpf_sao_digitados),
        ("alucinação do modelo", testar_alucinacao),
        ("módulos fechados pelo rastreio", testar_modulos_fechados),
        ("trecho curto demais", testar_trecho_curto),
        ("sem chave", testar_sem_chave),
    ):
        print(f"\n{titulo}")
        falhas += teste()

    escuta.httpx.post = original
    if guardada is None:
        os.environ.pop("DEEPSEEK_API_KEY", None)
    else:
        os.environ["DEEPSEEK_API_KEY"] = guardada

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
