"""Regras do caso: status de cada item do checklist e o pedido para o cliente.

A tela do advogado responde três perguntas: o que já chegou, o que falta e o que
chegou com problema. Tudo aqui é derivado das entregas — nada de status guardado
à mão, que sairia do lugar assim que alguém apagasse uma entrega.
"""

from __future__ import annotations

from typing import Any

from . import armazenamento, categorias
from .categorias import ItemChecklist
from .extractors import ROTULOS_TIPO

# Status possíveis de um item do checklist.
PENDENTE = "pendente"          # nada foi enviado
PROCESSANDO = "processando"    # chegou e está sendo lido pelo OCR
CONFERIR = "conferir"          # chegou, mas com ressalva (ilegível ou tipo trocado)
ENTREGUE = "entregue"          # chegou e passou na validação


def _esta_pronta(entrega: dict[str, Any]) -> bool:
    return entrega.get("status_proc", "pronto") == "pronto"


def _status_do_item(entregas: list[dict[str, Any]]) -> str:
    if not entregas:
        return PENDENTE

    prontas = [e for e in entregas if _esta_pronta(e)]

    # Basta uma entrega boa: "atestados médicos" pode ter 5 arquivos e 1 ruim.
    if any(
        (e["dados_utilizaveis"] or e.get("confirmado_manual", False))
        and e["tipo_confere"] is not False
        for e in prontas
    ):
        return ENTREGUE

    # Nenhuma boa ainda, mas há leitura em curso: não é pendência nem ressalva.
    if any(e.get("status_proc") == "processando" for e in entregas):
        return PROCESSANDO

    # Sobrou o que chegou e não presta: lido com ressalva ou falho na leitura.
    # Em ambos o arquivo existe, então é "conferir" — nunca "pendente", que
    # significaria que o cliente não mandou nada.
    return CONFERIR


def _alertas_da_entrega(entrega: dict[str, Any], item: ItemChecklist) -> list[str]:
    alertas: list[str] = []

    # Ainda sem leitura: os campos de validação estão vazios, e lê-los produziria
    # o alerta de "não foi possível extrair" para um arquivo que só está na fila.
    estado = entrega.get("status_proc", "pronto")
    if estado == "processando":
        return ["Documento recebido. A leitura está em andamento."]
    if estado == "erro":
        return [
            "Não foi possível ler este arquivo: "
            + (entrega.get("erro_proc") or "falha no processamento.")
        ]

    if entrega["tipo_confere"] is False:
        codigo = entrega.get("tipo_detectado")
        # ROTULOS_TIPO traduz "cnh" -> "CNH (Carteira Nacional de Habilitação)".
        legivel = ROTULOS_TIPO.get(codigo, codigo) if codigo else "algo não identificado"
        alertas.append(
            f"Enviado como '{item.nome}', mas o documento parece ser {legivel}. "
            "Confira se não houve troca de arquivo."
        )
    if len(entrega.get("itens_atendidos") or []) > 1 and not entrega.get("confirmado_manual"):
        rotulo = ROTULOS_TIPO.get(entrega.get("tipo_detectado"), entrega.get("tipo_detectado"))
        alertas.append(
            f"Este arquivo foi reconhecido como {rotulo} e traz RG e CPF, "
            "então vale para os dois itens do checklist."
        )
    if entrega.get("confirmado_manual"):
        alertas.append("Identidade unificada confirmada manualmente para RG e CPF.")
    elif not entrega["dados_utilizaveis"]:
        score = entrega.get("score_legibilidade")
        sufixo = f" (legibilidade {score}%)" if score is not None else ""
        alertas.append(f"Não foi possível extrair os dados com segurança{sufixo}.")

    return alertas


def montar_situacao(caso_id: str) -> dict[str, Any] | None:
    """Caso + checklist com o status de cada item + contagens de progresso."""
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        return None

    categoria = categorias.obter(caso["categoria"])
    if categoria is None:
        # A categoria saiu do código mas o caso continua no banco.
        return {
            "caso": caso,
            "categoria": None,
            "erro": f"Categoria '{caso['categoria']}' não existe mais no sistema.",
            "itens": [],
        }

    entregas = armazenamento.listar_entregas(caso_id)
    por_item: dict[str, list[dict[str, Any]]] = {}
    for entrega in entregas:
        # Uma CIN pode ter sido marcada para atender RG e CPF com o mesmo arquivo.
        for item_codigo in entrega["itens_atendidos"]:
            por_item.setdefault(item_codigo, []).append(entrega)

    itens = []
    for item in categoria.itens:
        do_item = por_item.get(item.codigo, [])
        status = _status_do_item(do_item)
        itens.append(
            {
                **item.to_dict(),
                "status": status,
                "entregas": [
                    {**e, "alertas": _alertas_da_entrega(e, item)} for e in do_item
                ],
            }
        )

    obrigatorios = [i for i in itens if i["obrigatorio"]]
    entregues_obrig = [i for i in obrigatorios if i["status"] == ENTREGUE]
    pendentes_obrig = [i for i in obrigatorios if i["status"] == PENDENTE]
    conferir = [i for i in itens if i["status"] == CONFERIR]

    return {
        "caso": caso,
        "categoria": {
            "codigo": categoria.codigo,
            "nome": categoria.nome,
            "descricao": categoria.descricao,
        },
        "itens": itens,
        "progresso": {
            "obrigatorios_total": len(obrigatorios),
            "obrigatorios_entregues": len(entregues_obrig),
            "obrigatorios_pendentes": len(pendentes_obrig),
            "opcionais_total": len(itens) - len(obrigatorios),
            "opcionais_entregues": sum(
                1 for i in itens if not i["obrigatorio"] and i["status"] == ENTREGUE
            ),
            "itens_a_conferir": len(conferir),
            "percentual_obrigatorios": (
                round(len(entregues_obrig) / len(obrigatorios) * 100) if obrigatorios else 100
            ),
            "pronto": not pendentes_obrig and not conferir,
        },
    }


# Documentos que provam identidade e CPF no mesmo arquivo. A CIN traz o CPF como
# número principal e substitui o RG por lei; a CNH imprime os dois. Um cartão de
# CPF NÃO entra aqui: ele não carrega RG nenhum, e aceitá-lo marcaria a
# identidade como entregue sem que exista documento de identidade no caso.
TIPOS_IDENTIDADE_UNIFICADA = {"cin", "cnh"}


def _campo_valido(extracao: dict[str, Any], nome: str) -> bool:
    campo = next((c for c in extracao.get("campos", []) if c["nome"] == nome), None)
    return bool(
        campo and str(campo.get("valor", "")).strip() and campo.get("valido") is not False
    )


def cobre_rg_e_cpf(extracao: dict[str, Any]) -> bool:
    """O arquivo comprova identidade E CPF de uma vez?

    Decidido pelos dados extraídos, não só pelo tipo: uma CNH ilegível em que o
    CPF não saiu não pode dar o item CPF por entregue.
    """
    tipo = extracao.get("tipo", {}).get("detectado")
    if tipo not in TIPOS_IDENTIDADE_UNIFICADA:
        return False
    if not _campo_valido(extracao, "cpf"):
        return False
    # Na CIN não há número de RG a conferir — o próprio documento é a identidade.
    return True if tipo == "cin" else _campo_valido(extracao, "rg")


def tipo_confere(
    item: ItemChecklist,
    tipo_detectado: str | None,
    identidade_unificada: bool = False,
) -> bool | None:
    """O arquivo enviado é mesmo o documento pedido?

    `None` quando não dá para afirmar: ou o item não tem classificador, ou o OCR
    não reconheceu o tipo. Só devolve False quando o classificador reconheceu com
    confiança um tipo diferente do esperado — aí houve troca de arquivo mesmo.
    """
    if item.tipo_ocr is None:
        return None
    if not tipo_detectado or tipo_detectado == "desconhecido":
        return None
    if identidade_unificada and item.tipo_ocr in {"rg", "cpf"}:
        # Antes só a CIN valia; a CNH entrou porque imprime RG e CPF juntos.
        return tipo_detectado in TIPOS_IDENTIDADE_UNIFICADA
    return tipo_detectado == item.tipo_ocr


def itens_para_identidade_unificada(categoria: categorias.Categoria, item: ItemChecklist) -> list[str]:
    """Itens atendidos por uma CIN ou CNH: RG e CPF, uma única vez cada.

    Fora dos documentos que trazem os dois, RG e CPF continuam independentes,
    como nos documentos antigos.
    """
    if item.tipo_ocr not in {"rg", "cpf"}:
        raise ValueError("A identidade unificada só pode ser usada nos itens RG ou CPF.")

    itens = [i.codigo for i in categoria.itens if i.tipo_ocr in {"rg", "cpf"}]
    if len(itens) != 2:
        raise ValueError("Este checklist não possui os itens RG e CPF para vincular.")
    return itens


# ------------------------------------------------------- pedido ao cliente


def _linha_do_item(item: dict[str, Any]) -> str:
    observacao = item.get("observacao", "").strip()
    complemento = f" — {observacao}" if observacao else ""
    return f"- {item['nome']}{complemento}"


