"""Regras do caso: status de cada item do checklist e o pedido para o cliente.

A tela do advogado responde três perguntas: o que já chegou, o que falta e o que
chegou com problema. Tudo aqui é derivado das entregas — nada de status guardado
à mão, que sairia do lugar assim que alguém apagasse uma entrega.
"""

from __future__ import annotations

import re
import unicodedata
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import armazenamento, cache_leitura, categorias, conversao_pdf
from .categorias import ItemChecklist
from .extractors import RE_PIS, ROTULOS_TIPO

# Status possíveis de um item do checklist.
PENDENTE = "pendente"          # nada foi enviado
PROCESSANDO = "processando"    # chegou e está sendo lido pelo OCR
CONFERIR = "conferir"          # chegou, mas com ressalva (ilegível ou tipo trocado)
ENTREGUE = "entregue"          # chegou e passou na validação

PRIORIDADE_LISTAGEM = {
    PENDENTE: 0,
    PROCESSANDO: 0,
    CONFERIR: 1,
    ENTREGUE: 2,
}

#: A partir daqui a espera não é mais fila, é problema.
#:
#: Uma leitura leva de 4 a 30 segundos. Passados dez minutos no mesmo estado, o
#: que existe não é um documento na frente na fila — é o leitor fora do ar ou uma
#: mensagem perdida. `tasks.manutencao.recuperar_entregas_travadas` usa o mesmo
#: número para ir buscar essas entregas, e o alerta abaixo para parar de dizer
#: que está tudo normal enquanto não está.
MINUTOS_ESPERA_ANORMAL = 10


def _esta_pronta(entrega: dict[str, Any]) -> bool:
    return entrega.get("status_proc", "pronto") == "pronto"


def _aproveitavel(entrega: dict[str, Any]) -> bool:
    """A entrega cumpre o item, ou só ocupa espaço?

    `dados_utilizaveis` responde por documento CADASTRAL: ele vale quando os
    campos esperados saíram e passaram na validação. Só que o extrator conhece
    nove tipos de identidade, e o checklist tem trinta itens — CAT, laudo,
    atestado, contracheque, CNIS e procuração não têm campo estruturado nenhum,
    então `dados_utilizaveis` nasce False neles SEMPRE. Enquanto essa era a
    única pergunta, o arquivo certo, legível e no item certo mantinha o item em
    "a conferir" para todo o sempre, e o cliente lia "precisa reenviar".

    `texto_utilizavel` é o sinal que o pipeline calcula para esses: a imagem é
    legível e o OCR extraiu texto de verdade. É o que o advogado usaria para
    dizer "chegou" — ele abre o laudo e lê.
    """
    return bool(
        entrega.get("dados_utilizaveis")
        or entrega.get("confirmado_manual", False)
        or entrega.get("texto_utilizavel")
    )


def _status_do_item(entregas: list[dict[str, Any]]) -> str:
    if not entregas:
        return PENDENTE

    prontas = [e for e in entregas if _esta_pronta(e)]

    # Basta uma entrega boa: "atestados médicos" pode ter 5 arquivos e 1 ruim.
    if any(_aproveitavel(e) and e["tipo_confere"] is not False for e in prontas):
        return ENTREGUE

    # Nenhuma boa ainda, mas há leitura em curso: não é pendência nem ressalva.
    if any(e.get("status_proc") in {"na_fila", "processando"} for e in entregas):
        return PROCESSANDO

    # Sobrou o que chegou e não presta: lido com ressalva ou falho na leitura.
    # Em ambos o arquivo existe, então é "conferir" — nunca "pendente", que
    # significaria que o cliente não mandou nada.
    return CONFERIR


def _esperando_ha_muito(entrega: dict[str, Any]) -> bool:
    """A entrega passou de `MINUTOS_ESPERA_ANORMAL` sem ser lida?

    Medido por `criado_em`, que é o único carimbo que a entrega tem — não há
    coluna de "última tentativa". Como só é consultado para entrega ainda não
    lida, `criado_em` é justamente o momento em que ela entrou na fila.

    `criado_em` ausente ou ilegível responde `False`: um formato inesperado não
    pode virar alarme numa entrega que acabou de chegar.
    """
    bruto = entrega.get("criado_em")
    if not bruto:
        return False
    try:
        criado = datetime.fromisoformat(str(bruto))
    except ValueError:
        return False
    if criado.tzinfo is None:
        criado = criado.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - criado > timedelta(minutes=MINUTOS_ESPERA_ANORMAL)


