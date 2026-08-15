"""O dossiê do caso: tudo que o escritório sabe, numa resposta só.

Junta o que mora de cada lado — cliente, checklist e contrato aqui; fato,
classificação, pendência, contradição e jurisprudência no agente — e devolve
também a **linha do processo**: em que etapa o caso está e o que falta para andar.

Duas decisões que sustentam a tela:

- **agente fora do ar não vira caso vazio.** Cada bloco que veio dele carrega o
  estado da consulta; quando falha, a etapa fica `indisponivel` com o motivo, nunca
  `pendente` — "não consegui olhar" e "não há nada" levam a decisões opostas;
- **a montagem é uma leitura, não um cálculo.** Nada aqui deriva conclusão jurídica:
  a classificação é a do agente, a pendência é a do playbook dele, o precedente é o
  que a pesquisa recuperou. Esta camada só arruma na ordem em que se lê.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

from .. import armazenamento, casos as casos_ocr, contrato
from .cliente import Cliente, ErroDoAgente
from .config import config

log = logging.getLogger("agente")

__all__ = ["dados_do_contrato", "montar"]

PENDENTE = "pendente"
ANDAMENTO = "andamento"
PRONTO = "pronto"
ATENCAO = "atencao"
INDISPONIVEL = "indisponivel"


def montar(caso_id: str) -> dict[str, Any] | None:
    """O dossiê inteiro. `None` quando o caso não existe no OCR."""
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        return None

    situacao = casos_ocr.montar_situacao(caso_id) or {}
    vinculo = armazenamento.obter_vinculo_agente(caso_id)
    agente = _do_agente(vinculo)
    entrevistas = [_entrevista_resumida(item) for item in armazenamento.listar_entrevistas(caso_id)]
    cliente = _cliente(caso, situacao, agente)
    assinaturas = armazenamento.listar_assinaturas(caso_id=caso_id) or _por_cliente(cliente)

    categoria = situacao.get("categoria") or {}
    return {
        "caso": caso,
        "cliente": cliente,
        "checklist": {
            # A situação traz a categoria como objeto (código, nome, descrição); a
            # tela quer o nome. Passar o objeto inteiro imprimia o dicionário na
            # linha do processo.
            "categoria": categoria.get("nome") or caso.get("categoria"),
            "progresso": situacao.get("progresso"),
            "itens": [
                {
                    "codigo": item.get("codigo"),
                    "rotulo": item.get("rotulo"),
                    "status": item.get("status"),
                    "obrigatorio": item.get("obrigatorio"),
                    "alertas": item.get("alertas") or [],
                }
                for item in situacao.get("itens", [])
            ],
        },
        "contrato": {
            # Token da ZapSign e CPF são chaves internas de correlação, não dados
            # de apresentação do dossiê.
            "assinaturas": [
                {
                    chave: assinatura.get(chave)
                    for chave in ("id", "nome", "estado", "assinaram", "total", "faltam")
                }
                for assinatura in assinaturas
            ],
            "assinado": any(a.get("estado") == "assinado" for a in assinaturas),
        },
        "entrevistas": entrevistas,
        "agente": agente,
        "etapas": _etapas(situacao, assinaturas, agente, entrevistas),
    }


#: Quanto do relato vai no dossiê. O texto inteiro pode ter dez páginas, e a linha do
#: processo é carregada a cada abertura da tela; quem quer ler tudo abre a entrevista.
_PREVIA = 800


def _entrevista_resumida(registro: dict[str, Any]) -> dict[str, Any]:
    texto = str(registro.get("texto") or "")
    return {
        "id": registro["id"],
        "arquivo": registro["arquivo"],
        "realizada_em": registro.get("realizada_em") or "",
        "entrevistador": registro.get("entrevistador") or "",
        "resumo": registro.get("resumo") or "",
        "perguntas": registro.get("perguntas") or [],
        "fatos_gerados": registro.get("fatos_gerados") or 0,
        "enviada": bool(registro.get("enviada")),
        "criado_em": registro.get("criado_em"),
        "caracteres": len(texto),
        "previa": texto[:_PREVIA],
        "truncada": len(texto) > _PREVIA,
    }


def _nome_da_categoria(situacao: dict[str, Any]) -> str:
    categoria = situacao.get("categoria") or {}
    return str(categoria.get("nome") or "não definida")


def _por_cliente(cliente: dict[str, Any]) -> list[dict[str, Any]]:
    """Contrato assinado **antes** de o caso existir não tem `caso_id`.

    É o fluxo normal do escritório: assina-se na entrevista e o caso é aberto depois.
    Procurar pelo nome recupera esse contrato em vez de deixar a tela dizendo que não
    há contrato quando existe um assinado.
    """
    respostas, motivos = dados_do_contrato({"cliente": cliente})
    if motivos:
        return []
    return armazenamento.listar_assinaturas(
        cliente=respostas.get("nome"), cpf=respostas.get("cpf")
    ) or []


def _cliente(
    caso: dict[str, Any], situacao: dict[str, Any], agente: dict[str, Any]
) -> dict[str, Any]:
    """A ficha do cliente, montada a partir dos fatos com proveniência.

    O nome vem do cadastro do OCR; CPF, RG, PIS, nascimento e endereço vêm dos
    **documentos lidos**, não de digitação. Cada campo carrega de onde saiu — é o que
    o advogado precisa para conferir sem abrir o arquivo.
    """
    ficha: dict[str, Any] = {"nome": caso.get("cliente"), "campos": [], "origem": "cadastro"}
    rotulos = {
        "PERSON.CPF": ("CPF", "digits"),
        "PERSON.RG": ("RG", "number"),
        "PERSON.PIS": ("PIS/PASEP", "digits"),
        "PERSON.BIRTH_DATE": ("Nascimento", "date"),
        "PERSON.NAME": ("Nome no documento", "full_name"),
        "PERSON.ADDRESS": ("Endereço", "street"),
    }

    for fato in agente.get("fatos", []):
        entrada = rotulos.get(str(fato.get("type")))
        if entrada is None:
            continue
        rotulo, chave = entrada
        valor = (fato.get("value") or {}).get(chave)
        if not valor:
            continue
        ficha["campos"].append(
            {
                "rotulo": rotulo,
                "valor": valor,
                "confianca": fato.get("confidence"),
                "status": fato.get("status"),
                "fontes": _origens(fato),
            }
        )

    ficha["documentos_entregues"] = (situacao.get("progresso") or {}).get(
        "obrigatorios_entregues"
    )
    return ficha


def _origens(fato: dict[str, Any]) -> list[str]:
    """De onde o fato saiu, em uma linha por origem.

    "documento, página 2, campo pis" é o que o advogado precisa para conferir sem
    abrir o arquivo — e é o que distingue um fato apurado de um dado digitado.
    """
    origens: list[str] = []
    for fonte in fato.get("sources") or []:
        partes = [str(fonte.get("source_type", "")).lower()]
        if fonte.get("page"):
            partes.append(f"página {fonte['page']}")
        if fonte.get("ocr_field"):
            partes.append(f"campo {fonte['ocr_field']}")
        if fonte.get("user_subject"):
            partes.append(str(fonte["user_subject"]))
        origens.append(", ".join(parte for parte in partes if parte))
    return origens


def _chave_nome(nome: object) -> str:
    texto = unicodedata.normalize("NFKD", str(nome or ""))
    sem_acentos = "".join(c for c in texto if not unicodedata.combining(c))
    return "".join(c for c in sem_acentos.casefold() if c.isalpha())


def _cpf_canonico(cpf: object) -> str:
    texto = unicodedata.normalize("NFKC", str(cpf or ""))
    if not re.fullmatch(r"[0-9.\-\s]+", texto):
        return ""
    return re.sub(r"[^0-9]", "", texto)


def dados_do_contrato(montado: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Deriva a qualificação do estado atual do caso, sem escolher divergências.

    É chamada novamente no POST de geração; a tela não é fronteira de confiança e
    um fato pode ter sido contestado desde o último GET do dossiê.
    """
    cliente = montado.get("cliente") or {}
    campos = list(cliente.get("campos") or [])
    descartados = {"REJECTED", "SUPERSEDED"}
    inseguros = {"CONTESTED", "CONTRADICTED"}
    motivos: list[str] = []

    def status(campo: dict[str, Any]) -> str:
        return str(campo.get("status") or "").upper()

    def fatos(rotulo: str) -> list[dict[str, Any]]:
        return [
            campo
            for campo in campos
            if campo.get("rotulo") == rotulo and status(campo) not in descartados
        ]

    fatos_cpf = fatos("CPF")
    if any(status(campo) in inseguros for campo in fatos_cpf):
        motivos.append("o CPF está contestado ou contraditado; resolva o fato antes de gerar.")
    if any(
        str(campo.get("valor") or "").strip()
        and not _cpf_canonico(campo.get("valor"))
        for campo in fatos_cpf
    ):
        motivos.append(
            "há um CPF em formato inválido nos documentos; corrija ou rejeite o fato."
        )
    cpfs = {
        _cpf_canonico(campo.get("valor"))
        for campo in fatos_cpf
        if _cpf_canonico(campo.get("valor"))
    }
    if len(cpfs) > 1:
        motivos.append(
            "há CPFs divergentes nos documentos; rejeite ou substitua o fato incorreto."
        )
    cpf = next(iter(cpfs), "") if len(cpfs) == 1 and not any(
        status(campo) in inseguros for campo in fatos_cpf
    ) else ""

    nome_cadastro = " ".join(str(cliente.get("nome") or "").split())
    fatos_nome = fatos("Nome no documento")
    if any(status(campo) in inseguros for campo in fatos_nome):
        motivos.append(
            "o nome está contestado ou contraditado; resolva o fato antes de gerar."
        )
    nomes = {
        _chave_nome(campo.get("valor"))
        for campo in fatos_nome
        if _chave_nome(campo.get("valor"))
    }
    if len(nomes) > 1:
        motivos.append(
            "há nomes divergentes nos documentos; rejeite ou substitua o fato incorreto."
        )
    elif len(nomes) == 1 and _chave_nome(nome_cadastro) not in nomes:
        motivos.append(
            "o nome do cadastro diverge do nome encontrado nos documentos; corrija um deles."
        )

    campos_seguros = [
        campo for campo in campos if status(campo) not in descartados | inseguros
    ]

    def valor(rotulo: str) -> str:
        for campo in campos_seguros:
            if campo.get("rotulo") == rotulo:
                return str(campo.get("valor") or "").strip()
        return ""

    respostas: dict[str, Any] = {
        "nome": nome_cadastro,
        "nacionalidade": valor("Nacionalidade"),
        "estado_civil": valor("Estado civil"),
        "profissao": valor("Profissão"),
        "cpf": cpf,
        "rg": valor("RG"),
        "rg_orgao": valor("Órgão emissor"),
        "rg_uf": valor("UF do RG"),
        "endereco": valor("Endereço"),
        "telefone": valor("Telefone"),
        "email": valor("E-mail"),
    }
    try:
        respostas = contrato.normalizar_respostas(respostas)
    except contrato.DadosObrigatoriosContrato as exc:
        requisito = str(exc).removeprefix("Contrato não gerado: ").rstrip(".")
        motivos.append(f"{requisito}.")

    return respostas, list(dict.fromkeys(motivos))


