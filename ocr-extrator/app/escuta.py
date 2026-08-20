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

A PERGUNTA DA TELA, E O QUE ELA CONSERTA

O roteiro é feito de perguntas fechadas, e a resposta delas é "sim", "não", "8
vezes". Sozinha, uma resposta dessas não diz do que trata: quem diz é a pergunta
que acabou de ser feita. Ela chega em `pergunta_atual` e vai para o modelo em
seção própria — antes disto, ia só para `_binaria_curta`, e o modelo recebia
"oito vezes" no meio de dezoito perguntas para adivinhar de qual era.

Pior: a janela de perguntas cortava nas 18 primeiras EM ABERTO, e pergunta
pulada não se responde nem sai da lista. Meia hora de entrevista depois, as 18
primeiras abertas eram 18 pendências velhas e a pergunta da tela nem ia no
prompt. É o "depois de um tempo o agente fica ruim" que o escritório relatou —
não era o modelo piorando, era a janela deslizando para trás. Ver `_janela`.

COMPLETAR O QUE JÁ FOI RESPONDIDO

Uma pergunta saía da lista de abertas no instante em que o campo ganhava
qualquer valor. Só que a conversa não é linear: "quantas vezes e em que anos?"
recebe "oito vezes" agora e os anos dois minutos depois, quando o cliente volta
ao assunto. O dado chegava e não tinha onde cair.

Então as já respondidas voltam ao prompt — poucas, as mais próximas da pergunta
da tela — oferecidas para ACRÉSCIMO. O que o modelo devolve em `complementos` é
só o que faltava, e a tela soma ao que está no campo. Reescrever resposta é
outra coisa, e continua sendo de quem conduz: contradição vira lembrete, não
complemento. Ver `_completaveis` e `_acrescimo`.

QUEM ESTÁ FALANDO, E POR QUE O TRECHO SOZINHO NÃO DIZ

O microfone é da sala e a transcrição não separa vozes. Pior que isso: o trecho
fecha quando o texto para de mudar, ou seja, na PAUSA — e a primeira pausa de
toda pergunta é a do entrevistador terminando de fazê-la, antes de o cliente
responder. O que chegava aqui, então, era a pergunta sozinha, e o campo se
preenchia com ela: o entrevistador perguntava, parava, e a resposta aparecia na
tela sem ninguém ter respondido.

Separar vozes é problema de outra ordem (diarização, outro modelo, mais
latência). O que resolve este caso é uma particularidade do atendimento: o
entrevistador LÊ o roteiro, e o enunciado que ele lê é o mesmo texto que este
módulo tem em mãos. Trecho que é essencialmente o enunciado não vai ao modelo e
não preenche nada — ver `_e_o_enunciado`. Trecho que tem a pergunta E o começo
da resposta vai, porque separar as duas é justamente o que o modelo sabe fazer.

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
import unicodedata
from typing import Any

import httpx

from . import roteiros

log = logging.getLogger("escuta")

#: A entrevista está acontecendo: o entrevistador espera o painel se mexer entre
#: uma frase e a seguinte. Passar disto, o trecho já não é mais o assunto.
TEMPO_MODELO_S = 20.0

#: Piso para chamar o modelo. Era 25, e o custo estava do lado errado.
#:
#: Vinte e cinco caracteres derrubavam a resposta curta que não é sim/não —
#: "motorizado", "cinco anos", "no ombro direito". Elas nunca chegavam ao modelo
#: e desapareciam sem deixar rastro: nem preenchiam, nem viravam lembrete, nem
#: apareciam em log. O entrevistado respondia, a tela não mudava, e ele repetia.
#:
#: Trocar por 3 assume o custo de chamar o modelo em cima de ruído — decisão
#: tomada com o escritório, sabendo o que ela significa: mais chamadas, e o
#: preço delas. Vale porque o outro lado é perder resposta dada, e resposta
#: perdida ninguém percebe.
#:
#: Não é zero: com um ou dois caracteres não há o que interpretar, e a chamada
#: seria puro gasto. "sim"/"não" explícitos continuam resolvidos antes disto,
#: sem ida ao modelo (ver `_binaria_curta`), então o caso mais comum segue barato.
MINIMO_CARACTERES = 3

#: Teto de perguntas mandadas por vez. Um roteiro de 86 perguntas com tudo em
#: aberto encheria o prompt de coisa que não tem chance de ser respondida agora.
MAXIMO_PERGUNTAS = 18

