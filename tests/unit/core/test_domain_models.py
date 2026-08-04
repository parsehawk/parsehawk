import hashlib

import pytest
from pydantic import ValidationError

from parsehawk.core.domain import ids
from parsehawk.core.domain.ids import new_id
from parsehawk.core.domain.models import (
    NUEXTRACT3_MODELS,
    PAGE_BREAK_SEPARATOR,
    Example,
    ExampleInput,
    ExampleInputKind,
    ExtractionJob,
    ExtractionResult,
    Extractor,
    ExtractorSource,
    File,
    FileSource,
    JobStatus,
    ParseJob,
    ParsePageResult,
    Parser,
    ParseResult,
    ParserOutputFormat,
    ParserSnapshot,
    ParserSource,
    Provider,
    ProviderName,
    ValidationIssue,
    extractor_name_suffix,
    parser_name_suffix,
    slugify_extractor_name,
    slugify_parser_name,
    validate_parser_name,
)


def test_job_state_transitions_and_result_validity() -> None:
    job = ExtractionJob(
        id="job_1",
        extractor_id="extractor_1",
        file_id="file_1",
        status=JobStatus.QUEUED,
    )

    running = job.mark_running()
    assert running.status == JobStatus.RUNNING
    assert running.started_at is not None
    configured = running.with_execution_config(
        provider_name=ProviderName.OPENAI_COMPATIBLE,
        model="numind/NuExtract3-W4A16",
    )
    assert configured.provider_name_used == ProviderName.OPENAI_COMPATIBLE
    assert configured.model_used == "numind/NuExtract3-W4A16"

    valid_result = ExtractionResult(data={"receipt_id": "2"})
    completed = configured.mark_completed(valid_result)
    assert completed.status == JobStatus.COMPLETED
    assert completed.completed_at is not None
    assert completed.result is valid_result
    assert valid_result.valid is True

    invalid_result = ExtractionResult(
        data={},
        validation_errors=[ValidationIssue(path="receipt_id", message="required")],
    )
    assert invalid_result.valid is False

    failed = running.mark_failed("boom", code="custom")
    assert failed.status == JobStatus.FAILED
    assert failed.error is not None
    assert failed.error.message == "boom"
    assert failed.error.code == "custom"

    deleting = running.mark_deleting()
    assert deleting.status == JobStatus.DELETING
    assert deleting.completed_at is None

    canceled = running.mark_canceled()
    assert canceled.status == JobStatus.CANCELED
    assert canceled.completed_at is not None


def test_new_id_uses_prefix() -> None:
    generated = new_id("file")
    assert generated.startswith("file_")
    assert len(generated) == len("file_") + 26


def test_new_id_is_sortable_within_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ids.time, "time_ns", lambda: 1_700_000_000_000_000_000)
    monkeypatch.setattr(ids.secrets, "randbits", lambda bits: 123)
    monkeypatch.setattr(ids, "_last_timestamp_ms", -1)
    monkeypatch.setattr(ids, "_last_random", 0)

    first = new_id("job")
    second = new_id("job")

    assert first < second


def test_new_id_advances_timestamp_when_random_suffix_wraps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamp_ms = 1_700_000_000_000
    monkeypatch.setattr(ids.time, "time_ns", lambda: timestamp_ms * 1_000_000)
    monkeypatch.setattr(ids, "_last_timestamp_ms", timestamp_ms)
    monkeypatch.setattr(ids, "_last_random", ids._MAX_RANDOM)

    new_id("job")

    assert ids._last_timestamp_ms == timestamp_ms + 1


def test_source_metadata_defaults_and_flags() -> None:
    uploaded_file = File(
        id="file_1",
        file_name="document.md",
        content_type="text/markdown",
        size_bytes=5,
        sha256="abc",
        storage_path="/tmp/document.md",
    )
    example_file = uploaded_file.model_copy(update={"source": FileSource.EXAMPLE})
    extractor = Extractor(
        id="extractor_1",
        name="Receipt",
        instructions="Extract receipt fields.",
        schema={"type": "object"},
    )
    prebuilt = extractor.model_copy(update={"source": ExtractorSource.PREBUILT})

    assert uploaded_file.source == FileSource.USER
    assert uploaded_file.is_example is False
    assert example_file.is_example is True
    assert extractor.source == ExtractorSource.USER
    assert extractor.is_prebuilt is False
    assert extractor.model_dump()["schema"] == {"type": "object"}
    assert "schema_" not in extractor.model_dump()
    assert "nuextract_template" not in extractor.model_dump()
    assert prebuilt.is_prebuilt is True


