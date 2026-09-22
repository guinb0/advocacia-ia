"""O chat do escritório: uma tela só, para qualquer pergunta.

O Acervo já tinha três conversas diferentes — a do Dossiê (sobre a petição), a do agente
geral (sobre um caso) e a pesquisa na web (ao lado da minuta). Cada uma com a sua tela, o
seu histórico e o seu jeito de responder. Quem trabalha aqui não pensa em módulos: pensa
em "preciso saber X". Este pacote é a porta única.

O QUE ELE FAZ QUE NENHUM DOS TRÊS FAZIA

- **decide o destino sozinho**, pela pergunta (`destinos.py`): web, documentos do caso,
  glossário do produto, caso ou acervo. Determinístico, antes de qualquer modelo;
- **busca dentro e fora**: o acervo pelas ferramentas do analista, a internet pela
  pesquisa que já existia — e diz, em toda resposta, de onde veio;
- **abre caminho**: cada resposta carrega `atalhos` — o dossiê do caso citado, os
  documentos daquele caso, a tela que mede aquilo. A tela transforma isso em botão, e o
  botão ou navega, ou traz o material para dentro da conversa (`documentos.py`);
- **guarda oito sessões por pessoa** (`armazenamento.TETO_DE_SESSOES`), como um chat
  qualquer: a nona empurra a mais antiga para fora.

ONDE CADA COISA MORA

    destinos.py    para onde vai a pergunta — sem modelo, sem rede
    documentos.py  o que o sistema JÁ tem sobre um caso, pronto para a conversa
    atalhos.py     os caminhos que uma resposta abre
    sessoes.py     a transcrição: abrir, listar, responder, apagar
    rotas.py       `/api/chat/*`

O que este pacote NÃO faz é responder por conta própria. Ele não tem prompt, não tem
modelo e não inventa texto: cada destino é um serviço que já existe, e o que se acrescenta
aqui é a decisão de qual chamar e o caminho que a resposta abre.
"""

from __future__ import annotations

from . import atalhos, destinos, documentos, sessoes
from .rotas import roteador

__all__ = ["atalhos", "destinos", "documentos", "roteador", "sessoes"]
