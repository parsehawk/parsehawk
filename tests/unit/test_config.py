from __future__ import annotations

import pytest

from parsehawk import config


@pytest.mark.parametrize("machine", ["x86_64", "aarch64", "arm64"])
def test_default_inference_engine_supports_linux_x86_and_arm(
    monkeypatch: pytest.MonkeyPatch, machine: str
) -> None:
    monkeypatch.setattr(config.sys, "platform", "linux")
    monkeypatch.setattr(config.platform, "machine", lambda: machine)

    assert config.default_inference_engine() == "vllm"


def test_default_inference_engine_rejects_other_linux_architectures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.sys, "platform", "linux")
    monkeypatch.setattr(config.platform, "machine", lambda: "ppc64le")

    assert config.default_inference_engine() is None


def test_parsing_token_budget_has_separate_default_and_environment_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert config.Settings().parsing_max_tokens == config.DEFAULT_PARSING_MAX_TOKENS == 4096
    assert config.DEFAULT_PARSING_MAX_TOKENS < config.DEFAULT_VLLM_MAX_MODEL_LEN

    monkeypatch.setenv("PARSEHAWK_PARSING_MAX_TOKENS", "12288")
    assert config.Settings.from_env().parsing_max_tokens == 12288

    with pytest.raises(ValueError):
        config.Settings(parsing_max_tokens=0)
