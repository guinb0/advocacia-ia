-- Acervo semântico de peças do escritório.
-- Não guarda estilo visual; cada registro é texto jurídico extraído e auditável.
CREATE TABLE IF NOT EXISTS pecas_conteudo (
    id BIGSERIAL PRIMARY KEY,
    origem_id TEXT NOT NULL UNIQUE,
    nome_arquivo TEXT NOT NULL,
    tipo_peca TEXT NOT NULL DEFAULT 'PETICAO_INICIAL',
    categoria TEXT NOT NULL DEFAULT '',
    texto_integral TEXT NOT NULL,
    hash_conteudo CHAR(64) NOT NULL,
    metadados JSONB NOT NULL DEFAULT '{}'::jsonb,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pecas_conteudo_chunks (
    id BIGSERIAL PRIMARY KEY,
    peca_id BIGINT NOT NULL REFERENCES pecas_conteudo(id) ON DELETE CASCADE,
    ordem INTEGER NOT NULL,
    texto TEXT NOT NULL,
    metadados JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(1536),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(peca_id, ordem)
);

CREATE INDEX IF NOT EXISTS ix_pecas_conteudo_categoria ON pecas_conteudo(tipo_peca, categoria);
CREATE INDEX IF NOT EXISTS ix_pecas_conteudo_chunks_embedding
    ON pecas_conteudo_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
