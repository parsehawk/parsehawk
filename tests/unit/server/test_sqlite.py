from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import Connection
from sqlalchemy.exc import IntegrityError

from parsehawk.core.domain.errors import PersistenceBusyError
from parsehawk.core.domain.models import (
    Example,
    ExampleInput,
    ExampleInputKind,
    Extractor,
    File,
    Job,
    JobResult,
    JobStatus,
    Provider,
    ProviderName,
    ReasoningEffort,
    ValidationIssue,
)
from parsehawk.server.adapters.persistence.sqlite import (
    SQLiteExtractorRepository,
    SQLiteFileRepository,
    SQLiteJobRepository,
    SQLiteProviderRepository,
    SQLiteSecretStore,
    SQLiteUnitOfWorkFactory,
    connect,
    create_sqlite_engine,
    init_db,
    init_engine,
)
from parsehawk.server.adapters.security import SecretCipher


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "parsehawk.db")
    init_db(connection)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def sa_conn(tmp_path: Path) -> Iterator[Connection]:
    engine = create_sqlite_engine(tmp_path / "parsehawk-core.db")
    init_engine(engine)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.fixture
def uow_factory(tmp_path: Path) -> Iterator[SQLiteUnitOfWorkFactory]:
    engine = create_sqlite_engine(tmp_path / "parsehawk-uow.db")
    init_engine(engine)
    factory = SQLiteUnitOfWorkFactory(engine, SecretCipher(Fernet.generate_key()))
    try:
        yield factory
    finally:
        factory.close()


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
        "display_name",
        "instructions",
        "schema",
        "examples",
        "source",
        "seed_key",
        "seed_version",
        "created_at",
        "updated_at",
        "provider_name",
        "model",
        "reasoning_effort",
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
        "provider_name_used",
        "model_used",
    ]
    assert indexes(conn, "jobs") == {
        "idx_jobs_extractor_id",
        "idx_jobs_status_created_at",
    }
    assert "idx_extractors_name" in indexes(conn, "extractors")
    assert foreign_keys(conn, "jobs") == {
        ("file_id", "files", "id", "RESTRICT"),
        ("extractor_id", "extractors", "id", "RESTRICT"),
    }


