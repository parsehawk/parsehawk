from __future__ import annotations

import pytest
from pydantic import ValidationError

from parsehawk.core.domain.models import (
    Extractor,
    ExtractorSource,
    File,
    FileSource,
    JobStatus,
    ParseJob,
    ParsePageResult,
    Parser,
    ParseResult,
    ParserSnapshot,
    ParserSource,
    ReasoningEffort,
)
from parsehawk.server.api.fastapi.schemas import (
    ExtractorResponse,
    FileResponse,
    ParseJobResponse,
    ParserResponse,
)


def test_response_helpers_only_emit_public_file_fields() -> None:
    file = File(
        id="file_1",
        file_name="receipt.md",
        content_type="text/markdown",
        size_bytes=12,
        sha256="abc123",
        storage_path="/private/receipt.md",
        source=FileSource.EXAMPLE,
        seed_key="fixture:receipt",
        seed_version=1,
    )

    payload = FileResponse.from_domain(file).model_dump(mode="json")

    assert payload["is_example"] is True
    assert "storage_path" not in payload
    assert "seed_key" not in payload
    assert "seed_version" not in payload

    with pytest.raises(ValidationError):
        FileResponse.model_validate({**payload, "storage_path": "/private/receipt.md"})


def test_response_helpers_only_emit_public_extractor_fields() -> None:
    extractor = Extractor(
        id="extractor_1",
        name="receipt",
        display_name="Receipt",
        instructions="Extract receipt fields.",
        reasoning_effort=ReasoningEffort.MEDIUM,
        schema={"type": "object", "properties": {}},
        examples=[],
        source=ExtractorSource.PREBUILT,
        seed_key="prebuilt:receipt:v1",
        seed_version=1,
    )

    payload = ExtractorResponse.from_domain(extractor).model_dump(by_alias=True, mode="json")

    assert payload["is_prebuilt"] is True
    assert payload["schema"] == {"type": "object", "properties": {}}
    assert "schema_" not in payload
    assert "seed_key" not in payload
    assert "seed_version" not in payload

    with pytest.raises(ValidationError):
        ExtractorResponse.model_validate({**payload, "seed_key": "prebuilt:receipt:v1"})


def test_parser_and_parse_job_responses_emit_public_page_contract() -> None:
    parser = Parser(
        id="parser_1",
        name="document-to-markdown",
        display_name="Document to Markdown",
        source=ParserSource.PREBUILT,
        seed_key="prebuilt:document-to-markdown:v1",
        seed_version=1,
    )
    parser_payload = ParserResponse.from_domain(parser).model_dump(mode="json")
    assert parser_payload["is_prebuilt"] is True
    assert "seed_key" not in parser_payload

    job = ParseJob(
        id="parse_job_1",
        parser_id=parser.id,
        file_id="file_1",
        parser_snapshot=ParserSnapshot.from_parser(parser),
        status=JobStatus.COMPLETED,
        result=ParseResult(
            pages=[
                ParsePageResult(page_number=1, content="# One"),
                ParsePageResult(page_number=2, content="## Two"),
            ]
        ),
    )
    payload = ParseJobResponse.from_domain(job).model_dump(mode="json")
    assert payload["result"] == {
        "format": "markdown",
        "content": "# One\n\n<!-- page-break -->\n\n## Two",
        "page_count": 2,
        "pages": [
            {"page_number": 1, "content": "# One"},
            {"page_number": 2, "content": "## Two"},
        ],
    }
    assert "seed_key" not in payload["parser_snapshot"]
