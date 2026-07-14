---
title: Core concepts
description: The files, extractors, schemas, examples, providers, and jobs in ParseHawk's resource model.
sidebar:
  order: 3
---

ParseHawk turns document extraction into a small set of persistent resources.

## File

A file is an uploaded source document. ParseHawk supports PDF, JPEG, PNG, plain
text, and Markdown inputs. A public `file_...` ID separates storage from later
jobs, so one upload can be processed by multiple extractors.

## Extraction schema

The schema is the output contract. ParseHawk accepts a focused JSON Schema Draft
2020-12 dialect, uses it to guide the model, and validates the returned object
before a job can complete.

A stable object shape with explicit nullable values is easier for both models
and downstream systems than an open-ended prompt.

## Extractor

An extractor bundles:

- an immutable, API-safe `name`
- a mutable human-facing `display_name`
- natural-language instructions
- an extraction schema
- optional few-shot examples
- provider, model, and optional reasoning effort

The server-generated `extractor_...` ID is canonical. The stable name, such as
`receipt` or `invoice_v1`, is the ergonomic reference for configuration and
scripts.

## Example

A few-shot example pairs a representative input with the desired JSON output.
Its input can be inline text or a previously uploaded file. Examples are part of
the extractor definition and are sent to the selected model as demonstrations.

Use examples to settle recurring ambiguity, not to hide a vague schema.

## Provider

A provider stores connection state for a model service. ParseHawk has fixed
slots for `openai_compatible_api`, `openai`, and `microsoft_foundry`. API keys
are write-only at the API boundary and encrypted at rest.

## Job

A job is one asynchronous attempt to apply an extractor to a file or text input.
It records lifecycle state, execution metadata, an error when failed, or a
schema-valid object under `result.data` when completed.

Jobs preserve their outcomes even when the extractor definition changes later.
Create a new job to evaluate an updated extractor.