def _motivo_para_o_cliente(item: dict[str, Any]) -> str:
    """Por que reenviar, em linguagem de cliente.

    Os alertas de `_alertas_da_entrega` são para a tela do advogado e citam nome
    de classificador ("o sistema leu como 'cpf'"). Isso não vai numa mensagem de
    WhatsApp para o cliente.
    """
    entregas = item["entregas"]

    if any(e["tipo_confere"] is False for e in entregas):
        return "o arquivo enviado parece ser de outro documento"
    if any(not e["dados_utilizaveis"] for e in entregas):
        return "a foto não ficou legível o suficiente"
    return "precisamos de uma nova cópia"


def visao_do_cliente(situacao: dict[str, Any]) -> dict[str, Any]:
    """O checklist como o cliente deve vê-lo, no portal.

    Recorte deliberado. Fica de fora:
      - os alertas de `_alertas_da_entrega`, escritos para o advogado e cheios de
        termo de classificador ("o sistema leu como 'cpf'");
      - a extração (CPF, RG, nome lidos), que é dado pessoal que o cliente já
        tem e que não precisa trafegar de volta;
      - o caminho dos arquivos e os identificadores internos das entregas.

    Fica o que o cliente precisa para agir: o que já chegou, o que falta e, para
    o que precisa refazer, o motivo em português de gente.
    """
    itens = []
    for item in situacao["itens"]:
        entregas = item["entregas"]
        precisa_refazer = item["status"] == CONFERIR
        itens.append(
            {
                "codigo": item["codigo"],
                "nome": item["nome"],
                "observacao": item.get("observacao", ""),
                "obrigatorio": item["obrigatorio"],
                "status": item["status"],
                "enviados": len(entregas),
                "motivo": _motivo_para_o_cliente(item) if precisa_refazer else "",
            }
        )

    progresso = situacao["progresso"]
    return {
        "cliente": situacao["caso"]["cliente"],
        "categoria": (situacao.get("categoria") or {}).get("nome", ""),
        "itens": itens,
        "progresso": {
            "obrigatorios_total": progresso["obrigatorios_total"],
            "obrigatorios_entregues": progresso["obrigatorios_entregues"],
            "percentual": progresso["percentual_obrigatorios"],
            "pronto": progresso["pronto"],
        },
    }


def montar_pedido(caso_id: str, incluir_opcionais: bool = False) -> dict[str, Any] | None:
    """Texto pronto para o advogado mandar ao cliente com o que ainda falta."""
    situacao = montar_situacao(caso_id)
    if situacao is None or situacao.get("categoria") is None:
        return None

    itens = situacao["itens"]
    faltando_obrig = [i for i in itens if i["obrigatorio"] and i["status"] == PENDENTE]
    faltando_opc = [i for i in itens if not i["obrigatorio"] and i["status"] == PENDENTE]
    reenviar = [i for i in itens if i["status"] == CONFERIR]

    cliente = situacao["caso"]["cliente"]
    partes = [f"Olá, {cliente}!", ""]

    if not faltando_obrig and not reenviar:
        partes.append(
            "Recebemos todos os documentos obrigatórios do seu processo. Obrigado!"
        )
    else:
        partes.append(
            "Para dar andamento ao seu processo, precisamos dos documentos abaixo."
        )

    if faltando_obrig:
        partes += ["", "DOCUMENTOS OBRIGATÓRIOS QUE AINDA FALTAM:"]
        partes += [_linha_do_item(i) for i in faltando_obrig]

    if reenviar:
        partes += ["", "DOCUMENTOS QUE PRECISAM SER REENVIADOS:"]
        partes += [f"- {i['nome']} — {_motivo_para_o_cliente(i)}" for i in reenviar]

    if incluir_opcionais and faltando_opc:
        partes += ["", "SE VOCÊ TIVER, ENVIE TAMBÉM (opcionais, mas ajudam no processo):"]
        partes += [_linha_do_item(i) for i in faltando_opc]

    partes += [
        "",
        "Dicas para a foto sair legível:",
        "- Coloque o documento sobre uma superfície de cor contrastante;",
        "- Fotografe em local bem iluminado, sem sombra e sem flash;",
        "- Enquadre o documento inteiro, preenchendo a maior parte da tela;",
        "- Confira se dá para ler todos os números antes de enviar.",
    ]

    return {
        "texto": "\n".join(partes),
        "faltando_obrigatorios": [i["nome"] for i in faltando_obrig],
        "faltando_opcionais": [i["nome"] for i in faltando_opc],
        "reenviar": [i["nome"] for i in reenviar],
        "progresso": situacao["progresso"],
    }
