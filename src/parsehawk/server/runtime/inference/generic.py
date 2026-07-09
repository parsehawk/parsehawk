"""Generic OpenAI-compatible payload builder for non-NuExtract models.

NuExtract3 is fine-tuned on its template, so it receives the template through
``chat_template_kwargs``. Every other model gets a standard chat request instead:
the schema template plus a vendored copy of NuExtract3's semantic-type reference
(TYPES.md) go into the system prompt, so the model understands what each type
token (``verbatim-string``, ``date-time``, ``region:US`` …) means. Structural
constraints are still enforced separately via ``response_format`` JSON Schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from parsehawk.core.application.ports import ExtractionRequest
from parsehawk.server.runtime.inference.nuextract import (
    content_from_example_input,
    instructions_with_schema_guidance,
    output_text,
    schema_for_constrained_decoding,
    template_from_json_schema,
    user_message,
)

# Response-format modes (broadest → strictest fallback for varied endpoints).
RESPONSE_FORMAT_JSON_SCHEMA = "json_schema"
RESPONSE_FORMAT_JSON_OBJECT = "json_object"
RESPONSE_FORMAT_NONE = "none"

# NuExtract3's semantic-type reference, vendored verbatim from
# https://huggingface.co/numind/NuExtract3/blob/main/TYPES.md
NUEXTRACT_TYPES_REFERENCE = (
    Path(__file__).with_name("nuextract_types.md").read_text(encoding="utf-8").strip()
)


def build_generic_chat_payload(
    request: ExtractionRequest,
    *,
    model: str,
    max_completion_tokens: int,
    response_format_mode: str = RESPONSE_FORMAT_JSON_SCHEMA,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(standard_kwargs, extra_body)`` for the OpenAI chat client.

    Uses ``max_completion_tokens`` (the go-forward OpenAI param, required by
    gpt-5/o-series and accepted by non-reasoning models and modern
    OpenAI-compatible servers) and omits ``temperature`` — reasoning models
    reject a non-default temperature, and ``response_format`` already constrains
    the output. The engine falls back to ``max_tokens`` only for legacy servers
    that don't recognize ``max_completion_tokens``.
    """
    messages = [
        {"role": "system", "content": generic_system_prompt(request)},
        *messages_from_examples(request.examples),
        user_message(request),
    ]
    payload: dict[str, Any] = {
        "model": model,
        "max_completion_tokens": max_completion_tokens,
        "messages": messages,
    }
    extra_body: dict[str, Any] = {}

    if response_format_mode == RESPONSE_FORMAT_JSON_SCHEMA:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "extraction_result",
                "strict": True,
                "schema": schema_for_constrained_decoding(request.schema),
            },
        }
    elif response_format_mode == RESPONSE_FORMAT_JSON_OBJECT:
        payload["response_format"] = {"type": "json_object"}

    # None means "the model's own default": send no reasoning parameter at all.
    # Whether an explicit value is valid for this model is the provider's call.
    if request.reasoning_effort is not None:
        payload["reasoning_effort"] = str(request.reasoning_effort)

    return payload, extra_body


def generic_system_prompt(request: ExtractionRequest) -> str:
    template = json.dumps(template_from_json_schema(request.schema), ensure_ascii=False, indent=4)
    parts: list[str] = []
    instructions = instructions_with_schema_guidance(request.instructions, request.schema).strip()
    if instructions:
        parts.append(instructions)
    parts.append(
        "Extract the data from the input according to the template below. The "
        "template mirrors the desired JSON structure and labels each field with a "
        "semantic type; the type reference explains what each type means and how "
        "to format it. Return only a JSON object matching the template."
    )
    parts.append(f"Semantic type reference:\n\n{NUEXTRACT_TYPES_REFERENCE}")
    parts.append(f"Template:\n\n{template}")
    return "\n\n".join(parts)


def messages_from_examples(examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Render few-shot examples as standard user/assistant message pairs."""
    messages: list[dict[str, Any]] = []
    for example in examples:
        messages.append(
            {"role": "user", "content": content_from_example_input(example.get("input", {}))}
        )
        messages.append({"role": "assistant", "content": output_text(example.get("output"))})
    return messages
