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
