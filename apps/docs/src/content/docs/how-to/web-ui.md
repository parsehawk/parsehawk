---
title: Use the Web UI
description: Run extraction and page-aware Markdown parsing in the browser using the same resources as the API and CLI.
sidebar:
  order: 9
---

The Web UI at `http://127.0.0.1:5173` is a client of the same REST API used by
the CLI. Resources created in one surface are immediately available in the
others.

## Run an extraction

1. Select the **Extract** workflow.
2. Upload a supported PDF, image, text, or Markdown file.
3. Choose an existing extractor, or create one with
   instructions and a schema.
4. Start a run with the uploaded file.
5. Inspect **Extraction jobs** for lifecycle state, execution metadata, and the
   structured result.

The seeded `Receipt` extractor and
`tests/fixtures/receipt/receipt.jpg` are a known-good first path.

## Create an extractor safely

- Give the extractor a stable API name that can outlive a UI label.
- Describe each schema field precisely and use nullable values for legitimate
  absence.
- Validate the schema before depending on it downstream.
- Add few-shot examples only when instructions and schema do not settle a
  recurring ambiguity.
- Select a provider and model with the capabilities required by the inputs.

The UI edits the same definition documented in [core concepts](/explanation/core-concepts/).

## Parse a document to Markdown

1. Select the **Parse** workflow.
2. Upload or choose one PDF, JPEG, or PNG.
3. Select the prebuilt **Document to Markdown** parser, or create a custom parser
   with provider, model, reasoning effort, and additional instructions.
4. Run parsing and follow the parse-job history.
5. Review rendered whole-document Markdown, switch to a one-based page view, or
   inspect the raw Markdown.
6. Copy the complete result or download it as a `.md` file.

The result panel also shows the provider, model, internal adapter, duration, and
actionable terminal error. Active parse jobs can be canceled, and completed jobs
can be deleted. The parsing token budget is server-controlled through
`PARSEHAWK_PARSING_MAX_TOKENS` and displayed in parser settings.

## Move between UI, CLI, and API

Use the stable name shown for an extractor in CLI commands:

```console
parsehawk extract document.pdf --extractor invoice_v1 --wait
```

Use the `file_...`, `extractor_...`, `parser_...`, `job_...`, and
`parse_job_...` IDs shown in the UI when an API operation requires a canonical
resource ID.

This page intentionally avoids step-by-step screenshots while the UI evolves.
The resource names and outcomes are the stable contract; the generated
[REST API reference](/reference/api/) and [CLI reference](/reference/cli/) are
authoritative for automation.
