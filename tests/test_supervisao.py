"""O checklist do roteiro: o que a supervisão consegue conferir sem ler a conversa.

O banco é dublado — o checklist só lê registro, e as quatro funções que o montam são
puras. O que está coberto é o que faz o checklist MENTIR se quebrar:

- item que não se aplica entrando na conta do progresso, e fazendo uma entrevista
  sem caso parecer malfeita;
- assinatura casada pelo nome errado, dando por pendente uma procuração já assinada
  (ou o contrário, que é pior);
- avaliação do Google marcada aparecendo como pendente — é a etapa mais frágil do
  roteiro e a única que a supervisão consegue corrigir à mão;
- documento recusado contando como feito.

Rodar: .venv\\Scripts\\python.exe -m tests.test_supervisao
"""

from __future__ import annotations

import os

# Mesma razão do `test_roteiros`: as rotas exigem papel, e este teste não tem sessão.
os.environ["JWT_SECRET"] = ""

from app import supervisao  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str, detalhe: str = "") -> None:
    global falhas
    if condicao:
        print(f"  PASS  {descricao}")
    else:
        falhas += 1
        print(f"  FALHA {descricao}" + (f"\n          {detalhe}" if detalhe else ""))


def por_id(fase: dict, identificador: str) -> dict:
    return next(i for i in fase["itens"] if i["id"] == identificador)


def entrevista(**campos) -> dict:
    base = {
        "id": "e1",
        "caso_id": "c1",
        "entrevistador": "Helena Prado",
        "texto": "palavra " * 60,
        "realizada_em": "2026-08-20",
        "resumo": "Carteiro motociclista, assalto em serviço.",
        "fatos_gerados": 12,
        "enviada": True,
        "avaliacao_google": False,
        "avaliacao_google_em": None,
        # Vazio = anexada como arquivo. Preenchido = conduzida pelo roteiro guiado.
        "gravacao_id": "",
    }
    base.update(campos)
    return base


# ------------------------------------------------------- avaliação no Google

print("\nAvaliação no Google Meu Negócio")

fase = supervisao._fase_avaliacao(entrevista())
item = por_id(fase, "avaliacao-confirmada")
checar(item["situacao"] == "pendente", "sem marcação -> pendente")
checar(item["critico"], "é crítica: passada a chamada, não há segunda chance")
checar(
    "não há como conferir" in item["detalhe"],
    "o texto separa 'não aconteceu' de 'não foi registrado'",
    item["detalhe"],
)

fase = supervisao._fase_avaliacao(
    entrevista(avaliacao_google=True, avaliacao_google_em="2026-08-20T14:32:07")
)
item = por_id(fase, "avaliacao-confirmada")
checar(item["situacao"] == "feito", "marcada -> feito")
checar("2026-08-20 14:32" in item["detalhe"], "mostra quando foi marcada", item["detalhe"])


# ------------------------------------------------------------- assinaturas

print("\nPapelada e assinaturas")

# Como `main.py` monta o nome ao enviar para a ZapSign.
assinado = {"nome": "Contrato de honorários — Ana Lima", "estado": "assinado"}
recusado = {"nome": "Procuração ad judicia — Ana Lima", "estado": "recusado"}
parcial = {
    "nome": "Declaração de hipossuficiência — Ana Lima",
    "estado": "pendente",
    "assinaram": 1,
    "total": 2,
    "faltam": ["Ana Lima"],
}

fase = supervisao._fase_papelada("c1", [assinado, recusado, parcial])
checar(por_id(fase, "assinatura-contrato")["situacao"] == "feito", "contrato assinado -> feito")
checar(
    por_id(fase, "assinatura-procuracao")["situacao"] == "pendente",
    "procuração recusada NÃO conta como feita",
)
checar(
    "Recusado" in por_id(fase, "assinatura-procuracao")["detalhe"],
    "e o motivo aparece na linha",
)
hipo = por_id(fase, "assinatura-hipossuficiencia")
checar(hipo["situacao"] == "pendente", "1 de 2 assinaram -> ainda pendente")
checar("Ana Lima" in hipo["detalhe"], "diz de quem se está esperando", hipo["detalhe"])

