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

import unicodedata
from datetime import datetime, timezone
from typing import Any

from . import armazenamento, banco
from . import casos as casos_ocr

#: Dias parados a partir dos quais um caso sem documento vira cobrança.
DIAS_PARA_COBRAR = 7

#: A partir daqui, mesmo COM follow-up automático ligado, o silêncio já pede uma
#: ligação: o WhatsApp não trouxe os documentos e a espera virou risco.
DIAS_PARA_LIGAR = 10

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


def _normalizar(texto: str) -> str:
    """Minúsculas, sem acento — para buscar 'joão' achando 'JOAO' e vice-versa."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", str(texto or "")) if unicodedata.category(c) != "Mn"
    )
    return " ".join(sem_acento.lower().split())


def _passa_situacao(medido: dict[str, Any], filtro: str) -> bool:
    """O mesmo vocabulário dos chips da tela (`useCarteira.ts`), agora no servidor.

    `pedido` e `pronto` olham o progresso; os demais são a própria severidade.
    """
    if filtro in ("", "todos"):
        return True
    progresso = medido["situacao"]["progresso"]
    if filtro == "pedido":
        return progresso["obrigatorios_pendentes"] > 0
    if filtro == "pronto":
        return bool(progresso["pronto"])
    return medido["severidade"] == filtro


#: Como ordenar a fila. "risco" é o padrão histórico (o que pode travar primeiro).
ORDENS = ("risco", "recente", "parado", "nome")


def montar(
    pagina: int = 1,
    tamanho: int = TAMANHO_PADRAO,
    *,
    busca: str = "",
    categoria: str = "",
    situacao: str = "",
    ordenar: str = "risco",
) -> dict[str, Any]:
    """A página pedida da fila, mais os números que valem para a carteira toda.

    Duas consultas numa conexão só — o banco é remoto e o handshake custa mais que as
    leituras (ver `banco.sessao`).
    """
    with banco.sessao():
        cadastro = armazenamento.listar_casos()
        entregas_por_caso = armazenamento.entregas_de_todos_os_casos()
    return compor(
        cadastro,
        entregas_por_caso,
        pagina=pagina,
        tamanho=tamanho,
        busca=busca,
        categoria=categoria,
        situacao=situacao,
        ordenar=ordenar,
    )


def compor(
    cadastro: list[dict[str, Any]],
    entregas_por_caso: dict[str, list[dict[str, Any]]],
    pagina: int = 1,
    tamanho: int = TAMANHO_PADRAO,
    *,
    busca: str = "",
    categoria: str = "",
    situacao: str = "",
    ordenar: str = "risco",
) -> dict[str, Any]:
    """A mesma fila, a partir de dados já em mãos — sem tocar no banco (assim é testada).

    Os filtros (`busca`, `categoria`, `situacao`) recortam a LISTA e a paginação; os
    contadores do topo e os painéis laterais continuam medindo a carteira inteira, para
    não mentir sobre o tamanho do escritório quando um filtro está ativo.
    """
    pagina = max(1, pagina)
    tamanho = max(1, min(100, tamanho))

    medidos: list[dict[str, Any]] = []
    for caso in cadastro:
        situacao_caso = casos_ocr.situacao_de(caso, entregas_por_caso.get(str(caso["id"]), []))
        progresso = situacao_caso.get("progresso")
        if not progresso:
            # Categoria que saiu do código: sem checklist não há progresso a medir.
            continue
        dias = _dias_desde(caso.get("atualizado_em") or caso.get("criado_em"))
        severidade = _severidade(progresso, dias)
        medidos.append(
            {
                "situacao": situacao_caso,
                "severidade": severidade,
                "peso": _peso(severidade, progresso, dias),
                "dias": dias,
            }
        )

    medidos.sort(key=lambda m: m["peso"])

    # Vocabulário das categorias presentes, para a tela oferecer só o que existe.
    categorias_presentes = _categorias_presentes(medidos)

    # ---- filtragem: recorta a lista, preserva a medição da carteira inteira ----
    filtrados = list(medidos)
    if situacao:
        filtrados = [m for m in filtrados if _passa_situacao(m, situacao)]
    if categoria:
        filtrados = [
            m for m in filtrados if str(m["situacao"]["caso"].get("categoria") or "") == categoria
        ]
    alvo = _normalizar(busca)
    if alvo:
        def casa(m: dict[str, Any]) -> bool:
            caso = m["situacao"]["caso"]
            campos = " ".join(
                _normalizar(v)
                for v in (
                    caso.get("cliente"),
                    caso.get("observacao"),
                    (m["situacao"].get("categoria") or {}).get("nome"),
                    caso.get("categoria"),
                )
            )
            return all(termo in campos for termo in alvo.split())

        filtrados = [m for m in filtrados if casa(m)]

    _ordenar(filtrados, ordenar)

    total = len(filtrados)
    paginas = max(1, -(-total // tamanho))
    pagina = min(pagina, paginas)
    inicio = (pagina - 1) * tamanho
    da_pagina = filtrados[inicio : inicio + tamanho]

    return {
        "situacoes": [m["situacao"] for m in da_pagina],
        "total": total,
        "pagina": pagina,
        "tamanho": tamanho,
        "paginas": paginas,
        "categorias": categorias_presentes,
        "triagem": _triagem(medidos),
        "chegando_agora": _chegando_agora(medidos),
        "pedidos": _pedidos(medidos),
    }


def _ordenar(medidos: list[dict[str, Any]], ordenar: str) -> None:
    """Reordena no lugar. Já vem ordenado por risco; só mexe se pedirem outra ordem."""
    if ordenar == "recente":
        medidos.sort(key=lambda m: m["dias"])  # menos dias parado = mais recente
    elif ordenar == "parado":
        medidos.sort(key=lambda m: m["dias"], reverse=True)
    elif ordenar == "nome":
        medidos.sort(key=lambda m: _normalizar(m["situacao"]["caso"].get("cliente")))
    # "risco" (ou desconhecido): mantém a ordem por peso já aplicada.


def _categorias_presentes(medidos: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Categorias que aparecem na carteira, com código e nome, sem repetir."""
    vistas: dict[str, str] = {}
    for m in medidos:
        caso = m["situacao"]["caso"]
        codigo = str(caso.get("categoria") or "")
        if not codigo or codigo in vistas:
            continue
        vistas[codigo] = (m["situacao"].get("categoria") or {}).get("nome") or codigo
    return [{"codigo": c, "nome": n} for c, n in sorted(vistas.items(), key=lambda kv: _normalizar(kv[1]))]


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


