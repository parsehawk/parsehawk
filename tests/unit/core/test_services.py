from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable, List

import pytest

from parsehawk.core.application import services as service_module
from parsehawk.core.application.ports import (
    ExtractionRequest,
    ExtractionResponse,
    PreparedDocument,
    PreparedImage,
    ResolvedExecutionConfig,
)
from parsehawk.core.application.services import (
    DeleteJobResult,
    ExtractorService,
    FileService,
    JobService,
    ProviderService,
)
from parsehawk.core.domain.errors import ExtractionCancelled, NotFoundError, ValidationFailure
from parsehawk.core.domain.models import (
    ExampleInputKind,
    Extractor,
    ExtractorSource,
    File,
    FileSource,
    Job,
    JobResult,
    JobStatus,
    Provider,
    ProviderName,
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


class MemoryJobRepository:
    def __init__(self) -> None:
        self.items: dict[str, Job] = {}

    def save(self, job: Job) -> None:
        self.items[job.id] = job

    def save_if_status(self, job: Job, expected: Iterable[JobStatus]) -> bool:
        existing = self.items.get(job.id)
        if existing is None or existing.status not in expected:
            return False
        self.items[job.id] = job
        return True

    def list(self, extractor_id: str | None = None) -> List[Job]:
        jobs = list(self.items.values())
        if extractor_id is not None:
            jobs = [job for job in jobs if job.extractor_id == extractor_id]
        return jobs

    def get(self, job_id: str) -> Job | None:
        return self.items.get(job_id)

    def delete(self, job_id: str) -> None:
        self.items.pop(job_id, None)

    def delete_if_status(self, job_id: str, expected: Iterable[JobStatus]) -> bool:
        existing = self.items.get(job_id)
        if existing is None or existing.status not in expected:
            return False
        self.delete(job_id)
        return True

    def claim_next_queued(self) -> Job | None:
        for job in self.items.values():
            if job.status == JobStatus.QUEUED:
                claimed = job.mark_running()
                self.save(claimed)
                return claimed
        return None


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


class MemoryStorage:
    def __init__(self) -> None:
        self.contents: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def write_file(self, file_id: str, file_name: str, content: bytes) -> str:
        path = f"/memory/{file_id}/{file_name}"
        self.contents[path] = content
        return path

    def read_text(self, file: File) -> str:
        return self.contents[file.storage_path].decode()

    def prepare_document(self, file: File) -> PreparedDocument:
        if file.content_type.startswith("image/"):
            return PreparedDocument(
                text="",
                storage_path=file.storage_path,
                content_type=file.content_type,
                images=[
                    PreparedImage(storage_path=file.storage_path, content_type=file.content_type)
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

    def save(self, job: Job) -> None:
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

    def save_if_status(self, job: Job, expected: Iterable[JobStatus]) -> bool:
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
        replacement: Job | None = None,
        rejected_statuses: set[JobStatus] | None = None,
    ) -> None:
        super().__init__()
        self.replacement = replacement
        self.rejected_statuses = rejected_statuses

    def save_if_status(self, job: Job, expected: Iterable[JobStatus]) -> bool:
        if self.rejected_statuses is not None and job.status not in self.rejected_statuses:
            return super().save_if_status(job, expected)
        if self.replacement is not None:
            self.items[job.id] = self.replacement
        return False


class RacingDeleteJobRepository(MemoryJobRepository):
    def __init__(self, replacement: Job) -> None:
        super().__init__()
        self.replacement: Job | None = replacement

    def delete_if_status(self, job_id: str, expected: Iterable[JobStatus]) -> bool:
        if self.replacement is not None:
            self.items[job_id] = self.replacement
            self.replacement = None
            return False
        return super().delete_if_status(job_id, expected)


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

    def for_extractor(self, extractor: Extractor) -> StubEngine:
        return self.engine


@pytest.fixture
def services():
    files = MemoryFileRepository()
    extractors = MemoryExtractorRepository()
    jobs = MemoryJobRepository()
    storage = MemoryStorage()
    engine = StubEngine(response=ExtractionResponse(data={"receipt_id": "2"}))
    return {
        "files": files,
        "extractors": extractors,
        "jobs": jobs,
        "storage": storage,
        "engine": engine,
        "file_service": FileService(files, storage),
        "extractor_service": ExtractorService(extractors, files, default_model=DEFAULT_MODEL),
        "job_service": JobService(jobs, files, extractors, storage, StubEngineFactory(engine)),
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


def test_file_service_rejects_empty_filename(services) -> None:
    with pytest.raises(ValidationFailure):
        services["file_service"].upload(file_name="", content_type="", content=b"")


def test_file_service_rejects_unsupported_file_type(services) -> None:
    with pytest.raises(ValidationFailure):
        services["file_service"].upload(
            file_name="a.eml", content_type="message/rfc822", content=b""
        )


def test_extractor_service_create_update_list_delete(services) -> None:
    extractor_service: ExtractorService = services["extractor_service"]

    extractor = extractor_service.create(
        name="receipt",
        instructions="classify",
        enable_thinking=True,
        schema=schema(),
        examples=[{"input": "x", "output": {"receipt_id": "2"}}],
    )

    assert extractor.enable_thinking is True
    assert extractor.examples[0].output == {"receipt_id": "2"}
    assert extractor.examples[0].input.type == ExampleInputKind.TEXT
    assert extractor.examples[0].input.text == "x"
    assert extractor.schema == derived_schema()
    assert extractor_service.list() == [extractor]
    updated = extractor_service.update(
        extractor.id,
        display_name="Receipt v2",
        instructions="classify better",
        enable_thinking=False,
        schema=schema(),
        examples=[],
    )
    assert updated.name == "receipt"
    assert updated.display_name == "Receipt v2"
    assert updated.instructions == "classify better"
    assert updated.enable_thinking is False
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
    assert updated.enable_thinking is False

    updated = extractor_service.update(extractor.id, enable_thinking=True)
    assert updated.enable_thinking is True

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
        name="receipt", instructions="classify", enable_thinking=True, schema=schema()
    )

    job_service: JobService = services["job_service"]
    job = job_service.create(extractor_id=extractor.id, file_id=file.id)
    assert job.status == JobStatus.QUEUED
    assert job_service.list(extractor_id=extractor.id) == [job]
    assert job_service.get(job.id) == job

    completed = job_service.run_next_queued()
    assert completed is not None
    assert completed.status == JobStatus.COMPLETED
    assert completed.provider_name_used == ProviderName.OPENAI_COMPATIBLE
    assert completed.model_used == DEFAULT_MODEL
    assert completed.result is not None
    assert completed.result.data == {"receipt_id": "2"}
    assert services["engine"].requests[0].source_text == "Subject: #1#"
    assert services["engine"].requests[0].source_storage_path == file.storage_path
    assert services["engine"].requests[0].source_content_type == file.content_type
    assert services["engine"].requests[0].enable_thinking is True

    assert job_service.delete(job.id) == DeleteJobResult.DELETED
    with pytest.raises(NotFoundError):
        job_service.get(job.id)


def test_job_service_records_resolved_provider_and_model_at_execution_time(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)

    services["extractor_service"].update(extractor.id, model="custom/local-model")
    completed = services["job_service"].run_next_queued()

    assert completed is not None
    assert completed.provider_name_used == ProviderName.OPENAI_COMPATIBLE
    assert completed.model_used == "custom/local-model"
    assert services["job_service"].get(job.id).model_used == "custom/local-model"


def test_job_service_runs_inline_text_input(services) -> None:
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )

    job = services["job_service"].create(extractor_id=extractor.id, text="Subject: #1#")
    completed = services["job_service"].run_claimed(job)

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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)

    services["job_service"].run_claimed(job)

    assert services["engine"].cancellation_checks[0] is not None
    assert services["engine"].cancellation_checks[0]() is False


def test_job_service_cancel_marks_queued_job_canceled(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)

    canceled = services["job_service"].cancel(job.id)

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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)

    services["jobs"].save(job.mark_running())

    canceled = services["job_service"].cancel(job.id)

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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)
    services["jobs"].save(job.mark_running())

    result = services["job_service"].delete(job.id)

    assert result == DeleteJobResult.ACCEPTED
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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)
    services["jobs"].save(job.mark_running().mark_canceling())

    result = services["job_service"].delete(job.id)

    assert result == DeleteJobResult.ACCEPTED
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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)
    deleting = job.mark_running().mark_deleting()
    services["jobs"].save(deleting)

    result = services["job_service"].delete(job.id)

    assert result == DeleteJobResult.ACCEPTED
    assert services["jobs"].get(job.id) == deleting


def test_job_service_delete_retries_when_queued_delete_loses_race(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)
    running = job.mark_running()
    job_repo = RacingDeleteJobRepository(replacement=running)
    job_repo.save(job)
    job_service = JobService(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )

    result = job_service.delete(job.id)

    assert result == DeleteJobResult.ACCEPTED
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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)

    services["jobs"].save(job.model_copy(update={"status": JobStatus.COMPLETED}))

    with pytest.raises(ValidationFailure, match="cannot cancel job"):
        services["job_service"].cancel(job.id)


