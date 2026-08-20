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


def cenario_preenchimento() -> int:
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


def cenario_recusa_documentos() -> int:
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


def cenario_nome_e_cpf_sao_digitados() -> int:
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


def cenario_alucinacao() -> int:
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


def cenario_modulos_fechados() -> int:
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


def cenario_trecho_curto() -> int:
    falhas = 0
    chamou = {"n": 0}

    def contando(url, **kwargs):
        chamou["n"] += 1
        return _resposta({"preenchidas": [], "lembretes": []})

    escuta.httpx.post = contando  # type: ignore[assignment]

    # O piso é 3 desde que `MINIMO_CARACTERES` caiu de 25: abaixo disto não há o
    # que interpretar; acima, a chamada acontece mesmo em cima de ruído. É a
    # decisão registrada no módulo, porque o outro lado — perder "motorizado",
    # "cinco anos", "8 vezes" — é pior, e ninguém percebe uma resposta perdida.
    r = escuta.escutar("é", {})
    falhas += not checar(chamou["n"] == 0, "trecho de um caractere não gasta chamada")
    falhas += not checar(r["analisado"] is False, "e sai marcado como não analisado")
    falhas += not checar(
        len(r["faltando"]) > 0,
        "mas o painel do que falta vem mesmo assim — é ele abrindo a entrevista",
    )

    escuta.escutar("aham", {})
    falhas += not checar(
        chamou["n"] == 1,
        "'aham' passa do piso e vai ao modelo — quem julga ambiguidade é ele",
    )
    return falhas


def cenario_sim_nao_curto() -> int:
    falhas = 0
    roteiro = escuta.roteiros.obter("empregado_publico")
    assert roteiro is not None
    perguntas = [p for b in roteiro.blocos for p in b.perguntas]
    objetiva = next(p for p in perguntas if p.tipo == "sim_nao")
    composta = next(p for p in perguntas if p.id == "desligamento")

    sim = escuta._binaria_curta("Sim.", [objetiva])
    nao = escuta._binaria_curta("não", [composta])
    ambigua = escuta._binaria_curta("aham", [objetiva])
    falhas += not checar(sim is not None and sim["valor"] == "sim", "'sim' preenche pergunta objetiva")
    falhas += not checar(nao is not None and nao["valor"] == "não", "'não' preenche pergunta composta binária")
    falhas += not checar(ambigua is None, "'aham' continua ambíguo e não preenche")

    acao = next(p for p in perguntas if p.id == "r_acao")
    misto = escuta._binaria_apos_enunciado(
        "Já entrou com ação judicial contra os Correios sobre esses assuntos? Sim.",
        acao,
    )
    falhas += not checar(
        misto is not None and misto["pergunta_id"] == "r_acao" and misto["valor"] == "sim",
        "resposta dada no mesmo trecho da pergunta não é descartada como enunciado",
    )
    falhas += not checar(
        escuta._binaria_apos_enunciado(
            "Já entrou com ação judicial contra os Correios sobre esses assuntos? sim ou não",
            acao,
        ) is None,
        "advogado lendo as opções sim ou não não responde pelo cliente",
    )
    return falhas


def cenario_pergunta_da_tela() -> int:
    """A pergunta que está na tela tem de chegar ao modelo — sempre.

    É o que faltava quando o entrevistador reclamou que "depois de um tempo o
    agente fica ruim": a resposta curta continuava chegando, mas a pergunta que
    ela responde não cabia mais na janela, e o modelo tinha de adivinhar de qual
    das dezoito ela era.
    """
    falhas = 0
    instalar_modelo({"preenchidas": [], "lembretes": []})

    roteiro = escuta.roteiros.obter("empregado_publico")
    assert roteiro is not None

    escuta.escutar(FALA, {}, "empregado_publico", "desligamento")
    prompt = str(visto["prompt"])
    falhas += not checar(
        "PERGUNTA NA TELA AGORA:" in prompt and "desligamento:" in prompt,
        "a pergunta da vez vai no prompt, em seção própria",
    )

    # A entrevista adiantada: as primeiras do roteiro ficaram para depois e se
    # acumulam no topo da lista de abertas. Sem a janela, elas empurram a
    # pergunta da tela para fora do teto — e era o que acontecia.
    abertas_todas = [
        p
        for bloco in roteiro.blocos
        if not bloco.modulo and not bloco.delegado_a
        for p in bloco.perguntas
        if not p.validacao and p.id not in escuta.DADOS_DIGITADOS
    ]
    falhas += not checar(
        len(abertas_todas) > escuta.MAXIMO_PERGUNTAS,
        f"o roteiro tem mais abertas que o teto ({len(abertas_todas)})",
    )
    la_atras = abertas_todas[escuta.MAXIMO_PERGUNTAS + 2].id
    janela = escuta._perguntas_abertas(roteiro, {}, la_atras)
    falhas += not checar(
        any(p.id == la_atras for p in janela),
        f"pergunta fora do teto entra na janela por ser a da tela ({la_atras})",
    )
    falhas += not checar(
        len(janela) <= escuta.MAXIMO_PERGUNTAS,
        f"e a janela continua cabendo no teto ({len(janela)})",
    )
    falhas += not checar(
        janela[0].id == la_atras,
        "ela vem primeiro: é a que o cliente está respondendo agora",
    )
    # As deixadas para trás ficam com o resto da janela, as mais próximas
    # primeiro: o cliente volta ao que se falou há pouco, não ao que ficou para
    # trás meia hora atrás.
    vizinha_atras = abertas_todas[escuta.MAXIMO_PERGUNTAS + 1].id
    falhas += not checar(
        any(p.id == vizinha_atras for p in janela),
        f"e as deixadas para trás continuam tendo vaga ({vizinha_atras})",
    )
    falhas += not checar(
        len(janela) == escuta.MAXIMO_PERGUNTAS,
        f"a janela é usada inteira, não pela metade ({len(janela)})",
    )
    return falhas


