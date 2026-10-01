-- Fluxo de atendimento v2: agenda, presença, alertas, modelos de WhatsApp,
-- critérios dos tipos de caso, análise pós-entrevista.
-- Executar no SQL Server do app (schema dbo).
--
-- ADITIVA E IDEMPOTENTE: só cria o que não existe (IF OBJECT_ID / COL_LENGTH).
-- Nenhuma coluna existente muda, nenhum dado é apagado. O app também cria tudo
-- isto no startup; aplicar antes só adianta o trabalho.
-- Gerado por scripts/gerar_sql_fluxo_v2.py — edite as definições em Python, não aqui.


-- dbo.acervo_atendimentos
IF OBJECT_ID('dbo.acervo_atendimentos') IS NULL CREATE TABLE dbo.acervo_atendimentos (
    id varchar(64) NOT NULL,
    cliente nvarchar(200) NOT NULL CONSTRAINT df_acervo_atendimentos_cliente DEFAULT '',
    telefone varchar(30) NOT NULL CONSTRAINT df_acervo_atendimentos_telefone DEFAULT '',
    data_hora varchar(40) NULL,
    duracao_min int NOT NULL CONSTRAINT df_acervo_atendimentos_duracao_min DEFAULT 60,
    sala varchar(120) NULL,
    link_cliente nvarchar(1000) NULL,
    responsavel_id varchar(64) NULL,
    responsavel_nome nvarchar(200) NULL,
    atendente_id varchar(64) NULL,
    atendente_nome nvarchar(200) NULL,
    entrevista_id varchar(64) NULL,
    casos_json nvarchar(max) NULL,
    acoes_json nvarchar(max) NULL,
    documentos_json nvarchar(max) NULL,
    estado varchar(60) NOT NULL CONSTRAINT df_acervo_atendimentos_estado DEFAULT 'AGENDADA',
    origem varchar(60) NOT NULL CONSTRAINT df_acervo_atendimentos_origem DEFAULT 'agenda',
    revisada int NOT NULL CONSTRAINT df_acervo_atendimentos_revisada DEFAULT 0,
    config_lembretes_json nvarchar(max) NULL,
    observacao nvarchar(1000) NULL,
    cliente_entrou_em varchar(40) NULL,
    cliente_batida_em varchar(40) NULL,
    cliente_saiu_em varchar(40) NULL,
    escritorio_batida_em varchar(40) NULL,
    versao int NOT NULL CONSTRAINT df_acervo_atendimentos_versao DEFAULT 1,
    criado_em varchar(40) NOT NULL,
    criado_por nvarchar(200) NULL,
    atualizado_em varchar(40) NOT NULL,
    finalizado_em varchar(40) NULL,
    CONSTRAINT pk_acervo_atendimentos PRIMARY KEY (id)
)
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'cliente') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD cliente nvarchar(200) NOT NULL CONSTRAINT df_acervo_atendimentos_cliente DEFAULT ''
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'telefone') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD telefone varchar(30) NOT NULL CONSTRAINT df_acervo_atendimentos_telefone DEFAULT ''
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'data_hora') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD data_hora varchar(40) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'duracao_min') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD duracao_min int NOT NULL CONSTRAINT df_acervo_atendimentos_duracao_min DEFAULT 60
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'sala') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD sala varchar(120) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'link_cliente') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD link_cliente nvarchar(1000) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'responsavel_id') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD responsavel_id varchar(64) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'responsavel_nome') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD responsavel_nome nvarchar(200) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'atendente_id') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD atendente_id varchar(64) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'atendente_nome') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD atendente_nome nvarchar(200) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'entrevista_id') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD entrevista_id varchar(64) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'casos_json') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD casos_json nvarchar(max) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'acoes_json') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD acoes_json nvarchar(max) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'documentos_json') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD documentos_json nvarchar(max) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'estado') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD estado varchar(60) NOT NULL CONSTRAINT df_acervo_atendimentos_estado DEFAULT 'AGENDADA'
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'origem') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD origem varchar(60) NOT NULL CONSTRAINT df_acervo_atendimentos_origem DEFAULT 'agenda'
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'revisada') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD revisada int NOT NULL CONSTRAINT df_acervo_atendimentos_revisada DEFAULT 0
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'config_lembretes_json') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD config_lembretes_json nvarchar(max) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'observacao') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD observacao nvarchar(1000) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'cliente_entrou_em') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD cliente_entrou_em varchar(40) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'cliente_batida_em') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD cliente_batida_em varchar(40) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'cliente_saiu_em') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD cliente_saiu_em varchar(40) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'escritorio_batida_em') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD escritorio_batida_em varchar(40) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'versao') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD versao int NOT NULL CONSTRAINT df_acervo_atendimentos_versao DEFAULT 1
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'criado_por') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD criado_por nvarchar(200) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimentos', 'finalizado_em') IS NULL ALTER TABLE dbo.acervo_atendimentos ADD finalizado_em varchar(40) NULL
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_acervo_atendimentos_sala') CREATE INDEX ix_acervo_atendimentos_sala ON dbo.acervo_atendimentos (sala)
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_acervo_atendimentos_estado') CREATE INDEX ix_acervo_atendimentos_estado ON dbo.acervo_atendimentos (estado, data_hora)
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_acervo_atendimentos_entrevista') CREATE INDEX ix_acervo_atendimentos_entrevista ON dbo.acervo_atendimentos (entrevista_id)
GO

-- dbo.acervo_atendimento_eventos
IF OBJECT_ID('dbo.acervo_atendimento_eventos') IS NULL CREATE TABLE dbo.acervo_atendimento_eventos (
    id varchar(64) NOT NULL,
    atendimento_id varchar(64) NOT NULL,
    tipo varchar(60) NOT NULL,
    de_estado varchar(60) NULL,
    para_estado varchar(60) NULL,
    usuario_id varchar(64) NULL,
    usuario_nome nvarchar(200) NULL,
    detalhes nvarchar(1000) NULL,
    criado_em varchar(40) NOT NULL,
    CONSTRAINT pk_acervo_atendimento_eventos PRIMARY KEY (id)
)
GO
IF COL_LENGTH('dbo.acervo_atendimento_eventos', 'de_estado') IS NULL ALTER TABLE dbo.acervo_atendimento_eventos ADD de_estado varchar(60) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimento_eventos', 'para_estado') IS NULL ALTER TABLE dbo.acervo_atendimento_eventos ADD para_estado varchar(60) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimento_eventos', 'usuario_id') IS NULL ALTER TABLE dbo.acervo_atendimento_eventos ADD usuario_id varchar(64) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimento_eventos', 'usuario_nome') IS NULL ALTER TABLE dbo.acervo_atendimento_eventos ADD usuario_nome nvarchar(200) NULL
GO
IF COL_LENGTH('dbo.acervo_atendimento_eventos', 'detalhes') IS NULL ALTER TABLE dbo.acervo_atendimento_eventos ADD detalhes nvarchar(1000) NULL
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_acervo_atend_eventos_atend') CREATE INDEX ix_acervo_atend_eventos_atend ON dbo.acervo_atendimento_eventos (atendimento_id, criado_em)
GO

-- dbo.acervo_config_atendimento
IF OBJECT_ID('dbo.acervo_config_atendimento') IS NULL CREATE TABLE dbo.acervo_config_atendimento (
    chave varchar(60) NOT NULL,
    valor_json nvarchar(max) NOT NULL,
    atualizado_em varchar(40) NOT NULL,
    atualizado_por nvarchar(200) NULL,
    CONSTRAINT pk_acervo_config_atendimento PRIMARY KEY (chave)
)
GO
IF COL_LENGTH('dbo.acervo_config_atendimento', 'atualizado_por') IS NULL ALTER TABLE dbo.acervo_config_atendimento ADD atualizado_por nvarchar(200) NULL
GO

-- dbo.acervo_alertas
IF OBJECT_ID('dbo.acervo_alertas') IS NULL CREATE TABLE dbo.acervo_alertas (
    id varchar(64) NOT NULL,
    chave varchar(220) NOT NULL,
    tipo varchar(60) NOT NULL,
    atendimento_id varchar(64) NOT NULL,
    destinatario_id varchar(64) NULL,
    modulo varchar(60) NULL,
    titulo nvarchar(200) NOT NULL,
    texto nvarchar(1000) NULL,
    acao varchar(60) NULL,
    dados_json nvarchar(max) NULL,
    criado_em varchar(40) NOT NULL,
    expira_em varchar(40) NULL,
    resolvido_em varchar(40) NULL,
    motivo_resolucao varchar(60) NULL,
    CONSTRAINT pk_acervo_alertas PRIMARY KEY (id)
)
GO
IF COL_LENGTH('dbo.acervo_alertas', 'destinatario_id') IS NULL ALTER TABLE dbo.acervo_alertas ADD destinatario_id varchar(64) NULL
GO
IF COL_LENGTH('dbo.acervo_alertas', 'modulo') IS NULL ALTER TABLE dbo.acervo_alertas ADD modulo varchar(60) NULL
GO
IF COL_LENGTH('dbo.acervo_alertas', 'texto') IS NULL ALTER TABLE dbo.acervo_alertas ADD texto nvarchar(1000) NULL
GO
IF COL_LENGTH('dbo.acervo_alertas', 'acao') IS NULL ALTER TABLE dbo.acervo_alertas ADD acao varchar(60) NULL
GO
IF COL_LENGTH('dbo.acervo_alertas', 'dados_json') IS NULL ALTER TABLE dbo.acervo_alertas ADD dados_json nvarchar(max) NULL
GO
IF COL_LENGTH('dbo.acervo_alertas', 'expira_em') IS NULL ALTER TABLE dbo.acervo_alertas ADD expira_em varchar(40) NULL
GO
IF COL_LENGTH('dbo.acervo_alertas', 'resolvido_em') IS NULL ALTER TABLE dbo.acervo_alertas ADD resolvido_em varchar(40) NULL
GO
IF COL_LENGTH('dbo.acervo_alertas', 'motivo_resolucao') IS NULL ALTER TABLE dbo.acervo_alertas ADD motivo_resolucao varchar(60) NULL
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ux_acervo_alertas_chave') CREATE UNIQUE INDEX ux_acervo_alertas_chave ON dbo.acervo_alertas (chave)
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_acervo_alertas_ativos') CREATE INDEX ix_acervo_alertas_ativos ON dbo.acervo_alertas (resolvido_em, atendimento_id)
GO

-- dbo.acervo_whatsapp_modelos
IF OBJECT_ID('dbo.acervo_whatsapp_modelos') IS NULL CREATE TABLE dbo.acervo_whatsapp_modelos (
    codigo varchar(60) NOT NULL,
    nome nvarchar(200) NOT NULL CONSTRAINT df_acervo_whatsapp_modelos_nome DEFAULT '',
    descricao nvarchar(1000) NULL,
    texto nvarchar(max) NOT NULL,
    ativo int NOT NULL CONSTRAINT df_acervo_whatsapp_modelos_ativo DEFAULT 1,
    sistema int NOT NULL CONSTRAINT df_acervo_whatsapp_modelos_sistema DEFAULT 1,
    versao int NOT NULL CONSTRAINT df_acervo_whatsapp_modelos_versao DEFAULT 1,
    atualizado_em varchar(40) NOT NULL,
    atualizado_por nvarchar(200) NULL,
    CONSTRAINT pk_acervo_whatsapp_modelos PRIMARY KEY (codigo)
)
GO
IF COL_LENGTH('dbo.acervo_whatsapp_modelos', 'nome') IS NULL ALTER TABLE dbo.acervo_whatsapp_modelos ADD nome nvarchar(200) NOT NULL CONSTRAINT df_acervo_whatsapp_modelos_nome DEFAULT ''
GO
IF COL_LENGTH('dbo.acervo_whatsapp_modelos', 'descricao') IS NULL ALTER TABLE dbo.acervo_whatsapp_modelos ADD descricao nvarchar(1000) NULL
GO
IF COL_LENGTH('dbo.acervo_whatsapp_modelos', 'ativo') IS NULL ALTER TABLE dbo.acervo_whatsapp_modelos ADD ativo int NOT NULL CONSTRAINT df_acervo_whatsapp_modelos_ativo DEFAULT 1
GO
IF COL_LENGTH('dbo.acervo_whatsapp_modelos', 'sistema') IS NULL ALTER TABLE dbo.acervo_whatsapp_modelos ADD sistema int NOT NULL CONSTRAINT df_acervo_whatsapp_modelos_sistema DEFAULT 1
GO
IF COL_LENGTH('dbo.acervo_whatsapp_modelos', 'versao') IS NULL ALTER TABLE dbo.acervo_whatsapp_modelos ADD versao int NOT NULL CONSTRAINT df_acervo_whatsapp_modelos_versao DEFAULT 1
GO
IF COL_LENGTH('dbo.acervo_whatsapp_modelos', 'atualizado_por') IS NULL ALTER TABLE dbo.acervo_whatsapp_modelos ADD atualizado_por nvarchar(200) NULL
GO

