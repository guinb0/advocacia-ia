-- Acervo Jurídico: sincronização incremental, versionamento por dispositivo e painel administrativo.
-- Executar no PostgreSQL do RAG (banco advocacia_ia), DEPOIS de 006, 009 e 010.
--
-- ADITIVA E IDEMPOTENTE: só ADD COLUMN IF NOT EXISTS, CREATE TABLE/INDEX IF NOT EXISTS.
-- Nenhuma coluna existente muda de tipo, nenhum dado é apagado. Pode rodar mais de uma vez.
-- O app funciona sem ela: o painel mostra "migração não aplicada" e a sincronização recusa rodar.

BEGIN;

-- ------------------------------------------------------------ corpus_manifest (uma linha por norma)
ALTER TABLE corpus_manifest ADD COLUMN IF NOT EXISTS categoria text NOT NULL DEFAULT 'legislacao';
ALTER TABLE corpus_manifest ADD COLUMN IF NOT EXISTS tipo text NOT NULL DEFAULT 'lei';
ALTER TABLE corpus_manifest ADD COLUMN IF NOT EXISTS nome_amigavel text NOT NULL DEFAULT '';
ALTER TABLE corpus_manifest ADD COLUMN IF NOT EXISTS chave_norma text NOT NULL DEFAULT '';
ALTER TABLE corpus_manifest ADD COLUMN IF NOT EXISTS orgao text NOT NULL DEFAULT '';
ALTER TABLE corpus_manifest ADD COLUMN IF NOT EXISTS tribunal text NOT NULL DEFAULT '';
ALTER TABLE corpus_manifest ADD COLUMN IF NOT EXISTS content_hash text NOT NULL DEFAULT '';
ALTER TABLE corpus_manifest ADD COLUMN IF NOT EXISTS last_updated_at timestamptz;
ALTER TABLE corpus_manifest ADD COLUMN IF NOT EXISTS next_check_at timestamptz;
ALTER TABLE corpus_manifest ADD COLUMN IF NOT EXISTS source_last_modified_at timestamptz;
-- ATUALIZADO | PENDENTE | ERRO | EM_ANDAMENTO | REVOGADO
ALTER TABLE corpus_manifest ADD COLUMN IF NOT EXISTS sync_status text NOT NULL DEFAULT 'PENDENTE';
ALTER TABLE corpus_manifest ADD COLUMN IF NOT EXISTS ultimo_erro text NOT NULL DEFAULT '';
ALTER TABLE corpus_manifest ADD COLUMN IF NOT EXISTS encoding text NOT NULL DEFAULT '';

-- ------------------------------------------------- normative_device_versions (uma linha por versão de nó)
-- `dispositivo_id` é o caminho estável na árvore (art-482, art-482.par-1.inc-ii, adct.art-1).
-- Linhas antigas (identificador posicional "art-482-310") ficam com dispositivo_id NULL até a
-- primeira sincronização, que as associa quando o texto é o mesmo ou as encerra com valid_until.
ALTER TABLE normative_device_versions ADD COLUMN IF NOT EXISTS dispositivo_id text;
ALTER TABLE normative_device_versions ADD COLUMN IF NOT EXISTS tipo_no text NOT NULL DEFAULT 'artigo';
ALTER TABLE normative_device_versions ADD COLUMN IF NOT EXISTS artigo text NOT NULL DEFAULT '';
ALTER TABLE normative_device_versions ADD COLUMN IF NOT EXISTS paragrafo text NOT NULL DEFAULT '';
ALTER TABLE normative_device_versions ADD COLUMN IF NOT EXISTS inciso text NOT NULL DEFAULT '';
ALTER TABLE normative_device_versions ADD COLUMN IF NOT EXISTS alinea text NOT NULL DEFAULT '';
ALTER TABLE normative_device_versions ADD COLUMN IF NOT EXISTS ordem integer NOT NULL DEFAULT 0;
-- `status` já existe (006, minúsculo "vigente" na carga antiga). A sincronização grava o vocabulário do
-- Acervo: VIGENTE | REVOGADA | ALTERADA (versão encerrada por nova redação) | SUPERADA | SUSPENSA |
-- AGUARDANDO_VERIFICACAO. A leitura (`acervo.status.status_no`) aceita os dois.
ALTER TABLE normative_device_versions ADD COLUMN IF NOT EXISTS superada_por text NOT NULL DEFAULT '';
ALTER TABLE normative_device_versions ADD COLUMN IF NOT EXISTS ultima_verificacao timestamptz;
-- 'observado' = data em que a sincronização viu esta redação pela primeira vez na fonte oficial
-- (não é a data de publicação da lei alteradora; o painel diz isso ao advogado).
ALTER TABLE normative_device_versions ADD COLUMN IF NOT EXISTS valid_from_origem text NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS ix_ndv_dispositivo ON normative_device_versions (document_id, dispositivo_id, version DESC);
CREATE INDEX IF NOT EXISTS ix_ndv_artigo ON normative_device_versions (document_id, artigo) WHERE valid_until IS NULL;

-- ------------------------------------------------------------ knowledge_chunks (embedding por versão)
-- A busca ignora trecho invalidado. Ela filtra por `metadados->>'invalidado_em'` (não depende
-- desta coluna existir); a sincronização grava os dois.
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS device_version_id bigint;
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS content_hash text;
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedding_model text;
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedding_dimensions integer;
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedded_at timestamptz;
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS invalidado_em timestamptz;

