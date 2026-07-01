"""Shared parsing of OpenAI-compatible chat-completion responses.

Reused by every provider adapter: the response envelope is identical whether the
model runs on the bundled vLLM, a cloud endpoint, or Azure. Reasoning models put
their answer in ``reasoning``/``reasoning_content`` instead of ``content``, so we
fall through those fields in order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MessageContent:
    text: str
    source: str


def message_content_with_source(payload: dict[str, Any]) -> MessageContent:
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


def redact_model_io(value: Any) -> Any:
    """Recursively redact base64 image data URLs from a request/response payload."""
    if isinstance(value, dict):
        return {key: redact_model_io(child) for key, child in value.items()}
    if isinstance(value, list):
        return [redact_model_io(child) for child in value]
    if isinstance(value, str) and value.startswith("data:") and ";base64," in value:
        media_type, _, encoded = value.partition(";base64,")
        return f"{media_type};base64,<redacted {len(encoded)} chars>"
    return value
