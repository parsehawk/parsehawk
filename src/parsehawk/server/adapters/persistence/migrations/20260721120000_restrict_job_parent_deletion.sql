-- Preserve accepted job history when its referenced file or extractor is deleted.
-- Parent resources must now remain until their jobs are explicitly removed.

CREATE TABLE jobs_new (
    id TEXT PRIMARY KEY,
    extractor_id TEXT NOT NULL REFERENCES extractors(id) ON DELETE RESTRICT,
    file_id TEXT REFERENCES files(id) ON DELETE RESTRICT,
    source_text TEXT,
    status TEXT NOT NULL,
    result TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    provider_name_used TEXT,
    model_used TEXT
);

INSERT INTO jobs_new (
    id, extractor_id, file_id, source_text, status, result, error,
    created_at, started_at, completed_at, provider_name_used, model_used
)
SELECT
    id, extractor_id, file_id, source_text, status, result, error,
    created_at, started_at, completed_at, provider_name_used, model_used
FROM jobs;

DROP TABLE jobs;
ALTER TABLE jobs_new RENAME TO jobs;

CREATE INDEX idx_jobs_extractor_id ON jobs(extractor_id);
CREATE INDEX idx_jobs_status_created_at ON jobs(status, created_at);
