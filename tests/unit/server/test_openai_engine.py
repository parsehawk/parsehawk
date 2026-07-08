from __future__ import annotations

from contextlib import contextmanager
from typing import Any, cast

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, OpenAI

from parsehawk.core.application.ports import ExtractionRequest
from parsehawk.core.domain.errors import ExtractionCancelled, ProviderRequestError
from parsehawk.server.runtime.inference import openai_engine as openai_engine_module
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
        self.streams: list[_FakeStream] = []
        self.chunks: list[dict[str, Any]] | None = None

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        if kwargs.get("stream"):
            stream = _FakeStream(
                self.chunks if self.chunks is not None else _stream_chunks(self._data or {})
            )
            self.streams.append(stream)
            return stream
        return _FakeCompletion(self._data or {})


class _FakeCompletion:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def model_dump(self) -> dict[str, Any]:
        return self._data


class _FakeChunk:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def model_dump(self) -> dict[str, Any]:
        return self._data


class _FakeStream:
    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self._chunks = chunks
        self.closed = False

    def __iter__(self):
        for chunk in self._chunks:
            yield _FakeChunk(chunk)

    def close(self) -> None:
        self.closed = True


class _FakeClient:
    def __init__(self, completions: Any) -> None:
        self.chat = type("Chat", (), {"completions": completions})()


def _client_returning(content: str) -> tuple[_FakeClient, _FakeCompletions]:
    completions = _FakeCompletions({"choices": [{"message": {"content": content}}]})
    return _FakeClient(completions), completions


def _stream_chunks(data: dict[str, Any]) -> list[dict[str, Any]]:
    message = (data.get("choices") or [{"message": {}}])[0].get("message", {})
    chunks: list[dict[str, Any]] = []
    for field in ("content", "reasoning_content"):
        value = message.get(field)
        if not isinstance(value, str):
            continue
        split_at = max(1, len(value) // 2)
        for part in (value[:split_at], value[split_at:]):
            chunks.append({"choices": [{"delta": {field: part}}]})
    return chunks


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
    assert call["stream"] is True
    assert call["model"] == NUEXTRACT_MODEL
    assert call["extra_body"]["chat_template_kwargs"]["template"]
    assert call["response_format"]["type"] == "json_schema"


def test_nuextract_adapter_records_extra_body_for_tracing_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict[str, Any]] = []

    @contextmanager
    def fake_extra_body_context(extra_body: dict[str, Any]):
        recorded.append(extra_body)
        yield

    monkeypatch.setattr(
        openai_engine_module.tracing, "openai_extra_body_context", fake_extra_body_context
    )
    client, completions = _client_returning('{"receipt_id": "2"}')
    engine = OpenAIExtractionEngine(
        OpenAIEngineConfig(model=NUEXTRACT_MODEL), client=cast(OpenAI, client)
    )

    engine.extract(make_request())

    assert recorded == [completions.calls[0]["extra_body"]]
    assert recorded[0]["chat_template_kwargs"]["instructions"] == "Extract the receipt id."


