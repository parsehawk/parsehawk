from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable, Iterable, List

import pytest

from parsehawk.core.application import services as service_module
from parsehawk.core.application.ports import (
    ExtractionJobRepository,
    ExtractionRequest,
    ExtractionResponse,
    ExtractorRepository,
    FileRepository,
    ParseJobRepository,
    ParserRepository,
    ParsingRequest,
    ParsingResponse,
    PreparedDocument,
    PreparedImage,
    ProviderRepository,
    ResolvedExecutionConfig,
    ResolvedParsingConfig,
    SecretStore,
    UnitOfWork,
)
from parsehawk.core.application.services import (
    DeleteExtractionJobResult,
    DeleteParseJobResult,
    ExtractionJobService,
    ExtractorService,
    FileService,
    ParseJobService,
    ParserService,
    ProviderService,
)
from parsehawk.core.domain.errors import (
    ExtractionCancelled,
    NotFoundError,
    ParsingCancelled,
    PersistenceBusyError,
    ProviderRequestError,
    ValidationFailure,
)
from parsehawk.core.domain.models import (
    ExampleInputKind,
    ExtractionJob,
    ExtractionResult,
    Extractor,
    ExtractorSource,
    File,
    FileSource,
    JobStatus,
    ParseJob,
    Parser,
    ParserOutputFormat,
    ParserSnapshot,
    ParserSource,
    Provider,
    ProviderName,
    ReasoningEffort,
)

DEFAULT_MODEL = "numind/NuExtract3-W4A16"


class MemoryFileRepository:
    def __init__(self) -> None:
        self.items: dict[str, File] = {}

    def save(self, file: File) -> None:
        self.items[file.id] = file

    def list(self) -> List[File]:
        return list(self.items.values())

    def get(self, file_id: str) -> File | None:
        return self.items.get(file_id)

    def delete(self, file_id: str) -> None:
        self.items.pop(file_id, None)


class MemoryExtractorRepository:
    def __init__(self) -> None:
        self.items: dict[str, Extractor] = {}

    def save(self, extractor: Extractor) -> None:
        self.items[extractor.id] = extractor

    def list(self) -> List[Extractor]:
        return list(self.items.values())

    def get(self, extractor_id: str) -> Extractor | None:
        return self.items.get(extractor_id)

    def get_by_name(self, name: str) -> Extractor | None:
        return next((item for item in self.items.values() if item.name == name), None)

    def delete(self, extractor_id: str) -> None:
        self.items.pop(extractor_id, None)


class MemoryParserRepository:
    def __init__(self) -> None:
        self.items: dict[str, Parser] = {}

    def save(self, parser: Parser) -> None:
        self.items[parser.id] = parser

    def list(self) -> List[Parser]:
        return list(self.items.values())

    def get(self, parser_id: str) -> Parser | None:
        return self.items.get(parser_id)

    def get_by_name(self, name: str) -> Parser | None:
        return next((item for item in self.items.values() if item.name == name), None)

    def delete(self, parser_id: str) -> None:
        self.items.pop(parser_id, None)


class MemoryJobRepository:
    def __init__(self) -> None:
        self.items: dict[str, ExtractionJob] = {}

    def save(self, job: ExtractionJob) -> None:
        self.items[job.id] = job

    def save_if_status(self, job: ExtractionJob, expected: Iterable[JobStatus]) -> bool:
        existing = self.items.get(job.id)
        if existing is None or existing.status not in expected:
            return False
        self.items[job.id] = job
        return True

    def list(self, extractor_id: str | None = None) -> List[ExtractionJob]:
        jobs = list(self.items.values())
        if extractor_id is not None:
            jobs = [job for job in jobs if job.extractor_id == extractor_id]
        return jobs

    def get(self, job_id: str) -> ExtractionJob | None:
        return self.items.get(job_id)

    def delete(self, job_id: str) -> None:
        self.items.pop(job_id, None)

    def delete_if_status(self, job_id: str, expected: Iterable[JobStatus]) -> bool:
        existing = self.items.get(job_id)
        if existing is None or existing.status not in expected:
            return False
        self.delete(job_id)
        return True

    def claim_next_queued(self) -> ExtractionJob | None:
        for job in self.items.values():
            if job.status == JobStatus.QUEUED:
                claimed = job.mark_running()
                self.save(claimed)
                return claimed
        return None

    def has_for_file(self, file_id: str) -> bool:
        return any(job.file_id == file_id for job in self.items.values())

    def has_for_extractor(self, extractor_id: str) -> bool:
        return any(job.extractor_id == extractor_id for job in self.items.values())


class MemoryParseJobRepository:
    def __init__(self) -> None:
        self.items: dict[str, ParseJob] = {}

    def save(self, job: ParseJob) -> None:
        self.items[job.id] = job

    def save_if_status(self, job: ParseJob, expected: Iterable[JobStatus]) -> bool:
        existing = self.items.get(job.id)
        if existing is None or existing.status not in expected:
            return False
        self.items[job.id] = job
        return True

    def list(self, parser_id: str | None = None) -> List[ParseJob]:
        jobs = list(self.items.values())
        if parser_id is not None:
            jobs = [job for job in jobs if job.parser_id == parser_id]
        return jobs

    def get(self, job_id: str) -> ParseJob | None:
        return self.items.get(job_id)

    def delete(self, job_id: str) -> None:
        self.items.pop(job_id, None)

    def delete_if_status(self, job_id: str, expected: Iterable[JobStatus]) -> bool:
        existing = self.items.get(job_id)
        if existing is None or existing.status not in expected:
            return False
        self.delete(job_id)
        return True

    def claim_next_queued(self) -> ParseJob | None:
        for job in self.items.values():
            if job.status == JobStatus.QUEUED:
                claimed = job.mark_running()
                self.save(claimed)
                return claimed
        return None

    def has_for_file(self, file_id: str) -> bool:
        return any(job.file_id == file_id for job in self.items.values())

    def has_for_parser(self, parser_id: str) -> bool:
        return any(job.parser_id == parser_id for job in self.items.values())


class RejectingParseJobRepository(MemoryParseJobRepository):
    def __init__(
        self,
        *,
        replacement: ParseJob | None = None,
        rejected_statuses: set[JobStatus] | None = None,
    ) -> None:
        super().__init__()
        self.replacement = replacement
        self.rejected_statuses = rejected_statuses

    def save_if_status(self, job: ParseJob, expected: Iterable[JobStatus]) -> bool:
        if self.rejected_statuses is not None and job.status not in self.rejected_statuses:
            return super().save_if_status(job, expected)
        if self.replacement is not None:
            self.items[job.id] = self.replacement
        return False


class BusyOnceParseJobRepository(MemoryParseJobRepository):
    def __init__(self) -> None:
        super().__init__()
        self.busy_attempts = 0

    def save_if_status(self, job: ParseJob, expected: Iterable[JobStatus]) -> bool:
        if job.status == JobStatus.COMPLETED and self.busy_attempts == 0:
            self.busy_attempts += 1
            raise PersistenceBusyError()
        return super().save_if_status(job, expected)


class MemoryProviderRepository:
    def __init__(self) -> None:
        self.items: dict[ProviderName, Provider] = {}

    def save(self, provider: Provider) -> None:
        self.items[provider.name] = provider

    def list(self) -> List[Provider]:
        return list(self.items.values())

    def get(self, name: ProviderName) -> Provider | None:
        return self.items.get(name)


class MemorySecretStore:
    def __init__(self) -> None:
        self.items: dict[ProviderName, str] = {}

    def put(self, provider_name: ProviderName, api_key: str) -> None:
        self.items[provider_name] = api_key

    def get(self, provider_name: ProviderName) -> str | None:
        return self.items.get(provider_name)

    def delete(self, provider_name: ProviderName) -> None:
        self.items.pop(provider_name, None)

    def has(self, provider_name: ProviderName) -> bool:
        return provider_name in self.items


class MemoryUnitOfWork:
    files: FileRepository
    extractors: ExtractorRepository
    parsers: ParserRepository
    extraction_jobs: ExtractionJobRepository
    parse_jobs: ParseJobRepository
    providers: ProviderRepository
    secrets: SecretStore

    def __init__(
        self,
        files: MemoryFileRepository,
        extractors: MemoryExtractorRepository,
        parsers: MemoryParserRepository,
        jobs: MemoryJobRepository,
        parse_jobs: MemoryParseJobRepository,
        providers: MemoryProviderRepository,
        secrets: MemorySecretStore,
    ) -> None:
        self.files = files
        self.extractors = extractors
        self.parsers = parsers
        self.extraction_jobs = jobs
        self.parse_jobs = parse_jobs
        self.providers = providers
        self.secrets = secrets

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class MemoryUnitOfWorkFactory:
    def __init__(
        self,
        *,
        files: MemoryFileRepository | None = None,
        extractors: MemoryExtractorRepository | None = None,
        parsers: MemoryParserRepository | None = None,
        jobs: MemoryJobRepository | None = None,
        parse_jobs: MemoryParseJobRepository | None = None,
        providers: MemoryProviderRepository | None = None,
        secrets: MemorySecretStore | None = None,
    ) -> None:
        self.files = files or MemoryFileRepository()
        self.extractors = extractors or MemoryExtractorRepository()
        self.parsers = parsers or MemoryParserRepository()
        self.extraction_jobs = jobs or MemoryJobRepository()
        self.parse_jobs = parse_jobs or MemoryParseJobRepository()
        self.providers = providers or MemoryProviderRepository()
        self.secrets = secrets or MemorySecretStore()

    def __call__(self, *, write: bool = False) -> UnitOfWork:
        return MemoryUnitOfWork(
            self.files,
            self.extractors,
            self.parsers,
            self.extraction_jobs,
            self.parse_jobs,
            self.providers,
            self.secrets,
        )


class MemoryStorage:
    def __init__(self) -> None:
        self.contents: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.prepared_document: PreparedDocument | None = None
        self.prepare_error: Exception | None = None

    def write_file(self, file_id: str, file_name: str, content: bytes) -> str:
        path = f"/memory/{file_id}/{file_name}"
        self.contents[path] = content
        return path

    def read_text(self, file: File) -> str:
        return self.contents[file.storage_path].decode()

    def prepare_document(self, file: File) -> PreparedDocument:
        if self.prepare_error is not None:
            raise self.prepare_error
        if self.prepared_document is not None:
            return self.prepared_document
        if file.content_type.startswith("image/"):
            return PreparedDocument(
                text="",
                storage_path=file.storage_path,
                content_type=file.content_type,
                images=[
                    PreparedImage(
                        storage_path=file.storage_path,
                        content_type=file.content_type,
                        page_number=1,
                    )
                ],
            )
        return PreparedDocument(
            text=self.read_text(file),
            storage_path=file.storage_path,
            content_type=file.content_type,
            images=[],
        )

    def delete_file(self, file: File) -> None:
        self.deleted.append(file.id)
        self.contents.pop(file.storage_path, None)


