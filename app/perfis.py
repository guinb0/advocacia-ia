"""Perfis de acesso: quem enxerga qual módulo do Acervo.

POR QUE A LISTA DEIXOU DE SER FECHADA

Até aqui os perfis eram três, cravados no código (`usuarios.PERFIS`), e o motivo
estava escrito lá: *"papel novo sem código que o entenda vira acesso
que ninguém sabe explicar"*. A objeção era certa — e é exatamente ela que este
módulo remove. Perfil novo agora nasce **com** o que o entende: uma linha por
módulo dizendo se aquele perfil entra ou não. Não há mais papel cujo alcance
ninguém saiba dizer; o alcance está na tabela, e a tela mostra.

ONDE CADA COISA MORA, E POR QUÊ

- **o perfil viaja no token**, no claim `perfil` que o `app/auth.py` assina no
  login. É o que permite decidir acesso sem consultar banco em toda requisição;
- **a matriz perfil × módulo é do Acervo.** Fica aqui, editável na tela, porque
  quem administra o escritório precisa mudar o alcance de um perfil sem esperar
  alguém subir código — e porque o alcance muda mais do que o perfil.

O CATÁLOGO DE MÓDULOS É FECHADO — E ESSE FECHAMENTO É O QUE VALE

Módulo é código: cada um corresponde a rotas que existem. Deixar o catálogo
aberto traria de volta o problema antigo por outra porta — alguém cadastraria o
módulo "financeiro", marcaria a caixa, e nada aconteceria, porque não existe rota
guardando nada com esse nome. Módulo novo entra aqui junto com a rota que ele
protege.

O QUE ACONTECE QUANDO A MATRIZ NÃO DIZ NADA

Nega. Perfil sem linha para um módulo não entra nele. O contrário — liberar o que
não foi declarado — faria cada módulo novo nascer aberto para todo mundo até
alguém lembrar de fechá-lo, e ninguém lembra.
"""

from __future__ import annotations

import logging
from typing import Any

from .banco import PREFIXO, SCHEMA, conectar

log = logging.getLogger("perfis")

__all__ = ["MODULOS", "CODIGOS_MODULOS", "listar", "salvar", "remover", "pode", "modulos_de"]

#: Os módulos do sistema, na ordem em que a tela os mostra. Cada `codigo` é
#: consumido por `auth.exigir_modulo` nas rotas — mudar um código aqui sem mudar
#: a rota abre o módulo para todo mundo, então eles são estáveis.
MODULOS: tuple[dict[str, str], ...] = (
    {
        "codigo": "entrevista",
        "rotulo": "Entrevista",
        "descricao": "Conduzir entrevista guiada, roteiro, triagem e chamada.",
    },
    {
        "codigo": "casos",
        "rotulo": "Casos",
        "descricao": "Carteira, checklist e dossiê dos casos do escritório.",
    },
    {
        "codigo": "documentos",
        "rotulo": "Documentos",
        "descricao": "Envio, leitura por OCR e conferência dos documentos.",
    },
    {
        "codigo": "documentacao",
        "rotulo": "Departamento de Documentação",
        "descricao": "Fila de entrevistas e transferência de chamadas para coleta documental.",
    },
    {
        "codigo": "supervisao",
        "rotulo": "Entrevistas no geral",
        "descricao": (
            "As entrevistas de toda a equipe, com auditoria de condução. "
            "É o painel do chefe e do analista."
        ),
    },
    {
        "codigo": "metricas",
        "rotulo": "Métricas gerais",
        "descricao": "Panorama do escritório e painéis de dados.",
    },
    {
        "codigo": "agente",
        "rotulo": "Agente jurídico",
        "descricao": "Análise do caso, jurimetria, estratégia e petição.",
    },
    {
        "codigo": "contratos",
        "rotulo": "Contratos e assinatura",
        "descricao": "Geração do contrato e envio para assinatura eletrônica.",
    },
    {
        "codigo": "investigacao",
        "rotulo": "Investigação",
        "descricao": "Consultas públicas e investigação patrimonial.",
    },
    {
        "codigo": "usuarios",
        "rotulo": "Usuários e perfis",
        "descricao": "Cadastrar pessoas e definir o que cada perfil acessa.",
    },
)
CODIGOS_MODULOS = tuple(m["codigo"] for m in MODULOS)

