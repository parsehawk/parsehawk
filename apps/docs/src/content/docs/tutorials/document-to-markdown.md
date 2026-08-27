---
title: Parse your first document
description: Start ParseHawk and turn the bundled receipt PDF into complete-document and per-page Markdown.
sidebar:
  order: 2
---

In this tutorial you will parse a known PDF with the prebuilt
`document-to-markdown` parser, inspect its Markdown, and find the same run in the
Web UI.

## Before you begin

Use a supported [macOS or Linux installation](/start-here/choose-installation/).
This tutorial runs from a ParseHawk repository checkout because it uses the
bundled receipt fixture.

## 1. Start ParseHawk

```console
parsehawk start
```

Wait for the services to become ready. If startup fails, run `parsehawk doctor`
and follow the reported fix.

## 2. Parse the bundled receipt

```console
parsehawk parse tests/fixtures/receipt/receipt.pdf \
  --wait \
  --output receipt.md
```

The command uploads the PDF, creates a parse job, waits for it with a 600-second
client deadline, and writes the complete-document Markdown. It selects the
read-only `document-to-markdown` parser because `--parser` is omitted.

The final line should confirm:

```text
Wrote Markdown output: receipt.md
```

## 3. Inspect the Markdown

Confirm that the output is not empty, then print its first lines:

```console
test -s receipt.md
sed -n '1,40p' receipt.md
```

The text and exact Markdown can vary with the model. You should see the receipt
content in readable Markdown instead of a fixed JSON object.

List the job that produced it:

```console
parsehawk parse-jobs list --parser document-to-markdown
```

The completed job contains both `result.content` for the complete document and
`result.pages` for one-based source pages. ParseHawk joins multiple pages with
an HTML `page-break` comment.

## 4. Inspect the same run in the Web UI

Open `http://127.0.0.1:5173`, select **Parse**, and open the newest parse job.
You can switch between these result views:

- rendered complete-document Markdown
- rendered Markdown for one source page
- raw Markdown

The result panel also shows the provider, model, internal adapter, duration, and
job state. You can copy or download the Markdown from the same page.

## What you built

You exercised the complete parsing path:

```text
document → uploaded file → parse job → page images → Markdown
```

Parsing keeps the document's content and page structure. It does not select a
predefined set of business fields. Compare the two output models in
[parsing and extraction](/explanation/parsing-and-extraction/).

Next, [customize Markdown parsing](/how-to/customize-parsing/) or run
[parsing and extraction through the REST API](/tutorials/rest-api/).
