from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, List, cast

from sqlalchemy import Connection, Engine, create_engine, delete, event, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import URL, RowMapping
from sqlalchemy.exc import DBAPIError

from parsehawk.core.application.ports import (
    ExtractorRepository,
    FileRepository,
    JobRepository,
    ProviderRepository,
    SecretStore,
    UnitOfWork,
)
from parsehawk.core.domain.errors import PersistenceBusyError
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
    ReasoningEffort,
    utc_now,
)
from parsehawk.server.adapters.persistence.migrations import apply_pending
from parsehawk.server.adapters.persistence.tables import (
    extractors as extractors_table,
)
from parsehawk.server.adapters.persistence.tables import files as files_table
from parsehawk.server.adapters.persistence.tables import jobs as jobs_table
from parsehawk.server.adapters.persistence.tables import (
    provider_secrets as provider_secrets_table,
)
from parsehawk.server.adapters.persistence.tables import providers as providers_table
from parsehawk.server.adapters.security import SecretCipher

DEFAULT_BUSY_TIMEOUT_MS = 5_000
_BUSY_MESSAGES = (
    "database is busy",
    "database is locked",
    "database schema is locked",
    "database table is locked",
)


def connect(
    database_path: Path, *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS
) -> sqlite3.Connection:
    """Open a configured raw connection for migrations and maintenance commands."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        database_path,
        check_same_thread=False,
        timeout=busy_timeout_ms / 1_000,
    )
    conn.row_factory = sqlite3.Row
    _configure_dbapi_connection(conn, busy_timeout_ms=busy_timeout_ms)
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def create_sqlite_engine(
    database_path: Path, *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS
) -> Engine:
    """Create the process-lifetime engine used by short-lived Units of Work."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(database_path)),
        connect_args={
            "check_same_thread": False,
            "timeout": busy_timeout_ms / 1_000,
        },
    )

    @event.listens_for(engine, "connect")
    def configure_connection(dbapi_connection: sqlite3.Connection, _: object) -> None:
        _configure_dbapi_connection(dbapi_connection, busy_timeout_ms=busy_timeout_ms)

    raw_connection = engine.raw_connection()
    try:
        dbapi_connection = cast(sqlite3.Connection, raw_connection.driver_connection)
        dbapi_connection.execute("PRAGMA journal_mode = WAL")
    finally:
        raw_connection.close()
    return engine


def _configure_dbapi_connection(conn: sqlite3.Connection, *, busy_timeout_ms: int) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")


def init_db(conn: sqlite3.Connection) -> None:
    """Bring a raw SQLite connection up to the current migrated schema."""
    apply_pending(conn)


def init_engine(engine: Engine) -> None:
    """Apply migrations through one engine-owned DBAPI connection."""
    raw_connection = engine.raw_connection()
    try:
        dbapi_connection = cast(sqlite3.Connection, raw_connection.driver_connection)
        apply_pending(dbapi_connection)
    finally:
        raw_connection.close()


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_json(value: str) -> Any:
    return json.loads(value)


def _datetime_to_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime_from_text(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _is_busy_error(exc: BaseException) -> bool:
    candidate: BaseException = exc
    if isinstance(exc, DBAPIError) and isinstance(exc.orig, BaseException):
        candidate = exc.orig
    return isinstance(candidate, sqlite3.OperationalError) and any(
        message in str(candidate).lower() for message in _BUSY_MESSAGES
    )


def _raise_if_busy(exc: BaseException) -> None:
    if _is_busy_error(exc):
        raise PersistenceBusyError() from exc


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
    def from_mapping(cls, row: RowMapping) -> SQLiteFileRow:
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
    reasoning_effort: str | None
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
            reasoning_effort=extractor.reasoning_effort.value
            if extractor.reasoning_effort
            else None,
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
    def from_mapping(cls, row: RowMapping) -> SQLiteExtractorRow:
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
            reasoning_effort=ReasoningEffort(self.reasoning_effort)
            if self.reasoning_effort
            else None,
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
    provider_name_used: str | None
    model_used: str | None

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
            provider_name_used=job.provider_name_used.value if job.provider_name_used else None,
            model_used=job.model_used,
        )

    @classmethod
    def from_mapping(cls, row: RowMapping) -> SQLiteJobRow:
        return cls(**dict(row))

    def to_domain(self) -> Job:
        created_at = _datetime_from_text(self.created_at)
        assert created_at is not None
        return Job(
            id=self.id,
            extractor_id=self.extractor_id,
            file_id=self.file_id,
            source_text=self.source_text,
            provider_name_used=ProviderName(self.provider_name_used)
            if self.provider_name_used
            else None,
            model_used=self.model_used,
            status=JobStatus(self.status),
            result=JobResult.model_validate(_load_json(self.result)) if self.result else None,
            error=JobError.model_validate(_load_json(self.error)) if self.error else None,
            created_at=created_at,
            started_at=_datetime_from_text(self.started_at),
            completed_at=_datetime_from_text(self.completed_at),
        )


