-- Torna cargas repetidas do RAG seguras e auditáveis.
CREATE UNIQUE INDEX IF NOT EXISTS uq_fontes_tipo_identificador
    ON fontes (tipo, identificador) WHERE identificador IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_chunks_fonte_ordem
    ON knowledge_chunks (fonte_id, ordem);