#: Quantas vagas da janela ficam com as perguntas que a condução deixou para
#: trás — as "deixadas para depois", que o cliente às vezes responde sozinho lá
#: na frente. O resto da janela é da pergunta da tela em diante.
#:
#: A divisão existe porque "as primeiras abertas são as certas" deixou de ser
#: verdade depois de um tempo de entrevista. Pergunta pulada não se responde e
#: não sai da lista: passada meia hora, as 18 primeiras em aberto são 18
#: pendências velhas, e a pergunta que está NA TELA não vai mais no prompt. O
#: modelo então recebia a resposta do cliente sem a pergunta que ela responde —
#: e ou chutava outra, ou não preenchia nada. É o "depois de um tempo o agente
#: fica ruim": não é o modelo piorando, é a janela deslizando para trás.
VAGAS_ATRASADAS = 6

#: Toda pergunta narrativa já respondida volta ao prompt. Uma informação dita
#: agora pode alterar um assunto do começo da entrevista; proximidade no roteiro
#: não é evidência de pertinência. O valor é truncado apenas para controlar a
#: latência, mas o campo não deixa de ser oferecido por já conter um relato longo.
MAXIMO_COMPLETAVEIS = 64
TAMANHO_COMPLETAVEL = 400

#: Teto de complementos aceitos por trecho, igual ao que a instrução pede.
MAXIMO_COMPLEMENTOS = 3

#: Quantas palavras próprias um trecho precisa ter para PODER ser julgado
#: enunciado lido. Abaixo disto ele é resposta curta — "sim", "oito vezes",
#: "carteiro motociclista" — e resposta curta é o que a escuta menos pode
#: descartar.
#:
#: Quatro, e não cinco, porque o trecho fecha NO MEIO da pergunta: "ainda
#: trabalha na empresa" chega sem o resto do enunciado. E não três, porque aí
#: entra a resposta que ecoa a pergunta ("ainda trabalho na empresa"), que é
#: resposta de verdade e não pode morrer aqui.
MINIMO_PALAVRAS_ENUNCIADO = 4

#: A partir de quantas letras duas palavras podem casar pelo começo.
#:
#: "desligado" e "desligamento", "trabalha" e "trabalhava" são a mesma palavra
#: para este julgamento — o entrevistador não lê o enunciado conjugado como está
#: escrito. Abaixo de seis letras a exigência é igualdade: "foi" e "fui" mudam
#: quem está falando, e é exatamente o que não se pode confundir.
LETRAS_RADICAL = 6

#: Quanto do trecho precisa vir do texto da pergunta para ele ser a pergunta
#: sendo lida, e não uma resposta.
#:
#: 0,8 e não 1,0 porque o entrevistador não lê igual: troca "o senhor" por
#: "você", gagueja, emenda um "certo?" no fim, e o Whisper erra uma palavra aqui
#: e ali. E não menos que 0,8 porque o cliente responde com as palavras da
#: pergunta ("recebia hora extra sim, todo mês") — isso é resposta, e derrubar
#: resposta seria trocar um defeito por outro pior.
COBERTURA_ENUNCIADO = 0.8

#: Palavras que não distinguem nada: entram igual na pergunta e na resposta, e
#: contá-las faria qualquer frase parecer o enunciado.
#:
#: O tratamento ("o senhor", "doutora") está aqui junto com as preposições, e por
#: um motivo mais forte: ele é do entrevistador, não do roteiro. Contá-lo como
#: palavra que a pergunta NÃO tem empurraria para baixo justamente a cobertura
#: do trecho que mais interessa reconhecer.
VAZIAS = frozenset(
    {
        "a", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos",
        "dr", "dra", "doutor", "doutora", "e", "em", "essa", "esse", "esta",
        "este", "eu", "foi", "ha", "isso", "ja", "la", "lhe", "me", "meu",
        "minha", "na", "nas", "no", "nos", "num", "numa", "o", "os", "ou",
        "para", "pela", "pelo", "por", "que", "se", "sem", "senhor", "senhora",
        "ser", "seu", "sr", "sra", "sua", "tem", "um", "uma", "voce", "voces",
    }
)

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


def _binaria_curta(
    trecho: str, abertas: list[roteiros.Pergunta], pergunta_atual: str = ""
) -> dict[str, Any] | None:
    """Aplica um `sim`/`não` explícito à pergunta que está na vez.

    O frontend e `_perguntas_abertas` seguem a mesma ordem do roteiro, portanto
    a primeira aberta é a pergunta mostrada. Não aceitamos "aham", "acho" ou
    outras formas ambíguas: velocidade não pode virar preenchimento falso.
    """
    palavras = re.findall(r"[a-záàâãéêíóôõúç]+", trecho.casefold())
    if not palavras or not abertas:
        return None

    # Exigir o trecho INTEIRO igual a "sim" deixava de fora a forma como as
    # pessoas respondem de verdade: "sim senhor", "não doutor". Elas caíam aqui,
    # e com menos de 25 caracteres também não chegavam ao modelo — sumiam. O
    # entrevistado repetia "sim, sim, sim" até virar um trecho só de "sim", que é
    # a única forma que passava. Agora o acompanhamento de cortesia é ignorado.
    #
    # `restante` continua fechado de propósito: "aham", "acho que sim" e "mais ou
    # menos" seguem NÃO preenchendo. Velocidade não pode virar resposta falsa num
    # campo que decide se um módulo inteiro do roteiro abre.
    cortesia = {
        "senhor", "senhora", "sr", "sra", "doutor", "doutora", "dr", "dra",
        "moço", "moça", "é", "e",
    }
    afirma = {"sim"}
    nega = {"não", "nao"}
    restante = [p for p in palavras if p not in cortesia]
    if not restante:
        return None
    if all(p in afirma for p in restante):
        valor = "sim"
    elif all(p in nega for p in restante):
        valor = "não"
    else:
        return None

    # A pergunta da VEZ, dita pela tela — não a primeira em aberto.
    #
    # Assumir `abertas[0]` só acerta quando a entrevista corre em ordem. Ela não
    # corre: a condução pula o que o cliente já respondeu adiantado e o
    # entrevistador salta perguntas. Com isso, um "não" dito para "Tem acesso às
    # CATs?" era aplicado a outra pergunta — ou, se essa outra não fosse binária,
    # descartado em silêncio. Foi o que aconteceu.
    pergunta = next((p for p in abertas if p.id == pergunta_atual), None) if pergunta_atual else None
    if pergunta is None:
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


def _e_o_enunciado(
    trecho: str, perguntas: list[roteiros.Pergunta]
) -> roteiros.Pergunta | None:
    """A pergunta que este trecho está apenas LENDO em voz alta, se for uma.

    O microfone é da sala e não sabe quem fala; o trecho fecha quando o texto
    para de mudar, ou seja, na PAUSA — e a primeira pausa de uma pergunta é a
    do entrevistador terminando de fazê-la, antes de o cliente abrir a boca. O
    resultado, relatado do uso real: o entrevistador pergunta, para, e o campo
    se preenche sozinho com a pergunta que ele acabou de ler.

    O que resolve isso por código é uma particularidade do atendimento: o
    entrevistador LÊ o roteiro. O enunciado está escrito na tela e é o mesmo
    texto que este módulo tem em mãos, então dá para reconhecê-lo sem
    adivinhação e sem separar vozes — que é problema de outra ordem.

    O julgamento é do trecho INTEIRO, não de conter pergunta: "o senhor recebia
    hora extra? sim, recebia" tem as duas coisas e vai para o modelo, que sabe
    separá-las. O que morre aqui é o trecho que é SÓ o enunciado.

    O que ele NÃO pega: leitura cortada muito cedo, de três palavras próprias e
    sem ponto de interrogação — "ainda trabalha na empresa". Ali o enunciado e a
    resposta que o ecoa ("ainda trabalho na empresa") são o mesmo punhado de
    palavras, e derrubar resposta é pior que deixar passar. Esse caso vai ao
    modelo, que recebe o enunciado da tela junto e a regra de não preenchê-lo.
    """
    palavras = [p for p in _palavras(trecho) if p and p not in VAZIAS]

    # Pergunta escrita com ponto de interrogação é do entrevistador — o cliente
    # não devolve a pergunta ao ser perguntado. Com esse sinal, a leitura curta
    # ("ainda trabalha na empresa?") também é reconhecível, e é justamente a que
    # o corte no meio produz.
    minimo = 3 if trecho.rstrip().endswith("?") else MINIMO_PALAVRAS_ENUNCIADO
    if len(palavras) < minimo:
        return None

    for pergunta in perguntas:
        # As opções entram porque o entrevistador as lê em voz alta, e é essa
        # leitura que já preencheu campo com a PRIMEIRA opção da lista (ver a
        # regra das opções na INSTRUCAO). A `dica` fica de fora: ela é conduta
        # para a atendente ("se sim, pedir o processo do INSS"), e as palavras
        # dela reaparecem na RESPOSTA do cliente — contá-las mataria resposta.
        escrito = " ".join([pergunta.texto, " ".join(pergunta.opcoes)])
        do_roteiro = [p for p in _palavras(escrito) if p]
        cobertas = sum(1 for p in palavras if _mesma_palavra(p, do_roteiro))
        if cobertas / len(palavras) >= COBERTURA_ENUNCIADO:
            return pergunta
    return None


