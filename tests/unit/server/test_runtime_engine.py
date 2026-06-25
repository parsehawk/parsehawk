from __future__ import annotations

import pytest

from parsehawk.server.runtime.inference.runtime_engine import (
    _message_content,
    _message_content_with_source,
    _redact_model_io,
)


def test_message_content_uses_assistant_content_first() -> None:
    assert (
        _message_content({"choices": [{"message": {"content": '{"answer": "ok"}'}}]})
        == '{"answer": "ok"}'
    )


def test_message_content_falls_back_to_vllm_reasoning_when_content_is_null() -> None:
    assert (
        _message_content(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "reasoning": '{"answer": "ok"}',
                        }
                    }
                ]
            }
        )
        == '{"answer": "ok"}'
    )


def test_message_content_reports_reasoning_source() -> None:
    message = _message_content_with_source(
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "reasoning": '{"answer": "ok"}',
                    }
                }
            ]
        }
    )

    assert message.text == '{"answer": "ok"}'
    assert message.source == "message.reasoning"


def test_message_content_falls_back_to_reasoning_content_alias() -> None:
    assert (
        _message_content(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "reasoning_content": '{"answer": "ok"}',
                        }
                    }
                ]
            }
        )
        == '{"answer": "ok"}'
    )


def test_message_content_reports_missing_text() -> None:
    with pytest.raises(
        RuntimeError, match="model runtime response did not include message content"
    ):
        _message_content({"choices": [{"message": {"content": None}}]})


def test_redact_model_io_replaces_base64_data_urls() -> None:
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "extract this"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,abcdefghijklmnopqrstuvwxyz"},
                    },
                ],
            }
        ]
    }

    assert _redact_model_io(payload) == {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "extract this"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,<redacted 26 chars>"},
                    },
                ],
            }
        ]
    }
