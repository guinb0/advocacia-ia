"""Várias conversas por petição: criar, listar, alternar, nomear e excluir.

Sem banco, sem rede e sem modelo: o armazenamento é um dicionário na memória.

O QUE ESTE TESTE PROTEGE

1. **cada conversa tem a sua transcrição** — pergunta e histórico de uma não vazam para
   outra, e o histórico enviado ao modelo é só o da conversa aberta;
2. **o id de uma conversa não é chave para o chat alheio**: outra pessoa, ou outro caso,
   recebe «não existe», nunca a transcrição;
3. **o histórico não enche de conversas em branco** e a primeira pergunta dá nome à
   conversa;
4. **as ações e os avisos do painel caem na conversa que está aberta**;
5. **excluir uma conversa não apaga o que o caso já levantou** (a base é da petição).

    .venv\\Scripts\\python.exe -m tests.test_chat_conversas
"""

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import peticao_local  # noqa: E402
from app.agente import chat_peticao, contexto_caso  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str) -> None:
    global falhas
    print(f"   {'OK  ' if condicao else 'FALHA'} {descricao}")
    if not condicao:
        falhas += 1


class Armazem:
    """Conversas e mensagens em memória, com o contrato que `chat_peticao` usa."""

    def __init__(self) -> None:
        self.conversas: dict[str, dict] = {}
        self.mensagens: dict[str, list[dict]] = {}
        self.relogio = 0

    def _tique(self) -> str:
        self.relogio += 1
        return f"2026-09-19T12:00:{self.relogio:02d}"

    def obter_caso(self, caso_id):
        return {"id": caso_id, "cliente": "Maria Santos", "categoria": "acidente_trabalho"}

    def criar_conversa(self, titulo, *, usuario, caso_id=None, resumo="", escopo="GERAL"):
        instante = self._tique()
        conversa = {
            "id": str(uuid.uuid4()), "titulo": titulo, "resumo": resumo, "usuario": usuario,
            "caso_id": caso_id, "conversa_ref": None, "escopo": escopo,
            "criado_em": instante, "atualizado_em": instante,
        }
        self.conversas[conversa["id"]] = conversa
        self.mensagens[conversa["id"]] = []
        return dict(conversa)

    def _do_caso(self, usuario, caso_id, escopo):
        itens = [
            c for c in self.conversas.values()
            if c["usuario"] == usuario and c["caso_id"] == caso_id and c["escopo"] == escopo
        ]
        return sorted(itens, key=lambda c: c["atualizado_em"], reverse=True)

    def conversa_do_caso(self, usuario, caso_id, *, escopo="PETICAO"):
        itens = self._do_caso(usuario, caso_id, escopo)
        return dict(itens[0]) if itens else None

    def listar_conversas_do_caso(self, usuario, caso_id, *, escopo="PETICAO"):
        return [
            {**c, "perguntas": sum(1 for m in self.mensagens[c["id"]] if m["natureza"] == "PERGUNTA")}
            for c in self._do_caso(usuario, caso_id, escopo)
        ]

    def obter_conversa(self, conversa_id):
        conversa = self.conversas.get(conversa_id)
        return dict(conversa) if conversa else None

    def atualizar_conversa(self, conversa_id, *, titulo=None, **_):
        conversa = self.conversas[conversa_id]
        conversa["atualizado_em"] = self._tique()
        if titulo is not None:
            conversa["titulo"] = titulo
        return True

    def excluir_conversa(self, conversa_id, usuario):
        if self.conversas.get(conversa_id, {}).get("usuario") != usuario:
            return False
        del self.conversas[conversa_id]
        del self.mensagens[conversa_id]
        return True

    def registrar_mensagem(self, conversa_id, *, papel, conteudo, natureza, payload=None):
        registro = {
            "id": f"m{sum(len(v) for v in self.mensagens.values()) + 1}", "conversa_id": conversa_id,
            "papel": papel, "conteudo": conteudo, "natureza": natureza,
            "payload": payload or {}, "criado_em": self._tique(),
        }
        self.mensagens[conversa_id].append(registro)
        return registro

    def mensagens_da_conversa(self, conversa_id):
        return list(self.mensagens.get(conversa_id, []))


BASE: dict[str, dict] = {}
contexto_caso._ler = lambda caso_id: json.loads(json.dumps(BASE.get(caso_id, {})))  # type: ignore[assignment]
contexto_caso._gravar = lambda caso_id, dados: BASE.__setitem__(caso_id, json.loads(json.dumps(dados, default=str)))  # type: ignore[assignment]
peticao_local.anexos_do_caso = lambda caso_id: []  # type: ignore[assignment]
peticao_local.carregar = lambda caso_id: None  # type: ignore[assignment]

armazem = Armazem()
chat_peticao.armazenamento = armazem  # type: ignore[assignment]
chat_peticao._contexto_do_caso = lambda caso_id: "Caso: Maria Santos"  # type: ignore[assignment]

vistos: list[list[dict]] = []


def modelo(mensagens, ferramentas=True, forcar=None):
    vistos.append(mensagens)
    yield {"tipo": "mensagem", "mensagem": {"role": "assistant", "content": "Resposta do modelo."}}


chat_peticao._transmitir = modelo  # type: ignore[assignment]


def perguntar(pergunta, usuario="adv-1", conversa_id="", caso="caso-1"):
    return list(chat_peticao.conversar(caso, pergunta, usuario, conversa_id))


print("1. a primeira conversa nasce sozinha")
aberta = chat_peticao.abrir("caso-1", "adv-1")
checar(len(aberta["conversas"]) == 1 and aberta["conversas"][0]["id"] == aberta["id"], "abrir cria a conversa e a lista no histórico")
checar(aberta["conversas"][0]["perguntas"] == 0, "em branco: zero perguntas")
primeira = aberta["id"]

