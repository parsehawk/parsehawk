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
    def mark_canceling(self) -> Job:
     return self.model_copy(
        update={
            "status": JobStatus.CANCELING,
        }
    )
     
    def mark_canceled(self) -> Job:
        return self.model_copy(update={"status": JobStatus.CANCELED, "completed_at": utc_now()})
