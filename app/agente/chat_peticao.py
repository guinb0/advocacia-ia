"""O chat da petição: a conversa que vive DENTRO do Dossiê, ao lado da minuta.

Não é o agente geral (`conversas.py`), que começa antes de haver caso e roteia a
pergunta entre o acervo, o glossário e o agente jurídico. Aqui o assunto já está
decidido — é esta peça, deste caso — e o que muda é o que o modelo tem na mão: a
entrevista, os documentos lidos por OCR, a análise, a minuta atual e o histórico
dela.

A REGRA QUE ATRAVESSA O MÓDULO INTEIRO

O chat **lê** sozinho e **não escreve nada** sozinho. Toda ferramenta que mexeria
na peça (gerar de novo, revisar por prompt, redigir outra peça, reanalisar os
documentos) não é executada pelo modelo: vira uma PROPOSTA que sobe na resposta e
espera o clique de quem lê. Documento jurídico não pode ter edição invisível, e a
diferença entre "a IA sugeriu" e "a IA fez" é a diferença entre um rascunho e uma
peça protocolada com um pedido que ninguém aprovou.

Quando a proposta é aceita, quem executa é `executar_acao` — e o resultado volta
para a transcrição como mensagem da IA, não como toast que some. O mesmo caminho
serve às ações disparadas pelos botões de sempre (`registrar_evento`): terminou a
análise, saiu uma versão nova, a IA conta no chat o que mudou e o que ficou sem
comprovação.

DE ONDE VEM CADA COISA QUE A RESPOSTA DIZ

Duas origens, nunca misturadas sem aviso: o que está no caso (ferramentas de
leitura, marcadas como `caso`) e o que veio da internet (`pesquisar_na_web`, que
volta com fonte e link e é mostrada com selo próprio pela tela). O prompt exige a
distinção; o `payload` da mensagem guarda as fontes para que ela sobreviva ao
reload da página.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from typing import Any

import httpx

from .. import analise_documentos, armazenamento, peticao_local
from .. import pesquisa_web as pesquisa_web_modulo
from . import peticao_fluxo
from .cliente import ErroDoAgente

log = logging.getLogger("agente")

__all__ = [
    "ESCOPO",
    "ErroDoChat",
    "abrir",
    "conversar",
    "executar_acao",
    "registrar_evento",
]


class ErroDoChat(RuntimeError):
    """Falha que a conversa mostra como está — texto já escrito para quem lê."""


#: O escopo da conversa no banco. Separa esta transcrição da do agente geral.
ESCOPO = "PETICAO"

#: Quantas rodadas de ferramenta antes de o modelo ter de responder com o que tem.
#:
#: Cinco cobre o caminho mais longo que faz sentido aqui (minuta -> análise ->
#: documentos -> histórico -> web). Sem teto, uma pergunta vaga faz o modelo ler o
#: caso em círculo enquanto o advogado espera com a tela em "digitando".
MAXIMO_DE_PASSOS = 5

#: Quantas trocas anteriores acompanham a pergunta.
#:
#: Doze mensagens (seis idas e voltas) é o que faz "e o item II?" continuar o
#: assunto. A conversa inteira encareceria cada pergunta e traria de volta minutas
#: antigas — e a minuta atual vai no contexto de qualquer jeito, a cada pergunta.
TROCAS_DE_CONTEXTO = 12

#: Prazo de cada chamada ao modelo. Alto porque a investigação encadeia leituras.
TEMPO_DO_MODELO_S = 120

#: Teto de caracteres por documento lido na ferramenta de OCR.
LIMITE_DOCUMENTO = 4000

#: Teto da transcrição da entrevista devolvida ao modelo.
LIMITE_ENTREVISTA = 12000


# --------------------------------------------------------------- a instrução

INSTRUCAO = """\
Você é o assistente de redação que trabalha AO LADO da petição, dentro do dossiê de
um caso trabalhista brasileiro. Quem lê é o advogado responsável pela peça.

O que você tem à mão, pelas ferramentas: a minuta atual e as versões anteriores, a
análise que cruzou a entrevista com os documentos, a transcrição da entrevista, o
texto de OCR dos anexos e a pesquisa na web.

Como você trabalha:

1. CONSULTE ANTES DE AFIRMAR. Nada sobre este caso é sabido de memória. Valor, data,
   nome, número de seção e trecho da minuta vêm de ferramenta. Quando a resposta
   depende do texto da peça, leia a minuta antes de falar dela.
2. SEPARE AS DUAS ORIGENS. O que está nos autos do caso e o que veio da internet são
   coisas diferentes e não se misturam na mesma frase sem aviso. Ao usar a web, diga
   que é da web e cite a fonte em linha, como link markdown.
3. NUNCA CONFUNDA RELATO COM PROVA. Fato que só aparece na entrevista é alegação do
   cliente; comprovado é o que algum documento sustenta. Dizer "comprovado" sobre um
   relato é o erro mais grave que você pode cometer aqui.
4. VOCÊ NÃO ALTERA A PEÇA SOZINHO. Para mudar a petição, gerar outra versão, redigir
   outra peça ou reanalisar os documentos, use a ferramenta de PROPOR correspondente.
   Ela não executa nada: registra o pedido para o advogado confirmar. Depois de
   propor, diga em uma frase o que vai acontecer e que depende do aceite dele.
   Nunca diga que já alterou, já gerou ou já salvou.
5. SEJA CURTO E ÚTIL. Sem saudação, sem repetir a pergunta, sem resumo do que você
   leu. Vá ao ponto, aponte o que está frágil e o que falta comprovar.