CREATE INDEX IF NOT EXISTS ix_chunks_device_version ON knowledge_chunks (device_version_id);
CREATE INDEX IF NOT EXISTS ix_chunks_dispositivo ON knowledge_chunks (fonte_id, (metadados->>'dispositivo'));

-- ------------------------------------------------------------ histórico de sincronizações
CREATE TABLE IF NOT EXISTS acervo_sincronizacoes (
    id bigserial PRIMARY KEY,
    document_id text NOT NULL,
    iniciada_em timestamptz NOT NULL DEFAULT now(),
    concluida_em timestamptz,
    -- EM_ANDAMENTO | SEM_ALTERACAO | ATUALIZADO | ERRO | SIMULADO
    status text NOT NULL DEFAULT 'EM_ANDAMENTO',
    origem text NOT NULL DEFAULT 'agendada',          -- agendada | manual | script
    solicitado_por text NOT NULL DEFAULT '',
    content_hash text NOT NULL DEFAULT '',
    encoding text NOT NULL DEFAULT '',
    dispositivos_total integer NOT NULL DEFAULT 0,
    dispositivos_novos integer NOT NULL DEFAULT 0,
    dispositivos_alterados integer NOT NULL DEFAULT 0,
    dispositivos_revogados integer NOT NULL DEFAULT 0,
    dispositivos_removidos integer NOT NULL DEFAULT 0,
    embeddings_gerados integer NOT NULL DEFAULT 0,
    embeddings_mantidos integer NOT NULL DEFAULT 0,
    embeddings_invalidados integer NOT NULL DEFAULT 0,
    -- custo: tokens enviados ao provedor (aprox. caracteres/4); o valor em dinheiro fica no painel de Gastos das APIs.
    tokens_embeddings_aprox integer NOT NULL DEFAULT 0,
    duracao_ms integer,
    erro text NOT NULL DEFAULT '',
    relatorio jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_acervo_sinc_doc ON acervo_sincronizacoes (document_id, iniciada_em DESC);

-- ------------------------------------------------------------ alertas para o advogado/admin
CREATE TABLE IF NOT EXISTS acervo_alertas (
    id bigserial PRIMARY KEY,
    criado_em timestamptz NOT NULL DEFAULT now(),
    -- DISPOSITIVO_ALTERADO | DISPOSITIVO_REVOGADO | DISPOSITIVO_INCLUIDO | DISPOSITIVO_REMOVIDO |
    -- AUTORIDADE_ALTERADA | AUTORIDADE_SUPERADA | FONTE_INDISPONIVEL | ENCODING_CORROMPIDO |
    -- EMBEDDING_FALHOU | SKILL_CITA_SUPERADA | SKILL_CITA_ALTERADA
    tipo text NOT NULL,
    severidade text NOT NULL DEFAULT 'media' CHECK (severidade IN ('baixa','media','alta')),
    document_id text NOT NULL DEFAULT '',
    dispositivo_id text NOT NULL DEFAULT '',
    authority_id text NOT NULL DEFAULT '',
    titulo text NOT NULL,
    detalhe text NOT NULL DEFAULT '',
    dados jsonb NOT NULL DEFAULT '{}'::jsonb,
    sincronizacao_id bigint,
    resolvido_em timestamptz,
    resolvido_por text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_acervo_alertas_abertos ON acervo_alertas (criado_em DESC) WHERE resolvido_em IS NULL;
-- Evita repetir o mesmo alerta aberto a cada noite.
CREATE UNIQUE INDEX IF NOT EXISTS ux_acervo_alertas_aberto
    ON acervo_alertas (tipo, document_id, dispositivo_id, authority_id) WHERE resolvido_em IS NULL;

-- ------------------------------------------------------------ anotações internas do escritório
CREATE TABLE IF NOT EXISTS acervo_anotacoes (
    id bigserial PRIMARY KEY,
    criado_em timestamptz NOT NULL DEFAULT now(),
    autor text NOT NULL DEFAULT '',
    document_id text NOT NULL DEFAULT '',
    dispositivo_id text NOT NULL DEFAULT '',
    authority_id text NOT NULL DEFAULT '',
    texto text NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_acervo_anotacoes_alvo ON acervo_anotacoes (document_id, dispositivo_id);

-- ------------------------------------------------------------ autoridades_juridicas (jurisprudência)
-- Importação de súmulas/OJs/SVs entra como 'aguardando verificação' (verificada=false) até alguém
-- conferir na fonte oficial; o status jurídico continua no CHECK de 010.
ALTER TABLE autoridades_juridicas ADD COLUMN IF NOT EXISTS content_hash text NOT NULL DEFAULT '';
ALTER TABLE autoridades_juridicas ADD COLUMN IF NOT EXISTS sync_status text NOT NULL DEFAULT 'AGUARDANDO_VERIFICACAO';
ALTER TABLE autoridades_juridicas ADD COLUMN IF NOT EXISTS ultima_verificacao timestamptz;

COMMIT;

-- ============================================================ conferência (somente leitura)
SELECT table_name, column_name FROM information_schema.columns
 WHERE table_name IN ('corpus_manifest','normative_device_versions','knowledge_chunks','autoridades_juridicas')
   AND column_name IN ('sync_status','next_check_at','dispositivo_id','valid_from_origem','device_version_id','invalidado_em','content_hash')
 ORDER BY 1, 2;
SELECT to_regclass('acervo_sincronizacoes') AS sincronizacoes, to_regclass('acervo_alertas') AS alertas,
       to_regclass('acervo_anotacoes') AS anotacoes;