#: Perfis que o sistema garante existir. Não podem ser apagados: um Acervo sem
#: nenhum perfil que administre usuários fica sem ninguém capaz de consertá-lo —
#: e a única saída seria mexer no banco à mão.
SEMENTE: tuple[dict[str, Any], ...] = (
    {
        "codigo": "advogado",
        "rotulo": "Advogado",
        "descricao": "Conduz entrevistas, gera documentos e cadastra usuários.",
        "sistema": True,
        "modulos": (
            "entrevista", "casos", "documentos", "agente", "contratos",
            "investigacao", "usuarios",
        ),
    },
    {
        "codigo": "secretario",
        "rotulo": "Secretário",
        "descricao": "Gerencia usuários e acompanha as entrevistas de toda a equipe.",
        "sistema": True,
        "modulos": ("casos", "documentos", "supervisao", "metricas", "usuarios"),
    },
    {
        "codigo": "cliente",
        "rotulo": "Cliente",
        "descricao": "Acompanha o próprio caso e envia documentos pelo portal.",
        "sistema": True,
        # Nenhum módulo do Acervo: o cliente vive no portal, que tem porta
        # própria e sessão própria. Marcar qualquer caixa aqui lhe daria acesso
        # ao escritório inteiro.
        "modulos": (),
    },
    {
        "codigo": "documentacao",
        "rotulo": "Documentação",
        "descricao": "Assume chamadas e coleta os dados e documentos finais do cliente.",
        "sistema": True,
        "modulos": ("documentacao", "casos", "documentos"),
    },
)

_TABELA_PERFIS = f"{SCHEMA}.{PREFIXO}perfis"
_TABELA_ACESSOS = f"{SCHEMA}.{PREFIXO}perfil_modulos"

ESQUEMA = f"""
IF OBJECT_ID('{_TABELA_PERFIS}') IS NULL
CREATE TABLE {_TABELA_PERFIS} (
    codigo     varchar(60)   NOT NULL CONSTRAINT pk_acervo_perfis PRIMARY KEY,
    rotulo     nvarchar(120) NOT NULL,
    descricao  nvarchar(400) NOT NULL CONSTRAINT df_acervo_perfis_desc DEFAULT N'',
    sistema    bit           NOT NULL CONSTRAINT df_acervo_perfis_sis DEFAULT 0,
    criado_em  varchar(40)   NOT NULL
);

IF OBJECT_ID('{_TABELA_ACESSOS}') IS NULL
CREATE TABLE {_TABELA_ACESSOS} (
    perfil_codigo varchar(60) NOT NULL,
    modulo        varchar(60) NOT NULL,
    CONSTRAINT pk_acervo_perfil_modulos PRIMARY KEY (perfil_codigo, modulo)
);
"""


def inicializar() -> None:
    """Cria as tabelas e garante os perfis de sistema. Idempotente."""
    with conectar() as con:
        for lote in ESQUEMA.split(";\n"):
            if lote.strip():
                con.execute(lote)

        from datetime import datetime, timezone

        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for perfil in SEMENTE:
            existe = con.execute(
                f"SELECT 1 FROM {_TABELA_PERFIS} WHERE codigo = ?", (perfil["codigo"],)
            ).fetchone()
            if existe:
                # Perfil de sistema já cadastrado NÃO é sobrescrito: o escritório
                # pode ter ajustado o que o secretário enxerga, e uma reinicialização
                # do servidor não é lugar para desfazer decisão de quem administra.
                continue
            con.execute(
                f"INSERT INTO {_TABELA_PERFIS} (codigo, rotulo, descricao, sistema, criado_em)"
                " VALUES (?, ?, ?, 1, ?)",
                (perfil["codigo"], perfil["rotulo"], perfil["descricao"], agora),
            )
            for modulo in perfil["modulos"]:
                con.execute(
                    f"INSERT INTO {_TABELA_ACESSOS} (perfil_codigo, modulo) VALUES (?, ?)",
                    (perfil["codigo"], modulo),
                )