fase = supervisao._fase_papelada("c1", [])
checar(
    all(i["situacao"] == "pendente" for i in fase["itens"]),
    "sem envio nenhum, os três ficam pendentes",
)
checar(
    por_id(fase, "assinatura-contrato")["critico"]
    and por_id(fase, "assinatura-procuracao")["critico"],
    "contrato e procuração são críticos: sem procuração não se peticiona",
)

fase_sem_caso = supervisao._fase_papelada("", [])
checar(
    all(i["situacao"] == "nao_aplica" for i in fase_sem_caso["itens"]),
    "entrevista sem caso não tem papelada a cobrar",
)


# --------------------------------------------------------------- registro

print("\nRegistro do atendimento")

fase = supervisao._fase_registro(entrevista(gravacao_id="grav-123456789"), [{"id": "d1"}])
checar(
    all(i["situacao"] == "feito" for i in fase["itens"]),
    "atendimento ao vivo completo fecha todas as linhas do registro",
    str([(i["id"], i["situacao"]) for i in fase["itens"]]),
)

fase = supervisao._fase_registro(
    entrevista(entrevistador="", realizada_em="", texto="oi", resumo="", enviada=False), []
)
checar(
    all(i["situacao"] == "pendente" for i in fase["itens"] if i["id"] != "registro-audio"),
    "atendimento sem rastro nenhum abre todas as linhas",
    str([(i["id"], i["situacao"]) for i in fase["itens"]]),
)

# A entrevista anexada à mão nunca teve gravação. Cobrar áudio dela apontaria
# pendência em todo registro antigo do escritório — e não é falha de ninguém.
checar(
    por_id(supervisao._fase_registro(entrevista(), []), "registro-audio")["situacao"]
    == "nao_aplica",
    "entrevista anexada como arquivo não tem áudio a cobrar",
)
checar(
    por_id(supervisao._fase_registro(entrevista(gravacao_id="g1"), []), "registro-audio")[
        "situacao"
    ]
    == "feito",
    "entrevista conduzida ao vivo guarda o áudio",
)
checar(
    por_id(fase, "registro-transcricao")["situacao"] == "pendente",
    "texto abaixo do mínimo do auditor não vale como transcrição",
)
checar(
    supervisao._fase_registro(entrevista(texto="x" * supervisao.auditoria.MINIMO_CONVERSA), [])
    ["itens"][2]["situacao"]
    == "feito",
    "exatamente no mínimo já conta",
)


# --------------------------------------------------------------- progresso

print("\nProgresso")

progresso = supervisao._progresso(
    [
        {"itens": [{"situacao": "feito"}, {"situacao": "pendente"}]},
        {"itens": [{"situacao": "nao_aplica"}, {"situacao": "nao_aplica"}]},
    ]
)
checar(
    progresso == {"feitos": 1, "total": 2, "percentual": 50},
    "'não se aplica' fica fora do denominador",
    str(progresso),
)

progresso = supervisao._progresso([{"itens": [{"situacao": "incerto"}]}])
checar(
    progresso["feitos"] == 0 and progresso["total"] == 1,
    "'incerto' conta como não feito, mas continua no denominador",
    str(progresso),
)

progresso = supervisao._progresso([{"itens": [{"situacao": "nao_aplica"}]}])
checar(progresso["percentual"] == 0, "nada conferível não divide por zero")


# -------------------------------------------------------------- a rota toda

print("\nRota do checklist")