def cenario_complemento() -> int:
    """O cliente volta ao assunto e traz o que faltou — no campo de lá, não neste.

    "Quantas vezes e em que anos?" foi respondida com "8 vezes". Os anos vieram
    dois minutos depois. Antes disto a pergunta já tinha saído da lista de
    abertas, e o dado não tinha mais onde cair.
    """
    falhas = 0
    roteiro = escuta.roteiros.obter("empregado_publico")
    assert roteiro is not None

    completavel = next(
        p
        for bloco in roteiro.blocos
        for p in bloco.perguntas
        if p.tipo not in escuta.TIPOS_FECHADOS
        and not p.opcoes
        and not p.validacao
        and p.id not in escuta.DADOS_DIGITADOS
    )
    respostas = {completavel.id: "8 vezes"}

    instalar_modelo(
        {
            "preenchidas": [],
            "complementos": [
                {
                    "pergunta_id": completavel.id,
                    "valor": "2022, 2023 e 2024",
                    "trecho": "foi em 2022, 2023 e 2024",
                }
            ],
            "lembretes": [],
        }
    )
    r = escuta.escutar("foi em 2022, 2023 e 2024", respostas, "empregado_publico", "")
    prompt = str(visto["prompt"])
    falhas += not checar(
        "JÁ RESPONDIDAS" in prompt and '"8 vezes"' in prompt,
        "a já respondida volta ao prompt com o que está no campo",
    )
    complementos = [p for p in r["preenchidas"] if p.get("complemento")]
    falhas += not checar(
        len(complementos) == 1 and complementos[0]["valor"] == "2022, 2023 e 2024",
        f"o acréscimo entra marcado como complemento ({complementos})",
    )

    # A tela ACRESCENTA ao campo. Complemento que repete o que já está lá sairia
    # escrito duas vezes — e iria duplicado para a peça.
    instalar_modelo(
        {
            "preenchidas": [],
            "complementos": [
                {"pergunta_id": completavel.id, "valor": "8 vezes", "trecho": "oito vezes"}
            ],
            "lembretes": [],
        }
    )
    r = escuta.escutar("foram oito vezes mesmo", respostas, "empregado_publico", "")
    falhas += not checar(
        r["preenchidas"] == [],
        f"complemento que repete o campo é descartado ({r['preenchidas']})",
    )

    # E quando o modelo devolve a resposta inteira em vez do que faltava, o que
    # o campo já tem é recortado fora — senão duplicaria do mesmo jeito.
    falhas += not checar(
        escuta._acrescimo("8 vezes, em 2022 e 2023", "8 vezes") == "em 2022 e 2023",
        "resposta inteira vira só o que sobra dela",
    )
    falhas += not checar(
        escuta._acrescimo("oito vezes", "8 vezes") == "oito vezes",
        "e o que é novo passa inteiro",
    )

    # Campo fechado não se completa: "sim" mais "não" no mesmo campo é pior que
    # resposta faltando.
    binaria = next(p for b in roteiro.blocos for p in b.perguntas if p.tipo == "sim_nao")
    completaveis = escuta._completaveis(roteiro, {binaria.id: "sim"}, "")
    falhas += not checar(
        all(p.id != binaria.id for p, _ in completaveis),
        "pergunta de sim ou não não é oferecida para complemento",
    )

    # Informação importante pode voltar muito depois. Nenhuma resposta narrativa
    # pode desaparecer por estar longe da pergunta atual ou por já ser longa.
    narrativas = [
        p
        for bloco in roteiro.blocos
        for p in bloco.perguntas
        if p.tipo not in escuta.TIPOS_FECHADOS
        and not p.opcoes
        and not p.validacao
        and p.id not in escuta.DADOS_DIGITADOS
    ]
    respostas_largas = {p.id: "relato " * 100 for p in narrativas}
    todos = escuta._completaveis(roteiro, respostas_largas, narrativas[-1].id)
    ids_completaveis = {p.id for p, _ in todos}
    falhas += not checar(
        ids_completaveis == {p.id for p in narrativas},
        "todas as narrativas respondidas, inclusive distantes e longas, podem receber complemento",
    )
    return falhas


