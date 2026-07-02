from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from parsehawk.core.domain.models import (
    ExampleInputKind,
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
)


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ExampleInputRequest(ApiModel):
    type: ExampleInputKind = ExampleInputKind.TEXT
    text: str | None = None
    file_id: str | None = None


class ExampleRequest(ApiModel):
    input: ExampleInputRequest | str
    output: dict[str, Any] | str


class CreateExtractorRequest(ApiModel):
    name: str | None = None
    display_name: str | None = None
    instructions: str
    enable_thinking: bool = False
    provider_name: ProviderName | None = None
    model: str | None = None
    schema_: dict[str, Any] = Field(alias="schema")
    examples: list[ExampleRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_identity(self) -> CreateExtractorRequest:
        if self.display_name is None and self.name is None:
            raise ValueError("provide display_name or name")
        return self


class UpdateExtractorRequest(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="forbid")

    display_name: str | None = None
    instructions: str | None = None
    enable_thinking: bool | None = None
    provider_name: ProviderName | None = None
    model: str | None = None
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")
    examples: list[ExampleRequest] | None = None


class UpsertExtractorRequest(ApiModel):
    name: str | None = None
    display_name: str
    instructions: str
    enable_thinking: bool = False
    provider_name: ProviderName | None = None
    model: str | None = None
    schema_: dict[str, Any] = Field(alias="schema")
    examples: list[ExampleRequest] = Field(default_factory=list)


class CreateJobRequest(ApiModel):
    extractor_id: str | None = None
    extractor_name: str | None = None
    file_id: str | None = None
    text: str | None = None

    @model_validator(mode="after")
    def validate_input(self) -> CreateJobRequest:
        provided_extractors = [self.extractor_id is not None, self.extractor_name is not None]
        if provided_extractors.count(True) != 1:
            raise ValueError("provide exactly one of extractor_id or extractor_name")
        provided_inputs = [self.file_id is not None, self.text is not None]
        if provided_inputs.count(True) != 1:
            raise ValueError("provide exactly one of file_id or text")
        if self.text is not None and not self.text.strip():
            raise ValueError("text input cannot be empty")
        return self


class ValidateSchemaRequest(ApiModel):
    schema_: dict[str, Any] = Field(
        alias="schema",
        description=(
            "ParseHawk extraction schema. This is the public authoring dialect "
            "documented in docs/schemas/parsehawk-extraction-schema.schema.json."
        ),
        json_schema_extra={
            "examples": [
                {
                    "type": "object",
                    "properties": {
                        "invoice_number": {
                            "type": ["string", "null"],
                            "x-parsehawk": {"semantic": "verbatim-string"},
                        },
                        "total": {"type": "number"},
                        "currency": {
                            "type": "string",
                            "x-parsehawk": {"semantic": "currency"},
                        },
                    },
                    "required": ["invoice_number", "total", "currency"],
                    "additionalProperties": False,
                }
            ]
        },
    )


class SchemaDiagnostic(ApiModel):
    message: str
    path: str = "$"
    code: str


class ValidateSchemaResponse(ApiModel):
    valid: bool
    schema_: dict[str, Any] | None = Field(
        default=None,
        alias="schema",
        description="Canonical ParseHawk extraction schema when validation succeeds.",
    )
    warnings: list[SchemaDiagnostic] = Field(default_factory=list)
    errors: list[SchemaDiagnostic] = Field(default_factory=list)


class FileResponse(ApiModel):
    id: str
    file_name: str
    content_type: str
    size_bytes: int
    sha256: str
    source: FileSource
    is_example: bool
    created_at: datetime

    @classmethod
    def from_domain(cls, file: File) -> FileResponse:
        return cls.model_validate(file)


class ExtractorResponse(ApiModel):
    id: str
    name: str
    display_name: str
    instructions: str
    enable_thinking: bool
    provider_name: ProviderName | None
    model: str | None
    schema_: dict[str, Any] = Field(alias="schema")
    examples: list[dict[str, Any]]
    source: ExtractorSource
    is_prebuilt: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, extractor: Extractor) -> ExtractorResponse:
        payload = extractor.model_dump()
        payload["schema"] = extractor.schema
        payload["examples"] = [example.model_dump() for example in extractor.examples]
        payload["is_prebuilt"] = extractor.is_prebuilt
        return cls.model_validate(payload)


class ProviderResponse(ApiModel):
    name: ProviderName
    base_url: str | None
    api_version: str | None
    has_api_key: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, provider: Provider, *, has_api_key: bool) -> ProviderResponse:
        return cls(
            name=provider.name,
            base_url=provider.base_url,
            api_version=provider.api_version,
            has_api_key=has_api_key,
            created_at=provider.created_at,
            updated_at=provider.updated_at,
        )


class ConfigureProviderRequest(ApiModel):
    """Write-only provider configuration. The API never returns the API key."""

    base_url: str | None = None
    api_version: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None


class ProviderModelsResponse(ApiModel):
    models: list[str]


class JobResultResponse(ApiModel):
    data: dict[str, Any]

    @classmethod
    def from_domain(cls, result: JobResult) -> JobResultResponse:
        return cls(data=result.data)


class JobErrorResponse(ApiModel):
    message: str
    code: str

    @classmethod
    def from_domain(cls, error: JobError) -> JobErrorResponse:
        return cls.model_validate(error)


class JobResponse(ApiModel):
    id: str
    extractor_id: str
    file_id: str | None
    source_text: str | None
    status: JobStatus
    result: JobResultResponse | None
    error: JobErrorResponse | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @classmethod
    def from_domain(cls, job: Job) -> JobResponse:
        return cls(
            id=job.id,
            extractor_id=job.extractor_id,
            file_id=job.file_id,
            source_text=job.source_text,
            status=job.status,
            result=JobResultResponse.from_domain(job.result)
            if job.status == JobStatus.COMPLETED and job.result
            else None,
            error=JobErrorResponse.from_domain(job.error) if job.error else None,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )
