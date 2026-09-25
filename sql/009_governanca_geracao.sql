-- Governança aditiva da geração jurídica. Executar no PostgreSQL do RAG.
-- Não altera nem apaga fontes/chunks já existentes.

ALTER TABLE fontes ADD COLUMN IF NOT EXISTS organization_id text NOT NULL DEFAULT '';
ALTER TABLE fontes ADD COLUMN IF NOT EXISTS hash_conteudo char(64);
ALTER TABLE fontes ADD COLUMN IF NOT EXISTS status_verificacao text NOT NULL DEFAULT 'UNVERIFIED'
    CHECK (status_verificacao IN ('VERIFIED', 'UNVERIFIED', 'REVOKED'));
ALTER TABLE fontes ADD COLUMN IF NOT EXISTS consultado_em timestamptz;
CREATE UNIQUE INDEX IF NOT EXISTS ux_fontes_organizacao_hash
    ON fontes (organization_id, hash_conteudo) WHERE hash_conteudo IS NOT NULL;

CREATE TABLE IF NOT EXISTS precedentes_verificados (
    id bigserial PRIMARY KEY,
    organization_id text NOT NULL DEFAULT '',
    fonte_id bigint NOT NULL REFERENCES fontes(id) ON DELETE CASCADE,
    tribunal text NOT NULL DEFAULT '', orgao_julgador text NOT NULL DEFAULT '',
    numero_processo text NOT NULL DEFAULT '', numero_acordao text NOT NULL DEFAULT '',
    tema text NOT NULL DEFAULT '', subtema text NOT NULL DEFAULT '', relator text NOT NULL DEFAULT '',
    julgado_em date, publicado_em date, ementa text NOT NULL DEFAULT '', trecho_relevante text NOT NULL DEFAULT '',
    contexto_fatico text NOT NULL DEFAULT '', tese_aplicada text NOT NULL DEFAULT '', resultado text NOT NULL DEFAULT '',
    valor_pedido numeric(14,2), valor_deferido numeric(14,2), fonte_url text NOT NULL DEFAULT '',
    consultado_em timestamptz NOT NULL DEFAULT now(), status_verificacao text NOT NULL
      CHECK (status_verificacao IN ('VERIFIED', 'UNVERIFIED', 'REVOKED')),
    hash_conteudo char(64) NOT NULL,
    UNIQUE (organization_id, hash_conteudo)
);
CREATE INDEX IF NOT EXISTS ix_precedentes_verificados_busca
    ON precedentes_verificados (organization_id, status_verificacao, tribunal, tema, publicado_em DESC);

CREATE TABLE IF NOT EXISTS geracao_proveniencia (
    id bigserial PRIMARY KEY,
    organization_id text NOT NULL DEFAULT '', generation_id text NOT NULL, caso_id text NOT NULL,
    tipo text NOT NULL CHECK (tipo IN ('DOCUMENTO','EVIDENCIA','FATO','TESE','PEDIDO','PRECEDENTE','PECA','SKILL','REGRA')),
    origem_id text NOT NULL, destino_tipo text NOT NULL DEFAULT '', destino_id text NOT NULL DEFAULT '',
    papel text NOT NULL DEFAULT '', confianca numeric(5,4), metadados jsonb NOT NULL DEFAULT '{}'::jsonb,
    criado_em timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, generation_id, tipo, origem_id, destino_tipo, destino_id, papel)
);
CREATE INDEX IF NOT EXISTS ix_geracao_proveniencia_caso ON geracao_proveniencia (organization_id, caso_id, generation_id);

CREATE TABLE IF NOT EXISTS modelos_aprovados (
    id bigserial PRIMARY KEY, organization_id text NOT NULL DEFAULT '', peca_origem_id bigint,
    tipo_peca text NOT NULL, area text NOT NULL DEFAULT '', taxonomia text NOT NULL DEFAULT '', subtipo text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','ARCHIVED')),
    aprovado_por text NOT NULL DEFAULT '', versao integer NOT NULL DEFAULT 1, metadados jsonb NOT NULL DEFAULT '{}'::jsonb,
    criado_em timestamptz NOT NULL DEFAULT now(), atualizado_em timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_modelos_aprovados_contexto ON modelos_aprovados (organization_id, status, tipo_peca, taxonomia, subtipo);

CREATE TABLE IF NOT EXISTS resultados_processuais_escritorio (
    id bigserial PRIMARY KEY, organization_id text NOT NULL DEFAULT '', caso_id text NOT NULL DEFAULT '',
    numero_processo text NOT NULL DEFAULT '', taxonomia text NOT NULL DEFAULT '', vara text NOT NULL DEFAULT '', tribunal text NOT NULL DEFAULT '',
    juiz text NOT NULL DEFAULT '', relator text NOT NULL DEFAULT '', pedidos jsonb NOT NULL DEFAULT '[]'::jsonb,
    valor_causa numeric(14,2), resultado text NOT NULL DEFAULT '', valores_deferidos jsonb NOT NULL DEFAULT '[]'::jsonb,
    acordo boolean, sentenca_url text NOT NULL DEFAULT '', acordao_url text NOT NULL DEFAULT '', duracao_dias integer,
    recursos jsonb NOT NULL DEFAULT '[]'::jsonb, versao_peticao integer, criado_em timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_resultados_escritorio_contexto
    ON resultados_processuais_escritorio (organization_id, taxonomia, vara, tribunal);
