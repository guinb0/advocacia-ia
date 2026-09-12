"""Perfis de acesso: quem enxerga qual módulo do Acervo.

O fluxo novo segue o desenho relacional usado nos outros sistemas da Level:
perfil, módulo e permissão se ligam por IDs. As tabelas antigas continuam vivas
(`acervo_perfis` e `acervo_perfil_modulos`) para não invalidar versões já
publicadas; este módulo mantém as duas em sincronia enquanto a transição existir.
"""

from __future__ import annotations

import json
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
    "historico",
    "usuarios_por_perfil",
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
        "codigo": "operacao",
        "rotulo": "Operação",
        "descricao": "Distribuição de atendimentos em curso e ligações registradas.",
        "rota": "operacao",
        "grupo": "Escritório",
        "ordem": 55,
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
        "codigo": "revisao",
        "rotulo": "Revisão de petições",
        "descricao": "Fila de petições a revisar, aprovação e métricas de revisão.",
        "rota": "revisao",
        "grupo": "Análise",
        "ordem": 65,
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
    {
        "codigo": "roteiros",
        "rotulo": "Roteiros de entrevista",
        "descricao": (
            "Manter o catálogo de roteiros: importar de um documento, editar "
            "perguntas e blocos, e desfazer edição."
        ),
        "rota": "catalogoRoteiros",
        # No "Escritório", e não em "Atendimento": manter o catálogo é trabalho
        # de bastidor. Quem conduz entrevista já edita o roteiro de dentro dela.
        "grupo": "Escritório",
        "ordem": 110,
    },
    {
        "codigo": "glossario_documentos",
        "rotulo": "Glossário de documentos",
        "descricao": (
            "Criar e editar os tipos de documento usados na classificação e na "
            "reclassificação. Consultar a lista é livre para a equipe."
        ),
        "rota": "glossarioDocumentos",
        # Manutenção de cadastro, como os roteiros: é o gestor do escritório que
        # decide o vocabulário, e não quem está com o documento na mão.
        "grupo": "Escritório",
        "ordem": 115,
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
            "entrevista", "casos", "documentos", "operacao", "agente", "contratos",
            "investigacao", "usuarios", "roteiros", "revisao",
            "glossario_documentos",
        ),
    },
    {
        "codigo": "secretario",
        "rotulo": "Secretário",
        "descricao": "Gerencia usuários e acompanha as entrevistas de toda a equipe.",
        "sistema": True,
        # `roteiros` sem `entrevista`: o secretário MANTÉM o roteiro do
        # escritório — importa do documento, corrige pergunta, desfaz edição —
        # sem necessariamente conduzir atendimento. São trabalhos diferentes, e
        # dar um não obriga a dar o outro.
        # `glossario_documentos` junto de `usuarios`: quem administra as contas do
        # escritório é o gestor, e o vocabulário dos documentos é cadastro dele.
        "modulos": (
            "casos", "documentos", "supervisao", "metricas", "operacao", "agente", "usuarios",
            "roteiros", "revisao", "glossario_documentos",
        ),
    },
    {
        "codigo": "revisor",
        "rotulo": "Revisor",
        "descricao": "Revisa e aprova as petições; vê a própria fila e as métricas de revisão.",
        "sistema": True,
        # Só a revisão: o revisor não conduz entrevista nem cadastra usuário. A
        # métrica é atividade operacional, não avaliação de qualidade (ver issue).
        "modulos": ("revisao",),
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
        "modulos": ("documentacao", "casos", "documentos", "agente"),
    },
)

_TABELA_PERFIS = f"{SCHEMA}.{PREFIXO}perfis"
_TABELA_ACESSOS = f"{SCHEMA}.{PREFIXO}perfil_modulos"
_TABELA_PERFIS_NOVA = f"{SCHEMA}.{PREFIXO}tb_perfis"
_TABELA_MODULOS = f"{SCHEMA}.{PREFIXO}tb_modulos_web"
_TABELA_PERMISSOES = f"{SCHEMA}.{PREFIXO}tb_permissoes"
_TABELA_ALTERACOES = f"{SCHEMA}.{PREFIXO}perfil_alteracoes"
#: Lida daqui, e não do módulo de contas, porque a pergunta é da MATRIZ: "quem
#: perde acesso se esta caixa for desmarcada?". Quem responde isso precisa
#: acompanhar a alteração no mesmo instante em que ela é gravada, e não depois,
#: da tela de cadastro.
_TABELA_USUARIOS = f"{SCHEMA}.{PREFIXO}usuarios"

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

