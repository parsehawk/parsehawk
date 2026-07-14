---
title: Inspect extraction traces
description: Use bundled Phoenix or an external OTLP collector to understand model behavior.
sidebar:
  order: 8
---

ParseHawk instruments model requests with OpenInference and exports traces over
OTLP. The default stack includes a local Phoenix instance at
`http://127.0.0.1:6006`.

## Inspect the bundled trace

1. Run an extraction.
2. Open Phoenix at `http://127.0.0.1:6006`.
3. Select the `parsehawk` project and open the API or worker span.
4. Compare the prompt, model response, latency, and validation outcome.

Phoenix stores its SQLite data under `data/phoenix/`, so traces survive normal
restarts.

## Send traces to another collector

The exporter expects an OTLP/HTTP base URL and appends `/v1/traces` itself:

```console
export OTEL_EXPORTER_OTLP_ENDPOINT=https://collector.example.com
export OTEL_EXPORTER_OTLP_HEADERS="authorization=Bearer%20my-key"
export OTEL_SDK_DISABLED=false
parsehawk start -x phoenix
```

Do not include `/v1/traces` at the end of the endpoint. Header values follow the
OTLP environment-variable encoding rules.

## Disable tracing

```console
parsehawk start -x phoenix
```

This disables the bundled Phoenix and, unless you explicitly provide another
collector configuration, disables SDK export.

## Enable model I/O logs only for local debugging

```console
PARSEHAWK_LOG_LEVEL=DEBUG \
PARSEHAWK_LOG_MODEL_IO=true \
parsehawk restart
```

Model I/O can contain sensitive document text and extracted values. Prefer
Phoenix's local access controls and turn verbose logging off after diagnosis.

## Separate anonymous telemetry from tracing

Anonymous product telemetry is independent of model tracing. Disable it with:

```console
export PARSEHAWK_TELEMETRY_DISABLED=1
# or
export DO_NOT_TRACK=1
```

ParseHawk does not send document contents, filenames, extractor instructions,
schemas, or results in anonymous telemetry.
