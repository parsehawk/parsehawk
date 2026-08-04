---
title: Architecture
description: How ParseHawk's clients, API, worker, storage, model runtime, and tracing fit together.
sidebar:
  order: 1
---

ParseHawk separates its control surface from extraction and parsing execution.
The Web UI and CLI are clients of the same FastAPI application; a worker
performs model calls asynchronously.

```text
                     ┌────────────────────────────┐
 Web UI ───────────┐ │                            │
 CLI ──────────────┼─▶         REST API           │
 Your application ─┘ │ files · extractors · parsers│
                     │ extraction jobs · parse jobs│
                     └─────────────┬──────────────┘
                                   │ shared state
                     ┌─────────────▼──────────────┐
                     │ SQLite · files · secret key│
                     └─────────────┬──────────────┘
                                   │ claim either queue fairly
                     ┌─────────────▼──────────────┐
                     │           Worker           │
                     └───────┬─────────────┬──────┘
                             │             │ traces
                     ┌───────▼───────┐ ┌───▼────────┐
                     │ Model provider│ │  Phoenix / │
                     │ local or cloud│ │ OTLP target│
                     └───────────────┘ └────────────┘
```

## Clients

The Web UI is for interactive work. The CLI covers both local-stack operations
and API resources. External applications can integrate directly with the REST
API. Because all three use the same resource model, an extractor or parser
created in the UI is immediately addressable from the CLI and HTTP.

## API and worker

The API validates requests, persists resources, and writes to separate
extraction-job and parse-job queues. It does not hold an HTTP request open for
model inference. The worker alternates queue priority after each claim and falls
back to the non-empty queue, preventing either workflow from starving.

For extraction, the worker resolves the extractor and returns schema-validated
JSON. For parsing, it executes the immutable parser snapshot page by page and
returns ordered Markdown. Each SQLite claim is atomic, and the claim transaction
commits before file preparation or model work begins.

This boundary keeps the API responsive and gives clients an explicit job
lifecycle. It also means a healthy API is not sufficient: the worker and its
provider connection must be healthy for jobs to complete.

## Persistence

The default `data/` directory contains:

```text
data/
  parsehawk.db
  files/
  logs/
  parsehawk-state.json
  phoenix/
  telemetry-id
```

The API and worker must see the same database, file store, and provider-secret
key. Local Docker Compose mounts one host directory into both processes.

Every API use case and worker database phase checks out its own SQLAlchemy Core
connection and owns one short transaction. Repositories never commit on their
own. The worker commits its claim before preparing files or calling a model, so
slow document and provider work never holds a SQLite transaction open.

## Model boundary

The worker resolves a provider and model for each extractor or parser. All
current providers use one OpenAI SDK transport, while the payload adapter changes
by workflow and model family:

- NuExtract3 extraction uses its fine-tuned structured template
- generic extraction uses an extraction prompt and JSON Schema response
  constraint
- NuExtract3 parsing uses its dedicated Markdown mode without an extraction
  template or JSON response format
- generic parsing sends one page at a time with a concise Markdown
  transcription prompt

The parsing port remains separate from the chat transport so future native OCR
or completion-style adapters do not need to imitate extraction.

## Observability boundary

Model calls are instrumented separately from job state. The bundled Phoenix
stores traces locally, or operators can point OTLP export at another collector.
Anonymous product telemetry is a separate, optional outbound path.
