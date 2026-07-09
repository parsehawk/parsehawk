from __future__ import annotations

import json

from parsehawk.core.application.ports import ExtractionRequest, PreparedImage
from parsehawk.server.runtime.inference.nuextract import (
    build_chat_completion_payload,
    field_guidance_from_json_schema,
    instructions_with_schema_guidance,
    schema_for_constrained_decoding,
    strip_generation_control_tokens,
    strip_hidden_thinking,
    template_from_json_schema,
)


def test_template_from_json_schema_preserves_parsehawk_semantics_and_enums() -> None:
    schema = {
        "type": "object",
        "properties": {
            "company": {
                "type": ["string", "null"],
                "x-parsehawk": {"semantic": "verbatim-string"},
            },
            "total": {"type": ["number", "null"]},
            "receipt_id": {
                "anyOf": [
                    {"const": "1", "title": "Invoice"},
                    {"const": "2", "title": "Support request"},
                    {"type": "null"},
                ]
            },
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            },
        },
    }

    assert template_from_json_schema(schema) == {
        "company": "verbatim-string",
        "total": "number",
        "receipt_id": ["1", "2"],
        "items": [{"name": "string"}],
    }


def test_schema_for_constrained_decoding_removes_internal_extensions() -> None:
    schema = {
        "type": "object",
        "properties": {
            "company": {
                "type": ["string", "null"],
                "description": "Company name",
                "x-parsehawk": {"semantic": "verbatim-string"},
            }
        },
    }

    assert schema_for_constrained_decoding(schema) == {
        "type": "object",
        "properties": {
            "company": {
                "type": ["string", "null"],
                "description": "Company name",
            }
        },
    }


def test_field_guidance_from_json_schema_renders_nested_descriptions() -> None:
    schema = {
        "type": "object",
        "description": "Root descriptions are not field guidance.",
        "properties": {
            "vendor": {
                "type": "object",
                "description": "Vendor details.",
                "properties": {
                    "name": {
                        "type": ["string", "null"],
                        "description": "Vendor full name. Document aliases: Vendor.",
                    },
                },
            },
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": "Line item text.",
                        },
                    },
                },
            },
        },
    }

    assert field_guidance_from_json_schema(schema) == (
        "Field guidance from the JSON Schema descriptions:\n"
        "- vendor: Vendor details.\n"
        "- vendor.name: Vendor full name. Document aliases: Vendor.\n"
        "- items[].description: Line item text."
    )


def test_instructions_with_schema_guidance_appends_descriptions() -> None:
    schema = {
        "type": "object",
        "properties": {
            "invoice_reference": {
                "type": ["string", "null"],
                "description": "Invoice reference exactly as printed. Document aliases: Invoice No., Reference.",
            },
        },
    }

    assert instructions_with_schema_guidance("Extract invoice fields.", schema) == (
        "Extract invoice fields.\n\n"
        "Field guidance from the JSON Schema descriptions:\n"
        "- invoice_reference: Invoice reference exactly as printed. Document aliases: Invoice No., Reference."
    )


def test_build_chat_completion_payload_uses_nuextract_message_structure() -> None:
    request = ExtractionRequest(
        source_text="John bought coffee.",
        instructions="Extract buyer and item.",
        reasoning_effort=None,
        schema={
            "type": "object",
            "properties": {
                "buyer": {"type": "string", "x-parsehawk": {"semantic": "verbatim-string"}},
                "item": {"type": "string", "description": "Purchased item name."},
            },
        },
        examples=[
            {
                "input": {"type": "text", "text": "Jane bought tea."},
                "output": {"buyer": "Jane", "item": "tea"},
            }
        ],
    )

    payload = build_chat_completion_payload(
        request,
        model="numind/NuExtract3",
        max_tokens=4096,
        temperature=0.2,
        enable_thinking=False,
    )

    assert payload["model"] == "numind/NuExtract3"
    assert payload["enable_thinking"] is False
    assert payload["messages"] == [
        {
            "role": "developer",
            "content": [
                {"type": "text", "text": "Jane bought tea."},
                {"type": "text", "text": '{"buyer": "Jane", "item": "tea"}'},
            ],
        },
        {"role": "user", "content": [{"type": "text", "text": "John bought coffee."}]},
    ]
    assert payload["chat_template_kwargs"]["instructions"] == (
        "Extract buyer and item.\n\n"
        "Field guidance from the JSON Schema descriptions:\n"
        "- item: Purchased item name."
    )
    assert json.loads(payload["chat_template_kwargs"]["template"]) == {
        "buyer": "verbatim-string",
        "item": "string",
    }
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "extraction_result",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "buyer": {"type": "string"},
                    "item": {"type": "string", "description": "Purchased item name."},
                },
            },
        },
    }