-- dbo.acervo_tipos_caso_criterios
IF OBJECT_ID('dbo.acervo_tipos_caso_criterios') IS NULL CREATE TABLE dbo.acervo_tipos_caso_criterios (
    id varchar(64) NOT NULL,
    tipo_codigo varchar(60) NOT NULL,
    ordem int NOT NULL CONSTRAINT df_acervo_tipos_caso_criterios_ordem DEFAULT 0,
    texto nvarchar(1000) NOT NULL,
    ativo int NOT NULL CONSTRAINT df_acervo_tipos_caso_criterios_ativo DEFAULT 1,
    criado_em varchar(40) NOT NULL,
    atualizado_em varchar(40) NOT NULL,
    atualizado_por nvarchar(200) NULL,
    CONSTRAINT pk_acervo_tipos_caso_criterios PRIMARY KEY (id)
)
GO
IF COL_LENGTH('dbo.acervo_tipos_caso_criterios', 'ordem') IS NULL ALTER TABLE dbo.acervo_tipos_caso_criterios ADD ordem int NOT NULL CONSTRAINT df_acervo_tipos_caso_criterios_ordem DEFAULT 0
GO
IF COL_LENGTH('dbo.acervo_tipos_caso_criterios', 'ativo') IS NULL ALTER TABLE dbo.acervo_tipos_caso_criterios ADD ativo int NOT NULL CONSTRAINT df_acervo_tipos_caso_criterios_ativo DEFAULT 1
GO
IF COL_LENGTH('dbo.acervo_tipos_caso_criterios', 'atualizado_por') IS NULL ALTER TABLE dbo.acervo_tipos_caso_criterios ADD atualizado_por nvarchar(200) NULL
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_acervo_tc_criterios_tipo') CREATE INDEX ix_acervo_tc_criterios_tipo ON dbo.acervo_tipos_caso_criterios (tipo_codigo, ordem)
GO

-- dbo.acervo_tipos_caso_ia
IF OBJECT_ID('dbo.acervo_tipos_caso_ia') IS NULL CREATE TABLE dbo.acervo_tipos_caso_ia (
    tipo_codigo varchar(60) NOT NULL,
    origem varchar(60) NOT NULL CONSTRAINT df_acervo_tipos_caso_ia_origem DEFAULT 'ia',
    requer_revisao int NOT NULL CONSTRAINT df_acervo_tipos_caso_ia_requer_revisao DEFAULT 1,
    informacoes_necessarias_json nvarchar(max) NULL,
    fundamentos_json nvarchar(max) NULL,
    atendimento_id varchar(64) NULL,
    gerado_em varchar(40) NOT NULL,
    gerado_por nvarchar(200) NULL,
    aprovado_em varchar(40) NULL,
    aprovado_por nvarchar(200) NULL,
    CONSTRAINT pk_acervo_tipos_caso_ia PRIMARY KEY (tipo_codigo)
)
GO
IF COL_LENGTH('dbo.acervo_tipos_caso_ia', 'origem') IS NULL ALTER TABLE dbo.acervo_tipos_caso_ia ADD origem varchar(60) NOT NULL CONSTRAINT df_acervo_tipos_caso_ia_origem DEFAULT 'ia'
GO
IF COL_LENGTH('dbo.acervo_tipos_caso_ia', 'requer_revisao') IS NULL ALTER TABLE dbo.acervo_tipos_caso_ia ADD requer_revisao int NOT NULL CONSTRAINT df_acervo_tipos_caso_ia_requer_revisao DEFAULT 1
GO
IF COL_LENGTH('dbo.acervo_tipos_caso_ia', 'informacoes_necessarias_json') IS NULL ALTER TABLE dbo.acervo_tipos_caso_ia ADD informacoes_necessarias_json nvarchar(max) NULL
GO
IF COL_LENGTH('dbo.acervo_tipos_caso_ia', 'fundamentos_json') IS NULL ALTER TABLE dbo.acervo_tipos_caso_ia ADD fundamentos_json nvarchar(max) NULL
GO
IF COL_LENGTH('dbo.acervo_tipos_caso_ia', 'atendimento_id') IS NULL ALTER TABLE dbo.acervo_tipos_caso_ia ADD atendimento_id varchar(64) NULL
GO
IF COL_LENGTH('dbo.acervo_tipos_caso_ia', 'gerado_por') IS NULL ALTER TABLE dbo.acervo_tipos_caso_ia ADD gerado_por nvarchar(200) NULL
GO
IF COL_LENGTH('dbo.acervo_tipos_caso_ia', 'aprovado_em') IS NULL ALTER TABLE dbo.acervo_tipos_caso_ia ADD aprovado_em varchar(40) NULL
GO
IF COL_LENGTH('dbo.acervo_tipos_caso_ia', 'aprovado_por') IS NULL ALTER TABLE dbo.acervo_tipos_caso_ia ADD aprovado_por nvarchar(200) NULL
GO