def listar() -> list[dict[str, Any]]:
    """Todos os perfis, cada um com a lista de módulos que ele acessa."""
    with conectar() as con:
        perfis = con.execute(
            f"SELECT codigo, rotulo, descricao, sistema, criado_em FROM {_TABELA_PERFIS}"
            " ORDER BY sistema DESC, rotulo"
        ).fetchall()
        acessos = con.execute(
            f"SELECT perfil_codigo, modulo FROM {_TABELA_ACESSOS}"
        ).fetchall()

    por_perfil: dict[str, list[str]] = {}
    for linha in acessos:
        por_perfil.setdefault(linha["perfil_codigo"], []).append(linha["modulo"])

    return [
        {
            "codigo": p["codigo"],
            "rotulo": p["rotulo"],
            "descricao": p["descricao"],
            "sistema": bool(p["sistema"]),
            "criado_em": p["criado_em"],
            # Na ordem do catálogo, não na do banco: a tela mostra a matriz e
            # duas linhas com a mesma marcação precisam parecer iguais.
            "modulos": [m for m in CODIGOS_MODULOS if m in por_perfil.get(p["codigo"], [])],
        }
        for p in perfis
    ]


def salvar(
    codigo: str, rotulo: str, descricao: str, modulos: list[str]
) -> dict[str, Any]:
    """Cria ou atualiza um perfil e a lista de módulos que ele acessa.

    Módulo fora do catálogo é descartado em silêncio — não é erro do usuário, é
    tela desatualizada mandando código que não existe mais, e recusar a operação
    inteira por causa disso perderia as marcações válidas junto.
    """
    limpo = [m for m in modulos if m in CODIGOS_MODULOS]
    descartados = [m for m in modulos if m not in CODIGOS_MODULOS]
    if descartados:
        log.warning("Módulos desconhecidos ignorados em %r: %s", codigo, descartados)

    from datetime import datetime, timezone

    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conectar() as con:
        existe = con.execute(
            f"SELECT sistema FROM {_TABELA_PERFIS} WHERE codigo = ?", (codigo,)
        ).fetchone()
        if existe:
            con.execute(
                f"UPDATE {_TABELA_PERFIS} SET rotulo = ?, descricao = ? WHERE codigo = ?",
                (rotulo, descricao, codigo),
            )
        else:
            con.execute(
                f"INSERT INTO {_TABELA_PERFIS} (codigo, rotulo, descricao, sistema, criado_em)"
                " VALUES (?, ?, ?, 0, ?)",
                (codigo, rotulo, descricao, agora),
            )
        # Substitui a matriz inteira: a tela manda o estado completo das caixas,
        # e comparar item a item só criaria caminho para divergência.
        con.execute(f"DELETE FROM {_TABELA_ACESSOS} WHERE perfil_codigo = ?", (codigo,))
        for modulo in limpo:
            con.execute(
                f"INSERT INTO {_TABELA_ACESSOS} (perfil_codigo, modulo) VALUES (?, ?)",
                (codigo, modulo),
            )

    return {"codigo": codigo, "rotulo": rotulo, "descricao": descricao, "modulos": limpo}


def remover(codigo: str) -> None:
    """Apaga um perfil. Os de sistema não podem ser apagados — ver `SEMENTE`."""
    with conectar() as con:
        linha = con.execute(
            f"SELECT sistema FROM {_TABELA_PERFIS} WHERE codigo = ?", (codigo,)
        ).fetchone()
        if linha is None:
            raise ValueError("Perfil não encontrado.")
        if bool(linha["sistema"]):
            raise ValueError(
                "Perfil de sistema não pode ser apagado. Ajuste os módulos que ele acessa."
            )
        con.execute(f"DELETE FROM {_TABELA_ACESSOS} WHERE perfil_codigo = ?", (codigo,))
        con.execute(f"DELETE FROM {_TABELA_PERFIS} WHERE codigo = ?", (codigo,))


def modulos_de(perfis: list[str] | tuple[str, ...]) -> set[str]:
    """A união dos módulos que estes perfis acessam.

    União, e não interseção: quem tem dois perfis pode o que qualquer um dos
    dois pode. É como papel funciona em todo lugar, e o contrário faria o
    acúmulo de perfis TIRAR acesso, que ninguém espera.
    """
    if not perfis:
        return set()
    marcadores = ",".join("?" for _ in perfis)
    with conectar() as con:
        linhas = con.execute(
            f"SELECT DISTINCT modulo FROM {_TABELA_ACESSOS}"
            f" WHERE perfil_codigo IN ({marcadores})",
            tuple(perfis),
        ).fetchall()
    return {linha["modulo"] for linha in linhas}


def pode(perfis: list[str] | tuple[str, ...], modulo: str) -> bool:
    """Estes perfis dão acesso a este módulo?

    Nega quando a matriz não diz nada — ver o cabeçalho do módulo.
    """
    return modulo in modulos_de(perfis)
