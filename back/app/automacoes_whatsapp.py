"""Estado durável das automações de WhatsApp.

O texto de cobrança não é armazenado: ele é remontado a partir do checklist no
instante do envio. Assim, cada documento recebido altera automaticamente a
próxima mensagem, sem o atendente precisar editar uma cópia antiga.
"""

from __future__ import annotations

import logging

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pyodbc

from . import armazenamento
from .banco import conectar

log = logging.getLogger(__name__)
FUSO_NEGOCIO = ZoneInfo("America/Sao_Paulo")


def _agora_dt() -> datetime:
    return datetime.now(timezone.utc)


def _iso(valor: datetime | None = None) -> str:
    return (valor or _agora_dt()).isoformat()


#: Um 'enviando' sem notícia por este tempo é processo que morreu no meio (worker
#: reiniciado, API derrubada). Antes ele travava a chave PARA SEMPRE — nem o
#: reenvio forçado passava, e a tela dizia "já enviado" de uma mensagem que nunca saiu.
MINUTOS_ENVIO_ORFAO = 5

#: Ciclo de entrega mostrado na tela. `status` (enviando/enviado/falhou) continua
#: sendo a trava de idempotência; `status_entrega` é o que o cliente viu.
PENDENTE = "PENDENTE"
PROCESSANDO = "PROCESSANDO"
ENVIADO = "ENVIADO"
ENTREGUE = "ENTREGUE"
LIDO = "LIDO"
FALHOU = "FALHOU"
EXPIRADO = "EXPIRADO"
DESTINATARIO_INVALIDO = "DESTINATARIO_INVALIDO"
#: Estados que liberam reenvio sem confirmação explícita.
REENVIAVEIS = frozenset({FALHOU, EXPIRADO, DESTINATARIO_INVALIDO})
#: A entrega só anda para a frente: um "lido" não volta a "entregue".
_ORDEM_ENTREGA = {PROCESSANDO: 1, ENVIADO: 2, ENTREGUE: 3, LIDO: 4}

_ERROS_DE_CHAVE: tuple[type[Exception], ...] = (pyodbc.IntegrityError,)
try:  # os testes rodam estas consultas num SQLite em memória
    import sqlite3

    _ERROS_DE_CHAVE = (pyodbc.IntegrityError, sqlite3.IntegrityError)
except ImportError:  # pragma: no cover
    pass


def reservar(
    chave: str, tipo: str, destino: str, caso_id: str | None = None, forcar: bool = False,
    atendimento_id: str | None = None, texto: str | None = None,
) -> bool:
    """Reserva um envio, impedindo duplicidade entre API e workers concorrentes.

    `forcar` libera um reenvio deliberado: um envio já CONCLUÍDO ('enviado')
    deixa de barrar a operação — é o caso do atendente que, com o cliente ainda
    na chamada, pede o link de novo. O que nunca é liberado é um envio EM
    ANDAMENTO ('enviando') recente: essa continua sendo a defesa contra clique
    duplo e corrida entre a API e o worker. O 'enviando' órfão (mais velho que
    `MINUTOS_ENVIO_ORFAO`) volta a ser reservável.
    """
    instante = _iso()
    orfao = _iso(_agora_dt() - timedelta(minutes=MINUTOS_ENVIO_ORFAO))
    resumo = (texto or "")[:600] or None
    try:
        with conectar() as con:
            # UPDATE condicional é uma única operação no banco. O antigo
            # SELECT seguido de UPDATE deixava dois workers lerem "falhou" e
            # ambos reservarem a mesma chave.
            atualizadas = con.execute(
                """UPDATE automacoes_whatsapp
                      SET status = 'enviando', tentativas = tentativas + 1,
                          ultimo_erro = NULL, atualizado_em = ?, status_entrega = ?,
                          destino = ?, mensagem_id = NULL, entregue_em = NULL, lido_em = NULL,
                          texto_resumo = COALESCE(?, texto_resumo)
                    WHERE chave = ?
                      AND (status <> 'enviando' OR atualizado_em < ?)
                      AND (? = 1 OR status <> 'enviado')""",
                (instante, PROCESSANDO, destino, resumo, chave, orfao, int(forcar)),
            ).rowcount
            if atualizadas:
                return True
            existe = con.execute(
                "SELECT 1 AS existe FROM automacoes_whatsapp WHERE chave = ?", (chave,)
            ).fetchone()
            if existe:
                return False
            con.execute(
                """INSERT INTO automacoes_whatsapp
                   (chave, tipo, caso_id, destino, status, tentativas, criado_em, atualizado_em,
                    status_entrega, atendimento_id, texto_resumo)
                   VALUES (?, ?, ?, ?, 'enviando', 1, ?, ?, ?, ?, ?)""",
                (chave, tipo, caso_id, destino, instante, instante, PROCESSANDO,
                 atendimento_id, resumo),
            )
        return True
    except _ERROS_DE_CHAVE:
        return False


