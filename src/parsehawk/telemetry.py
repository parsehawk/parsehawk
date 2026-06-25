"""Anonymous, opt-out usage analytics for ParseHawk.

This is the only module that knows about the analytics backend (PostHog). It is
intentionally self-contained and defensive: telemetry must never slow down or
break a Run, so every public entry point swallows its own errors.

What we collect:

- ``install`` — emitted once per install, the first time ParseHawk is started.
- ``run_started`` — emitted each time a user starts an extraction Run.

Both events carry coarse, non-identifying properties (ParseHawk version, OS, and an
approximate location that PostHog derives from the request IP at ingestion). We never
send file contents, file names, extractor instructions, schemas, or extracted data.

The ``distinct_id`` is a random per-install UUID, not a person or machine
fingerprint; it lets us count distinct installs and runs. Person-profile creation is
disabled so events stay event-level and anonymous; IP geolocation is intentionally
left on so we know which countries/regions installs and runs come from.

How to opt out: set ``PARSEHAWK_TELEMETRY_DISABLED=1`` (project-specific) or the
widely-honored ``DO_NOT_TRACK=1`` convention (also respected by tools such as
Homebrew and Turborepo).
"""

from __future__ import annotations

import logging
import os
import platform
import uuid
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

logger = logging.getLogger(__name__)

# Public PostHog project ("write") API key. Project keys are write-only and safe to
# ship in open-source clients. Forks/self-hosters can override both values via env.
_DEFAULT_POSTHOG_KEY = "phc_u2GTchrRo8LY2eh5CTDiC3NfB2iAXiRGYB9N99WhpmZQ"
_DEFAULT_POSTHOG_HOST = "https://eu.i.posthog.com"

_TRUTHY = {"1", "true", "yes", "on"}

_TELEMETRY_ID_FILENAME = "telemetry-id"

_client = None  # lazily initialised PostHog client
_client_initialised = False


def _is_truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in _TRUTHY


def telemetry_enabled() -> bool:
    """Return whether telemetry may be sent.

    Honors both the project-specific ``PARSEHAWK_TELEMETRY_DISABLED`` flag and the
    cross-tool ``DO_NOT_TRACK`` standard. ``DO_NOT_TRACK`` has no ``PARSEHAWK_``
    prefix, so it cannot live in :class:`~parsehawk.config.Settings`; both are read
    here from the environment.
    """
    if _is_truthy(os.getenv("PARSEHAWK_TELEMETRY_DISABLED")):
        return False
    if _is_truthy(os.getenv("DO_NOT_TRACK")):
        return False
    return True


def _parsehawk_version() -> str:
    try:
        return version("parsehawk")
    except PackageNotFoundError:
        return "unknown"


def _anonymous_id(data_dir: Path) -> str:
    """Return a stable random per-install id, creating it on first use.

    This is a random UUID — not a machine fingerprint and not tied to any user
    identity. It only lets us de-duplicate events coming from the same install.
    """
    path = Path(data_dir) / _TELEMETRY_ID_FILENAME
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    anon_id = str(uuid.uuid4())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(anon_id, encoding="utf-8")
    except OSError:
        # If we cannot persist the id we still return one for this process; the
        # worst case is that an install without a writable data dir is counted as
        # multiple installs. That is acceptable and must not break anything.
        pass
    return anon_id


def _get_client():
    global _client, _client_initialised
    if _client_initialised:
        return _client
    _client_initialised = True
    from posthog import Posthog

    api_key = os.getenv("PARSEHAWK_POSTHOG_KEY", _DEFAULT_POSTHOG_KEY)
    host = os.getenv("PARSEHAWK_POSTHOG_HOST", _DEFAULT_POSTHOG_HOST)
    # The SDK disables GeoIP by default for server-side libraries (the ingest IP is
    # usually the server's). ParseHawk is local-first, so events are sent from the
    # user's own machine and the egress IP reflects their location — enable GeoIP so
    # PostHog resolves coarse country/region for "where is usage coming from".
    _client = Posthog(api_key, host=host, disable_geoip=False)
    return _client


def _base_properties() -> dict[str, object]:
    return {
        "parsehawk_version": _parsehawk_version(),
        "os": platform.system(),
        # Keep events anonymous: no person profile keyed on the per-install id.
        # IP geolocation is deliberately left enabled so PostHog resolves coarse
        # location ($geoip_country_name, region) — used to see where usage comes from.
        "$process_person_profile": False,
        # Team machines set PARSEHAWK_TELEMETRY_INTERNAL=1 so their events can be
        # excluded from product/marketing dashboards (PostHog "internal users" filter)
        # without losing the ability to dogfood and verify telemetry end-to-end.
        "internal": _is_truthy(os.getenv("PARSEHAWK_TELEMETRY_INTERNAL")),
    }


def _capture(*, event: str, data_dir: Path, extra: dict[str, object] | None = None) -> None:
    """Send one event, never raising. No-op when telemetry is disabled."""
    try:
        if not telemetry_enabled():
            return
        properties = _base_properties()
        if extra:
            properties.update(extra)
        _get_client().capture(
            distinct_id=_anonymous_id(data_dir),
            event=event,
            properties=properties,
        )
    except Exception:  # pragma: no cover - defensive; telemetry must never break a Run
        logger.debug("telemetry: failed to record %s", event, exc_info=True)


def _flush() -> None:
    """Block until queued events are sent. For short-lived processes (the CLI)."""
    try:
        if _client is not None:
            _client.flush()
    except Exception:  # pragma: no cover - defensive
        logger.debug("telemetry: flush failed", exc_info=True)


def track_install(*, data_dir: Path) -> None:
    """Record a fresh install (first start). No-op when telemetry is disabled.

    Fired from the short-lived CLI process, so it flushes synchronously to make sure
    the event is delivered before the process can exit.
    """
    _capture(event="install", data_dir=data_dir)
    _flush()


def track_run_started(*, input_type: str, data_dir: Path) -> None:
    """Record that a user started a Run. No-op when telemetry is disabled.

    Runs in the long-lived API process, so the PostHog client's background flushing
    delivers the event; no synchronous flush is needed.
    """
    _capture(event="run_started", data_dir=data_dir, extra={"input_type": input_type})