def test_build_chat_completion_payload_vllm_flavor_keeps_response_format() -> None:
    request = ExtractionRequest(
        source_text="John bought coffee.",
        instructions="Extract buyer and item.",
        schema={
            "type": "object",
            "properties": {"buyer": {"type": "string"}},
        },
        examples=[],
        reasoning_effort="medium",
    )

    payload = build_chat_completion_payload(
        request,
        model="numind/NuExtract3",
        max_tokens=2048,
        temperature=0.2,
        enable_thinking=True,
        include_enable_thinking_field=False,
    )

    assert "enable_thinking" not in payload
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "extraction_result",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"buyer": {"type": "string"}},
            },
        },
    }
    assert payload["chat_template_kwargs"]["enable_thinking"] is True
    assert payload["chat_template_kwargs"]["instructions"] == "Extract buyer and item."
    assert json.loads(payload["chat_template_kwargs"]["template"]) == {"buyer": "string"}


def test_build_chat_completion_payload_derives_nuextract_template_from_schema() -> None:
    request = ExtractionRequest(
        source_text="Jane bought tea.",
        instructions="Extract buyer and item.",
        reasoning_effort=None,
        schema={
            "type": "object",
            "properties": {
                "buyer": {"type": "string", "x-parsehawk": {"semantic": "verbatim-string"}},
                "item": {"type": "string", "x-parsehawk": {"semantic": "verbatim-string"}},
            },
        },
        examples=[],
    )

    payload = build_chat_completion_payload(
        request,
        model="numind/NuExtract3",
        max_tokens=4096,
        temperature=0.2,
        enable_thinking=False,
    )

    assert json.loads(payload["chat_template_kwargs"]["template"]) == {
        "buyer": "verbatim-string",
        "item": "verbatim-string",
    }


def test_build_chat_completion_payload_includes_prepared_images_in_order(tmp_path) -> None:
    first = tmp_path / "page-001.png"
    second = tmp_path / "page-002.png"
    first.write_bytes(b"first image")
    second.write_bytes(b"second image")
    request = ExtractionRequest(
        source_text="",
        source_storage_path="document.pdf",
        source_content_type="application/pdf",
        source_images=[
            PreparedImage(storage_path=str(first), content_type="image/png", page_number=1),
            PreparedImage(storage_path=str(second), content_type="image/png", page_number=2),
        ],
        instructions="Extract invoice fields.",
        reasoning_effort=None,
        schema={
            "type": "object",
            "properties": {"invoice_number": {"type": "string"}},
        },
        examples=[],
    )

    payload = build_chat_completion_payload(
        request,
        model="numind/NuExtract3",
        max_tokens=4096,
        temperature=0.2,
        enable_thinking=False,
    )

    content = payload["messages"][0]["content"]
    assert [item["type"] for item in content] == ["image_url", "image_url"]
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_strip_generation_control_tokens_removes_trailing_chat_markers() -> None:
    assert strip_generation_control_tokens('{"answer": "ok"}<|im_end|><|im_end|>') == (
        '{"answer": "ok"}'
    )


def test_strip_hidden_thinking_removes_leading_reasoning() -> None:
    assert strip_hidden_thinking('<think>private reasoning</think>{"answer": "ok"}') == (
        '{"answer": "ok"}'
    )
    assert strip_hidden_thinking('private reasoning</think>{"answer": "ok"}') == (
        '{"answer": "ok"}'
    )