class ControlledJobRepository(MemoryJobRepository):
    def __init__(
        self,
        *,
        status_to_apply: JobStatus | None = None,
        complete_status_to_apply: JobStatus | None = None,
        preserve_canceled: bool = False,
    ) -> None:
        super().__init__()
        self._status_to_apply = status_to_apply
        self._complete_status_to_apply = complete_status_to_apply
        self._preserve_canceled = preserve_canceled

    def save(self, job: ExtractionJob) -> None:
        if self._preserve_canceled and job.status == JobStatus.RUNNING:
            existing = self.items.get(job.id)
            if existing is not None and existing.status == JobStatus.CANCELED:
                return

        if job.status == JobStatus.RUNNING and self._status_to_apply is not None:
            if self._status_to_apply == JobStatus.CANCELING:
                job = job.mark_canceling()
            elif self._status_to_apply == JobStatus.CANCELED:
                job = job.mark_canceled()
            else:
                job = job.model_copy(update={"status": self._status_to_apply})

        if (
            job.status == JobStatus.COMPLETED
            and self._complete_status_to_apply == JobStatus.CANCELING
        ):
            job = job.mark_canceling()

        self.items[job.id] = job

    def save_if_status(self, job: ExtractionJob, expected: Iterable[JobStatus]) -> bool:
        existing = self.items.get(job.id)
        if existing is None or existing.status not in expected:
            return False
        if (
            job.status == JobStatus.COMPLETED
            and self._complete_status_to_apply == JobStatus.CANCELING
        ):
            self.items[job.id] = job.mark_canceling()
            return False
        self.save(job)
        return True


class RejectingJobRepository(MemoryJobRepository):
    def __init__(
        self,
        *,
        replacement: ExtractionJob | None = None,
        rejected_statuses: set[JobStatus] | None = None,
    ) -> None:
        super().__init__()
        self.replacement = replacement
        self.rejected_statuses = rejected_statuses

    def save_if_status(self, job: ExtractionJob, expected: Iterable[JobStatus]) -> bool:
        if self.rejected_statuses is not None and job.status not in self.rejected_statuses:
            return super().save_if_status(job, expected)
        if self.replacement is not None:
            self.items[job.id] = self.replacement
        return False


class RacingDeleteJobRepository(MemoryJobRepository):
    def __init__(self, replacement: ExtractionJob) -> None:
        super().__init__()
        self.replacement: ExtractionJob | None = replacement

    def delete_if_status(self, job_id: str, expected: Iterable[JobStatus]) -> bool:
        if self.replacement is not None:
            self.items[job_id] = self.replacement
            self.replacement = None
            return False
        return super().delete_if_status(job_id, expected)


class BusyOnceCompletingJobRepository(MemoryJobRepository):
    def __init__(self) -> None:
        super().__init__()
        self.busy_attempts = 0

    def save_if_status(self, job: ExtractionJob, expected: Iterable[JobStatus]) -> bool:
        if job.status == JobStatus.COMPLETED and self.busy_attempts == 0:
            self.busy_attempts += 1
            raise PersistenceBusyError()
        return super().save_if_status(job, expected)


@dataclass
class StubEngine:
    response: ExtractionResponse | None = None
    error: Exception | None = None
    requests: list[ExtractionRequest] = field(default_factory=list)
    cancellation_checks: list[object] = field(default_factory=list)

    def extract(
        self,
        request: ExtractionRequest,
        cancellation_check=None,
    ) -> ExtractionResponse:
        self.requests.append(request)
        self.cancellation_checks.append(cancellation_check)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


@dataclass
class StubEngineFactory:
    engine: StubEngine

    def resolve_extractor_config(self, extractor: Extractor) -> ResolvedExecutionConfig:
        return ResolvedExecutionConfig(
            provider_name=extractor.provider_name or ProviderName.OPENAI_COMPATIBLE,
            model=extractor.model or DEFAULT_MODEL,
        )

    def for_extractor(
        self,
        extractor: Extractor,
        *,
        provider: Provider | None = None,
        api_key: str | None = None,
    ) -> StubEngine:
        return self.engine


@dataclass
class StubParsingEngine:
    responses: list[ParsingResponse] = field(default_factory=list)
    error: Exception | None = None
    error_at: int | None = None
    requests: list[ParsingRequest] = field(default_factory=list)
    on_parse: Callable[[Callable[[], bool] | None], None] | None = None

    def parse_page(
        self,
        request: ParsingRequest,
        cancellation_check=None,
    ) -> ParsingResponse:
        self.requests.append(request)
        if self.on_parse is not None:
            self.on_parse(cancellation_check)
        if self.error is not None and (
            self.error_at is None or self.error_at == len(self.requests)
        ):
            raise self.error
        return self.responses[len(self.requests) - 1]


@dataclass
class StubParsingEngineFactory:
    engine: StubParsingEngine
    on_resolve: Callable[[], None] | None = None
    on_for_parser: Callable[[], None] | None = None

    def resolve_parser_config(self, parser: ParserSnapshot) -> ResolvedParsingConfig:
        if self.on_resolve is not None:
            self.on_resolve()
        model = parser.model or DEFAULT_MODEL
        return ResolvedParsingConfig(
            provider_name=parser.provider_name or ProviderName.OPENAI_COMPATIBLE,
            model=model,
            reasoning_effort=parser.reasoning_effort,
            model_adapter=("nuextract_markdown" if model == DEFAULT_MODEL else "generic_markdown"),
        )

    def for_parser(
        self,
        parser: ParserSnapshot,
        *,
        provider: Provider | None = None,
        api_key: str | None = None,
    ) -> StubParsingEngine:
        if self.on_for_parser is not None:
            self.on_for_parser()
        return self.engine


def build_memory_uow(
    files: MemoryFileRepository,
    extractors: MemoryExtractorRepository,
    jobs: MemoryJobRepository,
    *,
    providers: MemoryProviderRepository | None = None,
    secrets: MemorySecretStore | None = None,
) -> MemoryUnitOfWorkFactory:
    return MemoryUnitOfWorkFactory(
        files=files,
        extractors=extractors,
        jobs=jobs,
        providers=providers,
        secrets=secrets,
    )


def build_job_service(
    jobs: MemoryJobRepository,
    files: MemoryFileRepository,
    extractors: MemoryExtractorRepository,
    storage: MemoryStorage,
    engine_factory: StubEngineFactory,
) -> ExtractionJobService:
    return ExtractionJobService(
        build_memory_uow(files, extractors, jobs),
        storage,
        engine_factory,
    )


def build_parse_job_service(
    jobs: MemoryParseJobRepository,
    files: MemoryFileRepository,
    parsers: MemoryParserRepository,
    storage: MemoryStorage,
    engine_factory: StubParsingEngineFactory,
) -> ParseJobService:
    return ParseJobService(
        MemoryUnitOfWorkFactory(files=files, parsers=parsers, parse_jobs=jobs),
        storage,
        engine_factory,
    )


@pytest.fixture
def services():
    files = MemoryFileRepository()
    extractors = MemoryExtractorRepository()
    jobs = MemoryJobRepository()
    storage = MemoryStorage()
    engine = StubEngine(response=ExtractionResponse(data={"receipt_id": "2"}))
    uow = build_memory_uow(files, extractors, jobs)
    return {
        "files": files,
        "extractors": extractors,
        "jobs": jobs,
        "storage": storage,
        "engine": engine,
        "uow": uow,
        "file_service": FileService(uow, storage),
        "extractor_service": ExtractorService(uow, default_model=DEFAULT_MODEL),
        "extraction_job_service": ExtractionJobService(uow, storage, StubEngineFactory(engine)),
    }


def schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "receipt_id": {"anyOf": [{"type": "string", "enum": ["2"]}, {"type": "null"}]}
        },
        "required": ["receipt_id"],
        "additionalProperties": False,
    }


def derived_schema() -> dict:
    return {
        "type": "object",
        "properties": {"receipt_id": {"type": ["string", "null"], "enum": ["2", None]}},
        "required": ["receipt_id"],
        "additionalProperties": False,
    }


def test_file_service_upload_list_get_delete(services) -> None:
    file_service: FileService = services["file_service"]
    storage: MemoryStorage = services["storage"]

    file = file_service.upload(file_name="a.md", content_type="text/markdown", content=b"hello")

    assert file.file_name == "a.md"
    assert file.content_type == "text/markdown"
    assert file.size_bytes == 5
    assert file.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert file_service.list() == [file]
    assert file_service.get(file.id) == file

    file_service.delete(file.id)
    assert storage.deleted == [file.id]
    with pytest.raises(NotFoundError):
        file_service.get(file.id)


def test_file_service_rejects_deleting_example_files(services) -> None:
    file_service: FileService = services["file_service"]
    file = file_service.upload(
        file_name="example.md",
        content_type="text/markdown",
        content=b"hello",
        source=FileSource.EXAMPLE,
        seed_key="example:file:v1",
        seed_version=1,
    )

    with pytest.raises(ValidationFailure, match="example files are read-only"):
        file_service.delete(file.id)

    assert file_service.get(file.id) == file