def _avisos_da_entrega(entrega: dict[str, Any], item: ItemChecklist) -> list[dict[str, str]]:
    """Cada aviso da tela do advogado, com um `tom` que diz se é problema ou nota.

    Nem todo aviso é alerta. "Classificado pela leitura do texto", "traz RG e
    CPF", "identidade confirmada" são NOTAS — o advogado lê e segue. Pintá-las de
    amarelo, como problema, foi o que encheu a tela de aviso e treinou o olho a
    ignorar todos, inclusive a troca de arquivo que importa. Por isso o `tom`:

      - "info": nota de rotina, mostrada quieta (sem amarelo).
      - "atencao": problema que pede conferência (foto ilegível, possível troca).
      - "critico": falha dura (não deu para ler o arquivo).

    `_alertas_da_entrega` continua devolvendo só os textos, para quem só quer a
    lista antiga de strings.
    """
    def info(texto: str) -> dict[str, str]:
        return {"texto": texto, "tom": "info"}

    def atencao(texto: str) -> dict[str, str]:
        return {"texto": texto, "tom": "atencao"}

    def critico(texto: str) -> dict[str, str]:
        return {"texto": texto, "tom": "critico"}

    avisos: list[dict[str, str]] = []

    # Ainda sem leitura: os campos de validação estão vazios, e lê-los produziria
    # o alerta de "não foi possível extrair" para um arquivo que só está na fila.
    estado = entrega.get("status_proc", "pronto")
    if estado in {"na_fila", "processando"}:
        if _esperando_ha_muito(entrega):
            # A mensagem antiga ("aguardando a vez na fila") continuava serena
            # depois de horas paradas, e era o único sinal que o advogado tinha.
            # Quem repara é `recuperar_entregas_travadas`, a cada 5 minutos.
            return [
                atencao(
                    "Este documento está há mais de "
                    f"{MINUTOS_ESPERA_ANORMAL} minutos esperando para ser lido — mais que o "
                    "normal. O sistema tenta de novo sozinho; se não sair daqui, o leitor "
                    "de documentos está fora do ar."
                )
            ]
        if estado == "na_fila":
            return [info("Documento recebido e aguardando a vez na fila de leitura.")]
        return [info("Documento recebido. A leitura está em andamento.")]
    if estado == "erro":
        return [
            critico(
                "Não foi possível ler este arquivo: "
                + (entrega.get("erro_proc") or "falha no processamento.")
            )
        ]

    if entrega["tipo_confere"] is False:
        codigo = entrega.get("tipo_detectado")
        # ROTULOS_TIPO traduz "cnh" -> "CNH (Carteira Nacional de Habilitação)".
        legivel = ROTULOS_TIPO.get(codigo, codigo) if codigo else "algo não identificado"
        avisos.append(
            atencao(
                f"Enviado como '{item.nome}', mas o documento parece ser {legivel}. "
                "Confira se não houve troca de arquivo."
            )
        )
    if len(entrega.get("itens_atendidos") or []) > 1 and not entrega.get("confirmado_manual"):
        rotulo = ROTULOS_TIPO.get(entrega.get("tipo_detectado"), entrega.get("tipo_detectado"))
        avisos.append(
            info(
                f"Este arquivo foi reconhecido como {rotulo} e traz RG e CPF, "
                "então vale para os dois itens do checklist."
            )
        )
    if entrega.get("confirmado_manual"):
        avisos.append(info("Identidade unificada confirmada manualmente para RG e CPF."))
    elif not entrega["dados_utilizaveis"] and item.tipo_ocr is not None:
        # Só para item cadastral: cobrar "campos extraídos" de um laudo médico é
        # cobrar o que o extrator nunca teve como dar (ver `_aproveitavel`).
        score = entrega.get("score_legibilidade")
        sufixo = f" (legibilidade {score}%)" if score is not None else ""
        avisos.append(atencao(f"Não foi possível extrair os dados com segurança{sufixo}."))
    elif not entrega["dados_utilizaveis"] and not entrega.get("texto_utilizavel"):
        score = entrega.get("score_legibilidade")
        sufixo = f" (legibilidade {score}%)" if score is not None else ""
        avisos.append(
            atencao(f"Não foi possível extrair texto aproveitável deste arquivo{sufixo}.")
        )

    origem = entrega.get("roteamento_origem")
    motivo = (entrega.get("roteamento_motivo") or "").strip()
    if origem == "deterministico":
        avisos.append(
            info(
                "Este arquivo foi encaminhado a este item pela leitura do documento"
                + (f": {motivo}" if motivo else ".")
            )
        )
        if entrega.get("tipo_detectado") == "ctps":
            avisos.append(
                atencao(
                    "Se não for carteira de trabalho (por exemplo CAT ou contracheque), "
                    "use «Mover para outro item» abaixo e escolha o documento certo."
                )
            )
    elif origem == "semantico":
        # Vem de modelo de linguagem, e a tela precisa dizer isso com todas as
        # letras: é a única fonte que existe para CAT, laudo e contracheque. É
        # nota de rotina, não problema — fica em tom "info".
        avisos.append(
            info(
                "Classificado automaticamente pela leitura do texto — confira"
                + (f": {motivo}" if motivo else ".")
            )
        )
    elif origem == "humano" and motivo:
        avisos.append(info(f"Movido para este item por: {motivo}"))
    elif origem == "escolha" and motivo:
        # Formatos sem OCR continuam aceitos no item escolhido. A tela interna
        # precisa deixar claro que o original foi preservado, mas não lido.
        avisos.append(info(motivo))

    return avisos


