"""O chat do agente fora do caso — para onde vai cada pergunta, e o que fica sem resposta.

A tela do agente geral aceita qualquer pergunta, mas o que existe do outro lado é um chat
**por caso**: `POST /api/v1/cases/{ref}/chat`. Não há, hoje, rota que responda sobre o
acervo inteiro. Este módulo é onde essa diferença é decidida — de forma determinística,
antes de qualquer modelo entrar na história — e onde a recusa honesta é escrita.

Três destinos, nesta ordem de precedência:

- **`CASO`** — a pergunta cita um caso do acervo (ou a conversa já está sobre um). Vai
  para o chat que existe, com o guardrail de lastro do agente valendo normalmente;
- **`SISTEMA`** — a pergunta é sobre como o produto funciona ("o que é um fato
  alegado?"). Responde o glossário abaixo: texto fixo, escrito e revisável aqui dentro,
  nunca uma consulta ao acervo. É por isso que a resposta vai marcada com o selo "Sobre o
  sistema" na tela — explicação de produto e dado de caso não podem se parecer;
- **`ACERVO`** — a pergunta atravessa vários casos ("quais casos estão parados esperando
  documento?"). **Ninguém responde isso ainda.** A tela diz que não sabe, e
  `docs/AGENTE-GERAL.md` descreve a rota que faltaria. Responder por aproximação seria o
  pior resultado possível num sistema construído inteiro sobre a diferença entre o que
  foi apurado e o que é plausível.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ACERVO",
    "ANALISE",
    "CASO",
    "ESCOLHA",
    "GLOSSARIO",
    "SISTEMA",
    "Decisao",
    "Verbete",
    "casos_citados",
    "rotear",
    "texto_do_acervo",
    "verbete_para",
]

CASO = "CASO"
SISTEMA = "SISTEMA"
ACERVO = "ACERVO"
ESCOLHA = "ESCOLHA"

#: Resposta do **analista**: leitura do acervo construída a partir de consultas.
#:
#: Separada de `CASO` porque a origem é outra e a tela precisa dizer qual é. `CASO` vem
#: do agente jurídico, com o estado daquele caso; `ANALISE` é o que este sistema mediu
#: agora, ferramenta por ferramenta — e a resposta carrega quais foram.
ANALISE = "ANALISE"


# ------------------------------------------------------------------ normalização


def normalizar(texto: object) -> str:
    """Minúsculas, sem acento, espaços colapsados.

    O acervo mistura grafias — "José", "Jose", "JOSÉ" — e a pergunta vem digitada com
    pressa. Comparar sem isto faria a detecção de caso falhar justamente onde ela
    importa: quando o advogado escreve o nome do cliente do jeito que lembra.
    """
    bruto = unicodedata.normalize("NFKD", str(texto or ""))
    sem_acento = "".join(c for c in bruto if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def _contem_expressao(texto_normalizado: str, expressao: str) -> bool:
    """Casa a expressão inteira, respeitando limite de palavra.

    Sem o limite, "provado" casaria dentro de "comprovado" e o glossário responderia
    sobre fato provado a quem perguntou de comprovante de residência.
    """
    return re.search(rf"(?<!\w){re.escape(expressao)}(?!\w)", texto_normalizado) is not None


# --------------------------------------------------------------------- glossário


@dataclass(frozen=True)
class Verbete:
    """Uma explicação do produto, escrita à mão e conferível.

    `termos` são as expressões que fazem a pergunta cair aqui. Elas são deliberadamente
    específicas: é melhor não reconhecer a pergunta — e dizer isso — do que reconhecer a
    errada e explicar outra coisa com ar de certeza.
    """

    codigo: str
    titulo: str
    termos: tuple[str, ...]
    texto: str


#: A ordem importa: empate no peso dos termos casados resolve pelo primeiro da lista.
GLOSSARIO: tuple[Verbete, ...] = (
    Verbete(
        codigo="fato-alegado",
        titulo="Fato alegado e fato provado",
        termos=(
            "fato alegado",
            "fatos alegados",
            "alegado",
            "alegados",
            "fato provado",
            "fatos provados",
            "provado",
        ),
        texto=(
            "Fato ALEGADO é o que o cliente contou e nenhum documento confirmou ainda — "
            "tudo o que sai da entrevista nasce assim. Fato PROVADO é o que veio de um "
            "documento lido, com a página de origem registrada.\n\n"
            "A distinção não é decorativa: a petição não pode afirmar como provado o que "
            "está só alegado, e o agente recusa a resposta que troca um pelo outro. Na "
            "tela, cada afirmação vem com o selo da sua natureza — Provado, Alegado, "
            "Hipótese, Inferência."
        ),
    ),
    Verbete(
        codigo="pendencia",
        titulo="Pendência bloqueante e pendência recomendável",
        termos=(
            "pendencia",
            "pendencias",
            "bloqueante",
            "bloqueantes",
            "recomendavel",
            "lacuna",
            "lacunas",
        ),
        texto=(
            "Toda pendência apontada pelo agente tem uma de duas gravidades.\n\n"
            "BLOQUEANTE: falta algo indispensável, e a petição não é gerada enquanto isso "
            "não for resolvido.\n"
            "RECOMENDÁVEL: a peça sai, mas com a lacuna apontada no texto — quem assina "
            "sabe o que está faltando."
        ),
    ),
    Verbete(
        codigo="proposta",
        titulo="Por que o agente propõe em vez de alterar",
        termos=("proposta", "propostas", "aplicar alteracao", "confirmar alteracao"),
        texto=(
            "Nenhuma conversa altera o caso sozinha. Quando o agente conclui que algo "
            "deveria mudar, ele devolve uma PROPOSTA com o texto de hoje e o texto que "
            "passaria a valer, e nada acontece até alguém clicar em aplicar.\n\n"
            "Se o caso mudar entre a proposta e o clique, ela é recusada como obsoleta — "
            "e o caminho é pedir a proposta de novo, sobre o estado novo."
        ),
    ),
    Verbete(
        codigo="estrategia",
        titulo="Estratégia, hipótese e a aprovação humana",
        termos=("estrategia", "hipotese", "hipoteses", "tese", "teses"),
        texto=(
            "A estratégia reúne as teses do caso, cada uma amarrada aos fatos que a "
            "sustentam E aos que a enfraquecem — estratégia que só mostra o que ajuda é "
            "propaganda, não análise.\n\n"
            "Tese sem fato que a ancore é descartada pelo próprio sistema, com o motivo "
            "registrado. E a estratégia só passa a alimentar os pedidos da petição depois "
            "de aprovada por uma pessoa."
        ),
    ),
    Verbete(
        codigo="peticao",
        titulo="Quando a petição pode ser gerada",
        termos=("peticao", "peticoes", "minuta", "peca", "pecas"),
        texto=(
            "Antes de escrever, o sistema confere se o caso sustenta a peça: fato "
            "essencial que continua só alegado, documento obrigatório que não chegou e "
            "pendência bloqueante em aberto reprovam a geração, com a lista do que "
            "falta.\n\n"
            "Gerada a minuta, um revisor confere cada citação contra o caso. Achado grave "
            "retém a peça como rascunho — ela não avança sem revisão humana."
        ),
    ),
    Verbete(
        codigo="contradicao",
        titulo="Contradição entre fatos",
        termos=("contradicao", "contradicoes", "divergencia", "divergencias"),
        texto=(
            "Quando dois fatos do mesmo caso não podem ser verdadeiros ao mesmo tempo, o "
            "sistema registra a divergência e mostra o caminho de conferência — nunca "
            "escolhe um vencedor.\n\n"
            "«Ambos permanecem como tese» é resposta legítima e frequente: no vínculo não "
            "registrado, a diferença entre o que o cliente conta e o que a CTPS diz é a "
            "própria causa."
        ),
    ),
    Verbete(
        codigo="precedente",
        titulo="Jurisprudência e precedentes",
        termos=(
            "precedente",
            "precedentes",
            "jurisprudencia",
            "julgado",
            "julgados",
            "acordao",
            "acordaos",
        ),
        texto=(
            "A pesquisa procura decisões do foro em que o caso corre, sobre as questões "
            "jurídicas que ele levanta, e classifica cada uma como favorável, contrária ou "
            "não aplicável — com o trecho citado à vista.\n\n"
            "Quando a base consultada está incompleta, isso aparece junto do resultado: "
            "ausência de precedente sem essa ressalva pareceria conclusão, e é só falta de "
            "dado."
        ),
    ),
    Verbete(
        codigo="entrevista",
        titulo="Entrevista guiada",
        termos=("entrevista guiada", "entrevista", "atendimento guiado", "roteiro"),
        texto=(
            "A entrevista conduz o atendimento por um roteiro, com a conversa sendo "
            "transcrita, e o caso nasce dali já com o tipo de ação escolhido.\n\n"
            "O que o cliente relata vira fato ALEGADO, com a fala de origem guardada — "
            "nunca fato provado, por mais convincente que tenha sido o relato."
        ),
    ),
    Verbete(
        codigo="checklist",
        titulo="Checklist de documentos",
        termos=(
            "checklist",
            "documento obrigatorio",
            "documentos obrigatorios",
            "lista de documentos",
        ),
        texto=(
            "Cada tipo de ação tem a sua lista de documentos. O checklist mostra o que já "
            "chegou, o que falta e o que chegou mas precisa de conferência — documento "
            "ilegível não conta como entregue.\n\n"
            "O cliente envia pelo portal, e a leitura automática confere se o arquivo é "
            "mesmo o documento pedido."
        ),
    ),
    Verbete(
        codigo="carteira",
        titulo="Carteira, panorama e painel do caso",
        termos=("carteira", "panorama", "painel analitico"),
        texto=(
            "São três leituras diferentes, de propósito:\n\n"
            "CARTEIRA — o que fazer agora, com os casos ordenados por risco de travar;\n"
            "PANORAMA — como o escritório vai: quantos casos, em que estágio, o que está "
            "parado;\n"
            "PAINEL DO CASO — quanto tempo cada etapa levou neste caso e como ele se "
            "compara aos anteriores."
        ),
    ),
    Verbete(
        codigo="portal",
        titulo="Portal do cliente",
        termos=("portal do cliente", "portal", "link do cliente"),
        texto=(
            "Cada caso tem um endereço próprio para o cliente enviar os documentos, com "
            "senha própria. Ele vê só a lista do que falta e o que já foi recebido — nada "
            "de fato, tese ou peça.\n\n"
            "A tela é desenhada para celular e para quem tem pouca prática com telas: uma "
            "coluna, alvos grandes, texto maior."
        ),
    ),
    Verbete(
        codigo="jurimetria",
        titulo="Jurimetria",
        termos=("jurimetria", "indicador de desfecho", "indicadores de desfecho"),
        texto=(
            "É a leitura que olha para fora do escritório: como o foro decidiu casos "
            "comparáveis, e onde este cai dentro disso.\n\n"
            "Amostra pequena vem marcada como pequena. Um percentual sobre sete casos não "
            "é tendência, e apresentá-lo como se fosse seria o tipo de falsa precisão que "
            "este sistema existe para evitar."
        ),
    ),
)


def verbete_para(pergunta: str) -> Verbete | None:
    """O verbete que a pergunta pede, ou nada.

    Vence quem casar os termos mais específicos; empate resolve pela ordem do glossário.
    Zero termos casados devolve `None` — e a pergunta segue para o destino seguinte, que
    dirá honestamente que não sabe. Chutar o verbete mais próximo daria uma explicação
    certa sobre o assunto errado, que é pior do que não responder.
    """
    alvo = normalizar(pergunta)
    melhor: Verbete | None = None
    melhor_peso = 0

    for verbete in GLOSSARIO:
        casados = [termo for termo in verbete.termos if _contem_expressao(alvo, termo)]
        if not casados:
            continue
        # Expressão de duas palavras pesa mais que a de uma: "fato alegado" deve vencer
        # "alegado", que aparece em muita frase solta.
        peso = sum(len(termo.split()) * 10 + len(termo) for termo in casados)
        if peso > melhor_peso:
            melhor, melhor_peso = verbete, peso
    return melhor


# ------------------------------------------------------------- detecção de caso


#: Pedaços de nome que não identificam ninguém.
_LIGACOES = frozenset({"de", "da", "do", "das", "dos", "e"})


def _tokens_do_nome(nome: str) -> list[str]:
    """Os pedaços do nome que valem como identificação.

    Preposição fora, e pedaço de uma ou duas letras fora: "J. R. S." não identifica
    ninguém, e "de" identificaria metade do acervo.
    """
    return [
        pedaco
        for pedaco in normalizar(nome).split()
        if len(pedaco) > 2 and pedaco not in _LIGACOES
    ]


def casos_citados(pergunta: str, casos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Os casos que a pergunta nomeia — pelo identificador ou pelo nome do cliente.

    Conservador de propósito: exige dois pedaços seguidos do nome ("Maria Silva" para
    "Maria Silva Santos") ou o identificador do caso. Um primeiro nome sozinho não basta —
    "o caso da Maria", com três Marias no acervo, escolheria uma delas por sorteio e a
    resposta viria sobre o caso errado com toda a confiança do mundo.

    A exceção é o cliente cadastrado com um nome só. Acontece bastante ("Guilherme",
    "maria"), e aí o token sozinho é tudo o que existe daquele nome.

    **O casamento mais específico manda.** No acervo real convivem "Guilherme Nunes" e
    "Guilherme": sem esta regra, perguntar por "GUILHERME NUNES" traria os dois primeiros
    e mais três homônimos de primeiro nome, e a lista de escolha viraria ruído em cima da
    pergunta que já tinha sido específica.
    """
    alvo = normalizar(pergunta)
    if not alvo:
        return []

    #: (caso, força) — quantos pedaços do nome a pergunta acertou. O identificador vale
    #: mais que qualquer nome: ele é único, e quem o digitou não estava adivinhando.
    encontrados: list[tuple[dict[str, Any], int]] = []
    for caso in casos:
        identificador = str(caso.get("id") or "")
        if identificador and identificador.lower() in alvo:
            encontrados.append((caso, 3))
            continue

        tokens = _tokens_do_nome(str(caso.get("cliente") or ""))
        if not tokens:
            continue
        if len(tokens) == 1:
            if _contem_expressao(alvo, tokens[0]):
                encontrados.append((caso, 1))
            continue

        pares = [f"{tokens[i]} {tokens[i + 1]}" for i in range(len(tokens) - 1)]
        if any(_contem_expressao(alvo, par) for par in pares):
            encontrados.append((caso, 2))

    if not encontrados:
        return []
    maior = max(forca for _, forca in encontrados)
    return [caso for caso, forca in encontrados if forca == maior]


# --------------------------------------------------------------------- decisão


@dataclass
class Decisao:
    """Para onde a pergunta vai, e por quê.

    `candidatos` só é preenchido em `ESCOLHA`: a pergunta nomeou mais de um caso, e
    escolher um deles seria adivinhar.
    """

    natureza: str
    caso_id: str | None = None
    verbete: Verbete | None = None
    candidatos: list[dict[str, Any]] = field(default_factory=list)


def rotear(
    pergunta: str,
    casos: list[dict[str, Any]],
    *,
    caso_fixado: str | None = None,
) -> Decisao:
    """Decide o destino da pergunta. Determinístico: nenhum modelo participa daqui.

    Duas precedências que valem a pena entender:

    - **o caso citado NA PERGUNTA vence o caso da conversa.** É o que faz "e o caso do
      João Souza?" mudar de assunto no meio da conversa, em vez de responder sobre a
      cliente anterior com o nome do João no texto;
    - **o caso da conversa vence o glossário.** Numa conversa já colada a um caso,
      "quais fatos alegados existem?" tem de listar os fatos daquele caso, não explicar o
      conceito. Quem quer a explicação genérica abre outra conversa, ou solta o caso na
      barra do alto — as duas coisas são um clique.
    """
    citados = casos_citados(pergunta, casos)
    if len(citados) > 1:
        return Decisao(natureza=ESCOLHA, candidatos=citados)
    if len(citados) == 1:
        return Decisao(natureza=CASO, caso_id=str(citados[0]["id"]))

    if caso_fixado:
        return Decisao(natureza=CASO, caso_id=caso_fixado)

    verbete = verbete_para(pergunta)
    if verbete is not None:
        return Decisao(natureza=SISTEMA, verbete=verbete)

    return Decisao(natureza=ACERVO)