def _binaria_apos_enunciado(
    trecho: str, pergunta: roteiros.Pergunta | None
) -> dict[str, Any] | None:
    """Captura ``pergunta inteira + sim/não`` no mesmo trecho do Whisper.

    O cliente frequentemente responde antes de o corte de áudio fechar. Nesse
    caso o filtro de enunciado não pode descartar o ``sim`` junto com a leitura
    do advogado. Só aceitamos a última palavra explícita e exigimos que tudo
    antes dela seja reconhecido como o enunciado da pergunta atual.
    """
    if pergunta is None or pergunta.tipo != "sim_nao":
        return None
    palavras = re.findall(r"[a-záàâãéêíóôõúç]+", trecho.casefold())
    cortesias = {"senhor", "senhora", "doutor", "doutora", "dr", "dra"}
    while palavras and palavras[-1] in cortesias:
        palavras.pop()
    if len(palavras) < 2 or palavras[-1] not in {"sim", "não", "nao"}:
        return None
    cauda = set(palavras[-3:])
    if "sim" in cauda and ({"não", "nao"} & cauda):
        # É o advogado lendo "sim ou não", não uma resposta do cliente.
        return None
    resposta = palavras[-1]
    prefixo = " ".join(palavras[:-1])
    if _e_o_enunciado(prefixo, [pergunta]) is None:
        return None
    valor = "não" if resposta in {"não", "nao"} else "sim"
    return {
        "pergunta_id": pergunta.id,
        "pergunta": pergunta.texto,
        "valor": valor,
        "trecho": trecho,
    }


def _mesma_palavra(palavra: str, escritas: list[str]) -> bool:
    """A palavra está no enunciado, contando flexão como a mesma palavra."""
    if palavra in escritas:
        return True
    if len(palavra) < LETRAS_RADICAL:
        return False
    radical = palavra[:LETRAS_RADICAL]
    return any(
        len(outra) >= LETRAS_RADICAL and outra[:LETRAS_RADICAL] == radical
        for outra in escritas
    )


class ErroEscuta(Exception):
    """Falha que o entrevistador precisa ver — sem parar a entrevista."""


# ------------------------------------------------------------------ roteiro


def _respondida(valor: Any) -> bool:
    if isinstance(valor, list):
        return len(valor) > 0
    return bool(str(valor or "").strip())


