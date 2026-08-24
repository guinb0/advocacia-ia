-- Índice parcial para achar o que ainda falta vetorizar.
--
-- Aplicar SOMENTE no banco `advocacia_ia`. O servidor do `DATABASE_URL` é
-- compartilhado com outros sistemas; nada aqui os alcança, mas vale conferir
-- antes de rodar:
--
--     SELECT current_database();   -- precisa dizer advocacia_ia
--
-- ---------------------------------------------------------------- o problema
--
-- `scripts/vetorizar_pendentes.py` pede o próximo lote assim:
--
--     SELECT k.id, k.texto FROM knowledge_chunks k
--       JOIN fontes f ON f.id = k.fonte_id
--      WHERE k.embedding IS NULL AND f.tipo = 'jurisprudencia'
--      ORDER BY k.id LIMIT 64
--
-- Sem este índice o plano era percorrer a chave primária em ordem de id e
-- filtrar `embedding IS NULL` linha a linha:
--
--     Index Scan using knowledge_chunks_pkey  Filter: (embedding IS NULL)
--
-- Medido em 13/08/2026: os pendentes ocupavam os ids 42497 a 52932 — todos no
-- fim da tabela. Cada lote de 64 varria os ~42.490 já vetorizados antes de achar
-- o primeiro pendente. E o custo CRESCE com o progresso: quanto mais chunks
-- ficam prontos, mais linhas cada lote precisa pular. Com a tabela em cache isso
-- levava 0,48s; com cache frio ou o servidor sob carga, passou de 180s e a
-- vetorização parou sozinha.
--
-- ---------------------------------------------------------------- a solução
--
-- Um índice que só contém as linhas que faltam. Ele encolhe conforme a
-- vetorização avança — no fim fica vazio — que é o oposto do problema acima.
--
-- CONCURRENTLY de propósito NÃO é usado: a conexão com este servidor é
-- instável, e um CONCURRENTLY interrompido deixa índice INVÁLIDO para trás, que
-- precisa ser derrubado à mão. O CREATE INDEX comum é atômico — se a conexão
-- cair, não sobra nada. Ele tranca escritas em knowledge_chunks por alguns
-- segundos, e o único escritor é o próprio vetorizador, que já retenta.

CREATE INDEX IF NOT EXISTS ix_chunks_pendentes
    ON knowledge_chunks (id)
 WHERE embedding IS NULL;

-- Sem isto o planejador pode continuar com o plano antigo por estatística velha.
ANALYZE knowledge_chunks;

-- ------------------------------------------------------------- conferência
--
-- O plano precisa passar a citar ix_chunks_pendentes:
--
--     EXPLAIN SELECT k.id, k.texto FROM knowledge_chunks k
--               JOIN fontes f ON f.id = k.fonte_id
--              WHERE k.embedding IS NULL AND f.tipo = 'jurisprudencia'
--              ORDER BY k.id LIMIT 64;
--
-- Terminada a vetorização o índice fica vazio e custa quase nada manter. Ele
-- volta a ter conteúdo sozinho na próxima ingestão, que é justamente quando
-- serve para alguma coisa — não derrube.