def test_provider_defaults_and_configuration() -> None:
    provider = Provider(name=ProviderName.OPENAI_COMPATIBLE)
    assert provider.name == ProviderName.OPENAI_COMPATIBLE
    assert provider.name.value == "openai_compatible_api"
    assert provider.base_url is None
    assert provider.configuration == {}
    assert provider.created_at is not None and provider.updated_at is not None

    foundry = Provider(
        name=ProviderName.MICROSOFT_FOUNDRY,
        base_url="https://res.services.ai.azure.com/openai/v1/",
        configuration={
            "project_url": "https://res.services.ai.azure.com/api/projects/project",
        },
    )
    assert foundry.base_url == "https://res.services.ai.azure.com/openai/v1/"
    assert foundry.configuration == {
        "project_url": "https://res.services.ai.azure.com/api/projects/project"
    }
    assert foundry.project_url == "https://res.services.ai.azure.com/api/projects/project"

    empty_foundry = Provider(
        name=ProviderName.MICROSOFT_FOUNDRY,
        configuration={"project_url": " "},
    )
    assert empty_foundry.configuration == {}

    none_foundry = Provider(
        name=ProviderName.MICROSOFT_FOUNDRY,
        configuration={"project_url": None},
    )
    assert none_foundry.configuration == {}

    with pytest.raises(ValidationError):
        Provider(name=ProviderName.OPENAI, configuration={"project_url": "https://example.test"})

    with pytest.raises(ValidationError):
        Provider(name=ProviderName.MICROSOFT_FOUNDRY, configuration={"api_version": "v1"})

    with pytest.raises(ValidationError):
        Provider(name=ProviderName.MICROSOFT_FOUNDRY, configuration={"project_url": 1})

    with pytest.raises(ValidationError):
        Provider.model_validate({"base_url": "https://example.test/v1"})

    with pytest.raises(ValidationError):
        Provider.model_validate({"name": "not_a_provider"})


def test_extractor_carries_provider_and_model() -> None:
    extractor = Extractor(
        id="extractor_1",
        name="Receipt",
        instructions="Extract receipt fields.",
        schema={"type": "object"},
    )
    assert extractor.provider_name is None
    assert extractor.model is None

    configured = extractor.model_copy(
        update={"provider_name": ProviderName.OPENAI, "model": "gpt-4o-mini"}
    )
    assert configured.provider_name == ProviderName.OPENAI
    assert configured.model == "gpt-4o-mini"
    dumped = configured.model_dump()
    assert dumped["provider_name"] == "openai"
    assert dumped["model"] == "gpt-4o-mini"


def test_extractor_name_validation_and_slug_generation() -> None:
    for name in ("receipt", "invoice_v1", "invoice-v1", "bank-statement-ocr"):
        extractor = Extractor(
            id=f"extractor_{name.replace('-', '_')}",
            name=name,
            display_name="Label",
            instructions="i",
            schema={"type": "object"},
        )
        assert extractor.name == name

    for name in (
        "InvoiceV1",
        "invoice v1",
        "-invoice",
        "invoice-",
        "invoice.v1",
        "rechnung/2026",
        "extractor_receipt",
    ):
        with pytest.raises(ValidationError):
            Extractor(
                id="extractor_bad",
                name=name,
                display_name="Label",
                instructions="i",
                schema={"type": "object"},
            )

    assert slugify_extractor_name("Invoice Extractor V1") == "invoice-extractor-v1"
    assert slugify_extractor_name("!!!") == "extractor"


def test_extractor_rejects_blank_display_name_and_suffixes_plain_ids() -> None:
    with pytest.raises(ValidationError):
        Extractor(
            id="extractor_bad",
            name="receipt",
            display_name=" ",
            instructions="i",
            schema={"type": "object"},
        )

    assert extractor_name_suffix("abc123456") == hashlib.sha256(b"abc123456").hexdigest()[:8]
    assert extractor_name_suffix("extractor_01kwjg0q5932zneyp7hhwr57ey") != extractor_name_suffix(
        "extractor_01kwjg0q5932zneyp7hhwr57ez"
    )


def test_nuextract3_model_set() -> None:
    assert "numind/NuExtract3-W4A16" in NUEXTRACT3_MODELS
    assert "numind/NuExtract3" in NUEXTRACT3_MODELS
    assert "gpt-4o-mini" not in NUEXTRACT3_MODELS
    assert len(NUEXTRACT3_MODELS) == 11


