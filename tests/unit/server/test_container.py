from __future__ import annotations

import pytest

from parsehawk.config import DEFAULT_VLLM_MODEL, Settings
from parsehawk.core.application.ports import ExtractionRequest
from parsehawk.server.container import UnavailableEngine, build_engine
from parsehawk.server.runtime.inference.runtime_engine import NuExtractRuntimeEngine


def test_build_engine_vllm_targets_vllm_runtime_without_top_level_thinking_field() -> None:
    engine = build_engine(Settings(inference_engine="vllm"))

    assert isinstance(engine, NuExtractRuntimeEngine)
    config = engine._config
    assert config.model == DEFAULT_VLLM_MODEL
    assert config.base_url == "http://127.0.0.1:8080/v1"
    assert config.include_response_format is True
    assert config.include_enable_thinking_field is False
    assert config.log_model_io is False


def test_build_engine_passes_model_io_logging_setting() -> None:
    engine = build_engine(Settings(inference_engine="vllm", log_model_io=True))

    assert isinstance(engine, NuExtractRuntimeEngine)
    assert engine._config.log_model_io is True


def test_build_engine_without_runtime_defers_a_clear_error() -> None:
    engine = build_engine(Settings(inference_engine="none"))

    assert isinstance(engine, UnavailableEngine)
    with pytest.raises(RuntimeError, match="no model runtime is configured"):
        engine.extract(
            ExtractionRequest(
                source_text="hello",
                instructions="extract",
                schema={"type": "object", "properties": {}},
                examples=[],
                enable_thinking=False,
            )
        )
