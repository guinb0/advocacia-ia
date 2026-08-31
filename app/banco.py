"""Conexão com o SQL Server, com a mesma interface que o SQLite oferecia.

O Acervo nasceu em SQLite (`dados/casos.db`), um arquivo na máquina do advogado. Isso
serve enquanto é uma pessoa só: o arquivo não é alcançável de outro computador, não tem
backup e não aceita duas escritas ao mesmo tempo.

Este módulo troca o motor sem reescrever as 44 funções de `armazenamento.py`. A interface
é a que o código já usa — `conectar()` como gerenciador de contexto, `execute(sql, params)`
com `?`, e linhas acessíveis por nome de coluna:

    with conectar() as con:
        linha = con.execute("SELECT * FROM casos WHERE id = ?", (caso_id,)).fetchone()
        print(linha["cliente"])

O que muda de verdade, e por que:

- **`?` continua sendo o marcador**, porque o pyodbc usa o mesmo do sqlite3. Foi sorte, e é
  o que permitiu manter as consultas como estavam;
- **`INSERT OR REPLACE` não existe** no SQL Server. Vira `MERGE`, escrito nas duas funções
  que o usavam;
- **função Python registrada na conexão** (`normalizar_nome_cliente`) não tem equivalente:
  o SQL Server não roda Python dentro da query. A normalização passou a ser feita antes,
  em Python, com o valor já normalizado sendo gravado na coluna;
- **`COLLATE NOCASE`** some: o banco usa `Latin1_General_CI_AS`, que já ignora maiúsculas.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from pathlib import Path
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import pyodbc

from . import ambiente

__all__ = [
    "ESQUEMA_SQLSERVER",
    "Conexao",
    "Linha",
    "conectar",
    "dsn",
    "inicializar_schema",
    "sessao",
]

SCHEMA = "dbo"
"""Schema único do banco `advocacia` — o mesmo do agente jurídico.

O Acervo teve schema próprio (`ocr`) por um tempo. Voltou para o `dbo` porque quatro
schemas com nome parecido, três deles vazios, custavam mais em confusão do que rendiam em
separação. Quem precisa distinguir os dois sistemas lê o prefixo da tabela.
"""

PREFIXO = "acervo_"
"""Prefixo das tabelas do Acervo dentro do `dbo`.

Sem ele, `casos` (Acervo) ficaria ao lado de `cases` (agente) guardando coisas diferentes,
e `entregas` ao lado de `documents`, que são o mesmo documento visto por cada lado. O
prefixo é o que substitui o schema separado na hora de saber de quem é cada tabela.
"""

DRIVER_PADRAO = "ODBC Driver 17 for SQL Server"


_ENV = ambiente.CAMINHO

#: Mantido como nome local porque metade do módulo (e os testes) já o chamam assim.
#: A leitura em si mudou de casa: ver o cabeçalho de `app/ambiente.py`.
_carregar_env = ambiente.carregar


def dsn() -> str:
    """String de conexão ODBC, montada a partir do ambiente.

    Segredo não mora em código. Sem `SQLSERVER_*` no ambiente nem no `.env`, falha aqui —
    no boot — em vez de na primeira consulta, quando o advogado já está com o caso aberto
    na tela.
    """
    _carregar_env()
    servidor = os.getenv("SQLSERVER_HOST")
    senha = os.getenv("SQLSERVER_PASSWORD")
    if not servidor or not senha:
        raise RuntimeError(
            "Faltam SQLSERVER_HOST e SQLSERVER_PASSWORD no ambiente (.env da raiz)."
        )
    return (
        f"DRIVER={{{os.getenv('SQLSERVER_DRIVER', DRIVER_PADRAO)}}};"
        f"SERVER={servidor},{os.getenv('SQLSERVER_PORT', '1433')};"
        f"DATABASE={os.getenv('SQLSERVER_DATABASE', 'advocacia')};"
        f"UID={os.getenv('SQLSERVER_USER', 'advocacia')};"
        f"PWD={senha};"
        "TrustServerCertificate=yes;"
    )


def url_sqlalchemy() -> str:
    """A mesma conexão em forma de URL, para quem precisa de SQLAlchemy."""
    senha = urllib.parse.quote_plus(os.environ["SQLSERVER_PASSWORD"])
    usuario = os.getenv("SQLSERVER_USER", "advocacia")
    servidor = os.environ["SQLSERVER_HOST"]
    porta = os.getenv("SQLSERVER_PORT", "1433")
    banco = os.getenv("SQLSERVER_DATABASE", "advocacia")
    driver = urllib.parse.quote_plus(os.getenv("SQLSERVER_DRIVER", DRIVER_PADRAO))
    return (
        f"mssql+pyodbc://{usuario}:{senha}@{servidor}:{porta}/{banco}?driver={driver}"
    )


class Linha:
    """Linha acessível por nome de coluna, como a `sqlite3.Row` era.

    O `pyodbc` devolve tuplas com atributos, e o código do Acervo lê `linha["campo"]` em
    dezenas de lugares. Este envelope evita reescrever tudo isso.
    """

    __slots__ = ("_valores",)

    def __init__(self, colunas: Sequence[str], valores: Sequence[Any]) -> None:
        self._valores = dict(zip(colunas, valores, strict=True))

    def __getitem__(self, chave: str | int) -> Any:
        # Por índice também, como a `sqlite3.Row` permitia: `SELECT count(*)` não tem
        # nome de coluna, e o código lê `linha[0]` nesses casos.
        if isinstance(chave, int):
            return list(self._valores.values())[chave]
        return self._valores[chave]

    def __contains__(self, chave: object) -> bool:
        return chave in self._valores

    def keys(self) -> Any:
        return self._valores.keys()

    def get(self, chave: str, padrao: Any = None) -> Any:
        return self._valores.get(chave, padrao)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._valores.values())

    def __repr__(self) -> str:
        return f"Linha({self._valores!r})"


class _Resultado:
    """O que `execute()` devolve: `fetchone`, `fetchall` e iteração, como antes."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor
        self._colunas = (
            [d[0] for d in cursor.description] if cursor.description is not None else []
        )

    def fetchone(self) -> Linha | None:
        linha = self._cursor.fetchone()
        return None if linha is None else Linha(self._colunas, linha)

    def fetchall(self) -> list[Linha]:
        return [Linha(self._colunas, linha) for linha in self._cursor.fetchall()]

    def __iter__(self) -> Iterator[Linha]:
        for linha in self._cursor:
            yield Linha(self._colunas, linha)

    @property
    def rowcount(self) -> int:
        return int(self._cursor.rowcount)


