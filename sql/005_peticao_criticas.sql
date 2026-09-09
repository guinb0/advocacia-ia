-- Críticas/prompts de revisão de petição, com retroalimentação automática por
-- categoria. Aplicado também de forma idempotente por
-- `app/peticao_criticas.py:inicializar()`; este arquivo é o registro do que
-- existe no banco, mesmo padrão de 002_jobs.sql / 004_peticao_skills.sql.

CREATE TABLE IF NOT EXISTS peticao_criticas (
    id               uuid PRIMARY KEY,
    caso_id          varchar(64) NOT NULL,
    categoria        varchar(80) NOT NULL,
    versao_origem    integer NOT NULL,
    versao_resultado integer NOT NULL,
    prompt           text NOT NULL,
    usuario          varchar(200) NOT NULL DEFAULT '',
    criado_em        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_peticao_criticas_caso ON peticao_criticas (caso_id, criado_em);
CREATE INDEX IF NOT EXISTS ix_peticao_criticas_categoria ON peticao_criticas (categoria, criado_em);
