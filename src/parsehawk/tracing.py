"""Backend-agnostic OTLP tracing for LM requests.

ParseHawk drives every model provider through the OpenAI SDK
(:mod:`parsehawk.server.runtime.inference.openai_engine`), so LM observability is
implemented as OpenInference auto-instrumentation of that client exporting OTLP
spans. The app knows nothing about any specific tracing backend: the bundled
Arize Phoenix service is simply the default OTLP target that `parsehawk start`
wires up, and any other collector works by overriding the standard
OpenTelemetry env vars:

- ``OTEL_SDK_DISABLED`` — master switch (``parsehawk start -x phoenix`` sets it).
- ``OTEL_EXPORTER_OTLP_ENDPOINT`` — OTLP/HTTP collector base URL.
- ``OTEL_EXPORTER_OTLP_HEADERS`` — optional auth, e.g.
  ``authorization=Bearer <api key>`` for an auth-enabled Phoenix.
- ``OTEL_SERVICE_NAME`` / ``OTEL_RESOURCE_ATTRIBUTES`` — resource overrides.

These are OTel-ecosystem standard names, so (like ``DO_NOT_TRACK`` in
:mod:`parsehawk.telemetry`) they are read straight from the environment instead
of :class:`~parsehawk.config.Settings`, which prefixes everything with
``PARSEHAWK_``.

Like telemetry, tracing must never slow down or break a Run: the OTel/
OpenInference dependencies are an optional extra (``parsehawk[tracing]``), and
every failure here — missing packages, bad config, unreachable collector —
degrades to a no-op instead of an error.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}

# Groups ParseHawk's spans under one Phoenix project; override via the standard
# OTEL_RESOURCE_ATTRIBUTES (e.g. "openinference.project.name=my-project").
_PROJECT_NAME_ATTRIBUTE = "openinference.project.name"
_DEFAULT_PROJECT_NAME = "parsehawk"

_configured = False


def _is_truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in _TRUTHY


def tracing_disabled() -> bool:
    """Return whether tracing is switched off via the OTel-standard env var."""
    return _is_truthy(os.getenv("OTEL_SDK_DISABLED"))


def configure_tracing(*, service_name: str) -> None:
    """Set up OTLP span export and LM auto-instrumentation for this process.

    Called once at process startup (API lifespan, worker main). Idempotent, and
    a no-op when tracing is disabled or the optional tracing dependencies are
    not installed.
    """
    global _configured
    if _configured:
        return
    _configured = True
    if tracing_disabled():
        return
    try:
        _register(service_name)
    except Exception:  # pragma: no cover - defensive; tracing must never break a Run
        logger.debug("tracing: failed to configure OTLP tracing", exc_info=True)


def _register(service_name: str) -> None:
    from openinference.instrumentation.openai import OpenAIInstrumentor
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Resource.create() lets explicitly passed attributes win over the standard
    # env detectors, so only fill the gaps: the env vars must stay authoritative.
    attributes: dict[str, str] = {}
    if not os.getenv("OTEL_SERVICE_NAME"):
        attributes["service.name"] = service_name
    if _PROJECT_NAME_ATTRIBUTE not in os.getenv("OTEL_RESOURCE_ATTRIBUTES", ""):
        attributes[_PROJECT_NAME_ATTRIBUTE] = _DEFAULT_PROJECT_NAME

    # The exporter reads OTEL_EXPORTER_OTLP_ENDPOINT / OTEL_EXPORTER_OTLP_HEADERS
    # itself; batching keeps span export off the request path.
    provider = TracerProvider(resource=Resource.create(attributes))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    # Every provider goes through the OpenAI SDK, so instrumenting it covers all
    # LM requests (chat completions and model listing alike).
    OpenAIInstrumentor().instrument(tracer_provider=provider)
    logger.info(
        "Tracing LM requests via OTLP: %s",
        os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"),
    )