@dataclass(frozen=True)
class SQLiteProviderRow:
    name: str
    base_url: str | None
    created_at: str
    updated_at: str
    configuration: str

    @classmethod
    def from_domain(cls, provider: Provider) -> SQLiteProviderRow:
        return cls(
            name=provider.name.value,
            base_url=provider.base_url,
            created_at=provider.created_at.isoformat(),
            updated_at=provider.updated_at.isoformat(),
            configuration=_dump_json(provider.configuration),
        )

    @classmethod
    def from_mapping(cls, row: RowMapping) -> SQLiteProviderRow:
        return cls(**dict(row))

    def to_domain(self) -> Provider:
        created_at = _datetime_from_text(self.created_at)
        updated_at = _datetime_from_text(self.updated_at)
        assert created_at is not None
        assert updated_at is not None
        return Provider(
            name=ProviderName(self.name),
            base_url=self.base_url,
            configuration=_load_json(self.configuration),
            created_at=created_at,
            updated_at=updated_at,
        )


class SQLiteFileRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def save(self, file: File) -> None:
        values = asdict(SQLiteFileRow.from_domain(file))
        statement = sqlite_insert(files_table).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[files_table.c.id],
            set_={
                column.name: statement.excluded[column.name]
                for column in files_table.c
                if column.name != "id"
            },
        )
        self._connection.execute(statement)

    def list(self) -> List[File]:
        rows = self._connection.execute(select(files_table).order_by(files_table.c.id)).mappings()
        return [SQLiteFileRow.from_mapping(row).to_domain() for row in rows]

    def get(self, file_id: str) -> File | None:
        row = (
            self._connection.execute(select(files_table).where(files_table.c.id == file_id))
            .mappings()
            .first()
        )
        return SQLiteFileRow.from_mapping(row).to_domain() if row else None

    def delete(self, file_id: str) -> None:
        self._connection.execute(delete(files_table).where(files_table.c.id == file_id))


class SQLiteExtractorRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def save(self, extractor: Extractor) -> None:
        values = asdict(SQLiteExtractorRow.from_domain(extractor))
        statement = sqlite_insert(extractors_table).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[extractors_table.c.id],
            set_={
                column.name: statement.excluded[column.name]
                for column in extractors_table.c
                if column.name != "id"
            },
        )
        self._connection.execute(statement)

    def list(self) -> List[Extractor]:
        rows = self._connection.execute(
            select(extractors_table).order_by(extractors_table.c.id)
        ).mappings()
        return [SQLiteExtractorRow.from_mapping(row).to_domain() for row in rows]

    def get(self, extractor_id: str) -> Extractor | None:
        row = (
            self._connection.execute(
                select(extractors_table).where(extractors_table.c.id == extractor_id)
            )
            .mappings()
            .first()
        )
        return SQLiteExtractorRow.from_mapping(row).to_domain() if row else None

    def get_by_name(self, name: str) -> Extractor | None:
        row = (
            self._connection.execute(
                select(extractors_table).where(extractors_table.c.name == name)
            )
            .mappings()
            .first()
        )
        return SQLiteExtractorRow.from_mapping(row).to_domain() if row else None

    def delete(self, extractor_id: str) -> None:
        self._connection.execute(
            delete(extractors_table).where(extractors_table.c.id == extractor_id)
        )


class SQLiteJobRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def save(self, job: Job) -> None:
        values = asdict(SQLiteJobRow.from_domain(job))
        statement = sqlite_insert(jobs_table).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[jobs_table.c.id],
            set_={
                column.name: statement.excluded[column.name]
                for column in jobs_table.c
                if column.name != "id"
            },
        )
        self._connection.execute(statement)

    def save_if_status(self, job: Job, expected: Iterable[JobStatus]) -> bool:
        statuses = tuple(status.value for status in expected)
        if not statuses:
            return False
        values = asdict(SQLiteJobRow.from_domain(job))
        job_id = values.pop("id")
        result = self._connection.execute(
            update(jobs_table)
            .where(jobs_table.c.id == job_id)
            .where(jobs_table.c.status.in_(statuses))
            .values(**values)
        )
        return result.rowcount == 1

    def list(self, extractor_id: str | None = None) -> List[Job]:
        statement = select(jobs_table)
        if extractor_id is not None:
            statement = statement.where(jobs_table.c.extractor_id == extractor_id)
        rows = self._connection.execute(statement.order_by(jobs_table.c.created_at)).mappings()
        return [SQLiteJobRow.from_mapping(row).to_domain() for row in rows]

    def get(self, job_id: str) -> Job | None:
        row = (
            self._connection.execute(select(jobs_table).where(jobs_table.c.id == job_id))
            .mappings()
            .first()
        )
        return SQLiteJobRow.from_mapping(row).to_domain() if row else None

    def delete(self, job_id: str) -> None:
        self._connection.execute(delete(jobs_table).where(jobs_table.c.id == job_id))

    def delete_if_status(self, job_id: str, expected: Iterable[JobStatus]) -> bool:
        statuses = tuple(status.value for status in expected)
        if not statuses:
            return False
        result = self._connection.execute(
            delete(jobs_table)
            .where(jobs_table.c.id == job_id)
            .where(jobs_table.c.status.in_(statuses))
        )
        return result.rowcount == 1

    def claim_next_queued(self) -> Job | None:
        row = (
            self._connection.execute(
                select(jobs_table)
                .where(jobs_table.c.status == JobStatus.QUEUED.value)
                .order_by(jobs_table.c.created_at)
                .limit(1)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        claimed = SQLiteJobRow.from_mapping(row).to_domain().mark_running()
        updated = SQLiteJobRow.from_domain(claimed)
        result = self._connection.execute(
            update(jobs_table)
            .where(jobs_table.c.id == updated.id)
            .where(jobs_table.c.status == JobStatus.QUEUED.value)
            .values(status=updated.status, started_at=updated.started_at)
        )
        return claimed if result.rowcount == 1 else None

    def has_for_file(self, file_id: str) -> bool:
        return (
            self._connection.execute(
                select(jobs_table.c.id).where(jobs_table.c.file_id == file_id).limit(1)
            ).first()
            is not None
        )

    def has_for_extractor(self, extractor_id: str) -> bool:
        return (
            self._connection.execute(
                select(jobs_table.c.id).where(jobs_table.c.extractor_id == extractor_id).limit(1)
            ).first()
            is not None
        )


class SQLiteProviderRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def save(self, provider: Provider) -> None:
        values = asdict(SQLiteProviderRow.from_domain(provider))
        statement = sqlite_insert(providers_table).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[providers_table.c.name],
            set_={
                "base_url": statement.excluded.base_url,
                "configuration": statement.excluded.configuration,
                "updated_at": statement.excluded.updated_at,
            },
        )
        self._connection.execute(statement)

    def list(self) -> List[Provider]:
        rows = self._connection.execute(
            select(providers_table).order_by(providers_table.c.name)
        ).mappings()
        return [SQLiteProviderRow.from_mapping(row).to_domain() for row in rows]

    def get(self, name: ProviderName) -> Provider | None:
        row = (
            self._connection.execute(
                select(providers_table).where(providers_table.c.name == name.value)
            )
            .mappings()
            .first()
        )
        return SQLiteProviderRow.from_mapping(row).to_domain() if row else None


class SQLiteSecretStore:
    """Store provider API keys encrypted at rest, keyed by provider name."""

    def __init__(self, connection: Connection, cipher: SecretCipher) -> None:
        self._connection = connection
        self._cipher = cipher

    def put(self, provider_name: ProviderName, api_key: str) -> None:
        now = utc_now().isoformat()
        statement = sqlite_insert(provider_secrets_table).values(
            provider_name=provider_name.value,
            ciphertext=self._cipher.encrypt(api_key),
            created_at=now,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[provider_secrets_table.c.provider_name],
            set_={
                "ciphertext": statement.excluded.ciphertext,
                "updated_at": statement.excluded.updated_at,
            },
        )
        self._connection.execute(statement)

    def get(self, provider_name: ProviderName) -> str | None:
        row = (
            self._connection.execute(
                select(provider_secrets_table.c.ciphertext).where(
                    provider_secrets_table.c.provider_name == provider_name.value
                )
            )
            .mappings()
            .first()
        )
        return self._cipher.decrypt(row["ciphertext"]) if row else None

    def delete(self, provider_name: ProviderName) -> None:
        self._connection.execute(
            delete(provider_secrets_table).where(
                provider_secrets_table.c.provider_name == provider_name.value
            )
        )

    def has(self, provider_name: ProviderName) -> bool:
        return (
            self._connection.execute(
                select(provider_secrets_table.c.provider_name)
                .where(provider_secrets_table.c.provider_name == provider_name.value)
                .limit(1)
            ).first()
            is not None
        )


class SQLiteUnitOfWork:
    """One SQLAlchemy Core connection and transaction for one application use case."""

    files: FileRepository
    extractors: ExtractorRepository
    jobs: JobRepository
    providers: ProviderRepository
    secrets: SecretStore

    def __init__(self, engine: Engine, cipher: SecretCipher, *, write: bool) -> None:
        self._engine = engine
        self._cipher = cipher
        self._write = write
        self._connection: Connection | None = None

    def __enter__(self) -> SQLiteUnitOfWork:
        self._connection = self._engine.connect()
        try:
            if self._write:
                self._connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                self._connection.begin()
        except BaseException as exc:
            self._connection.close()
            self._connection = None
            _raise_if_busy(exc)
            raise
        self.files = SQLiteFileRepository(self._connection)
        self.extractors = SQLiteExtractorRepository(self._connection)
        self.jobs = SQLiteJobRepository(self._connection)
        self.providers = SQLiteProviderRepository(self._connection)
        self.secrets = SQLiteSecretStore(self._connection, self._cipher)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        connection = self._require_connection()
        cleanup_error: BaseException | None = None
        try:
            if connection.in_transaction():
                connection.rollback()
        except BaseException as rollback_error:
            cleanup_error = rollback_error
        finally:
            connection.close()
            self._connection = None
        if exc is not None:
            _raise_if_busy(exc)
        if cleanup_error is not None:
            _raise_if_busy(cleanup_error)
            raise cleanup_error

    def commit(self) -> None:
        connection = self._require_connection()
        try:
            connection.commit()
        except BaseException as exc:
            if connection.in_transaction():
                connection.rollback()
            _raise_if_busy(exc)
            raise

    def rollback(self) -> None:
        connection = self._require_connection()
        try:
            connection.rollback()
        except BaseException as exc:
            _raise_if_busy(exc)
            raise

    def _require_connection(self) -> Connection:
        if self._connection is None:
            raise RuntimeError("Unit of Work is not active")
        return self._connection


class SQLiteUnitOfWorkFactory:
    def __init__(self, engine: Engine, cipher: SecretCipher) -> None:
        self.engine = engine
        self._cipher = cipher

    def __call__(self, *, write: bool = False) -> UnitOfWork:
        return SQLiteUnitOfWork(self.engine, self._cipher, write=write)

    def close(self) -> None:
        self.engine.dispose()


def dump_debug_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
