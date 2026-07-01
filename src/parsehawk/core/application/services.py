from __future__ import annotations

import hashlib
import os
from dataclasses import asdict
from typing import Any, List

from jsonschema import Draft202012Validator

from parsehawk.core.application.ports import (
    ExtractionEngine,
    ExtractionRequest,
    ExtractorRepository,
    FileRepository,
    FileStorage,
    JobRepository,
    PreparedDocument,
    ProviderRepository,
    SecretStore,
)
from parsehawk.core.domain.errors import NotFoundError, ValidationFailure
from parsehawk.core.domain.ids import new_id
from parsehawk.core.domain.models import (
    Example,
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
    ValidationIssue,
    utc_now,
)
from parsehawk.core.domain.schemas import MODE_JSON_SCHEMA, validate_extraction_schema

SUPPORTED_FILE_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".txt", ".md", ".markdown"}

# The provider new extractors default to when none is specified: the bundled
# OpenAI-compatible runtime that serves NuExtract3.
DEFAULT_PROVIDER_NAME = ProviderName.OPENAI_COMPATIBLE


class FileService:
    def __init__(self, files: FileRepository, storage: FileStorage) -> None:
        self._files = files
        self._storage = storage

    def upload(
        self,
        *,
        file_name: str,
        content_type: str,
        content: bytes,
        source: FileSource = FileSource.USER,
        seed_key: str | None = None,
        seed_version: int | None = None,
    ) -> File:
        if not file_name:
            raise ValidationFailure("file_name is required")
        suffix = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if suffix not in SUPPORTED_FILE_SUFFIXES:
            raise ValidationFailure(
                f"unsupported file type: {suffix or '<none>'}; "
                "supported types are PDF, JPG, PNG, TXT, and Markdown"
            )
        file_id = new_id("file")
        storage_path = self._storage.write_file(file_id, file_name, content)
        file = File(
            id=file_id,
            file_name=file_name,
            content_type=content_type or "application/octet-stream",
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            storage_path=storage_path,
            source=source,
            seed_key=seed_key,
            seed_version=seed_version,
        )
        self._files.save(file)
        return file

    def list(self) -> List[File]:
        return self._files.list()

    def get(self, file_id: str) -> File:
        file = self._files.get(file_id)
        if file is None:
            raise NotFoundError("file", file_id)
        return file

    def delete(self, file_id: str) -> None:
        file = self.get(file_id)
        if file.is_example:
            raise ValidationFailure("example files are read-only")
        self._storage.delete_file(file)
        self._files.delete(file_id)