def _alertas_da_entrega(entrega: dict[str, Any], item: ItemChecklist) -> list[str]:
    """Só os textos dos avisos — compatível com quem espera lista de strings."""
    return [aviso["texto"] for aviso in _avisos_da_entrega(entrega, item)]


def _alertas_da_triagem(entrega: dict[str, Any]) -> list[str]:
    """O que dizer sobre um arquivo que chegou sem destino."""
    estado = entrega.get("status_proc", "pronto")
    if estado in {"na_fila", "processando"}:
        return ["Documento recebido. A leitura está em andamento."]
    if estado == "erro":
        return [
            "Não foi possível ler este arquivo: "
            + (entrega.get("erro_proc") or "falha no processamento.")
        ]
    motivo = (entrega.get("roteamento_motivo") or "").strip()
    if entrega.get("roteamento_origem") == "duplicidade":
        # Aqui o destino É conhecido — o que falta é alguém confirmar que não é
        # repetição. Dizer "não foi possível identificar" mandaria procurar o
        # problema no lugar errado.
        return [
            (motivo or "Este documento parece repetir outro já enviado ao caso.")
            + " Remova-o se for repetido; se não for, atribua-o ao item — o sistema "
            "pedirá confirmação."
        ]
    return [
        "Este documento foi lido, mas não foi possível dizer a que item do "
        "checklist ele responde. Escolha o item certo aqui ao lado."
        + (f" ({motivo})" if motivo else "")
    ]


def montar_situacao(caso_id: str) -> dict[str, Any] | None:
    """Caso + checklist com o status de cada item + contagens de progresso."""
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        return None
    return situacao_de(caso, armazenamento.listar_entregas(caso_id))


# ------------------------------------------------------------------ ---------
# "NADA PASSA DESPERCEBIDO": dado de item que falta, encontrado em OUTRO documento
#
# A carteira de trabalho é o caso clássico: o cliente não traz a CTPS, mas o
# número e o PIS dela aparecem no CNIS, no holerite, no TRCT, no contrato. O item
# fica "pendente" e ninguém percebe que a informação já está no caso — só em outro
# arquivo. Aqui, para o item que falta, varre-se o texto dos DEMAIS documentos e
# avisa-se onde o dado apareceu, sem dar o item por entregue (é indício, não a
# carteira em si — quem confere é o advogado).


def _norm_busca(texto: str) -> str:
    sem = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sem.upper())


_RE_CTPS_KW = re.compile(r"\bCTPS\b|CARTEIRA DE TRABALHO")
#: "CTPS nº 12345 série 678", "Carteira 12345/00678" — o número perto do rótulo.
_RE_CTPS_NUM = re.compile(r"(?:CTPS|CARTEIRA(?: DE TRABALHO)?)\D{0,25}(\d[\d./ -]{2,}\d)")
_RE_PIS_KW = re.compile(r"\bPIS\b|\bPASEP\b|\bNIT\b")