class Conexao:
    """Envelope fino sobre a conexão pyodbc, com a interface que o Acervo já usa."""

    def __init__(self, bruta: pyodbc.Connection) -> None:
        self._bruta = bruta

    def execute(self, sql: str, params: Sequence[Any] = ()) -> _Resultado:
        cursor = self._bruta.cursor()
        cursor.execute(_qualificar(sql), tuple(params))
        return _Resultado(cursor)

    def executemany(self, sql: str, seq: Sequence[Sequence[Any]]) -> None:
        cursor = self._bruta.cursor()
        # A base de municípios tem milhares de linhas. Sem o envio em lote do
        # pyodbc, cada linha paga uma viagem completa até o SQL Server remoto.
        if hasattr(cursor, "fast_executemany"):
            cursor.fast_executemany = True
        cursor.executemany(_qualificar(sql), [tuple(p) for p in seq])

    def commit(self) -> None:
        self._bruta.commit()

    def rollback(self) -> None:
        self._bruta.rollback()

    def close(self) -> None:
        self._bruta.close()


# Tabelas do Acervo. O SQL do módulo `armazenamento` as nomeia sem schema — é assim que
# estavam no SQLite —, e qualificar aqui evita reescrever 58 consultas.
TABELAS = (
    "casos",
    "classificacoes_documentos_corrigidas",
    "entregas",
    "entrevistas",
    "peticoes_locais",
    "assinaturas",
    "roteiros",
    "ufs",
    "municipios",
    # `conversa_mensagens` vem antes de `conversas` só por clareza de leitura: a regex
    # de `_qualificar` já recusa prefixo de nome maior, e uma não alcança a outra.
    "conversa_mensagens",
    "conversas",
    "automacoes_whatsapp",
    "cobrancas_documentos",
    "modelos_documento",
)


def _qualificar(sql: str) -> str:
    """Traduz o nome curto da tabela para o nome real no banco.

    O SQL de `armazenamento.py` fala `casos`, `entregas` — os nomes que as tabelas tinham
    no SQLite. No banco elas se chamam `dbo.acervo_casos`, `dbo.acervo_entregas`. A
    tradução acontece aqui para que as 58 consultas continuem legíveis e não precisem
    repetir schema e prefixo em cada linha.

    Idempotente: consulta que já venha com o nome real passa intacta. Sem isso, prefixar
    de novo produz `acervo_acervo_casos` — e o erro que aparece é "nome de objeto
    inválido", que não denuncia o prefixo dobrado.
    """
    resultado = sql
    for tabela in TABELAS:
        # `(?<![\w.])` recusa o que já tem ponto ou letra antes — ou seja, o que já foi
        # qualificado e o que é sufixo de outra palavra; `(?![\w.])` recusa prefixo de
        # nome maior (`casos_antigos`).
        resultado = re.sub(
            rf"(?<![\w.]){tabela}(?![\w.])",
            f"{SCHEMA}.{PREFIXO}{tabela}",
            resultado,
        )
    return resultado


