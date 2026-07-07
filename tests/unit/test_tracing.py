from __future__ import annotations

import sys
from types import ModuleType

import pytest

from parsehawk import tracing


@pytest.fixture(autouse=True)
def reset_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure each test starts unconfigured and opted back in (conftest opts out)."""
    monkeypatch.setattr(tracing, "_configured", False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)


def test_enabled_by_default() -> None:
    assert tracing.tracing_disabled() is False


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_disabled_by_env_var(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", value)
    assert tracing.tracing_disabled() is True


@pytest.mark.parametrize("value", ["0", "false", ""])
def test_falsey_value_keeps_tracing_enabled(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", value)
    assert tracing.tracing_disabled() is False


def test_configure_tracing_registers_once(monkeypatch: pytest.MonkeyPatch) -> None:
    registered: list[str] = []
    monkeypatch.setattr(tracing, "_register", registered.append)

    tracing.configure_tracing(service_name="parsehawk-api")
    tracing.configure_tracing(service_name="parsehawk-api")

    assert registered == ["parsehawk-api"]


def test_configure_tracing_is_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    registered: list[str] = []
    monkeypatch.setattr(tracing, "_register", registered.append)

    tracing.configure_tracing(service_name="parsehawk-api")

    assert registered == []


def test_configure_tracing_swallows_missing_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(service_name: str) -> None:
        raise ImportError("No module named 'opentelemetry'")

    monkeypatch.setattr(tracing, "_register", _boom)

    # Must not raise — the tracing extra is optional and tracing can never
    # break a Run.
    tracing.configure_tracing(service_name="parsehawk-worker")


def test_configure_tracing_swallows_registration_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(service_name: str) -> None:
        raise RuntimeError("collector misconfigured")

    monkeypatch.setattr(tracing, "_register", _boom)

    tracing.configure_tracing(service_name="parsehawk-api")


def test_openai_extra_body_context_uses_openinference_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts: list[dict[str, object]] = []
    extra_body = {
        "chat_template_kwargs": {
            "instructions": "Extract receipt fields.",
            "template": '{"receipt_id": "string"}',
            "enable_thinking": False,
        }
    }
    module = ModuleType("openinference.instrumentation")

    def fake_using_metadata(metadata: dict[str, object]) -> _FakeMetadataContext:
        contexts.append(metadata)
        return _FakeMetadataContext()

    setattr(module, "using_metadata", fake_using_metadata)
    monkeypatch.setitem(sys.modules, "openinference.instrumentation", module)

    with tracing.openai_extra_body_context(extra_body):
        pass

    assert contexts == [{"parsehawk.openai.extra_body": extra_body}]


class _FakeMetadataContext:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> None:
        return None
