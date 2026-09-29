"""A transcrição do chat: abrir, listar, responder, apagar.

Este módulo executa a decisão de `destinos.py` e guarda o que aconteceu. Ele é o único
lugar do pacote que escreve no banco, e o único que conhece os cinco serviços que
respondem — o que mantém cada um deles ignorante do chat, como já eram.

O TETO DE OITO SESSÕES

É a regra do produto: cada pessoa mantém oito conversas. Ela é aplicada ao **abrir** uma
sessão nova, e não ao listar, porque podar na listagem deixaria a nona gravada e
invisível. Duas consequências deliberadas:

- abrir uma sessão e não perguntar nada NÃO consome vaga: a sessão em branco mais recente
  é reaproveitada. Sem isso, clicar três vezes em "Nova conversa" apagaria três conversas
  de verdade sem que uma única pergunta fosse feita;
- o que sai é a **menos recentemente usada**, e a tela é avisada de quais saíram. Barra
  lateral que encolhe sozinha, sem dizer o quê, parece defeito — e o que saiu não volta.

FALHA DE UM DESTINO NÃO É ERRO DE TELA

O agente jurídico cai, a chave da pesquisa vence, o analista fica sem cota. Nenhuma
dessas coisas pode derrubar a conversa: cada uma vira uma MENSAGEM que diz o que houve e
o que ainda dá para fazer. A sessão continua utilizável, e a pergunta seguinte pode
perfeitamente ter outro destino — que é o ponto de haver cinco.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import armazenamento, pesquisa_web
from ..agente import analista, conversa_geral, conversas as conversas_do_agente, espelho
from ..agente.cliente import Cliente, ErroDoAgente
from . import atalhos as atalhos_lib, contexto as contexto_lib, destinos
from . import documentos as documentos_lib

log = logging.getLogger("chat")

__all__ = [
    "TETO",
    "abrir",
    "apagar",
    "detalhar",
    "listar",
    "responder",
]

#: O teto vive no armazenamento porque é ele quem poda. Reexportado para a rota dizê-lo
#: à tela sem que a tela precise saber de onde veio.
TETO = armazenamento.TETO_DE_SESSOES

#: Quanto da primeira pergunta vira título da sessão.
_LIMITE_TITULO = 70

#: Quantas trocas anteriores acompanham a pergunta até o analista.
#:
#: Quatro (duas perguntas e duas respostas) é o que faz "e o dela?" continuar o assunto.
#: A sessão inteira encareceria cada pergunta e traria de volta material antigo, que o
#: analista já não pode conferir — resposta velha reapresentada como medição de agora é a
#: maneira mais silenciosa de mentir.
_TROCAS_DE_CONTEXTO = 4


# ------------------------------------------------------------------- sessões


def listar(usuario: str) -> dict[str, Any]:
    """As sessões da pessoa e o teto — a tela mostra os dois juntos.

    O teto vai na resposta de propósito: "8 de 8" explica, antes de a poda acontecer, por
    que a próxima conversa vai empurrar uma para fora.
    """
    return {"sessoes": armazenamento.listar_sessoes_de_chat(usuario), "teto": TETO}


def abrir(usuario: str) -> dict[str, Any]:
    """Uma sessão vazia — ou a que já está vazia. Devolve o que a poda apagou."""
    existentes = armazenamento.listar_sessoes_de_chat(usuario)
    em_branco = next((s for s in existentes if not s.get("perguntas")), None)
    if em_branco is not None:
        return {
            "sessao": {**em_branco, "mensagens": []},
            "apagadas": [],
            "teto": TETO,
        }

    sessao = armazenamento.criar_sessao_de_chat(usuario)
    apagadas = armazenamento.podar_sessoes_de_chat(usuario, teto=TETO)
    return {
        "sessao": {**sessao, "perguntas": 0, "mensagens": []},
        "apagadas": apagadas,
        "teto": TETO,
    }


def detalhar(sessao_id: str, usuario: str) -> dict[str, Any] | None:
    """A sessão com as mensagens. `None` quando não é de quem pediu.

    A rota traduz isso em `404`, e não em `403`: dizer "existe, mas não é sua" já entrega
    que ela existe, e para quem pergunta não muda nada.
    """
    sessao = armazenamento.obter_sessao_de_chat(sessao_id)
    if sessao is None or sessao["usuario"] != usuario:
        return None
    return {**sessao, "mensagens": armazenamento.mensagens_do_chat(sessao_id)}


def apagar(sessao_id: str, usuario: str) -> bool:
    return armazenamento.excluir_sessao_de_chat(sessao_id, usuario)


# ----------------------------------------------------------------- responder


def responder(
    sessao_id: str,
    pergunta: str,
    usuario: str,
    *,
    modo: str = "AUTO",
    caso_escolhido: str | None = None,
) -> dict[str, Any] | None:
    """Roteia, responde, grava as duas mensagens e devolve a resposta.

    `caso_escolhido` é a ORDEM de quem clicou num caso da lista de desambiguação: vence o
    texto e vence o caso da sessão. Sem essa distinção, clicar no candidato devolveria a
    MESMA lista — a frase continua citando os dois nomes.
    """
    sessao = armazenamento.obter_sessao_de_chat(sessao_id)
    if sessao is None or sessao["usuario"] != usuario:
        return None

    armazenamento.registrar_mensagem_de_chat(
        sessao_id, papel="USER", conteudo=pergunta, natureza="PERGUNTA"
    )

    casos = armazenamento.listar_casos()
    # O contexto é montado ANTES de gravar a resposta e DEPOIS de gravar a pergunta: o
    # histórico que vai ao modelo inclui a pergunta atual, e o assunto ainda é o de antes
    # dela — que é justamente o que "videos sobre" precisa para ser entendido.
    contexto = contexto_lib.de_sessao(sessao, armazenamento.mensagens_do_chat(sessao_id))

    if caso_escolhido:
        resposta = _do_caso(sessao, caso_escolhido, pergunta)
    else:
        destino = destinos.decidir(pergunta, casos, contexto=contexto, modo=modo)
        resposta = _despachar(destino, sessao, sessao_id, contexto)

    mensagem = armazenamento.registrar_mensagem_de_chat(
        sessao_id,
        papel="ASSISTANT",
        conteudo=resposta["conteudo"],
        natureza=resposta["natureza"],
        payload=resposta.get("payload") or {},
    )

    caso = next((c for c in casos if c["id"] == resposta.get("caso_id")), None)
    # `or None` para o resumo: uma resposta sem contexto próprio (uma recusa, uma lista
    # de escolha) não pode APAGAR o "Sobre um caso" que a conversa já tinha ganhado — a
    # linha da barra lateral ficaria em branco no meio de uma conversa em andamento.
    armazenamento.atualizar_sessao_de_chat(
        sessao_id,
        titulo=_titulo_de(pergunta) if sessao["titulo"] == "Nova conversa" else None,
        resumo=_resumo_de(resposta["natureza"], caso) or None,
        caso_id=resposta.get("caso_id"),
        conversa_ref=resposta.get("conversa_ref"),
        # O contexto da próxima pergunta: o assunto muda quando esta pergunta trouxe um,
        # e o destino é sempre o desta resposta.
        assunto=contexto_lib.proximo_assunto(pergunta, contexto.assunto),
        ultimo_destino=str(resposta["natureza"]),
    )

    return {
        "sessao": armazenamento.obter_sessao_de_chat(sessao_id) or sessao,
        "mensagem": mensagem,
        "propostas": resposta.get("propostas") or [],
    }


def _despachar(
    destino: destinos.Destino,
    sessao: dict[str, Any],
    sessao_id: str,
    contexto: contexto_lib.Contexto,
) -> dict[str, Any]:
    if destino.natureza == destinos.WEB:
        return _da_web(destino.consulta, contexto=contexto)

    if destino.natureza == destinos.DOCUMENTOS and destino.caso_id:
        return _dos_documentos(destino.caso_id)
    if destino.natureza == destinos.ESCOLHA:
        return _escolher_entre(destino.candidatos)
    if destino.natureza == destinos.SISTEMA:
        return _do_glossario(destino.verbete, destino.consulta, sessao_id, contexto)
    if destino.natureza == destinos.CASO and destino.caso_id:
        return _do_caso(sessao, destino.caso_id, destino.consulta)
    return _do_acervo(destino.consulta, sessao_id, contexto)


# ------------------------------------------------------------- os destinos


#: A linha que abre a resposta quando a web entrou como SEGUNDA tentativa.
#:
#: Ela existe para não fingir: a pergunta foi tratada como do acervo, o acervo não tinha
#: nada, e o que segue veio de fora. Sem isso, a mesma bolha apareceria ora com dado
#: apurado do escritório, ora com página de internet, sem nada que as diferenciasse.
_NOTA_DE_FORA = (
    "_Isto não está no acervo do escritório — busquei na internet, e as fontes estão"
    " abaixo._\n\n"
)


def _da_web(
    pergunta: str,
    *,
    nota: str = "",
    contexto: contexto_lib.Contexto | None = None,
) -> dict[str, Any]:
    """A internet, com as fontes que a pesquisa leu e o selo de cada uma.

    A resposta vem de fora e pode estar errada — foi o que aconteceu no primeiro teste
    desta busca, com um prazo de prescrição afirmado sem distinguir contrato em curso de
    contrato extinto. Por isso `tem_fonte_oficial` viaja junto: a tela precisa poder
    dizer "isto não veio da norma" sem depender de o modelo confessar.

    `nota` abre o texto quando a web não foi a primeira escolha (ver `_do_acervo`).

    `contexto` traz o FIO DA CONVERSA. Sem ele, "videos sobre" ia sozinho ao buscador
    logo depois de uma pergunta sobre bolo de chocolate — e voltaram cinco vídeos em
    espanhol sobre agentes de IA, porque duas palavras sem assunto não são uma busca. A
    pergunta já chega aqui com o assunto dentro (`Contexto.com_assunto`, aplicado no
    roteador); o histórico vai junto para o modelo entender o tom da conversa.
    """
    try:
        achado = pesquisa_web.pesquisar(
            pergunta, contexto.historico if contexto else None
        )
    except pesquisa_web.ErroPesquisa as erro:
        return {
            "natureza": "INDISPONIVEL",
            "conteudo": (
                f"Não consegui pesquisar na web agora.\n\n{erro}\n\n"
                "As perguntas sobre os casos do escritório continuam funcionando."
            ),
            "payload": {"atalhos": []},
        }

    return {
        "natureza": destinos.WEB,
        "conteudo": nota + achado["resposta"],
        "payload": {
            "fontes": achado["fontes"],
            "tem_fonte_oficial": achado["tem_fonte_oficial"],
            "modelo": achado.get("modelo", ""),
            "fora_do_acervo": bool(nota),
            "atalhos": atalhos_lib.da_web(achado["fontes"]),
        },
    }


def _tentar_a_web(
    pergunta: str, *, contexto: contexto_lib.Contexto | None = None
) -> dict[str, Any] | None:
    """A web como segunda tentativa. `None` quando ela não está de pé.

    Separada de `_da_web` porque aqui a falha NÃO pode virar a resposta: se a pesquisa
    está desligada ou não respondeu, quem vale é o que o analista já tinha escrito — uma
    recusa honesta é melhor do que trocá-la por "não consegui pesquisar".
    """
    if not pesquisa_web.configurada():
        return None
    resposta = _da_web(pergunta, nota=_NOTA_DE_FORA, contexto=contexto)
    return resposta if resposta["natureza"] == destinos.WEB else None


def _dos_documentos(caso_id: str) -> dict[str, Any]:
    """O que o caso tem, lido do checklist — sem modelo no caminho.

    O painel vai inteiro no `payload`: é o que a tela mostra quando se clica em "Ver
    aqui", e mandá-lo junto da resposta evita a segunda chamada que faria a lista piscar.
    """
    painel = documentos_lib.montar(caso_id)
    if painel is None:
        return {
            "natureza": "INDISPONIVEL",
            "conteudo": "Esse caso não está mais no acervo.",
            "payload": {"atalhos": []},
        }

    return {
        "natureza": destinos.DOCUMENTOS,
        "conteudo": documentos_lib.resumir(painel),
        "caso_id": caso_id,
        "payload": {
            "documentos": painel,
            # O atalho de documentos vai junto de propósito, mesmo com o painel já na
            # mensagem: é ele que leva ao checklist para AGIR — cobrar, reclassificar,
            # subir o que falta —, que é o passo seguinte de quem perguntou isso.
            "atalhos": atalhos_lib.de_casos([caso_id]),
        },
    }


def _do_glossario(
    verbete: conversa_geral.Verbete | None,
    pergunta: str,
    sessao_id: str,
    contexto: contexto_lib.Contexto | None = None,
) -> dict[str, Any]:
    """Explicação do produto: texto fixo, escrito à mão, e a tela diz que é."""
    if verbete is None:
        # Sem verbete não é recusa: é pergunta que o analista pode investigar.
        return _do_acervo(pergunta, sessao_id, contexto)
    return {
        "natureza": destinos.SISTEMA,
        "conteudo": verbete.texto,
        "payload": {
            "verbete": verbete.codigo,
            "titulo": verbete.titulo,
            "atalhos": [atalhos_lib.de_tela("documentacao", "Central de documentação")],
        },
    }


def _do_caso(sessao: dict[str, Any], caso_id: str, pergunta: str) -> dict[str, Any]:
    """Pergunta sobre um caso: vai ao agente jurídico, com o lastro dele.

    Quando o agente não atende — e ele é outro serviço, com outro ciclo de vida —, a
    pergunta NÃO morre: cai para o analista, que lê o acervo daqui. A resposta é outra
    (leitura deste sistema, não do agente), e a tela a mostra como tal. É a diferença
    entre um chat que fica inútil quando um serviço cai e um que responde com o que tem.
    """
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        return {
            "natureza": "INDISPONIVEL",
            "conteudo": "Esse caso não está mais no acervo.",
            "payload": {"atalhos": []},
        }

    # O fio do agente pertence a um caso. Mudou o caso, começa outro.
    anterior = sessao["conversa_ref"] if sessao["caso_id"] == caso_id else None

    try:
        caso_ref = espelho.caso_ref(caso_id)
        corpo = Cliente().perguntar_ao_caso(
            caso_ref, mensagem=pergunta, conversa_ref=anterior
        )
    except ErroDoAgente as erro:
        log.warning("agente não respondeu sobre o caso %s: %s", caso_id, erro)
        return _sem_o_agente(caso, pergunta, erro)

    resposta = conversas_do_agente.traduzir_do_agente(
        corpo, caso_id=caso_id, cliente=str(caso["cliente"])
    )
    resposta["payload"]["atalhos"] = atalhos_lib.de_caso(caso)
    return resposta


def _sem_o_agente(
    caso: dict[str, Any], pergunta: str, erro: ErroDoAgente
) -> dict[str, Any]:
    """O agente caiu: responde o analista, e a resposta diz que foi ele.

    Trocar a origem em silêncio seria pior que não responder — as duas respostas têm
    lastros diferentes, e quem lê precisa saber qual está lendo.
    """
    caso_id = str(caso["id"])
    try:
        analise = analista.responder(
            f"{pergunta}\n\n(A pergunta é sobre o caso {caso_id}, de {caso['cliente']}.)"
        )
    except analista.ErroDoAnalista as falha:
        return {
            "natureza": "INDISPONIVEL",
            "conteudo": (
                f"Não consegui falar com o agente sobre o caso de {caso['cliente']} agora.\n\n"
                f"{erro}\n\nO analista do acervo também não respondeu: {falha}"
            ),
            "payload": {"caso_id": caso_id, "atalhos": atalhos_lib.de_caso(caso)},
            "caso_id": caso_id,
        }

    aviso = (
        "_O agente jurídico não respondeu agora; o que segue é a leitura do acervo "
        "feita por este sistema, com as consultas listadas abaixo._\n\n"
    )
    return {
        "natureza": destinos.ANALISE,
        "conteudo": aviso + analise.conteudo,
        "caso_id": caso_id,
        "payload": {
            "afirmacoes": analise.afirmacoes,
            "pendencias": analise.pendencias,
            "consultas": analise.consultas,
            "casos": analise.casos or [caso_id],
            "atalhos": atalhos_lib.de_caso(caso),
        },
    }


def _compor(analise: analista.Analise, da_web: dict[str, Any]) -> dict[str, Any]:
    """As duas metades numa resposta só: o que o acervo diz, e o que a internet diz.

    POR QUE SOMAR E NÃO SUBSTITUIR
    ==============================

    Uma pergunta de verdade, medida em 22/09: "há algum caso no sistema parecido com o
    julgamento do Moraes, e como anda esse julgamento?". São DUAS perguntas — a primeira
    só o acervo responde, a segunda só a internet. A rede mandava a pergunta inteira para
    a web e devolvia uma resposta só: a metade sobre o escritório simplesmente sumia, e
    quem perguntou não tinha como saber que ela tinha sumido.

    Separar por origem não é enfeite: o que o acervo afirma tem lastro conferível, e o
    que veio da internet não. Juntar os dois num texto corrido faria as duas coisas
    chegarem com o mesmo peso — que é o que este sistema inteiro existe para evitar.

    A parte do acervo só entra quando tem TEXTO. Analista que não produziu nada não vira
    um título vazio em cima da resposta da web.
    """
    do_acervo = (analise.conteudo or "").strip()
    if not do_acervo:
        return da_web

    payload = dict(da_web.get("payload") or {})
    payload["afirmacoes"] = analise.afirmacoes
    payload["pendencias"] = analise.pendencias
    payload["consultas"] = analise.consultas
    payload["fora_do_acervo"] = True

    # O texto da web já vem com a nota de origem (`_NOTA_DE_FORA`); aqui ela é substituída
    # pelo título da seção, senão a mesma informação apareceria duas vezes seguidas.
    da_internet = da_web["conteudo"].replace(_NOTA_DE_FORA, "").strip()

    return {
        "natureza": destinos.MISTA,
        "conteudo": (
            f"**No acervo do escritório**\n\n{do_acervo}\n\n"
            f"---\n\n**Da internet**\n\n{da_internet}"
        ),
        "payload": payload,
    }


def _do_acervo(
    pergunta: str, sessao_id: str, contexto: contexto_lib.Contexto | None = None
) -> dict[str, Any]:
    """A pergunta que atravessa o acervo — ou que não coube em nenhum outro destino.

    Vai para o analista: um modelo com as consultas do escritório na mão, livre para
    escolher quais usar. O que ele não pode é afirmar sem ter medido, e é isso que o
    guardrail de lastro confere antes de a resposta chegar aqui.
    """
    try:
        # O histórico já foi lido para montar o contexto: relê-lo aqui seria uma segunda
        # ida ao banco para buscar exatamente as mesmas linhas.
        historico = contexto.historico if contexto else _historico(sessao_id)
        analise = analista.responder(pergunta, historico[-_TROCAS_DE_CONTEXTO:])
    except analista.ErroDoAnalista as erro:
        log.warning("analista indisponível: %s", erro)
        # O analista caiu, mas a pergunta continua de pé: a internet responde o que
        # puder em vez de a conversa terminar em aviso de configuração.
        alternativa = _tentar_a_web(pergunta, contexto=contexto)
        if alternativa is not None:
            return alternativa
        honesta = conversa_geral.texto_do_acervo()
        return {
            "natureza": destinos.ACERVO,
            "conteudo": honesta["conteudo"],
            "payload": {
                "falta": [str(erro), *honesta["falta"]],
                "atalhos": [atalhos_lib.de_tela("panorama", "Panorama do escritório")],
            },
        }

    # NENHUMA consulta: o analista leu a pergunta, não achou o que medir e respondeu de
    # cabeça — quase sempre para dizer que o assunto não é do acervo. Foi o que aconteceu
    # com "como instalo um alto-falante em paralelo?": três parágrafos de recusa educada
    # sobre uma pergunta que a internet responde em dois segundos.
    #
    # A contagem de consultas é o sinal OBJETIVO de que a pergunta não era daqui — mais
    # confiável que procurar palavras de recusa no texto, que mudam a cada versão do
    # modelo. Quando ela é zero, a mesma pergunta vai para a web antes de qualquer recusa
    # chegar à tela.
    # DOIS caminhos levam à web, e eles cobrem coisas diferentes:
    #
    # 1. o analista DECLAROU que parte da pergunta não é do acervo (`para_a_web`). É o
    #    caso da pergunta de duas metades — "há caso parecido no sistema, e como anda esse
    #    julgamento?" —, em que ele responde a primeira e diz qual é a segunda;
    # 2. ele não consultou NADA. Aí a pergunta não era daqui de forma nenhuma, e o que ele
    #    escreveu é uma recusa educada que a internet responde em dois segundos.
    #
    # O segundo caminho sozinho não bastava: desde que o analista passou a consultar antes
    # de negar, ele mede o acervo, responde bem a metade que é dele — e a outra metade
    # sumia, porque a contagem de consultas deixou de ser zero.
    if analise.para_a_web or not analise.consultas:
        alternativa = _tentar_a_web(analise.para_a_web or pergunta, contexto=contexto)
        if alternativa is not None:
            log.info(
                "chat: %s respondida pela web",
                "segunda metade da pergunta" if analise.para_a_web else "pergunta fora do acervo",
            )
            return _compor(analise, alternativa)

    if analise.recusa:
        # O analista trabalhou e o guardrail reprovou o resultado. Isso é resposta — e
        # das mais importantes: diz que a pergunta não pôde ser sustentada, em vez de
        # entregar um número que ninguém mediu.
        return {
            "natureza": destinos.ACERVO,
            "conteudo": analise.conteudo,
            "payload": {
                "falta": analise.pendencias,
                "consultas": analise.consultas,
                "atalhos": [],
            },
        }

    return {
        "natureza": destinos.ANALISE,
        "conteudo": analise.conteudo,
        "payload": {
            "afirmacoes": analise.afirmacoes,
            "pendencias": analise.pendencias,
            # O caminho que a resposta percorreu. Sem isso, leitura crítica do acervo é
            # indistinguível de palpite bem escrito.
            "consultas": analise.consultas,
            "casos": analise.casos,
            "atalhos": atalhos_lib.de_casos(analise.casos),
        },
    }


def _escolher_entre(candidatos: list[dict[str, Any]]) -> dict[str, Any]:
    """A pergunta citou mais de um caso — ou nenhum, quando pedia um.

    Perguntar é a única saída honesta: escolher seria adivinhar, e responder sobre todos
    seria trocar a pergunta por outra.
    """
    if not candidatos:
        return {
            "natureza": destinos.ESCOLHA,
            "conteudo": (
                "De qual caso? Escreva `#` e o nome do cliente para eu abrir o caso "
                "certo — homônimo e grafia diferente fazem a busca por nome errar, e eu "
                "prefiro perguntar a responder sobre o caso de outra pessoa."
            ),
            "payload": {"candidatos": [], "atalhos": []},
        }

    # A lista de desambiguação é a MESMA do agente geral (`conversas._escolher_entre`):
    # ela sabe distinguir dois casos do mesmo cliente abertos no mesmo dia, e duas cópias
    # dessa regra divergiriam na primeira vez que uma delas ganhasse um critério novo.
    escolha = conversas_do_agente.escolher_entre(candidatos)
    escolha["payload"]["atalhos"] = []
    return escolha


# ------------------------------------------------------------------ auxiliares


def _historico(sessao_id: str) -> list[dict[str, str]]:
    """As últimas trocas, no vocabulário do modelo.

    Só o TEXTO volta — nunca o lastro, as fontes nem as consultas de antes. O analista
    mede de novo a cada pergunta: reaproveitar o número de ontem como se fosse de agora
    envelhece a resposta sem que ninguém perceba.
    """
    recentes = armazenamento.mensagens_do_chat(sessao_id)[-_TROCAS_DE_CONTEXTO:]
    return [
        {
            "role": "user" if m["papel"] == "USER" else "assistant",
            "content": str(m["conteudo"])[:2000],
        }
        for m in recentes
        if str(m.get("conteudo") or "").strip()
    ]


def _titulo_de(pergunta: str) -> str:
    """A primeira pergunta vira o título — como em qualquer chat.

    Cortado com reticência, e não truncado seco: "Quais casos estão parados esper" na
    barra lateral parece defeito, e quem lê não sabe se falta texto ou se foi escrito
    assim.
    """
    limpa = " ".join((pergunta or "").split())
    _, sem_comando = destinos.separar_comando(limpa)
    limpa = sem_comando or limpa
    if len(limpa) <= _LIMITE_TITULO:
        return limpa or "Nova conversa"
    return limpa[: _LIMITE_TITULO - 1].rstrip() + "…"


def _resumo_de(natureza: str, caso: dict[str, Any] | None) -> str:
    """A segunda linha do item na barra lateral: de que a conversa é.

    É o que distingue, na lista, "Sobre o sistema" de uma conversa sobre um cliente —
    dois títulos parecidos com propósitos opostos.
    """
    if natureza == destinos.WEB:
        return "Pesquisa na web"
    if natureza == destinos.MISTA:
        return "Acervo e internet"
    if natureza == destinos.SISTEMA:
        return "Sobre o sistema"
    if natureza == destinos.ANALISE:
        return "Leitura do acervo"
    if natureza == destinos.ACERVO:
        return "Sem resposta ainda"
    if caso:
        return str(caso.get("cliente") or "Sobre um caso")
    return "Sobre um caso" if natureza in (destinos.CASO, destinos.DOCUMENTOS) else ""
