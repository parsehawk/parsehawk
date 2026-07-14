---
title: Use the Web UI
description: Manage files, extractors, and extraction jobs in the browser without coupling docs to changing screen layouts.
sidebar:
  order: 9
---

The Web UI at `http://127.0.0.1:5173` is a client of the same REST API used by
the CLI. Resources created in one surface are immediately available in the
others.

## Run an extraction

1. Open **Files** and upload a supported PDF, image, text, or Markdown file.
2. Open **Extractors** and choose an existing extractor, or create one with
   instructions and a schema.
3. Start a run with the uploaded file.
4. Open **Jobs** and inspect the lifecycle state.
5. When the job is completed, review the structured fields and canonical JSON.

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

## Move between UI, CLI, and API

Use the stable name shown for an extractor in CLI commands:

```console
parsehawk extract document.pdf --extractor invoice_v1 --wait
```

Use the `file_...`, `extractor_...`, and `job_...` IDs shown in the UI when an
API operation requires a canonical resource ID.

This page intentionally avoids step-by-step screenshots while the UI evolves.
The resource names and outcomes are the stable contract; the generated
[REST API reference](/reference/api/) and [CLI reference](/reference/cli/) are
authoritative for automation.