print("2. a primeira pergunta dá nome à conversa")
perguntar("Aumenta o valor da causa para 60 mil", conversa_id=primeira)
titulos = {c["id"]: c["titulo"] for c in chat_peticao.listar_conversas("caso-1", "adv-1")}
checar(titulos[primeira] == "Aumenta o valor da causa para 60 mil", "o título é a primeira pergunta")
perguntar("Segunda pergunta bem diferente", conversa_id=primeira)
checar(chat_peticao.listar_conversas("caso-1", "adv-1")[0]["titulo"] == "Aumenta o valor da causa para 60 mil", "e não muda nas seguintes")
longa = chat_peticao._titulo_da_pergunta("palavra " * 30)
checar(len(longa) <= 58 and longa.endswith("…"), "pergunta longa vira título curto")

print("3. novo chat")
nova = chat_peticao.nova_conversa("caso-1", "adv-1")
checar(nova["id"] != primeira and nova["mensagens"] == [], "abre uma conversa em branco")
checar(len(nova["conversas"]) == 2, "e o histórico passa a ter duas")
de_novo = chat_peticao.nova_conversa("caso-1", "adv-1")
checar(de_novo["id"] == nova["id"] and len(de_novo["conversas"]) == 2, "pedir outra enquanto há uma em branco reaproveita a em branco")

print("4. cada conversa tem a sua transcrição")
vistos.clear()
perguntar("Pergunta só da conversa nova", conversa_id=nova["id"])
historico_enviado = " ".join(str(m.get("content")) for m in vistos[0])
checar("Pergunta só da conversa nova" in historico_enviado, "a pergunta chega ao modelo")
checar("Aumenta o valor da causa" not in historico_enviado, "sem nada da outra conversa no histórico enviado")
checar(len(chat_peticao.abrir("caso-1", "adv-1", primeira)["mensagens"]) == 4, "a primeira segue com as suas 4 mensagens")
checar(len(chat_peticao.abrir("caso-1", "adv-1", nova["id"])["mensagens"]) == 2, "e a nova com as suas 2")
checar(chat_peticao.abrir("caso-1", "adv-1")["id"] == nova["id"], "sem id, o refresh cai na conversa usada por último")

print("5. o id não abre o chat de outra pessoa nem de outro caso")
for descricao, chamada in (
    ("outra pessoa abre", lambda: chat_peticao.abrir("caso-1", "adv-2", primeira)),
    ("outra pessoa pergunta", lambda: perguntar("oi", usuario="adv-2", conversa_id=primeira)),
    ("outra pessoa exclui", lambda: chat_peticao.excluir_conversa("caso-1", "adv-2", primeira)),
    ("outro caso abre", lambda: chat_peticao.abrir("caso-2", "adv-1", primeira)),
    ("id que não existe", lambda: chat_peticao.abrir("caso-1", "adv-1", "nao-existe")),
):
    try:
        resultado = chamada()
        if isinstance(resultado, list):  # `conversar` é gerador: o erro sai como evento
            checar(resultado[-1]["tipo"] == "erro", f"{descricao}: recusado")
        else:
            checar(False, f"{descricao}: deveria ser recusado")
    except chat_peticao.ErroDoChat as erro:
        checar("não existe" in str(erro), f"{descricao}: recusado")
checar(len(armazem.mensagens[primeira]) == 4, "e a transcrição alheia continua intacta")
checar(chat_peticao.listar_conversas("caso-1", "adv-2") == [], "cada pessoa vê só o próprio histórico")

print("6. ação e aviso do painel caem na conversa aberta")
resultado = chat_peticao.executar_acao("caso-1", "adv-1", {"tipo": "INEXISTENTE"}, conversa_id=primeira)
checar(armazem.mensagens[primeira][-1]["id"] == resultado["mensagem"]["id"], "a ação registra o resultado na conversa pedida")
checar(len(armazem.mensagens[nova["id"]]) == 2, "e não na outra")
aviso = chat_peticao.registrar_evento("caso-1", "adv-1", "revisao_descartada", {}, nova["id"])
checar(aviso is not None and armazem.mensagens[nova["id"]][-1]["id"] == aviso["id"], "o aviso do painel vai para a conversa indicada")

print("7. excluir")
contexto_caso.registrar_pesquisa("caso-1", {"pergunta": "Súmula 378 TST", "resposta": "x", "fontes": [{"url": "https://tst.jus.br", "titulo": "TST", "confianca": "TRIBUNAL"}]})
chat_peticao.excluir_conversa("caso-1", "adv-1", primeira)
restantes = chat_peticao.listar_conversas("caso-1", "adv-1")
checar([c["id"] for c in restantes] == [nova["id"]], "a conversa some do histórico")
checar(len(BASE["caso-1"]["pesquisas"]) == 1, "mas o que o caso já levantou continua: a base é da petição")
checar(chat_peticao.abrir("caso-1", "adv-1")["id"] == nova["id"], "abrir sem id cai na que sobrou")
chat_peticao.excluir_conversa("caso-1", "adv-1", nova["id"])
recriada = chat_peticao.abrir("caso-1", "adv-1")
checar(len(recriada["conversas"]) == 1 and recriada["mensagens"] == [], "sem nenhuma, abrir cria uma em branco")

if __name__ == "__main__":
    print(f"\n{'TUDO OK' if not falhas else f'{falhas} FALHA(S)'}")
    raise SystemExit(1 if falhas else 0)
