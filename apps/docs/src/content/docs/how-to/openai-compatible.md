---
title: Use an OpenAI-compatible API
description: Connect LM Studio, a separate vLLM server, or another compatible inference endpoint.
sidebar:
  order: 8
---

Use `openai_compatible_api` for a model server that implements the OpenAI API
shape. Ollama has a [dedicated walkthrough](/how-to/ollama/); this page covers
the general contract.

## Compatibility requirements

For extraction, the server must support:

- `POST /v1/chat/completions` with streaming responses
- text chat messages and the selected model ID
- `max_completion_tokens`, or the legacy `max_tokens` fallback
- `response_format` with `type: json_schema`
- OpenAI `image_url` message parts when processing images or PDFs

`GET /v1/models` is needed for `parsehawk providers models` and the Web UI's
model list. A server can still extract without model discovery when you enter a
known model ID directly.

## Configure a local server

Start ParseHawk without its bundled model:

```console
parsehawk start -x runtime
```

For a server running on the Mac host while ParseHawk uses Docker:

```console
parsehawk providers configure openai_compatible_api \
  --base-url http://host.docker.internal:9000/v1
```

For `parsehawk dev`, where API and worker run on the host, use:

```console
parsehawk providers configure openai_compatible_api \
  --base-url http://127.0.0.1:9000/v1
```

Add a key when the endpoint requires one:

```console
export MODEL_API_KEY=...
parsehawk providers configure openai_compatible_api \
  --api-key-env MODEL_API_KEY
```

## Assign and test a model

```console
parsehawk providers models openai_compatible_api

parsehawk extractors update invoice_v1 \
  --provider openai_compatible_api \
  --model YOUR_MODEL_ID

parsehawk jobs create invoice_v1 --text \
  "Invoice A-204 · 14 July 2026 · Total EUR 128.40"
```

Inspect the returned job and the Phoenix model trace. A successful HTTP response
is not sufficient: the extracted object must also validate against the
extractor schema.

## Understand model adapters

Exact NuExtract3 model variants receive their fine-tuned template and runtime
arguments. All other model IDs receive a standard chat request containing the
extractor instructions, schema-derived template, and ParseHawk semantic-type
reference.