def test_file_service_keeps_metadata_when_storage_deletion_fails(
    services, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_service: FileService = services["file_service"]
    storage: MemoryStorage = services["storage"]
    file = file_service.upload(
        file_name="retryable.md",
        content_type="text/markdown",
        content=b"hello",
    )

    def fail_delete(_: File) -> None:
        raise PermissionError("storage is read-only")

    monkeypatch.setattr(storage, "delete_file", fail_delete)

    with pytest.raises(PermissionError, match="storage is read-only"):
        file_service.delete(file.id)

    assert file_service.get(file.id) == file
    assert storage.contents[file.storage_path] == b"hello"


def test_parent_resources_cannot_delete_jobs_implicitly(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Receipt #2"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="extract", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)

    with pytest.raises(ValidationFailure, match="file is referenced by jobs"):
        services["file_service"].delete(file.id)
    with pytest.raises(ValidationFailure, match="extractor is referenced by jobs"):
        services["extractor_service"].delete(extractor.id)

    assert services["extraction_job_service"].get(job.id) == job
    assert services["storage"].deleted == []

    assert services["extraction_job_service"].delete(job.id) == DeleteExtractionJobResult.DELETED
    services["file_service"].delete(file.id)
    services["extractor_service"].delete(extractor.id)

    with pytest.raises(NotFoundError):
        services["extraction_job_service"].get(job.id)


def test_file_service_rejects_empty_filename(services) -> None:
    with pytest.raises(ValidationFailure):
        services["file_service"].upload(file_name="", content_type="", content=b"")


def test_file_service_rejects_unsupported_file_type(services) -> None:
    with pytest.raises(ValidationFailure):
        services["file_service"].upload(
            file_name="a.eml", content_type="message/rfc822", content=b""
        )


def test_file_service_removes_written_content_when_persistence_fails(services) -> None:
    def fail_save(file: File) -> None:
        raise RuntimeError("database failed")

    services["files"].save = fail_save

    with pytest.raises(RuntimeError, match="database failed"):
        services["file_service"].upload(
            file_name="a.md", content_type="text/markdown", content=b"hello"
        )

    assert len(services["storage"].deleted) == 1
    assert services["storage"].contents == {}


def test_extractor_service_create_update_list_delete(services) -> None:
    extractor_service: ExtractorService = services["extractor_service"]

    extractor = extractor_service.create(
        name="receipt",
        instructions="classify",
        reasoning_effort=ReasoningEffort.HIGH,
        schema=schema(),
        examples=[{"input": "x", "output": {"receipt_id": "2"}}],
    )

    assert extractor.reasoning_effort is ReasoningEffort.HIGH
    assert extractor.examples[0].output == {"receipt_id": "2"}
    assert extractor.examples[0].input.type == ExampleInputKind.TEXT
    assert extractor.examples[0].input.text == "x"
    assert extractor.schema == derived_schema()
    assert extractor_service.list() == [extractor]
    updated = extractor_service.update(
        extractor.id,
        display_name="Receipt v2",
        instructions="classify better",
        reasoning_effort=None,
        schema=schema(),
        examples=[],
    )
    assert updated.name == "receipt"
    assert updated.display_name == "Receipt v2"
    assert updated.instructions == "classify better"
    assert updated.reasoning_effort is None
    assert updated.schema == derived_schema()
    assert updated.examples == []
    assert updated.updated_at >= extractor.updated_at

    extractor_service.delete(extractor.id)
    with pytest.raises(NotFoundError):
        extractor_service.get(extractor.id)


def test_extractor_service_partial_update_and_invalid_schema(services) -> None:
    extractor_service: ExtractorService = services["extractor_service"]
    extractor = extractor_service.create(name="a", instructions="b", schema=schema())

    updated = extractor_service.update(extractor.id, instructions="new")
    assert updated.name == "a"
    assert updated.display_name == "a"
    assert updated.instructions == "new"
    assert updated.reasoning_effort is None

    updated = extractor_service.update(extractor.id, reasoning_effort=ReasoningEffort.MEDIUM)
    assert updated.reasoning_effort is ReasoningEffort.MEDIUM

    # An update that omits the field leaves the explicit effort untouched …
    updated = extractor_service.update(extractor.id, instructions="newer")
    assert updated.reasoning_effort is ReasoningEffort.MEDIUM

    # … while an explicit None resets to the model's own default.
    updated = extractor_service.update(extractor.id, reasoning_effort=None)
    assert updated.reasoning_effort is None

    with pytest.raises(ValidationFailure):
        extractor_service.create(name="bad", instructions="bad", schema={"type": 1})


def test_extractor_service_creates_generated_names_and_resolves_refs(services) -> None:
    extractor_service: ExtractorService = services["extractor_service"]
    extractor = extractor_service.create(
        display_name="Invoice Extractor",
        instructions="extract",
        schema=schema(),
    )

    assert extractor.name == "invoice-extractor"
    assert extractor.display_name == "Invoice Extractor"
    assert extractor_service.get_by_ref(extractor.name) == extractor
    assert extractor_service.get_by_ref(extractor.id) == extractor


def test_extractor_service_upserts_by_name(services) -> None:
    extractor_service: ExtractorService = services["extractor_service"]

    created = extractor_service.upsert(
        "invoice_v1",
        display_name="Invoice",
        instructions="extract",
        schema=schema(),
    )
    updated = extractor_service.upsert(
        "invoice_v1",
        display_name="Invoice v2",
        instructions="extract better",
        schema=schema(),
    )

    assert updated.id == created.id
    assert updated.name == "invoice_v1"
    assert updated.display_name == "Invoice v2"
    assert updated.instructions == "extract better"

    with pytest.raises(ValidationFailure, match="request body name must match"):
        extractor_service.upsert(
            "invoice_v1",
            body_name="other",
            display_name="Invoice",
            instructions="extract",
            schema=schema(),
        )


def test_extractor_service_rejects_missing_or_blank_display_name(services) -> None:
    extractor_service: ExtractorService = services["extractor_service"]

    with pytest.raises(ValidationFailure, match="display_name is required"):
        extractor_service.create(instructions="i", schema=schema())

    with pytest.raises(ValidationFailure, match="display_name is required"):
        extractor_service.create(display_name=" ", instructions="i", schema=schema())


def test_extractor_service_rejects_invalid_and_duplicate_names(services) -> None:
    extractor_service: ExtractorService = services["extractor_service"]
    extractor_service.create(
        name="receipt", display_name="Receipt", instructions="i", schema=schema()
    )

    with pytest.raises(ValidationFailure, match="extractor name must"):
        extractor_service.create(
            name="Receipt", display_name="Receipt", instructions="i", schema=schema()
        )

    with pytest.raises(ValidationFailure, match="already exists"):
        extractor_service.create(
            name="receipt", display_name="Receipt 2", instructions="i", schema=schema()
        )


def test_extractor_service_suffixes_generated_name_collisions(services) -> None:
    extractor_service: ExtractorService = services["extractor_service"]
    first = extractor_service.create(
        display_name="Invoice Extractor",
        instructions="i",
        schema=schema(),
    )
    second = extractor_service.create(
        display_name="Invoice Extractor",
        instructions="i",
        schema=schema(),
    )

    assert first.name == "invoice-extractor"
    assert second.name.startswith("invoice-extractor-")


def test_extractor_service_rejects_exhausted_generated_name_suffixes(
    services, monkeypatch: pytest.MonkeyPatch
) -> None:
    extractor_service: ExtractorService = services["extractor_service"]
    extractor_service.create(
        display_name="Invoice Extractor",
        instructions="i",
        schema=schema(),
    )
    for suffix_length in (8, 10, 12, 16, 32):
        extractor_service.create(
            name=f"invoice-extractor-{'x' * suffix_length}",
            display_name=f"Blocker {suffix_length}",
            instructions="i",
            schema=schema(),
        )
    monkeypatch.setattr(
        service_module,
        "extractor_name_suffix",
        lambda extractor_id, length=8: "x" * length,
    )

    with pytest.raises(ValidationFailure, match="could not generate a unique extractor name"):
        extractor_service.create(
            display_name="Invoice Extractor",
            instructions="i",
            schema=schema(),
        )


def test_extractor_service_missing_ref_and_upsert_body_name_mismatch(services) -> None:
    extractor_service: ExtractorService = services["extractor_service"]

    with pytest.raises(NotFoundError):
        extractor_service.get_by_ref("missing")

    with pytest.raises(ValidationFailure, match="request body name must match"):
        extractor_service.upsert(
            "invoice_v1",
            body_name="other",
            display_name="Invoice",
            instructions="i",
            schema=schema(),
        )


def test_extractor_service_rejects_prebuilt_update_and_delete(services) -> None:
    extractor_service: ExtractorService = services["extractor_service"]
    extractor = extractor_service.create(
        name="receipt",
        display_name="Receipt",
        instructions="extract",
        schema=schema(),
        source=ExtractorSource.PREBUILT,
        seed_key="prebuilt:receipt:v1",
        seed_version=1,
    )

    with pytest.raises(ValidationFailure, match="prebuilt extractors are read-only"):
        extractor_service.update("receipt", display_name="Receipt copy")
    with pytest.raises(ValidationFailure, match="prebuilt extractors are read-only"):
        extractor_service.delete("receipt")

    assert extractor_service.get(extractor.id) == extractor


def test_extractor_service_rejects_missing_schema(services) -> None:
    with pytest.raises(ValidationFailure):
        services["extractor_service"].create(name="bad", instructions="bad")


def test_extractor_service_accepts_file_examples(services) -> None:
    file = services["file_service"].upload(
        file_name="example.md", content_type="text/markdown", content=b"Example text"
    )

    extractor = services["extractor_service"].create(
        name="receipt",
        instructions="classify",
        schema=schema(),
        examples=[
            {
                "input": {"type": "file", "file_id": file.id},
                "output": '{"receipt_id": "2"}',
            }
        ],
    )

    assert extractor.examples[0].input.type == ExampleInputKind.FILE
    assert extractor.examples[0].input.file_id == file.id
    assert extractor.examples[0].output == '{"receipt_id": "2"}'


def test_extractor_service_rejects_missing_file_examples(services) -> None:
    with pytest.raises(NotFoundError):
        services["extractor_service"].create(
            name="receipt",
            instructions="classify",
            schema=schema(),
            examples=[{"input": {"type": "file", "file_id": "missing"}, "output": {}}],
        )


def test_job_service_create_list_get_delete_and_success(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt",
        instructions="classify",
        reasoning_effort=ReasoningEffort.MEDIUM,
        schema=schema(),
    )

    extraction_job_service: ExtractionJobService = services["extraction_job_service"]
    job = extraction_job_service.create(extractor_id=extractor.id, file_id=file.id)
    assert job.status == JobStatus.QUEUED
    assert extraction_job_service.list(extractor_id=extractor.id) == [job]
    assert extraction_job_service.get(job.id) == job

    completed = extraction_job_service.run_next_queued()
    assert completed is not None
    assert completed.status == JobStatus.COMPLETED
    assert completed.provider_name_used == ProviderName.OPENAI_COMPATIBLE
    assert completed.model_used == DEFAULT_MODEL
    assert completed.result is not None
    assert completed.result.data == {"receipt_id": "2"}
    assert services["engine"].requests[0].source_text == "Subject: #1#"
    assert services["engine"].requests[0].source_storage_path == file.storage_path
    assert services["engine"].requests[0].source_content_type == file.content_type
    assert services["engine"].requests[0].reasoning_effort is ReasoningEffort.MEDIUM

    assert extraction_job_service.delete(job.id) == DeleteExtractionJobResult.DELETED
    with pytest.raises(NotFoundError):
        extraction_job_service.get(job.id)


def test_job_service_records_resolved_provider_and_model_at_execution_time(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)

    services["extractor_service"].update(extractor.id, model="custom/local-model")
    completed = services["extraction_job_service"].run_next_queued()

    assert completed is not None
    assert completed.provider_name_used == ProviderName.OPENAI_COMPATIBLE
    assert completed.model_used == "custom/local-model"
    assert services["extraction_job_service"].get(job.id).model_used == "custom/local-model"


def test_job_service_runs_inline_text_input(services) -> None:
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )

    job = services["extraction_job_service"].create(extractor_id=extractor.id, text="Subject: #1#")
    completed = services["extraction_job_service"].run_claimed(job)

    assert job.file_id is None
    assert job.source_text == "Subject: #1#"
    assert completed.status == JobStatus.COMPLETED
    assert services["engine"].requests[0].source_text == "Subject: #1#"
    assert services["engine"].requests[0].source_storage_path == ""
    assert services["engine"].requests[0].source_content_type == "text/plain"
    assert services["engine"].requests[0].source_images == []


def test_job_service_passes_cancellation_callback_to_engine(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)

    services["extraction_job_service"].run_claimed(job)

    assert services["engine"].cancellation_checks[0] is not None
    assert services["engine"].cancellation_checks[0]() is False


def test_job_service_cancel_marks_queued_job_canceled(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)

    canceled = services["extraction_job_service"].cancel(job.id)

    assert canceled.status == JobStatus.CANCELED
    persisted = services["jobs"].get(job.id)
    assert persisted is not None
    assert persisted.status == JobStatus.CANCELED


def test_job_service_cancel_marks_running_job_canceling(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)

    services["jobs"].save(job.mark_running())

    canceled = services["extraction_job_service"].cancel(job.id)

    assert canceled.status == JobStatus.CANCELING
    persisted = services["jobs"].get(job.id)
    assert persisted is not None
    assert persisted.status == JobStatus.CANCELING


def test_job_service_delete_marks_running_job_deleting(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)
    services["jobs"].save(job.mark_running())

    result = services["extraction_job_service"].delete(job.id)

    assert result == DeleteExtractionJobResult.ACCEPTED
    persisted = services["jobs"].get(job.id)
    assert persisted is not None
    assert persisted.status == JobStatus.DELETING


def test_job_service_delete_marks_canceling_job_deleting(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)
    services["jobs"].save(job.mark_running().mark_canceling())

    result = services["extraction_job_service"].delete(job.id)

    assert result == DeleteExtractionJobResult.ACCEPTED
    persisted = services["jobs"].get(job.id)
    assert persisted is not None
    assert persisted.status == JobStatus.DELETING


def test_job_service_delete_accepts_already_deleting_job(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)
    deleting = job.mark_running().mark_deleting()
    services["jobs"].save(deleting)

    result = services["extraction_job_service"].delete(job.id)

    assert result == DeleteExtractionJobResult.ACCEPTED
    assert services["jobs"].get(job.id) == deleting


def test_job_service_delete_retries_when_queued_delete_loses_race(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)
    running = job.mark_running()
    job_repo = RacingDeleteJobRepository(replacement=running)
    job_repo.save(job)
    extraction_job_service = build_job_service(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )

    result = extraction_job_service.delete(job.id)

    assert result == DeleteExtractionJobResult.ACCEPTED
    persisted = job_repo.get(job.id)
    assert persisted is not None
    assert persisted.status == JobStatus.DELETING


def test_job_service_cancel_rejects_completed_job(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)

    services["jobs"].save(job.model_copy(update={"status": JobStatus.COMPLETED}))

    with pytest.raises(ValidationFailure, match="cannot cancel job"):
        services["extraction_job_service"].cancel(job.id)


def test_job_service_cancel_rechecks_when_status_transition_loses_race(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)
    completed = job.mark_running().mark_completed(ExtractionResult(data={"receipt_id": "2"}))
    job_repo = RejectingJobRepository(replacement=completed)
    job_repo.save(job)
    services["extraction_job_service"] = build_job_service(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )

    with pytest.raises(ValidationFailure, match="cannot cancel job"):
        services["extraction_job_service"].cancel(job.id)


def test_job_service_cancels_when_job_is_already_canceling_before_engine_extract(
    services,
) -> None:
    job_repo = ControlledJobRepository(status_to_apply=JobStatus.CANCELING)
    services["jobs"] = job_repo
    services["extraction_job_service"] = build_job_service(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)

    completed = services["extraction_job_service"].run_claimed(job)

    assert completed.status == JobStatus.CANCELED
    assert completed.result is None
    assert services["engine"].requests == []


def test_job_service_deletes_when_job_is_deleting_before_engine_extract(services) -> None:
    job_repo = ControlledJobRepository(status_to_apply=JobStatus.DELETING)
    services["jobs"] = job_repo
    services["extraction_job_service"] = build_job_service(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)

    result = services["extraction_job_service"].run_claimed(job)

    assert result.status == JobStatus.DELETING
    assert job_repo.get(job.id) is None
    assert services["engine"].requests == []


def test_job_service_returns_latest_when_execution_config_save_loses_race(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)
    running = job.mark_running()
    replacement = running.mark_completed(ExtractionResult(data={"receipt_id": "2"}))
    job_repo = RejectingJobRepository(replacement=replacement)
    job_repo.save(running)
    extraction_job_service = build_job_service(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )

    result = extraction_job_service.run_claimed(running)

    assert result == replacement
    assert services["engine"].requests == []


def test_job_service_cancels_when_job_is_canceling_after_execution_config_save(
    services,
) -> None:
    class CancelingStorage(MemoryStorage):
        job_id: str | None = None

        def prepare_document(self, file: File) -> PreparedDocument:
            if self.job_id is not None:
                latest = services["jobs"].get(self.job_id)
                assert latest is not None
                services["jobs"].save(latest.mark_canceling())
            return super().prepare_document(file)

    storage = CancelingStorage()
    services["storage"] = storage
    storage_uow = build_memory_uow(services["files"], services["extractors"], services["jobs"])
    services["file_service"] = FileService(storage_uow, storage)
    services["extraction_job_service"] = build_job_service(
        services["jobs"],
        services["files"],
        services["extractors"],
        storage,
        StubEngineFactory(services["engine"]),
    )
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)
    storage.job_id = job.id

    result = services["extraction_job_service"].run_claimed(job)

    assert result.status == JobStatus.CANCELED
    assert result.model_used == DEFAULT_MODEL
    assert services["engine"].requests == []


