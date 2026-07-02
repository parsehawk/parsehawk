from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, List

from parsehawk.core.domain.models import (
    Example,
    Extractor,
    ExtractorSource,
    File,
    FileSource,
    Job,
    JobError,
    JobResult,
    JobStatus,
    Provider,
    ProviderName,
    utc_now,
)
from parsehawk.server.adapters.persistence.migrations import apply_pending
from parsehawk.server.adapters.security import SecretCipher

# A single sqlite3.Connection is shared across FastAPI's request threadpool, so
# multi-statement write transactions (e.g. claim_next_queued's BEGIN IMMEDIATE)
# can interleave across threads. This process-wide lock serializes writes so each
# transaction is atomic; busy_timeout/WAL below handle the separate worker process.
_write_lock = threading.RLock()


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Wait (rather than fail immediately with "database is locked") when another
    # connection holds the write lock, and use WAL so readers don't block writers.
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Bring the database schema up to date by applying pending migrations.

    The schema is no longer defined inline here: ordered, tracked migrations under
    ``migrations/`` own the DDL, and the runner is safe to call repeatedly.
    """
    apply_pending(conn)


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_json(value: str) -> Any:
    return json.loads(value)


def _datetime_to_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime_from_text(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


@dataclass(frozen=True)
class SQLiteFileRow:
    id: str
    file_name: str
    content_type: str
    size_bytes: int
    sha256: str
    storage_path: str
    source: str
    seed_key: str | None
    seed_version: int | None
    created_at: str

    @classmethod
    def from_domain(cls, file: File) -> SQLiteFileRow:
        return cls(
            id=file.id,
            file_name=file.file_name,
            content_type=file.content_type,
            size_bytes=file.size_bytes,
            sha256=file.sha256,
            storage_path=file.storage_path,
            source=file.source.value,
            seed_key=file.seed_key,
            seed_version=file.seed_version,
            created_at=file.created_at.isoformat(),
        )

    @classmethod
    def from_sqlite(cls, row: sqlite3.Row) -> SQLiteFileRow:
        return cls(**dict(row))

    def to_domain(self) -> File:
        created_at = _datetime_from_text(self.created_at)
        assert created_at is not None
        return File(
            id=self.id,
            file_name=self.file_name,
            content_type=self.content_type,
            size_bytes=self.size_bytes,
            sha256=self.sha256,
            storage_path=self.storage_path,
            source=FileSource(self.source),
            seed_key=self.seed_key,
            seed_version=self.seed_version,
            created_at=created_at,
        )


@dataclass(frozen=True)
class SQLiteExtractorRow:
    id: str
    name: str
    display_name: str
    instructions: str
    enable_thinking: int
    provider_name: str | None
    model: str | None
    schema: str
    examples: str
    source: str
    seed_key: str | None
    seed_version: int | None
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, extractor: Extractor) -> SQLiteExtractorRow:
        return cls(
            id=extractor.id,
            name=extractor.name,
            display_name=extractor.display_name,
            instructions=extractor.instructions,
            enable_thinking=1 if extractor.enable_thinking else 0,
            provider_name=extractor.provider_name.value if extractor.provider_name else None,
            model=extractor.model,
            schema=_dump_json(extractor.schema),
            examples=_dump_json(
                [example.model_dump(mode="json") for example in extractor.examples]
            ),
            source=extractor.source.value,
            seed_key=extractor.seed_key,
            seed_version=extractor.seed_version,
            created_at=extractor.created_at.isoformat(),
            updated_at=extractor.updated_at.isoformat(),
        )

    @classmethod
    def from_sqlite(cls, row: sqlite3.Row) -> SQLiteExtractorRow:
        return cls(**dict(row))

    def to_domain(self) -> Extractor:
        created_at = _datetime_from_text(self.created_at)
        updated_at = _datetime_from_text(self.updated_at)
        assert created_at is not None
        assert updated_at is not None
        return Extractor(
            id=self.id,
            name=self.name,
            display_name=self.display_name,
            instructions=self.instructions,
            enable_thinking=bool(self.enable_thinking),
            provider_name=ProviderName(self.provider_name) if self.provider_name else None,
            model=self.model,
            schema=_load_json(self.schema),
            examples=[Example.model_validate(example) for example in _load_json(self.examples)],
            source=ExtractorSource(self.source),
            seed_key=self.seed_key,
            seed_version=self.seed_version,
            created_at=created_at,
            updated_at=updated_at,
        )


@dataclass(frozen=True)
class SQLiteJobRow:
    id: str
    extractor_id: str
    file_id: str | None
    source_text: str | None
    status: str
    result: str | None
    error: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None

    @classmethod
    def from_domain(cls, job: Job) -> SQLiteJobRow:
        return cls(
            id=job.id,
            extractor_id=job.extractor_id,
            file_id=job.file_id,
            source_text=job.source_text,
            status=job.status.value,
            result=_dump_json(job.result.model_dump(mode="json")) if job.result else None,
            error=_dump_json(job.error.model_dump(mode="json")) if job.error else None,
            created_at=job.created_at.isoformat(),
            started_at=_datetime_to_text(job.started_at),
            completed_at=_datetime_to_text(job.completed_at),
        )

    @classmethod
    def from_sqlite(cls, row: sqlite3.Row) -> SQLiteJobRow:
        return cls(**dict(row))

    def to_domain(self) -> Job:
        created_at = _datetime_from_text(self.created_at)
        assert created_at is not None
        return Job(
            id=self.id,
            extractor_id=self.extractor_id,
            file_id=self.file_id,
            source_text=self.source_text,
            status=JobStatus(self.status),
            result=JobResult.model_validate(_load_json(self.result)) if self.result else None,
            error=JobError.model_validate(_load_json(self.error)) if self.error else None,
            created_at=created_at,
            started_at=_datetime_from_text(self.started_at),
            completed_at=_datetime_from_text(self.completed_at),
        )


class SQLiteFileRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, file: File) -> None:
        row = SQLiteFileRow.from_domain(file)
        with _write_lock:
            self._conn.execute(
                """
                INSERT INTO files (
                    id, file_name, content_type, size_bytes, sha256, storage_path,
                    source, seed_key, seed_version, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    file_name = excluded.file_name,
                    content_type = excluded.content_type,
                    size_bytes = excluded.size_bytes,
                    sha256 = excluded.sha256,
                    storage_path = excluded.storage_path,
                    source = excluded.source,
                    seed_key = excluded.seed_key,
                    seed_version = excluded.seed_version,
                    created_at = excluded.created_at
                """,
                (
                    row.id,
                    row.file_name,
                    row.content_type,
                    row.size_bytes,
                    row.sha256,
                    row.storage_path,
                    row.source,
                    row.seed_key,
                    row.seed_version,
                    row.created_at,
                ),
            )
            self._conn.commit()

    def list(self) -> List[File]:
        rows = self._conn.execute("SELECT * FROM files ORDER BY id").fetchall()
        return [SQLiteFileRow.from_sqlite(row).to_domain() for row in rows]

    def get(self, file_id: str) -> File | None:
        row = self._conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        return SQLiteFileRow.from_sqlite(row).to_domain() if row else None

    def delete(self, file_id: str) -> None:
        with _write_lock:
            self._conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
            self._conn.commit()


class SQLiteExtractorRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, extractor: Extractor) -> None:
        row = SQLiteExtractorRow.from_domain(extractor)
        with _write_lock:
            self._conn.execute(
                """
                INSERT INTO extractors (
                    id, name, display_name, instructions, enable_thinking, provider_name, model,
                    schema, examples, source, seed_key, seed_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    display_name = excluded.display_name,
                    instructions = excluded.instructions,
                    enable_thinking = excluded.enable_thinking,
                    provider_name = excluded.provider_name,
                    model = excluded.model,
                    schema = excluded.schema,
                    examples = excluded.examples,
                    source = excluded.source,
                    seed_key = excluded.seed_key,
                    seed_version = excluded.seed_version,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    row.id,
                    row.name,
                    row.display_name,
                    row.instructions,
                    row.enable_thinking,
                    row.provider_name,
                    row.model,
                    row.schema,
                    row.examples,
                    row.source,
                    row.seed_key,
                    row.seed_version,
                    row.created_at,
                    row.updated_at,
                ),
            )
            self._conn.commit()

    def list(self) -> List[Extractor]:
        rows = self._conn.execute("SELECT * FROM extractors ORDER BY id").fetchall()
        return [SQLiteExtractorRow.from_sqlite(row).to_domain() for row in rows]

    def get(self, extractor_id: str) -> Extractor | None:
        row = self._conn.execute(
            "SELECT * FROM extractors WHERE id = ?", (extractor_id,)
        ).fetchone()
        return SQLiteExtractorRow.from_sqlite(row).to_domain() if row else None

    def get_by_name(self, name: str) -> Extractor | None:
        row = self._conn.execute("SELECT * FROM extractors WHERE name = ?", (name,)).fetchone()
        return SQLiteExtractorRow.from_sqlite(row).to_domain() if row else None

    def delete(self, extractor_id: str) -> None:
        with _write_lock:
            self._conn.execute("DELETE FROM extractors WHERE id = ?", (extractor_id,))
            self._conn.commit()


class SQLiteJobRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, job: Job) -> None:
        row = SQLiteJobRow.from_domain(job)
        with _write_lock:
            self._conn.execute(
                """
                INSERT INTO jobs (
                    id, extractor_id, file_id, source_text, status, result, error,
                    created_at, started_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    extractor_id = excluded.extractor_id,
                    file_id = excluded.file_id,
                    source_text = excluded.source_text,
                    status = excluded.status,
                    result = excluded.result,
                    error = excluded.error,
                    created_at = excluded.created_at,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at
                """,
                (
                    row.id,
                    row.extractor_id,
                    row.file_id,
                    row.source_text,
                    row.status,
                    row.result,
                    row.error,
                    row.created_at,
                    row.started_at,
                    row.completed_at,
                ),
            )
            self._conn.commit()

    def list(self, extractor_id: str | None = None) -> List[Job]:
        if extractor_id is None:
            rows = self._conn.execute("SELECT * FROM jobs ORDER BY created_at").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE extractor_id = ? ORDER BY created_at",
                (extractor_id,),
            ).fetchall()
        return [SQLiteJobRow.from_sqlite(row).to_domain() for row in rows]

    def get(self, job_id: str) -> Job | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return SQLiteJobRow.from_sqlite(row).to_domain() if row else None

    def delete(self, job_id: str) -> None:
        with _write_lock:
            self._conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            self._conn.commit()

    def claim_next_queued(self) -> Job | None:
        with _write_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = ?
                    ORDER BY created_at
                    LIMIT 1
                    """,
                    (JobStatus.QUEUED.value,),
                ).fetchone()
                if row is None:
                    self._conn.commit()
                    return None
                job = SQLiteJobRow.from_sqlite(row).to_domain().mark_running()
                updated = SQLiteJobRow.from_domain(job)
                self._conn.execute(
                    """
                    UPDATE jobs
                    SET status = ?, started_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (
                        updated.status,
                        updated.started_at,
                        updated.id,
                        JobStatus.QUEUED.value,
                    ),
                )
                self._conn.commit()
                return job
            except Exception:
                self._conn.rollback()
                raise


