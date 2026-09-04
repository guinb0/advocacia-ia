-- Backfill idempotente de dbo.pessoas e dbo.caso_pessoas.
-- Requer a execução prévia de 004_pessoas_ddl.sql.
--
-- Precedência do CPF:
--   1. exatamente um CPF válido distinto nas assinaturas do caso;
--   2. sem CPF em assinatura, exatamente um CPF válido distinto no OCR;
--   3. conflitos vão para dbo.pessoas_revisao e não são adivinhados.
--
-- Pessoa sem CPF não é deduplicada por nome: cada caso ganha sua própria pessoa.
-- Execute primeiro em um dump restaurado e revise os SELECTs ao final.

BEGIN;

-- Funções temporárias: não deixam objetos auxiliares permanentes no banco.
-- A primeira tabela temporária materializa o schema pg_temp da sessão antes
-- da criação das funções auxiliares nele.
CREATE TEMP TABLE _backfill_context (id integer) ON COMMIT DROP;

CREATE OR REPLACE FUNCTION pg_temp.jsonb_seguro(valor text)
RETURNS jsonb
LANGUAGE plpgsql
IMMUTABLE
AS $func$
BEGIN
    IF valor IS NULL OR btrim(valor) = '' THEN
        RETURN NULL;
    END IF;
    RETURN valor::jsonb;
EXCEPTION WHEN invalid_text_representation THEN
    RETURN NULL;
END;
$func$;

CREATE OR REPLACE FUNCTION pg_temp.cpf_valido(valor text)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
AS $func$
DECLARE
    cpf text := regexp_replace(coalesce(valor, ''), '[^0-9]', '', 'g');
    soma integer;
    digito1 integer;
    digito2 integer;
    i integer;
BEGIN
    IF cpf !~ '^[0-9]{11}$' OR cpf ~ '^([0-9])\1{10}$' THEN
        RETURN false;
    END IF;

    soma := 0;
    FOR i IN 1..9 LOOP
        soma := soma + substr(cpf, i, 1)::integer * (11 - i);
    END LOOP;
    digito1 := CASE WHEN 11 - (soma % 11) >= 10 THEN 0 ELSE 11 - (soma % 11) END;

    soma := 0;
    FOR i IN 1..10 LOOP
        soma := soma + substr(cpf, i, 1)::integer * (12 - i);
    END LOOP;
    digito2 := CASE WHEN 11 - (soma % 11) >= 10 THEN 0 ELSE 11 - (soma % 11) END;

    RETURN substr(cpf, 10, 1)::integer = digito1
       AND substr(cpf, 11, 1)::integer = digito2;
END;
$func$;

CREATE TEMP TABLE _cpf_assinatura ON COMMIT DROP AS
SELECT DISTINCT
       a.caso_id,
       regexp_replace(a.cpf, '[^0-9]', '', 'g') AS cpf
FROM dbo.assinaturas AS a
WHERE a.caso_id IS NOT NULL
  AND pg_temp.cpf_valido(a.cpf);

CREATE TEMP TABLE _json_entregas ON COMMIT DROP AS
SELECT e.id,
       e.caso_id,
       e.extracao_json,
       pg_temp.jsonb_seguro(e.extracao_json::text) AS extracao
FROM dbo.entregas AS e
WHERE e.extracao_json IS NOT NULL
  AND btrim(e.extracao_json::text) <> '';

-- JSON quebrado é registrado para revisão, mas não interrompe o restante.
INSERT INTO dbo.pessoas_revisao
    (caso_id, motivo, nome_encontrado, detalhes, atualizado_em)
SELECT DISTINCT
       j.caso_id,
       'extracao_json_invalido',
       nullif(btrim(c.cliente), ''),
       jsonb_build_object('entrega_ids', ids.entrega_ids),
       now()
FROM _json_entregas AS j
JOIN dbo.casos AS c ON c.id = j.caso_id
JOIN LATERAL (
    SELECT jsonb_agg(j2.id ORDER BY j2.id) AS entrega_ids
    FROM _json_entregas AS j2
    WHERE j2.caso_id = j.caso_id AND j2.extracao IS NULL
) AS ids ON true
WHERE j.extracao IS NULL
ON CONFLICT (caso_id, motivo) DO UPDATE
SET nome_encontrado = EXCLUDED.nome_encontrado,
    detalhes = EXCLUDED.detalhes,
    atualizado_em = now();