#: Conexão emprestada pelo escopo em curso, quando há um (ver `sessao`).
_emprestada: ContextVar[Conexao | None] = ContextVar("conexao_emprestada", default=None)


@contextmanager
def conectar() -> Iterator[Conexao]:
    """Abre transação, confirma no fim e desfaz em qualquer erro.

    Mesmo contrato do `conectar()` que existia sobre o SQLite: quem chama não precisa
    lembrar de `commit`.

    Dentro de uma `sessao()`, reaproveita a conexão dela em vez de abrir outra — e aí
    não confirma nem fecha, porque quem abriu é que encerra.
    """
    ja_aberta = _emprestada.get()
    if ja_aberta is not None:
        yield ja_aberta
        return

    bruta = pyodbc.connect(dsn(), timeout=15, autocommit=False)
    conexao = Conexao(bruta)
    try:
        yield conexao
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    finally:
        conexao.close()


@contextmanager
def sessao() -> Iterator[Conexao]:
    """Uma conexão só para tudo que rodar dentro deste bloco.

    O banco é remoto: cada `pyodbc.connect` custa a viagem de rede do handshake e do
    login, medida em ~135 ms daqui. Telas como o painel do caso chamavam trinta e três
    funções de leitura independentes e pagavam essa viagem trinta e três vezes — cinco
    segundos gastos abrindo conexão para consultas que somadas não leem 100 kB.

    Vale para leitura. Escrita dentro do bloco passa a compartilhar a transação de quem
    o abriu, o que muda o momento do commit — por isso o escopo é explícito, e não algo
    que `conectar()` faça sozinho por toda a aplicação.

    Não atravessa thread: `ContextVar` não é herdada por thread de `ThreadPoolExecutor`,
    então cada uma abre a sua. É o que se quer — conexão pyodbc não é para ser
    compartilhada entre threads.
    """
    with conectar() as con:
        if _emprestada.get() is not None:
            # Já estamos dentro de uma sessão: o bloco de fora é que manda.
            yield con
            return
        marca = _emprestada.set(con)
        try:
            yield con
        finally:
            _emprestada.reset(marca)


# ---------------------------------------------------------------------------- schema

ESQUEMA_SQLSERVER = f"""
IF SCHEMA_ID('{SCHEMA}') IS NULL EXEC('CREATE SCHEMA {SCHEMA}');

IF OBJECT_ID('{SCHEMA}.{PREFIXO}casos') IS NULL
CREATE TABLE {SCHEMA}.{PREFIXO}casos (
    id                varchar(64)   NOT NULL CONSTRAINT pk_ocr_casos PRIMARY KEY,
    cliente           nvarchar(200) NOT NULL,
    categoria         varchar(80)   NOT NULL,
    observacao        nvarchar(max) NOT NULL CONSTRAINT df_ocr_casos_obs DEFAULT N'',
    criado_em         varchar(40)   NOT NULL,
    atualizado_em     varchar(40)   NOT NULL,
    portal_token      varchar(80)   NULL,
    portal_senha_hash varchar(255)  NULL,
    portal_sal        varchar(80)   NULL,
    portal_criado_em  varchar(40)   NULL,
    case_ref          varchar(80)   NULL,
    cliente_ref       varchar(80)   NULL,
    agente_ultimo_erro nvarchar(max) NULL,
    telefone          varchar(30)   NOT NULL CONSTRAINT df_ocr_casos_tel DEFAULT ''
);

IF OBJECT_ID('{SCHEMA}.{PREFIXO}entregas') IS NULL
CREATE TABLE {SCHEMA}.{PREFIXO}entregas (
    id                 varchar(64)   NOT NULL CONSTRAINT pk_ocr_entregas PRIMARY KEY,
    caso_id            varchar(64)   NOT NULL,
    item_codigo        varchar(80)   NOT NULL,
    arquivo            nvarchar(255) NOT NULL,
    caminho            nvarchar(500) NOT NULL,
    conteudo           varbinary(max) NULL,
    conteudo_sha256    char(64)       NULL,
    tipo_detectado     varchar(80)   NULL,
    tipo_confere       int           NULL,
    veredito           varchar(40)   NULL,
    dados_utilizaveis  int           NOT NULL CONSTRAINT df_ocr_entregas_uteis DEFAULT 0,
    confirmado_manual  int           NOT NULL CONSTRAINT df_ocr_entregas_conf DEFAULT 0,
    score_legibilidade int           NULL,
    itens_atendidos    nvarchar(max) NOT NULL CONSTRAINT df_ocr_entregas_itens DEFAULT N'[]',
    texto_utilizavel   int           NULL,
    lote_id            varchar(64)   NULL,
    roteamento_origem  varchar(20)   NULL,
    roteamento_confianca int         NULL,
    roteamento_motivo  nvarchar(600) NULL,
    extracao_json      nvarchar(max) NULL,
    criado_em          varchar(40)   NOT NULL,
    status_proc        varchar(40)   NOT NULL CONSTRAINT df_ocr_entregas_status DEFAULT 'pronto',
    erro_proc          nvarchar(max) NULL,
    agente_envio_chave varchar(120)  NULL,
    CONSTRAINT fk_ocr_entregas_caso FOREIGN KEY (caso_id)
        REFERENCES {SCHEMA}.{PREFIXO}casos (id) ON DELETE CASCADE
);

IF OBJECT_ID('{SCHEMA}.{PREFIXO}classificacoes_documentos_corrigidas') IS NULL
CREATE TABLE {SCHEMA}.{PREFIXO}classificacoes_documentos_corrigidas (
    id                  varchar(64)    NOT NULL CONSTRAINT pk_acervo_class_doc_corr PRIMARY KEY,
    entrega_id          varchar(64)    NOT NULL,
    caso_id             varchar(64)    NOT NULL,
    categoria           varchar(120)   NOT NULL,
    tipo_sugerido       nvarchar(160)  NULL,
    tipo_correto        varchar(80)    NOT NULL,
    rotulo_correto      nvarchar(200)  NOT NULL,
    item_codigo         varchar(80)    NOT NULL,
    corrigido_por       nvarchar(200)  NOT NULL,
    criado_em           varchar(40)    NOT NULL,
    CONSTRAINT fk_acervo_class_doc_corr_entrega FOREIGN KEY (entrega_id)
        REFERENCES {SCHEMA}.{PREFIXO}entregas (id) ON DELETE CASCADE,
    CONSTRAINT fk_acervo_class_doc_corr_caso FOREIGN KEY (caso_id)
        REFERENCES {SCHEMA}.{PREFIXO}casos (id)
);

IF OBJECT_ID('{SCHEMA}.{PREFIXO}entrevistas') IS NULL
CREATE TABLE {SCHEMA}.{PREFIXO}entrevistas (
    id            varchar(64)   NOT NULL CONSTRAINT pk_ocr_entrevistas PRIMARY KEY,
    caso_id       varchar(64)   NOT NULL,
    arquivo       nvarchar(255) NOT NULL,
    caminho       nvarchar(500) NOT NULL,
    texto         nvarchar(max) NOT NULL CONSTRAINT df_ocr_entrev_texto DEFAULT N'',
    realizada_em  varchar(40)   NOT NULL CONSTRAINT df_ocr_entrev_data DEFAULT '',
    entrevistador nvarchar(200) NOT NULL CONSTRAINT df_ocr_entrev_quem DEFAULT N'',
    resumo        nvarchar(max) NOT NULL CONSTRAINT df_ocr_entrev_resumo DEFAULT N'',
    perguntas     nvarchar(max) NOT NULL CONSTRAINT df_ocr_entrev_perg DEFAULT N'[]',
    fatos_gerados int           NOT NULL CONSTRAINT df_ocr_entrev_fatos DEFAULT 0,
    enviada_em    varchar(40)   NULL,
    avaliacao_google_em varchar(40) NULL,
    gravacao_id   varchar(64)   NULL,
    criado_em     varchar(40)   NOT NULL,
    CONSTRAINT fk_ocr_entrevistas_caso FOREIGN KEY (caso_id)
        REFERENCES {SCHEMA}.{PREFIXO}casos (id) ON DELETE CASCADE
);

IF OBJECT_ID('{SCHEMA}.{PREFIXO}peticoes_locais') IS NULL
CREATE TABLE {SCHEMA}.{PREFIXO}peticoes_locais (
    caso_id       varchar(64)    NOT NULL CONSTRAINT pk_acervo_peticoes_locais PRIMARY KEY,
    versao        int            NOT NULL CONSTRAINT df_acervo_peticao_versao DEFAULT 1,
    status        varchar(40)    NOT NULL CONSTRAINT df_acervo_peticao_status DEFAULT 'IN_REVIEW',
    dados_json    nvarchar(max)  NOT NULL,
    docx          varbinary(max) NOT NULL,
    criado_em     varchar(40)    NOT NULL,
    atualizado_em varchar(40)    NOT NULL,
    CONSTRAINT fk_acervo_peticao_caso FOREIGN KEY (caso_id)
        REFERENCES {SCHEMA}.{PREFIXO}casos (id) ON DELETE CASCADE
);

IF OBJECT_ID('{SCHEMA}.{PREFIXO}assinaturas') IS NULL
CREATE TABLE {SCHEMA}.{PREFIXO}assinaturas (
    id            varchar(64)   NOT NULL CONSTRAINT pk_ocr_assinaturas PRIMARY KEY,
    doc_token     varchar(120)  NOT NULL CONSTRAINT uq_ocr_assinaturas_token UNIQUE,
    nome          nvarchar(200) NOT NULL,
    cliente       nvarchar(200) NOT NULL CONSTRAINT df_ocr_assin_cliente DEFAULT N'',
    caso_id       varchar(64)   NULL,
    estado        varchar(40)   NOT NULL CONSTRAINT df_ocr_assin_estado DEFAULT 'pendente',
    signatarios   nvarchar(max) NOT NULL CONSTRAINT df_ocr_assin_signat DEFAULT N'[]',
    arquivo       nvarchar(255) NULL,
    criado_em     varchar(40)   NOT NULL,
    atualizado_em varchar(40)   NOT NULL,
    cpf           varchar(20)   NOT NULL CONSTRAINT df_ocr_assin_cpf DEFAULT ''
);

IF OBJECT_ID('{SCHEMA}.{PREFIXO}automacoes_whatsapp') IS NULL
CREATE TABLE {SCHEMA}.{PREFIXO}automacoes_whatsapp (
    chave         varchar(220)  NOT NULL CONSTRAINT pk_acervo_automacoes_whatsapp PRIMARY KEY,
    tipo          varchar(50)   NOT NULL,
    caso_id       varchar(64)   NULL,
    destino       varchar(20)   NOT NULL,
    status        varchar(20)   NOT NULL,
    tentativas    int           NOT NULL CONSTRAINT df_acervo_auto_tentativas DEFAULT 1,
    ultimo_erro   nvarchar(1000) NULL,
    enviado_em    varchar(40)   NULL,
    criado_em     varchar(40)   NOT NULL,
    atualizado_em varchar(40)   NOT NULL
);

IF OBJECT_ID('{SCHEMA}.{PREFIXO}cobrancas_documentos') IS NULL
CREATE TABLE {SCHEMA}.{PREFIXO}cobrancas_documentos (
    caso_id            varchar(64)   NOT NULL CONSTRAINT pk_acervo_cobrancas_documentos PRIMARY KEY,
    ativa              int           NOT NULL CONSTRAINT df_acervo_cobranca_ativa DEFAULT 0,
    telefone           varchar(20)   NOT NULL CONSTRAINT df_acervo_cobranca_telefone DEFAULT '',
    intervalo_dias     int           NOT NULL CONSTRAINT df_acervo_cobranca_intervalo DEFAULT 3,
    incluir_opcionais  int           NOT NULL CONSTRAINT df_acervo_cobranca_opcionais DEFAULT 0,
    proximo_envio_em   varchar(40)   NULL,
    ultimo_envio_em    varchar(40)   NULL,
    ultimo_hash        char(64)      NULL,
    ultimo_erro        nvarchar(1000) NULL,
    criado_em          varchar(40)   NOT NULL,
    atualizado_em      varchar(40)   NOT NULL,
    CONSTRAINT fk_acervo_cobrancas_caso FOREIGN KEY (caso_id)
        REFERENCES {SCHEMA}.{PREFIXO}casos (id) ON DELETE CASCADE
);

-- A conversa do agente geral. `caso_id` NÃO tem chave estrangeira de propósito: a
-- conversa é do Acervo, começa antes de haver caso e sobrevive ao caso apagado — a
-- transcrição continua sendo o registro do que foi perguntado e respondido. Quem lê
-- trata o caso sumido como estado ("esse caso não está mais no acervo"), e não como
-- linha órfã.
IF OBJECT_ID('{SCHEMA}.{PREFIXO}conversas') IS NULL
CREATE TABLE {SCHEMA}.{PREFIXO}conversas (
    id            varchar(64)   NOT NULL CONSTRAINT pk_acervo_conversas PRIMARY KEY,
    titulo        nvarchar(300) NOT NULL,
    resumo        nvarchar(300) NOT NULL CONSTRAINT df_acervo_conv_resumo DEFAULT N'',
    usuario       varchar(160)  NOT NULL CONSTRAINT df_acervo_conv_usuario DEFAULT '',
    caso_id       varchar(64)   NULL,
    conversa_ref  varchar(80)   NULL,
    criado_em     varchar(40)   NOT NULL,
    atualizado_em varchar(40)   NOT NULL
);

IF OBJECT_ID('{SCHEMA}.{PREFIXO}conversa_mensagens') IS NULL
CREATE TABLE {SCHEMA}.{PREFIXO}conversa_mensagens (
    id          varchar(64)   NOT NULL CONSTRAINT pk_acervo_conv_msg PRIMARY KEY,
    conversa_id varchar(64)   NOT NULL,
    papel       varchar(20)   NOT NULL,
    conteudo    nvarchar(max) NOT NULL CONSTRAINT df_acervo_msg_conteudo DEFAULT N'',
    natureza    varchar(30)   NOT NULL CONSTRAINT df_acervo_msg_natureza DEFAULT 'CASO',
    payload     nvarchar(max) NOT NULL CONSTRAINT df_acervo_msg_payload DEFAULT N'{{}}',
    criado_em   varchar(40)   NOT NULL,
    CONSTRAINT fk_acervo_msg_conversa FOREIGN KEY (conversa_id)
        REFERENCES {SCHEMA}.{PREFIXO}conversas (id) ON DELETE CASCADE
);

IF OBJECT_ID('{SCHEMA}.{PREFIXO}ufs') IS NULL
CREATE TABLE {SCHEMA}.{PREFIXO}ufs (
    id int NOT NULL CONSTRAINT pk_acervo_ufs PRIMARY KEY,
    sigla char(2) NOT NULL CONSTRAINT uq_acervo_ufs_sigla UNIQUE,
    nome nvarchar(80) NOT NULL,
    regiao_id int NULL,
    atualizado_em varchar(40) NOT NULL
);

IF OBJECT_ID('{SCHEMA}.{PREFIXO}municipios') IS NULL
CREATE TABLE {SCHEMA}.{PREFIXO}municipios (
    id int NOT NULL CONSTRAINT pk_acervo_municipios PRIMARY KEY,
    uf_id int NOT NULL,
    nome nvarchar(160) NOT NULL,
    atualizado_em varchar(40) NOT NULL,
    CONSTRAINT fk_acervo_municipios_uf FOREIGN KEY (uf_id)
        REFERENCES {SCHEMA}.{PREFIXO}ufs (id)
);

-- Os modelos .docx do escritorio: contrato, procuracao, hipossuficiencia.
--
-- POR QUE NO BANCO, E NAO SO EM `docs/`
--
-- O contrato de honorarios e o unico dos tres que NAO e versionado: traz tabela
-- de honorarios, CNPJ e as inscricoes na OAB, e por isso o `.gitignore` o mantem
-- fora do repositorio. A consequencia so aparecia em producao -- o arquivo nao
-- entra na imagem Docker, nenhum volume o repoe no conteiner, e gerar contrato
-- falhava com "modelo nao encontrado em docs/" num ambiente onde ninguem tem
-- shell para ir la coloca-lo.
--
-- Guardado aqui, o modelo acompanha o banco: sobe uma vez pela tela e vale para
-- todos os conteineres, inclusive os recriados no proximo deploy. O `docs/`
-- continua valendo como reserva, que e o que faz a maquina do advogado
-- funcionar sem precisar subir nada.
IF OBJECT_ID('{SCHEMA}.{PREFIXO}modelos_documento') IS NULL
CREATE TABLE {SCHEMA}.{PREFIXO}modelos_documento (
    codigo        varchar(40)    NOT NULL CONSTRAINT pk_acervo_modelos_doc PRIMARY KEY,
    nome_arquivo  nvarchar(400)  NOT NULL,
    conteudo      varbinary(max) NOT NULL,
    enviado_por   nvarchar(400)  NOT NULL CONSTRAINT df_acervo_mod_quem DEFAULT N'',
    criado_em     varchar(40)    NOT NULL,
    atualizado_em varchar(40)    NOT NULL
);

IF OBJECT_ID('{SCHEMA}.{PREFIXO}roteiros') IS NULL
CREATE TABLE {SCHEMA}.{PREFIXO}roteiros (
    codigo        varchar(80)   NOT NULL CONSTRAINT pk_acervo_roteiros PRIMARY KEY,
    nome          nvarchar(400) NOT NULL,
    descricao     nvarchar(max) NOT NULL CONSTRAINT df_acervo_rot_desc DEFAULT N'',
    corpo         nvarchar(max) NOT NULL,
    criado_por    nvarchar(400) NOT NULL CONSTRAINT df_acervo_rot_quem DEFAULT N'',
    origem        nvarchar(400) NOT NULL CONSTRAINT df_acervo_rot_origem DEFAULT N'',
    criado_em     varchar(40)   NOT NULL,
    atualizado_em varchar(40)   NOT NULL
);

-- `origem` (o arquivo de onde o roteiro foi importado) nasceu depois da tabela:
-- o banco de produção já tinha `acervo_roteiros` sem essa coluna, e o
-- `IF OBJECT_ID ... IS NULL` acima nunca roda para ela. Sem este acréscimo, uma
-- instalação antiga aceitaria o INSERT e perderia a procedência em silêncio.
IF COL_LENGTH('{SCHEMA}.{PREFIXO}roteiros', 'origem') IS NULL
ALTER TABLE {SCHEMA}.{PREFIXO}roteiros
    ADD origem nvarchar(400) NOT NULL CONSTRAINT df_acervo_rot_origem DEFAULT N'';
"""

