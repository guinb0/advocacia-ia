-- Skill/prompt configurável por categoria de petição.
-- Aplicado também de forma idempotente por `app/peticao_skills.py:inicializar()`;
-- este arquivo é o registro do que existe no banco, mesmo padrão de 002_jobs.sql.

CREATE TABLE IF NOT EXISTS peticao_skills (
    categoria      varchar(80) PRIMARY KEY,
    instrucoes     text NOT NULL DEFAULT '',
    atualizado_por varchar(200) NOT NULL DEFAULT '',
    criado_em      timestamptz NOT NULL DEFAULT now(),
    atualizado_em  timestamptz NOT NULL DEFAULT now()
);