CREATE TEMP TABLE _cpf_ocr ON COMMIT DROP AS
SELECT DISTINCT
       j.caso_id,
       regexp_replace(campo->>'valor', '[^0-9]', '', 'g') AS cpf
FROM _json_entregas AS j
CROSS JOIN LATERAL jsonb_array_elements(
    CASE
        WHEN jsonb_typeof(j.extracao->'campos') = 'array' THEN j.extracao->'campos'
        ELSE '[]'::jsonb
    END
) AS campo
WHERE lower(coalesce(campo->>'nome', '')) = 'cpf'
  AND pg_temp.cpf_valido(campo->>'valor');

CREATE TEMP TABLE _resolucao ON COMMIT DROP AS
WITH assinaturas AS (
    SELECT caso_id, count(*) AS quantidade, min(cpf) AS cpf,
           jsonb_agg(cpf ORDER BY cpf) AS cpfs
    FROM _cpf_assinatura
    GROUP BY caso_id
),
ocr AS (
    SELECT caso_id, count(*) AS quantidade, min(cpf) AS cpf,
           jsonb_agg(cpf ORDER BY cpf) AS cpfs
    FROM _cpf_ocr
    GROUP BY caso_id
)
SELECT
    c.id AS caso_id,
    nullif(btrim(c.cliente), '') AS nome,
    CASE
        WHEN coalesce(a.quantidade, 0) = 1 THEN a.cpf
        WHEN coalesce(a.quantidade, 0) = 0 AND coalesce(o.quantidade, 0) = 1 THEN o.cpf
        ELSE NULL
    END AS cpf,
    CASE
        WHEN nullif(btrim(c.cliente), '') IS NULL THEN 'cliente_sem_nome'
        WHEN coalesce(a.quantidade, 0) > 1 THEN 'multiplos_cpfs_assinatura'
        WHEN coalesce(a.quantidade, 0) = 0 AND coalesce(o.quantidade, 0) > 1
            THEN 'multiplos_cpfs_ocr'
        ELSE NULL
    END AS motivo,
    coalesce(a.cpfs, '[]'::jsonb) AS cpfs_assinatura,
    coalesce(o.cpfs, '[]'::jsonb) AS cpfs_ocr
FROM dbo.casos AS c
LEFT JOIN assinaturas AS a ON a.caso_id = c.id
LEFT JOIN ocr AS o ON o.caso_id = c.id;

-- Conflitos de identidade ficam pendentes, sem criação automática da pessoa.
INSERT INTO dbo.pessoas_revisao
    (caso_id, motivo, nome_encontrado, cpfs_encontrados, detalhes, atualizado_em)
SELECT
    r.caso_id,
    r.motivo,
    r.nome,
    CASE
        WHEN r.motivo = 'multiplos_cpfs_assinatura' THEN r.cpfs_assinatura
        WHEN r.motivo = 'multiplos_cpfs_ocr' THEN r.cpfs_ocr
        ELSE '[]'::jsonb
    END,
    jsonb_build_object(
        'cpfs_assinatura', r.cpfs_assinatura,
        'cpfs_ocr', r.cpfs_ocr
    ),
    now()
FROM _resolucao AS r
WHERE r.motivo IS NOT NULL
ON CONFLICT (caso_id, motivo) DO UPDATE
SET nome_encontrado = EXCLUDED.nome_encontrado,
    cpfs_encontrados = EXCLUDED.cpfs_encontrados,
    detalhes = EXCLUDED.detalhes,
    atualizado_em = now();

-- CPF canônico permite deduplicação segura entre casos.
INSERT INTO dbo.pessoas (cpf, nome, criado_por, atualizado_por)
SELECT DISTINCT ON (r.cpf)
       r.cpf,
       r.nome,
       'backfill_005',
       'backfill_005'
FROM _resolucao AS r
WHERE r.motivo IS NULL
  AND r.cpf IS NOT NULL
