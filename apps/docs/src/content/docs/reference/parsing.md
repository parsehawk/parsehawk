---
title: Parsing reference
description: Exact parsing inputs, built-in defaults, parser fields, Markdown result invariants, limits, and execution metadata.
sidebar:
  order: 5
---

Parsing converts one uploaded PDF or image into ordered Markdown. It uses a
reusable parser and an asynchronous parse job.

## Resource surface

| Purpose              | REST API           | CLI                          |
| -------------------- | ------------------ | ---------------------------- |
| Manage definitions   | `/v1/parsers`      | `parsehawk parsers ...`      |
| Run and inspect work | `/v1/parse-jobs`   | `parsehawk parse-jobs ...`   |
| Upload and wait      | Multiple endpoints | `parsehawk parse ... --wait` |

The generated [REST API reference](/reference/api/) and
[CLI reference](/reference/cli/) define every operation and field.

## Accepted inputs

Parse jobs require one uploaded file with one of these extensions:

| Kind  | Extensions              | Page behavior                         |
| ----- | ----------------------- | ------------------------------------- |
| PDF   | `.pdf`                  | One result entry per rendered page    |
| Image | `.jpg`, `.jpeg`, `.png` | One result entry with page number `1` |

Parsing does not accept inline text, plain-text files, or Markdown files. Use an
extraction job when the source is text. PDFs render at 170 DPI and accept up to
25 pages by default. See [paths, ports, and defaults](/reference/paths-ports-defaults/)
for the configuration controls.

## Built-in parser

Every installation includes a parser with these properties:

| Property         | Value                   |
| ---------------- | ----------------------- |
| Stable name      | `document-to-markdown`  |
| Display name     | `Document to Markdown`  |
| Output format    | `markdown`              |
| Source           | `prebuilt`              |
| Mutable          | No                      |
| Default provider | `openai_compatible_api` |
| Default model    | `PARSEHAWK_VLLM_MODEL`  |

The one-shot `parsehawk parse` command selects `document-to-markdown` when you
do not provide `--parser`.

## Parser definition

A custom parser contains a stable name, display name, output format,
instructions, optional reasoning effort, provider selection, and model
selection. `markdown` is the only output format in the current developer
preview.

Parser instructions supplement the built-in transcription prompt. A custom
parser must use a model that accepts image input because each PDF page or image
is sent as an image content part.

## Completed result

The result of a completed two-page parse job has this shape:

```json
{
  "format": "markdown",
  "content": "# First page\n\n...\n\n<!-- page-break -->\n\n## Second page\n\n...",
  "page_count": 2,
  "pages": [
    { "page_number": 1, "content": "# First page\n\n..." },
    { "page_number": 2, "content": "## Second page\n\n..." }
  ]
}
```

The following invariants apply:

- `pages` is non-empty, ordered, contiguous, and one-based.
- `page_count` equals the number of entries in `pages`.
- `content` joins each page with `\n\n<!-- page-break -->\n\n`.
- One image produces one page.
- Every page must succeed. A parse job does not return a partial result.

Use `pages` when a downstream system needs source-page attribution. Use
`content` when it needs one Markdown document.

## Snapshots and execution metadata

A parse job captures `parser_snapshot` when the job is created. Later parser
edits do not change queued or completed work. When execution starts, the job
also records the provider, model, reasoning effort, and internal adapter that
the worker used.

The internal adapter is diagnostic metadata. Clients cannot select it directly.
The provider and selected model determine it.

## Limits and failure behavior

Each page has a separate generated-token budget. The default is 4,096 tokens
through `PARSEHAWK_PARSING_MAX_TOKENS`. The configured model-request timeout
applies to each page request.

A failure on any page fails the complete job. See
[errors and job states](/reference/errors-and-job-states/#parse-job-error-codes)
for stable parsing error codes and polling rules.
