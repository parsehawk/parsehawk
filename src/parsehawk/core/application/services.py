from __future__ import annotations

import hashlib
import logging
import os
import time
from collections.abc import Callable
from dataclasses import asdict
from enum import StrEnum
from typing import Any, Iterable, List, TypeVar

from jsonschema import Draft202012Validator

from parsehawk.core.application.ports import (
    EngineFactory,
    ExtractionRequest,
    FileStorage,
    PreparedDocument,
    UnitOfWork,
    UnitOfWorkFactory,
)
from parsehawk.core.domain.errors import (
    ExtractionCancelled,
    NotFoundError,
    PersistenceBusyError,
    ValidationFailure,
)
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
    ReasoningEffort,
    ValidationIssue,
    extractor_name_suffix,
    normalize_provider_configuration,
    slugify_extractor_name,
    utc_now,
    validate_extractor_name,
)
from parsehawk.core.domain.schemas import MODE_JSON_SCHEMA, validate_extraction_schema

SUPPORTED_FILE_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".txt", ".md", ".markdown"}
WORKER_PERSISTENCE_RETRY_DELAY_SECONDS = 0.1

logger = logging.getLogger(__name__)
ResultT = TypeVar("ResultT")

# The provider new extractors default to when none is specified: the bundled
# OpenAI-compatible runtime that serves NuExtract3.
DEFAULT_PROVIDER_NAME = ProviderName.OPENAI_COMPATIBLE


# Sentinel distinguishing "field absent from the update" from an explicit None,
# which is a meaningful value for nullable extractor fields (model inherits the
# runtime default; reasoning_effort uses the model's own default).
class _NotProvided:
    pass


NOT_PROVIDED = _NotProvided()


class DeleteJobResult(StrEnum):
    DELETED = "deleted"
    ACCEPTED = "accepted"


class FileService:
    def __init__(self, uow_factory: UnitOfWorkFactory, storage: FileStorage) -> None:
        self._uow_factory = uow_factory
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
        try:
            with self._uow_factory(write=True) as uow:
                uow.files.save(file)
                uow.commit()
        except Exception:
            self._storage.delete_file(file)
            raise
        return file

    def list(self) -> List[File]:
        with self._uow_factory() as uow:
            return uow.files.list()

    def get(self, file_id: str) -> File:
        with self._uow_factory() as uow:
            return self._get(uow, file_id)

    def delete(self, file_id: str) -> None:
        with self._uow_factory(write=True) as uow:
            file = self._get(uow, file_id)
            if file.is_example:
                raise ValidationFailure("example files are read-only")
            if uow.jobs.has_for_file(file_id):
                raise ValidationFailure(
                    "file is referenced by jobs; delete those jobs before deleting the file"
                )
            uow.files.delete(file_id)
            uow.commit()
        self._storage.delete_file(file)

    @staticmethod
    def _get(uow: UnitOfWork, file_id: str) -> File:
        file = uow.files.get(file_id)
        if file is None:
            raise NotFoundError("file", file_id)
        return file


