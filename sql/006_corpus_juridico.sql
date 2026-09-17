-- Corpus normativo rastreável. Aplicar uma vez antes da primeira ingestão.
CREATE TABLE IF NOT EXISTS corpus_manifest (
    document_id TEXT PRIMARY KEY, document_name TEXT NOT NULL, document_number TEXT,
    document_year TEXT, official_source TEXT NOT NULL, source_url TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ, parser_version TEXT NOT NULL, total_devices INTEGER NOT NULL DEFAULT 0,
    total_chunks INTEGER NOT NULL DEFAULT 0, total_embeddings INTEGER NOT NULL DEFAULT 0,
    current_devices INTEGER NOT NULL DEFAULT 0, revoked_devices INTEGER NOT NULL DEFAULT 0,
    historical_versions INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'PENDING',
    last_checked_at TIMESTAMPTZ, report JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS normative_device_versions (
    id BIGSERIAL PRIMARY KEY, document_id TEXT NOT NULL REFERENCES corpus_manifest(document_id),
    identifier TEXT NOT NULL, version INTEGER NOT NULL, parent_identifier TEXT,
    hierarchy JSONB NOT NULL DEFAULT '{}'::jsonb, text TEXT NOT NULL, content_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'vigente', valid_from DATE, valid_until DATE,
    source_url TEXT NOT NULL, retrieved_at TIMESTAMPTZ NOT NULL, UNIQUE(document_id, identifier, version)
);
CREATE INDEX IF NOT EXISTS ix_normative_device_current ON normative_device_versions(document_id, identifier, version DESC);
CREATE TABLE IF NOT EXISTS corpus_references (
    id BIGSERIAL PRIMARY KEY, document_id TEXT NOT NULL, source_identifier TEXT,
    target_text TEXT NOT NULL, target_document TEXT, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
    UNIQUE(document_id, source_identifier, target_text)
);