Responda em português do Brasil. Markdown simples é bem-vindo (listas, negrito,
citação); a tela sabe renderizá-lo.\
"""


def _texto_da_minuta(peticao: dict[str, Any], *, completo: bool) -> str:
    linhas = []
    for secao in peticao.get("sections") or []:
        conteudo = str(secao.get("content") or "")
        if not completo and len(conteudo) > 600:
            conteudo = conteudo[:600] + " […]"
        linhas.append(
            f"[{secao.get('code')}] {secao.get('label') or ''}\n{conteudo}".strip()
        )
    return "\n\n".join(linhas)


def _contexto_do_caso(caso_id: str) -> str:
    """O cartão de identidade do caso, colado em TODA pergunta.

    Sem isto a segunda pergunta chegava ao modelo sem saber de quem é o caso nem se
    existe minuta, e ele começava pedindo ferramenta para descobrir o óbvio — uma
    ida a mais ao modelo por pergunta, e uma resposta a mais começando com "deixe-me
    verificar". O que é caro (texto da peça, OCR, transcrição) continua sendo pedido
    por ferramenta.
    """
    caso = armazenamento.obter_caso(caso_id) or {}
    peticao = peticao_local.carregar(caso_id)
    partes = [
        f"Caso: {caso.get('cliente') or 'cliente não identificado'}"
        f" · categoria {str(caso.get('categoria') or 'não informada').replace('_', ' ')}"
        f" · id {caso_id}",
    ]
    if not peticao:
        partes.append(
            "Minuta: ainda NÃO existe petição gerada para este caso. Para criá-la, a"
            " ferramenta é propor_geracao_da_peticao."
        )
        return "\n".join(partes)

    pendencias = (peticao.get("readiness") or {}).get("pendencias") or []
    anexas = peticao_local.listar_anexas(caso_id)
    partes.append(
        f"Minuta: {peticao.get('title') or 'Petição inicial'} — versão"
        f" {peticao.get('version')} ({peticao.get('status')}),"
        f" {len(peticao.get('sections') or [])} seções."
    )
    if pendencias:
        partes.append(
            "Pontos sem comprovação documental na minuta: " + "; ".join(str(p) for p in pendencias[:8])
        )
    if peticao.get("revisao_pendente"):
        partes.append(
            "ATENÇÃO: há uma revisão aguardando decisão do advogado (comparação aberta"
            " ao lado). Enquanto ela não for aceita ou descartada, propor outra revisão"
            " só confunde — avise-o disso."
        )
    if anexas:
        partes.append(
            "Outras peças já redigidas neste caso: "
            + "; ".join(str(p.get("titulo") or "") for p in anexas)
        )
    return "\n".join(partes)


# ------------------------------------------------------------- as ferramentas
#
# Leitura executa na hora; proposta NÃO executa nada. As duas listas são separadas
# no catálogo para que a distinção seja estrutural, e não uma convenção de nome que
# alguém quebra sem perceber.


def _ler_minuta(caso_id: str, completo: bool = False) -> dict[str, Any]:
    peticao = peticao_local.carregar(caso_id)
    if not peticao:
        return {"existe": False, "aviso": "Nenhuma petição foi gerada para este caso ainda."}
    pendente = peticao.get("revisao_pendente") or None
    return {
        "existe": True,
        "titulo": peticao.get("title"),
        "versao": peticao.get("version"),
        "status": peticao.get("status"),
        "pendencias_sem_comprovacao": (peticao.get("readiness") or {}).get("pendencias") or [],
        "revisao_aguardando_decisao": (
            {"pedido": pendente.get("prompt"), "de_quem": pendente.get("usuario")}
            if pendente
            else None
        ),
        "texto": _texto_da_minuta(peticao, completo=bool(completo)),
    }


def _ler_analise(caso_id: str) -> dict[str, Any]:
    peticao = peticao_local.carregar(caso_id) or {}
    analise = peticao.get("analise") or {}
    if not analise:
        return {
            "existe": False,
            "aviso": (
                "A análise entrevista × documentos ainda não foi feita. Ela sai junto"
                " com a geração da petição."
            ),
        }
    return {
        "existe": True,
        "resumo": analise.get("resumo"),
        "confirmado_por_documentos": analise.get("fatos_confirmados") or [],
        "depende_de_prova_ou_confirmacao": [
            *(analise.get("fatos_so_na_entrevista") or []),
            *(analise.get("lacunas") or []),
        ],
        "confronto_entrevista_documentos": analise.get("cruzamento_entrevista_documentos"),
        "acoes_sugeridas": analise.get("acoes_sugeridas") or [],
    }


def _ler_documentos(caso_id: str, arquivo: str = "") -> dict[str, Any]:
    procurado = " ".join(str(arquivo or "").split()).lower()
    lidos = peticao_local.documentos_ocr(caso_id)
    if not lidos:
        return {"documentos": [], "aviso": "Nenhum anexo deste caso tem texto lido por OCR."}
    escolhidos = [d for d in lidos if procurado in str(d["arquivo"]).lower()] if procurado else lidos
    if procurado and not escolhidos:
        return {
            "documentos": [],
            "aviso": f"Nenhum anexo com «{arquivo}» no nome.",
            "arquivos_disponiveis": [d["arquivo"] for d in lidos],
        }
    # Com nome, vai o texto que couber; sem nome, vai um panorama — devolver o OCR
    # de quarenta anexos numa só ferramenta estoura a janela e piora a resposta.
    limite = LIMITE_DOCUMENTO if procurado else 900
    return {
        "documentos": [
            {"arquivo": d["arquivo"], "texto": d["texto"][:limite]}
            for d in escolhidos[: (8 if procurado else 25)]
        ],
        "total_no_caso": len(lidos),
    }


def _ler_entrevista(caso_id: str) -> dict[str, Any]:
    try:
        dados = peticao_fluxo.transcricao(caso_id)
    except ErroDoAgente as erro:
        return {"existe": False, "aviso": str(erro)}
    return {
        "existe": True,
        "arquivo": dados.get("arquivo"),
        "caracteres": dados.get("caracteres"),
        "texto": str(dados.get("texto") or "")[:LIMITE_ENTREVISTA],
        "aviso": (
            "Isto é o RELATO do cliente. Fato que só aparece aqui é alegação, não"
            " prova."
        ),
    }


def _ler_historico(caso_id: str) -> dict[str, Any]:
    historico = peticao_fluxo.historico_de_peticao(caso_id)
    return {
        "versoes_anteriores": [
            {
                "versao": v.get("versao"),
                "em": v.get("criado_em"),
                "origem": ((v.get("dados") or {}).get("revisao") or {}).get("origem") or "painel",
                "pedido": ((v.get("dados") or {}).get("revisao") or {}).get("prompt") or "",
            }
            for v in historico.get("versoes") or []
        ],
        "criticas": [
            {
                "em": c.get("criado_em"),
                "de_quem": c.get("usuario"),
                "pedido": c.get("prompt"),
                "de_v": c.get("versao_origem"),
                "para_v": c.get("versao_resultado"),
            }
            for c in historico.get("criticas") or []
        ],
    }


def _pesquisar_na_web(caso_id: str, pergunta: str) -> dict[str, Any]:
    """A única ferramenta cuja resposta NÃO vem do caso. Volta com as fontes."""
    try:
        resultado = pesquisa_web_modulo.pesquisar(pergunta)
    except pesquisa_web_modulo.ErroPesquisa as erro:
        # Falha de pesquisa não derruba a resposta: o modelo é avisado e conta ao
        # advogado que a busca não foi feita, em vez de responder de memória como se
        # tivesse consultado.
        return {"falhou": True, "motivo": str(erro), "fontes": []}
    return {
        "falhou": False,
        "origem": "web",
        "resposta": resultado.get("resposta"),
        "fontes": resultado.get("fontes") or [],
        "aviso": "Conteúdo da internet: cite a fonte em linha e não misture com o que está nos autos.",
    }



# ------------------------------------------------------ as ações que se propõem
#
# Nenhuma delas roda aqui. O modelo as "chama", o executor transforma em proposta e
# a tela pede o clique. O texto de cada uma é escrito para o modelo: diz o que a
# ação faz e, principalmente, que ela NÃO acontece sem confirmação.

#: O que torna um pedido de revisão sensível o bastante para a tela avisar em
#: destaque antes do aceite: valor de pedido, remoção de cláusula, fundamentação.
#:
#: A confirmação é exigida de QUALQUER jeito — nenhuma revisão se aplica sozinha.
#: Isto só muda o peso do aviso: "vai mexer no valor da causa" merece uma leitura
#: mais lenta do que "troque «reclamante» por «autor»".
_TERMOS_SENSIVEIS = (
    "valor",
    "r$",
    "quantum",
    "indeniza",
    "remov",
    "retir",
    "exclu",
    "apag",
    "tira",
    "fundament",
    "tese",
    "artigo",
    "súmula",
    "sumula",
    "pedido",
)


def _sensivel(pedido: str) -> bool:
    texto = (pedido or "").lower()
    return any(termo in texto for termo in _TERMOS_SENSIVEIS)


def _propor_revisao(caso_id: str, pedido: str = "", motivo: str = "") -> dict[str, Any]:
    del caso_id  # a proposta é do chat; quem a executa é `executar_acao`
    pedido = " ".join(str(pedido or "").split())
    if not pedido:
        return {"registrada": False, "erro": "Escreva o que deve mudar na petição."}
    return {
        "registrada": True,
        "tipo": "REVISAR",
        "pedido": pedido,
        "motivo": motivo,
        "sensivel": _sensivel(pedido),
        "o_que_acontece": (
            "Quando o advogado confirmar, a IA reescreve a peça aplicando só este"
            " pedido e a comparação (antes × depois) abre ao lado. A versão atual"
            " continua valendo até ele aceitar a comparação."
        ),
    }


def _propor_geracao(caso_id: str, motivo: str = "") -> dict[str, Any]:
    del caso_id
    return {
        "registrada": True,
        "tipo": "GERAR",
        "motivo": motivo,
        "o_que_acontece": (
            "Quando confirmado, o sistema cruza entrevista e documentos de novo e"
            " redige a petição inteira. Isso cria uma versão nova e substitui o texto"
            " em trabalho — a anterior fica no histórico."
        ),
    }


def _propor_analise_documentos(caso_id: str, motivo: str = "") -> dict[str, Any]:
    del caso_id
    return {
        "registrada": True,
        "tipo": "ANALISAR_DOCUMENTOS",
        "motivo": motivo,
        "o_que_acontece": (
            "Quando confirmado, o sistema relê o OCR de todos os anexos e remonta a"
            " cronologia dos fatos. Não altera a minuta nem os anexos."
        ),
    }


def _propor_peca_anexa(
    caso_id: str, titulo: str = "", motivo: str = "", pedidos: list[str] | None = None
) -> dict[str, Any]:
    del caso_id
    titulo = " ".join(str(titulo or "").split())
    if not titulo:
        return {"registrada": False, "erro": "Diga qual peça deve ser redigida."}
    return {
        "registrada": True,
        "tipo": "PECA_ANEXA",
        "titulo": titulo,
        "motivo": motivo,
        "pedidos": [str(p) for p in (pedidos or []) if str(p).strip()],
        "o_que_acontece": (
            "Quando confirmado, o sistema redige esta peça a partir do mesmo material."
            " A petição inicial NÃO é tocada."
        ),
    }


#: Nome da ferramenta -> (função, esquema para o modelo, altera alguma coisa?).
#:
#: A terceira posição é a fronteira do módulo: `False` executa na hora, `True` só
#: registra a proposta. Deixá-la explícita no catálogo evita que a distinção vire
#: convenção de nome — que alguém quebra sem perceber ao acrescentar a próxima.
CATALOGO: dict[str, tuple[Any, dict[str, Any], bool]] = {
    "ler_minuta": (
        _ler_minuta,
        {
            "description": (
                "O texto da petição deste caso, seção por seção, com versão, status e"
                " os pontos sem comprovação documental. Use SEMPRE antes de falar do"
                " que está escrito na peça. `completo=true` traz as seções inteiras;"
                " sem isso, cada seção vem cortada."
            ),
            "parameters": {
                "type": "object",
                "properties": {"completo": {"type": "boolean"}},
            },
        },
        False,
    ),
    "ler_analise": (
        _ler_analise,
        {
            "description": (
                "A análise que cruzou a entrevista com os documentos: o que está"
                " confirmado por documento, o que depende de prova, o confronto"
                " completo e as outras ações cabíveis. É o conteúdo dos cartões"
                " «Confirmado por documentos» e «Depende de prova ou confirmação»."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
        False,
    ),
    "ler_documentos": (
        _ler_documentos,
        {
            "description": (
                "O texto lido por OCR dos anexos do caso. Sem `arquivo`, devolve um"
                " panorama de todos; com `arquivo` (parte do nome basta), devolve o"
                " texto daquele documento para você citar o trecho."
            ),
            "parameters": {
                "type": "object",
                "properties": {"arquivo": {"type": "string"}},
            },
        },
        False,
    ),
    "ler_entrevista": (
        _ler_entrevista,
        {
            "description": (
                "A transcrição do atendimento. É RELATO do cliente: o que só aparece"
                " aqui é alegação, nunca prova."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
        False,
    ),
    "ler_historico": (
        _ler_historico,
        {
            "description": (
                "As versões anteriores da minuta e as críticas registradas: quem pediu"
                " o quê, quando, e de qual versão para qual."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
        False,
    ),
    "pesquisar_na_web": (
        _pesquisar_na_web,
        {
            "description": (
                "Pesquisa na internet (jurisprudência recente, súmula, lei, notícia"
                " sobre a empresa ré) e devolve a resposta COM as fontes. Use quando a"
                " pergunta pedir dado externo ou quando um ponto da peça precisar de"
                " apoio que não está nos autos. O resultado não vem do caso: cite a"
                " fonte e diga que é da web."
            ),
            "parameters": {
                "type": "object",
                "properties": {"pergunta": {"type": "string"}},
                "required": ["pergunta"],
            },
        },
        False,
    ),
    "propor_revisao_da_peticao": (
        _propor_revisao,
        {
            "description": (
                "Registra um pedido de alteração da petição para o advogado confirmar."
                " NÃO altera nada. `pedido` é a instrução de redação, escrita por você"
                " de forma completa e literal (ex.: «retire o pedido de dano material e"
                " ajuste o valor da causa»)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pedido": {"type": "string"},
                    "motivo": {"type": "string"},
                },
                "required": ["pedido"],
            },
        },
        True,
    ),
    "propor_geracao_da_peticao": (
        _propor_geracao,
        {
            "description": (
                "Registra o pedido de gerar a petição (ou gerá-la de novo) para o"
                " advogado confirmar. NÃO gera nada. Com minuta já existente e pedido"
                " pontual, prefira propor_revisao_da_peticao."
            ),
            "parameters": {
                "type": "object",
                "properties": {"motivo": {"type": "string"}},
            },
        },
        True,
    ),
    "propor_analise_de_documentos": (
        _propor_analise_documentos,
        {
            "description": (
                "Registra o pedido de reler os anexos e remontar a cronologia dos"
                " fatos, para o advogado confirmar. NÃO executa nada."
            ),
            "parameters": {
                "type": "object",
                "properties": {"motivo": {"type": "string"}},
            },
        },
        True,
    ),
    "propor_peca_anexa": (
        _propor_peca_anexa,
        {
            "description": (
                "Registra o pedido de redigir OUTRA peça do mesmo caso (as ações"
                " sugeridas pela análise), para o advogado confirmar. NÃO redige nada"
                " e não toca na petição inicial."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string"},
                    "motivo": {"type": "string"},
                    "pedidos": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["titulo"],
            },
        },
        True,
    ),
}


def esquemas() -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": {"name": nome, **esquema}}
        for nome, (_funcao, esquema, _altera) in CATALOGO.items()
    ]


def executar_ferramenta(
    nome: str, caso_id: str, argumentos: dict[str, Any]
) -> dict[str, Any]:
    """Roda a ferramenta pedida. Nome desconhecido é dado, não exceção.

    O modelo às vezes inventa um nome parecido com o de que precisa. Estourar aqui
    derrubaria a resposta inteira; devolver o erro como resultado faz ele se corrigir
    na rodada seguinte — e, se não se corrigir, o advogado lê que a consulta não
    existe em vez de ver a tela quebrar.
    """
    entrada = CATALOGO.get(nome)
    if entrada is None:
        return {"erro": f"Não existe a consulta «{nome}» neste chat."}
    funcao = entrada[0]
    try:
        return funcao(caso_id, **argumentos)
    except TypeError as erro:
        log.warning("chat da petição: argumentos inválidos para %s: %s", nome, erro)
        return {"erro": f"Argumentos inválidos para «{nome}»: {erro}"}
    except Exception as erro:  # noqa: BLE001 — falha de leitura vira dado, não 500
        log.exception("chat da petição: falha em %s", nome)
        return {"erro": f"A consulta «{nome}» falhou: {erro}"}



# ------------------------------------------------------------------- o modelo


def _configurado() -> tuple[str, str, str]:
    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not chave:
        raise ErroDoChat(
            "O chat da petição está desligado: falta DEEPSEEK_API_KEY no .env. Os"
            " botões de gerar, analisar e revisar continuam funcionando."
        )
    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    modelo = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    return chave, base, modelo


def _juntar_chamadas(acumulado: dict[int, dict[str, Any]], pedacos: list[Any]) -> None:
    """Remonta as chamadas de ferramenta que chegam picadas no fluxo.

    Em streaming o nome vem num pedaço e os argumentos em vários outros, todos
    identificados só pelo `index`. Sem esta remontagem, o que chega é uma lista de
    fragmentos de JSON que nenhum `json.loads` aceita.
    """
    for pedaco in pedacos or []:
        indice = int(pedaco.get("index") or 0)
        # `type` vai junto, e não é decoração: ao reenviar a mensagem do assistente na
        # rodada seguinte, a API RECUSA (400, "missing field `type`") a chamada montada
        # sem ele. O fluxo só manda esse campo no primeiro pedaço — ou em nenhum.
        atual = acumulado.setdefault(
            indice, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
        )
        if pedaco.get("type"):
            atual["type"] = pedaco["type"]
        if pedaco.get("id"):
            atual["id"] = pedaco["id"]
        funcao = pedaco.get("function") or {}
        if funcao.get("name"):
            atual["function"]["name"] = funcao["name"]
        if funcao.get("arguments"):
            atual["function"]["arguments"] += funcao["arguments"]


def _transmitir(mensagens: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Uma rodada com o modelo, em fluxo. Emite `delta` e termina em `mensagem`.

    As ferramentas vão em TODA rodada: é o que permite ao modelo consultar de novo
    depois de ler algo — "vi a pendência do valor, agora deixa eu ver o documento".
    """
    chave, base, modelo = _configurado()
    corpo = {
        "model": modelo,
        # Baixa, não zero: aqui se conversa. Zero deixava a resposta com a mesma
        # abertura sempre, e o advogado lia a terceira pergunta como eco da primeira.
        "temperature": 0.2,
        "messages": mensagens,
        "tools": esquemas(),
        "tool_choice": "auto",
        "stream": True,
    }

    texto: list[str] = []
    chamadas: dict[int, dict[str, Any]] = {}
    try:
        with httpx.stream(
            "POST",
            base + "/chat/completions",
            headers={"Authorization": f"Bearer {chave}"},
            json=corpo,
            timeout=TEMPO_DO_MODELO_S,
        ) as resposta:
            if resposta.status_code >= 400:
                resposta.read()
                log.warning(
                    "chat da petição: modelo recusou (%s): %s",
                    resposta.status_code,
                    resposta.text[:300],
                )
                raise ErroDoChat(
                    f"O modelo respondeu {resposta.status_code} e não escreveu a resposta."
                    " Tente de novo."
                )
            for linha in resposta.iter_lines():
                if not linha or not linha.startswith("data:"):
                    continue
                carga = linha[5:].strip()
                if carga == "[DONE]":
                    break
                try:
                    pedaco = json.loads(carga)
                except json.JSONDecodeError:
                    continue
                escolha = (pedaco.get("choices") or [{}])[0]
                delta = escolha.get("delta") or {}
                if delta.get("tool_calls"):
                    _juntar_chamadas(chamadas, delta["tool_calls"])
                    if texto:
                        # O modelo começou a escrever e mudou de ideia: vai consultar
                        # antes. O que já apareceu na tela não é a resposta, e deixá-lo
                        # ali faria a resposta final parecer uma segunda tentativa.
                        texto.clear()
                        yield {"tipo": "recomeco"}
                conteudo = delta.get("content")
                if conteudo:
                    texto.append(conteudo)
                    yield {"tipo": "delta", "texto": conteudo}
    except httpx.HTTPError as erro:
        log.warning("chat da petição: modelo não respondeu: %s", str(erro)[:200])
        raise ErroDoChat(
            "O modelo não respondeu a tempo. A conversa está salva — tente de novo."
        ) from erro

    yield {
        "tipo": "mensagem",
        "mensagem": {
            "role": "assistant",
            "content": "".join(texto),
            "tool_calls": [chamadas[i] for i in sorted(chamadas)],
        },
    }