def _carteira_no_texto(texto: str) -> str | None:
    """Descreve o dado de carteira/PIS achado no texto, ou `None` se não houver."""
    t = _norm_busca(texto)
    partes: list[str] = []
    achou_numero = _RE_CTPS_NUM.search(t)
    if achou_numero:
        partes.append("CTPS nº " + achou_numero.group(1).strip()[:24])
    elif _RE_CTPS_KW.search(t):
        partes.append("menção à Carteira de Trabalho")
    # PIS só conta com o rótulo por perto: um número de 11 dígitos solto é tão
    # provável ser CPF quanto PIS, e indício errado é pior que indício nenhum.
    if _RE_PIS_KW.search(t):
        numero = RE_PIS.search(texto) or RE_PIS.search(t)
        partes.append("PIS " + numero.group(0).strip() if numero else "menção ao PIS/PASEP")
    # Mantém a ordem e remove repetição.
    return "; ".join(dict.fromkeys(partes)) or None


def _item_e_carteira(nome: str) -> bool:
    n = _norm_busca(nome)
    return "CTPS" in n or "CARTEIRA DE TRABALHO" in n


@cache_leitura.por_alguns_segundos(300)
def _carteira_em_outros_docs(caso_id: str, _assinatura: str) -> list[dict[str, str]]:
    """Onde a carteira/PIS aparece nos documentos do caso (fora uma CTPS própria).

    Lê o texto de cada entrega — caro, por isso cacheado pela assinatura do caso
    (o `atualizado_em`, que muda a cada documento novo). `_assinatura` entra na
    chave do cache; documento novo invalida sozinho.
    """
    achados: list[dict[str, str]] = []
    for entrega in armazenamento.listar_extracoes_do_caso(caso_id):
        extracao = entrega.get("extracao") or {}
        # Uma CTPS de verdade não é "outro documento" — é a própria carteira.
        if (extracao.get("tipo") or {}).get("detectado") == "ctps":
            continue
        texto = str(extracao.get("texto_completo") or "").strip()
        if not texto:
            continue
        dado = _carteira_no_texto(texto)
        if dado:
            achados.append(
                {"arquivo": str(entrega.get("arquivo") or "documento"), "dado": dado}
            )
    return achados


def anexar_observacoes_cruzadas(caso_id: str, situacao: dict[str, Any]) -> dict[str, Any]:
    """Para cada item PENDENTE de carteira, aponta em que documento o dado apareceu.

    Enriquece a situação NO LUGAR e a devolve. Só roda quando há de fato um item
    de carteira faltando — caso com a CTPS entregue nem toca no texto dos anexos.
    """
    itens = situacao.get("itens") or []
    pendentes = [i for i in itens if i.get("status") == PENDENTE and _item_e_carteira(i.get("nome", ""))]
    if not pendentes:
        return situacao
    caso = situacao.get("caso") or {}
    achados = _carteira_em_outros_docs(caso_id, str(caso.get("atualizado_em") or ""))
    if not achados:
        return situacao
    for item in pendentes:
        item["encontrado_em"] = achados
    return situacao