def finalizar(
    chave: str, erro: str | None = None, *, mensagem_id: str | None = None,
    status_entrega: str | None = None,
) -> None:
    instante = _iso()
    entrega = status_entrega or (FALHOU if erro else ENVIADO)
    with conectar() as con:
        con.execute(
            """UPDATE automacoes_whatsapp
                  SET status = ?, ultimo_erro = ?, enviado_em = ?, atualizado_em = ?,
                      status_entrega = ?, mensagem_id = ?
                WHERE chave = ?""",
            ("falhou" if erro else "enviado", erro, None if erro else instante, instante,
             entrega, mensagem_id, chave),
        )


def obter_envio(chave: str) -> dict[str, Any] | None:
    with conectar() as con:
        linha = con.execute(
            "SELECT * FROM automacoes_whatsapp WHERE chave = ?", (chave,)
        ).fetchone()
    return dict(zip(linha.keys(), linha)) if linha else None


def atualizar_entrega(mensagem_id: str, status_entrega: str) -> int:
    """O webhook da Evolution contou que a mensagem chegou, foi lida ou falhou."""
    if not mensagem_id:
        return 0
    instante = _iso()
    with conectar() as con:
        linha = con.execute(
            "SELECT chave, status_entrega FROM automacoes_whatsapp WHERE mensagem_id = ?",
            (mensagem_id,),
        ).fetchone()
        if linha is None:
            return 0
        atual = str(linha["status_entrega"] or "")
        if status_entrega in _ORDEM_ENTREGA and _ORDEM_ENTREGA.get(atual, 0) >= _ORDEM_ENTREGA[status_entrega]:
            return 0
        extras = ""
        if status_entrega == ENTREGUE:
            extras = ", entregue_em = ?"
        elif status_entrega == LIDO:
            extras = ", lido_em = ?, entregue_em = COALESCE(entregue_em, ?)"
        params: list[Any] = [status_entrega, instante]
        if status_entrega == ENTREGUE:
            params.append(instante)
        elif status_entrega == LIDO:
            params += [instante, instante]
        if status_entrega == FALHOU:
            extras = ", status = 'falhou'"
        return con.execute(
            f"UPDATE automacoes_whatsapp SET status_entrega = ?, atualizado_em = ?{extras} "
            "WHERE chave = ?",
            (*params, linha["chave"]),
        ).rowcount


def expirar_sem_entrega(horas: int = 24) -> int:
    """Enviado que nunca chegou ao aparelho em `horas` vira EXPIRADO (reenviável)."""
    limite = _iso(_agora_dt() - timedelta(hours=horas))
    with conectar() as con:
        return con.execute(
            """UPDATE automacoes_whatsapp SET status_entrega = ?, atualizado_em = ?
                WHERE status_entrega = ? AND enviado_em IS NOT NULL AND enviado_em < ?""",
            (EXPIRADO, _iso(), ENVIADO, limite),
        ).rowcount


def historico(
    *, dias: int = 30, tipo: str | None = None, atendimento_id: str | None = None,
    caso_id: str | None = None, limite: int = 200,
) -> list[dict[str, Any]]:
    filtros = ["criado_em >= ?"]
    params: list[Any] = [_iso(_agora_dt() - timedelta(days=max(1, dias)))]
    for coluna, valor in (("tipo", tipo), ("atendimento_id", atendimento_id), ("caso_id", caso_id)):
        if valor:
            filtros.append(f"{coluna} = ?")
            params.append(valor)
    with conectar() as con:
        linhas = con.execute(
            f"SELECT * FROM automacoes_whatsapp WHERE {' AND '.join(filtros)} "
            "ORDER BY atualizado_em DESC",
            tuple(params),
        ).fetchall()
    return [dict(zip(linha.keys(), linha)) for linha in linhas[: max(1, limite)]]


def telefone_do_caso(caso_id: str) -> str:
    """O WhatsApp que a entrevista colheu, recuperado do caso.

    DOIS LUGARES, NESTA ORDEM

    1. **A coluna `casos.telefone`**, gravada quando o caso nasce do
       atendimento: a entrevista pergunta o telefone (obrigatória, no roteiro) e
       agora ele viaja junto na criação do caso. É a fonte que existe desde o
       primeiro minuto, antes de haver contrato.
    2. **O signatário da assinatura**, que era a única fonte até aqui. O
       contrato é montado com as respostas, e `assinatura.montar_signatario`
       grava `phone_country` e `phone_number`. Continua valendo para os casos
       abertos antes desta coluna existir e para os que foram criados à mão pela
       carteira, sem passar pela entrevista.

    A ordem importa: a assinatura só aparece depois que o contrato vai para a
    ZapSign, e até lá a cobrança automática abria com o campo em branco pedindo
    um número que o cliente já tinha ditado. Era o tipo de retrabalho que faz o
    recurso ficar desligado porque ninguém preencheu o campo.

    Vazio quando as duas fontes falham — aí o campo continua para digitar à mão,
    como antes.
    """
    try:
        caso = armazenamento.obter_caso(caso_id)
        do_cadastro = str((caso or {}).get("telefone") or "").strip()
        if do_cadastro:
            return do_cadastro
    except Exception:
        # Cai para a assinatura: banco antigo, sem a coluna, não pode derrubar a
        # única fonte que já funcionava.
        log.debug("Não foi possível ler o telefone do caso %s.", caso_id, exc_info=True)

    try:
        assinaturas = armazenamento.listar_assinaturas(caso_id=caso_id)
        if not assinaturas:
            # Nome sozinho não identifica: um homônimo receberia a lista e o
            # link de portal de outra pessoa. Para legado sem `caso_id`, exige o
            # mesmo par nome + CPF usado pelo painel de assinaturas.
            caso = armazenamento.obter_caso(caso_id)
            qualificacao = armazenamento.obter_qualificacao(caso_id) or {}
            cliente = str((caso or {}).get("cliente") or "").strip()
            cpf = str(qualificacao.get("cpf") or "").strip()
            if cliente and cpf:
                assinaturas = armazenamento.listar_assinaturas(cliente=cliente, cpf=cpf)
    except Exception:
        log.debug("Não foi possível procurar o telefone do caso %s.", caso_id, exc_info=True)
        return ""

    for registro in assinaturas:
        for signatario in registro.get("signatarios") or []:
            # DOIS FORMATOS, e a diferença já enganou: `phone_number` /
            # `phone_country` é o payload que vai PARA a ZapSign (ver
            # `assinatura.montar_signatario`); o que fica GRAVADO na coluna
            # `signatarios` é a forma interna, com `telefone` num campo só.
            # Ler os dois cobre registro antigo e registro novo.
            numero = str(
                signatario.get("telefone") or signatario.get("phone_number") or ""
            ).strip()
            if not numero:
                continue
            ddi = str(signatario.get("phone_country") or "").strip()
            # O `_numero_brasileiro` do `whatsapp.py` acrescenta o 55 sozinho
            # quando o número vem com 10 ou 11 dígitos, então o caso comum não
            # precisa de prefixo. DDI estrangeiro (raro, mas existe) vai junto
            # para não virar um telefone brasileiro inventado.
            return f"+{ddi}{numero}" if ddi and ddi != "55" else numero
    return ""