#: O que a tela escreve enquanto a ferramenta roda. Escrito para quem lê, não para
#: o log: "consultando ler_minuta" não diz nada a um advogado.
ETAPAS = {
    "ler_minuta": "Lendo a minuta",
    "ler_analise": "Consultando a análise do caso",
    "ler_documentos": "Lendo os documentos anexados",
    "ler_entrevista": "Relendo a entrevista",
    "ler_historico": "Conferindo o histórico de versões",
    "pesquisar_na_web": "Pesquisando na web",
    "propor_revisao_da_peticao": "Preparando a alteração para você conferir",
    "propor_geracao_da_peticao": "Preparando a proposta de gerar a peça",
    "propor_analise_de_documentos": "Preparando a proposta de reler os anexos",
    "propor_peca_anexa": "Preparando a proposta da outra peça",
}


# ---------------------------------------------------------------- a transcrição


def _como_mensagem(registro: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": registro["id"],
        "papel": registro["papel"],
        "conteudo": registro["conteudo"],
        "natureza": registro["natureza"],
        "payload": registro.get("payload") or {},
        "criado_em": registro["criado_em"],
    }


def _garantir_conversa(caso_id: str, usuario: str) -> dict[str, Any]:
    """A conversa deste caso, desta pessoa. Criada na primeira vez e só nela."""
    conversa = armazenamento.conversa_do_caso(usuario, caso_id, escopo=ESCOPO)
    if conversa:
        return conversa
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise ErroDoChat("Esse caso não está mais no acervo.")
    cliente = str(caso.get("cliente") or "caso sem cliente")
    return armazenamento.criar_conversa(
        f"Petição — {cliente}",
        usuario=usuario,
        caso_id=caso_id,
        resumo="Chat da petição",
        escopo=ESCOPO,
    )


def abrir(caso_id: str, usuario: str) -> dict[str, Any]:
    """A conversa com o histórico inteiro — é o que o refresh da página reabre."""
    conversa = _garantir_conversa(caso_id, usuario)
    return {
        "id": conversa["id"],
        "caso_id": conversa["caso_id"],
        "criado_em": conversa["criado_em"],
        "atualizado_em": conversa["atualizado_em"],
        "mensagens": [
            _como_mensagem(m) for m in armazenamento.mensagens_da_conversa(conversa["id"])
        ],
        # A tela precisa saber se o modelo está ligado ANTES de alguém digitar: um
        # campo que aceita a pergunta e só depois diz "falta a chave no .env" é o
        # tipo de erro silencioso que este módulo existe para não repetir.
        "modelo_disponivel": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
        "web_disponivel": pesquisa_web_modulo.configurada(),
    }


def _historico_para_o_modelo(conversa_id: str) -> list[dict[str, str]]:
    """As últimas trocas, no vocabulário do modelo.

    Só o TEXTO volta — nunca as propostas nem as fontes de antes. A minuta atual
    entra pelo contexto a cada pergunta, e reaproveitar o texto de uma versão
    anterior como se fosse o de agora é a maneira mais silenciosa de responder
    sobre uma peça que já mudou.
    """
    recentes = armazenamento.mensagens_da_conversa(conversa_id)[-TROCAS_DE_CONTEXTO:]
    return [
        {
            "role": "user" if m["papel"] == "USER" else "assistant",
            "content": str(m["conteudo"])[:4000],
        }
        for m in recentes
        if str(m.get("conteudo") or "").strip()
    ]