def _do_agente(vinculo: dict[str, Any] | None) -> dict[str, Any]:
    """Lê o agente. Cada falha vira estado declarado, nunca lista vazia."""
    cfg = config()
    bloco: dict[str, Any] = {
        "ligado": cfg.ligado,
        "disponivel": False,
        "vinculado": vinculo is not None,
        "caso_ref": vinculo["caso_ref"] if vinculo else None,
        "ultimo_erro": vinculo.get("ultimo_erro") if vinculo else None,
        "fatos": [],
        "classificacoes": [],
        "pendencias": [],
        "contradicoes": [],
        "documentos": [],
        "pesquisas": [],
        "peticoes": [],
        "estrategia": None,
        "motivo": None,
    }

    if not cfg.ligado:
        bloco["motivo"] = "Agente jurídico não configurado neste ambiente."
        return bloco
    if vinculo is None:
        bloco["motivo"] = "Este caso ainda não foi enviado ao agente."
        return bloco

    caso_ref = vinculo["caso_ref"]

    try:
        # A construção entra no `try` porque ela também falha: o cliente recusa
        # nascer sem configuração, e essa falha precisa virar motivo na tela como
        # qualquer outra — não estourar o dossiê inteiro.
        cliente = Cliente(cfg)
        analise = cliente.analise(caso_ref)
        bloco["classificacoes"] = analise.get("classifications", [])
        bloco["pendencias"] = analise.get("missing_information", [])
        bloco["fatos"] = cliente.fatos(caso_ref).get("items", [])
        bloco["disponivel"] = True
    except ErroDoAgente as erro:
        bloco["motivo"] = str(erro)
        return bloco

    # As leituras seguintes são complementares: uma falha aqui não invalida o que já
    # foi lido, então cada uma degrada sozinha em vez de derrubar o dossiê.
    for chave, leitura in (
        ("contradicoes", lambda: cliente.contradicoes(caso_ref).get("items", [])),
        ("documentos", lambda: cliente.documentos(caso_ref).get("items", [])),
        ("pesquisas", lambda: cliente.pesquisas(caso_ref).get("items", [])),
        ("peticoes", lambda: cliente.peticoes(caso_ref).get("items", [])),
        ("estrategia", lambda: cliente.estrategia(caso_ref)),
    ):
        try:
            bloco[chave] = leitura()
        except ErroDoAgente as erro:
            log.warning("dossiê: %s indisponível — %s", chave, erro)
            bloco.setdefault("parciais", []).append({"bloco": chave, "motivo": str(erro)})

    return bloco