# As constraints criadas antes da faxina mantêm o nome `pk_ocr_*` / `fk_ocr_*`. Renomear
# constraint exige `sp_rename` em cada uma e não muda comportamento nenhum — o custo do
# risco não compensa a estética. Tabela nova criada por este DDL nasce com o nome novo.
INDICES = (
    f"CREATE INDEX idx_acervo_entregas_caso ON {SCHEMA}.{PREFIXO}entregas (caso_id)",
    f"CREATE INDEX idx_acervo_entregas_item ON {SCHEMA}.{PREFIXO}entregas (caso_id, item_codigo)",
    f"CREATE INDEX idx_acervo_entrevistas_caso ON {SCHEMA}.{PREFIXO}entrevistas (caso_id)",
    # A rota do atendimento ao vivo procura por esta coluna a cada gravação de
    # transcrição, e ela roda duas vezes por atendimento.
    f"CREATE INDEX idx_acervo_entrevistas_gravacao ON {SCHEMA}.{PREFIXO}entrevistas (gravacao_id)",
    f"CREATE INDEX idx_acervo_assinaturas_caso ON {SCHEMA}.{PREFIXO}assinaturas (caso_id)",
    f"CREATE INDEX idx_acervo_municipios_uf_nome ON {SCHEMA}.{PREFIXO}municipios (uf_id, nome)",
    # O histórico é de quem perguntou, e abre ordenado pela conversa mais recente.
    f"CREATE INDEX idx_acervo_conversas_usuario ON {SCHEMA}.{PREFIXO}conversas"
    f" (usuario, atualizado_em DESC)",
    # Reabrir a conversa lê as mensagens dela na ordem em que foram ditas. `ordem` vem
    # antes de `criado_em` porque é ela que decide o empate — ver `COLUNAS_NOVAS`.
    f"CREATE INDEX idx_acervo_conv_msg_conversa ON {SCHEMA}.{PREFIXO}conversa_mensagens"
    f" (conversa_id, ordem, criado_em)",
)


