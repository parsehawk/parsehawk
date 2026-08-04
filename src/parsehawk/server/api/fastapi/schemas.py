from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from parsehawk.core.domain.models import (
    ExampleInputKind,
    ExtractionError,
    ExtractionJob,
    ExtractionResult,
    Extractor,
    ExtractorSource,
    File,
    FileSource,
    JobStatus,
    ParseError,
    ParseJob,
    ParsePageResult,
    Parser,
    ParseResult,
    ParserOutputFormat,
    ParserSnapshot,
    ParserSource,
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


class CreateExtractionJobRequest(ApiModel):
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
    def validate_input(self) -> CreateExtractionJobRequest:
        provided_extractors = [self.extractor_id is not None, self.extractor_name is not None]
        if provided_extractors.count(True) != 1:
            raise ValueError("provide exactly one of extractor_id or extractor_name")
        provided_inputs = [self.file_id is not None, self.text is not None]
        if provided_inputs.count(True) != 1:
            raise ValueError("provide exactly one of file_id or text")
        if self.text is not None and not self.text.strip():
            raise ValueError("text input cannot be empty")
        return self


class CreateParserRequest(ApiModel):
    """Definition used to create a reusable document parser."""

    name: str | None = Field(
        default=None,
        description="Stable URL-safe parser name. Generated from display_name when omitted.",
        examples=["document-to-markdown"],
    )
    display_name: str | None = Field(
        default=None,
        description="Human-readable parser label. Either this field or name is required.",
        examples=["Document to Markdown"],
    )
    output_format: ParserOutputFormat = Field(
        default=ParserOutputFormat.MARKDOWN,
        description="Output format produced by the parser. Markdown is the v0.3 format.",
    )
    instructions: str = Field(
        default="",
        description="Optional instructions appended to the document transcription prompt.",
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
        examples=["gpt-5-mini"],
    )

    @model_validator(mode="after")
    def validate_identity(self) -> CreateParserRequest:
        if self.display_name is None and self.name is None:
            raise ValueError("provide display_name or name")
        return self


class UpdateParserRequest(ApiModel):
    """Partial update for an existing parser."""

    display_name: str | None = Field(default=None, description="New human-readable label.")
    output_format: ParserOutputFormat | None = Field(
        default=None,
        description="New parser output format.",
    )
    instructions: str | None = Field(default=None, description="New parsing instructions.")
    reasoning_effort: ReasoningEffort | None = Field(
        default=None,
        description="New reasoning effort; explicit null restores the model default.",
    )
    provider_name: ProviderName | None = Field(default=None, description="New provider selection.")
    model: str | None = Field(
        default=None,
        description="New model selection; explicit null uses the local provider default.",
    )


class UpsertParserRequest(ApiModel):
    """Complete parser definition used to create or replace a parser by reference."""

    name: str | None = Field(
        default=None,
        description="Optional body name. When supplied it must match the path reference.",
    )
    display_name: str = Field(
        description="Human-readable parser label.",
        examples=["Document to Markdown"],
    )
    output_format: ParserOutputFormat = Field(
        default=ParserOutputFormat.MARKDOWN,
        description="Output format produced by the parser.",
    )
    instructions: str = Field(default="", description="Document parsing instructions.")
    reasoning_effort: ReasoningEffort | None = Field(
        default=None,
        description="Optional reasoning effort passed to models that support it.",
    )
    provider_name: ProviderName | None = Field(
        default=None,
        description="Configured provider to use.",
    )
    model: str | None = Field(default=None, description="Provider model identifier.")


class CreateParseJobRequest(ApiModel):
    """Request to enqueue one document parsing job."""

    parser_id: str | None = Field(
        default=None,
        description="Immutable parser identifier. Supply exactly one parser selector.",
        examples=["parser_01JZ6QK8M7"],
    )
    parser_name: str | None = Field(
        default=None,
        description="Stable parser name. Supply exactly one parser selector.",
        examples=["document-to-markdown"],
    )
    file_id: str = Field(
        description="Uploaded PDF, JPG/JPEG, or PNG file identifier.",
        examples=["file_01JZ6QK8M7"],
    )

    @model_validator(mode="after")
    def validate_parser(self) -> CreateParseJobRequest:
        provided = [self.parser_id is not None, self.parser_name is not None]
        if provided.count(True) != 1:
            raise ValueError("provide exactly one of parser_id or parser_name")
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


class ParserResponse(ApiModel):
    """Public representation of a reusable parser."""

    id: str = Field(description="Immutable parser identifier.")
    name: str = Field(description="Stable URL-safe parser name.")
    display_name: str = Field(description="Human-readable parser label.")
    output_format: ParserOutputFormat = Field(description="Configured parser output format.")
    instructions: str = Field(description="Document parsing instructions.")
    reasoning_effort: ReasoningEffort | None = Field(description="Configured reasoning effort.")
    provider_name: ProviderName | None = Field(description="Configured model provider.")
    model: str | None = Field(description="Configured provider model identifier.")
    source: ParserSource = Field(description="How the parser was created.")
    is_prebuilt: bool = Field(description="Whether ParseHawk ships this parser.")
    created_at: datetime = Field(description="UTC creation time.")
    updated_at: datetime = Field(description="UTC last-update time.")

    @classmethod
    def from_domain(cls, parser: Parser) -> ParserResponse:
        return cls(
            id=parser.id,
            name=parser.name,
            display_name=parser.display_name,
            output_format=parser.output_format,
            instructions=parser.instructions,
            reasoning_effort=parser.reasoning_effort,
            provider_name=parser.provider_name,
            model=parser.model,
            source=parser.source,
            is_prebuilt=parser.is_prebuilt,
            created_at=parser.created_at,
            updated_at=parser.updated_at,
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


class ExtractionResultResponse(ApiModel):
    """Validated structured output produced by an extraction job."""

    data: dict[str, Any] = Field(description="Result validated against the extractor schema.")

    @classmethod
    def from_domain(cls, result: ExtractionResult) -> ExtractionResultResponse:
        return cls(data=result.data)


class ExtractionErrorResponse(ApiModel):
    """Terminal extraction error stored with a failed job."""

    message: str = Field(description="Human-readable failure message.")
    code: str = Field(description="Stable machine-readable failure code.")

    @classmethod
    def from_domain(cls, error: ExtractionError) -> ExtractionErrorResponse:
        return cls.model_validate(error)


class ExtractionJobResponse(ApiModel):
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
    result: ExtractionResultResponse | None = Field(
        description="Validated result for completed jobs."
    )
    error: ExtractionErrorResponse | None = Field(description="Failure details for failed jobs.")
    created_at: datetime = Field(description="UTC creation time.")
    started_at: datetime | None = Field(description="UTC execution start time.")
    completed_at: datetime | None = Field(description="UTC terminal-state time.")

    @classmethod
    def from_domain(cls, job: ExtractionJob) -> ExtractionJobResponse:
        return cls(
            id=job.id,
            extractor_id=job.extractor_id,
            file_id=job.file_id,
            source_text=job.source_text,
            provider_name_used=job.provider_name_used,
            model_used=job.model_used,
            status=job.status,
            result=ExtractionResultResponse.from_domain(job.result)
            if job.status == JobStatus.COMPLETED and job.result
            else None,
            error=ExtractionErrorResponse.from_domain(job.error) if job.error else None,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )


class ParserSnapshotResponse(ApiModel):
    """Immutable parser configuration captured when a parse job is enqueued."""

    parser_id: str = Field(description="Immutable parser identifier.")
    name: str = Field(description="Stable parser name at enqueue time.")
    display_name: str = Field(description="Parser label at enqueue time.")
    output_format: ParserOutputFormat = Field(description="Output format at enqueue time.")
    instructions: str = Field(description="Parsing instructions at enqueue time.")
    reasoning_effort: ReasoningEffort | None = Field(
        description="Reasoning effort at enqueue time."
    )
    provider_name: ProviderName | None = Field(description="Provider selection at enqueue time.")
    model: str | None = Field(description="Model selection at enqueue time.")

    @classmethod
    def from_domain(cls, snapshot: ParserSnapshot) -> ParserSnapshotResponse:
        return cls.model_validate(snapshot)


class ParsePageResultResponse(ApiModel):
    """Markdown output for one source page."""

    page_number: int = Field(description="One-based source page number.", ge=1)
    content: str = Field(description="Markdown transcription for this page.")

    @classmethod
    def from_domain(cls, page: ParsePageResult) -> ParsePageResultResponse:
        return cls.model_validate(page)


class ParseResultResponse(ApiModel):
    """Canonical Markdown result for a completed parse job."""

    format: ParserOutputFormat = Field(description="Result content format.")
    content: str = Field(
        description="All page content joined by an HTML page-break comment.",
    )
    page_count: int = Field(description="Number of parsed source pages.", ge=1)
    pages: list[ParsePageResultResponse] = Field(
        description="Canonical one-based per-page Markdown output.",
    )

    @classmethod
    def from_domain(cls, result: ParseResult) -> ParseResultResponse:
        return cls(
            format=result.format,
            content=result.content,
            page_count=result.page_count,
            pages=[ParsePageResultResponse.from_domain(page) for page in result.pages],
        )


class ParseErrorResponse(ApiModel):
    """Terminal parsing error stored with a failed job."""

    message: str = Field(description="Human-readable failure message.")
    code: str = Field(description="Stable machine-readable failure code.")

    @classmethod
    def from_domain(cls, error: ParseError) -> ParseErrorResponse:
        return cls.model_validate(error)


class ParseJobResponse(ApiModel):
    """Current state and eventual Markdown result of one parse job."""

    id: str = Field(description="Immutable parse job identifier.")
    parser_id: str = Field(description="Immutable parser identifier used by the job.")
    file_id: str = Field(description="Input file identifier.")
    parser_snapshot: ParserSnapshotResponse = Field(
        description="Immutable parser configuration captured when the job was created.",
    )
    provider_name_used: ProviderName | None = Field(
        description="Provider selected when execution starts.",
    )
    model_used: str | None = Field(description="Model selected when execution starts.")
    reasoning_effort_used: ReasoningEffort | None = Field(
        description="Reasoning effort selected when execution starts.",
    )
    model_adapter_used: str | None = Field(
        description="Parsing request adapter selected when execution starts.",
    )
    status: JobStatus = Field(description="Current job lifecycle state.")
    result: ParseResultResponse | None = Field(description="Markdown result for completed jobs.")
    error: ParseErrorResponse | None = Field(description="Failure details for failed jobs.")
    created_at: datetime = Field(description="UTC creation time.")
    started_at: datetime | None = Field(description="UTC execution start time.")
    completed_at: datetime | None = Field(description="UTC terminal-state time.")

    @classmethod
    def from_domain(cls, job: ParseJob) -> ParseJobResponse:
        return cls(
            id=job.id,
            parser_id=job.parser_id,
            file_id=job.file_id,
            parser_snapshot=ParserSnapshotResponse.from_domain(job.parser_snapshot),
            provider_name_used=job.provider_name_used,
            model_used=job.model_used,
            reasoning_effort_used=job.reasoning_effort_used,
            model_adapter_used=job.model_adapter_used,
            status=job.status,
            result=(
                ParseResultResponse.from_domain(job.result)
                if job.status == JobStatus.COMPLETED and job.result
                else None
            ),
            error=ParseErrorResponse.from_domain(job.error) if job.error else None,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )
