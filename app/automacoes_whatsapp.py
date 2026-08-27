"""Estado durável das automações de WhatsApp.

O texto de cobrança não é armazenado: ele é remontado a partir do checklist no
instante do envio. Assim, cada documento recebido altera automaticamente a
próxima mensagem, sem o atendente precisar editar uma cópia antiga.
"""

from __future__ import annotations

import logging

from datetime import datetime, timedelta, timezone
from typing import Any

import pyodbc

from . import armazenamento
from .banco import conectar

log = logging.getLogger(__name__)


def _agora_dt() -> datetime:
    return datetime.now(timezone.utc)


def _iso(valor: datetime | None = None) -> str:
    return (valor or _agora_dt()).isoformat()


def reservar(
    chave: str, tipo: str, destino: str, caso_id: str | None = None, forcar: bool = False
) -> bool:
    """Reserva um envio, impedindo duplicidade entre API e workers concorrentes.

    `forcar` libera um reenvio deliberado: um envio já CONCLUÍDO ('enviado')
    deixa de barrar a operação — é o caso do atendente que, com o cliente ainda
    na chamada, pede o link de novo. O que nunca é liberado é um envio EM
    ANDAMENTO ('enviando'): essa continua sendo a defesa contra clique duplo e
    corrida entre a API e o worker.
    """
    instante = _iso()
    try:
        with conectar() as con:
            anterior = con.execute(
                "SELECT status FROM automacoes_whatsapp WHERE chave = ?", (chave,)
            ).fetchone()
            if anterior and anterior["status"] == "enviando":
                return False
            if anterior and anterior["status"] == "enviado" and not forcar:
                return False
            if anterior:
                con.execute(
                    """UPDATE automacoes_whatsapp
                          SET status = 'enviando', tentativas = tentativas + 1,
                              ultimo_erro = NULL, atualizado_em = ? WHERE chave = ?""",
                    (instante, chave),
                )
            else:
                con.execute(
                    """INSERT INTO automacoes_whatsapp
                       (chave, tipo, caso_id, destino, status, tentativas, criado_em, atualizado_em)
                       VALUES (?, ?, ?, ?, 'enviando', 1, ?, ?)""",
                    (chave, tipo, caso_id, destino, instante, instante),
                )
        return True
    except pyodbc.IntegrityError:
        return False


def finalizar(chave: str, erro: str | None = None) -> None:
    instante = _iso()
    with conectar() as con:
        con.execute(
            """UPDATE automacoes_whatsapp
                  SET status = ?, ultimo_erro = ?, enviado_em = ?, atualizado_em = ?
                WHERE chave = ?""",
            ("falhou" if erro else "enviado", erro, None if erro else instante, instante, chave),
        )


def telefone_do_caso(caso_id: str) -> str:
    """O WhatsApp que a entrevista colheu, recuperado do caso.

    POR QUE VEM DA ASSINATURA, E NÃO DA ENTREVISTA

    As respostas do roteiro NÃO são guardadas: elas vivem na tela enquanto o
    atendimento corre e vão embora com ela. O único lugar onde o telefone do
    cliente sobrevive é o registro da assinatura — o contrato é montado com as
    respostas, e `assinatura.montar_signatario` grava `phone_country` e
    `phone_number` no signatário.

    Não é rodeio: é onde o dado está. Pedir de novo um número que o cliente já
    ditou na entrevista é o tipo de retrabalho que faz a cobrança automática
    ficar desligada porque ninguém preencheu o campo.

    Vazio quando o caso ainda não tem contrato — aí o campo continua para
    digitar à mão, como antes.
    """
    try:
        assinaturas = armazenamento.listar_assinaturas(caso_id=caso_id)
        if not assinaturas:
            # POR NOME, quando o vínculo não existe -- e hoje ele quase nunca
            # existe: das assinaturas gravadas neste banco, NENHUMA tem
            # `caso_id` preenchido. Procurar só pelo vínculo devolveria vazio
            # sempre, e o recurso nasceria morto.
            #
            # É o mesmo par que o painel de assinaturas usa para reencontrar um
            # documento depois de um F5 (ver `listar_assinaturas`), com o nome
            # já normalizado lá dentro.
            caso = armazenamento.obter_caso(caso_id)
            cliente = str((caso or {}).get("cliente") or "").strip()
            if cliente:
                assinaturas = armazenamento.listar_assinaturas(cliente=cliente)
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
            "incluir_opcionais": False, "proximo_envio_em": None,
            "ultimo_envio_em": None, "ultimo_erro": None,
        }
    return {
        "caso_id": linha["caso_id"], "ativa": bool(linha["ativa"]),
        # O salvo vence: quem digitou outro número tinha motivo. A busca só cobre
        # o campo em branco — inclusive numa configuração antiga, salva antes de
        # o contrato existir.
        "telefone": linha["telefone"] or telefone_do_caso(caso_id),
        "intervalo_dias": linha["intervalo_dias"],
        "incluir_opcionais": bool(linha["incluir_opcionais"]),
        "proximo_envio_em": linha["proximo_envio_em"],
        "ultimo_envio_em": linha["ultimo_envio_em"], "ultimo_erro": linha["ultimo_erro"],
    }


def salvar_cobranca(
    caso_id: str, *, ativa: bool, telefone: str, intervalo_dias: int,
    incluir_opcionais: bool,
) -> dict[str, Any]:
    instante = _iso()
    proximo = instante if ativa else None
    with conectar() as con:
        existe = con.execute(
            "SELECT caso_id FROM cobrancas_documentos WHERE caso_id = ?", (caso_id,)
        ).fetchone()
        if existe:
            con.execute(
                """UPDATE cobrancas_documentos SET ativa = ?, telefone = ?, intervalo_dias = ?,
                   incluir_opcionais = ?, proximo_envio_em = ?, ultimo_erro = NULL,
                   atualizado_em = ? WHERE caso_id = ?""",
                (int(ativa), telefone, intervalo_dias, int(incluir_opcionais), proximo, instante, caso_id),
            )
        else:
            con.execute(
                """INSERT INTO cobrancas_documentos
                   (caso_id, ativa, telefone, intervalo_dias, incluir_opcionais,
                    proximo_envio_em, criado_em, atualizado_em)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (caso_id, int(ativa), telefone, intervalo_dias, int(incluir_opcionais), proximo, instante, instante),
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
) -> None:
    instante = _agora_dt()
    proximo = instante + timedelta(days=intervalo_dias)
    with conectar() as con:
        con.execute(
            """UPDATE cobrancas_documentos
                  SET proximo_envio_em = ?, ultimo_envio_em = ?, ultimo_hash = ?,
                      ultimo_erro = ?, atualizado_em = ? WHERE caso_id = ?""",
            (_iso(proximo), None if erro else _iso(instante), texto_hash, erro, _iso(instante), caso_id),
        )


def caso_existe(caso_id: str) -> bool:
    return armazenamento.obter_caso(caso_id) is not None
