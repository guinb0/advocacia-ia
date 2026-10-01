-- Base jurídica verificada (camada B da geração). Aditiva: não altera tabelas existentes.
-- Executar no PostgreSQL do RAG. Alimentada só a partir de fonte oficial (Planalto, STF, TST, TRT),
-- com data de verificação; skill e peças do acervo NUNCA entram aqui.
CREATE TABLE IF NOT EXISTS autoridades_juridicas (
    id text PRIMARY KEY,
    organization_id text NOT NULL DEFAULT '',
    tipo text NOT NULL CHECK (tipo IN ('artigo','lei','sumula','sumula_vinculante','oj','tema','controle_concentrado','precedente')),
    chave text NOT NULL DEFAULT '',
    titulo text NOT NULL DEFAULT '', texto text NOT NULL DEFAULT '',
    norma text NOT NULL DEFAULT '', artigo text NOT NULL DEFAULT '', paragrafo text NOT NULL DEFAULT '',
    inciso text NOT NULL DEFAULT '', alinea text NOT NULL DEFAULT '',
    tribunal text NOT NULL DEFAULT '', orgao text NOT NULL DEFAULT '', classe text NOT NULL DEFAULT '',
    numero text NOT NULL DEFAULT '', tema text NOT NULL DEFAULT '', assunto text NOT NULL DEFAULT '', tese text NOT NULL DEFAULT '',
    data date, vigencia_inicio date, vigencia_fim date, versao text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'vigente' CHECK (status IN ('vigente','revogado','superado','cancelado','suspenso')),
    superado_por text NOT NULL DEFAULT '',
    vinculante boolean NOT NULL DEFAULT false, transito_em_julgado boolean,
    fonte_oficial text NOT NULL, url text NOT NULL DEFAULT '', verificado_em timestamptz NOT NULL,
    verificada boolean NOT NULL DEFAULT false,
    marcadores text[] NOT NULL DEFAULT '{}',
    criado_em timestamptz NOT NULL DEFAULT now(), atualizado_em timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_autoridades_chave ON autoridades_juridicas (organization_id, chave);
CREATE INDEX IF NOT EXISTS ix_autoridades_vigencia ON autoridades_juridicas (organization_id, tipo, status, vigencia_inicio, vigencia_fim);