def test_job_service_does_not_overwrite_concurrent_canceling_state(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)
    stale_running = job.mark_running()
    services["jobs"].save(stale_running.mark_canceling())

    completed = services["extraction_job_service"].run_claimed(stale_running)

    assert completed.status == JobStatus.CANCELED
    persisted = services["jobs"].get(job.id)
    assert persisted is not None
    assert persisted.status == JobStatus.CANCELED
    assert services["engine"].requests == []


def test_job_service_returns_latest_when_initial_running_transition_loses_race(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)
    completed = job.mark_running().mark_completed(ExtractionResult(data={"receipt_id": "2"}))
    services["jobs"].save(completed)

    result = services["extraction_job_service"].run_claimed(job)

    assert result == completed
    assert services["engine"].requests == []


def test_job_service_returns_latest_when_final_save_loses_race(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)
    running = job.mark_running()
    failed = running.mark_failed("already failed")
    services["jobs"].save(running)

    def mark_failed(request: ExtractionRequest, cancellation_check=None) -> ExtractionResponse:
        services["jobs"].save(failed)
        return services["engine"].response

    services["engine"].extract = mark_failed

    result = services["extraction_job_service"].run_claimed(running)

    assert result == failed


def test_job_service_cancels_when_final_save_loses_race_to_canceling(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)
    running = job.mark_running()
    canceling = running.mark_canceling()
    job_repo = RejectingJobRepository(
        replacement=canceling,
        rejected_statuses={JobStatus.COMPLETED},
    )
    job_repo.save(running)
    extraction_job_service = build_job_service(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )

    result = extraction_job_service.run_claimed(running)

    assert result.status == JobStatus.CANCELED


def test_job_service_cancels_when_job_becomes_canceling_after_extraction(
    services,
) -> None:
    job_repo = ControlledJobRepository(complete_status_to_apply=JobStatus.CANCELING)

    services["jobs"] = job_repo
    services["extraction_job_service"] = build_job_service(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )

    file = services["file_service"].upload(
        file_name="a.md",
        content_type="text/markdown",
        content=b"Subject: #1#",
    )

    extractor = services["extractor_service"].create(
        name="receipt",
        instructions="classify",
        schema=schema(),
    )

    job = services["extraction_job_service"].create(
        extractor_id=extractor.id,
        file_id=file.id,
    )

    canceled = services["extraction_job_service"].run_claimed(job)

    assert canceled.status == JobStatus.CANCELED
    saved_job = job_repo.get(job.id)
    assert saved_job is not None
    assert saved_job.status == JobStatus.CANCELED


def test_job_service_cancels_when_job_becomes_canceling_before_saving_completed(
    services,
) -> None:
    job_repo = MemoryJobRepository()
    services["jobs"] = job_repo
    services["extraction_job_service"] = build_job_service(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )

    file = services["file_service"].upload(
        file_name="a.md",
        content_type="text/markdown",
        content=b"Subject: #1#",
    )
    extractor = services["extractor_service"].create(
        name="receipt",
        instructions="classify",
        schema=schema(),
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)

    def mark_canceling(request: ExtractionRequest, cancellation_check=None) -> ExtractionResponse:
        latest = job_repo.get(job.id)
        assert latest is not None
        job_repo.save(latest.mark_canceling())
        return services["engine"].response

    services["engine"].extract = mark_canceling

    completed = services["extraction_job_service"].run_claimed(job)

    assert completed.status == JobStatus.CANCELED
    persisted = job_repo.get(job.id)
    assert persisted is not None
    assert persisted.status == JobStatus.CANCELED


def test_job_service_deletes_when_job_becomes_deleting_before_saving_completed(
    services,
) -> None:
    job_repo = MemoryJobRepository()
    services["jobs"] = job_repo
    services["extraction_job_service"] = build_job_service(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )

    file = services["file_service"].upload(
        file_name="a.md",
        content_type="text/markdown",
        content=b"Subject: #1#",
    )
    extractor = services["extractor_service"].create(
        name="receipt",
        instructions="classify",
        schema=schema(),
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)

    def mark_deleting(request: ExtractionRequest, cancellation_check=None) -> ExtractionResponse:
        latest = job_repo.get(job.id)
        assert latest is not None
        job_repo.save(latest.mark_deleting())
        return services["engine"].response

    services["engine"].extract = mark_deleting

    result = services["extraction_job_service"].run_claimed(job)

    assert result.status == JobStatus.DELETING
    assert job_repo.get(job.id) is None


