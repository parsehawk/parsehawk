from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from parsehawk.core.application.ports import ExtractionRequest, ExtractionResponse
from parsehawk.server.runtime.inference.nuextract import (
    build_chat_completion_payload,
    extract_json_object,
    strip_generation_control_tokens,
    strip_hidden_thinking,
)

logger = logging.getLogger("parsehawk.runtime")


@dataclass(frozen=True)
class NuExtractRuntimeConfig:
    model: str = "numind/NuExtract3"
    base_url: str = "http://127.0.0.1:8080/v1"
    max_tokens: int = 2048
    temperature: float = 0.2
    timeout_seconds: int = 600
    include_response_format: bool = True
    include_enable_thinking_field: bool = False
    log_model_io: bool = False


class NuExtractRuntimeEngine:
    """NuExtract3 adapter for a running OpenAI-compatible model runtime.

    The same HTTP client drives vLLM Metal on macOS and vLLM on Linux. Both are
    OpenAI-compatible servers that accept NuExtract3 chat-template kwargs plus
    OpenAI ``response_format`` constrained decoding.
    """

    def __init__(self, config: NuExtractRuntimeConfig) -> None:
        self._config = config

    def extract(self, request: ExtractionRequest) -> ExtractionResponse:
        payload = build_chat_completion_payload(
            request,
            model=self._config.model,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            enable_thinking=request.enable_thinking,
            include_response_format=self._config.include_response_format,
            include_enable_thinking_field=self._config.include_enable_thinking_field,
        )
        self._debug_model_io("model runtime request: %s", payload)
        raw_response = self._post_json("chat/completions", payload)
        self._debug_model_io("model runtime response: %s", raw_response)
        message_content = _message_content_with_source(raw_response)
        if self._config.log_model_io and logger.isEnabledFor(logging.DEBUG):
            logger.debug("model runtime response text source: %s", message_content.source)
        content = strip_generation_control_tokens(message_content.text)
        if request.enable_thinking:
            content = strip_hidden_thinking(content)
        data = extract_json_object(content)
        return ExtractionResponse(data=data)

    def _debug_model_io(self, message: str, payload: dict[str, Any]) -> None:
        if not self._config.log_model_io or not logger.isEnabledFor(logging.DEBUG):
            return
        logger.debug(message, json.dumps(_redact_model_io(payload), ensure_ascii=False))

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        base_url = self._config.base_url.rstrip("/")
        request = urllib.request.Request(
            f"{base_url}/{path.lstrip('/')}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"model runtime returned HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"model runtime is unreachable: {exc}") from exc


@dataclass(frozen=True)
class MessageContent:
    text: str
    source: str


def _message_content(payload: dict[str, Any]) -> str:
    return _message_content_with_source(payload).text


def _message_content_with_source(payload: dict[str, Any]) -> MessageContent:
    choices = payload.get("choices")
    if not choices:
        raise RuntimeError("model runtime response did not include choices")
    message = choices[0].get("message", {})
    content = _message_text(message.get("content"))
    if content is not None:
        return MessageContent(text=content, source="message.content")

    for reasoning_field in ("reasoning", "reasoning_content"):
        reasoning = _message_text(message.get(reasoning_field))
        if reasoning is not None:
            return MessageContent(text=reasoning, source=f"message.{reasoning_field}")

    raise RuntimeError("model runtime response did not include message content")


def _message_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(part.get("text", "") for part in value if isinstance(part, dict))
    return None


def _redact_model_io(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_model_io(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_redact_model_io(child) for child in value]
    if isinstance(value, str) and value.startswith("data:") and ";base64," in value:
        media_type, _, encoded = value.partition(";base64,")
        return f"{media_type};base64,<redacted {len(encoded)} chars>"
    return value