def cenario_enunciado_lido() -> int:
    """A pergunta sendo LIDA não responde nada — nem gasta chamada ao modelo.

    O trecho fecha quando o texto para de mudar, ou seja, na pausa; e a primeira
    pausa de toda pergunta é a do entrevistador terminando de fazê-la. Sem esta
    guarda o campo se preenchia ali, com o enunciado, antes de o cliente abrir a
    boca — foi o que o escritório relatou.
    """
    falhas = 0
    chamou = {"n": 0}

    def contando(url, **kwargs):
        chamou["n"] += 1
        return _resposta({"preenchidas": [], "lembretes": []})

    escuta.httpx.post = contando  # type: ignore[assignment]

    roteiro = escuta.roteiros.obter("empregado_publico")
    assert roteiro is not None
    perguntas = {p.id: p for b in roteiro.blocos for p in b.perguntas}
    tempo_casa = perguntas["tempo_casa"]

    r = escuta.escutar(
        "há quanto tempo o senhor trabalha nos Correios?", {}, "empregado_publico", "tempo_casa"
    )
    falhas += not checar(
        r["preenchidas"] == [] and r.get("enunciado") == "tempo_casa",
        f"a pergunta lida não preenche nada e sai identificada ({r.get('enunciado')})",
    )
    falhas += not checar(chamou["n"] == 0, "e nem chega a gastar chamada ao modelo")

    # A leitura cortada no meio é o caso que o escritório descreveu — "ele corta
    # quando eu paro de falar". Com o ponto de interrogação ela é reconhecível
    # mesmo curta.
    falhas += not checar(
        escuta._e_o_enunciado("ainda trabalha na empresa?", [perguntas["desligamento"]])
        is not None,
        "leitura cortada no meio, com interrogação, também é enunciado",
    )

    # E o outro lado, que importa mais: resposta não pode morrer aqui.
    for fala in ("sim", "oito anos", "eu trabalho lá faz uns oito anos", "carteiro motociclista"):
        falhas += not checar(
            escuta._e_o_enunciado(fala, list(perguntas.values())[:20]) is None,
            f"resposta do cliente continua passando ({fala!r})",
        )

    # A resposta que ECOA a pergunta é resposta, e é o limite do que dá para
    # separar por texto: sem "eu", sobra o mesmo punhado de palavras.
    falhas += not checar(
        escuta._e_o_enunciado("eu ainda trabalho na empresa sim", [perguntas["desligamento"]])
        is None,
        "resposta que repete as palavras da pergunta não é confundida com ela",
    )

    # O trecho que traz a pergunta E o começo da resposta vai para o modelo:
    # separar as duas é o que ele sabe fazer, e é onde a resposta está.
    misto = f"{tempo_casa.texto} eu trabalho lá faz uns oito anos, entrei em 2017"
    falhas += not checar(
        escuta._e_o_enunciado(misto, [tempo_casa]) is None,
        "pergunta seguida da resposta no mesmo trecho não é descartada",
    )
    return falhas


def cenario_sem_chave() -> int:
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
        ("preenchimento e lembretes", cenario_preenchimento),
        ("fala NÃO vira número de documento", cenario_recusa_documentos),
        ("nome e CPF são digitados, nunca ouvidos", cenario_nome_e_cpf_sao_digitados),
        ("alucinação do modelo", cenario_alucinacao),
        ("módulos fechados pelo rastreio", cenario_modulos_fechados),
        ("trecho curto demais", cenario_trecho_curto),
        ("sim/não curto", cenario_sim_nao_curto),
        ("a pergunta da tela chega ao modelo", cenario_pergunta_da_tela),
        ("completar o que já foi respondido", cenario_complemento),
        ("a pergunta lida não é resposta", cenario_enunciado_lido),
        ("sem chave", cenario_sem_chave),
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


def test_escuta_completa() -> None:
    """O pytest executa o mesmo runner que também pode ser chamado pelo terminal."""
    assert main_teste() == 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
