"""O que o agente analista pode consultar — e o que cada consulta comprova.

Este módulo é a resposta a "de onde veio esse número". Ele não pensa: cada ferramenta é
uma **leitura determinística** do que o escritório já apurou, com os mesmos cálculos que
as telas usam. O modelo escolhe qual chamar e escreve a frase; medir é aqui.

A separação existe por um motivo que atravessa o produto inteiro: uma contagem inventada
sobre o acervo é a falácia mais fácil de produzir e a mais difícil de perceber — "três
casos estão parados" soa igual esteja certo ou errado. Se a medição fosse do modelo, o
guardrail de lastro não teria o que conferir.

**Toda ferramenta devolve, junto do dado, as REFERÊNCIAS que ela comprova** (`refs`):
`caso:<id>`, `entrevista:<id>`, `documento:<id>`, `panorama`, `jurimetria`, `sistema:<verbete>`.
São elas que o guardrail de `analista.py` aceita numa afirmação, e são elas que a tela
transforma em "abrir no dossiê". Uma afirmação que cite o que nenhuma ferramenta
devolveu não passa.

Os resultados vão RESUMIDOS ao modelo. `panorama.montar()` sozinho traz o acervo inteiro,
e enfiar isso numa janela de contexto custa caro e piora a resposta — o modelo perde o
que importa no meio da lista. Cada ferramenta corta no que responde à pergunta dela e
diz quanto ficou de fora.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import armazenamento
from . import conversa_geral, dossie
from .cliente import Cliente, ErroDoAgente

log = logging.getLogger("agente")

__all__ = ["CATALOGO", "Resultado", "esquemas", "executar"]


@dataclass
class Resultado:
    """O que a ferramenta devolveu, e o que isso comprova.

    `refs` é o que o guardrail vai aceitar como lastro; `dados` é o que o modelo lê.
    Uma ferramenta que não achou nada devolve `dados` dizendo isso e `refs` vazio — a
    ausência é resultado, não erro, e é ela que faz o modelo dizer "não há" em vez de
    tentar outra ferramenta até achar algo que pareça resposta.
    """

    dados: dict[str, Any]
    refs: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class Ferramenta:
    nome: str
    #: O texto que o MODELO lê para decidir se é esta que responde. Escrito para ele:
    #: diz o que a ferramenta mede e, principalmente, o que ela NÃO alcança.
    descricao: str
    parametros: dict[str, Any]
    executar: Callable[..., Resultado]


# O `panorama` NÃO entra no import lá de cima, e isso não é estilo: `app/painel.py`
# importa o pacote `agente`, cujo `__init__` carrega as rotas — que chegam até aqui. E
# `app/panorama.py` copia onze utilitários do painel em tempo de import (`_instante`,
# `_iso`, os limiares), de propósito, para não haver duas conversões da mesma data. Com
# `panorama` no topo daqui, o ciclo painel → agente → panorama → painel se fecha: o
# painel ainda está a meio carregar quando o alias é avaliado, e o import morre em
# `AttributeError: partially initialized module`. Adiar para dentro da função desfaz o
# ciclo sem desfazer o compartilhamento.
def _montar_panorama():
    from .. import panorama

    return panorama.montar()


# --------------------------------------------------------------------- acervo


def _panorama_do_escritorio() -> Resultado:
    """Como o escritório inteiro está — os mesmos números da tela Panorama."""
    tudo = _montar_panorama()
    parados = tudo["parados"]
    return Resultado(
        dados={
            "cobertura": tudo["cobertura"],
            "indicadores": tudo["indicadores"],
            "funil": tudo["funil"],
            "tempo": tudo["tempo"],
            "categorias": tudo["categorias"][:8],
            "parados": {
                "total": parados["total"],
                "limiar_dias": parados["limiar_dias"],
                "itens": [
                    {
                        "caso_id": item["id"],
                        "cliente": item["cliente"],
                        "estagio": item["estagio_titulo"],
                        "dias_sem_movimentacao": item["dias"],
                    }
                    for item in parados["itens"]
                ],
            },
            "movimento": tudo["movimento"],
            # O que o panorama declaradamente NÃO mede vai junto: sem isto o modelo
            # preenche a lacuna com o que parece razoável.
            "nao_medido": tudo["ausencias"],
            "medido_em": tudo["gerado_em"],
        },
        refs={"panorama"} | {f"caso:{item['id']}" for item in parados["itens"]},
    )


#: Quantos casos cabem numa resposta antes de a lista deixar de informar.
_TETO_DA_LISTA = 25


def _listar_casos(
    termo: str = "",
    categoria: str = "",
    estagio: str = "",
    parados_ha_dias: int | None = None,
    limite: int = _TETO_DA_LISTA,
) -> Resultado:
    """Os casos do acervo que atendem aos filtros, com estágio e tempo sem movimentação.

    Filtra sobre a MESMA medição do panorama — não sobre uma consulta paralela. Duas
    leituras tiradas em instantes diferentes fariam a contagem do funil deixar de bater
    com a lista que ela abre, e não há como o advogado saber qual das duas está certa.
    """
    tudo = _montar_panorama()
    procurado = conversa_geral.normalizar(termo)
    categoria_procurada = conversa_geral.normalizar(categoria)
    estagio_procurado = conversa_geral.normalizar(estagio)

    achados: list[dict[str, Any]] = []
    for caso in tudo["casos"]:
        if procurado and procurado not in conversa_geral.normalizar(caso["cliente"]):
            continue
        if categoria_procurada and categoria_procurada not in conversa_geral.normalizar(
            caso["categoria"]
        ):
            continue
        if estagio_procurado and estagio_procurado not in conversa_geral.normalizar(
            f"{caso['estagio']} {caso['estagio_titulo']}"
        ):
            continue
        if parados_ha_dias is not None and (caso["dias_sem_movimentacao"] or 0) < parados_ha_dias:
            continue
        achados.append(
            {
                "caso_id": caso["id"],
                "cliente": caso["cliente"],
                "categoria": caso["categoria"],
                "estagio": caso["estagio_titulo"],
                "aberto_em": caso["aberto_em"],
                "dias_sem_movimentacao": caso["dias_sem_movimentacao"],
                "parado": caso["parado"],
                "instruido": caso["instruido"],
            }
        )

    teto = max(1, min(int(limite or _TETO_DA_LISTA), _TETO_DA_LISTA))
    mostrados = achados[:teto]
    return Resultado(
        dados={
            "encontrados": len(achados),
            "mostrando": len(mostrados),
            # A contagem TOTAL vai separada da lista de propósito: responder "quantos
            # casos…" com o tamanho da lista truncada seria errar por corte de tela.
            "casos": mostrados,
            "filtros_aplicados": {
                "termo": termo,
                "categoria": categoria,
                "estagio": estagio,
                "parados_ha_dias": parados_ha_dias,
            },
        },
        refs={f"caso:{caso['caso_id']}" for caso in mostrados},
    )


# ----------------------------------------------------------------------- caso


def _dossie_do_caso(caso_id: str) -> Resultado:
    """Tudo que o escritório sabe de UM caso, dos dois lados da ponte.

    `recuperar=False` não é detalhe: abrir o dossiê na TELA recria o caso no agente
    quando ele sumiu de lá, porque é isso que o advogado quer ao clicar. Aqui não — uma
    pergunta pode abrir dez casos, e uma consulta que ESCREVE no outro sistema
    (recriando caso e reenviando documentos) transformaria "quantos casos estão parados?"
    numa sincronização em massa que ninguém pediu.
    """
    montado = dossie.montar(caso_id, recuperar=False)
    if montado is None:
        return Resultado(dados={"erro": "Esse caso não está no acervo.", "caso_id": caso_id})

    agente = montado.get("agente") or {}
    checklist = montado.get("checklist") or {}
    faltando = [
        item["rotulo"]
        for item in checklist.get("itens") or []
        if item.get("obrigatorio") and item.get("status") != "ok"
    ]

    return Resultado(
        dados={
            "caso_id": caso_id,
            "cliente": (montado.get("caso") or {}).get("cliente"),
            "categoria": checklist.get("categoria"),
            "aberto_em": (montado.get("caso") or {}).get("criado_em"),
            "contrato": montado.get("contrato"),
            "checklist": {
                "progresso": checklist.get("progresso"),
                "obrigatorios_faltando": faltando,
            },
            "entrevistas": [
                {
                    "id": e.get("id"),
                    "realizada_em": e.get("realizada_em"),
                    "resumo": e.get("resumo"),
                    "fatos_gerados": e.get("fatos_gerados"),
                    "lida_pelo_agente": e.get("enviada"),
                }
                for e in montado.get("entrevistas") or []
            ],
            "agente": {
                "vinculado": agente.get("vinculado"),
                "indisponivel": agente.get("motivo"),
                # O fato vai com o ESTADO: `ALLEGED` é o que o cliente relatou e nenhum
                # documento comprova. Achatar isso faria relato e prova chegarem com o
                # mesmo peso — que é o erro que este sistema inteiro existe para evitar.
                "fatos": [
                    {
                        "id": f.get("id"),
                        "tipo": f.get("type"),
                        "estado": f.get("status"),
                        "valor": f.get("value"),
                    }
                    for f in (agente.get("fatos") or [])[:40]
                ],
                "classificacoes": [
                    {"codigo": c.get("code"), "rotulo": c.get("label"), "estado": c.get("status")}
                    for c in agente.get("classificacoes") or []
                ],
                "pendencias": [
                    {"codigo": p.get("code"), "rotulo": p.get("label"), "estado": p.get("status")}
                    for p in agente.get("pendencias") or []
                ],
                "peticoes": [
                    {"id": p.get("id"), "estado": p.get("status")}
                    for p in agente.get("peticoes") or []
                ],
                "pesquisas": len(agente.get("pesquisas") or []),
            },
        },
        refs={f"caso:{caso_id}"}
        | {f"fato:{f['id']}" for f in (agente.get("fatos") or []) if f.get("id")},
    )


def _documentos_do_caso(caso_id: str) -> Resultado:
    """O que o cliente entregou, o que o OCR leu e o que ainda falta."""
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        return Resultado(dados={"erro": "Esse caso não está no acervo.", "caso_id": caso_id})

    entregas = armazenamento.listar_entregas(caso_id)
    return Resultado(
        dados={
            "caso_id": caso_id,
            "cliente": caso.get("cliente"),
            "total": len(entregas),
            "entregas": [
                {
                    "id": e.get("id"),
                    "item": e.get("item_codigo"),
                    "arquivo": e.get("arquivo"),
                    "tipo_detectado": e.get("tipo_detectado"),
                    "tipo_confere": e.get("tipo_confere"),
                    "dados_utilizaveis": e.get("dados_utilizaveis"),
                    "recebido_em": e.get("criado_em"),
                }
                for e in entregas[:40]
            ],
        },
        refs={f"caso:{caso_id}"} | {f"documento:{e['id']}" for e in entregas[:40] if e.get("id")},
    )


#: Quanto da transcrição vai ao modelo de uma vez.
#:
#: Entrevista inteira são dezenas de milhares de caracteres, e mandá-la para responder
#: "o que o cliente falou sobre o acidente?" gasta a janela toda com saudação e
#: encerramento. O resumo responde a maioria; o texto vem quando pedido.
_TRECHO_DA_ENTREVISTA = 6000


def _entrevistas_do_caso(caso_id: str, com_texto: bool = False) -> Resultado:
    """O atendimento como ele foi conduzido: resumo, e o texto quando preciso."""
    entrevistas = armazenamento.listar_entrevistas(caso_id)
    if not entrevistas:
        return Resultado(
            dados={"caso_id": caso_id, "total": 0, "entrevistas": [],
                   "observacao": "Este caso não tem entrevista guardada."},
            refs={f"caso:{caso_id}"},
        )

    itens = []
    for registro in entrevistas:
        completo = armazenamento.obter_entrevista(registro["id"]) if com_texto else None
        texto = str((completo or {}).get("texto") or "")
        itens.append(
            {
                "id": registro["id"],
                "realizada_em": registro.get("realizada_em"),
                "entrevistador": registro.get("entrevistador"),
                "resumo": registro.get("resumo"),
                "fatos_gerados": registro.get("fatos_gerados"),
                **(
                    {
                        "texto": texto[:_TRECHO_DA_ENTREVISTA],
                        "texto_truncado": len(texto) > _TRECHO_DA_ENTREVISTA,
                    }
                    if com_texto
                    else {}
                ),
            }
        )

    return Resultado(
        dados={"caso_id": caso_id, "total": len(itens), "entrevistas": itens},
        refs={f"caso:{caso_id}"} | {f"entrevista:{i['id']}" for i in itens},
    )


# ----------------------------------------------------------------- jurimetria


def _jurimetria_do_acervo(orgao: str = "") -> Resultado:
    """Como o foro decide a matéria — do lado do agente jurídico, não daqui.

    Falha do agente vira RESULTADO, e não exceção: a resposta do analista continua
    valendo com as outras ferramentas, e a indisponibilidade é dita em vez de virar
    silêncio que o modelo preencheria sozinho.
    """
    try:
        bruto = Cliente().jurimetria_do_acervo({"orgao": orgao} if orgao else None)
    except ErroDoAgente as erro:
        log.warning("jurimetria do acervo indisponível: %s", erro)
        return Resultado(
            dados={
                "indisponivel": True,
                "motivo": str(erro),
                "observacao": "Sem isto, não há como afirmar como o foro decide.",
            }
        )
    return Resultado(dados=bruto, refs={"jurimetria"})


# -------------------------------------------------------------------- sistema


def _glossario_do_sistema(termo: str) -> Resultado:
    """O que uma palavra do produto significa — texto escrito à mão, não consulta.

    Existe como ferramenta para que o modelo tenha de onde tirar a explicação em vez de
    deduzi-la do nome. "Fato alegado" tem definição exata neste sistema, e uma definição
    plausível inventada pelo modelo seria pior que não responder.
    """
    verbete = conversa_geral.verbete_para(termo)
    if verbete is None:
        return Resultado(
            dados={
                "encontrado": False,
                "termo": termo,
                "verbetes_disponiveis": [v.titulo for v in conversa_geral.GLOSSARIO],
            }
        )
    return Resultado(
        dados={
            "encontrado": True,
            "titulo": verbete.titulo,
            "texto": verbete.texto,
            "origem": "texto do próprio sistema, não consulta ao acervo",
        },
        refs={f"sistema:{verbete.codigo}"},
    )


# ------------------------------------------------------------------- catálogo


CATALOGO: dict[str, Ferramenta] = {
    "panorama_do_escritorio": Ferramenta(
        nome="panorama_do_escritorio",
        descricao=(
            "Como o escritório inteiro está AGORA: quantos casos, em que estágio cada um "
            "está (funil), quantos estão parados e há quantos dias, tempo de ciclo, "
            "categorias e movimento dos últimos meses. Use para qualquer pergunta que "
            "atravesse vários casos ('quantos casos temos', 'o que está travado', 'como "
            "estamos'). NÃO traz valor de causa, prazo processual nem honorários — o "
            "campo `nao_medido` diz o que fica de fora."
        ),
        parametros={"type": "object", "properties": {}},
        executar=_panorama_do_escritorio,
    ),
    "listar_casos": Ferramenta(
        nome="listar_casos",
        descricao=(
            "Os casos que atendem a filtros, com estágio e dias sem movimentação. Use "
            "para achar o caso de um cliente pelo nome (`termo`), para recortar por "
            "`categoria` ou `estagio`, ou para listar os parados há N dias. Devolve "
            "`encontrados` (o total) separado de `casos` (a lista, que pode vir cortada) "
            "— para contar, use `encontrados`."
        ),
        parametros={
            "type": "object",
            "properties": {
                "termo": {
                    "type": "string",
                    "description": "Parte do nome do cliente. Vazio traz todos.",
                },
                "categoria": {"type": "string", "description": "Ex.: acidente_trabalho."},
                "estagio": {
                    "type": "string",
                    "description": "Ex.: coleta, conferência, instrução, entrevista.",
                },
                "parados_ha_dias": {
                    "type": "integer",
                    "description": "Só casos sem movimentação há pelo menos N dias.",
                },
                "limite": {"type": "integer", "description": f"Até {_TETO_DA_LISTA}."},
            },
        },
        executar=_listar_casos,
    ),
    "dossie_do_caso": Ferramenta(
        nome="dossie_do_caso",
        descricao=(
            "Tudo de UM caso: cadastro, contrato, progresso do checklist e o que falta, "
            "entrevistas resumidas, e o que o agente jurídico apurou — fatos com o "
            "ESTADO de cada um (ALLEGED = relatado pelo cliente e ainda sem prova; "
            "EXTRACTED/CONFIRMED = veio de documento), classificação, pendências do "
            "playbook e petições. Use para resumir um caso ou dizer o que falta nele. "
            "Precisa do `caso_id` — obtenha em `listar_casos` se só souber o nome."
        ),
        parametros={
            "type": "object",
            "properties": {"caso_id": {"type": "string"}},
            "required": ["caso_id"],
        },
        executar=_dossie_do_caso,
    ),
    "documentos_do_caso": Ferramenta(
        nome="documentos_do_caso",
        descricao=(
            "Os arquivos que o cliente entregou num caso, com o tipo que o OCR detectou "
            "e se a leitura serviu. Use quando a pergunta for sobre documentos "
            "recebidos, cobrança de documento ou qualidade do que chegou."
        ),
        parametros={
            "type": "object",
            "properties": {"caso_id": {"type": "string"}},
            "required": ["caso_id"],
        },
        executar=_documentos_do_caso,
    ),
    "entrevistas_do_caso": Ferramenta(
        nome="entrevistas_do_caso",
        descricao=(
            "As entrevistas guardadas de um caso. Sem `com_texto`, devolve o resumo de "
            "cada uma — costuma bastar. Com `com_texto=true`, devolve a transcrição "
            "(cortada), para quando a pergunta for sobre o que exatamente foi dito. "
            "Lembre-se: o que o cliente CONTOU é alegação, não prova."
        ),
        parametros={
            "type": "object",
            "properties": {
                "caso_id": {"type": "string"},
                "com_texto": {"type": "boolean"},
            },
            "required": ["caso_id"],
        },
        executar=_entrevistas_do_caso,
    ),
    "jurimetria_do_acervo": Ferramenta(
        nome="jurimetria_do_acervo",
        descricao=(
            "Como o foro vem decidindo a matéria, medido sobre o acervo de "
            "jurisprudência do agente jurídico. Use para 'como o TRT decide', 'qual a "
            "chance', 'o que costuma ser deferido'. Pode responder indisponível — se "
            "responder, não invente o número."
        ),
        parametros={
            "type": "object",
            "properties": {"orgao": {"type": "string", "description": "Ex.: TRT8."}},
        },
        executar=_jurimetria_do_acervo,
    ),
    "glossario_do_sistema": Ferramenta(
        nome="glossario_do_sistema",
        descricao=(
            "O que um termo do PRODUTO significa: fato alegado, pendência, dossiê, "
            "readiness, checklist, entrevista guiada. Use sempre que a pergunta for "
            "sobre como o sistema funciona — a definição exata está aqui, e deduzi-la "
            "do nome produz explicação plausível e errada."
        ),
        parametros={
            "type": "object",
            "properties": {"termo": {"type": "string"}},
            "required": ["termo"],
        },
        executar=_glossario_do_sistema,
    ),
}


def esquemas() -> list[dict[str, Any]]:
    """O catálogo no formato que a API de modelos espera (`tools`)."""
    return [
        {
            "type": "function",
            "function": {
                "name": f.nome,
                "description": f.descricao,
                "parameters": f.parametros,
            },
        }
        for f in CATALOGO.values()
    ]


def executar(nome: str, argumentos: dict[str, Any]) -> Resultado:
    """Roda a ferramenta pedida. Erro dela vira dado, nunca exceção.

    O modelo precisa PODER errar o nome ou o argumento e receber isso de volta em texto:
    é assim que ele corrige na rodada seguinte. Deixar a exceção subir derrubaria a
    conversa inteira por causa de uma chamada mal formada.
    """
    ferramenta = CATALOGO.get(nome)
    if ferramenta is None:
        return Resultado(
            dados={
                "erro": f"Não existe ferramenta chamada '{nome}'.",
                "disponiveis": sorted(CATALOGO),
            }
        )
    try:
        return ferramenta.executar(**(argumentos or {}))
    except TypeError as erro:
        return Resultado(dados={"erro": f"Argumentos inválidos para '{nome}': {erro}"})
    except Exception as erro:  # noqa: BLE001 - a falha é dita, e não engolida
        log.warning("ferramenta %s falhou: %s", nome, erro, exc_info=True)
        return Resultado(
            dados={
                "erro": f"A consulta '{nome}' falhou: {erro}",
                "observacao": "Sem este dado, não afirme o que ele responderia.",
            }
        )
