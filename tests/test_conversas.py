"""Tradução da resposta do agente para a conversa geral, e a lista de escolha.

Sem banco e sem rede. As amostras de `fixtures/` são respostas REAIS do `ia-juridica`,
capturadas de um caso do acervo — e não um JSON inventado a partir da leitura do outro
código. É a diferença entre provar que o formato bate e provar que eu acho que ele bate.
O nome do cliente foi trocado por um fictício antes de entrar no repositório; a estrutura
é a que veio, que é o que o teste precisa.

    .venv\\Scripts\\python.exe -m tests.test_conversas
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agente import conversa_geral as cg  # noqa: E402
from app.agente import conversas  # noqa: E402
from app.agente.conversas import _escolher_entre, traduzir_do_agente  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str) -> None:
    global falhas
    print(f"   {'OK  ' if condicao else 'FALHA'} {descricao}")
    if not condicao:
        falhas += 1


def amostra(nome: str) -> dict:
    return json.loads(
        (Path(__file__).parent / "fixtures" / nome).read_text(encoding="utf-8")
    )


#: Uma resposta que o guardrail de lastro do agente REPROVOU: sem afirmações, com as
#: lacunas dizendo por quê. É o caso que mais importa não se perder na tradução.
AMOSTRA = amostra("chat_do_agente.json")

#: E uma que passou, com afirmação, natureza e proveniência.
COM_LASTRO = amostra("chat_com_lastro.json")


print("\n1. A resposta real do agente é lida inteira")
traduzida = traduzir_do_agente(AMOSTRA, caso_id="caso-1", cliente="Joana Ribeiro Alves")
checar(traduzida["natureza"] == cg.CASO, "natureza CASO")
checar(traduzida["conteudo"] == AMOSTRA["message"]["content"], "o texto chega como veio")
checar(traduzida["conversa_ref"] == AMOSTRA["conversation_id"], "o fio do agente é guardado")
checar(traduzida["caso_id"] == "caso-1", "a resposta sabe de que caso é")
checar(traduzida["payload"]["cliente"] == "Joana Ribeiro Alves", "e de quem é o caso")

esperadas = AMOSTRA["message"]["payload"]["gaps"]
checar(traduzida["payload"]["pendencias"] == esperadas, "as lacunas do agente não se perdem")
checar(
    traduzida["payload"]["afirmacoes"] == AMOSTRA["message"]["payload"]["assertions"],
    "as afirmações passam no formato do agente, que a tela já lê",
)

# Nesta amostra o guardrail de lastro do próprio agente reprovou a resposta. É o caso mais
# importante de preservar: sem as lacunas, a tela mostraria "não foi possível responder" e
# nada explicaria por quê.
checar(len(esperadas) > 0, "a amostra é justamente uma resposta que o guardrail reprovou")


print("\n1b. A resposta COM lastro chega inteira até a tela")
com_lastro = traduzir_do_agente(COM_LASTRO, caso_id="caso-1", cliente="Joana Ribeiro Alves")
afirmacoes = com_lastro["payload"]["afirmacoes"]
checar(len(afirmacoes) == 1, "a afirmação do agente atravessa a tradução")
checar(afirmacoes[0]["nature"] == "PROVEN_FACT", "com a natureza intacta — é ela que vira o selo")
checar(
    afirmacoes[0]["refs"] == COM_LASTRO["message"]["payload"]["assertions"][0]["refs"],
    "e com a proveniência, que é o que leva ao item no dossiê",
)
checar(
    com_lastro["payload"]["citacoes"] == COM_LASTRO["message"]["citations"],
    "as citações da mensagem também",
)
checar(com_lastro["payload"]["pendencias"] == [], "resposta sem lacuna não inventa lacuna")


print("\n2. Corpo incompleto não quebra a conversa")
vazia = traduzir_do_agente({}, caso_id="caso-1", cliente="Alguém")
checar(vazia["conteudo"] == "", "resposta sem texto vira texto vazio, não exceção")
checar(vazia["payload"]["afirmacoes"] == [], "sem lastro, lista vazia")
checar(vazia["propostas"] == [], "sem propostas, lista vazia")
checar(
    traduzir_do_agente({"message": {"payload": None}}, caso_id="c", cliente="x")["payload"][
        "pendencias"
    ]
    == [],
    "`payload` nulo do agente não vira `None.get`",
)


print("\n3. A lista de escolha distingue casos do mesmo cliente")
mesmos = [
    {"id": "aaaaaa11-0000", "cliente": "Maria Santos", "categoria": "acidente_trabalho",
     "criado_em": "2026-08-25T03:55:12+00:00"},
    {"id": "bbbbbb22-0000", "cliente": "Maria Santos", "categoria": "acidente_trabalho",
     "criado_em": "2026-08-25T03:55:47+00:00"},
    {"id": "cccccc33-0000", "cliente": "Maria Santos", "categoria": "acidente_trabalho",
     "criado_em": "2026-08-21T09:10:00+00:00"},
]
escolha = _escolher_entre(mesmos)
candidatos = escolha["payload"]["candidatos"]
checar(escolha["natureza"] == cg.ESCOLHA, "natureza ESCOLHA")
checar("Há 3 casos de Maria Santos" in escolha["conteudo"], "nome repetido não vira lista de nomes")

# Os dois primeiros foram abertos com 35 segundos de diferença: categoria e data até o
# minuto são idênticas, e sem o desempate os dois botões ficariam iguais na tela.
checar(candidatos[0]["desempate"] == "aaaaaa", "o primeiro empatado ganha o identificador")
checar(candidatos[1]["desempate"] == "bbbbbb", "o segundo também")
checar(candidatos[2]["desempate"] == "", "o que já se distingue pela data não ganha número")
checar(
    len({f"{c['categoria']}{c['criado_em'][:16]}{c['desempate']}" for c in candidatos}) == 3,
    "as três linhas ficam distinguíveis",
)


print("\n4. Lista longa é cortada, e a resposta diz que cortou")
muitos = [
    {"id": f"id{n:04d}", "cliente": "Maria Santos", "categoria": "acidente_trabalho",
     "criado_em": f"2026-08-{10 + n:02d}T09:00:00+00:00"}
    for n in range(15)
]
longa = _escolher_entre(muitos)
checar(len(longa["payload"]["candidatos"]) == 8, "no máximo oito botões")
checar("os outros 7" in longa["conteudo"], "e a resposta conta quantos ficaram de fora")
checar(
    "Responder sobre" in longa["conteudo"],
    "apontando o seletor, que é onde os demais estão",
)


print("\n5. Nomes diferentes continuam sendo listados")
diferentes = [
    {"id": "a", "cliente": "Maria Silva", "categoria": "x", "criado_em": "2026-08-01T09:00:00+00:00"},
    {"id": "b", "cliente": "João Souza", "categoria": "y", "criado_em": "2026-08-02T09:00:00+00:00"},
]
mista = _escolher_entre(diferentes)
checar("Maria Silva" in mista["conteudo"] and "João Souza" in mista["conteudo"], "os dois nomes aparecem")
checar(
    "ainda não sei fazer" in mista["conteudo"],
    "e a resposta diz que comparar casos é o que falta",
)


print("\n6. A escolha de um caso RESPONDE a pergunta, e não só fixa o caso")


class BancoFalso:
    """O armazenamento em memória.

    `responder` é o coração do fluxo e merece teste — mas não à custa de encher o banco do
    escritório de casos de mentira, que é o que os testes mais antigos deste projeto fazem.
    """

    def __init__(self):
        self.conversa = {
            "id": "conv-1",
            "titulo": "Nova conversa",
            "resumo": "",
            "usuario": "quem-perguntou",
            "caso_id": None,
            "conversa_ref": None,
            "criado_em": "2026-08-25T10:00:00+00:00",
            "atualizado_em": "2026-08-25T10:00:00+00:00",
        }
        self.mensagens = []
        self.casos = [
            {"id": "c1", "cliente": "Maria Santos", "categoria": "acidente",
             "criado_em": "2026-08-25T03:55:12+00:00"},
            {"id": "c2", "cliente": "Maria Santos", "categoria": "acidente",
             "criado_em": "2026-08-24T03:55:12+00:00"},
        ]

    def obter_conversa(self, _conversa_id):
        return dict(self.conversa)

    def obter_caso(self, caso_id):
        return next((c for c in self.casos if c["id"] == caso_id), None)

    def listar_casos(self):
        return list(self.casos)

    def registrar_mensagem(self, _conversa_id, *, papel, conteudo, natureza, payload=None):
        registro = {
            "id": f"msg-{len(self.mensagens)}",
            "papel": papel,
            "conteudo": conteudo,
            "natureza": natureza,
            "payload": payload or {},
            "criado_em": "2026-08-25T10:00:01+00:00",
        }
        self.mensagens.append(registro)
        return registro

    def atualizar_conversa(self, _conversa_id, **campos):
        for chave, valor in campos.items():
            if valor is not None:
                self.conversa[chave] = valor


class ClienteFalso:
    """Devolve a resposta real do agente, seja qual for o caso perguntado."""

    perguntados = []

    def perguntar_ao_caso(self, caso_ref, *, mensagem, conversa_ref=None):
        ClienteFalso.perguntados.append(caso_ref)
        return AMOSTRA


banco = BancoFalso()
conversas.armazenamento = banco
conversas.Cliente = lambda *args, **kwargs: ClienteFalso()
conversas.espelho.caso_ref = lambda caso_id: f"case_{caso_id}"

sem_escolha = conversas.responder("conv-1", "Resuma o caso de Maria Santos", "quem-perguntou")
checar(sem_escolha["mensagem"]["natureza"] == cg.ESCOLHA, "sem escolha, pergunta qual caso")
checar(ClienteFalso.perguntados == [], "e não incomoda o agente enquanto não sabe qual é")

com_escolha = conversas.responder(
    "conv-1", "Resuma o caso de Maria Santos", "quem-perguntou", caso_escolhido="c2"
)
checar(com_escolha["mensagem"]["natureza"] == cg.CASO, "com escolha, a pergunta é respondida")
checar(ClienteFalso.perguntados == ["case_c2"], "sobre o caso escolhido, não sobre os citados")
checar(banco.conversa["caso_id"] == "c2", "e a conversa passa a ser sobre ele")
checar(
    banco.conversa["titulo"] == "Resuma o caso de Maria Santos",
    "a primeira pergunta virou o título da conversa",
)
checar(
    [m["papel"] for m in banco.mensagens] == ["USER", "ASSISTANT", "USER", "ASSISTANT"],
    "as quatro mensagens ficam gravadas, na ordem em que foram ditas",
)
checar(
    conversas.responder("conv-1", "oi", "outra-pessoa") is None,
    "conversa de outra pessoa não responde nada",
)


# O placar e a saída ficam sob a guarda de `__main__`, como nos demais testes da casa
# (ver `tests/test_perfis.py`). Solto no nível do módulo, o `SystemExit` era disparado
# durante o IMPORT do arquivo — e como o nome começa com `test_`, qualquer `pytest`
# que varresse a pasta morria em `INTERNALERROR` ao coletar este arquivo, levando
# junto a suíte inteira. O jeito de rodar continua o mesmo: `python -m tests.<nome>`.
if __name__ == "__main__":
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    raise SystemExit(1 if falhas else 0)
