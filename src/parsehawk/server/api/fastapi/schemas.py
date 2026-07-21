from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

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
    ReasoningEffort,
)


class ApiModel(BaseModel):
    """Base class for strict public API payloads."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="forbid")


class ApiErrorResponse(ApiModel):
    """Error returned by request validation or a ParseHawk domain service."""

    code: str | None = Field(
        default=None,
        description="Stable machine-readable error code when the failure is retryable or actionable.",
    )
    detail: str | list[dict[str, Any]] = Field(
        description=(
            "Human-readable error text, or FastAPI validation details when the request "
            "does not match the declared schema."
        )
    )


class HealthResponse(ApiModel):
    """Liveness status for the API process."""

    status: Literal["ok"] = Field(description="The API process is ready to accept requests.")


class RootResponse(ApiModel):
    """API welcome message."""

    message: str = Field(description="Short API welcome message with a link to the documentation.")


class ExampleInputRequest(ApiModel):
    """Input used by a few-shot extraction example."""

    type: ExampleInputKind = Field(
        default=ExampleInputKind.TEXT,
        description="Whether the example input is inline text or a previously uploaded file.",
    )
    text: str | None = Field(default=None, description="Inline example text when type is text.")
    file_id: str | None = Field(
        default=None,
        description="Uploaded example file identifier when type is file.",
    )


class ExampleRequest(ApiModel):
    """Few-shot example pairing representative input with expected structured output."""

    input: ExampleInputRequest | str = Field(description="Representative input for the example.")
    output: dict[str, Any] | str = Field(description="Expected JSON-compatible extraction output.")


class CreateExtractorRequest(ApiModel):
    """Definition used to create a reusable extractor."""

    name: str | None = Field(
        default=None,
        description="Stable URL-safe extractor name. Generated from display_name when omitted.",
        examples=["invoice"],
    )
    display_name: str | None = Field(
        default=None,
        description="Human-readable extractor label. Either this field or name is required.",
        examples=["Invoice"],
    )
    instructions: str = Field(
        description="Natural-language extraction instructions.",
        examples=["Extract the invoice header, supplier, and total exactly as shown."],
    )
    reasoning_effort: ReasoningEffort | None = Field(
        default=None,
        description="Optional reasoning effort passed to models that support it.",
    )
    provider_name: ProviderName | None = Field(
        default=None,
        description="Configured provider to use. The local OpenAI-compatible provider is the default.",
    )
    model: str | None = Field(
        default=None,
        description="Provider model identifier. Required for hosted providers.",
        examples=["gpt-4o-mini"],
    )
    schema_: dict[str, Any] = Field(
        alias="schema",
        description="JSON Schema that every successful extraction result must satisfy.",
    )
    examples: list[ExampleRequest] = Field(
        default_factory=list,
        description="Optional few-shot examples for difficult document types.",
    )

    @model_validator(mode="after")
    def validate_identity(self) -> CreateExtractorRequest:
        if self.display_name is None and self.name is None:
            raise ValueError("provide display_name or name")
        return self


class UpdateExtractorRequest(ApiModel):
    """Partial update for an existing extractor."""

    display_name: str | None = Field(default=None, description="New human-readable label.")
    instructions: str | None = Field(default=None, description="New extraction instructions.")
    # None is a meaningful value here ("use the model's default"); the endpoint
    # checks model_fields_set to tell an explicit null from an absent field.
    reasoning_effort: ReasoningEffort | None = Field(
        default=None,
        description="New reasoning effort; explicit null restores the model default.",
    )
    provider_name: ProviderName | None = Field(default=None, description="New provider selection.")
    model: str | None = Field(
        default=None,
        description="New model selection; explicit null uses the local provider default.",
    )
    schema_: dict[str, Any] | None = Field(
        default=None,
        alias="schema",
        description="Replacement extraction schema.",
    )
    examples: list[ExampleRequest] | None = Field(
        default=None,
        description="Replacement few-shot example set.",
    )


class UpsertExtractorRequest(ApiModel):
    """Complete extractor definition used to create or replace an extractor by reference."""

    name: str | None = Field(
        default=None,
        description="Optional body name. When supplied it must match the path reference.",
    )
    display_name: str = Field(description="Human-readable extractor label.", examples=["Invoice"])
    instructions: str = Field(description="Natural-language extraction instructions.")
    reasoning_effort: ReasoningEffort | None = Field(
        default=None,
        description="Optional reasoning effort passed to models that support it.",
    )
    provider_name: ProviderName | None = Field(
        default=None, description="Configured provider to use."
    )
    model: str | None = Field(default=None, description="Provider model identifier.")
    schema_: dict[str, Any] = Field(
        alias="schema",
        description="JSON Schema that every successful extraction result must satisfy.",
    )
    examples: list[ExampleRequest] = Field(
        default_factory=list,
        description="Optional few-shot examples.",
    )


class CreateJobRequest(ApiModel):
    """Request to enqueue one extraction job."""

    extractor_id: str | None = Field(
        default=None,
        description="Immutable extractor identifier. Supply exactly one extractor selector.",
        examples=["ext_01JZ6QK8M7"],
    )
    extractor_name: str | None = Field(
        default=None,
        description="Stable extractor name. Supply exactly one extractor selector.",
        examples=["invoice"],
    )
    file_id: str | None = Field(
        default=None,
        description="Uploaded file identifier. Supply exactly one input source.",
        examples=["file_01JZ6QK8M7"],
    )
    text: str | None = Field(
        default=None,
        description="Inline text to extract. Supply exactly one input source.",
        examples=["Invoice INV-1001 from Acme GmbH for EUR 42.00."],
    )

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
    """Request to validate a ParseHawk extraction schema."""

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
    """One machine-readable schema validation diagnostic."""

    message: str = Field(description="Human-readable diagnostic message.")
    path: str = Field(default="$", description="JSONPath-like location in the submitted schema.")
    code: str = Field(description="Stable diagnostic code.", examples=["unsupported_keyword"])


class ValidateSchemaResponse(ApiModel):
    """Validation result and canonical schema when accepted."""

    valid: bool = Field(description="Whether the schema is accepted by ParseHawk.")
    schema_: dict[str, Any] | None = Field(
        default=None,
        alias="schema",
        description="Canonical ParseHawk extraction schema when validation succeeds.",
    )
    warnings: list[SchemaDiagnostic] = Field(
        default_factory=list,
        description="Non-blocking diagnostics.",
    )
    errors: list[SchemaDiagnostic] = Field(
        default_factory=list,
        description="Blocking diagnostics that make the schema invalid.",
    )


class FileResponse(ApiModel):
    """Metadata for a file stored by ParseHawk."""

    id: str = Field(description="Immutable file identifier.", examples=["file_01JZ6QK8M7"])
    file_name: str = Field(description="Original upload filename.", examples=["invoice.pdf"])
    content_type: str = Field(
        description="Detected or supplied media type.", examples=["application/pdf"]
    )
    size_bytes: int = Field(description="Stored file size in bytes.", ge=0)
    sha256: str = Field(description="Lowercase SHA-256 digest of the stored bytes.")
    source: FileSource = Field(description="How the file entered ParseHawk.")
    is_example: bool = Field(description="Whether the file ships as a built-in example.")
    created_at: datetime = Field(description="UTC creation time.")

    @classmethod
    def from_domain(cls, file: File) -> FileResponse:
        return cls.model_validate(file)


class ExtractorResponse(ApiModel):
    """Public representation of a reusable extractor."""

    id: str = Field(description="Immutable extractor identifier.")
    name: str = Field(description="Stable URL-safe extractor name.", examples=["invoice"])
    display_name: str = Field(description="Human-readable extractor label.")
    instructions: str = Field(description="Natural-language extraction instructions.")
    reasoning_effort: ReasoningEffort | None = Field(description="Configured reasoning effort.")
    provider_name: ProviderName | None = Field(description="Configured model provider.")
    model: str | None = Field(description="Configured provider model identifier.")
    schema_: dict[str, Any] = Field(alias="schema", description="Extraction result JSON Schema.")
    examples: list[dict[str, Any]] = Field(description="Configured few-shot examples.")
    source: ExtractorSource = Field(description="How the extractor was created.")
    is_prebuilt: bool = Field(description="Whether ParseHawk ships this extractor.")
    created_at: datetime = Field(description="UTC creation time.")
    updated_at: datetime = Field(description="UTC last-update time.")

    @classmethod
    def from_domain(cls, extractor: Extractor) -> ExtractorResponse:
        return cls(
            id=extractor.id,
            name=extractor.name,
            display_name=extractor.display_name,
            instructions=extractor.instructions,
            reasoning_effort=extractor.reasoning_effort,
            provider_name=extractor.provider_name,
            model=extractor.model,
            schema=extractor.schema,
            examples=[example.model_dump() for example in extractor.examples],
            source=extractor.source,
            is_prebuilt=extractor.is_prebuilt,
            created_at=extractor.created_at,
            updated_at=extractor.updated_at,
        )


class ProviderResponse(ApiModel):
    """Non-secret configuration for one model provider."""

    name: ProviderName = Field(description="Stable provider name.")
    base_url: str | None = Field(description="OpenAI-compatible API base URL when applicable.")
    configuration: dict[str, Any] = Field(description="Provider-specific non-secret settings.")
    has_api_key: bool = Field(
        description="Whether ParseHawk has a stored API key for the provider."
    )
    created_at: datetime = Field(description="UTC creation time.")
    updated_at: datetime = Field(description="UTC last-update time.")

    @classmethod
    def from_domain(cls, provider: Provider, *, has_api_key: bool) -> ProviderResponse:
        return cls(
            name=provider.name,
            base_url=provider.base_url,
            configuration=provider.configuration,
            has_api_key=has_api_key,
            created_at=provider.created_at,
            updated_at=provider.updated_at,
        )


class ConfigureProviderRequest(ApiModel):
    """Write-only provider configuration. The API never returns the API key."""

    base_url: str | None = Field(
        default=None,
        description="OpenAI-compatible API base URL.",
        examples=["http://127.0.0.1:11434/v1"],
    )
    configuration: dict[str, Any] | None = Field(
        default=None,
        description="Provider-specific non-secret settings.",
    )
    api_key: str | None = Field(
        default=None,
        description="API key to store securely. It is never returned by the API.",
        json_schema_extra={"writeOnly": True},
    )
    api_key_env: str | None = Field(
        default=None,
        description="Environment variable whose current value should be stored as the API key.",
        examples=["OPENAI_API_KEY"],
    )


class ProviderModelsResponse(ApiModel):
    """Models currently advertised by a configured provider."""

    models: list[str] = Field(description="Provider model identifiers.")


class JobResultResponse(ApiModel):
    """Validated structured output produced by an extraction job."""

    data: dict[str, Any] = Field(description="Result validated against the extractor schema.")

    @classmethod
    def from_domain(cls, result: JobResult) -> JobResultResponse:
        return cls(data=result.data)


class JobErrorResponse(ApiModel):
    """Terminal extraction error stored with a failed job."""

    message: str = Field(description="Human-readable failure message.")
    code: str = Field(description="Stable machine-readable failure code.")

    @classmethod
    def from_domain(cls, error: JobError) -> JobErrorResponse:
        return cls.model_validate(error)


class JobResponse(ApiModel):
    """Current state and eventual result of one extraction job."""

    id: str = Field(description="Immutable job identifier.", examples=["job_01JZ6QK8M7"])
    extractor_id: str = Field(description="Immutable extractor identifier used by the job.")
    file_id: str | None = Field(description="Input file identifier for file-based jobs.")
    source_text: str | None = Field(description="Inline source text for text-based jobs.")
    provider_name_used: ProviderName | None = Field(
        description="Provider selected when execution starts."
    )
    model_used: str | None = Field(description="Model selected when execution starts.")
    status: JobStatus = Field(description="Current job lifecycle state.")
    result: JobResultResponse | None = Field(description="Validated result for completed jobs.")
    error: JobErrorResponse | None = Field(description="Failure details for failed jobs.")
    created_at: datetime = Field(description="UTC creation time.")
    started_at: datetime | None = Field(description="UTC execution start time.")
    completed_at: datetime | None = Field(description="UTC terminal-state time.")

    @classmethod
    def from_domain(cls, job: Job) -> JobResponse:
        return cls(
            id=job.id,
            extractor_id=job.extractor_id,
            file_id=job.file_id,
            source_text=job.source_text,
            provider_name_used=job.provider_name_used,
            model_used=job.model_used,
            status=job.status,
            result=JobResultResponse.from_domain(job.result)
            if job.status == JobStatus.COMPLETED and job.result
            else None,
            error=JobErrorResponse.from_domain(job.error) if job.error else None,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )
