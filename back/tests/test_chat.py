"""O chat do escritório: para onde vai cada pergunta, e o que a resposta abre.

Sem banco e sem rede. O que se prova aqui é a parte determinística — a decisão de
destino (`app/chat/destinos.py`), o texto dos documentos (`app/chat/documentos.py`) e os
atalhos (`app/chat/atalhos.py`). É justamente a parte que precisa continuar valendo
amanhã: os três serviços que respondem já têm testes próprios, e o que este módulo
acrescenta é a escolha entre eles.

    .venv\\Scripts\\python.exe -m tests.test_chat
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.chat import atalhos, destinos  # noqa: E402
from app.chat import documentos as documentos_do_chat  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str) -> None:
    global falhas
    print(f"   {'OK  ' if condicao else 'FALHA'} {descricao}")
    if not condicao:
        falhas += 1


#: Um acervo pequeno, com nomes que não se confundem: aqui o que se prova é o DESTINO da
#: pergunta, e um nome ambíguo mandaria tudo para a lista de escolha antes disso.
CASOS = [
    {
        "id": "caso-maria",
        "cliente": "Maria Silva Santos",
        "categoria": "acidente_trabalho",
        "criado_em": "2026-09-01T10:00:00+00:00",
    },
    {
        "id": "caso-joao",
        "cliente": "João Pereira Lima",
        "categoria": "rescisao",
        "criado_em": "2026-08-20T10:00:00+00:00",
    },
]

#: O acervo como ele é de verdade: a mesma pessoa com dois processos. É o que faz a
#: pergunta virar pergunta de volta.
CASOS_AMBIGUOS = CASOS + [
    {
        "id": "caso-maria-2",
        "cliente": "Maria Silva Santos",
        "categoria": "rescisao",
        "criado_em": "2026-09-10T10:00:00+00:00",
    },
]


print("\n1. O comando escrito escolhe o destino, e some da pergunta")
modo, texto = destinos.separar_comando("/web prazo prescricional do acidente")
checar(modo == destinos.WEB, "`/web` pede a internet")
checar(texto == "prazo prescricional do acidente", "o comando não vai junto para a busca")

modo, texto = destinos.separar_comando("como funciona o /web daqui?")
checar(modo == "AUTO", "`/web` no meio da frase é texto, não comando")
checar(texto == "como funciona o /web daqui?", "e a pergunta chega inteira")

modo, _ = destinos.separar_comando("/doc da Maria Silva Santos")
checar(modo == destinos.DOCUMENTOS, "`/doc` pede os documentos do caso")


print("\n2. A pergunta sobre o mundo vai para a web")
for frase in (
    "pesquise na internet o entendimento do TST sobre adicional de insalubridade",
    "o que diz a súmula 331?",
    "qual o prazo prescricional para acidente de trabalho",
    "o que diz a NR-12 sobre proteção de máquinas",
):
    destino = destinos.decidir(frase, CASOS)
    checar(destino.natureza == destinos.WEB, f"{frase[:44]}... -> WEB")


print("\n3. A pergunta sobre um caso NÃO vai para a web, mesmo citando a lei")
destino = destinos.decidir(
    "o que diz a CAT do caso da Maria Silva Santos?", CASOS
)
checar(
    destino.natureza != destinos.WEB,
    "o caso citado segura a pergunta dentro do acervo",
)
checar(destino.caso_id == "caso-maria", "e ela vai para o caso certo")


print("\n4. Documentos: só com caso, e só quando é a papelada do cliente")
destino = destinos.decidir("quais documentos o caso da Maria Silva Santos tem?", CASOS)
checar(destino.natureza == destinos.DOCUMENTOS, "papelada de um caso -> DOCUMENTOS")
checar(destino.caso_id == "caso-maria", "do caso citado")

destino = destinos.decidir("quais documentos faltam?", CASOS, caso_fixado="caso-joao")
checar(
    destino.natureza == destinos.DOCUMENTOS and destino.caso_id == "caso-joao",
    "sem citar ninguém, vale o caso da sessão",
)

destino = destinos.decidir("onde fica a documentação do sistema?", CASOS)
checar(
    destino.natureza != destinos.DOCUMENTOS,
    "documentação DO SISTEMA não é a papelada de um cliente",
)

destino = destinos.decidir("quais documentos faltam?", CASOS)
checar(
    destino.natureza == destinos.ACERVO,
    "sem caso em foco, a mesma frase é pergunta sobre o escritório inteiro",
)

destino = destinos.decidir("/doc", CASOS)
checar(
    destino.natureza == destinos.ESCOLHA and not destino.candidatos,
    "pedir documentos sem dizer de quem devolve a pergunta, e não um caso ao acaso",
)


print("\n5. O modo pedido pela tela vence o texto")
destino = destinos.decidir(
    "o caso da Maria Silva Santos prescreve quando?", CASOS, modo=destinos.WEB
)
checar(
    destino.natureza == destinos.WEB,
    "quem clicou no botao de pesquisar na web recebe a web, mesmo citando um caso",
)

destino = destinos.decidir("qualquer coisa", CASOS, modo="INVENTADO")
checar(
    destino.natureza != "INVENTADO",
    "modo desconhecido não vira destino: cai no roteamento normal",
)


print("\n6. Dois casos citados: perguntar é a única saída honesta")
destino = destinos.decidir(
    "como está o caso da Maria Silva Santos?", CASOS_AMBIGUOS
)
checar(destino.natureza == destinos.ESCOLHA, "dois processos do mesmo cliente -> ESCOLHA")
checar(len(destino.candidatos) == 2, "e os dois vão para a lista")

destino = destinos.decidir(
    "quais documentos a Maria Silva Santos entregou?", CASOS_AMBIGUOS
)
checar(
    destino.natureza == destinos.ESCOLHA,
    "vale também para os documentos: mostrar a papelada do processo errado é pior que perguntar",
)


print("\n7. O que NÃO é do acervo vai para a web sem ninguém pedir")

# A pergunta que expôs o defeito: o analista recusava em três parágrafos educados uma
# dúvida que a internet responde em dois segundos.
for frase in (
    "como instalo um alto-falante em paralelo?",
    "qual a diferença entre PIS e PASEP?",
    "quanto custa registrar uma marca no INPI?",
    "como faço um churrasco para 40 pessoas?",
):
    destino = destinos.decidir(frase, CASOS)
    checar(destino.natureza == destinos.WEB, f"{frase[:44]}... -> WEB")

# E o que fala do escritório continua no analista, que é quem sabe medir.
for frase in (
    "quais casos estão parados esperando documento do INSS?",
    "quantos clientes entraram este mês?",
    "tem alguma audiência marcada para a semana que vem?",
    "quais peticoes ainda nao foram protocoladas?",
):
    destino = destinos.decidir(frase, CASOS)
    checar(
        destino.natureza == destinos.ACERVO,
        f"{frase[:44]}... -> analista",
    )


print("\n8. Glossário explica CONCEITO; lista e contagem são do analista")

# O verbete continua respondendo o que ele responde bem.
for frase in (
    "o que é um fato alegado?",
    "o que é um fato provado?",
    "como funciona a entrevista guiada?",
    "quando a petição pode ser gerada?",
    "qual a diferença entre fato alegado e fato provado?",
):
    destino = destinos.decidir(frase, CASOS)
    checar(destino.natureza == destinos.SISTEMA, f"{frase[:44]}... -> glossário")

# E cede quando a pergunta quer um levantamento. A primeira é a que expôs o defeito:
# cita "entrevista" e "peça" no meio, e voltava explicando o que é uma entrevista.
for frase in (
    "qual caso esta mais tempo parado?, quero que busque todos os casos e me diga"
    " quanto tempo cada um ta parado e porque ele esta parado, falta de doc,"
    " entrevista, ou peca",
    "quais petições ainda não foram protocoladas?",
    "me diga quais entrevistas foram feitas esta semana",
    "liste os casos parados por falta de documento",
):
    destino = destinos.decidir(frase, CASOS)
    checar(destino.natureza == destinos.ACERVO, f"{frase[:44]}... -> analista")


print("\n9. O texto dos documentos não melhora o que está guardado")
PAINEL = {
    "caso": {"id": "caso-maria", "cliente": "Maria Silva Santos", "categoria": "acidente trabalho"},
    "progresso": {"obrigatorios_entregues": 3, "obrigatorios_total": 7, "itens_a_conferir": 2},
    "entregas": [
        {
            "id": "e1",
            "arquivo": "cat.pdf",
            "tipo_detectado": "CAT",
            "tipo_confere": True,
            "status": "ok",
        },
        {
            "id": "e2",
            "arquivo": "rg.jpg",
            "tipo_detectado": "holerite",
            "tipo_confere": False,
            "status": "ok",
        },
        {
            "id": "e3",
            "arquivo": "contracheque.pdf",
            "tipo_detectado": "",
            "tipo_confere": None,
            "status": "ok",
        },
    ],
    "entregas_ocultas": 2,
    "pendentes": [{"nome": "Carteira de trabalho", "motivo": "ainda não recebemos este documento"}],
    "entrevistas": [{"id": "ent-1"}],
    "pecas": [{"titulo": "Petição inicial"}],
}
texto = documentos_do_chat.resumir(PAINEL)
checar("Maria Silva Santos" in texto, "o texto diz de quem é o caso")
checar("3 de 7" in texto, "e quanto do checklist está resolvido")
checar("cat.pdf" in texto and "rg.jpg" in texto, "cada arquivo aparece pelo nome")
checar("não bate com o item" in texto, "o documento divergente é apontado como tal")
checar(
    "ainda não conferido" in texto,
    "e o que ninguém conferiu NÃO é acusado de errado — são estados diferentes",
)
checar("e mais 2 no dossiê" in texto, "o que não coube é declarado, não escondido")
checar("Carteira de trabalho" in texto, "o que falta entra na resposta")


print("\n10. Atalhos: caminho que existe, ou nenhum")
caminhos = atalhos.de_caso(
    {"id": "caso-maria", "cliente": "Maria Silva Santos"}
)
checar(len(caminhos) == 2, "um caso abre dois caminhos: dossiê e documentos")
checar(
    any(c["tipo"] == "DOCUMENTOS" and c["embutido"] for c in caminhos),
    "o dos documentos pode ser mostrado DENTRO da conversa",
)
checar(
    all(c["caso_id"] == "caso-maria" for c in caminhos),
    "e os dois levam ao caso certo",
)
checar(atalhos.de_caso({"cliente": "Sem identificador"}) == [], "caso sem id não vira botão")

fontes = [
    {"url": "https://www.planalto.gov.br/lei", "titulo": "Lei 8.213", "confianca": "OFICIAL"},
    {"url": "", "titulo": "Fonte sem endereço", "confianca": "OUTRO"},
]
da_web = atalhos.da_web(fontes)
checar(len(da_web) == 1, "fonte sem endereço não vira botão")
checar(da_web[0]["confianca"] == "OFICIAL", "o selo da fonte acompanha o atalho")


print("\n11. O contexto da sessão: a pergunta é lida dentro do assunto")

from app.chat import contexto as ctx  # noqa: E402

# A conversa que expôs o problema (22/09): bolo de chocolate, depois "videos sobre" —
# duas palavras que, sozinhas no buscador, devolveram cinco vídeos em espanhol sobre
# agentes de IA.
checar(
    ctx.se_sustenta_sozinha("como fazer um bolo de chocolate"),
    "pergunta inteira traz o próprio assunto",
)
for dependente in ("videos sobre", "e como faz", "e sem açúcar?", "manda mais", "e o preço disso?"):
    checar(
        not ctx.se_sustenta_sozinha(dependente),
        f"«{dependente}» depende do que veio antes",
    )

# O ASSUNTO SOBREVIVE A VÁRIAS DEPENDENTES SEGUIDAS — é o que a regra antiga (colar a
# pergunta anterior) não fazia: na terceira pergunta, a anterior já era "videos sobre".
assunto = ""
for pergunta in ("como fazer um bolo de chocolate", "videos sobre", "e sem açúcar?"):
    assunto = ctx.proximo_assunto(pergunta, assunto)
checar(assunto == "como fazer um bolo de chocolate", "o assunto atravessa a conversa inteira")

# E uma pergunta nova inteira troca o assunto, sem cerimônia.
assunto = ctx.proximo_assunto("quais casos do escritório estão parados esperando documento", assunto)
checar(assunto.startswith("quais casos"), "pergunta com assunto próprio assume a conversa")

contexto_bolo = ctx.Contexto(assunto="como fazer um bolo de chocolate")
checar(
    "bolo de chocolate" in contexto_bolo.com_assunto("videos sobre"),
    "a pergunta chega ao destino com o assunto dentro",
)
checar(
    contexto_bolo.com_assunto("qual o prazo prescricional do acidente de trabalho?")
    == "qual o prazo prescricional do acidente de trabalho?",
    "e a pergunta que se sustenta não é contaminada pelo assunto anterior",
)

# O DESTINO TAMBÉM É CONTEXTO: "e quanto tempo?" depois do acervo é acervo.
depois_do_acervo = ctx.Contexto(
    assunto="quais casos estão parados", ultimo_destino=destinos.ANALISE
)
checar(
    destinos.decidir("e quanto tempo?", CASOS, contexto=depois_do_acervo).natureza
    == destinos.ACERVO,
    "pergunta de acompanhamento segue o caminho da anterior",
)
depois_da_web = ctx.Contexto(assunto="como fazer um bolo", ultimo_destino=destinos.WEB)
checar(
    destinos.decidir("videos sobre", CASOS, contexto=depois_da_web).natureza == destinos.WEB,
    "e depois de uma resposta da internet, continua na internet",
)
checar(
    "bolo" in destinos.decidir("videos sobre", CASOS, contexto=depois_da_web).consulta,
    "com o assunto dentro da consulta que vai para a busca",
)

# Pergunta inteira NÃO herda o caminho: quem escreveu o assunto está trocando de assunto.
inteira = destinos.decidir(
    "qual o prazo prescricional para acidente de trabalho?", CASOS, contexto=depois_do_acervo
)
checar(inteira.natureza == destinos.WEB, "pergunta nova é roteada do zero")


print("\n12. A rede: analista que não consultou nada não estava falando do acervo")

from app.chat import sessoes  # noqa: E402
from app.agente import analista  # noqa: E402

#: O histórico vem do banco; aqui a sessão é sempre nova.
sessoes.armazenamento.mensagens_do_chat = lambda _: []  # type: ignore[assignment]

PESQUISA = {
    "pergunta": "como instalo um alto-falante em paralelo?",
    "resposta": "Ligue os terminais positivos entre si e os negativos entre si…",
    "fontes": [{"url": "https://exemplo.org/paralelo", "titulo": "Ligação em paralelo", "confianca": "OUTRO"}],
    "tem_fonte_oficial": False,
    "modelo": "modelo-de-teste",
}


def com_analista(
    consultas,
    *,
    recusa=None,
    erro=False,
    texto="Nada parecido no acervo: os 24 casos são trabalhistas.",
    para_a_web="",
):
    """Instala um analista que devolve o que o teste mandar."""

    def responder(pergunta, historico=None):
        if erro:
            raise analista.ErroDoAnalista("sem chave")
        return analista.Analise(
            conteudo=texto,
            consultas=list(consultas),
            recusa=recusa,
            para_a_web=para_a_web,
        )

    sessoes.analista.responder = responder  # type: ignore[assignment]


def com_web(ligada: bool):
    sessoes.pesquisa_web.configurada = lambda: ligada  # type: ignore[assignment]
    # `historico` no dublê porque a busca real o recebe desde 22/09 — é ele que faz
    # "e como faz?" continuar o assunto em vez de virar uma aula de gramática.
    sessoes.pesquisa_web.pesquisar = (  # type: ignore[assignment]
        lambda pergunta, historico=None: dict(PESQUISA, pergunta=pergunta)
    )


# Zero consultas: a pergunta não era daqui, e a web responde antes da recusa. Como o
# analista TEM texto ("nada parecido no acervo"), as duas metades chegam juntas — foi a
# pergunta do julgamento do Moraes (22/09) que mostrou por quê: ela tinha uma pergunta
# sobre o escritório e outra sobre o mundo, e a do escritório sumia.
com_analista([])
com_web(True)
resposta = sessoes._do_acervo(
    "há algum caso no sistema parecido com esse julgamento, e como ele anda?", "sessao-1"
)
checar(resposta["natureza"] == destinos.MISTA, "as duas metades viram uma resposta mista")
checar(
    "No acervo do escritório" in resposta["conteudo"]
    and "Da internet" in resposta["conteudo"],
    "cada origem sob o seu título — nunca as duas no mesmo parágrafo",
)
checar(
    "Nada parecido no acervo" in resposta["conteudo"]
    and PESQUISA["resposta"] in resposta["conteudo"],
    "e nenhuma das duas respostas se perde pelo caminho",
)
checar(resposta["payload"]["fora_do_acervo"] is True, "o payload marca que a web entrou depois")
checar(resposta["payload"]["fontes"], "as fontes da web continuam na resposta")

# Analista sem texto nenhum: aí não há o que compor, e a web responde sozinha — um
# título "No acervo do escritório" seguido de nada seria pior que não ter título.
com_analista([], texto="")
resposta = sessoes._do_acervo("como instalo um alto-falante em paralelo?", "sessao-1")
checar(resposta["natureza"] == destinos.WEB, "sem texto do analista, a web responde sozinha")
checar("não está no acervo" in resposta["conteudo"], "e diz que veio de fora")

# CONSULTOU e ainda assim há uma segunda metade: o analista a declara em `para_a_web`.
# Este é o caminho que a contagem de consultas não pega — desde que ele passou a consultar
# antes de negar, medir o acervo deixou de significar que a pergunta era toda dele.
buscado = {}
sessoes.pesquisa_web.pesquisar = (  # type: ignore[assignment]
    lambda pergunta, historico=None: buscado.update(pergunta=pergunta)
    or dict(PESQUISA, pergunta=pergunta)
)
com_analista(
    [{"ferramenta": "listar_casos", "argumentos": {}}],
    para_a_web="como está o julgamento do ministro X no STF em 2026?",
)
resposta = sessoes._do_acervo("há caso parecido aqui, e como anda o julgamento?", "sessao-1")
checar(resposta["natureza"] == destinos.MISTA, "metade declarada pelo analista -> resposta mista")
checar(
    buscado.get("pergunta") == "como está o julgamento do ministro X no STF em 2026?",
    "e quem vai para a busca é a PERGUNTA que ele reformulou, não a frase inteira",
)

com_web(True)  # restaura a pesquisa padrão do teste

# Consultou alguma coisa: a resposta é do acervo e não vai para a internet.
com_analista([{"ferramenta": "listar_casos", "argumentos": {}}])
resposta = sessoes._do_acervo("quais casos estão parados?", "sessao-1")
checar(
    resposta["natureza"] == destinos.ANALISE and "fora_do_acervo" not in resposta["payload"],
    "analista que mediu alguma coisa responde ele mesmo",
)

# Web desligada: a recusa honesta continua valendo — nada de trocar por "não pesquisei".
com_analista([])
com_web(False)
resposta = sessoes._do_acervo("como instalo um alto-falante em paralelo?", "sessao-1")
checar(
    resposta["natureza"] == destinos.ANALISE
    and "Nada parecido no acervo" in resposta["conteudo"],
    "sem pesquisa configurada, vale o que o analista escreveu",
)

# Analista fora do ar: a pergunta não morre, a web assume.
com_analista([], erro=True)
com_web(True)
resposta = sessoes._do_acervo("qualquer pergunta", "sessao-1")
checar(resposta["natureza"] == destinos.WEB, "analista fora do ar -> a web assume")

com_analista([], erro=True)
com_web(False)
resposta = sessoes._do_acervo("qualquer pergunta", "sessao-1")
checar(
    resposta["natureza"] == destinos.ACERVO and resposta["payload"]["falta"],
    "os dois fora: a recusa diz o que falta, com todas as letras",
)


print()
if falhas:
    print(f"{falhas} verificação(ões) falharam.")
    sys.exit(1)
print("Tudo certo.")
