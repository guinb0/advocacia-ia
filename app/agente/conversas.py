"""O agente geral: a conversa que não começa dentro de um caso.

`conversa_geral.py` decide **para onde** vai cada pergunta. Este módulo executa a decisão
e guarda a transcrição.

Quem é dono do quê:

- **a conversa é do Acervo.** Ela começa antes de haver caso, e pode nunca ter um. A
  transcrição inteira mora em `dbo.acervo_conversas` / `dbo.acervo_conversa_mensagens`,
  porque só ela mistura o que o agente respondeu sobre um caso, o que o glossário
  explicou sobre o sistema e a recusa honesta de uma pergunta sobre o acervo. Nenhum dos
  outros lados tem essa transcrição inteira, e é ela que a tela reabre;
- **o raciocínio continua sendo do agente.** Quando a pergunta vai para um caso, o
  `conversation_id` de lá é guardado em `conversa_ref` — é o que faz a segunda pergunta
  continuar o mesmo fio em vez de recomeçar do zero.

Trocar de caso no meio da conversa zera esse fio de propósito: o `conversation_id` do
agente pertence a um caso, e reaproveitá-lo em outro pediria ao agente que respondesse
sobre um caso com o histórico de outro.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import armazenamento
from . import analista, conversa_geral, espelho
from .cliente import Cliente, ErroDoAgente

log = logging.getLogger("agente")

__all__ = [
    "abrir",
    "apagar",
    "detalhar",
    "fixar_caso",
    "listar",
    "responder",
    "traduzir_do_agente",
]

#: Quanto do texto da pergunta vira título quando a conversa é nova.
_LIMITE_TITULO = 80


def _titulo_de(pergunta: str) -> str:
    """A primeira pergunta vira o título — como em qualquer chat.

    Cortado com reticência em vez de truncado seco: "Quais casos estão parados esper" na
    lista parece defeito, e o advogado não sabe se falta texto ou se ele escreveu assim.
    """
    limpa = " ".join(pergunta.split())
    if len(limpa) <= _LIMITE_TITULO:
        return limpa or "Nova conversa"
    return limpa[: _LIMITE_TITULO - 1].rstrip() + "…"


def _resumo_de(natureza: str, caso: dict[str, Any] | None) -> str:
    """A linha de contexto do item no histórico.

    É o que distingue, na lista, "Sobre o sistema" de uma conversa sobre um cliente —
    duas conversas com título parecido e propósitos opostos.
    """
    if natureza == conversa_geral.SISTEMA:
        return "Sobre o sistema"
    if natureza == conversa_geral.ANALISE:
        # Sem esta linha a análise entrava no histórico como "Sobre um caso" — e ela é
        # justamente a resposta que NÃO é de um caso só.
        return "Análise do acervo"
    if natureza == conversa_geral.ACERVO:
        return "Sem resposta ainda"
    if caso:
        return str(caso.get("cliente") or "Sobre um caso")
    return "Sobre um caso"


def listar(usuario: str, busca: str = "") -> list[dict[str, Any]]:
    return [_como_resumo(item) for item in armazenamento.listar_conversas(usuario, busca=busca)]


def _como_resumo(conversa: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": conversa["id"],
        "titulo": conversa["titulo"],
        "resumo": conversa["resumo"],
        "caso_id": conversa["caso_id"],
        "criado_em": conversa["criado_em"],
        "atualizado_em": conversa["atualizado_em"],
    }


def abrir(usuario: str, *, caso_id: str | None = None) -> dict[str, Any]:
    """Uma conversa vazia. O título real chega com a primeira pergunta."""
    caso = armazenamento.obter_caso(caso_id) if caso_id else None
    conversa = armazenamento.criar_conversa(
        "Nova conversa",
        usuario=usuario,
        caso_id=caso["id"] if caso else None,
        resumo=str(caso.get("cliente") or "") if caso else "",
    )
    return {**_como_resumo(conversa), "mensagens": []}


def detalhar(conversa_id: str, usuario: str) -> dict[str, Any] | None:
    conversa = armazenamento.obter_conversa(conversa_id)
    if conversa is None or conversa["usuario"] != usuario:
        return None
    return {
        **_como_resumo(conversa),
        "mensagens": [_como_mensagem(m) for m in armazenamento.mensagens_da_conversa(conversa_id)],
    }


def _como_mensagem(registro: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": registro["id"],
        "papel": registro["papel"],
        "conteudo": registro["conteudo"],
        "natureza": registro["natureza"],
        "payload": registro.get("payload") or {},
        "criado_em": registro["criado_em"],
    }


def apagar(conversa_id: str, usuario: str) -> bool:
    return armazenamento.excluir_conversa(conversa_id, usuario)


def fixar_caso(
    conversa_id: str, usuario: str, caso_id: str | None
) -> dict[str, Any] | None:
    """Cola a conversa a um caso, ou a solta quando `caso_id` é nulo.

    Trocar de caso zera o `conversa_ref`: o fio do agente pertence ao caso que saiu, e
    reaproveitá-lo pediria ao agente que respondesse sobre um caso com o histórico de
    outro.
    """
    conversa = armazenamento.obter_conversa(conversa_id)
    if conversa is None or conversa["usuario"] != usuario:
        return None

    if caso_id is None:
        armazenamento.atualizar_conversa(conversa_id, resumo="", soltar_caso=True)
        return detalhar(conversa_id, usuario)

    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        return None
    if conversa["caso_id"] != caso_id:
        armazenamento.atualizar_conversa(conversa_id, soltar_caso=True)
    armazenamento.atualizar_conversa(
        conversa_id, caso_id=caso_id, resumo=str(caso.get("cliente") or "")
    )
    return detalhar(conversa_id, usuario)


def responder(
    conversa_id: str,
    pergunta: str,
    usuario: str,
    *,
    caso_escolhido: str | None = None,
) -> dict[str, Any] | None:
    """Roteia a pergunta, grava as duas mensagens e devolve a resposta.

    `caso_escolhido` é a ORDEM de quem clicou num caso da lista de desambiguação — vence
    tudo, inclusive os nomes citados na pergunta. É diferente do caso da conversa, que é
    só o padrão e cede à citação.

    Devolve `None` quando a conversa não é de quem perguntou — a rota traduz isso em
    `404`, e não em `403`: dizer "existe, mas não é sua" já entrega que ela existe.
    """
    conversa = armazenamento.obter_conversa(conversa_id)
    if conversa is None or conversa["usuario"] != usuario:
        return None

    armazenamento.registrar_mensagem(
        conversa_id, papel="USER", conteudo=pergunta, natureza="PERGUNTA"
    )

    casos = armazenamento.listar_casos()

    if caso_escolhido:
        # Escolha explícita não passa pelo roteador: quem clicou num dos casos da lista de
        # desambiguação já respondeu a pergunta que o roteador faria. Roteá-la de novo
        # devolveria a MESMA lista — o texto continua citando os dois nomes —, e o clique
        # não sairia do lugar.
        resposta = _do_caso(conversa, caso_escolhido, pergunta)
    else:
        decisao = conversa_geral.rotear(pergunta, casos, caso_fixado=conversa["caso_id"])
        if decisao.natureza == conversa_geral.ESCOLHA:
            resposta = _escolher_entre(decisao.candidatos)
        elif decisao.natureza == conversa_geral.SISTEMA:
            resposta = _do_glossario(decisao.verbete, pergunta, conversa_id)
        elif decisao.natureza == conversa_geral.CASO and decisao.caso_id:
            resposta = _do_caso(conversa, decisao.caso_id, pergunta)
        else:
            resposta = _do_acervo(pergunta, conversa_id)

    mensagem = armazenamento.registrar_mensagem(
        conversa_id,
        papel="ASSISTANT",
        conteudo=resposta["conteudo"],
        natureza=resposta["natureza"],
        payload=resposta.get("payload") or {},
    )

    caso = next((c for c in casos if c["id"] == resposta.get("caso_id")), None)
    titulo = None if conversa["titulo"] != "Nova conversa" else _titulo_de(pergunta)
    armazenamento.atualizar_conversa(
        conversa_id,
        titulo=titulo,
        resumo=_resumo_de(resposta["natureza"], caso),
        caso_id=resposta.get("caso_id"),
        conversa_ref=resposta.get("conversa_ref"),
    )

    return {
        "conversa": _como_resumo(armazenamento.obter_conversa(conversa_id) or conversa),
        "mensagem": _como_mensagem(mensagem),
        "propostas": resposta.get("propostas") or [],
    }


# ------------------------------------------------------------- os quatro destinos


def _do_caso(conversa: dict[str, Any], caso_id: str, pergunta: str) -> dict[str, Any]:
    """Pergunta sobre um caso: vai para o chat que já existe, com o lastro dele.

    Falha do agente vira mensagem NA CONVERSA, e não erro de tela. Aqui a diferença
    importa: as outras perguntas da conversa continuam respondíveis, e transformar isso
    num `502` apagaria a transcrição inteira por causa de uma resposta.
    """
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        return {
            "natureza": "INDISPONIVEL",
            "conteudo": "Esse caso não está mais no acervo.",
            "payload": {},
        }

    # O fio do agente pertence a um caso. Mudou o caso, começa outro.
    anterior = conversa["conversa_ref"] if conversa["caso_id"] == caso_id else None

    try:
        caso_ref = espelho.caso_ref(caso_id)
        corpo = Cliente().perguntar_ao_caso(
            caso_ref, mensagem=pergunta, conversa_ref=anterior
        )
    except ErroDoAgente as erro:
        log.warning("agente não respondeu à conversa sobre o caso %s: %s", caso_id, erro)
        return {
            "natureza": "INDISPONIVEL",
            "conteudo": (
                f"Não consegui falar com o agente sobre o caso de {caso['cliente']} agora.\n\n"
                f"{erro}"
            ),
            "payload": {"caso_id": caso_id, "cliente": caso["cliente"]},
            "caso_id": caso_id,
        }

    return traduzir_do_agente(corpo, caso_id=caso_id, cliente=str(caso["cliente"]))


def traduzir_do_agente(
    corpo: dict[str, Any], *, caso_id: str, cliente: str
) -> dict[str, Any]:
    """O corpo do chat do agente vira uma mensagem da conversa geral.

    Separado do resto para poder ser exercitado com uma resposta de verdade do agente, sem
    banco e sem rede — que é como o formato de lá foi conferido (`tests/test_conversas.py`).

    O lastro é gravado junto do texto. Sem ele, reabrir a conversa amanhã mostraria a
    conclusão sem as afirmações que a sustentam, que é exatamente o que este sistema não
    pode produzir. Vale também para as `gaps`: quando o guardrail do agente reprova a
    própria resposta ("não foi possível produzir uma resposta com referências
    verificáveis"), é a lista de lacunas que diz por quê.
    """
    mensagem = corpo.get("message") or {}
    lastro = mensagem.get("payload") or {}
    return {
        "natureza": conversa_geral.CASO,
        "conteudo": str(mensagem.get("content") or ""),
        "payload": {
            "caso_id": caso_id,
            "cliente": cliente,
            "citacoes": mensagem.get("citations") or [],
            "afirmacoes": lastro.get("assertions") or [],
            "pendencias": lastro.get("gaps") or [],
        },
        "caso_id": caso_id,
        "conversa_ref": corpo.get("conversation_id"),
        # As propostas seguem no formato do agente: `lib/agente.ts` já sabe traduzi-lo, e
        # é a mesma tradução que a tela do caso usa.
        "propostas": corpo.get("proposals") or [],
    }


def _do_glossario(
    verbete: conversa_geral.Verbete | None, pergunta: str, conversa_id: str
) -> dict[str, Any]:
    """Explicação do produto. Texto fixo, e a tela diz que é."""
    if verbete is None:
        # Sem verbete não é recusa: é pergunta que o analista pode investigar.
        return _do_acervo(pergunta, conversa_id)
    return {
        "natureza": conversa_geral.SISTEMA,
        "conteudo": verbete.texto,
        "payload": {"verbete": verbete.codigo, "titulo": verbete.titulo},
    }


#: Quantas trocas anteriores acompanham a pergunta até o analista.
#:
#: Quatro (duas perguntas e duas respostas) é o que faz "e o dela?" continuar o assunto.
#: A conversa inteira encareceria cada pergunta e traria de volta o material das
#: consultas antigas, que o analista já não pode conferir.
_TROCAS_DE_CONTEXTO = 4


def _historico_para_o_analista(conversa_id: str) -> list[dict[str, str]]:
    """As últimas trocas, no vocabulário do modelo.

    Só o TEXTO volta — nunca o lastro nem as consultas de antes. O analista mede de novo
    a cada pergunta: reaproveitar o número de ontem como se fosse de agora é a maneira
    mais silenciosa de envelhecer uma resposta.
    """
    recentes = armazenamento.mensagens_da_conversa(conversa_id)[-_TROCAS_DE_CONTEXTO:]
    return [
        {
            "role": "user" if m["papel"] == "USER" else "assistant",
            "content": str(m["conteudo"])[:2000],
        }
        for m in recentes
        if str(m.get("conteudo") or "").strip()
    ]


def _do_acervo(pergunta: str, conversa_id: str) -> dict[str, Any]:
    """A pergunta que atravessa o acervo — ou que não coube em nenhum outro destino.

    Vai para o **analista** (`analista.py`): um modelo com as consultas do escritório na
    mão, livre para escolher quais usar. O que ele não pode é afirmar sem ter medido, e
    é isso que o guardrail de lastro confere antes de a resposta chegar aqui.

    Falha do analista NÃO é erro de tela: vira a recusa honesta que existia antes dele,
    dizendo o que faltaria. A conversa continua utilizável, e a pergunta seguinte pode
    perfeitamente ser sobre um caso — que tem outro caminho.
    """
    try:
        analise = analista.responder(pergunta, _historico_para_o_analista(conversa_id))
    except analista.ErroDoAnalista as erro:
        log.warning("analista indisponível: %s", erro)
        honesta = conversa_geral.texto_do_acervo()
        return {
            "natureza": conversa_geral.ACERVO,
            "conteudo": honesta["conteudo"],
            "payload": {"falta": [str(erro), *honesta["falta"]]},
        }

    if analise.recusa:
        # O analista trabalhou e o guardrail reprovou o resultado. Isso é resposta — e
        # das mais importantes: diz que a pergunta não pôde ser sustentada, em vez de
        # entregar um número que ninguém mediu.
        return {
            "natureza": conversa_geral.ACERVO,
            "conteudo": analise.conteudo,
            "payload": {
                "falta": analise.pendencias,
                "consultas": analise.consultas,
            },
        }

    return {
        "natureza": conversa_geral.ANALISE,
        "conteudo": analise.conteudo,
        "payload": {
            "afirmacoes": analise.afirmacoes,
            "pendencias": analise.pendencias,
            # O caminho que a resposta percorreu. Aparece na tela como "como cheguei
            # nisso": sem isso, uma leitura crítica do acervo é indistinguível de um
            # palpite bem escrito.
            "consultas": analise.consultas,
            "casos": analise.casos,
        },
    }


#: Quantos casos cabem na resposta antes de a lista deixar de ajudar.
#:
#: Oito botões ainda se lê de relance; vinte viram uma segunda lista de casos dentro da
#: conversa, e aí o seletor do alto da tela faz esse trabalho melhor.
_MAXIMO_DE_CANDIDATOS = 8


def _escolher_entre(candidatos: list[dict[str, Any]]) -> dict[str, Any]:
    """A pergunta nomeou mais de um caso.

    Escolher um seria adivinhar; responder sobre os dois seria a pergunta de acervo que
    ainda não existe. Perguntar qual é a única saída honesta.

    O mesmo cliente com dois casos é situação corriqueira — mesma pessoa, duas ações —, e
    aí a lista de nomes repetidos não distingue nada. Por isso cada candidato vai com a
    categoria e a data: é o que permite reconhecer qual é qual.
    """
    nomes = sorted({str(c.get("cliente") or "") for c in candidatos})
    mostrados = candidatos[:_MAXIMO_DE_CANDIDATOS]

    if len(nomes) == 1:
        texto = f"Há {len(candidatos)} casos de {nomes[0]}. Sobre qual deles eu respondo?"
    else:
        texto = (
            f"Esta pergunta cita mais de um caso ({', '.join(nomes)}). "
            "Sobre qual deles eu respondo?\n\n"
            "Comparar casos entre si é justamente o que eu ainda não sei fazer."
        )
    if len(candidatos) > len(mostrados):
        texto += (
            f"\n\nMostro os {len(mostrados)} mais recentes; os outros "
            f"{len(candidatos) - len(mostrados)} estão em «Responder sobre», no alto."
        )

    return {
        "natureza": conversa_geral.ESCOLHA,
        "conteudo": texto,
        "payload": {"candidatos": _distinguir(mostrados)},
    }


def _distinguir(casos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dá a cada candidato uma linha que o separa dos outros.

    Categoria e data de abertura resolvem o caso comum. Não resolvem o que um acervo de
    verdade produz: dois processos do mesmo cliente, da mesma categoria, abertos no mesmo
    dia. Aí entra o identificador curto — feio, e ainda assim a única coisa que sobra
    quando tudo o mais coincide. Botão que não distingue é clique no escuro.

    A data vai como veio (UTC, no `criado_em`) e é a tela que a escreve no fuso de quem
    lê. O desempate, aqui, compara instantes — e dois instantes iguais continuam iguais em
    qualquer fuso.
    """
    # Até o minuto, e não até o segundo: a comparação tem de ser sobre o que a tela vai
    # MOSTRAR. Dois casos abertos com 30 segundos de diferença têm `criado_em` distintos e
    # aparecem com a mesma linha — que foi exatamente o que aconteceu no acervo real.
    rotulos = [
        f"{str(caso.get('categoria') or '').replace('_', ' ')}|"
        f"{str(caso.get('criado_em') or '')[:16]}"
        for caso in casos
    ]
    repetidos = {rotulo for rotulo in rotulos if rotulos.count(rotulo) > 1}

    return [
        {
            "caso_id": caso["id"],
            "cliente": caso.get("cliente") or "",
            "categoria": str(caso.get("categoria") or "").replace("_", " "),
            "criado_em": caso.get("criado_em") or "",
            # Só aparece quando é mesmo necessário: um número de seis letras em toda linha
            # da lista pesa e não ajuda ninguém a reconhecer o próprio caso.
            "desempate": str(caso["id"])[:6] if rotulo in repetidos else "",
        }
        for caso, rotulo in zip(casos, rotulos)
    ]
