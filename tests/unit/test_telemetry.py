from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from parsehawk import telemetry


@pytest.fixture(autouse=True)
def reset_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure each test starts with a fresh, uninitialised client."""
    monkeypatch.setattr(telemetry, "_client", None)
    monkeypatch.setattr(telemetry, "_client_initialised", False)
    monkeypatch.delenv("PARSEHAWK_TELEMETRY_INTERNAL", raising=False)


class _FakeClient:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.flushed = 0

    def capture(self, **kwargs) -> None:
        self.events.append(kwargs)

    def flush(self) -> None:
        self.flushed += 1


def test_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PARSEHAWK_TELEMETRY_DISABLED", raising=False)
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    assert telemetry.telemetry_enabled() is True


@pytest.mark.parametrize("var", ["PARSEHAWK_TELEMETRY_DISABLED", "DO_NOT_TRACK"])
@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_disabled_by_either_env_var(monkeypatch: pytest.MonkeyPatch, var: str, value: str) -> None:
    monkeypatch.delenv("PARSEHAWK_TELEMETRY_DISABLED", raising=False)
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.setenv(var, value)
    assert telemetry.telemetry_enabled() is False


def test_falsey_value_keeps_telemetry_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.setenv("PARSEHAWK_TELEMETRY_DISABLED", "0")
    assert telemetry.telemetry_enabled() is True


def test_anonymous_id_is_stable_uuid(tmp_path: Path) -> None:
    first = telemetry._anonymous_id(tmp_path)
    second = telemetry._anonymous_id(tmp_path)
    assert first == second
    # Valid UUID and persisted to disk.
    uuid.UUID(first)
    assert (tmp_path / telemetry._TELEMETRY_ID_FILENAME).read_text().strip() == first


def test_track_run_started_captures_event(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PARSEHAWK_TELEMETRY_DISABLED", raising=False)
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    fake = _FakeClient()
    monkeypatch.setattr(telemetry, "_get_client", lambda: fake)

    telemetry.track_run_started(input_type="file", data_dir=tmp_path)

    assert len(fake.events) == 1
    event = fake.events[0]
    assert event["event"] == "run_started"
    assert event["properties"]["input_type"] == "file"
    assert "parsehawk_version" in event["properties"]
    assert "os" in event["properties"]
    # Person profiles are off; geo (from IP) is left enabled, so it is NOT disabled.
    assert event["properties"]["$process_person_profile"] is False
    assert "$geoip_disable" not in event["properties"]
    # Not a team machine by default.
    assert event["properties"]["internal"] is False
    # Distinct id is the anonymous install id, never anything identifying.
    assert event["distinct_id"] == telemetry._anonymous_id(tmp_path)


def test_internal_flag_tags_events(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PARSEHAWK_TELEMETRY_DISABLED", raising=False)
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.setenv("PARSEHAWK_TELEMETRY_INTERNAL", "1")
    fake = _FakeClient()
    monkeypatch.setattr(telemetry, "_get_client", lambda: fake)

    telemetry.track_run_started(input_type="text", data_dir=tmp_path)

    assert fake.events[0]["properties"]["internal"] is True


def test_track_install_captures_event_and_flushes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("PARSEHAWK_TELEMETRY_DISABLED", raising=False)
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    fake = _FakeClient()
    monkeypatch.setattr(telemetry, "_get_client", lambda: fake)
    monkeypatch.setattr(telemetry, "_client", fake)

    telemetry.track_install(data_dir=tmp_path)

    assert [event["event"] for event in fake.events] == ["install"]
    assert fake.events[0]["distinct_id"] == telemetry._anonymous_id(tmp_path)
    # Short-lived CLI process: must flush so the event is delivered before exit.
    assert fake.flushed == 1


def test_track_install_is_noop_when_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PARSEHAWK_TELEMETRY_DISABLED", "1")
    fake = _FakeClient()
    monkeypatch.setattr(telemetry, "_get_client", lambda: fake)
    monkeypatch.setattr(telemetry, "_client", fake)

    telemetry.track_install(data_dir=tmp_path)

    assert fake.events == []


def test_track_run_started_is_noop_when_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    fake = _FakeClient()
    monkeypatch.setattr(telemetry, "_get_client", lambda: fake)

    telemetry.track_run_started(input_type="text", data_dir=tmp_path)

    assert fake.events == []


def test_track_run_started_swallows_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PARSEHAWK_TELEMETRY_DISABLED", raising=False)
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)

    def _boom() -> None:
        raise RuntimeError("network down")

    monkeypatch.setattr(telemetry, "_get_client", _boom)

    # Must not raise — telemetry can never break a Run.
    telemetry.track_run_started(input_type="text", data_dir=tmp_path)