#: Colunas acrescentadas a tabelas que JÁ EXISTEM no banco.
#:
#: O DDL acima só roda quando a tabela ainda não existe (`IF OBJECT_ID ... IS NULL`),
#: então acrescentar uma linha lá alcança apenas instalação nova. Um banco já em uso
#: continuaria sem a coluna, e a consulta que a lê quebraria em produção enquanto
#: passa nos testes — que rodam contra banco recém-criado. Cada entrada é
#: `(tabela, coluna, tipo)` e vira um ALTER guardado por `IF COL_LENGTH(...) IS NULL`.
#:
#: Só coluna ANULÁVEL, ou com DEFAULT: preencher linha existente é migração de dado, e
#: migração de dado não cabe num passo de partida que roda a cada subida do servidor.
COLUNAS_NOVAS = (
    # O banco é a cópia durável do anexo. O caminho local é só cache: caminhos
    # absolutos quebram quando o projeto muda de pasta ou outro servidor atende.
    (f"{PREFIXO}entregas", "conteudo", "varbinary(max) NULL"),
    (f"{PREFIXO}entregas", "conteudo_sha256", "char(64) NULL"),
    # A avaliação no Google Meu Negócio é etapa do roteiro (ver `FECHAMENTO` em
    # `app/roteiros.py`) e era marcada só na tela do atendente, em estado de React que
    # morria no refresh. Sem gravar, a supervisão não tinha como conferir se a etapa
    # aconteceu — que é justamente o que o checklist do roteiro pergunta.
    (f"{PREFIXO}entrevistas", "avaliacao_google_em", "varchar(40) NULL"),
    # O id da gravação do atendimento ao vivo (o serviço de transcrição, na 8200).
    # É por ele que a entrevista gravada ao vivo se reconhece entre duas chamadas
    # da mesma rota — sem uma chave estável, criar o caso e depois encerrar o
    # atendimento gravaria a MESMA entrevista duas vezes, e a supervisão passaria a
    # contar o dobro do trabalho de quem a conduziu.
    (f"{PREFIXO}entrevistas", "gravacao_id", "varchar(64) NULL"),
    # A ordem da mensagem dentro da conversa. `criado_em` tem precisão de SEGUNDOS, e
    # pergunta e resposta caem no mesmo segundo com facilidade — quando isso acontecia,
    # o desempate ia para o `id` (um UUID) e a conversa reabria com a resposta ANTES da
    # pergunta. Nasce com `0` nas mensagens que já existem, e aí o desempate volta a ser
    # `criado_em`: o mesmo comportamento de antes para o que já está gravado, sem
    # migração de dado num passo que roda a cada subida.
    (
        f"{PREFIXO}conversa_mensagens",
        "ordem",
        "int NOT NULL CONSTRAINT df_acervo_msg_ordem DEFAULT 0",
    ),
    # Documento sem campo cadastral — CAT, laudo, contracheque, procuração — não tem
    # `dados_utilizaveis`: o extrator só conhece documento de identidade. Sem este
    # sinal, o item ficava para sempre "a conferir" com o arquivo certo e legível na
    # mão, e o cliente lia "precisa reenviar" (ver `casos._status_do_item`).
    (f"{PREFIXO}entregas", "texto_utilizavel", "int NULL"),
    # Envio em massa: agrupa as entregas de um mesmo `POST .../documentos/lote`.
    (f"{PREFIXO}entregas", "lote_id", "varchar(64) NULL"),
    # Quem decidiu a que item do checklist o arquivo pertence, com que confiança e
    # por quê. Sem isso, uma atribuição automática errada fica indistinguível de uma
    # escolha do cliente na hora de auditar por que a petição levou o documento errado.
    (f"{PREFIXO}entregas", "roteamento_origem", "varchar(20) NULL"),
    (f"{PREFIXO}entregas", "roteamento_confianca", "int NULL"),
    (f"{PREFIXO}entregas", "roteamento_motivo", "nvarchar(600) NULL"),
    # Referência do caso no agente jurídico — antes ficava numa tabela separada que
    # apontava para casos que já não existiam do outro lado.
    (f"{PREFIXO}casos", "case_ref", "varchar(80) NULL"),
    (f"{PREFIXO}casos", "cliente_ref", "varchar(80) NULL"),
    (f"{PREFIXO}casos", "agente_ultimo_erro", "nvarchar(max) NULL"),
    # Chave idempotente do envio ao agente (entrega_id:hash da extração).
    (f"{PREFIXO}entregas", "agente_envio_chave", "varchar(120) NULL"),
    # O WhatsApp do cliente, colhido na entrevista e guardado NO CASO.
    #
    # Ele já era pedido no roteiro (`telefone`, obrigatória), mas as respostas
    # não são gravadas: viviam na tela e iam embora com ela. O único lugar onde
    # o número sobrevivia era o signatário da assinatura — o que só existe
    # depois de o contrato ir para a ZapSign. Antes disso, a cobrança
    # automática de documentos abria com o campo em branco e pedia de novo um
    # número que o cliente já tinha ditado (ver `automacoes_whatsapp`).
    (
        f"{PREFIXO}casos",
        "telefone",
        "varchar(30) NOT NULL CONSTRAINT df_ocr_casos_tel DEFAULT ''",
    ),
)


def inicializar_schema() -> None:
    """Cria as tabelas do Acervo, se ainda não existirem. Idempotente."""
    bruta = pyodbc.connect(dsn(), timeout=30, autocommit=True)
    try:
        cursor = bruta.cursor()
        for lote in ESQUEMA_SQLSERVER.split(";\n"):
            if lote.strip():
                cursor.execute(lote)
        for tabela, coluna, tipo in COLUNAS_NOVAS:
            cursor.execute(
                f"IF COL_LENGTH('{SCHEMA}.{tabela}', '{coluna}') IS NULL "
                f"ALTER TABLE {SCHEMA}.{tabela} ADD {coluna} {tipo}"
            )
        for indice in INDICES:
            nome = indice.split()[2]
            cursor.execute(
                f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = '{nome}') {indice}"
            )
        cursor.execute(
            f"IF OBJECT_ID('{SCHEMA}.{PREFIXO}vinculos_agente') IS NOT NULL "
            f"DROP TABLE {SCHEMA}.{PREFIXO}vinculos_agente"
        )
    finally:
        bruta.close()