def test_job_service_cancellation_callback_treats_deleting_as_requested(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)

    def mark_deleting(request: ExtractionRequest, cancellation_check=None) -> ExtractionResponse:
        assert cancellation_check is not None
        latest = services["jobs"].get(job.id)
        assert latest is not None
        services["jobs"].save(latest.mark_deleting())
        assert cancellation_check() is True
        return services["engine"].response

    services["engine"].extract = mark_deleting

    result = services["extraction_job_service"].run_claimed(job)

    assert result.status == JobStatus.DELETING
    assert services["jobs"].get(job.id) is None


def test_job_service_cancels_when_engine_raises_cancelled_and_job_is_canceling(
    services,
) -> None:
    job_repo = ControlledJobRepository(status_to_apply=JobStatus.CANCELING)
    services["jobs"] = job_repo
    services["extraction_job_service"] = build_job_service(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )
    services["engine"].error = ExtractionCancelled("cancelled")
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)

    completed = services["extraction_job_service"].run_claimed(job)

    assert completed.status == JobStatus.CANCELED


def test_job_service_cancels_when_canceling_before_extraction_cancelled_handler(
    services,
) -> None:
    job_repo = MemoryJobRepository()
    services["jobs"] = job_repo
    services["extraction_job_service"] = build_job_service(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )
    services["engine"].error = ExtractionCancelled("cancelled")
    file = services["file_service"].upload(
        file_name="a.md",
        content_type="text/markdown",
        content=b"Subject: #1#",
    )
    extractor = services["extractor_service"].create(
        name="receipt",
        instructions="classify",
        schema=schema(),
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)

    def mark_canceling(request: ExtractionRequest, cancellation_check=None) -> ExtractionResponse:
        latest = job_repo.get(job.id)
        assert latest is not None
        job_repo.save(latest.mark_canceling())
        raise services["engine"].error

    services["engine"].extract = mark_canceling

    completed = services["extraction_job_service"].run_claimed(job)

    assert completed.status == JobStatus.CANCELED
    persisted = job_repo.get(job.id)
    assert persisted is not None
    assert persisted.status == JobStatus.CANCELED


def test_job_service_returns_already_canceled_job_when_engine_raises_cancelled(
    services,
) -> None:
    job_repo = ControlledJobRepository(status_to_apply=JobStatus.CANCELED, preserve_canceled=True)
    services["jobs"] = job_repo
    services["extraction_job_service"] = build_job_service(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )
    services["engine"].error = ExtractionCancelled("cancelled")
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)
    canceled_job = job.mark_canceled()
    job_repo.save(canceled_job)

    completed = services["extraction_job_service"].run_claimed(job)

    assert completed == canceled_job
    assert completed.status == JobStatus.CANCELED


def test_job_service_fails_when_engine_raises_cancelled_and_job_is_neither_canceling_nor_canceled(
    services,
) -> None:
    services["engine"].error = ExtractionCancelled("cancelled")
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)

    completed = services["extraction_job_service"].run_claimed(job)

    assert completed.status == JobStatus.FAILED
    assert completed.error is not None
    assert completed.error.message == "cancelled"


def test_job_service_returns_latest_when_cancelled_failure_save_loses_race(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)
    running = job.mark_running()
    failed = running.mark_failed("already failed")
    services["jobs"].save(running)
    services["engine"].error = ExtractionCancelled("cancelled")

    def mark_failed(request: ExtractionRequest, cancellation_check=None) -> ExtractionResponse:
        services["jobs"].save(failed)
        raise services["engine"].error

    services["engine"].extract = mark_failed

    result = services["extraction_job_service"].run_claimed(running)

    assert result == failed


def test_job_service_cancels_when_generic_error_races_with_canceling(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)
    running = job.mark_running()
    services["jobs"].save(running)

    def mark_canceling(request: ExtractionRequest, cancellation_check=None) -> ExtractionResponse:
        services["jobs"].save(running.mark_canceling())
        raise RuntimeError("boom")

    services["engine"].extract = mark_canceling

    result = services["extraction_job_service"].run_claimed(running)

    assert result.status == JobStatus.CANCELED


def test_cancel_if_requested_returns_latest_when_finalize_loses_race(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)
    canceling = job.mark_running().mark_canceling()
    job_repo = RejectingJobRepository(replacement=canceling)
    job_repo.save(canceling)
    extraction_job_service = build_job_service(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )

    result = extraction_job_service._cancel_if_requested(job.id)

    assert result == canceling


def test_job_service_passes_prepared_image_inputs_to_engine(services) -> None:
    file = services["file_service"].upload(
        file_name="receipt.png", content_type="image/png", content=b"fake png"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="extract", schema=schema()
    )

    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)
    completed = services["extraction_job_service"].run_claimed(job)

    assert completed.status == JobStatus.COMPLETED
    assert services["engine"].requests[0].source_text == ""
    assert services["engine"].requests[0].source_images == [
        PreparedImage(
            storage_path=file.storage_path,
            content_type="image/png",
            page_number=1,
        )
    ]


def test_job_service_resolves_file_examples_for_engine(services) -> None:
    example_file = services["file_service"].upload(
        file_name="example.md", content_type="text/markdown", content=b"Example text"
    )
    input_file = services["file_service"].upload(
        file_name="input.md", content_type="text/markdown", content=b"Input text"
    )
    extractor = services["extractor_service"].create(
        name="receipt",
        instructions="classify",
        schema=schema(),
        examples=[
            {"input": {"type": "text", "text": "Text example"}, "output": {"receipt_id": "2"}},
            {"input": {"type": "file", "file_id": example_file.id}, "output": {"receipt_id": "2"}},
        ],
    )
    job = services["extraction_job_service"].create(
        extractor_id=extractor.id, file_id=input_file.id
    )

    completed = services["extraction_job_service"].run_claimed(job)

    assert completed.status == JobStatus.COMPLETED
    assert services["engine"].requests[0].examples == [
        {
            "input": {"type": ExampleInputKind.TEXT, "text": "Text example"},
            "output": {"receipt_id": "2"},
        },
        {
            "input": {
                "type": ExampleInputKind.FILE,
                "file_id": example_file.id,
                "file_name": "example.md",
                "content_type": "text/markdown",
                "storage_path": example_file.storage_path,
                "text": "Example text",
                "images": [],
            },
            "output": {"receipt_id": "2"},
        },
    ]


def test_job_service_fails_when_file_example_is_deleted_before_run(services) -> None:
    example_file = services["file_service"].upload(
        file_name="example.md", content_type="text/markdown", content=b"Example text"
    )
    input_file = services["file_service"].upload(
        file_name="input.md", content_type="text/markdown", content=b"Input text"
    )
    extractor = services["extractor_service"].create(
        name="receipt",
        instructions="classify",
        schema=schema(),
        examples=[
            {"input": {"type": "file", "file_id": example_file.id}, "output": {"receipt_id": "2"}}
        ],
    )
    services["files"].delete(example_file.id)
    job = services["extraction_job_service"].create(
        extractor_id=extractor.id, file_id=input_file.id
    )

    completed = services["extraction_job_service"].run_claimed(job)

    assert completed.status == JobStatus.FAILED
    assert completed.error is not None
    assert "file not found" in completed.error.message


def test_job_service_create_missing_references_and_list_missing_extractor(services) -> None:
    with pytest.raises(NotFoundError):
        services["extraction_job_service"].create(extractor_id="missing", file_id="missing")
    extractor = services["extractor_service"].create(name="e", instructions="i", schema=schema())
    with pytest.raises(NotFoundError):
        services["extraction_job_service"].create(extractor_id=extractor.id, file_id="missing")
    with pytest.raises(ValidationFailure, match="extractor_id or extractor_name"):
        services["extraction_job_service"].create(
            extractor_id=extractor.id, extractor_name=extractor.name
        )
    with pytest.raises(ValidationFailure, match="extractor_id or extractor_name"):
        services["extraction_job_service"].create(file_id="file_1")
    with pytest.raises(ValidationFailure):
        services["extraction_job_service"].create(extractor_id=extractor.id)
    with pytest.raises(ValidationFailure):
        services["extraction_job_service"].create(
            extractor_id=extractor.id, file_id="file_1", text="x"
        )
    with pytest.raises(ValidationFailure):
        services["extraction_job_service"].create(extractor_id=extractor.id, text="  ")
    with pytest.raises(NotFoundError):
        services["extraction_job_service"].list(extractor_id="missing")


def test_job_service_resolves_extractor_name_to_canonical_id(services) -> None:
    extractor = services["extractor_service"].create(
        name="receipt",
        display_name="Receipt",
        instructions="i",
        schema=schema(),
    )
    file = services["file_service"].upload(
        file_name="receipt.md",
        content_type="text/markdown",
        content=b"Receipt #2",
    )

    job = services["extraction_job_service"].create(extractor_name="receipt", file_id=file.id)

    assert job.extractor_id == extractor.id
    assert services["extraction_job_service"].list(extractor_name="receipt") == [job]


def test_job_service_lists_all_and_rejects_ambiguous_filters(services) -> None:
    extractor = services["extractor_service"].create(
        name="receipt", instructions="i", schema=schema()
    )
    file = services["file_service"].upload(
        file_name="receipt.md",
        content_type="text/markdown",
        content=b"Receipt #2",
    )
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)

    assert services["extraction_job_service"].list() == [job]
    with pytest.raises(ValidationFailure, match="only one of extractor_id or extractor_name"):
        services["extraction_job_service"].list(
            extractor_id=extractor.id, extractor_name=extractor.name
        )


def test_job_service_run_next_returns_none_when_no_work(services) -> None:
    assert services["extraction_job_service"].run_next_queued() is None


def test_job_service_schema_failure_keeps_invalid_result(services) -> None:
    services["engine"].response = ExtractionResponse(data={"receipt_id": "not-allowed"})
    file = services["file_service"].upload(file_name="a.md", content_type="", content=b"x")
    extractor = services["extractor_service"].create(name="e", instructions="i", schema=schema())
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)

    completed = services["extraction_job_service"].run_claimed(job)

    assert completed.status == JobStatus.FAILED
    assert completed.error is not None
    assert completed.error.code == "schema_validation_failed"
    assert completed.result is not None
    assert completed.result.valid is False
    assert completed.result.validation_errors[0].path == "receipt_id"


def test_job_service_engine_exception_fails_job(services) -> None:
    services["engine"].error = RuntimeError("model unavailable")
    file = services["file_service"].upload(file_name="a.md", content_type="", content=b"x")
    extractor = services["extractor_service"].create(name="e", instructions="i", schema=schema())
    job = services["extraction_job_service"].create(extractor_id=extractor.id, file_id=file.id)

    completed = services["extraction_job_service"].run_claimed(job)

    assert completed.status == JobStatus.FAILED
    assert completed.error is not None
    assert "model unavailable" in completed.error.message