def test_job_service_cancel_rechecks_when_status_transition_loses_race(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)
    completed = job.mark_running().mark_completed(JobResult(data={"receipt_id": "2"}))
    job_repo = RejectingJobRepository(replacement=completed)
    job_repo.save(job)
    services["job_service"] = JobService(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )

    with pytest.raises(ValidationFailure, match="cannot cancel job"):
        services["job_service"].cancel(job.id)


def test_job_service_cancels_when_job_is_already_canceling_before_engine_extract(
    services,
) -> None:
    job_repo = ControlledJobRepository(status_to_apply=JobStatus.CANCELING)
    services["jobs"] = job_repo
    services["job_service"] = JobService(
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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)

    completed = services["job_service"].run_claimed(job)

    assert completed.status == JobStatus.CANCELED
    assert completed.result is None
    assert services["engine"].requests == []


def test_job_service_deletes_when_job_is_deleting_before_engine_extract(services) -> None:
    job_repo = ControlledJobRepository(status_to_apply=JobStatus.DELETING)
    services["jobs"] = job_repo
    services["job_service"] = JobService(
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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)

    result = services["job_service"].run_claimed(job)

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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)
    running = job.mark_running()
    replacement = running.mark_completed(JobResult(data={"receipt_id": "2"}))
    job_repo = RejectingJobRepository(replacement=replacement)
    job_repo.save(running)
    job_service = JobService(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )

    result = job_service.run_claimed(running)

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
    services["file_service"] = FileService(services["files"], storage)
    services["job_service"] = JobService(
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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)
    storage.job_id = job.id

    result = services["job_service"].run_claimed(job)

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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)
    stale_running = job.mark_running()
    services["jobs"].save(stale_running.mark_canceling())

    completed = services["job_service"].run_claimed(stale_running)

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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)
    completed = job.mark_running().mark_completed(JobResult(data={"receipt_id": "2"}))
    services["jobs"].save(completed)

    result = services["job_service"].run_claimed(job)

    assert result == completed
    assert services["engine"].requests == []


def test_job_service_returns_latest_when_final_save_loses_race(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)
    running = job.mark_running()
    failed = running.mark_failed("already failed")
    services["jobs"].save(running)

    def mark_failed(request: ExtractionRequest, cancellation_check=None) -> ExtractionResponse:
        services["jobs"].save(failed)
        return services["engine"].response

    services["engine"].extract = mark_failed

    result = services["job_service"].run_claimed(running)

    assert result == failed


def test_job_service_cancels_when_final_save_loses_race_to_canceling(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)
    running = job.mark_running()
    canceling = running.mark_canceling()
    job_repo = RejectingJobRepository(
        replacement=canceling,
        rejected_statuses={JobStatus.COMPLETED},
    )
    job_repo.save(running)
    job_service = JobService(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )

    result = job_service.run_claimed(running)

    assert result.status == JobStatus.CANCELED