def test_repositories_round_trip_domain_models(sa_conn: Connection) -> None:
    files = SQLiteFileRepository(sa_conn)
    extractors = SQLiteExtractorRepository(sa_conn)
    jobs = SQLiteJobRepository(sa_conn)
    file = sample_file()
    extractor = sample_extractor()
    queued = sample_job(file_id=file.id, extractor_id=extractor.id)
    completed = (
        queued.mark_running()
        .with_execution_config(
            provider_name=ProviderName.OPENAI_COMPATIBLE,
            model="numind/NuExtract3-W4A16",
        )
        .mark_completed(
            JobResult(
                data={"receipt_id": "2"},
                validation_errors=[ValidationIssue(path="total", message="missing")],
            )
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
    assert extractors.get_by_name(extractor.name) == extractor
    assert jobs.get(completed.id) == completed
    assert jobs.get(failed.id) == failed
    assert jobs.list(extractor_id=extractor.id) == [completed, failed]


def test_extractor_round_trips_provider_and_model(sa_conn: Connection) -> None:
    extractors = SQLiteExtractorRepository(sa_conn)
    extractor = sample_extractor().model_copy(
        update={"provider_name": ProviderName.OPENAI, "model": "gpt-4o-mini"}
    )

    extractors.save(extractor)

    assert extractors.get(extractor.id) == extractor


def test_provider_repository_round_trip_and_upsert(sa_conn: Connection) -> None:
    providers = SQLiteProviderRepository(sa_conn)
    provider = Provider(
        name=ProviderName.OPENAI_COMPATIBLE,
        base_url="http://127.0.0.1:8080/v1",
        created_at=datetime(2024, 1, 2, tzinfo=UTC),
        updated_at=datetime(2024, 1, 2, tzinfo=UTC),
    )

    providers.save(provider)

    assert providers.get(ProviderName.OPENAI_COMPATIBLE) == provider
    assert providers.list() == [provider]
    assert providers.get(ProviderName.OPENAI) is None

    reconfigured = provider.model_copy(
        update={
            "base_url": "https://proxy.example/v1",
            "updated_at": datetime(2024, 1, 5, tzinfo=UTC),
        }
    )
    providers.save(reconfigured)
    stored = providers.get(ProviderName.OPENAI_COMPATIBLE)
    assert stored is not None
    assert stored.base_url == "https://proxy.example/v1"
    # created_at is preserved across an upsert; only mutable config changes.
    assert stored.created_at == provider.created_at


def test_secret_store_encrypts_and_round_trips(sa_conn: Connection) -> None:
    providers = SQLiteProviderRepository(sa_conn)
    providers.save(Provider(name=ProviderName.OPENAI))  # FK target for the secret
    secrets = SQLiteSecretStore(sa_conn, SecretCipher(Fernet.generate_key()))

    assert secrets.has(ProviderName.OPENAI) is False
    assert secrets.get(ProviderName.OPENAI) is None

    secrets.put(ProviderName.OPENAI, "sk-secret")

    assert secrets.has(ProviderName.OPENAI) is True
    assert secrets.get(ProviderName.OPENAI) == "sk-secret"
    ciphertext = (
        sa_conn.exec_driver_sql(
            "SELECT ciphertext FROM provider_secrets WHERE provider_name = ?", ("openai",)
        )
        .mappings()
        .one()["ciphertext"]
    )
    assert ciphertext != "sk-secret"

    secrets.put(ProviderName.OPENAI, "sk-rotated")  # upsert replaces the ciphertext
    assert secrets.get(ProviderName.OPENAI) == "sk-rotated"

    secrets.delete(ProviderName.OPENAI)
    assert secrets.has(ProviderName.OPENAI) is False


def test_claim_next_queued_marks_oldest_job_running(sa_conn: Connection) -> None:
    files = SQLiteFileRepository(sa_conn)
    extractors = SQLiteExtractorRepository(sa_conn)
    jobs = SQLiteJobRepository(sa_conn)
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


def test_save_if_status_refuses_stale_job_transition(sa_conn: Connection) -> None:
    files = SQLiteFileRepository(sa_conn)
    extractors = SQLiteExtractorRepository(sa_conn)
    jobs = SQLiteJobRepository(sa_conn)
    file = sample_file()
    extractor = sample_extractor()
    running = sample_job(file_id=file.id, extractor_id=extractor.id).mark_running()
    files.save(file)
    extractors.save(extractor)
    jobs.save(running.mark_canceling())

    saved = jobs.save_if_status(
        running.mark_completed(JobResult(data={"receipt_id": "2"})),
        [JobStatus.RUNNING],
    )

    assert saved is False
    stored = jobs.get(running.id)
    assert stored is not None
    assert stored.status == JobStatus.CANCELING


def test_delete_if_status_refuses_stale_job_delete(sa_conn: Connection) -> None:
    files = SQLiteFileRepository(sa_conn)
    extractors = SQLiteExtractorRepository(sa_conn)
    jobs = SQLiteJobRepository(sa_conn)
    file = sample_file()
    extractor = sample_extractor()
    running = sample_job(file_id=file.id, extractor_id=extractor.id).mark_running()
    files.save(file)
    extractors.save(extractor)
    jobs.save(running)

    deleted = jobs.delete_if_status(running.id, [JobStatus.QUEUED])

    assert deleted is False
    assert jobs.get(running.id) == running

    deleted = jobs.delete_if_status(running.id, [JobStatus.RUNNING])

    assert deleted is True
    assert jobs.get(running.id) is None


def test_deleting_referenced_file_or_extractor_is_restricted(sa_conn: Connection) -> None:
    files = SQLiteFileRepository(sa_conn)
    extractors = SQLiteExtractorRepository(sa_conn)
    jobs = SQLiteJobRepository(sa_conn)
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

    with pytest.raises(IntegrityError):
        files.delete(file.id)

    assert jobs.get(file_job.id) == file_job
    assert jobs.get(other_job.id) == other_job
    assert jobs.get(text_job.id) == text_job

    with pytest.raises(IntegrityError):
        extractors.delete(extractor.id)

    assert jobs.get(text_job.id) == text_job


def test_updating_file_or_extractor_preserves_jobs(sa_conn: Connection) -> None:
    files = SQLiteFileRepository(sa_conn)
    extractors = SQLiteExtractorRepository(sa_conn)
    jobs = SQLiteJobRepository(sa_conn)
    file = sample_file()
    extractor = sample_extractor()
    job = sample_job(file_id=file.id, extractor_id=extractor.id)
    files.save(file)
    extractors.save(extractor)
    jobs.save(job)

    files.save(file.model_copy(update={"file_name": "renamed.md"}))
    extractors.save(extractor.model_copy(update={"name": "Updated"}))

    assert jobs.get(job.id) == job


@pytest.mark.concurrency
def test_unit_of_work_isolates_and_rolls_back_uncommitted_writes(
    uow_factory: SQLiteUnitOfWorkFactory,
) -> None:
    provider = Provider(name=ProviderName.OPENAI)

    with uow_factory(write=True) as writer:
        writer.providers.save(provider)
        with uow_factory() as reader:
            assert reader.providers.get(ProviderName.OPENAI) is None

    with uow_factory() as reader:
        assert reader.providers.get(ProviderName.OPENAI) is None

    with uow_factory(write=True) as writer:
        writer.providers.save(provider)
        writer.commit()

    with uow_factory() as reader:
        assert reader.providers.get(ProviderName.OPENAI) == provider


@pytest.mark.concurrency
def test_unit_of_work_translates_exhausted_write_contention(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "busy.db", busy_timeout_ms=25)
    init_engine(engine)
    factory = SQLiteUnitOfWorkFactory(engine, SecretCipher(Fernet.generate_key()))
    try:
        with factory(write=True):
            with pytest.raises(PersistenceBusyError) as error:
                with factory(write=True):
                    pass
        assert error.value.code == "persistence_busy"
        assert error.value.retryable is True
    finally:
        factory.close()


@pytest.mark.concurrency
def test_concurrent_claimers_never_claim_the_same_job(
    uow_factory: SQLiteUnitOfWorkFactory,
) -> None:
    file = sample_file()
    extractor = sample_extractor()
    jobs = [
        sample_job(id=f"job_{index}", file_id=file.id, extractor_id=extractor.id).model_copy(
            update={"created_at": datetime(2024, 1, index + 1, tzinfo=UTC)}
        )
        for index in range(10)
    ]
    with uow_factory(write=True) as uow:
        uow.files.save(file)
        uow.extractors.save(extractor)
        for job in jobs:
            uow.jobs.save(job)
        uow.commit()

    def claim_one() -> str | None:
        with uow_factory(write=True) as uow:
            claimed = uow.jobs.claim_next_queued()
            uow.commit()
            return claimed.id if claimed else None

    with ThreadPoolExecutor(max_workers=5) as executor:
        claimed_ids = list(executor.map(lambda _: claim_one(), range(len(jobs))))

    assert None not in claimed_ids
    assert len(set(claimed_ids)) == len(jobs)
    assert set(claimed_ids) == {job.id for job in jobs}
    assert claim_one() is None


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
    suffix = id.removeprefix("extractor_")
    return Extractor(
        id=id,
        name=f"receipt_{suffix}",
        display_name="Receipt",
        instructions="Extract receipt fields.",
        reasoning_effort=ReasoningEffort.MEDIUM,
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
