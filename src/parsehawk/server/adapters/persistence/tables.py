from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Index, Integer, MetaData, Table, Text

metadata = MetaData()

files = Table(
    "files",
    metadata,
    Column("id", Text, primary_key=True),
    Column("file_name", Text, nullable=False),
    Column("content_type", Text, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("storage_path", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("seed_key", Text),
    Column("seed_version", Integer),
    Column("created_at", Text, nullable=False),
)

extractors = Table(
    "extractors",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("display_name", Text, nullable=False),
    Column("instructions", Text, nullable=False),
    Column("schema", Text, nullable=False),
    Column("examples", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("seed_key", Text),
    Column("seed_version", Integer),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Column("provider_name", Text),
    Column("model", Text),
    Column("reasoning_effort", Text),
)
Index("idx_extractors_name", extractors.c.name, unique=True)

jobs = Table(
    "jobs",
    metadata,
    Column("id", Text, primary_key=True),
    Column("extractor_id", ForeignKey("extractors.id", ondelete="RESTRICT"), nullable=False),
    Column("file_id", ForeignKey("files.id", ondelete="RESTRICT")),
    Column("source_text", Text),
    Column("status", Text, nullable=False),
    Column("result", Text),
    Column("error", Text),
    Column("created_at", Text, nullable=False),
    Column("started_at", Text),
    Column("completed_at", Text),
    Column("provider_name_used", Text),
    Column("model_used", Text),
)
Index("idx_jobs_extractor_id", jobs.c.extractor_id)
Index("idx_jobs_status_created_at", jobs.c.status, jobs.c.created_at)

providers = Table(
    "providers",
    metadata,
    Column("name", Text, primary_key=True),
    Column("base_url", Text),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Column("configuration", Text, nullable=False),
)

provider_secrets = Table(
    "provider_secrets",
    metadata,
    Column(
        "provider_name",
        ForeignKey("providers.name", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("ciphertext", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
)
