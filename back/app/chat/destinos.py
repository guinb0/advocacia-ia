"""Para onde vai cada pergunta do chat — decidido sem modelo e sem rede.

O roteamento entre caso, glossário e acervo já existia (`agente/conversa_geral.py`) e
continua valendo: reescrevê-lo aqui criaria duas regras que divergem no dia em que uma
das duas mudar. Este módulo acrescenta os dois destinos que o chat tem e o agente geral
não tinha, e os coloca ANTES do roteamento antigo:

- **`WEB`** — a pergunta é sobre o mundo, não sobre o acervo: texto de lei, prazo,
  súmula, notícia de tribunal. Vai para `pesquisa_web.py`, que busca e cita as fontes;
- **`DOCUMENTOS`** — "quais documentos tem o caso da Maria?". Não precisa de modelo
  nenhum: o sistema sabe a resposta, e o chat a mostra como ela está guardada.

O PADRÃO É A WEB, E ISSO É O PONTO

A primeira versão deste módulo fazia o contrário: a web só acontecia com gatilho
explícito, e todo o resto ia para o analista do acervo. O resultado, medido na primeira
pergunta que fugiu do roteiro ("como instalo um alto-falante em paralelo?"), foi uma
recusa educada de três parágrafos — o analista explicando, com toda a razão, que nenhuma
ferramenta dele alcança eletrônica.

Recusar é o pior resultado possível aqui. O chat existe para responder, e a diferença
entre "isto está no acervo" e "isto está na internet" é trabalho DELE, não de quem
pergunta. Então o padrão virou: **só vai para o analista o que tem cara de acervo; o
resto vai para a web, sem ninguém precisar pedir.**

A PRECEDÊNCIA

1. **o modo pedido pela tela** vence tudo. Quem clicou em "Pesquisar na web" pediu a web,
   mesmo que a frase cite um cliente;
2. **o comando escrito** (`/web`, `/doc`) vem logo atrás — é o mesmo pedido, digitado;
3. **documentos**, quando a pergunta fala de papelada E há um caso em foco;
4. **caso, glossário ou escolha** — o roteamento que já existia (`conversa_geral.rotear`):
   cliente citado, termo do produto, mais de um caso possível;
5. **a web**, quando a frase pede a internet ou pergunta o que a norma diz;
6. **o analista**, quando a frase fala do escritório: casos, prazos, clientes, pendências,
   audiências, peças — o vocabulário de quem está perguntando sobre o próprio acervo;
7. **a web**, para todo o resto.

A ordem entre 3/4 e 5 importa: "o que diz a CAT do caso da Maria?" é documento do caso, e
não pesquisa na internet. O acervo vem primeiro sempre que a pergunta tem um caso dentro.

E a heurística do passo 6 erra — vai errar. A rede que a cobre não está aqui, e sim em
`sessoes._do_acervo`: quando o analista responde sem ter consultado NADA, a pergunta não
era do acervo, e a mesma pergunta é refeita na web antes de qualquer recusa chegar à tela.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..agente import conversa_geral
from .contexto import Contexto, se_sustenta_sozinha

__all__ = [
    "ACERVO",
    "CASO",
    "DOCUMENTOS",
    "MISTA",
    "ESCOLHA",
    "MODOS",
    "SISTEMA",
    "WEB",
    "Destino",
    "decidir",
    "separar_comando",
]

CASO = conversa_geral.CASO
SISTEMA = conversa_geral.SISTEMA
ACERVO = conversa_geral.ACERVO
ESCOLHA = conversa_geral.ESCOLHA
ANALISE = conversa_geral.ANALISE

#: Pesquisa na internet, com as fontes que a sustentam.
WEB = "WEB"

#: O que o sistema já tem sobre um caso: entregas, pendências, entrevistas e peças.
DOCUMENTOS = "DOCUMENTOS"

#: As DUAS respostas na mesma mensagem: o que o acervo diz e o que a internet diz.
#:
#: Não é um destino que `decidir` escolhe — nenhuma lista de palavras separa com
#: segurança "pergunta de acervo" de "pergunta de acervo COM uma segunda pergunta sobre o
#: mundo dentro". Ela nasce em `sessoes._do_acervo`, quando a pergunta falava do
#: escritório e o acervo não tinha a resposta: aí as duas metades são entregues, cada uma
#: com a sua origem. Ver a composição lá.
MISTA = "MISTA"

#: Os modos que a tela pode pedir em voz alta. `AUTO` é a ausência de pedido.
MODOS = ("AUTO", WEB, DOCUMENTOS)


@dataclass(frozen=True)
class Destino:
    """A decisão, e o material que ela já apurou.

    `consulta` é a pergunta LIMPA — sem o `/web` que a começou. É ela que vai para a
    busca; mandar o comando junto faria o buscador procurar pela barra.
    """

    natureza: str
    consulta: str = ""
    caso_id: str | None = None
    verbete: conversa_geral.Verbete | None = None
    candidatos: list[dict[str, Any]] = field(default_factory=list)


# ------------------------------------------------------------------- comandos


#: O que se digita para escolher o destino na mão. Curto porque é atalho de teclado, e
#: quem usa atalho não quer escrever "pesquisar na internet" toda vez.
_COMANDOS = {
    "/web": WEB,
    "/internet": WEB,
    "/pesquisar": WEB,
    "/doc": DOCUMENTOS,
    "/docs": DOCUMENTOS,
    "/documentos": DOCUMENTOS,
}


def separar_comando(pergunta: str) -> tuple[str, str]:
    """Devolve `(modo, pergunta sem o comando)`.

    Só reconhece o comando no COMEÇO. `/web` no meio da frase é parte do texto — e uma
    pergunta que cita um caminho de URL não pode mudar de destino por causa disso.
    """
    texto = (pergunta or "").strip()
    primeira = texto.split(maxsplit=1)
    if not primeira:
        return "AUTO", ""
    modo = _COMANDOS.get(primeira[0].lower())
    if modo is None:
        return "AUTO", texto
    resto = primeira[1].strip() if len(primeira) > 1 else ""
    return modo, resto


# -------------------------------------------------------------------- gatilhos


#: Expressões que pedem a INTERNET em voz alta.
_PEDE_A_WEB = (
    "na web",
    "na internet",
    "no google",
    "pesquise na",
    "pesquisa na",
    "busque na",
    "procure na",
    "busca na internet",
    "fora do sistema",
    "online",
)

#: Perguntas de DIREITO que o acervo não responde: o texto da norma, o prazo, a súmula.
#:
#: Cada uma pede a fonte oficial, e nenhuma delas está no banco do escritório. Sem este
#: gatilho a pergunta caía no analista, que consultava o acervo, não achava nada — e
#: respondia "não encontrei" a uma pergunta que a internet responde em dois segundos.
_PEDE_A_LEI = (
    "o que diz a lei",
    "o que diz o artigo",
    "o que diz a sumula",
    "o que diz a súmula",
    "qual o prazo prescricional",
    "prazo prescricional",
    "qual artigo",
    "que artigo",
    "qual sumula",
    "qual súmula",
    "sumula",
    "súmula",
    "jurisprudencia recente",
    "jurisprudência recente",
    "entendimento do tst",
    "entendimento do stj",
    "entendimento do stf",
    "norma regulamentadora",
)

#: A norma citada pelo NÚMERO. Não cabe na lista acima porque ali cada entrada casa
#: palavra inteira, e "nr-12" tem o número colado no rótulo: o limite de palavra depois
#: de "nr-" nunca fecha, e o gatilho não disparava justamente na forma mais comum de
#: citar uma norma regulamentadora.
_NORMA_POR_NUMERO = (
    re.compile(r"(?<!\w)nr\s*-?\s*\d{1,2}(?!\w)"),
    re.compile(r"(?<!\w)art(?:igo)?\.?\s*\d+"),
    re.compile(r"(?<!\w)lei\s+n?o?\.?\s*\d"),
    re.compile(r"(?<!\w)s[uú]mula\s*n?o?\.?\s*\d+"),
)

#: A papelada do caso, dita de todos os jeitos que se diz por aqui.
_PEDE_DOCUMENTOS = (
    "documento",
    "documentos",
    "documentacao",
    "documentação",
    "papelada",
    "anexo",
    "anexos",
    "arquivo",
    "arquivos",
    "o que ele entregou",
    "o que ela entregou",
    "o que falta entregar",
    "o que ja foi entregue",
    "o que já foi entregue",
    "checklist",
)

#: O vocabulário de quem pergunta sobre o PRÓPRIO escritório.
#:
#: É esta lista que segura a pergunta dentro do acervo agora que o padrão é a web. Ela é
#: de propósito operacional — o que existe no sistema (caso, cliente, prazo, audiência,
#: pendência, minuta) —, e não jurídica: "adicional de insalubridade" é tema de direito e
#: a internet responde melhor; "quais casos têm pedido de insalubridade" é o acervo.
#:
#: Errar para o lado do acervo custa uma consulta a mais (ver a rede em `sessoes.py`);
#: errar para o lado da web custa uma resposta genérica sobre um caso concreto — que é o
#: erro pior, e por isso a lista é generosa.
_FALA_DO_ESCRITORIO = (
    "acervo",
    "escritorio",
    "carteira",
    "meus casos",
    "nossos casos",
    "caso",
    "casos",
    "cliente",
    "clientes",
    "processo",
    "processos",
    "dossie",
    "checklist",
    "entrevista",
    "entrevistas",
    "atendimento",
    "atendimentos",
    "pendencia",
    "pendencias",
    "peticao",
    "peticoes",
    "minuta",
    "peca",
    "pecas",
    "audiencia",
    "audiencias",
    "prazo do caso",
    "contrato",
    "honorarios",
    "panorama",
    "triagem",
    "follow-up",
    "assinatura",
    "aqui no sistema",
    "no sistema",
)

#: Palavras que transformam "documento" em pergunta de PRODUTO, não de caso.
#:
#: "onde fica a documentação do sistema" tem a mesma palavra e destino oposto. Sem esta
#: lista, quem perguntasse como o produto funciona receberia a papelada de um cliente.
_DOCUMENTACAO_DO_PRODUTO = (
    "do sistema",
    "do acervo",
    "da plataforma",
    "tecnica",
    "técnica",
    "manual",
)


#: A pergunta de CONCEITO — a única que o glossário responde bem.
#:
#: Ele explica o que o produto chama de fato alegado, de entrevista, de petição. Essas
#: são as formas de perguntar isso, e o verbete é a melhor resposta que existe para elas:
#: texto escrito à mão, conferível, sem consultar nada.
_CONCEITUAL = (
    "o que e",
    "o que significa",
    "o que quer dizer",
    "como funciona",
    "para que serve",
    "qual a diferenca",
    "qual e a diferenca",
    "diferenca entre",
    "defina",
    "explique",
    "me explica",
    "significa",
)

#: O que denuncia um LEVANTAMENTO: a pergunta quer uma lista, uma contagem, um ranking.
#:
#: O glossário respondia a "qual caso está mais tempo parado?" com a explicação do que é
#: uma entrevista — porque a frase cita "entrevista" e "peça", e o roteador antigo olhava
#: só para a palavra. A resposta chegava correta sobre o conceito e completamente inútil
#: para quem perguntou.
#:
#: "Quando" fica de fora de propósito: "quando a petição pode ser gerada?" é pergunta de
#: regra do produto, e o verbete responde melhor que qualquer consulta.
_LEVANTAMENTO = (
    "qual",
    "quais",
    "quanto",
    "quantos",
    "quanta",
    "quantas",
    "quem",
    "liste",
    "lista",
    "todos",
    "todas",
    "cada",
    "busque",
    "procure",
    "me diga",
    "me mostra",
    "me mostre",
    "mostre",
    "mais tempo",
    "ha quanto tempo",
    "parado",
    "parados",
    "parada",
    "paradas",
    "atrasado",
    "atrasados",
    "pendente",
    "pendentes",
    "tem algum",
    "tem alguma",
    "existe algum",
    "existe alguma",
    "ainda nao",
    "ja foram",
    "faltam",
    "meu",
    "meus",
    "minha",
    "minhas",
    "nosso",
    "nossos",
)


def _cita(texto_normalizado: str, expressoes: tuple[str, ...]) -> bool:
    """A expressão inteira, com limite de palavra.

    Sem o limite, "documento" casaria dentro de "documentoscopia" e "lei" dentro de
    "leilão" — e o destino da pergunta mudaria por causa de uma sílaba.
    """
    for expressao in expressoes:
        alvo = conversa_geral.normalizar(expressao)
        if re.search(rf"(?<!\w){re.escape(alvo)}(?!\w)", texto_normalizado):
            return True
    return False


def _cita_norma(texto_normalizado: str) -> bool:
    return any(padrao.search(texto_normalizado) for padrao in _NORMA_POR_NUMERO)


# -------------------------------------------------------------------- decisão


def decidir(
    pergunta: str,
    casos: list[dict[str, Any]],
    *,
    contexto: Contexto | None = None,
    caso_fixado: str | None = None,
    modo: str = "AUTO",
) -> Destino:
    """O destino da pergunta, lida DENTRO do contexto da sessão.

    `modo` é o que a tela pediu (o botão "Pesquisar na web", por exemplo) e vence
    qualquer leitura do texto: um pedido explícito que o sistema reinterpreta é um
    sistema que não obedece.

    `contexto` é o que a conversa já sabe (`chat/contexto.py`): o assunto em curso e para
    onde a última pergunta foi. É o que permite responder "videos sobre" — que sozinha
    não diz nada — sem inventar regra para cada forma de perguntar.

    `caso_fixado` continua aceito para quem chama sem contexto; o do contexto vence.
    """
    contexto = contexto or Contexto(caso_id=caso_fixado)
    caso_fixado = contexto.caso_id or caso_fixado

    modo_digitado, texto = separar_comando(pergunta)
    if modo not in MODOS:
        modo = "AUTO"
    if modo == "AUTO":
        modo = modo_digitado

    # A pergunta com o assunto dentro. Daqui para baixo é ela que é roteada e é ela que
    # vai ao destino — "videos sobre" e "videos sobre — sobre: como fazer um bolo de
    # chocolate" não têm por que tomar caminhos diferentes.
    texto = contexto.com_assunto(texto)
    normalizada = conversa_geral.normalizar(texto)
    citados = conversa_geral.casos_citados(texto, casos)
    # Caso citado na pergunta vence o caso da sessão — é o que faz "e o do João?" mudar
    # de assunto em vez de responder sobre a cliente anterior.
    caso_em_foco = str(citados[0]["id"]) if len(citados) == 1 else caso_fixado

    if modo == WEB:
        return Destino(natureza=WEB, consulta=texto)

    if modo == DOCUMENTOS:
        if caso_em_foco:
            return Destino(natureza=DOCUMENTOS, consulta=texto, caso_id=caso_em_foco)
        # Pediu os documentos sem dizer de quem — ou citando mais de um cliente.
        # Perguntar é a única saída honesta: escolher um caso aqui seria mostrar a
        # papelada de outra pessoa com toda a confiança do mundo.
        return Destino(natureza=ESCOLHA, consulta=texto, candidatos=citados)

    if len(citados) > 1:
        return Destino(natureza=ESCOLHA, consulta=texto, candidatos=citados)

    # Só vira leitura de papelada quando há UM caso em foco. Sem caso, "quais documentos
    # faltam?" é pergunta sobre o escritório inteiro — e quem responde isso é o analista,
    # que sabe varrer o acervo. Responder com o checklist de um caso escolhido a esmo
    # seria trocar a pergunta por outra parecida.
    quer_documentos = _cita(normalizada, _PEDE_DOCUMENTOS) and not _cita(
        normalizada, _DOCUMENTACAO_DO_PRODUTO
    )
    if quer_documentos and caso_em_foco:
        return Destino(natureza=DOCUMENTOS, consulta=texto, caso_id=caso_em_foco)

    # O roteamento que já existia: caso citado, caso da sessão, termo do produto. Ele só
    # devolve `ACERVO` quando não reconheceu nada disso — e é aí que a decisão nova
    # começa.
    decisao = conversa_geral.rotear(texto, casos, caso_fixado=caso_fixado)
    if decisao.natureza == SISTEMA and not _cita(normalizada, _CONCEITUAL):
        # A pergunta usa uma palavra do produto sem perguntar o que ela SIGNIFICA. Se o
        # que ela quer é uma lista, uma contagem ou um ranking — "qual caso está mais
        # tempo parado?", que cita "entrevista" e "peça" no meio —, o verbete explicaria
        # o conceito e deixaria a pergunta sem resposta.
        if _cita(normalizada, _LEVANTAMENTO):
            return Destino(natureza=ACERVO, consulta=texto)
    if decisao.natureza != ACERVO:
        return Destino(
            natureza=decisao.natureza,
            consulta=texto,
            caso_id=decisao.caso_id,
            verbete=decisao.verbete,
            candidatos=decisao.candidatos,
        )

    # Pergunta de direito — norma, prazo, súmula, entendimento de tribunal — não está no
    # banco do escritório, e o analista só teria como respondê-la de memória.
    if _cita(normalizada, _PEDE_A_WEB) or _cita(normalizada, _PEDE_A_LEI) or _cita_norma(
        normalizada
    ):
        return Destino(natureza=WEB, consulta=texto)

    # Fala do escritório: quem responde é o analista, com as ferramentas. `quer_documentos`
    # entra aqui porque sem caso em foco ele não virou destino próprio lá em cima — "quais
    # documentos faltam?" continua sendo pergunta sobre o acervo, e não sobre o mundo.
    if quer_documentos or _cita(normalizada, _FALA_DO_ESCRITORIO):
        return Destino(natureza=ACERVO, consulta=texto)

    # A PERGUNTA DE ACOMPANHAMENTO SEGUE O CAMINHO DA ANTERIOR.
    #
    # "e quanto tempo?" depois de uma leitura do acervo é pergunta de acervo; a mesma
    # frase depois de uma resposta da internet é pergunta da internet. Sem isto, as duas
    # caíam no padrão (a web) e metade das conversas sobre o escritório era interrompida
    # por uma busca que ninguém pediu.
    #
    # Vale só para a pergunta que NÃO se sustenta sozinha: quem escreveu uma pergunta
    # inteira está dizendo do que quer falar, e o caminho de antes não tem mais peso.
    if not se_sustenta_sozinha(pergunta) and contexto.ultimo_destino in (ACERVO, ANALISE, MISTA):
        return Destino(natureza=ACERVO, consulta=texto)

    # E o resto — qualquer assunto do mundo — vai para a internet em vez de virar recusa.
    return Destino(natureza=WEB, consulta=texto)