def test_job_service_retries_final_persistence_without_rerunning_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service_module.time, "sleep", lambda _: None)
    files = MemoryFileRepository()
    extractors = MemoryExtractorRepository()
    jobs = BusyOnceCompletingJobRepository()
    storage = MemoryStorage()
    engine = StubEngine(response=ExtractionResponse(data={"receipt_id": "2"}))
    uow = build_memory_uow(files, extractors, jobs)
    extractor_service = ExtractorService(uow, default_model=DEFAULT_MODEL)
    extraction_job_service = ExtractionJobService(uow, storage, StubEngineFactory(engine))
    extractor = extractor_service.create(name="e", instructions="i", schema=schema())
    extraction_job_service.create(extractor_id=extractor.id, text="receipt 2")

    completed = extraction_job_service.run_next_queued()

    assert completed is not None
    assert completed.status == JobStatus.COMPLETED
    assert jobs.busy_attempts == 1
    assert len(engine.requests) == 1


def test_job_service_missing_resources_during_run_fail_job(services) -> None:
    job = ExtractionJob(
        id="job_1",
        extractor_id="missing",
        file_id="missing",
        status=JobStatus.RUNNING,
    )

    completed = services["extraction_job_service"].run_claimed(job)

    assert completed.status == JobStatus.FAILED
    assert completed.error is not None
    assert "extractor not found" in completed.error.message


def test_job_service_missing_file_during_run_fails_job(services) -> None:
    extractor = services["extractor_service"].create(name="e", instructions="i", schema=schema())
    job = ExtractionJob(
        id="job_1",
        extractor_id=extractor.id,
        file_id="missing",
        status=JobStatus.RUNNING,
    )

    completed = services["extraction_job_service"].run_claimed(job)

    assert completed.status == JobStatus.FAILED
    assert completed.error is not None
    assert "file not found" in completed.error.message


def test_extractor_create_inherits_default_openai_compatible_model(services) -> None:
    extractor = services["extractor_service"].create(name="e", instructions="i", schema=schema())

    assert extractor.provider_name == ProviderName.OPENAI_COMPATIBLE
    assert extractor.model is None


def test_extractor_create_uses_supplied_provider_and_model(services) -> None:
    extractor = services["extractor_service"].create(
        name="e",
        instructions="i",
        schema=schema(),
        provider_name=ProviderName.OPENAI,
        model="gpt-4o-mini",
    )

    assert extractor.provider_name == ProviderName.OPENAI
    assert extractor.model == "gpt-4o-mini"


def test_extractor_create_requires_model_for_cloud_providers(services) -> None:
    with pytest.raises(ValidationFailure, match="model is required for provider openai"):
        services["extractor_service"].create(
            name="e",
            instructions="i",
            schema=schema(),
            provider_name=ProviderName.OPENAI,
        )

    with pytest.raises(ValidationFailure, match="model is required for provider microsoft_foundry"):
        services["extractor_service"].create(
            name="f",
            instructions="i",
            schema=schema(),
            provider_name=ProviderName.MICROSOFT_FOUNDRY,
            model=" ",
        )


def test_extractor_update_changes_provider_and_model(services) -> None:
    extractor = services["extractor_service"].create(name="e", instructions="i", schema=schema())

    updated = services["extractor_service"].update(
        extractor.id, provider_name=ProviderName.MICROSOFT_FOUNDRY, model="my-deployment"
    )

    assert updated.provider_name == ProviderName.MICROSOFT_FOUNDRY
    assert updated.model == "my-deployment"


def test_extractor_update_distinguishes_omitted_model_from_inherited_model(services) -> None:
    extractor = services["extractor_service"].create(
        name="e",
        instructions="i",
        schema=schema(),
        provider_name=ProviderName.OPENAI,
        model="gpt-4o-mini",
    )

    unchanged = services["extractor_service"].update(extractor.id, instructions="updated")
    assert unchanged.model == "gpt-4o-mini"

    inherited = services["extractor_service"].update(
        extractor.id,
        provider_name=ProviderName.OPENAI_COMPATIBLE,
        model=None,
    )
    assert inherited.provider_name == ProviderName.OPENAI_COMPATIBLE
    assert inherited.model is None


def test_extractor_update_rejects_missing_model_when_switching_to_cloud_provider(
    services,
) -> None:
    extractor = services["extractor_service"].create(name="e", instructions="i", schema=schema())

    with pytest.raises(ValidationFailure, match="model is required for provider openai"):
        services["extractor_service"].update(extractor.id, provider_name=ProviderName.OPENAI)


def _provider_service() -> tuple[ProviderService, MemoryProviderRepository, MemorySecretStore]:
    providers = MemoryProviderRepository()
    secrets = MemorySecretStore()
    providers.save(Provider(name=ProviderName.OPENAI))
    providers.save(
        Provider(name=ProviderName.OPENAI_COMPATIBLE, base_url="http://127.0.0.1:8080/v1")
    )
    uow = MemoryUnitOfWorkFactory(providers=providers, secrets=secrets)
    return ProviderService(uow), providers, secrets


def test_provider_service_list_get_and_missing() -> None:
    service, _providers, _secrets = _provider_service()

    assert {provider.name for provider in service.list()} == {
        ProviderName.OPENAI,
        ProviderName.OPENAI_COMPATIBLE,
    }
    assert service.get(ProviderName.OPENAI).name == ProviderName.OPENAI
    assert service.has_api_key(ProviderName.OPENAI) is False
    with pytest.raises(NotFoundError):
        service.get(ProviderName.MICROSOFT_FOUNDRY)


def test_provider_service_configure_base_url_and_api_key() -> None:
    service, _providers, secrets = _provider_service()

    updated = service.configure(
        ProviderName.OPENAI,
        base_url="https://api.openai.com/v1",
        api_key="sk-x",
    )

    assert updated.base_url == "https://api.openai.com/v1"
    assert updated.configuration == {}
    assert secrets.get(ProviderName.OPENAI) == "sk-x"
    assert service.has_api_key(ProviderName.OPENAI) is True
    # Configuring nothing leaves the provider and secret untouched.
    unchanged = service.configure(ProviderName.OPENAI)
    assert unchanged.base_url == "https://api.openai.com/v1"


def test_provider_service_configure_provider_specific_configuration() -> None:
    service, providers, _secrets = _provider_service()
    providers.save(Provider(name=ProviderName.MICROSOFT_FOUNDRY))

    updated = service.configure(
        ProviderName.MICROSOFT_FOUNDRY,
        configuration={
            "project_url": "https://resource.services.ai.azure.com/api/projects/project",
        },
    )

    assert updated.configuration == {
        "project_url": "https://resource.services.ai.azure.com/api/projects/project",
    }
    assert updated.project_url == "https://resource.services.ai.azure.com/api/projects/project"

    with pytest.raises(ValueError):
        service.configure(
            ProviderName.OPENAI, configuration={"project_url": "https://example.test"}
        )


def test_provider_service_configure_reads_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _providers, secrets = _provider_service()
    monkeypatch.setenv("MY_PROVIDER_KEY", "sk-env")

    service.configure(ProviderName.OPENAI, api_key_env="MY_PROVIDER_KEY")

    assert secrets.get(ProviderName.OPENAI) == "sk-env"


def test_provider_service_configure_missing_env_var_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _providers, _secrets = _provider_service()
    monkeypatch.delenv("MISSING_PROVIDER_KEY", raising=False)

    with pytest.raises(ValidationFailure):
        service.configure(ProviderName.OPENAI, api_key_env="MISSING_PROVIDER_KEY")


def _parse_service_bundle(
    engine: StubParsingEngine,
) -> tuple[
    FileService,
    ParserService,
    ParseJobService,
    MemoryStorage,
    MemoryUnitOfWorkFactory,
]:
    storage = MemoryStorage()
    uow = MemoryUnitOfWorkFactory()
    return (
        FileService(uow, storage),
        ParserService(uow, default_model=DEFAULT_MODEL),
        ParseJobService(uow, storage, StubParsingEngineFactory(engine)),
        storage,
        uow,
    )


def test_parser_service_crud_stable_names_and_read_only_prebuilt() -> None:
    _files, service, _jobs, _storage, _uow = _parse_service_bundle(StubParsingEngine())

    parser = service.create(
        display_name="Legal Document Parser",
        instructions="Preserve numbering.",
        reasoning_effort=ReasoningEffort.LOW,
    )
    assert parser.name == "legal-document-parser"
    assert service.get_by_ref(parser.name) == parser
    updated = service.update(
        parser.id,
        display_name="Legal Parser",
        instructions="Preserve numbering and footnotes.",
        reasoning_effort=None,
    )
    assert updated.name == parser.name
    assert updated.reasoning_effort is None

    prebuilt = service.create(
        name="document-to-markdown",
        display_name="Document to Markdown",
        source=ParserSource.PREBUILT,
        seed_key="prebuilt:document-to-markdown:v1",
        seed_version=1,
    )
    with pytest.raises(ValidationFailure, match="read-only"):
        service.update(prebuilt.id, instructions="change")
    with pytest.raises(ValidationFailure, match="read-only"):
        service.delete(prebuilt.id)

    service.delete(parser.name)
    with pytest.raises(NotFoundError):
        service.get_by_ref(parser.id)


def test_parser_service_validation_updates_and_provider_models() -> None:
    _files, service, _jobs, _storage, _uow = _parse_service_bundle(StubParsingEngine())

    with pytest.raises(ValidationFailure, match="display_name is required"):
        service.create()
    with pytest.raises(ValidationFailure, match="display_name is required"):
        service.create(display_name=" ")
    with pytest.raises(ValidationFailure, match="parser name must"):
        service.create(name="Invalid Parser", display_name="Invalid")
    with pytest.raises(ValidationFailure, match="model is required for provider openai"):
        service.create(
            name="hosted",
            display_name="Hosted",
            provider_name=ProviderName.OPENAI,
        )

    named = service.create(name="named-parser")
    assert named.display_name == "named-parser"
    assert named.model is None
    assert named in service.list()
    with pytest.raises(ValidationFailure, match="already exists"):
        service.create(name="named-parser")

    hosted = service.update(
        named.id,
        display_name="Hosted Parser",
        output_format=ParserOutputFormat.MARKDOWN,
        instructions="Preserve footnotes.",
        provider_name=ProviderName.OPENAI,
        model=" gpt-4o ",
    )
    assert hosted.provider_name == ProviderName.OPENAI
    assert hosted.model == "gpt-4o"
    assert hosted.output_format == ParserOutputFormat.MARKDOWN

    inherited = service.update(
        hosted.id,
        provider_name=ProviderName.OPENAI_COMPATIBLE,
        model=None,
    )
    assert inherited.model is None
    with pytest.raises(ValidationFailure, match="model is required for provider openai"):
        service.update(inherited.id, provider_name=ProviderName.OPENAI)


