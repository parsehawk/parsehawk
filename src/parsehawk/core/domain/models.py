from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EXTRACTOR_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")


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
    MICROSOFT_FOUNDRY = "microsoft_foundry"
    OPENAI_COMPATIBLE = "openai_compatible_api"


class MicrosoftFoundryProviderConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_version: str | None = None
    project_url: str | None = None

    @field_validator("api_version", "project_url", mode="before")
    @classmethod
    def normalize_optional_string(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


def normalize_provider_configuration(
    name: ProviderName, configuration: dict[str, Any] | None
) -> dict[str, Any]:
    raw_configuration = configuration or {}
    if name == ProviderName.MICROSOFT_FOUNDRY:
        return MicrosoftFoundryProviderConfiguration.model_validate(raw_configuration).model_dump(
            exclude_none=True
        )
    if raw_configuration:
        raise ValueError(f"{name.value} does not support provider configuration")
    return {}


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
    display_name: str = ""
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

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_display_name(cls, data: Any) -> Any:
        if (
            isinstance(data, dict)
            and "display_name" not in data
            and isinstance(data.get("name"), str)
        ):
            legacy_name = data["name"]
            migrated = {**data, "display_name": legacy_name}
            if not EXTRACTOR_NAME_PATTERN.fullmatch(legacy_name):
                migrated["name"] = slugify_extractor_name(legacy_name)
            return migrated
        return data

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        validate_extractor_name(value)
        return value

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("display_name is required")
        return value


class Provider(Entity):
    """Connection configuration for one of the fixed model providers.

    The API key is never stored here; it lives encrypted in its own table keyed
    by ``name``. ``base_url`` is common provider connection state; provider-specific
    knobs live in ``configuration`` and are validated per provider.
    """

    name: ProviderName
    base_url: str | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="before")
    @classmethod
    def validate_configuration(cls, data: Any) -> Any:
        if not isinstance(data, dict) or "name" not in data:
            return data
        name = ProviderName(data["name"])
        return {
            **data,
            "configuration": normalize_provider_configuration(
                name, data.get("configuration") or {}
            ),
        }

    def configuration_string(self, key: str) -> str | None:
        value = self.configuration.get(key)
        return value if isinstance(value, str) and value else None

    @property
    def api_version(self) -> str | None:
        return self.configuration_string("api_version")

    @property
    def project_url(self) -> str | None:
        return self.configuration_string("project_url")


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELING = "canceling"
    DELETING = "deleting"
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

    def mark_canceling(self) -> Job:
        return self.model_copy(
            update={
                "status": JobStatus.CANCELING,
            }
        )

    def mark_deleting(self) -> Job:
        return self.model_copy(
            update={
                "status": JobStatus.DELETING,
            }
        )

    def mark_canceled(self) -> Job:
        return self.model_copy(update={"status": JobStatus.CANCELED, "completed_at": utc_now()})


def validate_extractor_name(name: str) -> None:
    if name.startswith("extractor_"):
        raise ValueError("extractor name cannot start with the reserved extractor_ prefix")
    if not EXTRACTOR_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "extractor name must be 1-64 characters of lowercase letters, digits, "
            "hyphen, or underscore, and must start and end with a letter or digit"
        )


def slugify_extractor_name(display_name: str) -> str:
    normalized = unicodedata.normalize("NFKD", display_name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        slug = "extractor"
    return slug[:64].strip("-") or "extractor"


def extractor_name_suffix(extractor_id: str, length: int = 8) -> str:
    digest = hashlib.sha256(extractor_id.encode("utf-8")).hexdigest()
    return digest[:length]
