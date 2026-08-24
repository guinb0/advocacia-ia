CREATE TABLE IF NOT EXISTS jobs (
    id uuid PRIMARY KEY,
    celery_task_id varchar(255),
    caso_id varchar(64),
    tipo varchar(50) NOT NULL,
    status varchar(30) NOT NULL,
    progresso integer NOT NULL DEFAULT 0 CHECK (progresso BETWEEN 0 AND 100),
    erro text,
    resultado jsonb,
    arquivo_temporario text,
    criado_em timestamptz NOT NULL DEFAULT now(),
    iniciado_em timestamptz,
    finalizado_em timestamptz,
    atualizado_em timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_jobs_status_criado ON jobs(status, criado_em);
