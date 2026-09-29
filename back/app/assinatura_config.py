"""Qual provedor de assinatura eletrônica está ativo, e o token de cada um.

TRÊS PROVEDORES, UMA CONFIGURAÇÃO SÓ

- **ZapSign** continua sendo o padrão e não passa por aqui: a credencial dele é
  do `.env` (API em `app/assinatura.py`, navegador em `app/assinatura_navegador.py`)
  porque foi assim que o escritório sempre configurou, e trocar isso agora
  quebraria um fluxo que já funciona sem necessidade.
- **Clicksign** e **Autentique** são opcionais: o escritório-cliente entra na tela
  de configuração, cola o PRÓPRIO token da conta dele e testa. Sem isso, o sistema
  segue mandando pela ZapSign — nunca fica sem caminho de assinatura por causa de
  uma integração nova mal configurada.

O QUE FICA GUARDADO, E COMO

Cada linha desta tabela é um provedor (`clicksign`, `autentique`). O token vai
CIFRADO (`app/cripto.py`) — nunca em claro no banco, e nunca de volta para a tela:
o que a tela recebe é `configurado` (há um token salvo) e o resultado do último
teste, não o valor. `ativo` diz qual provedor o próximo envio vai usar; só um pode
estar ativo por vez, e ativar um provedor sem teste aprovado é erro do usuário, não
do sistema — ver `ativar()`.

POR QUE "TESTADO" EXPIRA AO SALVAR TOKEN NOVO

Trocar o token invalida o teste anterior: o token velho podia estar certo e o novo
ainda não ter sido conferido contra a API de verdade. Sem zerar `testado_ok`, a tela
mostraria "conexão OK" para um token que ninguém testou.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from . import cripto
from .banco import PREFIXO, SCHEMA, conectar

log = logging.getLogger("assinatura_config")

_TABELA = "config_assinatura"

#: O ZapSign não entra aqui — ele usa o `.env`, como sempre usou.
PROVEDORES_COM_TOKEN = ("clicksign", "autentique")
PROVEDORES = ("zapsign",) + PROVEDORES_COM_TOKEN

ESQUEMA = f"""
IF OBJECT_ID('{SCHEMA}.{PREFIXO}{_TABELA}') IS NULL
CREATE TABLE {SCHEMA}.{PREFIXO}{_TABELA} (
    provedor          varchar(20)   NOT NULL CONSTRAINT pk_acervo_config_assinatura PRIMARY KEY,
    token_cifrado     nvarchar(max) NULL,
    ativo             bit           NOT NULL CONSTRAINT df_acervo_config_assin_ativo DEFAULT 0,
    testado_ok        bit           NOT NULL CONSTRAINT df_acervo_config_assin_testado DEFAULT 0,
    testado_em        varchar(40)   NULL,
    testado_mensagem  nvarchar(400) NULL,
    configurado_em    varchar(40)   NULL,
    atualizado_em     varchar(40)   NOT NULL
)
"""


class ErroConfigAssinatura(Exception):
    """Falha que a tela precisa ver — provedor desconhecido, ativação sem teste…"""


def inicializar() -> None:
    """Cria a tabela se ainda não existir. Chamado no start (main), como as outras."""
    with conectar() as con:
        con.execute(ESQUEMA)
        con.commit()


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validar_provedor_com_token(provedor: str) -> str:
    p = (provedor or "").strip().lower()
    if p not in PROVEDORES_COM_TOKEN:
        raise ErroConfigAssinatura(
            f"Provedor {provedor!r} desconhecido. Use um de: {', '.join(PROVEDORES_COM_TOKEN)}."
        )
    return p


def _linha(con: Any, provedor: str) -> Any:
    return con.execute(
        f"SELECT * FROM {SCHEMA}.{PREFIXO}{_TABELA} WHERE provedor = ?", (provedor,)
    ).fetchone()


def provedor_ativo() -> str:
    """Qual provedor o próximo envio deve usar. `zapsign` quando nenhum outro está ativo."""
    with conectar() as con:
        linha = con.execute(
            f"SELECT provedor FROM {SCHEMA}.{PREFIXO}{_TABELA} WHERE ativo = 1"
        ).fetchone()
    return str(linha["provedor"]) if linha else "zapsign"


def esta_pronto(provedor: str) -> bool:
    """Há token salvo E o último teste contra a API do provedor passou?"""
    provedor = _validar_provedor_com_token(provedor)
    with conectar() as con:
        linha = _linha(con, provedor)
    return bool(linha and linha["token_cifrado"] and linha["testado_ok"])


def status() -> list[dict[str, Any]]:
    """O que a tela de configuração mostra — nunca o token."""
    ativo = provedor_ativo()
    with conectar() as con:
        linhas = {
            str(r["provedor"]): r
            for r in con.execute(f"SELECT * FROM {SCHEMA}.{PREFIXO}{_TABELA}").fetchall()
        }
    saida = []
    for provedor in PROVEDORES:
        linha = linhas.get(provedor)
        saida.append(
            {
                "provedor": provedor,
                "ativo": provedor == ativo,
                "configurado": bool(linha and linha["token_cifrado"]) if linha else provedor == "zapsign",
                "testado_ok": bool(linha and linha["testado_ok"]) if linha else provedor == "zapsign",
                "testado_em": (linha["testado_em"] if linha else None),
                "testado_mensagem": (linha["testado_mensagem"] if linha else None),
            }
        )
    return saida


def salvar_token(provedor: str, token: str) -> None:
    """Cifra e grava o token do escritório. Zera o teste anterior — ver o cabeçalho."""
    provedor = _validar_provedor_com_token(provedor)
    token = (token or "").strip()
    if not token:
        raise ErroConfigAssinatura("Cole o token antes de salvar.")
    cifrado = cripto.cifrar(token)
    agora = _agora()
    with conectar() as con:
        con.execute(
            f"""
            MERGE {SCHEMA}.{PREFIXO}{_TABELA} AS alvo
            USING (SELECT ? AS provedor) AS origem
               ON alvo.provedor = origem.provedor
            WHEN MATCHED THEN UPDATE SET
                 token_cifrado = ?, testado_ok = 0, testado_em = NULL,
                 testado_mensagem = NULL, configurado_em = ?, atualizado_em = ?
            WHEN NOT MATCHED THEN INSERT
                 (provedor, token_cifrado, ativo, testado_ok, configurado_em, atualizado_em)
                 VALUES (?, ?, 0, 0, ?, ?);
            """,
            (provedor, cifrado, agora, agora, provedor, cifrado, agora, agora),
        )
        con.commit()


def token_de(provedor: str) -> str:
    """O token em claro, para a chamada à API do provedor. Só uso interno — nunca à tela."""
    provedor = _validar_provedor_com_token(provedor)
    with conectar() as con:
        linha = _linha(con, provedor)
    if not linha or not linha["token_cifrado"]:
        raise ErroConfigAssinatura(f"Nenhum token salvo para {provedor}.")
    return cripto.decifrar(str(linha["token_cifrado"]))


def marcar_teste(provedor: str, ok: bool, mensagem: str) -> None:
    """Registra o resultado do botão "Testar conexão"."""
    provedor = _validar_provedor_com_token(provedor)
    with conectar() as con:
        con.execute(
            f"UPDATE {SCHEMA}.{PREFIXO}{_TABELA} "
            "SET testado_ok = ?, testado_em = ?, testado_mensagem = ?, atualizado_em = ? "
            "WHERE provedor = ?",
            (1 if ok else 0, _agora(), (mensagem or "")[:400], _agora(), provedor),
        )
        con.commit()


def ativar(provedor: str) -> None:
    """Torna `provedor` o caminho de envio. Exige teste aprovado, exceto para a ZapSign.

    Ativar sem testar deixaria o escritório mandando o primeiro contrato de
    verdade contra uma credencial nunca conferida — e um contrato que não chega
    ao cliente só aparece como problema dias depois, no acompanhamento do caso.
    """
    provedor = (provedor or "").strip().lower()
    if provedor not in PROVEDORES:
        raise ErroConfigAssinatura(
            f"Provedor {provedor!r} desconhecido. Use um de: {', '.join(PROVEDORES)}."
        )
    if provedor != "zapsign" and not esta_pronto(provedor):
        raise ErroConfigAssinatura(
            f"Teste a conexão com {provedor} antes de ativá-lo — sem isso o token "
            "pode estar errado e os contratos não sairiam para assinatura."
        )
    agora = _agora()
    with conectar() as con:
        con.execute(
            f"UPDATE {SCHEMA}.{PREFIXO}{_TABELA} SET ativo = 0, atualizado_em = ?", (agora,)
        )
        if provedor != "zapsign":
            con.execute(
                f"UPDATE {SCHEMA}.{PREFIXO}{_TABELA} SET ativo = 1, atualizado_em = ? "
                "WHERE provedor = ?",
                (agora, provedor),
            )
        con.commit()
