from __future__ import annotations

import pytest
from pydantic import ValidationError

from parsehawk.core.domain.models import (
    Extractor,
    ExtractorSource,
    File,
    FileSource,
    ReasoningEffort,
)
from parsehawk.server.api.fastapi.schemas import ExtractorResponse, FileResponse


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
