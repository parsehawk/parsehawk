-- Providers, their encrypted secrets, and per-extractor provider/model (#5).
--
-- Providers are the fixed set ParseHawk ships; their rows are seeded by the
-- application, not this migration. API keys are never stored in `providers` --
-- they live encrypted in `provider_secrets`, keyed by provider name.

CREATE TABLE providers (
    name TEXT PRIMARY KEY,
    base_url TEXT,
    api_version TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE provider_secrets (
    provider_name TEXT PRIMARY KEY REFERENCES providers(name) ON DELETE CASCADE,
    ciphertext TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

ALTER TABLE extractors ADD COLUMN provider_name TEXT;
ALTER TABLE extractors ADD COLUMN model TEXT;
