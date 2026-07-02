-- Split extractor identity into stable API-safe name plus mutable display_name.

CREATE TEMP TABLE jobs_backup AS SELECT * FROM jobs;

CREATE TABLE extractors_new (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    instructions TEXT NOT NULL,
    enable_thinking INTEGER NOT NULL,
    schema TEXT NOT NULL,
    examples TEXT NOT NULL,
    source TEXT NOT NULL,
    seed_key TEXT,
    seed_version INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    provider_name TEXT,
    model TEXT
);

INSERT INTO extractors_new (
    id, name, display_name, instructions, enable_thinking, schema, examples,
    source, seed_key, seed_version, created_at, updated_at, provider_name, model
)
WITH slugged AS (
    SELECT
        *,
        parsehawk_slug(name) AS base_name,
        EXISTS (
            SELECT 1 FROM extractors AS receipt
            WHERE receipt.seed_key = 'prebuilt:receipt:v1'
        ) AS has_prebuilt_receipt
    FROM extractors
),
ranked AS (
    SELECT
        *,
        COUNT(*) OVER (PARTITION BY base_name) AS base_count,
        ROW_NUMBER() OVER (
            PARTITION BY base_name
            ORDER BY CASE WHEN seed_key = 'prebuilt:receipt:v1' THEN 0 ELSE 1 END, id
        ) AS base_rank
    FROM slugged
)
SELECT
    id,
    CASE
        WHEN seed_key = 'prebuilt:receipt:v1' THEN 'receipt'
        WHEN base_count > 1 OR (base_name = 'receipt' AND has_prebuilt_receipt)
            THEN substr(base_name, 1, 57) || '-' || substr(lower(replace(id, 'extractor_', '')), 1, 6)
        ELSE base_name
    END AS name,
    name AS display_name,
    instructions,
    enable_thinking,
    schema,
    examples,
    source,
    seed_key,
    seed_version,
    created_at,
    updated_at,
    provider_name,
    model
FROM ranked;

DROP TABLE extractors;
ALTER TABLE extractors_new RENAME TO extractors;

CREATE UNIQUE INDEX idx_extractors_name ON extractors(name);

INSERT OR IGNORE INTO jobs (
    id, extractor_id, file_id, source_text, status, result, error,
    created_at, started_at, completed_at
)
SELECT
    id, extractor_id, file_id, source_text, status, result, error,
    created_at, started_at, completed_at
FROM jobs_backup;

DROP TABLE jobs_backup;
