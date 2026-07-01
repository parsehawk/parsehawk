from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Entity(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True, serialize_by_alias=True)


class FileSource(StrEnum):
    USER = "user"
    EXAMPLE = "example"


class ExtractorSource(StrEnum):
    USER = "user"
    PREBUILT = "prebuilt"


class ProviderName(StrEnum):
    """The fixed set of model providers ParseHawk ships.

    Providers are preconfigured and configurable, not user-creatable, so the
    name doubles as the stable identifier extractors reference and as the
    discriminator the engine factory switches on.
    """

    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    OPENAI_COMPATIBLE = "openai_compatible_api"


# NuExtract3 is fine-tuned on its own chat template, so only these exact models
# use the NuExtract payload adapter; every other model uses the generic adapter.
# Hardcoded from https://huggingface.co/collections/numind/nuextract3 and
# independent of what the runtime currently has loaded.
NUEXTRACT3_MODELS = frozenset(
    {
        "numind/NuExtract3",
        "numind/NuExtract3-GGUF",
        "numind/NuExtract3-W8A8",
        "numind/NuExtract3-W4A16",
        "numind/NuExtract3-FP8",
        "numind/NuExtract3-mlx-4bits",
        "numind/NuExtract3-mlx-5bits",
        "numind/NuExtract3-mlx-6bits",
        "numind/NuExtract3-mlx-8bits",
        "numind/NuExtract3-mlx-nvfp4",
        "numind/NuExtract3-mlx-mxfp8",
    }
)


class File(Entity):
    id: str
    file_name: str
    content_type: str
    size_bytes: int = Field(ge=0)
    sha256: str
    storage_path: str
    source: FileSource = FileSource.USER
    seed_key: str | None = None
    seed_version: int | None = Field(default=None, ge=1)
    created_at: datetime = Field(default_factory=utc_now)

    @property
    def is_example(self) -> bool:
        return self.source == FileSource.EXAMPLE


class ExampleInputKind(StrEnum):
    TEXT = "text"
    FILE = "file"


class ExampleInput(Entity):
    type: ExampleInputKind
    text: str | None = None
    file_id: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> ExampleInput:
        if self.type == ExampleInputKind.TEXT:
            if not self.text:
                raise ValueError("text examples require input.text")
            if self.file_id is not None:
                raise ValueError("text examples cannot include input.file_id")
        if self.type == ExampleInputKind.FILE:
            if not self.file_id:
                raise ValueError("file examples require input.file_id")
            if self.text is not None:
                raise ValueError("file examples cannot include input.text")
        return self


class Example(Entity):
    input: ExampleInput
    output: dict[str, Any] | str

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_text_input(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("input"), str):
            return {**data, "input": {"type": ExampleInputKind.TEXT, "text": data["input"]}}
        return data


class Extractor(Entity):
    id: str
    name: str
    instructions: str
    enable_thinking: bool = False
    provider_name: ProviderName | None = None
    model: str | None = None
    schema_: dict[str, Any] = Field(alias="schema")
    examples: list[Example] = Field(default_factory=list)
    source: ExtractorSource = ExtractorSource.USER
    seed_key: str | None = None
    seed_version: int | None = Field(default=None, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def is_prebuilt(self) -> bool:
        return self.source == ExtractorSource.PREBUILT

    @property
    def schema(self) -> dict[str, Any]:
        return self.schema_


class Provider(Entity):
    """Connection configuration for one of the fixed model providers.

    The API key is never stored here; it lives encrypted in its own table keyed
    by ``name``. ``base_url``/``api_version`` are configurable (e.g. Azure users
    set ``base_url`` to their OpenAI-compatible v1 endpoint).
    """

    name: ProviderName
    base_url: str | None = None
    api_version: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELING = "canceling"
    CANCELED = "canceled"


class ValidationIssue(Entity):
    path: str
    message: str


class JobResult(Entity):
    data: dict[str, Any]
    validation_errors: list[ValidationIssue] = Field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.validation_errors


class JobError(Entity):
    message: str
    code: str = "extraction_failed"


class Job(Entity):
    id: str
    extractor_id: str
    status: JobStatus
    file_id: str | None = None
    source_text: str | None = None
    result: JobResult | None = None
    error: JobError | None = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def mark_running(self) -> Job:
        return self.model_copy(update={"status": JobStatus.RUNNING, "started_at": utc_now()})

    def mark_completed(self, result: JobResult) -> Job:
        return self.model_copy(
            update={"status": JobStatus.COMPLETED, "result": result, "completed_at": utc_now()}
        )

    def mark_failed(self, message: str, code: str = "extraction_failed") -> Job:
        return self.model_copy(
            update={
                "status": JobStatus.FAILED,
                "error": JobError(message=message, code=code),
                "completed_at": utc_now(),
            }
        )

    def mark_canceled(self) -> Job:
        return self.model_copy(update={"status": JobStatus.CANCELED, "completed_at": utc_now()})
