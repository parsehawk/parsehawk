---
title: Architecture
description: How ParseHawk's clients, API, worker, storage, model runtime, and tracing fit together.
sidebar:
  order: 1
---

ParseHawk separates its control surface from extraction execution. The Web UI
and CLI are clients of the same FastAPI application; a worker performs model
calls asynchronously.

```text
                     ┌────────────────────────────┐
 Web UI ───────────┐ │                            │
 CLI ──────────────┼─▶         REST API           │
 Your application ─┘ │ files · extractors · jobs  │
                     └─────────────┬──────────────┘
                                   │ shared state
                     ┌─────────────▼──────────────┐
                     │ SQLite · files · secret key│
                     └─────────────┬──────────────┘
                                   │ claim queued jobs
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
API. Because all three use the same resource model, an extractor created in the
UI is immediately addressable from the CLI and HTTP.

## API and worker

The API validates requests, persists resources, and queues jobs. It does not
hold an HTTP request open for model inference. The worker claims jobs from the
shared SQLite state, resolves the extractor's current provider configuration,
loads the source, calls the model, validates the output, and writes the terminal
result.

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

## Model boundary

The worker resolves a provider and model for each extractor. All providers use
one OpenAI SDK transport, while the payload adapter changes by model family:

- exact NuExtract3 variants receive their fine-tuned chat template
- other models receive a generic extraction prompt and JSON Schema response
  constraint

This is why the same extractor can move from the bundled vLLM runtime to Ollama
or a cloud provider without changing its data contract.

## Observability boundary

Model calls are instrumented separately from job state. The bundled Phoenix
stores traces locally, or operators can point OTLP export at another collector.
Anonymous product telemetry is a separate, optional outbound path.