# ------------------------------------------------------- o que ainda não existe


#: A recusa honesta. Curta na tela; a rota que faltaria está em `docs/AGENTE-GERAL.md`.
#:
#: Ela diz três coisas, nesta ordem: que não sabe, por que não sabe, e o que dá para
#: fazer agora. As duas primeiras sem a terceira seriam uma porta fechada.
TEXTO_ACERVO = (
    "Esta pergunta atravessa vários casos, e eu ainda não sei responder isso.\n\n"
    "O que existe hoje é a conversa sobre UM caso: fatos, pendências, teses e peças "
    "daquele caso, com a origem de cada afirmação. Uma resposta sobre o acervo inteiro "
    "precisaria de uma consulta que ainda não foi construída — e responder por "
    "aproximação seria pior do que não responder.\n\n"
    "Enquanto isso: cite o cliente pelo nome (ou escolha o caso no alto da conversa) e eu "
    "respondo sobre ele. Para a leitura do escritório inteiro — quantos casos, em que "
    "estágio, o que está parado — o Panorama já mede isso com dado apurado."
)

#: O que a tela mostra como "o que falta para isto funcionar". Resumo do que está
#: especificado em `docs/AGENTE-GERAL.md`: a tela não deve virar documentação, mas quem lê
#: a recusa merece saber que ela tem tamanho conhecido, e não é um buraco vago.
FALTA_PARA_RESPONDER = (
    "Uma rota de chat sobre o acervo no agente jurídico — hoje o chat é por caso",
    "Entrada: a pergunta, o escritório e os filtros que a Carteira já usa",
    "Saída: a resposta, os casos citados e a natureza de cada afirmação",
)


def texto_do_acervo() -> dict[str, Any]:
    """A resposta que a tela mostra para a pergunta que ninguém responde ainda."""
    return {"conteudo": TEXTO_ACERVO, "falta": list(FALTA_PARA_RESPONDER)}
