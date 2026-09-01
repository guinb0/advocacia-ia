"""A fila da carteira: os casos ordenados por risco de travar, uma página por vez.

Antes esta tela era montada no navegador: `GET /api/casos` trazia a carteira inteira e
o front pedia `GET /api/casos/{id}` de cada caso para saber o progresso — uma requisição
HTTP por caso, todas de uma vez, e o payload crescendo junto com o escritório.

Aqui a mesma conta é feita no servidor, em duas consultas (casos + todas as entregas,
agrupadas em memória como `panorama.montar` já fazia), e só a página pedida atravessa a
rede. O que **não** é paginado é a medição: a ordem por risco e a triagem olham a
carteira inteira antes de cortar a página, senão "o que pode travar aparece primeiro"
passaria a valer só dentro da página, e os contadores do topo mudariam de valor ao virar
de página — dois jeitos de a tela mentir sobre o escritório.

A regra de severidade é a mesma de `frontend/src/lib/useCarteira.ts` (`acaoPara`), que
segue responsável pelo texto exibido. Aqui ela existe só para ordenar e contar.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import armazenamento, banco
from . import casos as casos_ocr

#: Dias parados a partir dos quais um caso sem documento vira cobrança.
DIAS_PARA_COBRAR = 7

#: Casos por página. O mesmo valor é o padrão da rota.
TAMANHO_PADRAO = 10


def _dias_desde(iso: str | None) -> int:
    if not iso:
        return 0
    texto = str(iso).replace("Z", "+00:00")
    try:
        quando = datetime.fromisoformat(texto)
    except ValueError:
        return 0
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - quando).total_seconds() // 86_400))


def _severidade(progresso: dict[str, Any], dias: int) -> str:
    if progresso["pronto"]:
        return "pronto"
    if progresso["obrigatorios_pendentes"] > 0 and dias >= DIAS_PARA_COBRAR:
        return "critico"
    if progresso["itens_a_conferir"] > 0:
        return "atencao"
    return "neutro"


def _peso(severidade: str, progresso: dict[str, Any], dias: int) -> int:
    """Menor primeiro. O desempate por dias parados mantém a ordem estável."""
    if severidade == "critico":
        base = 0
    elif severidade == "atencao":
        base = 1_000
    elif progresso["pronto"]:
        base = 2_000
    else:
        base = 3_000
    return base - dias


def montar(pagina: int = 1, tamanho: int = TAMANHO_PADRAO) -> dict[str, Any]:
    """A página pedida da fila, mais os números que valem para a carteira toda.

    Duas consultas numa conexão só — o banco é remoto e o handshake custa mais que as
    leituras (ver `banco.sessao`).
    """
    with banco.sessao():
        cadastro = armazenamento.listar_casos()
        entregas_por_caso = armazenamento.entregas_de_todos_os_casos()
    return compor(cadastro, entregas_por_caso, pagina=pagina, tamanho=tamanho)


def compor(
    cadastro: list[dict[str, Any]],
    entregas_por_caso: dict[str, list[dict[str, Any]]],
    pagina: int = 1,
    tamanho: int = TAMANHO_PADRAO,
) -> dict[str, Any]:
    """A mesma fila, a partir de dados já em mãos — sem tocar no banco (assim é testada)."""
    pagina = max(1, pagina)
    tamanho = max(1, min(100, tamanho))

    medidos: list[dict[str, Any]] = []
    for caso in cadastro:
        situacao = casos_ocr.situacao_de(caso, entregas_por_caso.get(str(caso["id"]), []))
        progresso = situacao.get("progresso")
        if not progresso:
            # Categoria que saiu do código: sem checklist não há progresso a medir.
            continue
        dias = _dias_desde(caso.get("atualizado_em") or caso.get("criado_em"))
        severidade = _severidade(progresso, dias)
        medidos.append(
            {
                "situacao": situacao,
                "severidade": severidade,
                "peso": _peso(severidade, progresso, dias),
            }
        )

    medidos.sort(key=lambda m: m["peso"])

    total = len(medidos)
    paginas = max(1, -(-total // tamanho))
    pagina = min(pagina, paginas)
    inicio = (pagina - 1) * tamanho
    da_pagina = medidos[inicio : inicio + tamanho]

    return {
        "situacoes": [m["situacao"] for m in da_pagina],
        "total": total,
        "pagina": pagina,
        "tamanho": tamanho,
        "paginas": paginas,
        "triagem": _triagem(medidos),
        "chegando_agora": _chegando_agora(medidos),
        "pedidos": _pedidos(medidos),
    }


def _triagem(medidos: list[dict[str, Any]]) -> dict[str, int]:
    """Contagens da carteira inteira — nunca só da página exibida."""
    progressos = [m["situacao"]["progresso"] for m in medidos]
    return {
        "travados": sum(1 for m in medidos if m["severidade"] == "critico"),
        "aConferir": sum(p["itens_a_conferir"] for p in progressos),
        "pedidosProntos": sum(1 for p in progressos if p["obrigatorios_pendentes"] > 0),
        "completos": sum(1 for p in progressos if p["pronto"]),
        "ativos": len(medidos),
    }


def _chegando_agora(medidos: list[dict[str, Any]], quantas: int = 4) -> list[dict[str, Any]]:
    """As últimas entregas recebidas no escritório, com o cliente de cada uma."""
    vistas: set[str] = set()
    todas: list[dict[str, Any]] = []
    for medido in medidos:
        situacao = medido["situacao"]
        for item in situacao["itens"]:
            for entrega in item["entregas"]:
                # Uma CIN que atende RG e CPF aparece em dois itens.
                if entrega["id"] in vistas:
                    continue
                vistas.add(entrega["id"])
                todas.append({"entrega": entrega, "cliente": situacao["caso"]["cliente"]})
    todas.sort(key=lambda t: str(t["entrega"]["criado_em"]), reverse=True)
    return todas[:quantas]


def _pedidos(medidos: list[dict[str, Any]], quantos: int = 4) -> list[dict[str, Any]]:
    """Casos com documento obrigatório faltando, na mesma ordem de risco da fila."""
    saida = []
    for medido in medidos:
        progresso = medido["situacao"]["progresso"]
        if progresso["obrigatorios_pendentes"] <= 0:
            continue
        caso = medido["situacao"]["caso"]
        saida.append(
            {
                "casoId": str(caso["id"]),
                "cliente": caso["cliente"],
                "faltantes": progresso["obrigatorios_pendentes"],
                "reenvios": progresso["itens_a_conferir"],
            }
        )
        if len(saida) == quantos:
            break
    return saida