def test_generic_adapter_records_no_extra_body_for_tracing_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict[str, Any]] = []

    @contextmanager
    def fake_extra_body_context(extra_body: dict[str, Any]):
        recorded.append(extra_body)
        yield

    monkeypatch.setattr(
        openai_engine_module.tracing, "openai_extra_body_context", fake_extra_body_context
    )
    client, _ = _client_returning('{"receipt_id": "2"}')
    engine = OpenAIExtractionEngine(
        OpenAIEngineConfig(model="gpt-4o-mini"), client=cast(OpenAI, client)
    )

    engine.extract(make_request())

    assert recorded == []


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
        request, model="gpt-4o-mini", max_completion_tokens=256
    )
    # max_completion_tokens (not max_tokens), and no temperature (reasoning-safe).
    assert payload["max_completion_tokens"] == 256
    assert "max_tokens" not in payload
    assert "temperature" not in payload
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert extra_body == {}
    roles = [message["role"] for message in payload["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert payload["messages"][2]["content"] == '{"receipt_id": "7"}'

    obj, _ = build_generic_chat_payload(
        request,
        model="m",
        max_completion_tokens=1,
        response_format_mode=RESPONSE_FORMAT_JSON_OBJECT,
    )
    assert obj["response_format"] == {"type": "json_object"}

    none_payload, _ = build_generic_chat_payload(
        request, model="m", max_completion_tokens=1, response_format_mode=RESPONSE_FORMAT_NONE
    )
    assert "response_format" not in none_payload


def test_generic_payload_routes_reasoning() -> None:
    thinking = make_request(enable_thinking=True)

    effort, _ = build_generic_chat_payload(
        thinking,
        model="o3",
        max_completion_tokens=1,
        reasoning_mode=REASONING_EFFORT,
        reasoning_effort="high",
    )
    assert effort["reasoning_effort"] == "high"

    _, extra_body = build_generic_chat_payload(
        thinking,
        model="qwen",
        max_completion_tokens=1,
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


def test_list_foundry_chat_deployments_filters_chat_capable_deployments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_get(**kwargs: Any) -> httpx.Response:
        captured.update(kwargs)
        return httpx.Response(
            200,
            request=httpx.Request("GET", str(kwargs["url"])),
            json={
                "value": [
                    {
                        "name": "mistral-ocr-4-0-dzs",
                        "capabilities": {"chat_completion": "false"},
                    },
                    {
                        "name": "gpt-5.4-dzs",
                        "capabilities": {"chat_completion": "true"},
                    },
                    {
                        "name": "boolean-chat",
                        "capabilities": {"chat_completion": True},
                    },
                ]
            },
        )

    def fake_httpx_get(
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str],
        timeout: int,
    ) -> httpx.Response:
        return fake_get(url=url, headers=headers, params=params, timeout=timeout)

    monkeypatch.setattr(openai_engine_module.httpx, "get", fake_httpx_get)

    models = openai_engine_module.list_foundry_chat_deployments(
        project_url="https://resource.services.ai.azure.com/api/projects/project/",
        api_key="sk-secret",
        timeout_seconds=7,
    )

    assert models == ["gpt-5.4-dzs", "boolean-chat"]
    assert captured == {
        "url": "https://resource.services.ai.azure.com/api/projects/project/deployments",
        "headers": {"api-key": "sk-secret"},
        "params": {"api-version": "v1"},
        "timeout": 7,
    }


def test_list_foundry_chat_deployments_requires_project_url() -> None:
    with pytest.raises(ProviderRequestError) as excinfo:
        openai_engine_module.list_foundry_chat_deployments(project_url=None, api_key="sk")

    assert "project URL" in str(excinfo.value)


def _legacy_max_completion_tokens_error() -> APIStatusError:
    # What a legacy OpenAI-compatible server returns when it doesn't know the param.
    request = httpx.Request("POST", "https://api.test/v1/chat/completions")
    message = "Unsupported parameter: 'max_completion_tokens'. Use 'max_tokens' instead."
    response = httpx.Response(400, request=request, json={"error": {"message": message}})
    return APIStatusError(message, response=response, body=None)


class _SequencedCompletions:
    """Raises the queued error on the first call, then returns the JSON."""

    def __init__(self, error: Exception, data: dict[str, Any]) -> None:
        self._error = error
        self._data = data
        self.calls: list[dict[str, Any]] = []
        self.streams: list[_FakeStream] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise self._error
        if kwargs.get("stream"):
            stream = _FakeStream(_stream_chunks(self._data))
            self.streams.append(stream)
            return stream
        return _FakeCompletion(self._data)


def test_legacy_server_falls_back_to_max_tokens() -> None:
    completions = _SequencedCompletions(
        _legacy_max_completion_tokens_error(),
        {"choices": [{"message": {"content": '{"receipt_id": "2"}'}}]},
    )
    engine = OpenAIExtractionEngine(
        OpenAIEngineConfig(model="gpt-4o-mini"), client=cast(OpenAI, _FakeClient(completions))
    )

    result = engine.extract(make_request())

    assert result.data == {"receipt_id": "2"}
    first, second = completions.calls
    # The common path sends max_completion_tokens; only a legacy 400 triggers the
    # one-off retry that converts it to max_tokens.
    assert "max_completion_tokens" in first and "max_tokens" not in first
    assert second["max_tokens"] == first["max_completion_tokens"]
    assert "max_completion_tokens" not in second
    assert second["stream"] is True


def test_legacy_fallback_is_cached_for_later_calls() -> None:
    completions = _SequencedCompletions(
        _legacy_max_completion_tokens_error(),
        {"choices": [{"message": {"content": '{"receipt_id": "2"}'}}]},
    )
    engine = OpenAIExtractionEngine(
        OpenAIEngineConfig(model="gpt-4o-mini"), client=cast(OpenAI, _FakeClient(completions))
    )

    engine.extract(make_request())  # first call: one failure + one retry
    engine.extract(make_request())  # second call: legacy param already learned

    assert len(completions.calls) == 3
    assert "max_tokens" in completions.calls[2]
    assert "max_completion_tokens" not in completions.calls[2]


def test_cancellation_closes_stream_during_generation() -> None:
    client, completions = _client_returning('{"receipt_id": "2"}')
    engine = OpenAIExtractionEngine(
        OpenAIEngineConfig(model="gpt-4o-mini"), client=cast(OpenAI, client)
    )
    checks = 0

    def cancellation_check() -> bool:
        nonlocal checks
        checks += 1
        return checks > 1

    with pytest.raises(ExtractionCancelled):
        engine.extract(make_request(), cancellation_check=cancellation_check)

    assert completions.streams[0].closed is True


def test_stream_cancellation_check_is_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, completions = _client_returning('{"receipt_id": "2"}')
    completions.chunks = [
        {"choices": [{"delta": {"content": "{"}}]},
        {"choices": [{"delta": {"content": '"receipt_id"'}}]},
        {"choices": [{"delta": {"content": ":"}}]},
        {"choices": [{"delta": {"content": '"2"'}}]},
        {"choices": [{"delta": {"content": "}"}}]},
    ]
    times = iter([0.0, 0.0, 0.2, 0.8, 1.0, 1.1])
    monkeypatch.setattr(openai_engine_module, "monotonic", lambda: next(times))
    engine = OpenAIExtractionEngine(
        OpenAIEngineConfig(model="gpt-4o-mini"), client=cast(OpenAI, client)
    )
    checks = 0

    def cancellation_check() -> bool:
        nonlocal checks
        checks += 1
        return False

    result = engine.extract(make_request(), cancellation_check=cancellation_check)

    assert result.data == {"receipt_id": "2"}
    # One check before the request, two rate-limited checks during five chunks,
    # and one final check after the stream completes.
    assert checks == 4


def test_other_400_is_not_retried() -> None:
    request = httpx.Request("POST", "https://api.test/v1/chat/completions")
    response = httpx.Response(400, request=request, json={"error": {"message": "bad schema"}})
    completions = _FakeCompletions(
        None, error=APIStatusError("bad schema", response=response, body=None)
    )
    engine = OpenAIExtractionEngine(
        OpenAIEngineConfig(model="gpt-4o-mini"), client=cast(OpenAI, _FakeClient(completions))
    )

    with pytest.raises(ProviderRequestError):
        engine.extract(make_request())
    assert len(completions.calls) == 1  # not retried
