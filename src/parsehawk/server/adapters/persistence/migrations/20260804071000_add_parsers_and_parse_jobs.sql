-- Add reusable Parser resources and a separate asynchronous parse-job queue.

CREATE TABLE parsers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    output_format TEXT NOT NULL,
    instructions TEXT NOT NULL,
    reasoning_effort TEXT,
    provider_name TEXT,
    model TEXT,
    source TEXT NOT NULL,
    seed_key TEXT,
    seed_version INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_parsers_name ON parsers(name);

CREATE TABLE parse_jobs (
    id TEXT PRIMARY KEY,
    parser_id TEXT NOT NULL REFERENCES parsers(id) ON DELETE RESTRICT,
    file_id TEXT NOT NULL REFERENCES files(id) ON DELETE RESTRICT,
    parser_snapshot TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    provider_name_used TEXT,
    model_used TEXT,
    reasoning_effort_used TEXT,
    model_adapter_used TEXT
);

CREATE INDEX idx_parse_jobs_parser_id ON parse_jobs(parser_id);
CREATE INDEX idx_parse_jobs_status_created_at ON parse_jobs(status, created_at);
