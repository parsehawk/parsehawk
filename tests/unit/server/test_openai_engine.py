from __future__ import annotations

from typing import Any, cast

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, OpenAI

from parsehawk.core.application.ports import ExtractionRequest
from parsehawk.core.domain.errors import ProviderRequestError
from parsehawk.server.runtime.inference.generic import (
    REASONING_CHAT_TEMPLATE_KWARGS,
    REASONING_EFFORT,
    RESPONSE_FORMAT_JSON_OBJECT,
    RESPONSE_FORMAT_NONE,
    build_generic_chat_payload,
)
from parsehawk.server.runtime.inference.openai_engine import (
    OpenAIEngineConfig,
    OpenAIExtractionEngine,
    select_adapter,
)

NUEXTRACT_MODEL = "numind/NuExtract3-W4A16"


def make_request(*, enable_thinking: bool = False, examples: list[dict[str, Any]] | None = None):
    return ExtractionRequest(
        source_text="Receipt #2",
        instructions="Extract the receipt id.",
        enable_thinking=enable_thinking,
        schema={
            "type": "object",
            "properties": {"receipt_id": {"type": "string"}},
            "required": ["receipt_id"],
        },
        examples=examples or [],
    )


class _FakeCompletions:
    def __init__(self, data: dict[str, Any] | None, error: Exception | None = None) -> None:
        self._data = data
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return _FakeCompletion(self._data or {})


class _FakeCompletion:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def model_dump(self) -> dict[str, Any]:
        return self._data


class _FakeClient:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.chat = type("Chat", (), {"completions": completions})()


def _client_returning(content: str) -> tuple[_FakeClient, _FakeCompletions]:
    completions = _FakeCompletions({"choices": [{"message": {"content": content}}]})
    return _FakeClient(completions), completions


def test_select_adapter_matches_exact_nuextract_models() -> None:
    assert select_adapter("numind/NuExtract3") == "nuextract"
    assert select_adapter(NUEXTRACT_MODEL) == "nuextract"
    assert select_adapter("numind/NuExtract3-mlx-8bits") == "nuextract"
    # A near-miss substring is NOT treated as NuExtract.
    assert select_adapter("numind/NuExtract3-Turbo") == "generic"
    assert select_adapter("gpt-4o-mini") == "generic"


def test_nuextract_adapter_sends_chat_template_kwargs_in_extra_body() -> None:
    client, completions = _client_returning('{"receipt_id": "2"}')
    engine = OpenAIExtractionEngine(
        OpenAIEngineConfig(model=NUEXTRACT_MODEL), client=cast(OpenAI, client)
    )

    result = engine.extract(make_request())

    assert result.data == {"receipt_id": "2"}
    (call,) = completions.calls
    assert call["model"] == NUEXTRACT_MODEL
    assert call["extra_body"]["chat_template_kwargs"]["template"]
    assert call["response_format"]["type"] == "json_schema"


def test_generic_adapter_builds_system_prompt_without_nuextract_kwargs() -> None:
    client, completions = _client_returning('{"receipt_id": "2"}')
    engine = OpenAIExtractionEngine(
        OpenAIEngineConfig(model="gpt-4o-mini"), client=cast(OpenAI, client)
    )

    result = engine.extract(make_request())

    assert result.data == {"receipt_id": "2"}
    (call,) = completions.calls
    assert "extra_body" not in call
    system = call["messages"][0]
    assert system["role"] == "system"
    assert "Semantic type reference" in system["content"]
    assert "verbatim-string" in system["content"]  # from vendored TYPES.md
    assert "Template:" in system["content"]
    assert "chat_template_kwargs" not in str(call)
    assert all(message["role"] != "developer" for message in call["messages"])


def test_generic_payload_response_format_modes_and_examples() -> None:
    request = make_request(
        examples=[{"input": {"type": "text", "text": "Receipt #7"}, "output": {"receipt_id": "7"}}]
    )

    payload, extra_body = build_generic_chat_payload(
        request, model="gpt-4o-mini", max_tokens=256, temperature=0.1
    )
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert extra_body == {}
    roles = [message["role"] for message in payload["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert payload["messages"][2]["content"] == '{"receipt_id": "7"}'

    obj, _ = build_generic_chat_payload(
        request,
        model="m",
        max_tokens=1,
        temperature=0.0,
        response_format_mode=RESPONSE_FORMAT_JSON_OBJECT,
    )
    assert obj["response_format"] == {"type": "json_object"}

    none_payload, _ = build_generic_chat_payload(
        request,
        model="m",
        max_tokens=1,
        temperature=0.0,
        response_format_mode=RESPONSE_FORMAT_NONE,
    )
    assert "response_format" not in none_payload


def test_generic_payload_routes_reasoning() -> None:
    thinking = make_request(enable_thinking=True)

    effort, _ = build_generic_chat_payload(
        thinking,
        model="o3",
        max_tokens=1,
        temperature=0.0,
        reasoning_mode=REASONING_EFFORT,
        reasoning_effort="high",
    )
    assert effort["reasoning_effort"] == "high"

    _, extra_body = build_generic_chat_payload(
        thinking,
        model="qwen",
        max_tokens=1,
        temperature=0.0,
        reasoning_mode=REASONING_CHAT_TEMPLATE_KWARGS,
    )
    assert extra_body["chat_template_kwargs"] == {"enable_thinking": True}


def test_extract_reads_reasoning_content_fallback() -> None:
    completions = _FakeCompletions(
        {"choices": [{"message": {"content": None, "reasoning_content": '{"receipt_id": "9"}'}}]}
    )
    engine = OpenAIExtractionEngine(
        OpenAIEngineConfig(model="gpt-4o-mini"), client=cast(OpenAI, _FakeClient(completions))
    )

    assert engine.extract(make_request()).data == {"receipt_id": "9"}


def test_provider_status_error_becomes_provider_request_error() -> None:
    request = httpx.Request("POST", "https://api.test/v1/chat/completions")
    response = httpx.Response(404, request=request, json={"error": {"message": "model not found"}})
    completions = _FakeCompletions(
        None, error=APIStatusError("model not found", response=response, body=None)
    )
    engine = OpenAIExtractionEngine(
        OpenAIEngineConfig(model="gpt-4o-mini"), client=cast(OpenAI, _FakeClient(completions))
    )

    with pytest.raises(ProviderRequestError) as excinfo:
        engine.extract(make_request())
    assert excinfo.value.status_code == 404
    assert "model not found" in str(excinfo.value)


def test_provider_connection_error_becomes_provider_request_error() -> None:
    request = httpx.Request("POST", "https://api.test/v1/chat/completions")
    completions = _FakeCompletions(None, error=APIConnectionError(request=request))
    engine = OpenAIExtractionEngine(
        OpenAIEngineConfig(model="gpt-4o-mini"), client=cast(OpenAI, _FakeClient(completions))
    )

    with pytest.raises(ProviderRequestError) as excinfo:
        engine.extract(make_request())
    assert excinfo.value.status_code is None
    assert "unreachable" in str(excinfo.value)