# ---------------------------------------------------- RELATÓRIO DE FOLLOW-UP
# Visão operacional para o atendimento: quem tem documento obrigatório pendente
# e — pela regra abaixo — precisa de LIGAÇÃO, porque o follow-up automático por
# WhatsApp não está trazendo os documentos.


def _cobrancas_por_caso() -> dict[str, dict[str, Any]]:
    """Estado do follow-up automático (cobrança) de cada caso, em uma consulta."""
    with banco.conectar() as con:
        linhas = con.execute(
            "SELECT caso_id, ativa, telefone, ultimo_envio_em, ultimo_erro FROM cobrancas_documentos"
        ).fetchall()
    return {str(l["caso_id"]): dict(l) for l in linhas}


def _ultimas_ligacoes_por_caso() -> dict[str, dict[str, Any]]:
    with banco.conectar() as con:
        linhas = con.execute(
            """
            SELECT caso_id, id, atendente_id, atendente_nome, realizada_em, criado_em
              FROM (
                    SELECT caso_id, id, atendente_id, atendente_nome, realizada_em, criado_em,
                           ROW_NUMBER() OVER (
                               PARTITION BY caso_id ORDER BY realizada_em DESC, id DESC
                           ) AS posicao
                      FROM ligacoes
                   ) AS ordenadas
             WHERE posicao = 1
            """
        ).fetchall()
    return {str(linha["caso_id"]): dict(linha) for linha in linhas}