def test_job_service_cancels_when_job_becomes_canceling_after_extraction(
    services,
) -> None:
    job_repo = ControlledJobRepository(complete_status_to_apply=JobStatus.CANCELING)

    services["jobs"] = job_repo
    services["job_service"] = JobService(
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

    job = services["job_service"].create(
        extractor_id=extractor.id,
        file_id=file.id,
    )

    canceled = services["job_service"].run_claimed(job)

    assert canceled.status == JobStatus.CANCELED
    saved_job = job_repo.get(job.id)
    assert saved_job is not None
    assert saved_job.status == JobStatus.CANCELED


def test_job_service_cancels_when_job_becomes_canceling_before_saving_completed(
    services,
) -> None:
    job_repo = MemoryJobRepository()
    services["jobs"] = job_repo
    services["job_service"] = JobService(
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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)

    def mark_canceling(request: ExtractionRequest, cancellation_check=None) -> ExtractionResponse:
        latest = job_repo.get(job.id)
        assert latest is not None
        job_repo.save(latest.mark_canceling())
        return services["engine"].response

    services["engine"].extract = mark_canceling

    completed = services["job_service"].run_claimed(job)

    assert completed.status == JobStatus.CANCELED
    persisted = job_repo.get(job.id)
    assert persisted is not None
    assert persisted.status == JobStatus.CANCELED


def test_job_service_deletes_when_job_becomes_deleting_before_saving_completed(
    services,
) -> None:
    job_repo = MemoryJobRepository()
    services["jobs"] = job_repo
    services["job_service"] = JobService(
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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)

    def mark_deleting(request: ExtractionRequest, cancellation_check=None) -> ExtractionResponse:
        latest = job_repo.get(job.id)
        assert latest is not None
        job_repo.save(latest.mark_deleting())
        return services["engine"].response

    services["engine"].extract = mark_deleting

    result = services["job_service"].run_claimed(job)

    assert result.status == JobStatus.DELETING
    assert job_repo.get(job.id) is None


def test_job_service_cancellation_callback_treats_deleting_as_requested(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)

    def mark_deleting(request: ExtractionRequest, cancellation_check=None) -> ExtractionResponse:
        assert cancellation_check is not None
        latest = services["jobs"].get(job.id)
        assert latest is not None
        services["jobs"].save(latest.mark_deleting())
        assert cancellation_check() is True
        return services["engine"].response

    services["engine"].extract = mark_deleting

    result = services["job_service"].run_claimed(job)

    assert result.status == JobStatus.DELETING
    assert services["jobs"].get(job.id) is None


def test_job_service_cancels_when_engine_raises_cancelled_and_job_is_canceling(
    services,
) -> None:
    job_repo = ControlledJobRepository(status_to_apply=JobStatus.CANCELING)
    services["jobs"] = job_repo
    services["job_service"] = JobService(
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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)

    completed = services["job_service"].run_claimed(job)

    assert completed.status == JobStatus.CANCELED


def test_job_service_cancels_when_canceling_before_extraction_cancelled_handler(
    services,
) -> None:
    job_repo = MemoryJobRepository()
    services["jobs"] = job_repo
    services["job_service"] = JobService(
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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)

    def mark_canceling(request: ExtractionRequest, cancellation_check=None) -> ExtractionResponse:
        latest = job_repo.get(job.id)
        assert latest is not None
        job_repo.save(latest.mark_canceling())
        raise services["engine"].error

    services["engine"].extract = mark_canceling

    completed = services["job_service"].run_claimed(job)

    assert completed.status == JobStatus.CANCELED
    persisted = job_repo.get(job.id)
    assert persisted is not None
    assert persisted.status == JobStatus.CANCELED


def test_job_service_returns_already_canceled_job_when_engine_raises_cancelled(
    services,
) -> None:
    job_repo = ControlledJobRepository(status_to_apply=JobStatus.CANCELED, preserve_canceled=True)
    services["jobs"] = job_repo
    services["job_service"] = JobService(
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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)
    canceled_job = job.mark_canceled()
    job_repo.save(canceled_job)

    completed = services["job_service"].run_claimed(job)

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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)

    completed = services["job_service"].run_claimed(job)

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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)
    running = job.mark_running()
    failed = running.mark_failed("already failed")
    services["jobs"].save(running)
    services["engine"].error = ExtractionCancelled("cancelled")

    def mark_failed(request: ExtractionRequest, cancellation_check=None) -> ExtractionResponse:
        services["jobs"].save(failed)
        raise services["engine"].error

    services["engine"].extract = mark_failed

    result = services["job_service"].run_claimed(running)

    assert result == failed


def test_job_service_cancels_when_generic_error_races_with_canceling(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)
    running = job.mark_running()
    services["jobs"].save(running)

    def mark_canceling(request: ExtractionRequest, cancellation_check=None) -> ExtractionResponse:
        services["jobs"].save(running.mark_canceling())
        raise RuntimeError("boom")

    services["engine"].extract = mark_canceling

    result = services["job_service"].run_claimed(running)

    assert result.status == JobStatus.CANCELED


def test_cancel_if_requested_returns_latest_when_finalize_loses_race(services) -> None:
    file = services["file_service"].upload(
        file_name="a.md", content_type="text/markdown", content=b"Subject: #1#"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="classify", schema=schema()
    )
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)
    canceling = job.mark_running().mark_canceling()
    job_repo = RejectingJobRepository(replacement=canceling)
    job_repo.save(canceling)
    job_service = JobService(
        job_repo,
        services["files"],
        services["extractors"],
        services["storage"],
        StubEngineFactory(services["engine"]),
    )

    result = job_service._cancel_if_requested(job.id)

    assert result == canceling


