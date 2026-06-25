from __future__ import annotations

import base64
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from parsehawk.core.application.ports import ExtractionRequest

GENERATION_CONTROL_TOKENS = ("<|im_end|>", "<|endoftext|>", "<|eot_id|>")
THINKING_START_TOKEN = "<think>"
THINKING_END_TOKEN = "</think>"


def build_chat_completion_payload(
    request: ExtractionRequest,
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    enable_thinking: bool,
    include_response_format: bool = True,
    include_enable_thinking_field: bool = True,
) -> dict[str, Any]:
    """Build the OpenAI-compatible request for a NuExtract3 runtime.

    vLLM receives NuExtract chat-template kwargs and an OpenAI ``response_format``
    block for JSON-Schema constrained decoding. Its NuExtract chat template
    expects ``enable_thinking`` inside ``chat_template_kwargs``.
    """
    template = template_from_json_schema(request.schema)
    payload: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [*messages_from_examples(request.examples), user_message(request)],
        "chat_template_kwargs": {
            "template": json.dumps(template, ensure_ascii=False, indent=4),
            "instructions": instructions_with_schema_guidance(
                request.instructions,
                request.schema,
            ),
            "enable_thinking": enable_thinking,
        },
    }
    if include_enable_thinking_field:
        payload["enable_thinking"] = enable_thinking
    if include_response_format:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "extraction_result",
                "strict": True,
                "schema": schema_for_constrained_decoding(request.schema),
            },
        }
    return payload


def instructions_with_schema_guidance(instructions: str, schema_json: dict[str, Any]) -> str:
    guidance = field_guidance_from_json_schema(schema_json)
    if not guidance:
        return instructions
    instructions = instructions.strip()
    if instructions:
        return f"{instructions}\n\n{guidance}"
    return guidance


def field_guidance_from_json_schema(schema_json: dict[str, Any]) -> str:
    lines = [
        f"- {path}: {description}" for path, description in schema_description_entries(schema_json)
    ]
    if not lines:
        return ""
    return "Field guidance from the JSON Schema descriptions:\n" + "\n".join(lines)


def schema_description_entries(
    schema_json: dict[str, Any],
    path: str = "",
) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    effective_schema = non_null_schema(schema_json)
    description = effective_schema.get("description")
    if path and isinstance(description, str) and description.strip():
        entries.append((path, " ".join(description.split())))

    properties = effective_schema.get("properties")
    if isinstance(properties, dict):
        for name, property_schema in properties.items():
            if not isinstance(property_schema, dict):
                continue
            child_path = f"{path}.{name}" if path else str(name)
            entries.extend(schema_description_entries(property_schema, child_path))

    if effective_schema.get("type") == "array":
        items = effective_schema.get("items")
        if isinstance(items, dict):
            item_path = f"{path}[]" if path else "[]"
            entries.extend(schema_description_entries(items, item_path))

    return entries


def non_null_schema(schema_json: dict[str, Any]) -> dict[str, Any]:
    for key in ("anyOf", "oneOf"):
        branches = schema_json.get(key)
        if not isinstance(branches, list):
            continue
        meaningful = [
            branch
            for branch in branches
            if isinstance(branch, dict) and branch.get("type") != "null"
        ]
        if len(meaningful) == 1:
            return {**meaningful[0], **{k: v for k, v in schema_json.items() if k != key}}
    return schema_json


def user_message(request: ExtractionRequest) -> dict[str, Any]:
    content = content_from_source(
        text=request.source_text,
        storage_path=request.source_storage_path,
        content_type=request.source_content_type,
        images=[
            {
                "storage_path": image.storage_path,
                "content_type": image.content_type,
                "page_number": image.page_number,
            }
            for image in request.source_images
        ],
    )
    return {"role": "user", "content": content}