def obter_cobranca(caso_id: str) -> dict[str, Any]:
    with conectar() as con:
        linha = con.execute(
            "SELECT * FROM cobrancas_documentos WHERE caso_id = ?", (caso_id,)
        ).fetchone()
    if not linha:
        return {
            "caso_id": caso_id, "ativa": False,
            # Já vem preenchido na primeira abertura da tela: o número é o mesmo
            # que o cliente ditou na entrevista.
            "telefone": telefone_do_caso(caso_id), "intervalo_dias": 3,
            "intervalo_horas": 24, "max_envios_dia": 1,
            "incluir_opcionais": False, "proximo_envio_em": None,
            "ultimo_envio_em": None, "ultimo_erro": None,
        }
    intervalo_dias = int(linha["intervalo_dias"])
    intervalo_horas_salvo = linha.get("intervalo_horas")
    intervalo_horas = int(intervalo_horas_salvo or 0) or intervalo_dias * 24
    # Uma versão intermediária da migração criou a coluna com DEFAULT 24. Para
    # linha antiga de 2+ dias, 24 não foi escolha do gestor: foi preenchimento
    # automático do schema. A UI nova sempre salva 24h junto com 1 dia.
    if intervalo_horas == 24 and intervalo_dias > 1:
        intervalo_horas = intervalo_dias * 24
    return {
        "caso_id": linha["caso_id"], "ativa": bool(linha["ativa"]),
        # O cadastro atual vence. O número salvo só cobre configuração antiga
        # enquanto o caso ainda não tiver uma fonte identificável e segura.
        "telefone": telefone_do_caso(caso_id) or linha["telefone"],
        "intervalo_dias": intervalo_dias,
        "intervalo_horas": max(1, intervalo_horas),
        "max_envios_dia": max(1, int(linha.get("max_envios_dia") or 1)),
        "incluir_opcionais": bool(linha["incluir_opcionais"]),
        "proximo_envio_em": linha["proximo_envio_em"],
        "ultimo_envio_em": linha["ultimo_envio_em"], "ultimo_erro": linha["ultimo_erro"],
    }