class ExtractorService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        default_model: str,
        default_provider: ProviderName = DEFAULT_PROVIDER_NAME,
    ) -> None:
        self._uow_factory = uow_factory
        self._default_model = default_model
        self._default_provider = default_provider

    def create(
        self,
        *,
        display_name: str | None = None,
        name: str | None = None,
        instructions: str,
        reasoning_effort: ReasoningEffort | None = None,
        provider_name: ProviderName | None = None,
        model: str | None = None,
        schema: dict[str, Any] | None = None,
        examples: List[dict[str, Any]] | None = None,
        source: ExtractorSource = ExtractorSource.USER,
        seed_key: str | None = None,
        seed_version: int | None = None,
    ) -> Extractor:
        with self._uow_factory(write=True) as uow:
            extractor = self._create(
                uow,
                display_name=display_name,
                name=name,
                instructions=instructions,
                reasoning_effort=reasoning_effort,
                provider_name=provider_name,
                model=model,
                schema=schema,
                examples=examples,
                source=source,
                seed_key=seed_key,
                seed_version=seed_version,
            )
            uow.commit()
            return extractor

    def _create(
        self,
        uow: UnitOfWork,
        *,
        display_name: str | None,
        name: str | None,
        instructions: str,
        reasoning_effort: ReasoningEffort | None,
        provider_name: ProviderName | None,
        model: str | None,
        schema: dict[str, Any] | None,
        examples: List[dict[str, Any]] | None,
        source: ExtractorSource,
        seed_key: str | None,
        seed_version: int | None,
    ) -> Extractor:
        if display_name is None:
            if name is None:
                raise ValidationFailure("display_name is required")
            display_name = name
        self._validate_display_name(display_name)
        extractor_id = new_id("extractor")
        stable_name = name or self._unique_generated_name(uow, display_name, extractor_id)
        self._validate_new_name(uow, stable_name)
        resolved_provider_name = provider_name or self._default_provider
        resolved_model = self._normalize_model(resolved_provider_name, model)
        schema = self._validate_schema(schema)
        parsed_examples = self._validate_examples(uow, examples or [])
        extractor = Extractor(
            id=extractor_id,
            name=stable_name,
            display_name=display_name,
            instructions=instructions,
            reasoning_effort=reasoning_effort,
            provider_name=resolved_provider_name,
            model=resolved_model,
            schema=schema,
            examples=parsed_examples,
            source=source,
            seed_key=seed_key,
            seed_version=seed_version,
        )
        uow.extractors.save(extractor)
        return extractor

    def list(self) -> List[Extractor]:
        with self._uow_factory() as uow:
            return uow.extractors.list()

    def get(self, extractor_id: str) -> Extractor:
        with self._uow_factory() as uow:
            extractor = uow.extractors.get(extractor_id)
            if extractor is None:
                raise NotFoundError("extractor", extractor_id)
            return extractor

    def get_by_ref(self, extractor_ref: str) -> Extractor:
        with self._uow_factory() as uow:
            return self._get_by_ref(uow, extractor_ref)

    def update(
        self,
        extractor_ref: str,
        *,
        display_name: str | None = None,
        instructions: str | None = None,
        reasoning_effort: ReasoningEffort | None | _NotProvided = NOT_PROVIDED,
        provider_name: ProviderName | None = None,
        model: str | None | _NotProvided = NOT_PROVIDED,
        schema: dict[str, Any] | None = None,
        examples: List[dict[str, Any]] | None = None,
    ) -> Extractor:
        with self._uow_factory(write=True) as uow:
            current = self._get_by_ref(uow, extractor_ref)
            self._ensure_mutable(current)
            updates: dict[str, Any] = {"updated_at": utc_now()}
            if display_name is not None:
                self._validate_display_name(display_name)
                updates["display_name"] = display_name
            if instructions is not None:
                updates["instructions"] = instructions
            if not isinstance(reasoning_effort, _NotProvided):
                updates["reasoning_effort"] = reasoning_effort
            resolved_provider_name = (
                provider_name or current.provider_name or self._default_provider
            )
            if provider_name is not None:
                updates["provider_name"] = provider_name
            if not isinstance(model, _NotProvided):
                updates["model"] = self._normalize_model(resolved_provider_name, model)
            elif provider_name is not None:
                self._normalize_model(resolved_provider_name, current.model)
            if schema is not None:
                updates["schema_"] = self._validate_schema(schema)
            if examples is not None:
                updates["examples"] = self._validate_examples(uow, examples)
            updated = current.model_copy(update=updates)
            uow.extractors.save(updated)
            uow.commit()
            return updated

    def upsert(
        self,
        extractor_ref: str,
        *,
        display_name: str,
        body_name: str | None = None,
        instructions: str,
        reasoning_effort: ReasoningEffort | None = None,
        provider_name: ProviderName | None = None,
        model: str | None = None,
        schema: dict[str, Any] | None = None,
        examples: List[dict[str, Any]] | None = None,
    ) -> Extractor:
        with self._uow_factory(write=True) as uow:
            existing = self._resolve_ref(uow, extractor_ref)
            if existing is not None:
                self._ensure_mutable(existing)
                if body_name is not None and body_name != existing.name:
                    raise ValidationFailure(
                        "request body name must match the target extractor name"
                    )
                extractor = self._replace(
                    uow,
                    existing,
                    display_name=display_name,
                    instructions=instructions,
                    reasoning_effort=reasoning_effort,
                    provider_name=provider_name,
                    model=model,
                    schema=schema,
                    examples=examples,
                )
            else:
                self._validate_new_name(uow, extractor_ref)
                if body_name is not None and body_name != extractor_ref:
                    raise ValidationFailure(
                        "request body name must match the target extractor name"
                    )
                extractor = self._create(
                    uow,
                    name=extractor_ref,
                    display_name=display_name,
                    instructions=instructions,
                    reasoning_effort=reasoning_effort,
                    provider_name=provider_name,
                    model=model,
                    schema=schema,
                    examples=examples,
                    source=ExtractorSource.USER,
                    seed_key=None,
                    seed_version=None,
                )
            uow.commit()
            return extractor

    def delete(self, extractor_ref: str) -> None:
        with self._uow_factory(write=True) as uow:
            extractor = self._get_by_ref(uow, extractor_ref)
            self._ensure_mutable(extractor)
            if uow.jobs.has_for_extractor(extractor.id):
                raise ValidationFailure(
                    "extractor is referenced by jobs; delete those jobs before deleting the extractor"
                )
            uow.extractors.delete(extractor.id)
            uow.commit()

    def _replace(
        self,
        uow: UnitOfWork,
        current: Extractor,
        *,
        display_name: str,
        instructions: str,
        reasoning_effort: ReasoningEffort | None,
        provider_name: ProviderName | None,
        model: str | None,
        schema: dict[str, Any] | None,
        examples: List[dict[str, Any]] | None,
    ) -> Extractor:
        self._validate_display_name(display_name)
        resolved_provider_name = provider_name or self._default_provider
        resolved_model = self._normalize_model(resolved_provider_name, model)
        updated = current.model_copy(
            update={
                "display_name": display_name,
                "instructions": instructions,
                "reasoning_effort": reasoning_effort,
                "provider_name": resolved_provider_name,
                "model": resolved_model,
                "schema_": self._validate_schema(schema),
                "examples": self._validate_examples(uow, examples or []),
                "updated_at": utc_now(),
            }
        )
        uow.extractors.save(updated)
        return updated

    def _normalize_model(self, provider_name: ProviderName, model: str | None) -> str | None:
        normalized = model.strip() if isinstance(model, str) else None
        if provider_name == ProviderName.OPENAI_COMPATIBLE:
            return normalized or None
        if not normalized:
            raise ValidationFailure(f"model is required for provider {provider_name.value}")
        return normalized

    @staticmethod
    def _resolve_ref(uow: UnitOfWork, extractor_ref: str) -> Extractor | None:
        return uow.extractors.get(extractor_ref) or uow.extractors.get_by_name(extractor_ref)

    def _get_by_ref(self, uow: UnitOfWork, extractor_ref: str) -> Extractor:
        extractor = self._resolve_ref(uow, extractor_ref)
        if extractor is None:
            raise NotFoundError("extractor", extractor_ref)
        return extractor

    def _unique_generated_name(self, uow: UnitOfWork, display_name: str, extractor_id: str) -> str:
        base = slugify_extractor_name(display_name)
        if uow.extractors.get_by_name(base) is None:
            return base
        for suffix_length in (8, 10, 12, 16, 32):
            suffix = extractor_name_suffix(extractor_id, suffix_length)
            max_base_len = 64 - len(suffix) - 1
            candidate = f"{base[:max_base_len].rstrip('-_')}-{suffix}"
            if uow.extractors.get_by_name(candidate) is None:
                return candidate
        raise ValidationFailure("could not generate a unique extractor name")

    @staticmethod
    def _validate_new_name(uow: UnitOfWork, name: str) -> None:
        try:
            validate_extractor_name(name)
        except ValueError as exc:
            raise ValidationFailure(str(exc)) from exc
        existing = uow.extractors.get_by_name(name)
        if existing is not None:
            raise ValidationFailure(f"extractor name already exists: {name}")

    @staticmethod
    def _validate_display_name(display_name: str) -> None:
        if not display_name.strip():
            raise ValidationFailure("display_name is required")

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

    @staticmethod
    def _validate_examples(uow: UnitOfWork, examples: List[dict[str, Any]]) -> List[Example]:
        parsed_examples = [Example.model_validate(example) for example in examples]
        for example in parsed_examples:
            if example.input.type != ExampleInputKind.FILE:
                continue
            assert example.input.file_id is not None
            if uow.files.get(example.input.file_id) is None:
                raise NotFoundError("file", example.input.file_id)
        return parsed_examples


