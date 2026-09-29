"""O contexto da sessão: sobre o que se está falando, e por onde a conversa anda.

POR QUE ISTO EXISTE, E POR QUE NÃO É UMA LISTA DE PALAVRAS

A primeira tentativa de fazer a pergunta de acompanhamento funcionar foi colar a
pergunta ANTERIOR na atual quando a atual era curta. Funcionou uma vez e quebrou na
seguinte, por três motivos que só aparecem conversando:

- **a anterior também pode ser dependente.** "como fazer um bolo de chocolate" → "videos
  sobre" → "e sem açúcar?": na terceira pergunta, colar a anterior traz "videos sobre",
  que não é assunto nenhum. O bolo já tinha se perdido;
- **o destino não acompanhava.** "e quanto tempo?" depois de uma resposta do acervo é
  pergunta de acervo; depois de uma resposta da web, é da web. Sem lembrar para onde a
  conversa foi, as duas caíam no mesmo lugar;
- **regra por palavra-chave não se conserta, só se estende.** Cada pergunta nova que
  falhava virava mais uma palavra numa lista, e a lista nunca fecha.

Assunto é ESTADO DA CONVERSA, e estado da conversa mora na conversa — em duas colunas de
`acervo_chat_sessoes` (`assunto`, `ultimo_destino`). Cada pergunta é lida dentro desse
estado, e cada resposta o atualiza.

COMO O ASSUNTO MUDA

Uma pergunta que **se sustenta sozinha** vira o assunto ("como fazer um bolo de
chocolate", "quais casos estão parados"). Uma que **depende do que veio antes** ("videos
sobre", "e sem açúcar?", "manda mais") não mexe nele — ela é lida dentro do assunto que
já existe. É a mesma regra de quem está ouvindo a conversa: o assunto só muda quando
alguém o troca por inteiro.

O caso continua à parte (`caso_id`), e não se mistura com o assunto: ele é referência a
um registro do acervo, com permissão e dossiê; o assunto é texto que orienta uma busca.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "Contexto",
    "de_sessao",
    "palavras_de_conteudo",
    "proximo_assunto",
    "se_sustenta_sozinha",
]


#: Quanto do assunto é guardado. Cabe numa pergunta inteira sem virar parágrafo.
LIMITE_DO_ASSUNTO = 240

#: Palavras que não nomeiam assunto nenhum: artigos, preposições, conjunções, pronomes e
#: os verbos com que toda pergunta começa.
#:
#: A primeira versão contava PALAVRAS — seis ou menos, dependente. "como fazer um bolo de
#: chocolate" tem exatamente seis, e quatro delas são "como", "fazer", "um" e "de": a
#: pergunta que mais claramente traz o próprio assunto era classificada como se não
#: trouxesse nenhum. O que distingue "videos sobre" de "bolo de chocolate" não é o
#: tamanho, é quanta coisa se está NOMEANDO.
_SEM_CONTEUDO = frozenset(
    {
        # artigos e preposições
        "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
        "em", "no", "na", "nos", "nas", "por", "para", "pra", "com", "sem", "sobre",
        "entre", "ate", "apos", "ao", "aos", "as", "num", "numa", "pelo", "pela",
        # conjunções e advérbios de ligação
        "e", "ou", "mas", "que", "se", "entao", "porque", "pois", "como", "quando",
        "onde", "qual", "quais", "quanto", "quanta", "quantos", "quantas", "quem",
        "ja", "ainda", "so", "tambem", "muito", "pouco", "mais", "menos", "bem", "tudo",
        "todo", "toda", "todos", "todas", "cada", "outro", "outra", "outros", "outras",
        # pronomes e dêiticos — os que apontam para o que foi dito antes
        "eu", "me", "meu", "minha", "meus", "minhas", "voce", "tu", "ele", "ela", "eles",
        "elas", "dele", "dela", "isso", "isto", "esse", "essa", "este", "esta", "aquilo",
        "aquele", "aquela", "disso", "desse", "dessa", "nisso", "nele", "nela", "ai",
        "la", "aqui", "mesmo", "mesma", "lo", "la", "os", "as",
        # os verbos que abrem pergunta sem dizer do que ela trata
        "e", "eh", "sao", "esta", "estao", "ser", "sou", "tem", "ter", "tenho", "teria",
        "faz", "fazer", "faco", "fica", "ficou", "vai", "vou", "quero", "queria", "pode",
        "posso", "poderia", "deve", "devo", "preciso", "gostaria", "manda", "mandar",
        "mostra", "mostre", "mostrar", "ver", "vejo", "diz", "dizer", "fala", "falar",
        "da", "dar", "me", "traz", "trazer", "busca", "buscar", "procura", "procurar",
    }
)

#: Quantas palavras de conteúdo bastam para a pergunta se sustentar.
#:
#: Duas: "bolo chocolate", "casos parados", "fato alegado". Uma só — "videos", "preço",
#: "açúcar" — é complemento de alguma coisa dita antes, que é exatamente o caso que este
#: módulo existe para resolver.
_CONTEUDO_MINIMO = 2


def normalizar(texto: object) -> str:
    """Minúsculas, sem acento, espaços colapsados — a mesma de `conversa_geral`."""
    bruto = unicodedata.normalize("NFKD", str(texto or ""))
    sem_acento = "".join(c for c in bruto if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


@dataclass(frozen=True)
class Contexto:
    """O que a sessão já sabe quando a próxima pergunta chega.

    `assunto` é a última pergunta que se sustentava sozinha. `ultimo_destino` é para onde
    a conversa foi da última vez, e serve à pergunta de acompanhamento — que herda o
    caminho em vez de ser roteada do zero.
    """

    assunto: str = ""
    caso_id: str | None = None
    ultimo_destino: str = ""
    #: As últimas trocas, no vocabulário do modelo (`role`/`content`).
    historico: list[dict[str, str]] = field(default_factory=list)

    def com_assunto(self, pergunta: str) -> str:
        """A pergunta lida DENTRO do assunto — é ela que vai ao destino.

        Quando a pergunta já se sustenta, nada é acrescentado: juntar as duas faria a
        busca procurar bolo de chocolate junto com prescrição trabalhista.
        """
        limpa = " ".join((pergunta or "").split())
        if not limpa or not self.assunto or se_sustenta_sozinha(limpa):
            return limpa
        return f"{limpa} — sobre: {self.assunto}"


def palavras_de_conteudo(pergunta: str) -> list[str]:
    """O que a pergunta NOMEIA, sem as palavras que só a costuram."""
    return [
        palavra
        for palavra in re.findall(r"[\w-]+", normalizar(pergunta))
        if palavra not in _SEM_CONTEUDO and not palavra.isdigit()
    ]


def se_sustenta_sozinha(pergunta: str) -> bool:
    """A pergunta diz do que trata, sem depender do que veio antes?

    Esta é a ÚNICA decisão por forma da frase que sobrou — e ela não escolhe destino nem
    monta busca: só decide se o assunto da conversa MUDA. Errar aqui custa uma pergunta
    lida no assunto errado, não uma resposta sobre o caso de outra pessoa.
    """
    return len(palavras_de_conteudo(pergunta)) >= _CONTEUDO_MINIMO


def proximo_assunto(pergunta: str, assunto_atual: str) -> str:
    """O assunto depois desta pergunta.

    Troca quando a pergunta traz um assunto próprio; mantém quando ela se apoia no que
    já estava em cima da mesa. É o que faz "bolo de chocolate" sobreviver a "videos
    sobre" e a "e sem açúcar?" na mesma conversa.
    """
    limpa = " ".join((pergunta or "").split())
    if not limpa:
        return assunto_atual
    if se_sustenta_sozinha(limpa):
        return limpa[:LIMITE_DO_ASSUNTO]
    return assunto_atual


def de_sessao(sessao: dict[str, Any], mensagens: list[dict[str, Any]]) -> Contexto:
    """Monta o contexto a partir do que está gravado.

    O histórico sai das mensagens e leva só o TEXTO: lastro, fontes e atalhos da resposta
    anterior não ajudam a entender a próxima pergunta e custariam a janela inteira.
    """
    return Contexto(
        assunto=str(sessao.get("assunto") or ""),
        caso_id=sessao.get("caso_id"),
        ultimo_destino=str(sessao.get("ultimo_destino") or ""),
        historico=[
            {
                "role": "user" if m.get("papel") == "USER" else "assistant",
                "content": str(m.get("conteudo") or "")[:2000],
            }
            for m in mensagens
            if str(m.get("conteudo") or "").strip()
        ],
    )
