-- Baseline schema, reproducing the exact v0.1.2 tables and indexes.
--
-- Idempotent `CREATE ... IF NOT EXISTS` DDL so a database created by the
-- pre-migration `init_db` converges onto this baseline without data loss and is
-- then recorded as already applied. Introduces no schema change versus v0.1.2.

CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    source TEXT NOT NULL,
    seed_key TEXT,
    seed_version INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extractors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    instructions TEXT NOT NULL,
    enable_thinking INTEGER NOT NULL,
    schema TEXT NOT NULL,
    examples TEXT NOT NULL,
    source TEXT NOT NULL,
    seed_key TEXT,
    seed_version INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    extractor_id TEXT NOT NULL REFERENCES extractors(id) ON DELETE CASCADE,
    file_id TEXT REFERENCES files(id) ON DELETE CASCADE,
    source_text TEXT,
    status TEXT NOT NULL,
    result TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_extractor_id ON jobs(extractor_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created_at ON jobs(status, created_at);