# ------------------------------------------------------------------- etapas


def _etapas(
    situacao: dict[str, Any],
    assinaturas: list[dict[str, Any]],
    agente: dict[str, Any],
    entrevistas: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """A linha do processo, na ordem em que o escritório trabalha.

    Cada etapa diz o estado **e o porquê**. Um "pendente" sem motivo obriga o
    advogado a caçar a informação em outra tela, que é justamente o que este painel
    existe para evitar.
    """
    progresso = situacao.get("progresso") or {}
    entregues = progresso.get("obrigatorios_entregues") or 0
    obrigatorios = progresso.get("obrigatorios_total") or 0
    a_conferir = progresso.get("itens_a_conferir") or 0

    etapas = [
        {
            "codigo": "caso",
            "titulo": "Caso aberto",
            "estado": PRONTO,
            "detalhe": f"Categoria {_nome_da_categoria(situacao)}.",
        },
        _etapa_entrevista(entrevistas or []),
        _etapa_contrato(assinaturas),
        {
            "codigo": "documentos",
            "titulo": "Documentos do checklist",
            # Item chegado com ressalva (ilegível ou tipo trocado) não é progresso:
            # ele volta para o cliente. Por isso "conferir" vence "entregue" aqui.
            "estado": (
                ATENCAO
                if a_conferir
                else PRONTO
                if obrigatorios and entregues >= obrigatorios
                else ANDAMENTO
                if entregues
                else PENDENTE
            ),
            "detalhe": (
                f"{entregues} de {obrigatorios} itens obrigatórios entregues"
                + (f"; {a_conferir} a conferir." if a_conferir else ".")
            ),
        },
    ]

    if not agente["ligado"] or not agente["vinculado"] or not agente["disponivel"]:
        motivo = agente.get("motivo") or "Agente jurídico indisponível."
        etapas.extend(
            {
                "codigo": codigo,
                "titulo": titulo,
                "estado": INDISPONIVEL,
                "detalhe": motivo,
            }
            for codigo, titulo in (
                ("fatos", "Fatos apurados"),
                ("classificacao", "Classificação jurídica"),
                ("pendencias", "Pendências do playbook"),
                ("pesquisa", "Jurisprudência"),
                ("estrategia", "Estratégia do caso"),
                ("peticao", "Petição inicial"),
            )
        )
        return etapas

    etapas.append(_etapa_fatos(agente))
    etapas.append(_etapa_classificacao(agente))
    etapas.append(_etapa_pendencias(agente))
    etapas.append(_etapa_pesquisa(agente))
    etapas.append(_etapa_estrategia(agente))
    etapas.append(_etapa_peticao(agente))
    return etapas


def _etapa_entrevista(entrevistas: list[dict[str, Any]]) -> dict[str, Any]:
    """O atendimento: primeira etapa do caso e a única que não depende do agente.

    Entrevista guardada mas **não lida** não é "pronto": o arquivo está no Acervo e nada
    dele chegou ao Case State, que é a diferença entre ter a conversa e ter o caso.
    """
    if not entrevistas:
        return {
            "codigo": "entrevista",
            "titulo": "Entrevista",
            "estado": PENDENTE,
            "detalhe": "Nenhuma entrevista anexada a este caso.",
        }

    recente = entrevistas[0]
    plural = "s" if len(entrevistas) > 1 else ""
    if not recente["enviada"]:
        return {
            "codigo": "entrevista",
            "titulo": "Entrevista",
            "estado": ANDAMENTO,
            "detalhe": (
                f"{len(entrevistas)} entrevista{plural} anexada{plural}; a mais recente "
                "ainda não foi lida pelo agente."
            ),
        }

    fatos = recente["fatos_gerados"]
    pendentes = len(recente["perguntas"])
    return {
        "codigo": "entrevista",
        "titulo": "Entrevista",
        "estado": PRONTO if fatos else ATENCAO,
        "detalhe": (
            f"{recente['arquivo']} lida: {fatos} fato(s) relatado(s)"
            + (f"; {pendentes} ponto(s) a confirmar." if pendentes else ".")
            if fatos
            else f"{recente['arquivo']} lida, mas nenhum fato foi aproveitado."
        ),
    }


def _etapa_contrato(assinaturas: list[dict[str, Any]]) -> dict[str, Any]:
    if not assinaturas:
        return {
            "codigo": "contrato",
            "titulo": "Contrato de honorários",
            "estado": PENDENTE,
            "detalhe": "Nenhum contrato enviado para assinatura.",
        }

    recente = assinaturas[0]
    assinado = recente.get("estado") == "assinado"
    faltam = recente.get("faltam") or []
    return {
        "codigo": "contrato",
        "titulo": "Contrato de honorários",
        "estado": PRONTO if assinado else ANDAMENTO,
        "detalhe": (
            "Assinado por todos os signatários."
            if assinado
            else f"Aguardando assinatura de {', '.join(faltam) or 'signatário'}."
        ),
    }


def _etapa_fatos(agente: dict[str, Any]) -> dict[str, Any]:
    fatos = agente["fatos"]
    contradicoes = [c for c in agente["contradicoes"] if c.get("status") == "OPEN"]
    if contradicoes:
        return {
            "codigo": "fatos",
            "titulo": "Fatos apurados",
            "estado": ATENCAO,
            "detalhe": (
                f"{len(fatos)} fatos, {len(contradicoes)} em contradição — "
                "conferir antes de usar."
            ),
        }
    return {
        "codigo": "fatos",
        "titulo": "Fatos apurados",
        "estado": PRONTO if fatos else PENDENTE,
        "detalhe": (
            f"{len(fatos)} fatos com origem registrada."
            if fatos
            else "Nenhum documento lido produziu fato ainda."
        ),
    }


def _etapa_classificacao(agente: dict[str, Any]) -> dict[str, Any]:
    classificacoes = agente["classificacoes"]
    if not classificacoes:
        return {
            "codigo": "classificacao",
            "titulo": "Classificação jurídica",
            "estado": PENDENTE,
            "detalhe": "O agente ainda não classificou o caso. Rode a análise.",
        }
    rotulos = ", ".join(str(c.get("label")) for c in classificacoes[:3])
    return {
        "codigo": "classificacao",
        "titulo": "Classificação jurídica",
        "estado": PRONTO,
        "detalhe": f"{rotulos}.",
    }


def _etapa_pendencias(agente: dict[str, Any]) -> dict[str, Any]:
    abertas = [p for p in agente["pendencias"] if p.get("status") == "OPEN"]
    bloqueantes = [p for p in abertas if p.get("severity") == "BLOCKING"]
    if not agente["classificacoes"]:
        return {
            "codigo": "pendencias",
            "titulo": "Pendências do playbook",
            "estado": PENDENTE,
            "detalhe": "A lista de pendências só existe depois da classificação.",
        }
    if bloqueantes:
        return {
            "codigo": "pendencias",
            "titulo": "Pendências do playbook",
            "estado": ATENCAO,
            "detalhe": f"{len(bloqueantes)} itens indispensáveis ainda faltam.",
        }
    return {
        "codigo": "pendencias",
        "titulo": "Pendências do playbook",
        "estado": PRONTO if not abertas else ANDAMENTO,
        "detalhe": (
            "Nada pendente no playbook."
            if not abertas
            else f"{len(abertas)} itens recomendados em aberto."
        ),
    }


def _etapa_pesquisa(agente: dict[str, Any]) -> dict[str, Any]:
    pesquisas = agente["pesquisas"]
    if not pesquisas:
        return {
            "codigo": "pesquisa",
            "titulo": "Jurisprudência",
            "estado": PENDENTE,
            "detalhe": "Nenhuma pesquisa executada para este caso.",
        }

    recente = pesquisas[0]
    if recente.get("status") == "FAILED":
        # Falha explícita, com o motivo do agente. O `§47` proíbe apresentar isto
        # como "não há jurisprudência sobre o caso".
        return {
            "codigo": "pesquisa",
            "titulo": "Jurisprudência",
            "estado": ATENCAO,
            "detalhe": f"A última pesquisa não concluiu: {recente.get('failure_reason')}",
        }
    if recente.get("status") == "RUNNING":
        return {
            "codigo": "pesquisa",
            "titulo": "Jurisprudência",
            "estado": ANDAMENTO,
            "detalhe": "Pesquisa em andamento.",
        }

    cobertura = recente.get("corpus_coverage") or {}
    ressalva = ""
    if cobertura and not cobertura.get("complete"):
        ressalva = f" Acervo {round((cobertura.get('ratio') or 0) * 100)}% vetorizado."
    return {
        "codigo": "pesquisa",
        "titulo": "Jurisprudência",
        "estado": PRONTO,
        "detalhe": f"Pesquisa concluída.{ressalva}",
    }


def _etapa_peticao(agente: dict[str, Any]) -> dict[str, Any]:
    """A última etapa do caso — e a única cujo "pronto" ainda depende de um humano.

    Peça retida por achado bloqueante aparece como `atencao`, nunca como pronta: é o
    estado em que o sistema já sabe que ela tem defeito, e mostrá-la como concluída faria
    alguém protocolar o que o próprio sistema reprovou.
    """
    peticoes = agente.get("peticoes") or []
    if not peticoes:
        pronto_para_gerar = bool(agente.get("classificacoes"))
        return {
            "codigo": "peticao",
            "titulo": "Petição inicial",
            "estado": PENDENTE,
            "detalhe": (
                "Nenhuma minuta gerada para este caso."
                if pronto_para_gerar
                else "A minuta só pode ser gerada depois da classificação."
            ),
        }

    recente = peticoes[0]
    bloqueantes = int(recente.get("blocking_findings") or 0)
    versao = recente.get("version")
    estado_peca = str(recente.get("status") or "")

    if bloqueantes:
        return {
            "codigo": "peticao",
            "titulo": "Petição inicial",
            "estado": ATENCAO,
            "detalhe": (
                f"Minuta v{versao} retida: {bloqueantes} achado(s) bloqueante(s) da revisão. "
                "Corrija o caso e gere outra versão."
            ),
        }
    if estado_peca == "APPROVED":
        return {
            "codigo": "peticao",
            "titulo": "Petição inicial",
            "estado": PRONTO,
            "detalhe": f"Minuta v{versao} aprovada por {recente.get('reviewed_by') or 'advogado'}.",
        }
    if estado_peca == "REJECTED":
        return {
            "codigo": "peticao",
            "titulo": "Petição inicial",
            "estado": ATENCAO,
            "detalhe": f"Minuta v{versao} rejeitada na revisão do advogado.",
        }
    return {
        "codigo": "peticao",
        "titulo": "Petição inicial",
        "estado": ANDAMENTO,
        "detalhe": f"Minuta v{versao} aguardando revisão do advogado.",
    }


def _etapa_estrategia(agente: dict[str, Any]) -> dict[str, Any]:
    """A tese do caso — e se ela já passou por decisão humana.

    Estratégia proposta e não aprovada aparece como `andamento`, nunca como pronta: até o
    advogado decidir, ela é sugestão do sistema, e a petição continua tirando os pedidos do
    playbook (`§13`).
    """
    estrategia = agente.get("estrategia")
    if not estrategia:
        return {
            "codigo": "estrategia",
            "titulo": "Estratégia do caso",
            "estado": PENDENTE,
            "detalhe": (
                "Nenhuma estratégia proposta."
                if agente.get("classificacoes")
                else "A estratégia só pode ser proposta depois da classificação."
            ),
        }

    hipoteses = estrategia.get("hypotheses") or []
    aceitas = [item for item in hipoteses if item.get("status") == "ACCEPTED"]
    descartados = len(estrategia.get("rejected_items") or [])
    ressalva = f" {descartados} item(ns) descartado(s) por falta de âncora." if descartados else ""

    if estrategia.get("status") == "APPROVED":
        return {
            "codigo": "estrategia",
            "titulo": "Estratégia do caso",
            "estado": PRONTO,
            "detalhe": (
                f"Versão {estrategia.get('version')} aprovada, "
                f"{len(aceitas)} de {len(hipoteses)} teses aceitas.{ressalva}"
            ),
        }
    if estrategia.get("status") == "REJECTED":
        return {
            "codigo": "estrategia",
            "titulo": "Estratégia do caso",
            "estado": ATENCAO,
            "detalhe": f"Versão {estrategia.get('version')} rejeitada pelo advogado.",
        }
    return {
        "codigo": "estrategia",
        "titulo": "Estratégia do caso",
        "estado": ANDAMENTO,
        "detalhe": (
            f"Versão {estrategia.get('version')} proposta, com {len(hipoteses)} tese(s), "
            f"aguardando decisão do advogado.{ressalva}"
        ),
    }