class ProviderService:
    """Read and configure the fixed set of model providers.

    Providers are not user-creatable: only their connection config and API key
    can be changed. Keys are handed straight to the secret store, which encrypts
    them; they are never returned.
    """

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def list(self) -> List[Provider]:
        with self._uow_factory() as uow:
            return uow.providers.list()

    def get(self, name: ProviderName) -> Provider:
        with self._uow_factory() as uow:
            return self._get(uow, name)

    def has_api_key(self, name: ProviderName) -> bool:
        with self._uow_factory() as uow:
            return uow.secrets.has(name)

    def get_with_api_key(self, name: ProviderName) -> tuple[Provider, str | None]:
        with self._uow_factory() as uow:
            return self._get(uow, name), uow.secrets.get(name)

    def ensure(
        self,
        provider: Provider,
        *,
        replace_base_url_if: frozenset[str | None] = frozenset(),
    ) -> Provider:
        """Create a fixed provider or reconcile a known generated base URL."""
        with self._uow_factory(write=True) as uow:
            existing = uow.providers.get(provider.name)
            if existing is None:
                resolved = provider
                uow.providers.save(resolved)
            elif (
                existing.base_url != provider.base_url and existing.base_url in replace_base_url_if
            ):
                resolved = existing.model_copy(
                    update={"base_url": provider.base_url, "updated_at": utc_now()}
                )
                uow.providers.save(resolved)
            else:
                resolved = existing
            uow.commit()
            return resolved

    def configure(
        self,
        name: ProviderName,
        *,
        base_url: str | None = None,
        configuration: dict[str, Any] | None = None,
        api_key: str | None = None,
        api_key_env: str | None = None,
    ) -> Provider:
        resolved_key = self._resolve_api_key(api_key, api_key_env)
        with self._uow_factory(write=True) as uow:
            provider = self._get(uow, name)
            updates: dict[str, Any] = {}
            if base_url is not None:
                updates["base_url"] = base_url
            if configuration is not None:
                updates["configuration"] = normalize_provider_configuration(name, configuration)
            if updates:
                provider = Provider.model_validate(
                    {**provider.model_dump(), **updates, "updated_at": utc_now()}
                )
                uow.providers.save(provider)
            if resolved_key is not None:
                uow.secrets.put(name, resolved_key)
            uow.commit()
            return provider

    @staticmethod
    def _get(uow: UnitOfWork, name: ProviderName) -> Provider:
        provider = uow.providers.get(name)
        if provider is None:
            raise NotFoundError("provider", name.value)
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
        uow_factory: UnitOfWorkFactory,
        storage: FileStorage,
        engine_factory: EngineFactory,
    ) -> None:
        self._uow_factory = uow_factory
        self._storage = storage
        self._engine_factory = engine_factory

    def create(
        self,
        *,
        extractor_id: str | None = None,
        extractor_name: str | None = None,
        file_id: str | None = None,
        text: str | None = None,
    ) -> Job:
        provided_extractors = [extractor_id is not None, extractor_name is not None]
        if provided_extractors.count(True) != 1:
            raise ValidationFailure("provide exactly one of extractor_id or extractor_name")
        provided_inputs = [file_id is not None, text is not None]
        if provided_inputs.count(True) != 1:
            raise ValidationFailure("provide exactly one of file_id or text")
        if text is not None and not text.strip():
            raise ValidationFailure("text input cannot be empty")

        with self._uow_factory(write=True) as uow:
            extractor = (
                uow.extractors.get(extractor_id)
                if extractor_id is not None
                else uow.extractors.get_by_name(extractor_name or "")
            )
            if extractor is None:
                raise NotFoundError("extractor", extractor_id or extractor_name or "")
            if file_id is not None and uow.files.get(file_id) is None:
                raise NotFoundError("file", file_id)
            job = Job(
                id=new_id("job"),
                extractor_id=extractor.id,
                file_id=file_id,
                source_text=text,
                status=JobStatus.QUEUED,
            )
            uow.jobs.save(job)
            uow.commit()
            return job

    def list(self, extractor_id: str | None = None, extractor_name: str | None = None) -> List[Job]:
        provided_extractors = [extractor_id is not None, extractor_name is not None]
        if provided_extractors.count(True) > 1:
            raise ValidationFailure("provide only one of extractor_id or extractor_name")
        with self._uow_factory() as uow:
            if extractor_id is None and extractor_name is None:
                return uow.jobs.list()
            extractor = (
                uow.extractors.get(extractor_id)
                if extractor_id is not None
                else uow.extractors.get_by_name(extractor_name or "")
            )
            if extractor is None:
                raise NotFoundError("extractor", extractor_id or extractor_name or "")
            return uow.jobs.list(extractor_id=extractor.id)

    def get(self, job_id: str) -> Job:
        with self._uow_factory() as uow:
            return self._get(uow, job_id)

    def cancel(self, job_id: str) -> Job:
        while True:
            with self._uow_factory(write=True) as uow:
                job = self._get(uow, job_id)
                if job.status == JobStatus.QUEUED:
                    next_job = job.mark_canceled()
                    expected = [JobStatus.QUEUED]
                elif job.status == JobStatus.RUNNING:
                    next_job = job.mark_canceling()
                    expected = [JobStatus.RUNNING]
                else:
                    raise ValidationFailure(f"cannot cancel job in '{job.status.value}' state")
                saved = uow.jobs.save_if_status(next_job, expected)
                if saved:
                    uow.commit()
                    return next_job

    def delete(self, job_id: str) -> DeleteJobResult:
        while True:
            with self._uow_factory(write=True) as uow:
                job = self._get(uow, job_id)
                if job.status in {
                    JobStatus.QUEUED,
                    JobStatus.COMPLETED,
                    JobStatus.FAILED,
                    JobStatus.CANCELED,
                }:
                    changed = uow.jobs.delete_if_status(job_id, [job.status])
                    result = DeleteJobResult.DELETED
                elif job.status in {JobStatus.RUNNING, JobStatus.CANCELING}:
                    changed = uow.jobs.save_if_status(job.mark_deleting(), [job.status])
                    result = DeleteJobResult.ACCEPTED
                elif job.status == JobStatus.DELETING:
                    return DeleteJobResult.ACCEPTED
                else:  # pragma: no cover - JobStatus is exhaustively handled above
                    raise ValidationFailure(f"cannot delete job in '{job.status.value}' state")
                if changed:
                    uow.commit()
                    return result

    def run_next_queued(self) -> Job | None:
        with self._uow_factory(write=True) as uow:
            claimed = uow.jobs.claim_next_queued()
            uow.commit()
        if claimed is None:
            return None
        return self.run_claimed(claimed)

    def run_claimed(self, job: Job) -> Job:
        running = job if job.status == JobStatus.RUNNING else job.mark_running()
        if job.status != JobStatus.RUNNING and not self._save_if_status(running, [job.status]):
            canceled = self._cancel_if_requested(running.id)
            if canceled is not None:
                return canceled
            latest = self._get_optional(running.id)
            if latest is not None:
                return latest
        try:
            extractor, source_file, example_files, provider, api_key = self._load_execution_state(
                running
            )
            resolved_config = self._engine_factory.resolve_extractor_config(extractor)
            running = running.with_execution_config(
                provider_name=resolved_config.provider_name,
                model=resolved_config.model,
            )
            if not self._save_if_status(running, [JobStatus.RUNNING]):
                canceled = self._cancel_if_requested(running.id)
                if canceled is not None:
                    return canceled
                latest = self._get_optional(running.id)
                if latest is not None:
                    return latest

            source = self._prepare_job_source(running, source_file)
            examples = self._resolve_examples(extractor, example_files)
            engine = self._engine_factory.for_extractor(
                extractor,
                provider=provider,
                api_key=api_key,
            )

            def cancellation_requested() -> bool:
                latest = self._get_optional(running.id)
                return latest is not None and latest.status in {
                    JobStatus.CANCELING,
                    JobStatus.DELETING,
                }

            canceled = self._cancel_if_requested(running.id)
            if canceled is not None:
                return canceled
            response = engine.extract(
                ExtractionRequest(
                    source_text=source.text,
                    source_storage_path=source.storage_path,
                    source_content_type=source.content_type,
                    source_images=source.images,
                    instructions=extractor.instructions,
                    reasoning_effort=extractor.reasoning_effort,
                    schema=extractor.schema,
                    examples=examples,
                ),
                cancellation_check=cancellation_requested,
            )
            validation_errors = self._validate_output(extractor.schema, response.data)
            result = JobResult(data=response.data, validation_errors=validation_errors)
            completed = (
                running.mark_completed(result)
                if result.valid
                else running.mark_failed(
                    "extraction did not match schema", code="schema_validation_failed"
                ).model_copy(update={"result": result})
            )
            canceled = self._cancel_if_requested(running.id)
            if canceled is not None:
                return canceled
            if self._save_if_status(completed, [JobStatus.RUNNING]):
                return completed
            canceled = self._cancel_if_requested(running.id)
            if canceled is not None:
                return canceled
            return self._get_optional(running.id) or completed

        except ExtractionCancelled as exc:
            canceled = self._cancel_if_requested(running.id)
            if canceled is not None:
                return canceled
            return self._record_failure(running, str(exc), check_cancellation=False)
        except Exception as exc:
            return self._record_failure(running, str(exc), check_cancellation=True)

    def _load_execution_state(
        self, job: Job
    ) -> tuple[Extractor, File | None, dict[str, File], Provider | None, str | None]:
        def load() -> tuple[Extractor, File | None, dict[str, File], Provider | None, str | None]:
            with self._uow_factory() as uow:
                extractor = uow.extractors.get(job.extractor_id)
                if extractor is None:
                    raise NotFoundError("extractor", job.extractor_id)
                source_file = None
                if job.file_id is not None:
                    source_file = uow.files.get(job.file_id)
                    if source_file is None:
                        raise NotFoundError("file", job.file_id)
                example_files: dict[str, File] = {}
                for example in extractor.examples:
                    if example.input.type != ExampleInputKind.FILE:
                        continue
                    assert example.input.file_id is not None
                    example_file = uow.files.get(example.input.file_id)
                    if example_file is None:
                        raise NotFoundError("file", example.input.file_id)
                    example_files[example_file.id] = example_file
                resolved_config = self._engine_factory.resolve_extractor_config(extractor)
                provider = uow.providers.get(resolved_config.provider_name)
                api_key = uow.secrets.get(resolved_config.provider_name)
                return extractor, source_file, example_files, provider, api_key

        return self._retry_persistence(load, job_id=job.id, phase="loading execution state")

    def _record_failure(self, running: Job, message: str, *, check_cancellation: bool) -> Job:
        failed = running.mark_failed(message)
        if self._save_if_status(failed, [JobStatus.RUNNING]):
            return failed
        if check_cancellation:
            canceled = self._cancel_if_requested(running.id)
            if canceled is not None:
                return canceled
        return self._get_optional(running.id) or failed

    def _cancel_if_requested(self, job_id: str) -> Job | None:
        def cancel() -> Job | None:
            with self._uow_factory(write=True) as uow:
                latest = uow.jobs.get(job_id)
                if latest is None:
                    return None
                if latest.status == JobStatus.CANCELED:
                    return latest
                if latest.status == JobStatus.DELETING:
                    uow.jobs.delete(latest.id)
                    uow.commit()
                    return latest
                if latest.status != JobStatus.CANCELING:
                    return None
                canceled = latest.mark_canceled()
                if uow.jobs.save_if_status(canceled, [JobStatus.CANCELING]):
                    uow.commit()
                    return canceled
            return self._get_optional(job_id) or canceled

        return self._retry_persistence(cancel, job_id=job_id, phase="applying cancellation")

    def _save_if_status(self, job: Job, expected: Iterable[JobStatus]) -> bool:
        def save() -> bool:
            with self._uow_factory(write=True) as uow:
                saved = uow.jobs.save_if_status(job, expected)
                uow.commit()
                return saved

        return self._retry_persistence(save, job_id=job.id, phase="saving state")

    def _get_optional(self, job_id: str) -> Job | None:
        def get() -> Job | None:
            with self._uow_factory() as uow:
                return uow.jobs.get(job_id)

        return self._retry_persistence(get, job_id=job_id, phase="reading state")

    @staticmethod
    def _retry_persistence(operation: Callable[[], ResultT], *, job_id: str, phase: str) -> ResultT:
        while True:
            try:
                return operation()
            except PersistenceBusyError:
                logger.warning(
                    "Persistence busy while %s for job %s; retrying in %.2f seconds",
                    phase,
                    job_id,
                    WORKER_PERSISTENCE_RETRY_DELAY_SECONDS,
                )
                time.sleep(WORKER_PERSISTENCE_RETRY_DELAY_SECONDS)

    @staticmethod
    def _get(uow: UnitOfWork, job_id: str) -> Job:
        job = uow.jobs.get(job_id)
        if job is None:
            raise NotFoundError("job", job_id)
        return job

    @staticmethod
    def _validate_output(schema: dict[str, Any], data: dict[str, Any]) -> List[ValidationIssue]:
        validator = Draft202012Validator(schema)
        issues = []
        for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path)):
            path = ".".join(str(part) for part in error.path)
            issues.append(ValidationIssue(path=path or "$", message=error.message))
        return issues

    def _prepare_job_source(self, job: Job, file: File | None) -> PreparedDocument:
        if job.file_id is not None:
            assert file is not None
            return self._storage.prepare_document(file)
        assert job.source_text is not None
        return PreparedDocument(
            text=job.source_text,
            storage_path="",
            content_type="text/plain",
            images=[],
        )

    def _resolve_examples(
        self, extractor: Extractor, example_files: dict[str, File]
    ) -> List[dict[str, Any]]:
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
                file = example_files.get(example.input.file_id)
                if file is None:  # pragma: no cover - execution state preloads every file
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
