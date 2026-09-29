"""Os caminhos que uma resposta abre — o que transforma conversa em trabalho.

Uma resposta que menciona o caso da Maria e para por aí obriga quem lê a sair do chat,
abrir a carteira, achar a Maria entre trezentos nomes e entrar no dossiê. O atalho é a
resposta dizendo onde fica o que ela acabou de citar.

DOIS JEITOS DE ABRIR, E O USUÁRIO ESCOLHE

Todo atalho tem `tela` — para onde levar — e alguns têm `embutido`. Quando `embutido` é
verdadeiro, a tela oferece as duas coisas: **"Abrir"**, que navega, e **"Ver aqui"**, que
traz o material para dentro da conversa sem sair dela. A diferença não é estética: quem
está no meio de uma pergunta perde o fio ao navegar, e quem quer trabalhar no caso não
quer o resumo dentro do chat. Oferecer os dois custa um botão.

O ATALHO NÃO INVENTA NADA. Ele aponta para tela que existe, com caso que existe. É por
isso que ele é montado aqui, a partir do que a resposta realmente citou, e não pedido a
um modelo — um link inventado é pior que link nenhum, porque parece confiável.
"""

from __future__ import annotations

from typing import Any

from .. import armazenamento

__all__ = ["da_web", "de_caso", "de_casos", "de_tela"]

#: Quantos atalhos cabem embaixo de uma resposta antes de virarem parede de botões.
_MAXIMO = 6


def de_caso(caso: dict[str, Any], *, com_documentos: bool = True) -> list[dict[str, Any]]:
    """Os caminhos de UM caso: o dossiê e, quando faz sentido, os documentos."""
    caso_id = str(caso.get("id") or "")
    cliente = str(caso.get("cliente") or "o caso")
    if not caso_id:
        return []

    caminhos = [
        {
            "tipo": "DOSSIE",
            "rotulo": f"Abrir o dossiê de {cliente}",
            "caso_id": caso_id,
            "tela": "dossie",
            "embutido": False,
        }
    ]
    if com_documentos:
        caminhos.append(
            {
                "tipo": "DOCUMENTOS",
                "rotulo": f"Documentos de {cliente}",
                "caso_id": caso_id,
                "tela": "caso",
                # O único que a conversa consegue mostrar por dentro: é leitura do que já
                # está guardado, e cabe numa lista (ver `documentos.montar`).
                "embutido": True,
            }
        )
    return caminhos


def de_casos(
    ids: list[str], *, com_documentos: bool = True, limite: int = _MAXIMO
) -> list[dict[str, Any]]:
    """Os caminhos dos casos que a resposta citou, na ordem em que apareceram.

    Caso apagado não vira atalho: a resposta pode citar um caso que saiu do acervo
    depois, e um botão que leva a lugar nenhum gasta a confiança de todos os outros.
    """
    caminhos: list[dict[str, Any]] = []
    for caso_id in dict.fromkeys(ids):
        caso = armazenamento.obter_caso(caso_id)
        if caso is None:
            continue
        caminhos.extend(de_caso(caso, com_documentos=com_documentos))
        if len(caminhos) >= limite:
            break
    return caminhos[:limite]


def de_tela(tela: str, rotulo: str) -> dict[str, Any]:
    """Um módulo do sistema, sem caso: Panorama, Carteira, Operação."""
    return {"tipo": "TELA", "rotulo": rotulo, "caso_id": None, "tela": tela, "embutido": False}


def da_web(fontes: list[dict[str, Any]], *, limite: int = _MAXIMO) -> list[dict[str, Any]]:
    """As páginas que a pesquisa leu, com o selo de confiança que ela já mediu.

    Elas saem como atalho, e não só como link no texto, para que a resposta da internet
    chegue com a mesma promessa das outras: dá para conferir sem sair do chat. O selo vem
    de `pesquisa_web._confianca` — quem decide se a fonte é oficial é o domínio, não o
    modelo que escreveu a resposta.
    """
    caminhos: list[dict[str, Any]] = []
    for fonte in fontes[:limite]:
        url = str(fonte.get("url") or "").strip()
        if not url:
            continue
        caminhos.append(
            {
                "tipo": "FONTE",
                "rotulo": str(fonte.get("titulo") or url)[:120],
                "url": url,
                "confianca": fonte.get("confianca") or "",
                "caso_id": None,
                "tela": None,
                "embutido": False,
            }
        )
    return caminhos