ORDER BY r.cpf, r.caso_id
ON CONFLICT (cpf) DO NOTHING;

INSERT INTO dbo.caso_pessoas (caso_id, pessoa_id, papel, criado_por)
SELECT r.caso_id, p.id, 'cliente_principal', 'backfill_005'
FROM _resolucao AS r
JOIN dbo.pessoas AS p ON p.cpf = r.cpf
WHERE r.motivo IS NULL
  AND r.cpf IS NOT NULL
ON CONFLICT DO NOTHING;

-- Sem CPF: cria no máximo uma pessoa por caso e nunca funde apenas pelo nome.
DO $backfill$
DECLARE
    item record;
    nova_pessoa_id bigint;
BEGIN
    FOR item IN
        SELECT r.caso_id, r.nome
        FROM _resolucao AS r
        WHERE r.motivo IS NULL
          AND r.cpf IS NULL
          AND NOT EXISTS (
              SELECT 1
              FROM dbo.caso_pessoas AS cp
              WHERE cp.caso_id = r.caso_id
                AND cp.papel = 'cliente_principal'
          )
        ORDER BY r.caso_id
    LOOP
        INSERT INTO dbo.pessoas (cpf, nome, criado_por, atualizado_por)
        VALUES (NULL, item.nome, 'backfill_005', 'backfill_005')
        RETURNING id INTO nova_pessoa_id;

        INSERT INTO dbo.caso_pessoas
            (caso_id, pessoa_id, papel, criado_por)
        VALUES
            (item.caso_id, nova_pessoa_id, 'cliente_principal', 'backfill_005');
    END LOOP;
END;
$backfill$;

-- Mesmo nome em casos diferentes sem CPF é suspeita, não autorização para merge.
WITH duplicados AS (
    SELECT lower(regexp_replace(btrim(p.nome), '\s+', ' ', 'g')) AS nome_chave
    FROM dbo.pessoas AS p
    JOIN dbo.caso_pessoas AS cp ON cp.pessoa_id = p.id
    WHERE cp.papel = 'cliente_principal' AND p.cpf IS NULL
    GROUP BY 1
    HAVING count(DISTINCT cp.caso_id) > 1
)
INSERT INTO dbo.pessoas_revisao
    (caso_id, motivo, nome_encontrado, detalhes, atualizado_em)
SELECT
    cp.caso_id,
    'nome_duplicado_sem_cpf',
    p.nome,
    jsonb_build_object('pessoa_id', p.id),
    now()
FROM dbo.pessoas AS p
JOIN dbo.caso_pessoas AS cp ON cp.pessoa_id = p.id
JOIN duplicados AS d
  ON d.nome_chave = lower(regexp_replace(btrim(p.nome), '\s+', ' ', 'g'))
WHERE cp.papel = 'cliente_principal' AND p.cpf IS NULL
ON CONFLICT (caso_id, motivo) DO UPDATE
SET nome_encontrado = EXCLUDED.nome_encontrado,
    detalhes = EXCLUDED.detalhes,
    atualizado_em = now();

COMMIT;

-- Validação pós-backfill (somente leitura).
SELECT
    (SELECT count(*) FROM dbo.casos) AS casos_total,
    (SELECT count(DISTINCT caso_id)
       FROM dbo.caso_pessoas
      WHERE papel = 'cliente_principal') AS casos_com_cliente_vinculado,
    (SELECT count(*) FROM dbo.pessoas) AS pessoas_total,
    (SELECT count(*) FROM dbo.pessoas WHERE cpf IS NOT NULL) AS pessoas_com_cpf,
    (SELECT count(*) FROM dbo.pessoas_revisao WHERE resolvido_em IS NULL) AS revisoes_pendentes;

SELECT motivo, count(*) AS quantidade
FROM dbo.pessoas_revisao
WHERE resolvido_em IS NULL
GROUP BY motivo
ORDER BY quantidade DESC, motivo;

SELECT c.id AS caso_id, c.cliente
FROM dbo.casos AS c
LEFT JOIN dbo.caso_pessoas AS cp
       ON cp.caso_id = c.id AND cp.papel = 'cliente_principal'
WHERE cp.caso_id IS NULL
ORDER BY c.id;