def test_parser_validation_and_snapshot() -> None:
    parser = Parser(
        id="parser_1",
        name="document-to-markdown",
        display_name="Document to Markdown",
        instructions="Preserve footnotes.",
        provider_name=ProviderName.OPENAI_COMPATIBLE,
        source=ParserSource.PREBUILT,
    )

    assert parser.output_format == ParserOutputFormat.MARKDOWN
    assert parser.is_prebuilt is True
    assert slugify_parser_name("Legal Document Parser") == "legal-document-parser"
    assert ParserSnapshot.from_parser(parser).parser_id == parser.id

    with pytest.raises(ValidationError):
        Parser(
            id="parser_bad",
            name="Parser Bad",
            display_name="Parser",
        )
    with pytest.raises(ValidationError):
        Parser(
            id="parser_blank",
            name="parser-blank",
            display_name=" ",
        )
    with pytest.raises(ValidationError):
        ParserSnapshot(
            parser_id=parser.id,
            name=parser.name,
            display_name=" ",
            output_format=ParserOutputFormat.MARKDOWN,
            instructions="",
        )

    with pytest.raises(ValueError, match="reserved parser_ prefix"):
        validate_parser_name("parser_reserved")
    with pytest.raises(ValueError, match="must be 1-64"):
        validate_parser_name("Invalid Parser")
    assert slugify_parser_name("☃") == "parser"
    assert parser_name_suffix("parser_1") == hashlib.sha256(b"parser_1").hexdigest()[:8]


def test_parse_result_derives_complete_document_from_contiguous_pages() -> None:
    result = ParseResult(
        pages=[
            ParsePageResult(page_number=1, content="# First"),
            ParsePageResult(page_number=2, content="## Second"),
        ]
    )

    assert result.content == f"# First{PAGE_BREAK_SEPARATOR}## Second"
    assert result.page_count == 2
    assert result.model_dump()["content"] == result.content

    with pytest.raises(ValidationError, match="at least one page"):
        ParseResult(pages=[])
    with pytest.raises(ValidationError, match="contiguous"):
        ParseResult(
            pages=[
                ParsePageResult(page_number=1, content="one"),
                ParsePageResult(page_number=3, content="three"),
            ]
        )


def test_parse_job_state_transitions_and_execution_metadata() -> None:
    parser = Parser(
        id="parser_1",
        name="document-to-markdown",
        display_name="Document to Markdown",
    )
    job = ParseJob(
        id="parse_job_1",
        parser_id=parser.id,
        file_id="file_1",
        parser_snapshot=ParserSnapshot.from_parser(parser),
        status=JobStatus.QUEUED,
    )

    running = job.mark_running().with_execution_config(
        provider_name=ProviderName.OPENAI_COMPATIBLE,
        model="numind/NuExtract3-W4A16",
        reasoning_effort=None,
        model_adapter="nuextract_markdown",
    )
    completed = running.mark_completed(
        ParseResult(pages=[ParsePageResult(page_number=1, content="# Document")])
    )

    assert completed.status == JobStatus.COMPLETED
    assert completed.result is not None and completed.result.content == "# Document"
    assert completed.provider_name_used == ProviderName.OPENAI_COMPATIBLE
    assert completed.model_adapter_used == "nuextract_markdown"

    failed = running.mark_failed("provider failed", code="provider_error")
    assert failed.status == JobStatus.FAILED
    assert failed.error is not None and failed.error.code == "provider_error"
    assert running.mark_canceling().status == JobStatus.CANCELING
    assert running.mark_deleting().status == JobStatus.DELETING
    canceled = running.mark_canceled()
    assert canceled.status == JobStatus.CANCELED
    assert canceled.completed_at is not None


def test_example_input_validation_and_legacy_text_migration() -> None:
    legacy = Example.model_validate({"input": "hello", "output": {"receipt_id": "2"}})
    assert legacy.input.type == ExampleInputKind.TEXT
    assert legacy.input.text == "hello"

    file_input = ExampleInput(type=ExampleInputKind.FILE, file_id="file_1")
    assert file_input.file_id == "file_1"

    with pytest.raises(ValidationError):
        ExampleInput(type=ExampleInputKind.FILE)

    with pytest.raises(ValidationError):
        ExampleInput(type=ExampleInputKind.TEXT, text="hello", file_id="file_1")

    with pytest.raises(ValidationError):
        ExampleInput(type=ExampleInputKind.TEXT)

    with pytest.raises(ValidationError):
        ExampleInput(type=ExampleInputKind.FILE, file_id="file_1", text="hello")