def test_parser_service_upsert_create_replace_and_name_mismatches() -> None:
    _files, service, _jobs, _storage, _uow = _parse_service_bundle(StubParsingEngine())

    with pytest.raises(ValidationFailure, match="request body name must match"):
        service.upsert("legal", body_name="other", display_name="Legal")

    created = service.upsert(
        "legal",
        body_name="legal",
        display_name="Legal",
        instructions="Preserve numbering.",
    )
    replaced = service.upsert(
        created.id,
        body_name="legal",
        display_name="Legal documents",
        output_format=ParserOutputFormat.MARKDOWN,
        instructions="Preserve numbering and footnotes.",
        reasoning_effort=ReasoningEffort.MEDIUM,
        provider_name=ProviderName.OPENAI,
        model="gpt-4o",
    )
    assert replaced.id == created.id
    assert replaced.display_name == "Legal documents"
    assert replaced.provider_name == ProviderName.OPENAI
    assert replaced.reasoning_effort == ReasoningEffort.MEDIUM

    with pytest.raises(ValidationFailure, match="request body name must match"):
        service.upsert(created.id, body_name="other", display_name="Legal")
    with pytest.raises(ValidationFailure, match="display_name is required"):
        service.upsert(created.id, display_name=" ")


def test_parser_service_generated_name_collisions_and_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _files, service, _jobs, _storage, _uow = _parse_service_bundle(StubParsingEngine())
    first = service.create(display_name="Invoice Parser")
    second = service.create(display_name="Invoice Parser")
    assert first.name == "invoice-parser"
    assert second.name.startswith("invoice-parser-")

    service.create(name="blocked", display_name="Blocker")
    for suffix_length in (8, 10, 12, 16, 32):
        service.create(
            name=f"blocked-{'x' * suffix_length}",
            display_name=f"Blocker {suffix_length}",
        )
    monkeypatch.setattr(
        service_module,
        "slugify_parser_name",
        lambda _display_name: "blocked",
    )
    monkeypatch.setattr(
        service_module,
        "parser_name_suffix",
        lambda _parser_id, length=8: "x" * length,
    )
    with pytest.raises(ValidationFailure, match="could not generate a unique parser name"):
        service.create(display_name="Anything")


def test_parse_job_snapshots_parser_and_builds_page_aware_markdown() -> None:
    engine = StubParsingEngine(
        responses=[
            ParsingResponse(content="# First page  "),
            ParsingResponse(content="## Second page"),
        ]
    )
    files, parsers, jobs, storage, _uow = _parse_service_bundle(engine)
    file = files.upload(file_name="document.pdf", content_type="application/pdf", content=b"pdf")
    parser = parsers.create(
        name="legal",
        display_name="Legal",
        instructions="Preserve section numbers.",
    )
    job = jobs.create(parser_name=parser.name, file_id=file.id)
    parsers.update(parser.id, instructions="New instructions must not affect queued jobs.")
    assert job.parser_snapshot.instructions == "Preserve section numbers."

    storage.prepared_document = PreparedDocument(
        text="",
        storage_path=file.storage_path,
        content_type="application/pdf",
        images=[
            PreparedImage(storage_path="page-1.png", content_type="image/png", page_number=1),
            PreparedImage(storage_path="page-2.png", content_type="image/png", page_number=2),
        ],
    )
    completed = jobs.run_next_queued()

    assert completed is not None and completed.status == JobStatus.COMPLETED
    assert completed.result is not None
    assert completed.result.page_count == 2
    assert completed.result.content == "# First page\n\n<!-- page-break -->\n\n## Second page"
    assert [page.page_number for page in completed.result.pages] == [1, 2]
    assert completed.model_adapter_used == "nuextract_markdown"
    assert [request.instructions for request in engine.requests] == [
        "Preserve section numbers.",
        "Preserve section numbers.",
    ]


def test_parse_job_rejects_unsupported_inputs_and_requires_one_parser_selector() -> None:
    engine = StubParsingEngine()
    files, parsers, jobs, _storage, _uow = _parse_service_bundle(engine)
    parser = parsers.create(name="parser", display_name="Parser")
    markdown = files.upload(file_name="notes.md", content_type="text/markdown", content=b"text")

    with pytest.raises(ValidationFailure, match="exactly one"):
        jobs.create(
            parser_id=parser.id,
            parser_name=parser.name,
            file_id=markdown.id,
        )
    with pytest.raises(ValidationFailure, match="PDF, JPG/JPEG, or PNG"):
        jobs.create(parser_id=parser.id, file_id=markdown.id)


def test_parse_job_create_and_list_validate_references_and_filters() -> None:
    engine = StubParsingEngine()
    files, parsers, jobs, _storage, _uow = _parse_service_bundle(engine)
    assert jobs.run_next_queued() is None
    with pytest.raises(NotFoundError, match="parse job not found"):
        jobs.get("missing")
    image = files.upload(file_name="page.png", content_type="image/png", content=b"png")
    parser = parsers.create(name="parser", display_name="Parser")

    with pytest.raises(NotFoundError, match="parser not found"):
        jobs.create(parser_id="missing", file_id=image.id)
    with pytest.raises(NotFoundError, match="file not found"):
        jobs.create(parser_id=parser.id, file_id="missing")

    job = jobs.create(parser_name=parser.name, file_id=image.id)
    assert jobs.list() == [job]
    assert jobs.list(parser_id=parser.id) == [job]
    assert jobs.list(parser_name=parser.name) == [job]
    with pytest.raises(ValidationFailure, match="only one"):
        jobs.list(parser_id=parser.id, parser_name=parser.name)
    with pytest.raises(NotFoundError, match="parser not found"):
        jobs.list(parser_name="missing")


def test_parse_job_cancel_and_delete_active_states() -> None:
    engine = StubParsingEngine()
    files, parsers, jobs, _storage, uow = _parse_service_bundle(engine)
    image = files.upload(file_name="page.png", content_type="image/png", content=b"png")
    parser = parsers.create(name="parser", display_name="Parser")

    running = jobs.create(parser_id=parser.id, file_id=image.id).mark_running()
    uow.parse_jobs.save(running)
    canceling = jobs.cancel(running.id)
    assert canceling.status == JobStatus.CANCELING
    with pytest.raises(ValidationFailure, match="cannot cancel"):
        jobs.cancel(canceling.id)

    assert jobs.delete(canceling.id) == DeleteParseJobResult.ACCEPTED
    deleting = jobs.get(canceling.id)
    assert deleting.status == JobStatus.DELETING
    assert jobs.delete(deleting.id) == DeleteParseJobResult.ACCEPTED


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (
            ProviderRequestError("model rejects image input", status_code=400),
            "model_modality_incompatible",
        ),
        (ProviderRequestError("model provider request timed out"), "parsing_timeout"),
        (ProviderRequestError("model provider is unreachable"), "provider_error"),
    ],
)
def test_parse_job_records_actionable_provider_failure_codes(
    error: Exception,
    expected_code: str,
) -> None:
    engine = StubParsingEngine(error=error)
    files, parsers, jobs, _storage, _uow = _parse_service_bundle(engine)
    file = files.upload(file_name="page.png", content_type="image/png", content=b"png")
    parser = parsers.create(name="parser", display_name="Parser")
    jobs.create(parser_id=parser.id, file_id=file.id)

    failed = jobs.run_next_queued()

    assert failed is not None and failed.status == JobStatus.FAILED
    assert failed.result is None
    assert failed.error is not None and failed.error.code == expected_code


@pytest.mark.parametrize(
    ("engine", "prepare_error", "prepared_document", "expected_code"),
    [
        (
            StubParsingEngine(),
            None,
            PreparedDocument(
                text="",
                storage_path="page.png",
                content_type="image/png",
                images=[],
            ),
            "unsupported_input",
        ),
        (
            StubParsingEngine(responses=[ParsingResponse(content="  ")]),
            None,
            None,
            "invalid_model_output",
        ),
        (
            StubParsingEngine(),
            ValidationFailure("PDF has 30 pages; page limit is 25"),
            None,
            "page_limit_exceeded",
        ),
        (StubParsingEngine(error=TimeoutError("deadline")), None, None, "parsing_timeout"),
        (StubParsingEngine(error=RuntimeError("boom")), None, None, "parsing_failed"),
        (
            StubParsingEngine(error=ParsingCancelled("cancelled")),
            None,
            None,
            "parsing_failed",
        ),
    ],
)
def test_parse_job_maps_execution_failures(
    engine: StubParsingEngine,
    prepare_error: Exception | None,
    prepared_document: PreparedDocument | None,
    expected_code: str,
) -> None:
    files, parsers, jobs, storage, _uow = _parse_service_bundle(engine)
    image = files.upload(file_name="page.png", content_type="image/png", content=b"png")
    parser = parsers.create(name="parser", display_name="Parser")
    storage.prepare_error = prepare_error
    storage.prepared_document = prepared_document
    jobs.create(parser_id=parser.id, file_id=image.id)

    failed = jobs.run_next_queued()

    assert failed is not None and failed.status == JobStatus.FAILED
    assert failed.error is not None and failed.error.code == expected_code


def test_parse_job_fails_whole_job_when_one_page_fails() -> None:
    engine = StubParsingEngine(
        responses=[ParsingResponse(content="page one")],
        error=ProviderRequestError("provider failed"),
        error_at=2,
    )
    files, parsers, jobs, storage, _uow = _parse_service_bundle(engine)
    file = files.upload(file_name="document.pdf", content_type="application/pdf", content=b"pdf")
    parser = parsers.create(name="parser", display_name="Parser")
    jobs.create(parser_id=parser.id, file_id=file.id)
    storage.prepared_document = PreparedDocument(
        text="",
        storage_path=file.storage_path,
        content_type="application/pdf",
        images=[
            PreparedImage(storage_path="one.png", content_type="image/png", page_number=1),
            PreparedImage(storage_path="two.png", content_type="image/png", page_number=2),
        ],
    )

    failed = jobs.run_next_queued()

    assert failed is not None and failed.status == JobStatus.FAILED
    assert failed.result is None
    assert failed.error is not None and failed.error.code == "provider_error"


@pytest.mark.parametrize("replacement_status", [JobStatus.CANCELED, JobStatus.FAILED])
def test_parse_job_handles_initial_running_save_races(replacement_status: JobStatus) -> None:
    engine = StubParsingEngine(responses=[ParsingResponse(content="page")])
    files, parsers, jobs, storage, uow = _parse_service_bundle(engine)
    image = files.upload(file_name="page.png", content_type="image/png", content=b"png")
    parser = parsers.create(name="parser", display_name="Parser")
    job = jobs.create(parser_id=parser.id, file_id=image.id)
    replacement = (
        job.mark_canceled()
        if replacement_status == JobStatus.CANCELED
        else job.mark_running().mark_failed("won race")
    )
    repository = RejectingParseJobRepository(
        replacement=replacement,
        rejected_statuses={JobStatus.RUNNING},
    )
    repository.save(job)
    service = build_parse_job_service(
        repository,
        uow.files,
        uow.parsers,
        storage,
        StubParsingEngineFactory(engine),
    )

    result = service.run_claimed(job)

    assert result.status == replacement_status