_guardados = (
    supervisao.armazenamento.obter_entrevista,
    supervisao.armazenamento.obter_caso,
    supervisao.armazenamento.listar_assinaturas,
    supervisao.armazenamento.listar_entregas,
)
supervisao.armazenamento.obter_entrevista = lambda i: entrevista(id=i)
supervisao.armazenamento.obter_caso = lambda i: {"id": i, "cliente": "Ana Lima", "categoria": "assalto"}
supervisao.armazenamento.listar_assinaturas = lambda caso_id=None, **_: [assinado]
supervisao.armazenamento.listar_entregas = lambda caso_id: []
try:
    resposta = supervisao.checklist("e1")
    checar(resposta["caso"]["cliente"] == "Ana Lima", "a rota traz o cliente do caso")
    checar(
        [f["codigo"] for f in resposta["fases"]] == ["avaliacao", "papelada", "registro"],
        "as três fases de registro saem na ordem em que o secretário confere",
    )
    checar(
        resposta["progresso"]["total"]
        == sum(
            1
            for f in resposta["fases"]
            for i in f["itens"]
            if i["situacao"] != "nao_aplica"
        ),
        "o progresso da rota bate com os itens que ela devolveu",
    )
    checar(
        all(i["situacao"] in supervisao.SITUACOES for f in resposta["fases"] for i in f["itens"]),
        "nenhum item sai com situação fora do vocabulário",
    )
finally:
    (
        supervisao.armazenamento.obter_entrevista,
        supervisao.armazenamento.obter_caso,
        supervisao.armazenamento.listar_assinaturas,
        supervisao.armazenamento.listar_entregas,
    ) = _guardados



# ------------------------------------------------ os agregados do painel

print("\nAgregados do painel")

# `realizada_em` e texto livre e o acervo tem os DOIS formatos convivendo. Numa
# coluna de tabela, lado a lado, a data parece erro de dado.
for bruto, esperado, o_que in [
    ("2026-08-21", "21/08/2026", "ISO vira brasileira"),
    ("12/08/2026", "12/08/2026", "brasileira passa intacta"),
    ("2026-08-21T14:30:00", "21/08/2026", "ISO com hora tambem"),
    ("", "", "vazio continua vazio"),
    (None, "", "None nao vira 'None'"),
]:
    checar(supervisao._data_curta(bruto) == esperado, o_que,
           f"{bruto!r} -> {supervisao._data_curta(bruto)!r}")

_guardados2 = (
    supervisao.armazenamento.listar_todas_entrevistas,
    supervisao.armazenamento.listar_casos,
)
supervisao.armazenamento.listar_casos = lambda: [{"id": "c1", "cliente": "Ana"}]
supervisao.armazenamento.listar_todas_entrevistas = lambda: [
    entrevista(id="a", entrevistador="Helena", avaliacao_google=True, enviada=True,
               gravacao_id="g1", realizada_em="2026-08-20"),
    entrevista(id="b", entrevistador="Helena", avaliacao_google=False, enviada=True,
               realizada_em="19/08/2026"),
    entrevista(id="c", entrevistador="", avaliacao_google=False, enviada=False),
]
try:
    d = supervisao.por_entrevistador()
    pend = d["pendencias"]
    checar(pend["sem_avaliacao"] == 2, "conta quem NAO tem avaliacao (nao quem tem)", str(pend))
    checar(pend["sem_dossie"] == 1, "conta quem nao virou dossie")
    checar(pend["sem_quem_conduziu"] == 1, "conta a que nao tem quem conduziu")
    checar(pend["ao_vivo"] == 1 and pend["anexadas"] == 2, "separa ao vivo de anexada", str(pend))

    helena = next(p for p in d["itens"] if p["entrevistador"] == "Helena")
    checar(helena["com_avaliacao"] == 1 and helena["quantidade"] == 2,
           "o resumo da pessoa bate com as entrevistas dela")
    checar(helena["com_dossie"] == 2, "e conta o dossie separado da avaliacao")
    checar(helena["ultima_em"] == "20/08/2026",
           f"a ultima e a mais recente, normalizada ({helena['ultima_em']})")
    checar(
        all("gravacao_id" in e for p in d["itens"] for e in p["entrevistas"]),
        "toda entrevista da lista traz gravacao_id — o painel soma por ele",
    )
finally:
    (
        supervisao.armazenamento.listar_todas_entrevistas,
        supervisao.armazenamento.listar_casos,
    ) = _guardados2


print(f"\n{'TUDO OK' if not falhas else f'{falhas} FALHA(S)'}")
raise SystemExit(1 if falhas else 0)
