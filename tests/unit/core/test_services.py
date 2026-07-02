from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import List

import pytest

from parsehawk.core.application.ports import (
    ExtractionRequest,
    ExtractionResponse,
    PreparedDocument,
    PreparedImage,
)
from parsehawk.core.application.services import (
    ExtractorService,
    FileService,
    JobService,
    ProviderService,
)
from parsehawk.core.domain.errors import NotFoundError, ValidationFailure
from parsehawk.core.domain.models import (
    ExampleInputKind,
    Extractor,
    ExtractorSource,
    File,
    FileSource,
    Job,
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

    def list(self, extractor_id: str | None = None) -> List[Job]:
        jobs = list(self.items.values())
        if extractor_id is not None:
            jobs = [job for job in jobs if job.extractor_id == extractor_id]
        return jobs

    def get(self, job_id: str) -> Job | None:
        return self.items.get(job_id)

    def delete(self, job_id: str) -> None:
        self.items.pop(job_id, None)

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


@dataclass
class StubEngine:
    response: ExtractionResponse | None = None
    error: Exception | None = None
    requests: list[ExtractionRequest] = field(default_factory=list)

    def extract(self, request: ExtractionRequest) -> ExtractionResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


@dataclass
class StubEngineFactory:
    engine: StubEngine

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
    assert completed.result is not None
    assert completed.result.data == {"receipt_id": "2"}
    assert services["engine"].requests[0].source_text == "Subject: #1#"
    assert services["engine"].requests[0].source_storage_path == file.storage_path
    assert services["engine"].requests[0].source_content_type == file.content_type
    assert services["engine"].requests[0].enable_thinking is True

    job_service.delete(job.id)
    with pytest.raises(NotFoundError):
        job_service.get(job.id)


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


def test_extractor_create_materializes_default_provider_and_model(services) -> None:
    extractor = services["extractor_service"].create(name="e", instructions="i", schema=schema())

    assert extractor.provider_name == ProviderName.OPENAI_COMPATIBLE
    assert extractor.model == DEFAULT_MODEL


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


def test_extractor_update_changes_provider_and_model(services) -> None:
    extractor = services["extractor_service"].create(name="e", instructions="i", schema=schema())

    updated = services["extractor_service"].update(
        extractor.id, provider_name=ProviderName.AZURE_OPENAI, model="my-deployment"
    )

    assert updated.provider_name == ProviderName.AZURE_OPENAI
    assert updated.model == "my-deployment"


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
        service.get(ProviderName.AZURE_OPENAI)


def test_provider_service_configure_base_url_and_api_key() -> None:
    service, _providers, secrets = _provider_service()

    updated = service.configure(
        ProviderName.OPENAI,
        base_url="https://api.openai.com/v1",
        api_version="2024-10-21",
        api_key="sk-x",
    )

    assert updated.base_url == "https://api.openai.com/v1"
    assert updated.api_version == "2024-10-21"
    assert secrets.get(ProviderName.OPENAI) == "sk-x"
    assert service.has_api_key(ProviderName.OPENAI) is True
    # Configuring nothing leaves the provider and secret untouched.
    unchanged = service.configure(ProviderName.OPENAI)
    assert unchanged.base_url == "https://api.openai.com/v1"


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