def _precisa_ligar(
    telefone: str,
    cobranca: dict[str, Any] | None,
    dias: int,
    ultima_ligacao: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Quando o follow-up por WhatsApp não resolve e um humano tem de ligar.

    Regra (operacional, não é ranking de cliente):
      - sem telefone → só dá para ligar;
      - último envio do follow-up falhou → o WhatsApp não está chegando;
      - follow-up desligado e caso parado além do prazo de cobrança;
      - follow-up ligado, mas parado tempo demais mesmo assim.
    """
    if ultima_ligacao:
        return False, "Ligação registrada."
    if not telefone:
        return True, "Sem telefone cadastrado — contato só por ligação."
    if cobranca and str(cobranca.get("ultimo_erro") or "").strip():
        return True, "O follow-up por WhatsApp falhou no último envio."
    ativa = bool(cobranca and cobranca.get("ativa"))
    if not ativa and dias >= DIAS_PARA_COBRAR:
        return True, f"Sem follow-up automático e {dias} dias sem movimento."
    if ativa and dias >= DIAS_PARA_LIGAR:
        return True, f"{dias} dias sem os documentos, apesar do follow-up."
    return False, ""


def relatorio_follow_up() -> dict[str, Any]:
    """Clientes com documento obrigatório pendente, com telefone, faltantes e alerta.

    Só entra quem tem pendência OBRIGATÓRIA. Ordena os que precisam de ligação
    primeiro e, entre eles, o que está parado há mais tempo. É o retrato do
    follow-up; a decisão de ligar é de quem atende.
    """
    with banco.sessao():
        cadastro = armazenamento.listar_casos()
        entregas_por_caso = armazenamento.entregas_de_todos_os_casos()
        cobrancas = _cobrancas_por_caso()
        ligacoes = _ultimas_ligacoes_por_caso()

    clientes: list[dict[str, Any]] = []
    for caso in cadastro:
        situacao_caso = casos_ocr.situacao_de(caso, entregas_por_caso.get(str(caso["id"]), []))
        progresso = situacao_caso.get("progresso")
        if not progresso or progresso.get("obrigatorios_pendentes", 0) == 0:
            continue
        faltantes = [
            i["nome"]
            for i in situacao_caso.get("itens", [])
            if i.get("obrigatorio") and i.get("status") == casos_ocr.PENDENTE
        ]
        dias = _dias_desde(caso.get("atualizado_em") or caso.get("criado_em"))
        telefone = str(caso.get("telefone") or "").strip()
        cobranca = cobrancas.get(str(caso["id"]))
        ultima_ligacao = ligacoes.get(str(caso["id"]))
        precisa, motivo = _precisa_ligar(telefone, cobranca, dias, ultima_ligacao)
        clientes.append(
            {
                "caso_id": str(caso["id"]),
                "cliente": str(caso.get("cliente") or ""),
                "telefone": telefone,
                "documentos_faltantes": faltantes,
                "faltantes_total": len(faltantes),
                "dias_parado": dias,
                "follow_up_ativo": bool(cobranca and cobranca.get("ativa")),
                "precisa_ligar": precisa,
                "motivo_ligacao": motivo,
                "ultima_ligacao": ultima_ligacao,
            }
        )

    clientes.sort(key=lambda c: (not c["precisa_ligar"], -c["dias_parado"]))
    return {
        "clientes": clientes,
        "total": len(clientes),
        "precisam_ligar": sum(1 for c in clientes if c["precisa_ligar"]),
        "regra": (
            f"Liga quando: sem telefone; ou WhatsApp do follow-up falhou; ou sem "
            f"follow-up e {DIAS_PARA_COBRAR}+ dias parado; ou {DIAS_PARA_LIGAR}+ dias "
            f"parado mesmo com follow-up."
        ),
        "aviso": "Retrato operacional do follow-up; a decisão de ligar é de quem atende.",
    }
