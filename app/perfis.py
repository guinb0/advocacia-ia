"""Perfis de acesso: quem enxerga qual módulo do Acervo.

O fluxo novo segue o desenho relacional usado nos outros sistemas da Level:
perfil, módulo e permissão se ligam por IDs. As tabelas antigas continuam vivas
(`acervo_perfis` e `acervo_perfil_modulos`) para não invalidar versões já
publicadas; este módulo mantém as duas em sincronia enquanto a transição existir.
"""

from __future__ import annotations

import logging
from typing import Any

from .banco import PREFIXO, SCHEMA, conectar

log = logging.getLogger("perfis")

__all__ = [
    "MODULOS",
    "CODIGOS_MODULOS",
    "catalogo",
    "listar",
    "salvar",
    "remover",
    "pode",
    "modulos_de",
    "modulos_ordenados_de",
    "perfil_id_de",
    "perfil_nome_de_id",
]

#: Os módulos do sistema, na ordem em que a tela os mostra. Cada `codigo` é
#: consumido por `auth.exigir_modulo` nas rotas — mudar um código aqui sem mudar
#: a rota abre o módulo para todo mundo, então eles são estáveis.
MODULOS: tuple[dict[str, str], ...] = (
    {
        "codigo": "entrevista",
        "rotulo": "Entrevista",
        "descricao": "Conduzir entrevista guiada, roteiro, triagem e chamada.",
        "rota": "entrevista",
        "grupo": "Atendimento",
        "ordem": 10,
    },
    {
        "codigo": "casos",
        "rotulo": "Casos",
        "descricao": "Carteira, checklist e dossiê dos casos do escritório.",
        "rota": "casos",
        "grupo": "Atendimento",
        "ordem": 20,
    },
    {
        "codigo": "documentos",
        "rotulo": "Documentos",
        "descricao": "Envio, leitura por OCR e conferência dos documentos.",
        "rota": "avulso",
        "grupo": "Análise",
        "ordem": 30,
    },
    {
        "codigo": "documentacao",
        "rotulo": "Departamento de Documentação",
        "descricao": "Fila de entrevistas e transferência de chamadas para coleta documental.",
        "rota": "documentacao",
        "grupo": "Atendimento",
        "ordem": 40,
    },
    {
        "codigo": "supervisao",
        "rotulo": "Entrevistas no geral",
        "descricao": (
            "As entrevistas de toda a equipe, com auditoria de condução. "
            "É o painel do chefe e do analista."
        ),
        "rota": "supervisao",
        "grupo": "Escritório",
        "ordem": 50,
    },
    {
        "codigo": "metricas",
        "rotulo": "Métricas gerais",
        "descricao": "Panorama do escritório e painéis de dados.",
        "rota": "panorama",
        "grupo": "Análise",
        "ordem": 60,
    },
    {
        "codigo": "agente",
        "rotulo": "Agente jurídico",
        "descricao": "Análise do caso, jurimetria, estratégia e petição.",
        "rota": "modelosDePeticao",
        "grupo": "Escritório",
        "ordem": 70,
    },
    {
        "codigo": "contratos",
        "rotulo": "Contratos e assinatura",
        "descricao": "Geração do contrato e envio para assinatura eletrônica.",
        "rota": "contratos",
        "grupo": "Escritório",
        "ordem": 80,
    },
    {
        "codigo": "investigacao",
        "rotulo": "Investigação",
        "descricao": "Consultas públicas e investigação patrimonial.",
        "rota": "investigacao",
        "grupo": "Análise",
        "ordem": 90,
    },
    {
        "codigo": "usuarios",
        "rotulo": "Usuários e perfis",
        "descricao": "Cadastrar pessoas e definir o que cada perfil acessa.",
        "rota": "usuarios",
        "grupo": "Escritório",
        "ordem": 100,
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
_TABELA_PERFIS_NOVA = f"{SCHEMA}.{PREFIXO}tb_perfis"
_TABELA_MODULOS = f"{SCHEMA}.{PREFIXO}tb_modulos_web"
_TABELA_PERMISSOES = f"{SCHEMA}.{PREFIXO}tb_permissoes"

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

IF OBJECT_ID('{_TABELA_PERFIS_NOVA}') IS NULL
CREATE TABLE {_TABELA_PERFIS_NOVA} (
    id         int           IDENTITY(1,1) NOT NULL CONSTRAINT pk_acervo_tb_perfis PRIMARY KEY,
    nome       varchar(60)   NOT NULL CONSTRAINT uq_acervo_tb_perfis_nome UNIQUE,
    rotulo     nvarchar(120) NOT NULL,
    descricao  nvarchar(400) NOT NULL CONSTRAINT df_acervo_tb_perfis_desc DEFAULT N'',
    sistema    bit           NOT NULL CONSTRAINT df_acervo_tb_perfis_sis DEFAULT 0,
    ativo      bit           NOT NULL CONSTRAINT df_acervo_tb_perfis_ativo DEFAULT 1,
    criado_em  varchar(40)   NOT NULL
);

IF OBJECT_ID('{_TABELA_MODULOS}') IS NULL
CREATE TABLE {_TABELA_MODULOS} (
    id           int           IDENTITY(1,1) NOT NULL CONSTRAINT pk_acervo_tb_modulos_web PRIMARY KEY,
    nome_modulo  varchar(60)   NOT NULL CONSTRAINT uq_acervo_tb_modulos_web_nome UNIQUE,
    rotulo       nvarchar(120) NOT NULL,
    descricao    nvarchar(400) NOT NULL CONSTRAINT df_acervo_tb_modulos_web_desc DEFAULT N'',
    rota         varchar(120)  NOT NULL CONSTRAINT df_acervo_tb_modulos_web_rota DEFAULT '',
    grupo        nvarchar(80)  NOT NULL CONSTRAINT df_acervo_tb_modulos_web_grupo DEFAULT N'',
    ordem        int           NOT NULL CONSTRAINT df_acervo_tb_modulos_web_ordem DEFAULT 0,
    ativo        bit           NOT NULL CONSTRAINT df_acervo_tb_modulos_web_ativo DEFAULT 1
);

IF OBJECT_ID('{_TABELA_PERMISSOES}') IS NULL
CREATE TABLE {_TABELA_PERMISSOES} (
    id            int     IDENTITY(1,1) NOT NULL CONSTRAINT pk_acervo_tb_permissoes PRIMARY KEY,
    modulo        int     NOT NULL,
    perfil        int     NOT NULL,
    hasPermissao  char(1) NOT NULL CONSTRAINT df_acervo_tb_permissoes_perm DEFAULT 'n',
    CONSTRAINT uq_acervo_tb_permissoes UNIQUE (modulo, perfil),
    CONSTRAINT fk_acervo_tb_permissoes_modulo FOREIGN KEY (modulo)
        REFERENCES {_TABELA_MODULOS} (id),
    CONSTRAINT fk_acervo_tb_permissoes_perfil FOREIGN KEY (perfil)
        REFERENCES {_TABELA_PERFIS_NOVA} (id)
);

IF OBJECT_ID('{SCHEMA}.ck_acervo_tb_permissoes_hasPermissao', 'C') IS NULL
ALTER TABLE {_TABELA_PERMISSOES}
    ADD CONSTRAINT ck_acervo_tb_permissoes_hasPermissao
    CHECK (hasPermissao IN ('s', 'n'));
"""


def _executar_schema(con: Any) -> None:
    for lote in ESQUEMA.split(";\n"):
        if lote.strip():
            con.execute(lote)


def _semear_legado(con: Any, agora: str) -> None:
    for perfil in SEMENTE:
        existe = con.execute(
            f"SELECT 1 FROM {_TABELA_PERFIS} WHERE codigo = ?", (perfil["codigo"],)
        ).fetchone()
        if existe:
            continue
        con.execute(
            f"INSERT INTO {_TABELA_PERFIS} (codigo, rotulo, descricao, sistema, criado_em)"
            " VALUES (?, ?, ?, 1, ?)",
            (perfil["codigo"], perfil["rotulo"], perfil["descricao"], agora),
        )
        for modulo in perfil["modulos"]:
            existe_acesso = con.execute(
                f"SELECT 1 FROM {_TABELA_ACESSOS} WHERE perfil_codigo = ? AND modulo = ?",
                (perfil["codigo"], modulo),
            ).fetchone()
            if not existe_acesso:
                con.execute(
                    f"INSERT INTO {_TABELA_ACESSOS} (perfil_codigo, modulo) VALUES (?, ?)",
                    (perfil["codigo"], modulo),
                )


def _sincronizar_modulos(con: Any) -> None:
    for modulo in MODULOS:
        existe = con.execute(
            f"SELECT id FROM {_TABELA_MODULOS} WHERE nome_modulo = ?",
            (modulo["codigo"],),
        ).fetchone()
        if existe:
            continue
        con.execute(
            f"""INSERT INTO {_TABELA_MODULOS}
                   (nome_modulo, rotulo, descricao, rota, grupo, ordem, ativo)
                VALUES (?, ?, ?, ?, ?, ?, 1)""",
            (
                modulo["codigo"],
                modulo["rotulo"],
                modulo["descricao"],
                modulo.get("rota", modulo["codigo"]),
                modulo.get("grupo", ""),
                modulo.get("ordem", 0),
            ),
        )


def _sincronizar_perfis(con: Any, agora: str) -> None:
    linhas = con.execute(
        f"SELECT codigo, rotulo, descricao, sistema, criado_em FROM {_TABELA_PERFIS}"
    ).fetchall()
    for perfil in linhas:
        nome = str(perfil["codigo"])
        existe = con.execute(
            f"SELECT id FROM {_TABELA_PERFIS_NOVA} WHERE nome = ?", (nome,)
        ).fetchone()
        if existe:
            con.execute(
                f"""UPDATE {_TABELA_PERFIS_NOVA}
                       SET rotulo = ?, descricao = ?, sistema = ?
                     WHERE nome = ?""",
                (perfil["rotulo"], perfil["descricao"], int(bool(perfil["sistema"])), nome),
            )
        else:
            con.execute(
                f"""INSERT INTO {_TABELA_PERFIS_NOVA}
                       (nome, rotulo, descricao, sistema, ativo, criado_em)
                    VALUES (?, ?, ?, ?, 1, ?)""",
                (
                    nome,
                    perfil["rotulo"],
                    perfil["descricao"],
                    int(bool(perfil["sistema"])),
                    perfil["criado_em"] or agora,
                ),
            )


def _perfil_id(con: Any, nome: str) -> int | None:
    linha = con.execute(
        f"SELECT id FROM {_TABELA_PERFIS_NOVA} WHERE nome = ? AND ativo = 1", (nome,)
    ).fetchone()
    return int(linha["id"]) if linha else None


def perfil_id_de(nome: str, *, ativo: bool = True, con: Any | None = None) -> int | None:
    """ID do perfil na tabela nova, mantendo o nome textual como contrato externo."""
    where_ativo = " AND ativo = 1" if ativo else ""

    def buscar(c: Any) -> int | None:
        linha = c.execute(
            f"SELECT id FROM {_TABELA_PERFIS_NOVA} WHERE nome = ?{where_ativo}",
            (nome,),
        ).fetchone()
        return int(linha["id"]) if linha else None

    if con is not None:
        return buscar(con)
    with conectar() as conexao:
        return buscar(conexao)


def perfil_nome_de_id(perfil_id: int, *, ativo: bool = True, con: Any | None = None) -> str | None:
    """Nome textual de um perfil novo, usado para compatibilidade com tokens antigos."""
    where_ativo = " AND ativo = 1" if ativo else ""

    def buscar(c: Any) -> str | None:
        linha = c.execute(
            f"SELECT nome FROM {_TABELA_PERFIS_NOVA} WHERE id = ?{where_ativo}",
            (perfil_id,),
        ).fetchone()
        return str(linha["nome"]) if linha else None

    if con is not None:
        return buscar(con)
    with conectar() as conexao:
        return buscar(conexao)


def _modulo_id(con: Any, nome_modulo: str) -> int | None:
    linha = con.execute(
        f"SELECT id FROM {_TABELA_MODULOS} WHERE nome_modulo = ? AND ativo = 1",
        (nome_modulo,),
    ).fetchone()
    return int(linha["id"]) if linha else None


def _definir_permissao(
    con: Any, perfil: str, modulo: str, permitido: bool, sobrescrever: bool = True
) -> None:
    perfil_id = _perfil_id(con, perfil)
    modulo_id = _modulo_id(con, modulo)
    if perfil_id is None or modulo_id is None:
        return
    valor = "s" if permitido else "n"
    existe = con.execute(
        f"SELECT id FROM {_TABELA_PERMISSOES} WHERE perfil = ? AND modulo = ?",
        (perfil_id, modulo_id),
    ).fetchone()
    if existe:
        if not sobrescrever:
            return
        con.execute(
            f"UPDATE {_TABELA_PERMISSOES} SET hasPermissao = ? WHERE id = ?",
            (valor, existe["id"]),
        )
    else:
        con.execute(
            f"INSERT INTO {_TABELA_PERMISSOES} (modulo, perfil, hasPermissao) VALUES (?, ?, ?)",
            (modulo_id, perfil_id, valor),
        )


def _migrar_acessos_legados(con: Any) -> None:
    acessos = con.execute(
        f"SELECT perfil_codigo, modulo FROM {_TABELA_ACESSOS}"
    ).fetchall()
    for acesso in acessos:
        _definir_permissao(
            con,
            acesso["perfil_codigo"],
            acesso["modulo"],
            True,
            sobrescrever=False,
        )


def _garantir_matriz_completa(con: Any) -> None:
    perfis = con.execute(
        f"SELECT nome FROM {_TABELA_PERFIS_NOVA} WHERE ativo = 1"
    ).fetchall()
    for perfil in perfis:
        for modulo in CODIGOS_MODULOS:
            _definir_permissao(con, perfil["nome"], modulo, False, sobrescrever=False)


def inicializar() -> None:
    """Cria as tabelas e garante os perfis de sistema. Idempotente."""
    with conectar() as con:
        from datetime import datetime, timezone

        _executar_schema(con)
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _semear_legado(con, agora)
        _sincronizar_modulos(con)
        _sincronizar_perfis(con, agora)
        _migrar_acessos_legados(con)
        _garantir_matriz_completa(con)


def catalogo() -> list[dict[str, Any]]:
    """Catálogo ativo do banco; vazio significa que nenhum módulo está ativo."""
    with conectar() as con:
        linhas = con.execute(
            f"""SELECT id, nome_modulo, rotulo, descricao, rota, grupo, ordem
                  FROM {_TABELA_MODULOS}
                 WHERE ativo = 1
                 ORDER BY ordem, id"""
        ).fetchall()
    return [
        {
            "id": linha["id"],
            # Campo de compatibilidade da API. A tabela nova não tem coluna
            # `codigo`; `nome_modulo` é o nome estável usado pelas versões atuais.
            "codigo": linha["nome_modulo"],
            "rotulo": linha["rotulo"],
            "descricao": linha["descricao"],
            "rota": linha["rota"],
            "grupo": linha["grupo"],
            "ordem": linha["ordem"],
        }
        for linha in linhas
    ]


def _codigos_modulos_ativos() -> set[str]:
    return {m["codigo"] for m in catalogo()}


def listar() -> list[dict[str, Any]]:
    """Todos os perfis, cada um com a lista de módulos que ele acessa."""
    with conectar() as con:
        perfis = con.execute(
            f"""SELECT id, nome AS codigo, rotulo, descricao, sistema, criado_em
                  FROM {_TABELA_PERFIS_NOVA}
                 WHERE ativo = 1
                 ORDER BY sistema DESC, rotulo"""
        ).fetchall()
        acessos = con.execute(
            f"""SELECT p.nome AS perfil_codigo, m.nome_modulo AS modulo
                  FROM {_TABELA_PERMISSOES} a
                  JOIN {_TABELA_PERFIS_NOVA} p ON p.id = a.perfil
                  JOIN {_TABELA_MODULOS} m ON m.id = a.modulo
                 WHERE p.ativo = 1 AND m.ativo = 1 AND a.hasPermissao = 's'"""
        ).fetchall()

    por_perfil: dict[str, list[str]] = {}
    for linha in acessos:
        por_perfil.setdefault(linha["perfil_codigo"], []).append(linha["modulo"])

    ordem_modulos = [m["codigo"] for m in catalogo()]
    return [
        {
            "id": p["id"],
            "codigo": p["codigo"],
            "rotulo": p["rotulo"],
            "descricao": p["descricao"],
            "sistema": bool(p["sistema"]),
            "criado_em": p["criado_em"],
            # Na ordem do catálogo, não na do banco: a tela mostra a matriz e
            # duas linhas com a mesma marcação precisam parecer iguais.
            "modulos": [m for m in ordem_modulos if m in por_perfil.get(p["codigo"], [])],
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
    ativos = _codigos_modulos_ativos()
    limpo = [m for m in modulos if m in ativos]
    descartados = [m for m in modulos if m not in ativos]
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
        _sincronizar_perfis(con, agora)
        for modulo in CODIGOS_MODULOS:
            _definir_permissao(con, codigo, modulo, modulo in limpo)

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
        perfil_id = _perfil_id(con, codigo)
        if perfil_id is not None:
            con.execute(f"DELETE FROM {_TABELA_PERMISSOES} WHERE perfil = ?", (perfil_id,))
            con.execute(f"UPDATE {_TABELA_PERFIS_NOVA} SET ativo = 0 WHERE id = ?", (perfil_id,))
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
            f"""SELECT DISTINCT m.nome_modulo AS modulo
                  FROM {_TABELA_PERMISSOES} a
                  JOIN {_TABELA_PERFIS_NOVA} p ON p.id = a.perfil
                  JOIN {_TABELA_MODULOS} m ON m.id = a.modulo
                 WHERE p.nome IN ({marcadores})
                   AND p.ativo = 1
                   AND m.ativo = 1
                   AND a.hasPermissao = 's'""",
            tuple(perfis),
        ).fetchall()
    return {linha["modulo"] for linha in linhas}


def modulos_ordenados_de(perfis: list[str] | tuple[str, ...]) -> list[str]:
    """Módulos permitidos na ordem do catálogo web."""
    if not perfis:
        return []
    marcadores = ",".join("?" for _ in perfis)
    with conectar() as con:
        linhas = con.execute(
            f"""SELECT DISTINCT m.nome_modulo AS modulo, m.ordem, m.id
                  FROM {_TABELA_PERMISSOES} a
                  JOIN {_TABELA_PERFIS_NOVA} p ON p.id = a.perfil
                  JOIN {_TABELA_MODULOS} m ON m.id = a.modulo
                 WHERE p.nome IN ({marcadores})
                   AND p.ativo = 1
                   AND m.ativo = 1
                   AND a.hasPermissao = 's'
                 ORDER BY m.ordem, m.id""",
            tuple(perfis),
        ).fetchall()
    return [linha["modulo"] for linha in linhas]


def pode(perfis: list[str] | tuple[str, ...], modulo: str) -> bool:
    """Estes perfis dão acesso a este módulo?

    Nega quando a matriz não diz nada — ver o cabeçalho do módulo.
    """
    return modulo in modulos_de(perfis)
