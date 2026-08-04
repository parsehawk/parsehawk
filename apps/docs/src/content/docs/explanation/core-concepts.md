---
title: Core concepts
description: Files, extractors, parsers, providers, extraction jobs, and parse jobs in ParseHawk's resource model.
sidebar:
  order: 3
---

ParseHawk exposes two independent document workflows through a small set of
persistent resources:

- **extraction** turns a document or text into schema-valid JSON
- **parsing** turns a PDF or image into page-aware Markdown

Parsing is not a required preprocessing step for extraction. Use the original
document directly when the extraction model benefits from layout or visual
context.

## File

A file is an uploaded source document. ParseHawk supports PDF, JPEG, PNG, plain
text, and Markdown inputs. A public `file_...` ID separates storage from later
jobs, so one upload can be processed by multiple extractors or parsers. Parse
jobs accept PDF, JPEG, and PNG files; extraction jobs accept every supported
file type and inline text.

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

## Parser

A parser is a reusable document-to-Markdown definition. It has an immutable
`parser_...` ID, stable name, display name, optional instructions and reasoning
effort, and a provider/model selection. The output format is `markdown` in v0.3.

A fresh installation includes the read-only `document-to-markdown` parser. It
uses the bundled NuExtract3 runtime by default, while custom parsers can select
another vision-capable model.

## Provider

A provider stores connection state for a model service. ParseHawk has fixed
slots for `openai_compatible_api`, `openai`, and `microsoft_foundry`. API keys
are write-only at the API boundary and encrypted at rest.

## Extraction Job

An extraction job is one asynchronous attempt to apply an extractor to a file
or inline text. It uses a legacy-compatible `job_...` ID and returns a
schema-valid object under `result.data` when completed. Its canonical REST
collection is `/v1/extraction-jobs`.

## Parse Job

A parse job applies a parser to one uploaded PDF, JPEG, or PNG. Its
`parse_job_...` record contains an immutable parser snapshot, resolved execution
metadata, and—when completed—both whole-document and per-page Markdown.

The ordered `result.pages` array is canonical. `result.content` is derived by
joining page content with `\n\n<!-- page-break -->\n\n`, and `page_count` always
matches the number of pages.

Both job resources preserve their outcomes when the reusable definition changes.
Create a new job to evaluate an updated extractor or parser.
