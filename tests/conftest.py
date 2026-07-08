from __future__ import annotations

import re

import pytest

from parsehawk.config import DEFAULT_VLLM_MODEL
from parsehawk.core.application.ports import (
    ExtractionRequest,
    ExtractionResponse,
    ResolvedExecutionConfig,
)
from parsehawk.core.domain.models import Extractor, ProviderName


class MockInference:
    """Deterministic in-process extraction engine for tests.

    Replaces the former production heuristic engine: it returns predictable
    receipt output so the API/worker integration tests can run without a real
    model runtime.
    """

    def extract(
        self,
        request: ExtractionRequest,
        cancellation_check=None,
    ) -> ExtractionResponse:
        text = request.source_text
        if "receipt_id" in request.schema.get("properties", {}):
            data: dict[str, object] = {
                "merchant_name": _first_non_empty_line(text),
                "receipt_id": _first_match(text, [r"Receipt\s*#\s*([A-Z0-9-]+)"]),
                "date": _first_match(text, [r"Date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})"]),
                "total": _first_number(text, [r"^Total\s+EUR\s+([0-9]+(?:\.[0-9]+)?)"]),
                "currency": _first_match(text, [r"^Total\s+(EUR|USD|GBP)\s+"]),
            }
            return _response(data)

        return _response({})


def _response(data: dict[str, object]) -> ExtractionResponse:
    return ExtractionResponse(data=data)


def _first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1)
    return None


def _first_number(text: str, patterns: list[str]) -> float | None:
    value = _first_match(text, patterns)
    return float(value) if value is not None else None


def _first_non_empty_line(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


@pytest.fixture(autouse=True)
def _disable_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite hermetic: no usage analytics or trace export during tests.

    Telemetry/tracing-specific tests opt back in by clearing these vars themselves.
    """
    monkeypatch.setenv("PARSEHAWK_TELEMETRY_DISABLED", "1")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")


class _StubEngineFactory:
    """Engine factory that hands every extractor the same in-process engine."""

    def __init__(self, engine: MockInference) -> None:
        self._engine = engine

    def resolve_extractor_config(self, extractor: Extractor) -> ResolvedExecutionConfig:
        return ResolvedExecutionConfig(
            provider_name=extractor.provider_name or ProviderName.OPENAI_COMPATIBLE,
            model=extractor.model or DEFAULT_VLLM_MODEL,
        )

    def for_extractor(self, extractor: Extractor) -> MockInference:
        return self._engine


@pytest.fixture
def mock_inference(monkeypatch: pytest.MonkeyPatch) -> MockInference:
    """Route build_container/create_app through the deterministic MockInference engine."""
    engine = MockInference()
    monkeypatch.setattr(
        "parsehawk.server.container.EngineFactory",
        lambda *args, **kwargs: _StubEngineFactory(engine),
    )
    return engine