def situacao_de(caso: dict[str, Any], entregas: list[dict[str, Any]]) -> dict[str, Any]:
    """A mesma situação, a partir de dados já em mãos — sem tocar no banco.

    Existe para quem já leu caso e entregas em lote. O painel compara o caso aberto
    com os anteriores da categoria, e buscar as entregas de cada um deles de novo,
    um por um, custava uma ida ao banco por caso da amostra.
    """
    categoria = categorias.obter(caso["categoria"])
    if categoria is None:
        # A categoria saiu do código mas o caso continua no banco.
        return {
            "caso": caso,
            "categoria": None,
            "erro": f"Categoria '{caso['categoria']}' não existe mais no sistema.",
            "itens": [],
        }

    por_item: dict[str, list[dict[str, Any]]] = {}
    # Chegou e ninguém soube dizer a que item responde. Fica aqui, visível, com o
    # arquivo guardado — nunca marcado num item por chute (ver `app/roteamento.py`).
    em_triagem: list[dict[str, Any]] = []
    codigos_da_categoria = {item.codigo for item in categoria.itens}
    for entrega in entregas:
        atendidos = [c for c in entrega["itens_atendidos"] if c in codigos_da_categoria]
        if not atendidos:
            em_triagem.append(entrega)
            continue
        # Uma CIN pode ter sido marcada para atender RG e CPF com o mesmo arquivo.
        for item_codigo in atendidos:
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
                    {
                        **e,
                        # `avisos` traz o tom (info/atencao/critico) para a tela
                        # pintar só o que é problema; `alertas` fica como a lista
                        # de strings que o resto do código já consumia.
                        "avisos": (avisos := _avisos_da_entrega(e, item)),
                        "alertas": [a["texto"] for a in avisos],
                    }
                    for e in do_item
                ],
            }
        )

    obrigatorios = [i for i in itens if i["obrigatorio"]]
    entregues_obrig = [i for i in obrigatorios if i["status"] == ENTREGUE]
    # "Recebido" é diferente de "validado": um documento obrigatório já
    # anexado, porém ainda a conferir, não pode sumir da contagem do que o
    # escritório possui. Ele continua fora de `entregues`, que é a métrica de
    # segurança usada para liberar a petição.
    recebidos_obrig = [i for i in obrigatorios if i["status"] != PENDENTE]
    pendentes_obrig = [i for i in obrigatorios if i["status"] == PENDENTE]
    conferir = [i for i in itens if i["status"] == CONFERIR]
    return {
        "caso": caso,
        "categoria": {
            "codigo": categoria.codigo,
            "nome": categoria.nome,
            "descricao": categoria.descricao,
        },
        # A ordem operacional nasce no domínio e vale para todos os consumidores.
        # A numeração original continua em cada item e serve como desempate.
        "itens": ordenar_itens_para_listagem(itens),
        "triagem": [
            {**e, "alertas": _alertas_da_triagem(e)} for e in em_triagem
        ],
        "progresso": {
            "obrigatorios_total": len(obrigatorios),
            "obrigatorios_entregues": len(entregues_obrig),
            "obrigatorios_recebidos": len(recebidos_obrig),
            "obrigatorios_pendentes": len(pendentes_obrig),
            "opcionais_total": len(itens) - len(obrigatorios),
            "opcionais_entregues": sum(
                1 for i in itens if not i["obrigatorio"] and i["status"] == ENTREGUE
            ),
            "itens_a_conferir": len(conferir),
            "em_triagem": len(em_triagem),
            "percentual_obrigatorios": (
                round(len(entregues_obrig) / len(obrigatorios) * 100) if obrigatorios else 100
            ),
            # Documento na triagem ainda pode ser o obrigatório que falta: dizer
            # "está tudo pronto" com arquivo por identificar seria promessa vazia.
            "pronto": not pendentes_obrig and not conferir and not em_triagem,
        },
    }


