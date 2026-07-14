---
title: Build a reusable extractor
description: Create a stable invoice extractor from instructions and a JSON Schema.
sidebar:
  order: 2
---

This tutorial turns a one-off extraction into a reusable contract named
`invoice_v1`. You will validate a schema, save an extractor, and run text through
it.

## 1. Define the output

Save this as `invoice.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "invoice_number": {
      "type": ["string", "null"],
      "description": "The invoice number exactly as printed."
    },
    "invoice_date": {
      "type": ["string", "null"],
      "description": "The invoice date in ISO 8601 format.",
      "x-parsehawk": { "semantic": "date" }
    },
    "total_amount": {
      "type": ["number", "null"],
      "description": "The final amount due."
    },
    "currency": {
      "type": ["string", "null"],
      "description": "The ISO 4217 currency code.",
      "x-parsehawk": { "semantic": "currency" }
    }
  },
  "required": ["invoice_number", "invoice_date", "total_amount", "currency"],
  "additionalProperties": false
}
```

## 2. Validate before saving

```console
parsehawk schemas validate invoice.schema.json
```

ParseHawk accepts a focused JSON Schema authoring dialect. This command catches
unsupported keywords and malformed semantic hints without creating a resource.

## 3. Save the extractor idempotently

```console
parsehawk extractors put invoice_v1 \
  --display-name "Invoice extractor" \
  --schema invoice.schema.json \
  --instructions "Extract only values stated in the invoice. Use null when a field is absent."
```

`put` is useful in scripts and configuration management: it creates
`invoice_v1` when missing and otherwise replaces its definition. The stable name
does not change when you edit its human-facing display name.

## 4. Run a text extraction

```console
parsehawk jobs create invoice_v1 --text \
  "Invoice A-204 · 14 July 2026 · Total EUR 128.40"
```

Copy the returned `job_...` ID and inspect it:

```console
parsehawk jobs get job_...
```

While the worker is processing it, the job moves from `queued` to `running`.
When it reaches `completed`, `result.data` contains a value like:

```json
{
  "invoice_number": "A-204",
  "invoice_date": "2026-07-14",
  "total_amount": 128.4,
  "currency": "EUR"
}
```

## 5. Evolve the definition

Edit the schema or instructions and run the same `extractors put` command. New
jobs use the updated definition; existing job records retain the result they
already produced.

Next, learn how to [call the same workflow over HTTP](/tutorials/rest-api/).