IF OBJECT_ID('{_TABELA_ALTERACOES}') IS NULL
CREATE TABLE {_TABELA_ALTERACOES} (
    id             int            IDENTITY(1,1) NOT NULL CONSTRAINT pk_acervo_perfil_alteracoes PRIMARY KEY,
    perfil_codigo  varchar(60)    NOT NULL,
    acao           varchar(20)    NOT NULL,
    autor          nvarchar(200)  NOT NULL,
    resumo         nvarchar(600)  NOT NULL,
    antes          nvarchar(max)  NULL,
    depois         nvarchar(max)  NULL,
    criado_em      varchar(40)    NOT NULL
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


def _entregar_modulos_ineditos(con: Any) -> None:
    """Entrega aos perfis de sistema os módulos que esta instalação nunca viu.

    O CASO QUE ISTO RESOLVE, E POR QUE NÃO É "SOBRESCREVER"

    `_semear_legado` pula perfil já cadastrado, e com razão: o escritório pode
    ter ajustado o que o secretário enxerga, e subir o servidor não é hora de
    desfazer decisão de quem administra.

    Só que a consequência era esta: um módulo NOVO, acrescentado ao `MODULOS`
    junto com a rota que ele protege, nunca chegava a nenhuma instalação já
    existente. Ele entra no catálogo pelo `_sincronizar_modulos` e o
    `_garantir_matriz_completa` o carimba como NEGADO para todo mundo — a rota
    nasce guardada por um módulo que ninguém tem, e o recurso simplesmente não
    existe até alguém descobrir sozinho que precisa marcar uma caixa na tela.

    A distinção que torna isto seguro: um módulo que não aparece em linha nenhuma
    da tabela — para perfil nenhum — é um módulo que esta instalação nunca
    conheceu. Ninguém pode tê-lo desmarcado, porque ele não existia para ser
    desmarcado. Entregá-lo é completar a instalação, não desfazer escolha.

    Módulo que já aparece para qualquer perfil fica intocado, mesmo que este aqui
    não o tenha: aí houve decisão, e decisão de quem administra se respeita.
    """
    # Uma vez só, fora do laço: dentro dele, o módulo entregue ao advogado já
    # contaria como conhecido na vez do secretário, e ele ficaria de fora.
    conhecidos = {
        linha["modulo"]
        for linha in con.execute(f"SELECT DISTINCT modulo FROM {_TABELA_ACESSOS}").fetchall()
    }
    for perfil in SEMENTE:
        ineditos = [m for m in perfil["modulos"] if m not in conhecidos]
        for modulo in ineditos:
            con.execute(
                f"INSERT INTO {_TABELA_ACESSOS} (perfil_codigo, modulo) VALUES (?, ?)",
                (perfil["codigo"], modulo),
            )
        if ineditos:
            log.info(
                "Perfil '%s' recebeu os módulos novos %s.",
                perfil["codigo"],
                ", ".join(ineditos),
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
            f"SELECT id, rotulo, descricao, sistema FROM {_TABELA_PERFIS_NOVA} WHERE nome = ?",
            (nome,),
        ).fetchone()
        if existe:
            # UPDATE só quando algo REALMENTE mudou.
            #
            # Antes ele rodava para TODO perfil a cada subida, mesmo sem diferença
            # nenhuma. Cada UPDATE toma lock exclusivo da linha até o commit — e o
            # commit é no fim de toda a inicialização —, então duas instâncias
            # subindo juntas (ou um deploy junto de um teste) travavam uma na
            # outra. Medido em 12/09/2026: `perfis.inicializar` levou 52s esperando
            # lock; em 10/09 o mesmo ponto prendeu o uvicorn antes de abrir a porta
            # (ver o cabeçalho de `banco.limite_de_espera_por_lock`).
            #
            # No caso comum — nada mudou — agora não há escrita nem lock.
            novo = (
                str(perfil["rotulo"] or ""),
                str(perfil["descricao"] or ""),
                int(bool(perfil["sistema"])),
            )
            atual = (
                str(existe["rotulo"] or ""),
                str(existe["descricao"] or ""),
                int(bool(existe["sistema"])),
            )
            if novo != atual:
                con.execute(
                    f"""UPDATE {_TABELA_PERFIS_NOVA}
                           SET rotulo = ?, descricao = ?, sistema = ?
                         WHERE nome = ?""",
                    (*novo, nome),
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


#: Ids já resolvidos DENTRO de uma inicialização — nome → id.
#:
#: POR QUE ISSO EXISTE
#:
#: Medido em 12/09/2026, contra o SQL Server remoto: `inicializar()` disparava 428
#: statements e levava 50s, sem nenhum statement individualmente lento (60ms de ida
#: e volta cada). Dos 428, 272 eram a MESMA pergunta repetida — 143 vezes "qual o
#: id deste módulo" e 129 "qual o id deste perfil", para as mesmas duas dúzias de
#: nomes, porque cada par perfil×módulo da matriz de permissões refazia as duas
#: consultas.
#:
#: Id de linha existente não muda no meio da inicialização, então perguntar de novo
#: é só latência. Com o memo a subida faz ~27 buscas em vez de 272 — e, além do
#: tempo, encurta a janela em que a transação segura lock, que é o que já prendeu o
#: uvicorn antes de abrir a porta (ver `banco.limite_de_espera_por_lock`).
#:
#: Só id ENCONTRADO entra: "não existe" é estado que a própria inicialização muda
#: (ela insere em seguida), e cachear a ausência devolveria `None` depois do INSERT.
_ids_de_perfil: dict[str, int] = {}
_ids_de_modulo: dict[str, int] = {}


def _limpar_memo_de_ids() -> None:
    """Zera o memo. Chamado no começo de cada `inicializar()`."""
    _ids_de_perfil.clear()
    _ids_de_modulo.clear()


def _perfil_id(con: Any, nome: str) -> int | None:
    if nome in _ids_de_perfil:
        return _ids_de_perfil[nome]
    linha = con.execute(
        f"SELECT id FROM {_TABELA_PERFIS_NOVA} WHERE nome = ? AND ativo = 1", (nome,)
    ).fetchone()
    if not linha:
        return None
    _ids_de_perfil[nome] = int(linha["id"])
    return _ids_de_perfil[nome]


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
    if nome_modulo in _ids_de_modulo:
        return _ids_de_modulo[nome_modulo]
    linha = con.execute(
        f"SELECT id FROM {_TABELA_MODULOS} WHERE nome_modulo = ? AND ativo = 1",
        (nome_modulo,),
    ).fetchone()
    if not linha:
        return None
    _ids_de_modulo[nome_modulo] = int(linha["id"])
    return _ids_de_modulo[nome_modulo]


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


def _liberar_agente_para_perfis_internos(con: Any) -> None:
    """Agente jurídico é ferramenta comum do escritório, não permissão opcional.

    Vale também para perfis personalizados já existentes. ``cliente`` fica fora:
    ele usa apenas o portal público e nunca deve ganhar acesso ao backoffice.
    """
    perfis = con.execute(
        f"SELECT nome FROM {_TABELA_PERFIS_NOVA} WHERE ativo = 1 AND nome <> 'cliente'"
    ).fetchall()
    for perfil in perfis:
        nome = str(perfil["nome"])
        existe_legado = con.execute(
            f"SELECT 1 FROM {_TABELA_ACESSOS} WHERE perfil_codigo = ? AND modulo = 'agente'",
            (nome,),
        ).fetchone()
        if not existe_legado:
            con.execute(
                f"INSERT INTO {_TABELA_ACESSOS} (perfil_codigo, modulo) VALUES (?, 'agente')",
                (nome,),
            )
        _definir_permissao(con, nome, "agente", True)


def _liberar_operacao_para_advogado(con: Any) -> None:
    existe = con.execute(
        f"SELECT 1 FROM {_TABELA_ACESSOS} WHERE perfil_codigo = 'advogado' AND modulo = 'operacao'"
    ).fetchone()
    if existe:
        return
    con.execute(
        f"INSERT INTO {_TABELA_ACESSOS} (perfil_codigo, modulo) VALUES ('advogado', 'operacao')"
    )
    _definir_permissao(con, "advogado", "operacao", True)


def inicializar() -> None:
    """Cria as tabelas e garante os perfis de sistema. Idempotente."""
    with conectar() as con:
        from datetime import datetime, timezone

        # O memo vale por inicialização: dentro dela os ids não mudam, entre uma e
        # outra o banco pode ter mudado (outra instância criou um módulo novo).
        _limpar_memo_de_ids()
        _executar_schema(con)
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _semear_legado(con, agora)
        # ANTES do `_migrar_acessos_legados`, e essa ordem é o ponto: é ele que
        # leva o acesso da tabela legada para a matriz nova como permitido. Se
        # isto rodasse depois, o módulo novo já teria sido carimbado como negado
        # pelo `_garantir_matriz_completa` e ninguém o alcançaria.
        _entregar_modulos_ineditos(con)
        _sincronizar_modulos(con)
        _sincronizar_perfis(con, agora)
        _migrar_acessos_legados(con)
        _garantir_matriz_completa(con)
        _liberar_agente_para_perfis_internos(con)
        _liberar_operacao_para_advogado(con)


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


def _estado_de(con: Any, codigo: str) -> dict[str, Any] | None:
    """O perfil como ele está AGORA, ou `None` se ele ainda não existe.

    Lido dentro da transação de quem vai alterar, e não antes dela: entre uma
    leitura solta e a escrita cabe outra alteração, e a trilha registraria como
    "antes" um estado que já não era o anterior de verdade.
    """
    linha = con.execute(
        f"SELECT rotulo, descricao FROM {_TABELA_PERFIS} WHERE codigo = ?", (codigo,)
    ).fetchone()
    if linha is None:
        return None
    marcados = con.execute(
        f"""SELECT m.nome_modulo AS modulo
              FROM {_TABELA_PERMISSOES} a
              JOIN {_TABELA_PERFIS_NOVA} p ON p.id = a.perfil
              JOIN {_TABELA_MODULOS} m ON m.id = a.modulo
             WHERE p.nome = ? AND p.ativo = 1 AND m.ativo = 1 AND a.hasPermissao = 's'""",
        (codigo,),
    ).fetchall()
    return {
        "rotulo": linha["rotulo"],
        "descricao": linha["descricao"],
        "modulos": sorted(str(item["modulo"]) for item in marcados),
    }


def _resumo_da_mudanca(antes: dict[str, Any] | None, depois: dict[str, Any]) -> str:
    """O que mudou, em uma linha legível. Vazio quando nada mudou.

    Vazio é o sinal que impede a trilha de encher de linhas iguais: salvar sem
    ter mexido em nada é o que acontece quando alguém abre a tela, clica e
    desiste — e uma auditoria cheia desses registros esconde a alteração real.

    Os CÓDIGOS dos módulos vão no texto, não os rótulos. O rótulo é editável e
    muda com o tempo; o registro precisa continuar querendo dizer a mesma coisa
    daqui a um ano.
    """
    if antes is None:
        marcados = ", ".join(depois["modulos"]) or "nenhum módulo"
        return f"perfil criado com {marcados}"

    partes: list[str] = []
    if antes["rotulo"] != depois["rotulo"]:
        partes.append(f"rótulo: {antes['rotulo']} para {depois['rotulo']}")
    if antes["descricao"] != depois["descricao"]:
        partes.append("descrição alterada")

    concedidos = [m for m in depois["modulos"] if m not in antes["modulos"]]
    retirados = [m for m in antes["modulos"] if m not in depois["modulos"]]
    if concedidos:
        partes.append("módulos concedidos: " + ", ".join(concedidos))
    if retirados:
        partes.append("módulos retirados: " + ", ".join(retirados))
    return "; ".join(partes)


def _registrar(
    con: Any,
    codigo: str,
    acao: str,
    antes: dict[str, Any] | None,
    depois: dict[str, Any] | None,
    resumo: str,
    autor: str,
    agora: str,
) -> dict[str, Any] | None:
    """Grava a linha da trilha. `resumo` vazio não vira registro.

    Na MESMA transação da alteração, de propósito: uma trilha gravada à parte
    pode sobreviver a uma alteração que deu erro e foi desfeita — e aí o
    registro afirma uma mudança que não aconteceu.
    """
    if not resumo:
        return None
    con.execute(
        f"""INSERT INTO {_TABELA_ALTERACOES}
               (perfil_codigo, acao, autor, resumo, antes, depois, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            codigo,
            acao,
            autor or "desconhecido",
            resumo[:600],
            json.dumps(antes, ensure_ascii=False) if antes is not None else None,
            json.dumps(depois, ensure_ascii=False) if depois is not None else None,
            agora,
        ),
    )
    return {
        "perfil": codigo,
        "acao": acao,
        "autor": autor or "desconhecido",
        "resumo": resumo,
        "criado_em": agora,
    }


def _quantos_usam(con: Any, codigo: str) -> int:
    """Contas ligadas a este perfil, pelo id novo ou pelo nome legado."""
    identificador = _perfil_id(con, codigo)
    linha = con.execute(
        f"""SELECT COUNT(*) AS n
              FROM {_TABELA_USUARIOS}
             WHERE perfil = ? OR (? IS NOT NULL AND perfil_id = ?)""",
        (codigo, identificador, identificador),
    ).fetchone()
    return int(linha["n"]) if linha else 0


def usuarios_por_perfil() -> dict[str, dict[str, int]]:
    """Quantas contas cada perfil tem, no total e ativas.

    É o que responde "quem eu afeto se mexer nesta linha?" antes de a alteração
    ser feita. Sem isso, desmarcar um módulo é decisão tomada às cegas: a matriz
    mostra o desenho de acesso e não mostra a gente que está atrás dele.
    """
    with conectar() as con:
        linhas = con.execute(
            f"""SELECT COALESCE(p.nome, u.perfil) AS perfil,
                       COUNT(*) AS total,
                       SUM(CASE WHEN u.ativo = 1 THEN 1 ELSE 0 END) AS ativos
                  FROM {_TABELA_USUARIOS} u
             LEFT JOIN {_TABELA_PERFIS_NOVA} p ON p.id = u.perfil_id
              GROUP BY COALESCE(p.nome, u.perfil)"""
        ).fetchall()
    return {
        str(linha["perfil"]): {
            "total": int(linha["total"] or 0),
            "ativos": int(linha["ativos"] or 0),
        }
        for linha in linhas
        if linha["perfil"]
    }


def historico(limite: int = 50) -> list[dict[str, Any]]:
    """As últimas alterações de perfil, da mais recente para a mais antiga."""
    limite = max(1, min(int(limite), 200))
    with conectar() as con:
        linhas = con.execute(
            f"""SELECT TOP (?) id, perfil_codigo, acao, autor, resumo, antes, depois, criado_em
                  FROM {_TABELA_ALTERACOES}
                 ORDER BY id DESC""",
            (limite,),
        ).fetchall()
    return [
        {
            "id": linha["id"],
            "perfil": linha["perfil_codigo"],
            "acao": linha["acao"],
            "autor": linha["autor"],
            "resumo": linha["resumo"],
            "antes": json.loads(linha["antes"]) if linha["antes"] else None,
            "depois": json.loads(linha["depois"]) if linha["depois"] else None,
            "criado_em": linha["criado_em"],
        }
        for linha in linhas
    ]


def salvar(
    codigo: str,
    rotulo: str,
    descricao: str,
    modulos: list[str],
    *,
    autor: str = "",
) -> dict[str, Any]:
    """Cria ou atualiza um perfil e a lista de módulos que ele acessa.

    Módulo fora do catálogo é descartado em silêncio — não é erro do usuário, é
    tela desatualizada mandando código que não existe mais, e recusar a operação
    inteira por causa disso perderia as marcações válidas junto.

    `autor` é quem responde pela alteração e vai para a trilha
    (`acervo_perfil_alteracoes`) junto do estado anterior e do novo. Tem padrão
    vazio porque há chamadas internas sem sessão — a inicialização, por exemplo
    —, e essas gravam como "desconhecido" em vez de inventar um nome.
    """
    ativos = _codigos_modulos_ativos()
    limpo = [m for m in modulos if m in ativos]
    if codigo != "cliente" and "agente" in ativos and "agente" not in limpo:
        limpo.append("agente")
    descartados = [m for m in modulos if m not in ativos]
    if descartados:
        log.warning("Módulos desconhecidos ignorados em %r: %s", codigo, descartados)

    from datetime import datetime, timezone

    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conectar() as con:
        antes = _estado_de(con, codigo)
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

        depois = {"rotulo": rotulo, "descricao": descricao, "modulos": sorted(limpo)}
        resumo = _resumo_da_mudanca(antes, depois)
        # A contagem entra no resumo só quando alguém PERDE acesso: é o caso em
        # que a auditoria precisa saber o tamanho do estrago sem ter de
        # reconstruir depois quem usava o perfil naquele dia.
        perdeu = antes is not None and any(
            m not in depois["modulos"] for m in antes["modulos"]
        )
        if resumo and perdeu:
            afetadas = _quantos_usam(con, codigo)
            if afetadas:
                resumo = f"{resumo}; {afetadas} conta(s) usavam este perfil"
        registro = _registrar(
            con,
            codigo,
            "criado" if antes is None else "atualizado",
            antes,
            depois,
            resumo,
            autor,
            agora,
        )

    return {
        "codigo": codigo,
        "rotulo": rotulo,
        "descricao": descricao,
        "modulos": limpo,
        "alteracao": registro,
    }


def remover(codigo: str, *, autor: str = "") -> None:
    """Apaga um perfil. Os de sistema não podem ser apagados — ver `SEMENTE`."""
    from datetime import datetime, timezone

    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conectar() as con:
        antes = _estado_de(con, codigo)
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
        _registrar(con, codigo, "removido", antes, None, "perfil removido", autor, agora)


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