-- dbo.acervo_analises_atendimento
IF OBJECT_ID('dbo.acervo_analises_atendimento') IS NULL CREATE TABLE dbo.acervo_analises_atendimento (
    id varchar(64) NOT NULL,
    atendimento_id varchar(64) NOT NULL,
    status varchar(60) NOT NULL CONSTRAINT df_acervo_analises_atendimento_status DEFAULT 'pendente',
    assinatura varchar(64) NOT NULL,
    entrada_json nvarchar(max) NULL,
    resultado_json nvarchar(max) NULL,
    erro nvarchar(1000) NULL,
    criado_em varchar(40) NOT NULL,
    atualizado_em varchar(40) NOT NULL,
    criado_por nvarchar(200) NULL,
    CONSTRAINT pk_acervo_analises_atendimento PRIMARY KEY (id)
)
GO
IF COL_LENGTH('dbo.acervo_analises_atendimento', 'status') IS NULL ALTER TABLE dbo.acervo_analises_atendimento ADD status varchar(60) NOT NULL CONSTRAINT df_acervo_analises_atendimento_status DEFAULT 'pendente'
GO
IF COL_LENGTH('dbo.acervo_analises_atendimento', 'entrada_json') IS NULL ALTER TABLE dbo.acervo_analises_atendimento ADD entrada_json nvarchar(max) NULL
GO
IF COL_LENGTH('dbo.acervo_analises_atendimento', 'resultado_json') IS NULL ALTER TABLE dbo.acervo_analises_atendimento ADD resultado_json nvarchar(max) NULL
GO
IF COL_LENGTH('dbo.acervo_analises_atendimento', 'erro') IS NULL ALTER TABLE dbo.acervo_analises_atendimento ADD erro nvarchar(1000) NULL
GO
IF COL_LENGTH('dbo.acervo_analises_atendimento', 'criado_por') IS NULL ALTER TABLE dbo.acervo_analises_atendimento ADD criado_por nvarchar(200) NULL
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_acervo_analises_atend') CREATE INDEX ix_acervo_analises_atend ON dbo.acervo_analises_atendimento (atendimento_id, criado_em)
GO

-- dbo.acervo_automacoes_whatsapp: ciclo de entrega
IF COL_LENGTH('dbo.acervo_automacoes_whatsapp', 'status_entrega') IS NULL ALTER TABLE dbo.acervo_automacoes_whatsapp ADD status_entrega varchar(30) NULL
GO
IF COL_LENGTH('dbo.acervo_automacoes_whatsapp', 'mensagem_id') IS NULL ALTER TABLE dbo.acervo_automacoes_whatsapp ADD mensagem_id varchar(120) NULL
GO
IF COL_LENGTH('dbo.acervo_automacoes_whatsapp', 'atendimento_id') IS NULL ALTER TABLE dbo.acervo_automacoes_whatsapp ADD atendimento_id varchar(64) NULL
GO
IF COL_LENGTH('dbo.acervo_automacoes_whatsapp', 'texto_resumo') IS NULL ALTER TABLE dbo.acervo_automacoes_whatsapp ADD texto_resumo nvarchar(600) NULL
GO
IF COL_LENGTH('dbo.acervo_automacoes_whatsapp', 'entregue_em') IS NULL ALTER TABLE dbo.acervo_automacoes_whatsapp ADD entregue_em varchar(40) NULL
GO
IF COL_LENGTH('dbo.acervo_automacoes_whatsapp', 'lido_em') IS NULL ALTER TABLE dbo.acervo_automacoes_whatsapp ADD lido_em varchar(40) NULL
GO