@dataclass(frozen=True)
class SQLiteProviderRow:
    name: str
    base_url: str | None
    api_version: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, provider: Provider) -> SQLiteProviderRow:
        return cls(
            name=provider.name.value,
            base_url=provider.base_url,
            api_version=provider.api_version,
            created_at=provider.created_at.isoformat(),
            updated_at=provider.updated_at.isoformat(),
        )

    @classmethod
    def from_sqlite(cls, row: sqlite3.Row) -> SQLiteProviderRow:
        return cls(**dict(row))

    def to_domain(self) -> Provider:
        created_at = _datetime_from_text(self.created_at)
        updated_at = _datetime_from_text(self.updated_at)
        assert created_at is not None
        assert updated_at is not None
        return Provider(
            name=ProviderName(self.name),
            base_url=self.base_url,
            api_version=self.api_version,
            created_at=created_at,
            updated_at=updated_at,
        )


class SQLiteProviderRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, provider: Provider) -> None:
        row = SQLiteProviderRow.from_domain(provider)
        with _write_lock:
            self._conn.execute(
                """
                INSERT INTO providers (name, base_url, api_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    base_url = excluded.base_url,
                    api_version = excluded.api_version,
                    updated_at = excluded.updated_at
                """,
                (row.name, row.base_url, row.api_version, row.created_at, row.updated_at),
            )
            self._conn.commit()

    def list(self) -> List[Provider]:
        rows = self._conn.execute("SELECT * FROM providers ORDER BY name").fetchall()
        return [SQLiteProviderRow.from_sqlite(row).to_domain() for row in rows]

    def get(self, name: ProviderName) -> Provider | None:
        row = self._conn.execute("SELECT * FROM providers WHERE name = ?", (name.value,)).fetchone()
        return SQLiteProviderRow.from_sqlite(row).to_domain() if row else None


class SQLiteSecretStore:
    """Stores provider API keys encrypted at rest, keyed by provider name."""

    def __init__(self, conn: sqlite3.Connection, cipher: SecretCipher) -> None:
        self._conn = conn
        self._cipher = cipher

    def put(self, provider_name: ProviderName, api_key: str) -> None:
        ciphertext = self._cipher.encrypt(api_key)
        now = utc_now().isoformat()
        with _write_lock:
            self._conn.execute(
                """
                INSERT INTO provider_secrets (provider_name, ciphertext, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(provider_name) DO UPDATE SET
                    ciphertext = excluded.ciphertext,
                    updated_at = excluded.updated_at
                """,
                (provider_name.value, ciphertext, now, now),
            )
            self._conn.commit()

    def get(self, provider_name: ProviderName) -> str | None:
        row = self._conn.execute(
            "SELECT ciphertext FROM provider_secrets WHERE provider_name = ?",
            (provider_name.value,),
        ).fetchone()
        return self._cipher.decrypt(row["ciphertext"]) if row else None

    def delete(self, provider_name: ProviderName) -> None:
        with _write_lock:
            self._conn.execute(
                "DELETE FROM provider_secrets WHERE provider_name = ?", (provider_name.value,)
            )
            self._conn.commit()

    def has(self, provider_name: ProviderName) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM provider_secrets WHERE provider_name = ?", (provider_name.value,)
        ).fetchone()
        return row is not None


def dump_debug_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