def _perguntas_abertas(
    roteiro: roteiros.Roteiro, respostas: dict[str, Any], pergunta_atual: str = ""
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
    return _janela(abertas, pergunta_atual)


def _janela(
    abertas: list[roteiros.Pergunta], pergunta_atual: str
) -> list[roteiros.Pergunta]:
    """Quais das abertas cabem no prompt, com a da tela garantida dentro.

    Enquanto tudo cabe, a ordem é a do roteiro e nada muda. Quando não cabe, a
    pergunta que está na tela vem primeiro — ela é a que o cliente está
    respondendo agora, e é a única que não pode faltar — seguida das que vêm
    depois dela, que é para onde a conversa está indo. As deixadas para trás
    ficam com `VAGAS_ATRASADAS` lugares, as mais próximas primeiro: o cliente
    volta a assuntos recentes, não ao que se falou meia hora atrás.
    """
    if len(abertas) <= MAXIMO_PERGUNTAS:
        return abertas

    posicao = next((i for i, p in enumerate(abertas) if p.id == pergunta_atual), None)
    if posicao is None:
        return abertas[:MAXIMO_PERGUNTAS]

    frente = abertas[posicao:][: MAXIMO_PERGUNTAS - VAGAS_ATRASADAS]
    # O que a frente não usou volta para trás: perto do fim do roteiro sobram
    # poucas daqui em diante, e deixar a janela pela metade seria desperdiçar
    # lugar que as pendências antigas aproveitam.
    sobra = MAXIMO_PERGUNTAS - len(frente)
    atrasadas = abertas[:posicao][-sobra:] if sobra > 0 else []
    return frente + atrasadas


#: Tipos cujo campo não se completa: a resposta é UMA, e acrescentar a segunda
#: deixaria as duas no campo ("sim não"). Complemento é para o que se conta em
#: pedaços — quantas vezes, em que anos, em que hospital.
TIPOS_FECHADOS = {"sim_nao", "escolha", "lista", "documentos", "data"}


def _completaveis(
    roteiro: roteiros.Roteiro, respostas: dict[str, Any], pergunta_atual: str
) -> list[tuple[roteiros.Pergunta, str]]:
    """As já respondidas que este trecho ainda pode completar, com o que há nelas.

    Elas saíram da lista de abertas no instante em que ganharam qualquer valor, e
    era ali que a entrevista as perdia: a pergunta é "quantas vezes e em que
    anos?", o cliente responde "oito vezes", o campo enche, e os anos — ditos
    dois minutos depois, quando ele volta ao assunto — não tinham mais onde
    cair. O modelo nem chegava a ver a pergunta.

    Volta pouca coisa, e a mais próxima da pergunta da tela primeiro: quem
    completa completa o que acabou de falar. O que voltar é oferecido para
    ACRÉSCIMO, nunca para reescrita — quem decide trocar uma resposta é quem
    está conduzindo.
    """
    todas = [p for bloco in roteiro.blocos for p in bloco.perguntas]
    posicao = {p.id: indice for indice, p in enumerate(todas)}
    daqui = posicao.get(pergunta_atual, len(todas))

    respondidas: list[roteiros.Pergunta] = []
    for pergunta in todas:
        bruto = respostas.get(pergunta.id)
        if isinstance(bruto, list) or not _respondida(bruto):
            continue
        if pergunta.validacao or pergunta.id in DADOS_DIGITADOS:
            continue
        if pergunta.tipo in TIPOS_FECHADOS or pergunta.opcoes:
            continue
        respondidas.append(pergunta)

    respondidas.sort(key=lambda p: abs(posicao[p.id] - daqui))
    escolhidas = sorted(respondidas[:MAXIMO_COMPLETAVEIS], key=lambda p: posicao[p.id])
    return [(p, _texto(respostas.get(p.id), TAMANHO_COMPLETAVEL)) for p in escolhidas]


def _sem_acento(valor: str) -> str:
    decomposto = unicodedata.normalize("NFKD", valor)
    return "".join(letra for letra in decomposto if not unicodedata.combining(letra))


def _palavras(valor: str) -> list[str]:
    """Uma entrada por palavra do texto original — a contagem tem de bater.

    É por ela que se recorta o acréscimo do texto como o cliente disse, com
    acento e maiúscula; comparar é que se faz sem.
    """
    return [p.strip(".,;:!?()-").casefold() for p in _sem_acento(valor).split()]


def _chave(valor: str) -> str:
    return " ".join(p for p in _palavras(valor) if p)


def _acrescimo(valor: str, atual: str) -> str:
    """O que o complemento traz de novo para um campo que já tem resposta.

    Devolve vazio quando não traz nada — e isso é o guardrail, não um detalhe: a
    tela ACRESCENTA o que vem daqui ao que já está no campo (`Roteiro.tsx`), de
    modo que um complemento repetido não se perde, ele duplica na cara do
    advogado e sai duplicado na peça.
    """
    novo, velho = _chave(valor), _chave(atual)
    if not novo:
        return ""
    if not velho:
        return valor.strip()
    if novo == velho or novo in velho:
        return ""

    palavras_novo, palavras_velho = _palavras(valor), _palavras(atual)
    if palavras_novo[: len(palavras_velho)] == palavras_velho:
        # O modelo devolveu a resposta inteira em vez de só o que faltava. O
        # campo já tem a primeira parte; o acréscimo é o que sobra dela.
        return " ".join(valor.split()[len(palavras_velho) :]).strip()
    return valor.strip()


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
- Só preencha o que foi DITO. Não deduza, não complete, não invente detalhe que
  não foi falado. Se a pessoa disse "faz uns três anos", o valor é "uns três
  anos" — não vire uma data exata, que ela não deu.
- EXTRAIR não é inventar. Você pode e deve tirar da fala só a parte que responde
  a pergunta, descartando repetição, muleta e o eco do enunciado. Isto é o que se
  espera:

    pergunta "Há quanto tempo trabalha nos Correios?"
    fala     "ah, 5 anos nos Correios, 5 anos"
    valor    "5 anos"                          <- certo
    valor    "5 anos nos Correios 5 anos"      <- ERRADO, é a fala copiada

  O campo é lido depois por quem não ouviu a conversa, e vai para peça
  processual. Fala copiada com repetição faz o documento parecer rascunho.
- A fala é de transcrição automática: pode vir truncada ou com palavra trocada.
  Na dúvida sobre o que foi dito, NÃO preencha — registre em `lembretes`.
- O microfone capta a SALA: a voz do entrevistador entra junto com a do cliente.
  Você recebe as duas misturadas, sem etiqueta de quem falou. Preencha SÓ com o
  que o cliente respondeu — nunca com o que o entrevistador perguntou.

  É pergunta do entrevistador quando o trecho:
    - enumera as opções ("você é carteiro pedestre, motorizado, ciclista?");
    - termina em interrogação ou repete o enunciado do roteiro;
    - usa segunda pessoa ("o senhor sofreu...", "você tem...").

  É resposta do cliente quando usa primeira pessoa ("eu sou...", "fiquei...",
  "faz uns cinco anos") ou responde direto ("sim", "motorizado").

  Isto já causou erro real: o entrevistador leu "carteiro pedestre, motorizado,
  motociclista, ciclista" e o campo foi preenchido com "Carteiro pedestre" — a
  PRIMEIRA da lista lida, não o que o cliente disse. Um trecho que lista opções
  não preenche nada, NUNCA. Espere a resposta.
- Um trecho pode responder várias perguntas de uma vez, ou nenhuma. Nenhuma é
  resposta legítima e comum: boa parte da conversa é saudação e rapport.

A PERGUNTA DA VEZ

Junto com a lista você recebe PERGUNTA NA TELA: é a que o entrevistador acabou
de fazer em voz alta. Ela mudou tudo o que vem a seguir.

- Resposta CURTA pertence a ela. "sim", "não", "8 vezes", "em 2022", "no ombro
  direito", "de moto" não dizem sozinhas do que tratam — quem diz é a pergunta
  na tela. Preencha ELA. Não espalhe a resposta curta pelas outras perguntas da
  lista e não a descarte por ser curta: o roteiro é feito de perguntas fechadas,
  e resposta curta é a resposta normal delas, não uma resposta pela metade.
- Resposta LONGA é outra coisa: ela responde a pergunta da tela e pode responder
  mais algumas da lista de uma vez. Aproveite todas, cada uma com o seu trecho.
- Se a fala claramente não responde a pergunta da tela — o cliente mudou de
  assunto, ou o trecho é só o entrevistador falando — não force. Preencha o que
  ela responder de verdade, ou nada.
- LER a pergunta não é RESPONDER a pergunta. O trecho chega quando alguém faz
  uma pausa, e a primeira pausa de toda pergunta é a do entrevistador acabando
  de fazê-la — o cliente ainda nem abriu a boca. Trecho que repete o enunciado
  que está na tela, com outras palavras ou com as mesmas, não preenche NADA.
  Espere o trecho seguinte, que é a resposta.

    tela   "O senhor recebia hora extra?"
    trecho "o senhor recebia hora extra, chegava a fazer hora extra?"
    valor  (não preencher — é a pergunta sendo feita, ninguém respondeu ainda)
- `sim_nao` sempre grava "sim" ou "não" no `valor`, e aceita as formas em que as
  pessoas dizem isso quando estão respondendo a pergunta da tela: "isso", "isso
  mesmo", "exatamente", "com certeza", "sempre" são SIM; "nunca", "jamais", "que
  nada" são NÃO. Continuam ambíguas, e não preenchem nada: "aham", "acho que
  sim", "acho que não", "mais ou menos", "talvez", "não sei" — essas viram
  lembrete, porque um campo desses decide se um módulo inteiro do roteiro abre.
- Pergunta com OPÇÕES: o valor tem que ser UMA das opções listadas, escrita como
  ela aparece. Se a fala casa com VÁRIAS, ela não escolheu — NÃO preencha, e mande
  um lembrete pedindo para separar. Escolher a primeira que serve é o pior erro
  possível aqui: a tela mostraria um campo preenchido, e ninguém voltaria a
  perguntar.

    opções  Atendente / OTT / Carteiro motorizado / Carteiro pedestre /
            Carteiro motociclista / Carteiro ciclista / Outra
    fala    "eu sou carteiro"
    valor   (não preencher — "carteiro" serve para quatro opções)
    lembrete "O senhor é carteiro motorizado, pedestre, motociclista ou ciclista?"

  Se a fala identificar uma só ("carteiro de moto", "entrego de bicicleta"),
  preencha normalmente.
- NUNCA preencha CPF, RG, datas de nascimento ou qualquer número de documento a
  partir da fala, mesmo que apareça claramente. Esses campos são digitados por
  outra equipe.
- `valor` é a RESPOSTA à pergunta, não a transcrição da fala. Use as palavras do
  cliente, mas só as que respondem: sem repetir o enunciado, sem "ah", "então",
  "né", e sem dizer duas vezes a mesma coisa. Pergunta de relato aceita frase
  inteira; pergunta de dado objetivo quer o dado, curto.
- `trecho` é a citação literal do que sustenta o preenchimento, para o
  entrevistador conferir de relance.
- `lembretes` é o que ficou pela metade: o cliente tocou no assunto mas faltou
  data, nome, número ou documento. Escreva como PERGUNTA pronta para ser lida em
  voz alta, na segunda pessoa.
- No máximo 4 lembretes. Menos é melhor: isto é lido durante a conversa.

COMPLETAR O QUE JÁ FOI RESPONDIDO

Você também recebe JÁ RESPONDIDAS: perguntas com o que já está escrito no campo.
Numa conversa o cliente volta ao assunto, e quando volta traz o que faltou — a
pergunta era "quantas vezes e em que anos?", no campo está "8 vezes", e agora ele
diz "foi em 2022, 2023 e 2024". A data pertence àquele campo, não a este trecho.

- Trecho que traz dado NOVO para uma dessas perguntas vai em `complementos`.
- Compare o trecho com TODAS as JÁ RESPONDIDAS, independentemente da pergunta
  que está na tela. Uma única fala pode complementar mais de um campo antigo.
- Em `valor` vai SÓ O QUE FALTAVA, nunca a resposta inteira: o que você mandar é
  ACRESCENTADO ao que já está no campo. No exemplo o valor é "2022, 2023 e 2024";
  mandar "8 vezes em 2022, 2023 e 2024" escreveria "8 vezes" duas vezes no campo.
- Nada novo, nenhum complemento. Não repita o que o campo já diz nem reescreva
  com outras palavras o que está lá.
- Completar não é corrigir. Se o cliente contradiz o campo ("na verdade foram
  seis, não oito"), NÃO complemente: mande um lembrete avisando que a resposta
  mudou. Quem conduz decide o que fica — acrescentar deixaria as duas no campo.
- No máximo 3 complementos por trecho.

Responda APENAS JSON:
{"preenchidas":[{"pergunta_id":"...","valor":"...","trecho":"..."}],
 "complementos":[{"pergunta_id":"...","valor":"...","trecho":"..."}],
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
    bruto: dict[str, Any],
    abertas: list[roteiros.Pergunta],
    completaveis: list[tuple[roteiros.Pergunta, str]] | None = None,
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

    preenchidas += _complementos(bruto, completaveis or [])

    lembretes = list(extras)
    for item in bruto.get("lembretes") or []:
        if isinstance(item, dict):
            pergunte, pid = _texto(item.get("pergunte"), 240), str(item.get("pergunta_id", ""))
        else:
            pergunte, pid = _texto(item, 240), ""
        if pergunte:
            lembretes.append({"pergunta_id": pid if pid in por_id else "", "pergunte": pergunte})

    return preenchidas, sugestoes, lembretes[:4]


def _complementos(
    bruto: dict[str, Any], completaveis: list[tuple[roteiros.Pergunta, str]]
) -> list[dict[str, Any]]:
    """O que o trecho acrescentou a campos que já tinham resposta.

    Sai no mesmo formato de `preenchidas` porque é o que a tela faz com os dois:
    acrescenta ao campo. A marca `complemento` existe para o painel poder dizer
    "completou" em vez de "respondeu" — quem respondeu foi o cliente, dois
    minutos atrás.
    """
    atual = {pergunta.id: valor for pergunta, valor in completaveis}
    por_id = {pergunta.id: pergunta for pergunta, _ in completaveis}

    saida: list[dict[str, Any]] = []
    for item in bruto.get("complementos") or []:
        if len(saida) >= MAXIMO_COMPLEMENTOS:
            break
        if not isinstance(item, dict):
            continue
        pergunta = por_id.get(str(item.get("pergunta_id", "")))
        if pergunta is None:
            # Id que não estava na lista de completáveis: ou é alucinação, ou é
            # uma pergunta que este módulo decidiu que não se completa.
            continue
        acrescimo = _acrescimo(_texto(item.get("valor")), atual[pergunta.id])
        if not acrescimo:
            log.info("Complemento sem dado novo em %r; descartado.", pergunta.id)
            continue
        saida.append(
            {
                "pergunta_id": pergunta.id,
                "pergunta": pergunta.texto,
                "valor": acrescimo,
                "trecho": _texto(item.get("trecho"), 240),
                "complemento": True,
            }
        )
    return saida


def _abertas_pelo_rastreio(
    roteiro: roteiros.Roteiro,
    respostas: dict[str, Any],
    preenchidas: list[dict[str, Any]],
    ja_oferecidas: list[roteiros.Pergunta],
    pergunta_atual: str = "",
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
    novas = _perguntas_abertas(roteiro, depois, pergunta_atual)
    return [p for p in novas if p.id not in conhecidas]


# -------------------------------------------------------------------- ação


def escutar(
    trecho: str,
    respostas: dict[str, Any],
    codigo_roteiro: str = "empregado_publico",
    pergunta_atual: str = "",
) -> dict[str, Any]:
    """O que este trecho de fala respondeu, e o que ainda falta perguntar.

    `respostas` é o estado atual da entrevista — entra para o modelo não repetir
    o que já está preenchido, e para o rastreio decidir quais módulos existem.
    """
    trecho = _texto(trecho, 4000)
    roteiro = roteiros.obter(codigo_roteiro)
    if roteiro is None:
        raise ErroEscuta(f"Roteiro {codigo_roteiro!r} não existe.")

    abertas = _perguntas_abertas(roteiro, respostas, pergunta_atual)
    faltando = [
        {"pergunta_id": p.id, "pergunta": p.texto, "obrigatoria": p.obrigatoria}
        for p in abertas
    ]

    # A da tela pode já ter resposta — o entrevistador relê para confirmar — e aí
    # ela não está entre as abertas. Continua sendo a que ele está lendo.
    atual_na_tela = next(
        (
            p
            for bloco in roteiro.blocos
            for p in bloco.perguntas
            if p.id == pergunta_atual
        ),
        None,
    )

    # Quando o cliente responde antes de o mesmo corte de áudio fechar, preserve
    # o sim/não final antes de testar se o restante era apenas o enunciado.
    binaria_mista = _binaria_apos_enunciado(trecho, atual_na_tela)
    if binaria_mista is not None:
        return {
            "preenchidas": [binaria_mista],
            "sugestoes": [],
            "lembretes": [],
            "faltando": [
                f for f in faltando
                if f["pergunta_id"] != binaria_mista["pergunta_id"]
            ],
            "analisado": True,
        }

    # A pergunta sendo LIDA não responde nada — e é o que mais chega aqui, porque
    # o trecho fecha na pausa e a primeira pausa é a do entrevistador terminando
    # de perguntar. Sai antes do modelo: não é economia, é que o modelo, vendo a
    # pergunta da tela e um trecho que fala dela, tende a preencher.
    lida = _e_o_enunciado(trecho, ([atual_na_tela] if atual_na_tela else []) + abertas)
    if lida is not None:
        log.info("Trecho é o enunciado de %r sendo lido; nada preenchido.", lida.id)
        return {
            "preenchidas": [],
            "sugestoes": [],
            "lembretes": [],
            "faltando": faltando,
            "analisado": False,
            "enunciado": lida.id,
        }

    binaria = _binaria_curta(trecho, abertas, pergunta_atual)
    if binaria is not None:
        return {
            "preenchidas": [binaria],
            "sugestoes": [],
            "lembretes": [],
            "faltando": [f for f in faltando if f["pergunta_id"] != binaria["pergunta_id"]],
            "analisado": True,
        }

    completaveis = _completaveis(roteiro, respostas, pergunta_atual)

    # Sem trecho útil, ainda assim devolve o que falta: é o painel abrindo no
    # começo da entrevista, antes de alguém falar qualquer coisa.
    #
    # `completaveis` entra na condição porque no fim da entrevista não há mais
    # pergunta aberta e o cliente ainda está falando — é justamente quando ele
    # volta e completa o que contou pela metade.
    if len(trecho) < MINIMO_CARACTERES or not (abertas or completaveis):
        return {
            "preenchidas": [],
            "sugestoes": [],
            "lembretes": [],
            "faltando": faltando,
            "analisado": False,
        }

    # A pergunta da tela vai PRIMEIRO e sozinha na sua seção. Ela é o assunto do
    # trecho — sem ela, "sim" e "oito vezes" chegam ao modelo como frases soltas
    # no meio de dezoito perguntas, e ele tem de adivinhar de qual são.
    partes = []
    if atual_na_tela is not None and any(p.id == pergunta_atual for p in abertas):
        partes.append("PERGUNTA NA TELA AGORA:\n" + _descrever(atual_na_tela))
    if abertas:
        partes.append(
            "PERGUNTAS EM ABERTO:\n" + "\n".join(f"- {_descrever(p)}" for p in abertas)
        )
    partes.append(f"TRECHO RECÉM-FALADO:\n{trecho}")
    if completaveis:
        partes.append(
            "JÁ RESPONDIDAS (complete só com dado novo):\n"
            + "\n".join(
                f'- {p.id}: {p.texto} — no campo: "{valor}"' for p, valor in completaveis
            )
        )

    preenchidas, sugestoes, lembretes = _normalizar(
        _chamar_modelo("\n\n".join(partes)), abertas, completaveis
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
    novas = _abertas_pelo_rastreio(
        roteiro, respostas, preenchidas, abertas, pergunta_atual
    )
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