def ordenar_itens_para_listagem(itens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Itens em ordem operacional, sem perder a numeração original do checklist."""
    return sorted(
        itens,
        key=lambda item: (
            PRIORIDADE_LISTAGEM.get(str(item.get("status") or ""), 99),
            0 if item.get("obrigatorio") else 1,
            int(item.get("numero") or 0),
            str(item.get("codigo") or ""),
        ),
    )


def documentos_pendentes_da_situacao(
    situacao: dict[str, Any],
    incluir_opcionais: bool = False,
) -> list[dict[str, Any]]:
    """Documentos que ainda exigem ação do cliente, prontos para reuso externo.

    Usa apenas os status já existentes do checklist. Documento em processamento
    não entra aqui: o cliente já enviou o arquivo, então uma cobrança automática
    não deve pedi-lo de novo antes da leitura terminar.
    """
    pendentes: list[dict[str, Any]] = []
    for item in situacao.get("itens") or []:
        obrigatorio = bool(item.get("obrigatorio"))
        status = str(item.get("status") or "")
        if not obrigatorio and not incluir_opcionais and status != CONFERIR:
            continue
        if status not in {PENDENTE, CONFERIR}:
            continue
        motivo = (
            _motivo_para_o_cliente(item)
            if status == CONFERIR and item.get("entregas")
            else "ainda não recebemos este documento"
        )
        pendentes.append(
            {
                "codigo": item.get("codigo"),
                "numero": item.get("numero"),
                "nome": item.get("nome"),
                "obrigatorio": obrigatorio,
                "status": status,
                "observacao": item.get("observacao", ""),
                "motivo": motivo,
            }
        )
    return ordenar_itens_para_listagem(pendentes)


def documentos_pendentes_do_caso(
    caso_id: str,
    incluir_opcionais: bool = False,
) -> dict[str, Any] | None:
    """Resumo dos documentos que ainda pedem ação do cliente neste caso."""
    situacao = montar_situacao(caso_id)
    if situacao is None or situacao.get("categoria") is None:
        return None
    caso = situacao["caso"]
    return {
        "caso": {
            "id": caso.get("id"),
            "cliente": caso.get("cliente"),
            "categoria": caso.get("categoria"),
            "telefone": caso.get("telefone", ""),
            "portal_ativo": bool(caso.get("portal_token")),
        },
        "categoria": situacao.get("categoria"),
        "pendentes": documentos_pendentes_da_situacao(situacao, incluir_opcionais),
        "progresso": situacao.get("progresso"),
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
    entregas = item.get("entregas") or []

    # Acesso tolerante, e não por gosto: `armazenamento._normalizar_entrega` já
    # trata `tipo_confere` AUSENTE (`if "tipo_confere" in registro`), então há
    # caminho em que a entrega chega sem a chave. Com `[...]` isso virava
    # `KeyError` dentro da montagem das pendências — ou seja, um 500 justamente na
    # lista que o atendente usa para cobrar e que alimenta a automação do
    # WhatsApp, por um campo que nem é o motivo principal.
    #
    # O padrão de `dados_utilizaveis` é `True` de propósito: sem informação, não
    # se acusa a foto de ilegível. Cai no motivo genérico, que é honesto.
    if any(e.get("tipo_confere") is False for e in entregas):
        return "o arquivo enviado parece ser de outro documento"
    if any(not e.get("dados_utilizaveis", True) for e in entregas):
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
    triagem = situacao.get("triagem") or []
    return {
        "cliente": situacao["caso"]["cliente"],
        "categoria": (situacao.get("categoria") or {}).get("nome", ""),
        "itens": itens,
        # Quantos arquivos o cliente mandou que o escritório ainda está
        # identificando. Sem isto o portal engolia o envio: o arquivo não
        # aparecia em item nenhum, e a tela ficava igual a antes de enviar.
        "em_analise": len([e for e in triagem if e.get("status_proc") != "erro"]),
        "processando": len(
            [e for e in triagem if e.get("status_proc") in {"na_fila", "processando"}]
        ),
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


# ------------------------------------------------- dossiê em ZIP


#: Caracteres que o Windows recusa em nome de arquivo. Um documento chamado
#: "RG (frente/verso).jpg" quebra o unzip do outro lado, e quem recebe o pacote
#: é o escritório — não dá para pedir que renomeie na mão.
_PROIBIDOS = str.maketrans({c: "-" for c in '\\/:*?"<>|'})


def _nome_no_pacote(indice: int, item_nome: str, arquivo: str) -> str:
    """`03 - Laudos medicos - foto.jpg`.

    O número vem primeiro porque o descompactador ordena por nome, e a ordem
    que interessa é a do checklist — quem abre o pacote está conferindo contra
    a lista de documentos, não procurando um arquivo específico.
    """
    limpo = str(item_nome or "Sem categoria").translate(_PROIBIDOS).strip()
    return f"{indice:02d} - {limpo} - {Path(arquivo).name.translate(_PROIBIDOS)}"


def montar_zip(caso_id: str, destino: Path) -> dict[str, Any] | None:
    """Junta num ZIP tudo que o cliente enviou. `None` se o caso não existe.

    O escritório baixava documento por documento, clicando em cada linha do
    checklist — trinta arquivos, trinta cliques, e a certeza de esquecer um.
    O pacote sai na ordem do checklist e com o nome do item em cada arquivo,
    porque do outro lado alguém vai conferir contra a mesma lista.

    Escreve em disco em vez de montar na memória: são fotos e PDFs de
    digitalização, e um caso instruído passa fácil de cem megabytes — segurar
    isso em RAM por requisição derruba o servidor no dia em que dois
    atendentes baixarem ao mesmo tempo.

    O que não existir mais no disco é PULADO e contado, nunca inventado: um ZIP
    silenciosamente incompleto é pior que um erro, porque ninguém confere o que
    não sabe que faltou.
    """
    situacao = montar_situacao(caso_id)
    if situacao is None:
        return None

    # A ordem é a do checklist, e cada entrega entra UMA vez — uma CIN que
    # atende RG e CPF é um arquivo só, e duplicá-lo faria o conferente procurar
    # diferença entre duas cópias idênticas.
    incluidos: dict[str, tuple[int, str]] = {}
    for item in situacao["itens"]:
        for entrega in item["entregas"]:
            incluidos.setdefault(entrega["id"], (item["numero"], item["nome"]))

    guardados: list[str] = []
    faltando: list[str] = []

    destino.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as pacote:
        usados: set[str] = set()
        for entrega_id, (numero, item_nome) in incluidos.items():
            entrega = armazenamento.obter_entrega(entrega_id)
            if entrega is None:
                continue
            caminho = armazenamento.caminho_duravel_da_entrega(entrega_id)
            if caminho is None:
                faltando.append(entrega["arquivo"])
                continue

            nome = _nome_no_pacote(numero, item_nome, entrega["arquivo"])
            # Dois arquivos com o mesmo nome no mesmo item: o ZIP aceita e o
            # descompactador sobrescreve um com o outro, calado.
            if nome in usados:
                base, ponto, ext = nome.rpartition(".")
                nome = f"{base} ({len(usados)}){ponto}{ext}" if ponto else f"{nome} ({len(usados)})"
            usados.add(nome)

            pacote.write(caminho, arcname=nome)
            guardados.append(nome)

    return {
        "arquivos": len(guardados),
        "faltando": faltando,
        "cliente": situacao["caso"]["cliente"],
        "pronto": situacao["progresso"]["pronto"],
    }


# ------------------------------------------- ZIP de uma seleção por classificação


class SelecaoInvalida(Exception):
    """Pedido de ZIP por classificação recusado inteiro.

    Motivos: um id que não é daquela classificação (item errado ou outro caso),
    ou seleção acima do teto de quantidade/tamanho. `status` é o código HTTP que
    a rota devolve — a regra do "por que recusou" mora aqui, não no `main`.
    """

    def __init__(self, mensagem: str, status: int = 400) -> None:
        super().__init__(mensagem)
        self.status = status


def _resolver_selecao(
    caso_id: str,
    classificacao: str,
    entrega_ids: list[str],
    *,
    limite_itens: int,
    limite_bytes: int,
) -> tuple[dict[str, Any], list[tuple[str, Path]], list[str], dict[str, dict[str, Any]], str] | None:
    """Valida e resolve uma seleção de entregas dentro de UMA classificação.

    Compartilhada por `montar_zip_selecao` e `montar_pdf_selecao`: as regras do
    que pode entrar são as MESMAS nos dois formatos — só muda o que se faz com
    os arquivos depois de resolvidos.

    Devolve `(item, resolvidos, faltando, do_item, cliente)`, com `resolvidos`
    já com o caminho no disco pronto para uso. `None` se o caso não existe.
    `SelecaoInvalida` recusa o pedido INTEIRO: classificação que não existe,
    id de outro item ou de outro caso (é essa a checagem de acesso por
    documento), ou seleção acima do teto de quantidade/tamanho.
    """
    situacao = montar_situacao(caso_id)
    if situacao is None:
        return None
    if situacao.get("categoria") is None:
        raise SelecaoInvalida(
            situacao.get("erro") or "A categoria deste caso não existe mais.", 409
        )

    item = next(
        (i for i in situacao["itens"] if i["codigo"] == classificacao), None
    )
    if item is None:
        raise SelecaoInvalida(
            f"A classificação '{classificacao}' não existe nesta categoria.", 404
        )

    # Dois cliques no mesmo arquivo não são dois arquivos; a ordem da seleção é
    # preservada porque é a ordem em que a tela mostrou as linhas.
    pedidos = list(dict.fromkeys(entrega_ids))
    if not pedidos:
        raise SelecaoInvalida("Nenhum documento foi selecionado.")
    if len(pedidos) > limite_itens:
        raise SelecaoInvalida(
            f"São aceitos até {limite_itens} documentos por pacote. "
            "Divida a seleção em partes menores.",
            413,
        )

    do_item = {e["id"]: e for e in item["entregas"]}
    intrusos = [eid for eid in pedidos if eid not in do_item]
    if intrusos:
        raise SelecaoInvalida(
            f"{len(intrusos)} documento(s) selecionado(s) não pertencem à "
            f"classificação '{item['nome']}'.",
            409,
        )

    # Resolve os caminhos ANTES de escrever: some quem não tem cópia recuperável,
    # e a soma dos bytes reprova a seleção grande antes de gastar disco.
    # Documento é PDF/foto já comprimido, então essa soma é ~o tamanho do ZIP
    # (o PDF combinado pode diferir um pouco, por causa da recompressão de
    # imagem — ver `conversao_pdf.converter_para_pdf`).
    resolvidos: list[tuple[str, Path]] = []
    faltando: list[str] = []
    total_bytes = 0
    for eid in pedidos:
        caminho = armazenamento.caminho_duravel_da_entrega(eid)
        if caminho is None:
            faltando.append(do_item[eid]["arquivo"])
            continue
        total_bytes += caminho.stat().st_size
        resolvidos.append((eid, caminho))

    if total_bytes > limite_bytes:
        raise SelecaoInvalida(
            f"A seleção passa de {limite_bytes // (1024 * 1024)}MB. "
            "Baixe em partes menores.",
            413,
        )

    return item, resolvidos, faltando, do_item, situacao["caso"]["cliente"]


def montar_zip_selecao(
    caso_id: str,
    classificacao: str,
    entrega_ids: list[str],
    destino: Path,
    *,
    limite_itens: int,
    limite_bytes: int,
) -> dict[str, Any] | None:
    """ZIP só com as entregas marcadas DENTRO de uma classificação.

    O irmão `montar_zip` leva o caso inteiro na ordem do checklist. Aqui o
    atendente escolhe uma classificação — "Laudos médicos", por exemplo —, marca
    alguns arquivos dela e leva só esses. Cada arquivo sai prefixado pelo nome da
    classificação, para o outro lado conferir contra a mesma lista.

    `None` se o caso não existe. Um id cujo arquivo sumiu do disco é PULADO e
    contado em `faltando`, nunca inventado. Ver `_resolver_selecao` para as
    condições em que o pedido é recusado inteiro.
    """
    resolvido = _resolver_selecao(
        caso_id, classificacao, entrega_ids,
        limite_itens=limite_itens, limite_bytes=limite_bytes,
    )
    if resolvido is None:
        return None
    item, resolvidos, faltando, do_item, cliente = resolvido

    guardados: list[str] = []
    if resolvidos:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as pacote:
            usados: set[str] = set()
            for eid, caminho in resolvidos:
                nome = _nome_no_pacote(
                    item["numero"], item["nome"], do_item[eid]["arquivo"]
                )
                # Dois arquivos com o mesmo nome: o descompactador sobrescreve um
                # com o outro, calado.
                if nome in usados:
                    base, ponto, ext = nome.rpartition(".")
                    nome = (
                        f"{base} ({len(usados)}){ponto}{ext}"
                        if ponto
                        else f"{nome} ({len(usados)})"
                    )
                usados.add(nome)
                pacote.write(caminho, arcname=nome)
                guardados.append(nome)

    return {
        "arquivos": len(guardados),
        "faltando": faltando,
        "cliente": cliente,
        "classificacao": item["nome"],
        "classificacao_codigo": item["codigo"],
    }


def montar_pdf_selecao(
    caso_id: str,
    classificacao: str,
    entrega_ids: list[str],
    destino: Path,
    *,
    limite_itens: int,
    limite_bytes: int,
    limite_paginas: int,
) -> dict[str, Any] | None:
    """Os documentos marcados de UMA classificação, juntos num único PDF.

    Mesma seleção e mesmas guardas de `montar_zip_selecao` — o que muda é o
    formato de saída: em vez de um ZIP com N arquivos, um PDF só com as páginas
    de todos, na ordem em que foram marcados. PDF entra intacto; imagem vira
    página, pelo mesmo conversor do botão "baixar como PDF" de uma entrega
    (`conversao_pdf.converter_para_pdf`).

    `None` se o caso não existe. Levanta `SelecaoInvalida` nas mesmas condições
    do ZIP (ver `_resolver_selecao`), mais quando algum arquivo não é PDF nem
    imagem, ou a soma de páginas passa do limite.
    """
    resolvido = _resolver_selecao(
        caso_id, classificacao, entrega_ids,
        limite_itens=limite_itens, limite_bytes=limite_bytes,
    )
    if resolvido is None:
        return None
    item, resolvidos, faltando, do_item, cliente = resolvido

    total_paginas = 0
    if resolvidos:
        destino.parent.mkdir(parents=True, exist_ok=True)
        try:
            total_paginas = conversao_pdf.mesclar_em_pdf(
                [(caminho, do_item[eid]["arquivo"]) for eid, caminho in resolvidos],
                destino,
                limite_paginas=limite_paginas,
            )
        except conversao_pdf.ErroConversaoPdf as exc:
            raise SelecaoInvalida(str(exc), 415) from exc

    return {
        "arquivos": len(resolvidos),
        "paginas": total_paginas,
        "faltando": faltando,
        "cliente": cliente,
        "classificacao": item["nome"],
        "classificacao_codigo": item["codigo"],
    }
