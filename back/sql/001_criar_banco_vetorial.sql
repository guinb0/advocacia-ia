-- Banco vetorial do Advocacia IA — rodar no pgAdmin conectado em 10.200.1.1
--
-- Servidor: PostgreSQL 18.3, extensao `vector` 0.8.2 ja disponivel.
-- Execute a PARTE 1 conectado ao banco `postgres`; depois troque a conexao para
-- `advocacia_ia` e execute a PARTE 2. CREATE DATABASE nao roda dentro de
-- transacao, entao ele fica sozinho.
--
-- Dimensao 1536 para casar com o EMBEDDINGS_DIMENSIONS que voces ja usam no
-- vig-agent (google/gemini-embedding-001 via OpenRouter). Mudar a dimensao
-- depois obriga a recriar a coluna e reindexar tudo, entao vale conferir antes.


-- ============================================================ PARTE 1
-- Conectado ao banco `postgres`:

CREATE DATABASE advocacia_ia
    WITH ENCODING 'UTF8'
         TEMPLATE template0
         LC_COLLATE 'pt_BR.UTF-8'
         LC_CTYPE   'pt_BR.UTF-8';

-- Se o servidor nao tiver a locale pt_BR, use apenas:
--   CREATE DATABASE advocacia_ia WITH ENCODING 'UTF8' TEMPLATE template0;

COMMENT ON DATABASE advocacia_ia IS
    'Base de conhecimento vetorial do sistema juridico (triagem e RAG).';


-- ============================================================ PARTE 2
-- Agora troque a conexao para o banco `advocacia_ia` e rode daqui para baixo:

CREATE EXTENSION IF NOT EXISTS vector;      -- similaridade vetorial
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- busca por trecho, complementa o vetor
CREATE EXTENSION IF NOT EXISTS unaccent;    -- "acao" encontra "ação"


-- ---------------------------------------------------------------- fontes
-- De onde veio cada texto. Separado dos trechos porque uma mesma lei rende
-- dezenas de chunks, e a procedencia precisa ser citada na resposta ao usuario.

CREATE TABLE fontes (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tipo         TEXT NOT NULL CHECK (tipo IN ('lei','sumula','jurisprudencia','interno','outro')),
    titulo       TEXT NOT NULL,
    identificador TEXT,           -- "Lei 8.213/91 art. 21", "Sumula 378 TST"
    url          TEXT,
    publicado_em DATE,
    criado_em    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_fontes_tipo ON fontes (tipo);


-- ------------------------------------------------------ trechos vetoriais
-- O chunk e a unidade de busca. `embedding` pode ser NULL enquanto o texto
-- ainda nao foi vetorizado — o ingestor preenche depois, em lote.

CREATE TABLE knowledge_chunks (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fonte_id   BIGINT REFERENCES fontes(id) ON DELETE CASCADE,
    ordem      INT NOT NULL DEFAULT 0,       -- posicao do trecho dentro da fonte
    texto      TEXT NOT NULL,
    metadados  JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding  vector(1536),
    criado_em  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HNSW com cosseno: e a metrica usada por praticamente todo modelo de
-- embedding atual, inclusive o gemini-embedding-001. Se um dia trocarem para
-- distancia L2, o operador do indice muda para vector_l2_ops.
CREATE INDEX ix_chunks_embedding
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);

-- Busca textual como rede de seguranca: quando o termo e literal (numero de
-- artigo, nome de sumula), trigrama acha o que o vetor deixa passar.
CREATE INDEX ix_chunks_texto_trgm
    ON knowledge_chunks USING gin (texto gin_trgm_ops);

CREATE INDEX ix_chunks_fonte ON knowledge_chunks (fonte_id, ordem);
CREATE INDEX ix_chunks_metadados ON knowledge_chunks USING gin (metadados);


-- ------------------------------------------------- entrevistas triadas
-- Guarda o relato e a categoria confirmada PELO ADVOGADO (nao a sugerida).
-- Serve para dois fins: medir a triagem contra decisao humana real, e no
-- futuro alimentar exemplos de casos parecidos.
--
-- ATENCAO: o relato contem dado pessoal sensivel (saude, CPF). Antes de
-- popular esta tabela, decidir retencao e base legal na LGPD — o banco fica
-- num servidor compartilhado com outros projetos.

CREATE TABLE entrevistas (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    caso_id           TEXT,                  -- id do caso no SQLite da aplicacao
    texto             TEXT NOT NULL,
    categoria_sugerida TEXT,                 -- o que a triagem propos
    categoria_final   TEXT,                  -- o que o advogado confirmou
    metodo            TEXT CHECK (metodo IN ('llm','pistas')),
    confiante         BOOLEAN,
    embedding         vector(1536),
    criado_em         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_entrevistas_embedding
    ON entrevistas USING hnsw (embedding vector_cosine_ops);

CREATE INDEX ix_entrevistas_categoria ON entrevistas (categoria_final);


-- ============================================================ conferencia

SELECT extname, extversion FROM pg_extension ORDER BY extname;

SELECT table_name FROM information_schema.tables
 WHERE table_schema = 'public' ORDER BY table_name;

-- Deve devolver a dimensao 1536 nas duas colunas de embedding:
SELECT c.relname AS tabela, a.attname AS coluna,
       format_type(a.atttypid, a.atttypmod) AS tipo
  FROM pg_attribute a
  JOIN pg_class c ON c.oid = a.attrelid
 WHERE a.atttypid = 'vector'::regtype AND NOT a.attisdropped
 ORDER BY 1, 2;