def _registrar(
    conversa_id: str, texto: str, *, natureza: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    registro = armazenamento.registrar_mensagem(
        conversa_id,
        papel="ASSISTANT",
        conteudo=texto,
        natureza=natureza,
        payload=payload or {},
    )
    armazenamento.atualizar_conversa(conversa_id)
    return _como_mensagem(registro)


# ------------------------------------------------------------------ a conversa


def conversar(caso_id: str, pergunta: str, usuario: str) -> Iterator[dict[str, Any]]:
    """Responde a uma pergunta, em fluxo. Cada item é um evento para a tela.

    Os eventos: `conversa` (qual é, e a pergunta já gravada), `etapa` (o que está
    sendo consultado), `delta` (o texto chegando), `recomeco` (o parcial não vale
    mais), `fim` (a mensagem gravada, com fontes e propostas) e `erro`.

    A falha vira MENSAGEM na transcrição, e não só um código HTTP: o advogado
    precisa ver na conversa que a resposta não veio — do contrário a pergunta fica
    na tela sem retorno e ele não sabe se ela chegou a ser feita.
    """
    pergunta = " ".join(str(pergunta or "").split())
    if not pergunta:
        raise ErroDoChat("Escreva a sua pergunta.")
    conversa = _garantir_conversa(caso_id, usuario)
    conversa_id = conversa["id"]

    historico = _historico_para_o_modelo(conversa_id)
    registro_da_pergunta = armazenamento.registrar_mensagem(
        conversa_id, papel="USER", conteudo=pergunta, natureza="PERGUNTA"
    )
    yield {
        "tipo": "conversa",
        "conversa_id": conversa_id,
        "pergunta": _como_mensagem(registro_da_pergunta),
    }

    mensagens: list[dict[str, Any]] = [
        {"role": "system", "content": INSTRUCAO + "\n\n" + _contexto_do_caso(caso_id)},
        *historico,
        {"role": "user", "content": pergunta},
    ]

    fontes: list[dict[str, str]] = []
    acoes: list[dict[str, Any]] = []
    consultas: list[str] = []
    texto = ""

    try:
        for _passo in range(MAXIMO_DE_PASSOS):
            resposta: dict[str, Any] = {}
            for evento in _transmitir(mensagens):
                if evento["tipo"] == "mensagem":
                    resposta = evento["mensagem"]
                else:
                    yield evento
            texto = str(resposta.get("content") or "")
            chamadas = resposta.get("tool_calls") or []
            mensagens.append(resposta)
            if not chamadas:
                break

            for chamada in chamadas:
                nome = (chamada.get("function") or {}).get("name") or ""
                bruto = (chamada.get("function") or {}).get("arguments") or "{}"
                try:
                    argumentos = json.loads(bruto) if isinstance(bruto, str) else dict(bruto)
                except json.JSONDecodeError:
                    argumentos = {}
                    log.warning("chat da petição: argumentos ilegíveis em %s", nome)
                if not isinstance(argumentos, dict):
                    argumentos = {}

                yield {"tipo": "etapa", "texto": ETAPAS.get(nome, "Consultando o caso")}
                resultado = executar_ferramenta(nome, caso_id, argumentos)
                consultas.append(nome)

                vistas = {f["url"] for f in fontes}
                for fonte in resultado.get("fontes") or []:
                    if fonte.get("url") and fonte["url"] not in vistas:
                        fontes.append(fonte)
                        vistas.add(fonte["url"])
                if resultado.get("registrada"):
                    acoes.append({k: v for k, v in resultado.items() if k != "registrada"})

                mensagens.append(
                    {
                        "role": "tool",
                        "tool_call_id": chamada.get("id"),
                        "content": json.dumps(resultado, ensure_ascii=False, default=str),
                    }
                )
        else:
            # Esgotou o teto ainda consultando: pede o fechamento com o que houver,
            # em vez de deixar o advogado olhando "digitando" até o prazo estourar.
            mensagens.append(
                {
                    "role": "user",
                    "content": (
                        "Você atingiu o limite de consultas. Responda agora com o que"
                        " já apurou e diga o que ficou sem conferir."
                    ),
                }
            )
            for evento in _transmitir(mensagens):
                if evento["tipo"] == "mensagem":
                    texto = str(evento["mensagem"].get("content") or "")
                else:
                    yield evento
    except ErroDoChat as erro:
        yield _falha(conversa_id, str(erro), pergunta)
        return
    except Exception as erro:  # noqa: BLE001 — nada aqui pode virar 500 silencioso
        log.exception("chat da petição: falha inesperada no caso %s", caso_id)
        yield _falha(conversa_id, f"Não consegui responder agora: {erro}", pergunta)
        return

    if not texto.strip():
        texto = (
            "Não consegui formular a resposta desta vez. Reescreva a pergunta ou peça"
            " de outro jeito."
        )

    mensagem = _registrar(
        conversa_id,
        texto,
        natureza="RESPOSTA",
        payload={"fontes": fontes, "acoes": acoes, "consultas": consultas},
    )
    yield {"tipo": "fim", "mensagem": mensagem}


def _falha(conversa_id: str, texto: str, pergunta: str) -> dict[str, Any]:
    """A falha entra na transcrição com o que foi perguntado, para poder repetir."""
    mensagem = _registrar(
        conversa_id,
        texto,
        natureza="ERRO",
        payload={"pergunta": pergunta, "pode_repetir": True},
    )
    return {"tipo": "erro", "texto": texto, "mensagem": mensagem}


# ------------------------------------------------------- as ações confirmadas
#
# O outro lado da regra: aqui as coisas ACONTECEM, e só chegam aqui depois do
# clique de quem lê. Cada execução devolve uma mensagem para a transcrição —
# inclusive quando falha, porque "a peça não foi gerada" é informação, e não um
# código HTTP que some com o toast.


def _lista(itens: Any, teto: int = 6) -> str:
    valores = [str(i).strip() for i in (itens or []) if str(i).strip()]
    if not valores:
        return ""
    mostrados = valores[:teto]
    resto = len(valores) - len(mostrados)
    texto = "; ".join(mostrados)
    return texto + (f" (e mais {resto})" if resto > 0 else "")


def _resumo_da_minuta(caso_id: str) -> tuple[int, list[str]]:
    peticao = peticao_local.carregar(caso_id) or {}
    pendencias = (peticao.get("readiness") or {}).get("pendencias") or []
    return int(peticao.get("version") or 0), [str(p) for p in pendencias]


def _executar(caso_id: str, autor: str, acao: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Faz o que a proposta pedia e escreve, em português, o que aconteceu."""
    tipo = str(acao.get("tipo") or "").upper()

    if tipo == "REVISAR":
        pedido = str(acao.get("pedido") or "").strip()
        if not pedido:
            raise ErroDoChat("A proposta não diz o que deve mudar na petição.")
        # `generaliza=False`: o pedido feito no chat vale para ESTE caso. Ensinar a
        # IA com ele é decisão à parte, que o campo de revisão do painel oferece
        # com a caixa marcada — aqui a conversa é rápida e ninguém leu essa
        # consequência antes de apertar "confirmar".
        resultado = peticao_fluxo.revisar_peticao(
            caso_id, prompt=pedido, usuario=autor, generaliza=False, origem="chat"
        )
        peticao = resultado.get("peticao") or {}
        revisao = peticao.get("revisao") or resultado.get("revisao") or {}
        pendente = peticao.get("revisao_pendente") or None
        if pendente:
            texto = (
                f"Preparei a alteração que você confirmou: «{pedido}».\n\n"
                "A comparação está aberta ao lado, com o texto que sai marcado em"
                " vermelho e o que entra em verde. **A peça oficial continua na versão"
                f" {peticao.get('version')}** — ela só muda quando você aceitar a"
                " comparação."
            )
            alteradas = _lista(revisao.get("alteradas"))
            if alteradas:
                texto += f"\n\nSeções tocadas: {alteradas}."
            perguntas = _lista(revisao.get("perguntas"))
            if perguntas:
                texto += f"\n\nAntes de aceitar, confirme comigo: {perguntas}"
            return texto, {"peticao_id": peticao.get("id"), "revisao_id": pendente.get("id")}

        perguntas = _lista(revisao.get("perguntas"))
        texto = (
            "Não encontrei uma alteração segura para esse pedido, então **nada foi"
            " mudado** e nenhuma versão nova foi criada."
        )
        if perguntas:
            texto += f"\n\nPrecisaria saber: {perguntas}"
        return texto, {"alterou": False}

    if tipo == "GERAR":
        resultado = peticao_fluxo.gerar_completo(caso_id)
        peticao = resultado.get("peticao") or {}
        pendencias = (peticao.get("readiness") or {}).get("pendencias") or []
        texto = (
            f"Gerei a petição a partir da entrevista e dos documentos: agora é a"
            f" **versão {peticao.get('version')}**, com"
            f" {len(peticao.get('sections') or [])} seções. A versão anterior ficou no"
            " histórico."
        )
        if pendencias:
            texto += (
                "\n\nContinuam sem comprovação documental: "
                + _lista(pendencias)
                + ".\n\nQuer que eu procure esses pontos nos anexos ou que eu os marque"
                " como pendentes no texto?"
            )
        return texto, {"peticao_id": peticao.get("id"), "versao": peticao.get("version")}

    if tipo == "ANALISAR_DOCUMENTOS":
        analise = analise_documentos.analisar(caso_id)
        achados = analise.get("achados") or []
        if analise.get("aviso"):
            return str(analise["aviso"]), {"achados": 0}
        texto = (
            f"Reli os anexos e remontei a cronologia: {analise.get('documentos_lidos', 0)}"
            f" documento(s) lido(s) e {len(achados)} acontecimento(s) datado(s) com o"
            " trecho que comprova cada um. A linha do tempo está no painel de"
            " documentos, acima. Nada na minuta foi alterado."
        )
        recusados = int(analise.get("recusados") or 0)
        if recusados:
            texto += (
                f"\n\n{recusados} achado(s) foram descartados por não conferir com o"
                " texto do documento apontado."
            )
        return texto, {"achados": len(achados)}

    if tipo == "PECA_ANEXA":
        titulo = str(acao.get("titulo") or "").strip()
        if not titulo:
            raise ErroDoChat("A proposta não diz qual peça deve ser redigida.")
        entrevista = peticao_fluxo.transcricao(caso_id)
        peca = peticao_local.gerar_anexa(
            caso_id,
            titulo=titulo,
            motivo=str(acao.get("motivo") or ""),
            pedidos=[str(p) for p in (acao.get("pedidos") or [])],
            texto_entrevista=entrevista["texto"],
            gerada_por=autor,
        )
        texto = (
            f"Redigi a peça «{titulo}». Ela está em «Outras peças deste caso», abaixo da"
            " minuta, pronta para conferir, editar e baixar. **A petição inicial não foi"
            " tocada.**"
        )
        pendencias = (peca.get("readiness") or {}).get("pendencias") or []
        if pendencias:
            texto += "\n\nPendente nesta peça: " + _lista(pendencias) + "."
        return texto, {"peca_id": peca.get("id"), "titulo": titulo}

    raise ErroDoChat(f"Não sei executar a ação «{tipo}».")


def executar_acao(
    caso_id: str, usuario: str, acao: dict[str, Any], *, autor: str = ""
) -> dict[str, Any]:
    """Executa uma proposta aceita e grava o resultado na conversa.

    `usuario` é o DONO da conversa (o identificador da sessão) e `autor` é o nome que
    vai para a rastreabilidade da peça. São coisas diferentes: o histórico de edição
    é lido por gente, e "a0f3-91bc" ali não diz quem pediu a mudança.

    Nunca levanta por falha da ação: a falha vira mensagem com `pode_repetir`, que é
    o que permite à tela oferecer "tentar de novo" sem perder o que foi pedido.
    """
    conversa = _garantir_conversa(caso_id, usuario)
    try:
        texto, extra = _executar(caso_id, autor or usuario, acao)
    except (ErroDoChat, ErroDoAgente, peticao_local.ErroPeticao) as erro:
        mensagem = _registrar(
            conversa["id"],
            f"A ação não foi concluída: {erro}",
            natureza="ERRO",
            payload={"acao": acao, "pode_repetir": True},
        )
        return {"ok": False, "mensagem": mensagem}
    except Exception as erro:  # noqa: BLE001 — falha de ação não pode virar 500 mudo
        log.exception("chat da petição: ação %s falhou no caso %s", acao.get("tipo"), caso_id)
        mensagem = _registrar(
            conversa["id"],
            f"A ação não foi concluída: {erro}",
            natureza="ERRO",
            payload={"acao": acao, "pode_repetir": True},
        )
        return {"ok": False, "mensagem": mensagem}

    mensagem = _registrar(
        conversa["id"],
        texto,
        natureza="EVENTO",
        payload={"acao": acao, "origem": "chat", **extra},
    )
    return {"ok": True, "mensagem": mensagem}


# -------------------------------------------------------- a IA falando sozinha
#
# O que os BOTÕES fazem também chega aqui. Sem isto, o advogado clicava em
# "Analisar documentos" no painel e o chat ao lado continuava falando da peça
# anterior, como se nada tivesse acontecido — e é justamente depois de uma ação
# que ele mais precisa saber o que mudou e o que ficou sem prova.


def _texto_do_evento(caso_id: str, tipo: str, dados: dict[str, Any]) -> str:
    versao, pendencias = _resumo_da_minuta(caso_id)

    if tipo == "peticao_gerada":
        texto = (
            f"Terminei de gerar a petição — agora é a **versão {versao}**. A anterior"
            " ficou no histórico de edição."
        )
        if pendencias:
            texto += (
                "\n\nEstes pontos continuam sem comprovação documental: "
                + _lista(pendencias)
                + ".\n\nQuer que eu marque cada um como pendente no texto ou que eu"
                " procure o comprovante nos anexos?"
            )
        else:
            texto += (
                "\n\nNenhum ponto ficou marcado como sem comprovação — ainda assim,"
                " confira os valores e as datas antes de protocolar."
            )
        return texto

    if tipo == "documentos_analisados":
        lidos = int(dados.get("documentos_lidos") or 0)
        achados = int(dados.get("achados") or 0)
        return (
            f"Terminei de ler os anexos: {lidos} documento(s) e {achados}"
            " acontecimento(s) datados na cronologia, cada um com o trecho que o"
            " comprova. A minuta não foi alterada. Se algum desses fatos precisar"
            " entrar na peça, me diga qual."
        )

    if tipo == "revisao_proposta":
        pedido = str(dados.get("pedido") or "").strip()
        texto = (
            "Preparei a revisão que você pediu no painel"
            + (f" — «{pedido}»" if pedido else "")
            + ". A comparação está aberta sobre o documento: o que sai vem riscado em"
            f" vermelho, o que entra vem em verde. A peça oficial continua na versão"
            f" {versao} até você aceitar."
        )
        alteradas = _lista(dados.get("alteradas"))
        if alteradas:
            texto += f"\n\nSeções tocadas: {alteradas}."
        return texto

    if tipo == "revisao_aceita":
        texto = f"Revisão aceita e gravada: a peça agora é a **versão {versao}**."
        pedido = str(dados.get("pedido") or "").strip()
        if pedido:
            texto += f" Ela nasceu do pedido «{pedido}»."
        texto += " O registro ficou no histórico de edição, com autor, data e pedido."
        if pendencias:
            texto += "\n\nSem comprovação documental: " + _lista(pendencias) + "."
        return texto

    if tipo == "revisao_descartada":
        return (
            "Revisão descartada — a peça continua na versão"
            f" {versao}, exatamente como estava. O descarte ficou registrado."
        )

    if tipo == "peca_anexa_gerada":
        titulo = str(dados.get("titulo") or "a peça pedida")
        return (
            f"Redigi «{titulo}» a partir do mesmo material. Ela está em «Outras peças"
            " deste caso» e a petição inicial não foi tocada."
        )

    if tipo == "versao_salva":
        formato = str(dados.get("formato") or "docx")
        return (
            f"Salvei suas edições — a peça agora é a **versão {versao}** — e baixei o"
            f" arquivo .{formato}. A edição manual também entra no histórico."
        )

    if tipo == "falha":
        acao = str(dados.get("acao") or "a última ação")
        erro = str(dados.get("erro") or "sem detalhe do servidor")
        return (
            f"**{acao}** não foi concluída: {erro}\n\nVocê pode tentar de novo pelo"
            " botão, ou me pedir aqui que eu preparo de outro jeito."
        )

    return ""


def registrar_evento(
    caso_id: str, usuario: str, tipo: str, dados: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """A IA contando, na conversa, o que uma ação da tela acabou de fazer.

    Devolve `None` para evento que não tem texto: melhor não dizer nada do que
    encher a transcrição com "algo aconteceu".
    """
    dados = dados or {}
    texto = _texto_do_evento(caso_id, str(tipo or ""), dados)
    if not texto:
        return None
    conversa = _garantir_conversa(caso_id, usuario)
    return _registrar(
        conversa["id"],
        texto,
        natureza="ERRO" if tipo == "falha" else "EVENTO",
        payload={"evento": tipo, "origem": "painel", **dados},
    )