def test_job_service_passes_prepared_image_inputs_to_engine(services) -> None:
    file = services["file_service"].upload(
        file_name="receipt.png", content_type="image/png", content=b"fake png"
    )
    extractor = services["extractor_service"].create(
        name="receipt", instructions="extract", schema=schema()
    )

    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)
    completed = services["job_service"].run_claimed(job)

    assert completed.status == JobStatus.COMPLETED
    assert services["engine"].requests[0].source_text == ""
    assert services["engine"].requests[0].source_images == [
        PreparedImage(storage_path=file.storage_path, content_type="image/png")
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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=input_file.id)

    completed = services["job_service"].run_claimed(job)

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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=input_file.id)

    completed = services["job_service"].run_claimed(job)

    assert completed.status == JobStatus.FAILED
    assert completed.error is not None
    assert "file not found" in completed.error.message


def test_job_service_create_missing_references_and_list_missing_extractor(services) -> None:
    with pytest.raises(NotFoundError):
        services["job_service"].create(extractor_id="missing", file_id="missing")
    extractor = services["extractor_service"].create(name="e", instructions="i", schema=schema())
    with pytest.raises(NotFoundError):
        services["job_service"].create(extractor_id=extractor.id, file_id="missing")
    with pytest.raises(ValidationFailure, match="extractor_id or extractor_name"):
        services["job_service"].create(extractor_id=extractor.id, extractor_name=extractor.name)
    with pytest.raises(ValidationFailure, match="extractor_id or extractor_name"):
        services["job_service"].create(file_id="file_1")
    with pytest.raises(ValidationFailure):
        services["job_service"].create(extractor_id=extractor.id)
    with pytest.raises(ValidationFailure):
        services["job_service"].create(extractor_id=extractor.id, file_id="file_1", text="x")
    with pytest.raises(ValidationFailure):
        services["job_service"].create(extractor_id=extractor.id, text="  ")
    with pytest.raises(NotFoundError):
        services["job_service"].list(extractor_id="missing")


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

    job = services["job_service"].create(extractor_name="receipt", file_id=file.id)

    assert job.extractor_id == extractor.id
    assert services["job_service"].list(extractor_name="receipt") == [job]


def test_job_service_lists_all_and_rejects_ambiguous_filters(services) -> None:
    extractor = services["extractor_service"].create(
        name="receipt", instructions="i", schema=schema()
    )
    file = services["file_service"].upload(
        file_name="receipt.md",
        content_type="text/markdown",
        content=b"Receipt #2",
    )
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)

    assert services["job_service"].list() == [job]
    with pytest.raises(ValidationFailure, match="only one of extractor_id or extractor_name"):
        services["job_service"].list(extractor_id=extractor.id, extractor_name=extractor.name)


def test_job_service_run_next_returns_none_when_no_work(services) -> None:
    assert services["job_service"].run_next_queued() is None


def test_job_service_schema_failure_keeps_invalid_result(services) -> None:
    services["engine"].response = ExtractionResponse(data={"receipt_id": "not-allowed"})
    file = services["file_service"].upload(file_name="a.md", content_type="", content=b"x")
    extractor = services["extractor_service"].create(name="e", instructions="i", schema=schema())
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)

    completed = services["job_service"].run_claimed(job)

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
    job = services["job_service"].create(extractor_id=extractor.id, file_id=file.id)

    completed = services["job_service"].run_claimed(job)

    assert completed.status == JobStatus.FAILED
    assert completed.error is not None
    assert "model unavailable" in completed.error.message


def test_job_service_missing_resources_during_run_fail_job(services) -> None:
    job = Job(
        id="job_1",
        extractor_id="missing",
        file_id="missing",
        status=JobStatus.RUNNING,
    )

    completed = services["job_service"].run_claimed(job)

    assert completed.status == JobStatus.FAILED
    assert completed.error is not None
    assert "extractor not found" in completed.error.message


def test_job_service_missing_file_during_run_fails_job(services) -> None:
    extractor = services["extractor_service"].create(name="e", instructions="i", schema=schema())
    job = Job(
        id="job_1",
        extractor_id=extractor.id,
        file_id="missing",
        status=JobStatus.RUNNING,
    )

    completed = services["job_service"].run_claimed(job)

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
    return ProviderService(providers, secrets), providers, secrets


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
