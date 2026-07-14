---
title: Use Ollama locally
description: Run text and multimodal ParseHawk extractors through Ollama's OpenAI-compatible API.
sidebar:
  order: 4
---

ParseHawk can use Ollama through the existing `openai_compatible_api` provider.
No separate provider adapter is required: ParseHawk sends chat-completions
requests with JSON Schema response constraints and OpenAI-compatible image
inputs.

## 1. Start Ollama and pull a small model

Install [Ollama](https://ollama.com/download), then start its local server. The
desktop app normally starts it for you; from a terminal you can run:

```console
ollama serve
```

For a lightweight text test:

```console
ollama pull qwen3:0.6b
```

For image and rendered-PDF extraction:

```console
ollama pull qwen3-vl:2b-instruct
```

Confirm Ollama's OpenAI-compatible endpoint:

```console
curl --fail http://127.0.0.1:11434/v1/models
```

## 2. Start ParseHawk without its bundled runtime

```console
parsehawk start -x runtime
```

The API and worker still run in Docker. Point them at the Mac host, not at their
own container loopback:

```console
parsehawk providers configure openai_compatible_api \
  --base-url http://host.docker.internal:11434/v1
```

If you run `parsehawk dev` with API and worker processes directly on the host,
use `http://127.0.0.1:11434/v1` instead.

## 3. Test structured text extraction

Assign the text model to a saved extractor:

```console
parsehawk extractors update invoice_v1 \
  --provider openai_compatible_api \
  --model qwen3:0.6b

parsehawk jobs create invoice_v1 --text \
  "Invoice A-204 · 14 July 2026 · Total EUR 128.40"
```

Inspect the returned job with `parsehawk jobs get job_...`. A completed job has
schema-valid JSON under `result.data`.

## 4. Test a multimodal model

Assign the vision-language model, then run an image:

```console
parsehawk extractors update receipt \
  --provider openai_compatible_api \
  --model qwen3-vl:2b-instruct

parsehawk extract tests/fixtures/receipt/receipt.jpg \
  --extractor receipt \
  --wait
```

PDFs use the same multimodal path: ParseHawk renders pages to images before
calling the model. The default limit is 25 pages at 170 DPI.

## Troubleshoot the connection

- If `/v1/models` fails on the host, Ollama is not listening yet. Open the app
  or run `ollama serve` and retry.
- If the host request works but ParseHawk cannot connect, verify that the stored
  base URL uses `host.docker.internal` for the Docker stack.
- If a model returns free-form prose instead of JSON, try its instruction-tuned
  variant and inspect the model trace in Phoenix.
- If a vision job fails immediately, confirm that the selected model supports
  images; a text-only model cannot process image or PDF inputs.
- Small models are useful for compatibility checks, not an accuracy baseline.
  Evaluate a representative document set before choosing a production model.
