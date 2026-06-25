from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

import pytest

from parsehawk.core.domain.models import (
    Example,
    ExampleInput,
    ExampleInputKind,
    Extractor,
    File,
    Job,
    JobResult,
    JobStatus,
    ValidationIssue,
)
from parsehawk.server.adapters.persistence.sqlite import (
    SQLiteExtractorRepository,
    SQLiteFileRepository,
    SQLiteJobRepository,
    connect,
    init_db,
)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "parsehawk.db")
    init_db(connection)
    try:
        yield connection
    finally:
        connection.close()


def test_init_db_creates_structured_tables_indexes_and_foreign_keys(
    conn: sqlite3.Connection,
) -> None:
    assert columns(conn, "files") == [
        "id",
        "file_name",
        "content_type",
        "size_bytes",
        "sha256",
        "storage_path",
        "source",
        "seed_key",
        "seed_version",
        "created_at",
    ]
    assert columns(conn, "extractors") == [
        "id",
        "name",
        "instructions",
        "enable_thinking",
        "schema",
        "examples",
        "source",
        "seed_key",
        "seed_version",
        "created_at",
        "updated_at",
    ]
    assert columns(conn, "jobs") == [
        "id",
        "extractor_id",
        "file_id",
        "source_text",
        "status",
        "result",
        "error",
        "created_at",
        "started_at",
        "completed_at",
    ]
    assert indexes(conn, "jobs") == {
        "idx_jobs_extractor_id",
        "idx_jobs_status_created_at",
    }
    assert foreign_keys(conn, "jobs") == {
        ("file_id", "files", "id", "CASCADE"),
        ("extractor_id", "extractors", "id", "CASCADE"),
    }


def test_repositories_round_trip_domain_models(conn: sqlite3.Connection) -> None:
    files = SQLiteFileRepository(conn)
    extractors = SQLiteExtractorRepository(conn)
    jobs = SQLiteJobRepository(conn)
    file = sample_file()
    extractor = sample_extractor()
    queued = sample_job(file_id=file.id, extractor_id=extractor.id)
    completed = queued.mark_running().mark_completed(
        JobResult(
            data={"receipt_id": "2"},
            validation_errors=[ValidationIssue(path="total", message="missing")],
        )
    )
    failed = sample_job(id="job_failed", file_id=None, extractor_id=extractor.id).mark_failed(
        "model unavailable"
    )

    files.save(file)
    extractors.save(extractor)
    jobs.save(completed)
    jobs.save(failed)

    assert files.get(file.id) == file
    assert extractors.get(extractor.id) == extractor
    assert jobs.get(completed.id) == completed
    assert jobs.get(failed.id) == failed
    assert jobs.list(extractor_id=extractor.id) == [completed, failed]


def test_claim_next_queued_marks_oldest_job_running(conn: sqlite3.Connection) -> None:
    files = SQLiteFileRepository(conn)
    extractors = SQLiteExtractorRepository(conn)
    jobs = SQLiteJobRepository(conn)
    file = sample_file()
    extractor = sample_extractor()
    newest = sample_job(id="job_newest", file_id=file.id, extractor_id=extractor.id)
    oldest = sample_job(id="job_oldest", file_id=file.id, extractor_id=extractor.id).model_copy(
        update={"created_at": datetime(2024, 1, 1, tzinfo=UTC)}
    )
    files.save(file)
    extractors.save(extractor)
    jobs.save(newest)
    jobs.save(oldest)

    claimed = jobs.claim_next_queued()

    assert claimed is not None
    assert claimed.id == oldest.id
    assert claimed.status == JobStatus.RUNNING
    assert jobs.get(oldest.id) == claimed
    assert jobs.get(newest.id) == newest


def test_deleting_file_or_extractor_cascades_jobs(conn: sqlite3.Connection) -> None:
    files = SQLiteFileRepository(conn)
    extractors = SQLiteExtractorRepository(conn)
    jobs = SQLiteJobRepository(conn)
    file = sample_file()
    extractor = sample_extractor()
    other_extractor = sample_extractor(id="extractor_other")
    file_job = sample_job(id="job_file", file_id=file.id, extractor_id=extractor.id)
    text_job = sample_job(id="job_text", file_id=None, extractor_id=extractor.id)
    other_job = sample_job(id="job_other", file_id=file.id, extractor_id=other_extractor.id)
    files.save(file)
    extractors.save(extractor)
    extractors.save(other_extractor)
    jobs.save(file_job)
    jobs.save(text_job)
    jobs.save(other_job)

    files.delete(file.id)

    assert jobs.get(file_job.id) is None
    assert jobs.get(other_job.id) is None
    assert jobs.get(text_job.id) == text_job

    extractors.delete(extractor.id)

    assert jobs.get(text_job.id) is None


def test_updating_file_or_extractor_does_not_cascade_jobs(conn: sqlite3.Connection) -> None:
    files = SQLiteFileRepository(conn)
    extractors = SQLiteExtractorRepository(conn)
    jobs = SQLiteJobRepository(conn)
    file = sample_file()
    extractor = sample_extractor()
    job = sample_job(file_id=file.id, extractor_id=extractor.id)
    files.save(file)
    extractors.save(extractor)
    jobs.save(job)

    files.save(file.model_copy(update={"file_name": "renamed.md"}))
    extractors.save(extractor.model_copy(update={"name": "Updated"}))

    assert jobs.get(job.id) == job


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]


def indexes(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(f"PRAGMA index_list({table})")
        if not str(row["name"]).startswith("sqlite_")
    }


def foreign_keys(conn: sqlite3.Connection, table: str) -> set[tuple[str, str, str, str]]:
    return {
        (row["from"], row["table"], row["to"], row["on_delete"])
        for row in conn.execute(f"PRAGMA foreign_key_list({table})")
    }


def sample_file() -> File:
    return File(
        id="file_1",
        file_name="receipt.md",
        content_type="text/markdown",
        size_bytes=12,
        sha256="abc",
        storage_path="files/file_1/receipt.md",
        created_at=datetime(2024, 1, 2, tzinfo=UTC),
    )


def sample_extractor(id: str = "extractor_1") -> Extractor:
    return Extractor(
        id=id,
        name="Receipt",
        instructions="Extract receipt fields.",
        enable_thinking=True,
        schema={
            "type": "object",
            "properties": {"receipt_id": {"type": "string"}},
            "required": ["receipt_id"],
        },
        examples=[
            Example(
                input=ExampleInput(type=ExampleInputKind.TEXT, text="Receipt #2"),
                output={"receipt_id": "2"},
            )
        ],
        created_at=datetime(2024, 1, 2, tzinfo=UTC),
        updated_at=datetime(2024, 1, 3, tzinfo=UTC),
    )


def sample_job(
    *,
    id: str = "job_1",
    file_id: str | None,
    extractor_id: str,
) -> Job:
    return Job(
        id=id,
        extractor_id=extractor_id,
        file_id=file_id,
        source_text=None if file_id else "Receipt #2",
        status=JobStatus.QUEUED,
        created_at=datetime(2024, 1, 4, tzinfo=UTC),
    )