def salvar_cobranca(
    caso_id: str, *, ativa: bool, telefone: str, intervalo_dias: int,
    incluir_opcionais: bool, intervalo_horas: int | None = None,
    max_envios_dia: int = 1,
) -> dict[str, Any]:
    instante = _iso()
    intervalo_horas = max(1, min(int(intervalo_horas or intervalo_dias * 24), 24 * 30))
    max_envios_dia = max(1, min(int(max_envios_dia or 1), 6))
    with conectar() as con:
        existe = con.execute(
            "SELECT caso_id, ativa, proximo_envio_em FROM cobrancas_documentos WHERE caso_id = ?",
            (caso_id,),
        ).fetchone()
        # Alterar frequência não dispara cobrança imediatamente. Só a transição
        # desligada -> ativa agenda para agora; desativar limpa a agenda.
        proximo = None
        if ativa:
            proximo = (
                existe["proximo_envio_em"]
                if existe and bool(existe["ativa"]) and existe["proximo_envio_em"]
                else instante
            )
        if existe:
            con.execute(
                """UPDATE cobrancas_documentos SET ativa = ?, telefone = ?, intervalo_dias = ?,
                   intervalo_horas = ?, max_envios_dia = ?, incluir_opcionais = ?,
                   proximo_envio_em = ?, ultimo_erro = NULL,
                   atualizado_em = ? WHERE caso_id = ?""",
                (
                    int(ativa), telefone, intervalo_dias, intervalo_horas,
                    max_envios_dia, int(incluir_opcionais), proximo, instante, caso_id,
                ),
            )
        else:
            con.execute(
                """INSERT INTO cobrancas_documentos
                   (caso_id, ativa, telefone, intervalo_dias, intervalo_horas,
                    max_envios_dia, incluir_opcionais,
                    proximo_envio_em, criado_em, atualizado_em)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    caso_id, int(ativa), telefone, intervalo_dias, intervalo_horas,
                    max_envios_dia, int(incluir_opcionais), proximo, instante, instante,
                ),
            )
    return obter_cobranca(caso_id)


def listar_cobrancas_vencidas() -> list[dict[str, Any]]:
    """As cobranças no ponto de enviar, já com o telefone resolvido.

    O `telefone <> ''` saiu do SQL de propósito. Ele filtrava a coluna, que pode
    estar em branco num caso configurado ANTES de o contrato existir — e desde
    que `obter_cobranca` passou a recuperar o número da assinatura, esse caso
    aparecia ativo na tela, com o número à vista, e mesmo assim nunca era
    cobrado. Ficar "ligado" sem enviar nada é pior que não ligar.

    Agora o filtro é sobre o valor RESOLVIDO. Quem continuar sem número nenhum é
    descartado aqui, e não vira uma tentativa de envio fadada a falhar.
    """
    instante = _iso()
    with conectar() as con:
        linhas = con.execute(
            """SELECT caso_id FROM cobrancas_documentos
                WHERE ativa = 1
                  AND (proximo_envio_em IS NULL OR proximo_envio_em <= ?)""",
            (instante,),
        ).fetchall()
    resolvidas = [obter_cobranca(linha["caso_id"]) for linha in linhas]
    return [c for c in resolvidas if str(c.get("telefone") or "").strip()]


def registrar_resultado_cobranca(
    caso_id: str, intervalo_dias: int, texto_hash: str | None, erro: str | None = None,
    intervalo_horas: int | None = None,
    reagendar: bool = True,
) -> None:
    instante = _agora_dt()
    horas = max(1, int(intervalo_horas or intervalo_dias * 24))
    proximo = instante + timedelta(hours=horas)
    with conectar() as con:
        con.execute(
            """UPDATE cobrancas_documentos
                  SET proximo_envio_em = CASE WHEN ? = 1 THEN ? ELSE proximo_envio_em END,
                      ultimo_envio_em = COALESCE(?, ultimo_envio_em),
                      ultimo_hash = COALESCE(?, ultimo_hash),
                      ultimo_erro = ?, atualizado_em = ? WHERE caso_id = ?""",
            (
                int(reagendar),
                _iso(proximo),
                _iso(instante) if texto_hash and not erro else None,
                texto_hash,
                erro,
                _iso(instante),
                caso_id,
            ),
        )


def envios_de_cobranca_hoje(caso_id: str) -> int:
    """Quantas cobranças de documento já saíram hoje para este caso."""
    agora_local = _agora_dt().astimezone(FUSO_NEGOCIO)
    inicio = agora_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(
        timezone.utc
    )
    with conectar() as con:
        linha = con.execute(
            """SELECT COUNT(*) AS total FROM automacoes_whatsapp
                WHERE caso_id = ?
                  AND tipo = 'cobranca_documentos'
                  AND status = 'enviado'
                  AND enviado_em >= ?""",
            (caso_id, _iso(inicio)),
        ).fetchone()
    return int(linha["total"] if linha else 0)


def reagendar_cobranca_para_amanha(caso_id: str) -> None:
    """Evita reprocessar a mesma cobrança depois de bater o limite diário."""
    agora = _agora_dt()
    agora_local = agora.astimezone(FUSO_NEGOCIO)
    proximo = (agora_local + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc)
    with conectar() as con:
        con.execute(
            """UPDATE cobrancas_documentos
                  SET proximo_envio_em = ?, atualizado_em = ?
                WHERE caso_id = ?""",
            (_iso(proximo), _iso(agora), caso_id),
        )


def caso_existe(caso_id: str) -> bool:
    return armazenamento.obter_caso(caso_id) is not None