@pytest.mark.parametrize("replacement_status", [JobStatus.CANCELED, JobStatus.FAILED])
def test_parse_job_handles_execution_config_save_races(
    replacement_status: JobStatus,
) -> None:
    engine = StubParsingEngine(responses=[ParsingResponse(content="page")])
    files, parsers, jobs, storage, uow = _parse_service_bundle(engine)
    image = files.upload(file_name="page.png", content_type="image/png", content=b"png")
    parser = parsers.create(name="parser", display_name="Parser")
    running = jobs.create(parser_id=parser.id, file_id=image.id).mark_running()
    repository = MemoryParseJobRepository()
    repository.save(running)
    replacement = (
        running.mark_canceled()
        if replacement_status == JobStatus.CANCELED
        else running.mark_failed("won race")
    )
    changed = False

    def replace_during_resolution() -> None:
        nonlocal changed
        if not changed:
            repository.save(replacement)
            changed = True

    service = build_parse_job_service(
        repository,
        uow.files,
        uow.parsers,
        storage,
        StubParsingEngineFactory(engine, on_resolve=replace_during_resolution),
    )

    result = service.run_claimed(running)

    assert result.status == replacement_status


def test_parse_job_cancels_before_first_page_when_state_changes_after_setup() -> None:
    engine = StubParsingEngine(responses=[ParsingResponse(content="page")])
    files, parsers, jobs, storage, uow = _parse_service_bundle(engine)
    image = files.upload(file_name="page.png", content_type="image/png", content=b"png")
    parser = parsers.create(name="parser", display_name="Parser")
    running = jobs.create(parser_id=parser.id, file_id=image.id).mark_running()
    repository = MemoryParseJobRepository()
    repository.save(running)

    def request_cancel() -> None:
        latest = repository.get(running.id)
        assert latest is not None
        repository.save(latest.mark_canceling())

    service = build_parse_job_service(
        repository,
        uow.files,
        uow.parsers,
        storage,
        StubParsingEngineFactory(engine, on_for_parser=request_cancel),
    )

    result = service.run_claimed(running)

    assert result.status == JobStatus.CANCELED
    assert engine.requests == []


def test_parse_job_cancellation_callback_treats_deleting_as_requested() -> None:
    engine = StubParsingEngine(responses=[ParsingResponse(content="page")])
    files, parsers, jobs, storage, uow = _parse_service_bundle(engine)
    image = files.upload(file_name="page.png", content_type="image/png", content=b"png")
    parser = parsers.create(name="parser", display_name="Parser")
    running = jobs.create(parser_id=parser.id, file_id=image.id).mark_running()
    repository = MemoryParseJobRepository()
    repository.save(running)

    def request_delete(cancellation_check: Callable[[], bool] | None) -> None:
        assert cancellation_check is not None
        assert cancellation_check() is False
        latest = repository.get(running.id)
        assert latest is not None
        repository.save(latest.mark_deleting())
        assert cancellation_check() is True

    engine.on_parse = request_delete
    service = build_parse_job_service(
        repository,
        uow.files,
        uow.parsers,
        storage,
        StubParsingEngineFactory(engine),
    )

    result = service.run_claimed(running)

    assert result.status == JobStatus.DELETING
    assert repository.get(running.id) is None


@pytest.mark.parametrize("replacement_status", [JobStatus.CANCELING, JobStatus.FAILED])
def test_parse_job_handles_completed_save_races(replacement_status: JobStatus) -> None:
    engine = StubParsingEngine(responses=[ParsingResponse(content="page")])
    files, parsers, jobs, storage, uow = _parse_service_bundle(engine)
    image = files.upload(file_name="page.png", content_type="image/png", content=b"png")
    parser = parsers.create(name="parser", display_name="Parser")
    running = jobs.create(parser_id=parser.id, file_id=image.id).mark_running()
    replacement = (
        running.mark_canceling()
        if replacement_status == JobStatus.CANCELING
        else running.mark_failed("won race")
    )
    repository = RejectingParseJobRepository(
        replacement=replacement,
        rejected_statuses={JobStatus.COMPLETED},
    )
    repository.save(running)
    service = build_parse_job_service(
        repository,
        uow.files,
        uow.parsers,
        storage,
        StubParsingEngineFactory(engine),
    )

    result = service.run_claimed(running)

    expected = JobStatus.CANCELED if replacement_status == JobStatus.CANCELING else JobStatus.FAILED
    assert result.status == expected


def test_parse_job_cancels_when_parsing_cancelled_races_with_cancel_request() -> None:
    engine = StubParsingEngine(error=ParsingCancelled("cancelled"))
    files, parsers, jobs, storage, uow = _parse_service_bundle(engine)
    image = files.upload(file_name="page.png", content_type="image/png", content=b"png")
    parser = parsers.create(name="parser", display_name="Parser")
    running = jobs.create(parser_id=parser.id, file_id=image.id).mark_running()
    repository = MemoryParseJobRepository()
    repository.save(running)

    def request_cancel(_cancellation_check: Callable[[], bool] | None) -> None:
        latest = repository.get(running.id)
        assert latest is not None
        repository.save(latest.mark_canceling())

    engine.on_parse = request_cancel
    service = build_parse_job_service(
        repository,
        uow.files,
        uow.parsers,
        storage,
        StubParsingEngineFactory(engine),
    )

    result = service.run_claimed(running)

    assert result.status == JobStatus.CANCELED


def test_parse_job_generic_failure_race_honors_cancel_request() -> None:
    engine = StubParsingEngine(error=RuntimeError("boom"))
    files, parsers, jobs, storage, uow = _parse_service_bundle(engine)
    image = files.upload(file_name="page.png", content_type="image/png", content=b"png")
    parser = parsers.create(name="parser", display_name="Parser")
    running = jobs.create(parser_id=parser.id, file_id=image.id).mark_running()
    repository = MemoryParseJobRepository()
    repository.save(running)

    def request_cancel(_cancellation_check: Callable[[], bool] | None) -> None:
        latest = repository.get(running.id)
        assert latest is not None
        repository.save(latest.mark_canceling())

    engine.on_parse = request_cancel
    service = build_parse_job_service(
        repository,
        uow.files,
        uow.parsers,
        storage,
        StubParsingEngineFactory(engine),
    )

    result = service.run_claimed(running)

    assert result.status == JobStatus.CANCELED


def test_parse_job_missing_source_during_execution_records_failure() -> None:
    engine = StubParsingEngine()
    _files, parsers, jobs, storage, uow = _parse_service_bundle(engine)
    parser = parsers.create(name="parser", display_name="Parser")
    running = ParseJob(
        id="parse_job_missing_file",
        parser_id=parser.id,
        file_id="missing",
        parser_snapshot=ParserSnapshot.from_parser(parser),
        status=JobStatus.RUNNING,
    )
    uow.parse_jobs.save(running)

    result = jobs.run_claimed(running)

    assert result.status == JobStatus.FAILED
    assert result.error is not None and "file not found" in result.error.message


def test_parse_job_retries_busy_completion_without_rerunning_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service_module.time, "sleep", lambda _seconds: None)
    engine = StubParsingEngine(responses=[ParsingResponse(content="page")])
    files = MemoryFileRepository()
    parsers_repo = MemoryParserRepository()
    jobs_repo = BusyOnceParseJobRepository()
    storage = MemoryStorage()
    uow = MemoryUnitOfWorkFactory(
        files=files,
        parsers=parsers_repo,
        parse_jobs=jobs_repo,
    )
    files_service = FileService(uow, storage)
    parsers_service = ParserService(uow, default_model=DEFAULT_MODEL)
    jobs_service = ParseJobService(uow, storage, StubParsingEngineFactory(engine))
    image = files_service.upload(
        file_name="page.png",
        content_type="image/png",
        content=b"png",
    )
    parser = parsers_service.create(name="parser", display_name="Parser")
    jobs_service.create(parser_id=parser.id, file_id=image.id)

    completed = jobs_service.run_next_queued()

    assert completed is not None and completed.status == JobStatus.COMPLETED
    assert jobs_repo.busy_attempts == 1
    assert len(engine.requests) == 1


def test_parse_job_private_race_helpers_return_latest_state() -> None:
    engine = StubParsingEngine()
    files, parsers, jobs, storage, uow = _parse_service_bundle(engine)
    image = files.upload(file_name="page.png", content_type="image/png", content=b"png")
    parser = parsers.create(name="parser", display_name="Parser")
    running = jobs.create(parser_id=parser.id, file_id=image.id).mark_running()

    canceling = running.mark_canceling()
    cancel_repo = RejectingParseJobRepository(replacement=canceling)
    cancel_repo.save(canceling)
    cancel_service = build_parse_job_service(
        cancel_repo,
        uow.files,
        uow.parsers,
        storage,
        StubParsingEngineFactory(engine),
    )
    assert cancel_service._cancel_if_requested("missing") is None
    assert cancel_service._cancel_if_requested(running.id) == canceling

    already_failed = running.mark_failed("won race")
    failure_repo = RejectingParseJobRepository(replacement=already_failed)
    failure_repo.save(running)
    failure_service = build_parse_job_service(
        failure_repo,
        uow.files,
        uow.parsers,
        storage,
        StubParsingEngineFactory(engine),
    )
    assert (
        failure_service._record_failure(
            running,
            "lost race",
            check_cancellation=False,
        )
        == already_failed
    )


def test_parse_job_cancel_delete_and_parent_references() -> None:
    engine = StubParsingEngine()
    files, parsers, jobs, _storage, _uow = _parse_service_bundle(engine)
    file = files.upload(file_name="page.jpg", content_type="image/jpeg", content=b"jpg")
    parser = parsers.create(name="parser", display_name="Parser")
    job = jobs.create(parser_id=parser.id, file_id=file.id)

    with pytest.raises(ValidationFailure, match="referenced by jobs"):
        files.delete(file.id)
    with pytest.raises(ValidationFailure, match="referenced by parse jobs"):
        parsers.delete(parser.id)

    canceled = jobs.cancel(job.id)
    assert canceled.status == JobStatus.CANCELED
    assert jobs.delete(job.id) == DeleteParseJobResult.DELETED
    parsers.delete(parser.id)
    files.delete(file.id)