class ExtractorService:
    def __init__(
        self,
        extractors: ExtractorRepository,
        files: FileRepository,
        *,
        default_model: str,
        default_provider: ProviderName = DEFAULT_PROVIDER_NAME,
    ) -> None:
        self._extractors = extractors
        self._files = files
        self._default_model = default_model
        self._default_provider = default_provider

    def create(
        self,
        *,
        name: str,
        instructions: str,
        enable_thinking: bool = False,
        provider_name: ProviderName | None = None,
        model: str | None = None,
        schema: dict[str, Any] | None = None,
        examples: List[dict[str, Any]] | None = None,
        source: ExtractorSource = ExtractorSource.USER,
        seed_key: str | None = None,
        seed_version: int | None = None,
    ) -> Extractor:
        schema = self._validate_schema(schema)
        parsed_examples = self._validate_examples(examples or [])
        extractor = Extractor(
            id=new_id("extractor"),
            name=name,
            instructions=instructions,
            enable_thinking=enable_thinking,
            provider_name=provider_name or self._default_provider,
            model=model or self._default_model,
            schema=schema,
            examples=parsed_examples,
            source=source,
            seed_key=seed_key,
            seed_version=seed_version,
        )
        self._extractors.save(extractor)
        return extractor

    def list(self) -> List[Extractor]:
        return self._extractors.list()

    def get(self, extractor_id: str) -> Extractor:
        extractor = self._extractors.get(extractor_id)
        if extractor is None:
            raise NotFoundError("extractor", extractor_id)
        return extractor

    def update(
        self,
        extractor_id: str,
        *,
        name: str | None = None,
        instructions: str | None = None,
        enable_thinking: bool | None = None,
        provider_name: ProviderName | None = None,
        model: str | None = None,
        schema: dict[str, Any] | None = None,
        examples: List[dict[str, Any]] | None = None,
    ) -> Extractor:
        current = self.get(extractor_id)
        self._ensure_mutable(current)
        updates: dict[str, Any] = {"updated_at": utc_now()}
        if name is not None:
            updates["name"] = name
        if instructions is not None:
            updates["instructions"] = instructions
        if enable_thinking is not None:
            updates["enable_thinking"] = enable_thinking
        if provider_name is not None:
            updates["provider_name"] = provider_name
        if model is not None:
            updates["model"] = model
        if schema is not None:
            updates["schema_"] = self._validate_schema(schema)
        if examples is not None:
            updates["examples"] = self._validate_examples(examples)
        updated = current.model_copy(update=updates)
        self._extractors.save(updated)
        return updated

    def delete(self, extractor_id: str) -> None:
        self._ensure_mutable(self.get(extractor_id))
        self._extractors.delete(extractor_id)

    @staticmethod
    def _ensure_mutable(extractor: Extractor) -> None:
        if extractor.is_prebuilt:
            raise ValidationFailure(
                "prebuilt extractors are read-only; create your own extractor instead"
            )

    @staticmethod
    def _validate_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
        if schema is None:
            raise ValidationFailure("schema is required")
        result = validate_extraction_schema(
            mode=MODE_JSON_SCHEMA,
            json_schema=schema,
        )
        if result.errors:
            messages = "; ".join(error.message for error in result.errors)
            raise ValidationFailure(f"invalid extraction schema: {messages}")
        assert result.json_schema is not None
        return result.json_schema

    def _validate_examples(self, examples: List[dict[str, Any]]) -> List[Example]:
        parsed_examples = [Example.model_validate(example) for example in examples]
        for example in parsed_examples:
            if example.input.type != ExampleInputKind.FILE:
                continue
            assert example.input.file_id is not None
            if self._files.get(example.input.file_id) is None:
                raise NotFoundError("file", example.input.file_id)
        return parsed_examples


class ProviderService:
    """Read and configure the fixed set of model providers.

    Providers are not user-creatable: only their connection config (base_url,
    api_version) and API key can be changed. Keys are handed straight to the
    secret store, which encrypts them; they are never returned.
    """

    def __init__(self, providers: ProviderRepository, secrets: SecretStore) -> None:
        self._providers = providers
        self._secrets = secrets

    def list(self) -> List[Provider]:
        return self._providers.list()

    def get(self, name: ProviderName) -> Provider:
        provider = self._providers.get(name)
        if provider is None:
            raise NotFoundError("provider", name.value)
        return provider

    def has_api_key(self, name: ProviderName) -> bool:
        return self._secrets.has(name)

    def configure(
        self,
        name: ProviderName,
        *,
        base_url: str | None = None,
        api_version: str | None = None,
        api_key: str | None = None,
        api_key_env: str | None = None,
    ) -> Provider:
        provider = self.get(name)
        updates: dict[str, Any] = {}
        if base_url is not None:
            updates["base_url"] = base_url
        if api_version is not None:
            updates["api_version"] = api_version
        if updates:
            updates["updated_at"] = utc_now()
            provider = provider.model_copy(update=updates)
            self._providers.save(provider)
        resolved_key = self._resolve_api_key(api_key, api_key_env)
        if resolved_key is not None:
            self._secrets.put(name, resolved_key)
        return provider

    @staticmethod
    def _resolve_api_key(api_key: str | None, api_key_env: str | None) -> str | None:
        if api_key is not None:
            return api_key
        if api_key_env is not None:
            value = os.getenv(api_key_env)
            if not value:
                raise ValidationFailure(f"environment variable {api_key_env!r} is not set")
            return value
        return None