def messages_from_examples(examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for example in examples:
        input_value = example.get("input", {})
        output_value = example.get("output")
        content = content_from_example_input(input_value)
        content.append({"type": "text", "text": output_text(output_value)})
        messages.append({"role": "developer", "content": content})
    return messages


def content_from_example_input(input_value: dict[str, Any]) -> list[dict[str, Any]]:
    if input_value.get("type") == "file":
        content = content_from_source(
            text=input_value.get("text", ""),
            storage_path=input_value.get("storage_path"),
            content_type=input_value.get("content_type"),
            images=input_value.get("images", []),
        )
        filename = Path(str(input_value.get("file_name", "document"))).name
        if content and content[0].get("type") == "text":
            content[0]["text"] = f"Source file: {filename}\n\n{content[0]['text']}"
        return content
    return [{"type": "text", "text": str(input_value.get("text", ""))}]


def content_from_source(
    *,
    text: str,
    storage_path: str | None,
    content_type: str | None,
    images: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if images:
        content: list[dict[str, Any]] = []
        if text.strip():
            content.append({"type": "text", "text": text})
        content.extend(
            {
                "type": "image_url",
                "image_url": {
                    "url": data_url(str(image["storage_path"]), str(image["content_type"]))
                },
            }
            for image in images
        )
        return content
    if storage_path and content_type and content_type.startswith("image/"):
        return [{"type": "image_url", "image_url": {"url": data_url(storage_path, content_type)}}]
    return [{"type": "text", "text": text}]


def data_url(storage_path: str, content_type: str) -> str:
    path = Path(storage_path)
    media_type = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def output_text(output_value: Any) -> str:
    if isinstance(output_value, str):
        return output_value
    return json.dumps(output_value, ensure_ascii=False)


def extract_json_object(raw_output: str) -> dict[str, Any]:
    raw_output = strip_hidden_thinking(strip_generation_control_tokens(raw_output))
    decoder = json.JSONDecoder()
    candidates = [raw_output]
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", raw_output, flags=re.DOTALL | re.IGNORECASE)
    candidates.extend(fenced)
    for candidate in candidates:
        for index, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    raise RuntimeError("model output did not contain a JSON object")


def strip_hidden_thinking(raw_output: str) -> str:
    stripped = raw_output.lstrip()
    if stripped.startswith(THINKING_START_TOKEN):
        _, separator, suffix = stripped.partition(THINKING_END_TOKEN)
        return suffix.lstrip() if separator else raw_output
    prefix, separator, suffix = stripped.partition(THINKING_END_TOKEN)
    if separator and "{" not in prefix and "[" not in prefix:
        return suffix.lstrip()
    return raw_output


def strip_generation_control_tokens(raw_output: str) -> str:
    stripped = raw_output.rstrip()
    while True:
        for token in GENERATION_CONTROL_TOKENS:
            if stripped.endswith(token):
                stripped = stripped[: -len(token)].rstrip()
                break
        else:
            return stripped


def template_from_json_schema(schema_json: dict[str, Any]) -> Any:
    schema_type = schema_json.get("type")
    if schema_type == "object" or "properties" in schema_json:
        return {
            name: template_from_json_schema(property_schema)
            for name, property_schema in schema_json.get("properties", {}).items()
        }
    if schema_type == "array":
        return [template_from_json_schema(schema_json.get("items", {"type": "string"}))]
    if "anyOf" in schema_json:
        return template_from_union(schema_json["anyOf"])
    if "oneOf" in schema_json:
        return template_from_union(schema_json["oneOf"])
    if "enum" in schema_json:
        return [value for value in schema_json["enum"] if value is not None]
    return scalar_template(schema_json)


def schema_for_constrained_decoding(schema_json: dict[str, Any]) -> dict[str, Any]:
    return strip_parsehawk_extensions(schema_json)


def strip_parsehawk_extensions(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: strip_parsehawk_extensions(child)
            for key, child in value.items()
            if key != "x-parsehawk"
        }
    if isinstance(value, list):
        return [strip_parsehawk_extensions(item) for item in value]
    return value


def template_from_union(branches: list[dict[str, Any]]) -> Any:
    meaningful = [branch for branch in branches if branch.get("type") != "null"]
    const_values = [branch["const"] for branch in meaningful if "const" in branch]
    if const_values:
        return const_values
    if not meaningful:
        return "string"
    return template_from_json_schema(meaningful[0])


def scalar_template(schema_json: dict[str, Any]) -> str:
    parsehawk_extension = schema_json.get("x-parsehawk")
    if isinstance(parsehawk_extension, dict) and isinstance(
        parsehawk_extension.get("semantic"), str
    ):
        return parsehawk_extension["semantic"]
    schema_type = schema_json.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), "string")
    if schema_type == "integer":
        return "integer"
    if schema_type == "number":
        return "number"
    if schema_type == "string":
        return "string"
    return "string"