class JobService:
    def __init__(
        self,
        jobs: JobRepository,
        files: FileRepository,
        extractors: ExtractorRepository,
        storage: FileStorage,
        engine: ExtractionEngine,
    ) -> None:
        self._jobs = jobs
        self._files = files
        self._extractors = extractors
        self._storage = storage
        self._engine = engine

    def create(
        self, *, extractor_id: str, file_id: str | None = None, text: str | None = None
    ) -> Job:
        if self._extractors.get(extractor_id) is None:
            raise NotFoundError("extractor", extractor_id)
        provided_inputs = [file_id is not None, text is not None]
        if provided_inputs.count(True) != 1:
            raise ValidationFailure("provide exactly one of file_id or text")
        if file_id is not None and self._files.get(file_id) is None:
            raise NotFoundError("file", file_id)
        if text is not None and not text.strip():
            raise ValidationFailure("text input cannot be empty")
        job_id = new_id("job")
        job = Job(
            id=job_id,
            extractor_id=extractor_id,
            file_id=file_id,
            source_text=text,
            status=JobStatus.QUEUED,
        )
        self._jobs.save(job)
        return job

    def list(self, extractor_id: str | None = None) -> List[Job]:
        if extractor_id is not None and self._extractors.get(extractor_id) is None:
            raise NotFoundError("extractor", extractor_id)
        return self._jobs.list(extractor_id=extractor_id)

    def get(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise NotFoundError("job", job_id)
        return job

    def delete(self, job_id: str) -> None:
        self.get(job_id)
        self._jobs.delete(job_id)

    def run_next_queued(self) -> Job | None:
        claimed = self._jobs.claim_next_queued()
        if claimed is None:
            return None
        return self.run_claimed(claimed)

    def run_claimed(self, job: Job) -> Job:
        running = job if job.status == JobStatus.RUNNING else job.mark_running()
        self._jobs.save(running)
        try:
            extractor = self._extractors.get(running.extractor_id)
            if extractor is None:
                raise NotFoundError("extractor", running.extractor_id)
            source = self._prepare_job_source(running)
            response = self._engine.extract(
                ExtractionRequest(
                    source_text=source.text,
                    source_storage_path=source.storage_path,
                    source_content_type=source.content_type,
                    source_images=source.images,
                    instructions=extractor.instructions,
                    enable_thinking=extractor.enable_thinking,
                    schema=extractor.schema,
                    examples=self._resolve_examples(extractor),
                )
            )
            validation_errors = self._validate_output(extractor.schema, response.data)
            result = JobResult(
                data=response.data,
                validation_errors=validation_errors,
            )
            completed = (
                running.mark_completed(result)
                if result.valid
                else running.mark_failed(
                    "extraction did not match schema", code="schema_validation_failed"
                ).model_copy(update={"result": result})
            )
            self._jobs.save(completed)
            return completed
        except Exception as exc:
            failed = running.mark_failed(str(exc))
            self._jobs.save(failed)
            return failed

    @staticmethod
    def _validate_output(schema: dict[str, Any], data: dict[str, Any]) -> List[ValidationIssue]:
        validator = Draft202012Validator(schema)
        issues = []
        for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path)):
            path = ".".join(str(part) for part in error.path)
            issues.append(ValidationIssue(path=path or "$", message=error.message))
        return issues

    def _prepare_job_source(self, job: Job) -> PreparedDocument:
        if job.file_id is not None:
            file = self._files.get(job.file_id)
            if file is None:
                raise NotFoundError("file", job.file_id)
            return self._storage.prepare_document(file)
        assert job.source_text is not None
        return PreparedDocument(
            text=job.source_text,
            storage_path="",
            content_type="text/plain",
            images=[],
        )

    def _resolve_examples(self, extractor: Extractor) -> List[dict[str, Any]]:
        resolved_examples: List[dict[str, Any]] = []
        for example in extractor.examples:
            if example.input.type == ExampleInputKind.TEXT:
                assert example.input.text is not None
                example_input: dict[str, Any] = {
                    "type": ExampleInputKind.TEXT,
                    "text": example.input.text,
                }
            else:
                assert example.input.file_id is not None
                file = self._files.get(example.input.file_id)
                if file is None:
                    raise NotFoundError("file", example.input.file_id)
                document = self._storage.prepare_document(file)
                example_input = {
                    "type": ExampleInputKind.FILE,
                    "file_id": file.id,
                    "file_name": file.file_name,
                    "content_type": document.content_type,
                    "storage_path": document.storage_path,
                    "text": document.text,
                    "images": [asdict(image) for image in document.images],
                }
            resolved_examples.append({"input": example_input, "output": example.output})
        return resolved_examples
