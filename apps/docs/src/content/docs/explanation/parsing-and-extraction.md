---
title: Parsing and extraction
description: How ParseHawk's Markdown parsing and structured JSON extraction workflows differ, relate, and fit common document tasks.
sidebar:
  order: 3
---

ParseHawk supports two document workflows. They answer different questions:

- **Parsing:** What does the complete document contain?
- **Extraction:** What are the specific values my application needs?

Both workflows use the same files, providers, model runtime, asynchronous job
states, CLI, Web UI, and REST API. They use separate reusable definitions and
separate job collections because their output contracts are different.

## Parsing produces page-aware Markdown

Parsing converts each PDF page or image into Markdown. It aims to preserve the
source's reading order, headings, paragraphs, lists, tables, code, formulas, and
meaningful visual information. The result includes one Markdown string for the
complete document and a canonical array with one entry per source page.

Parsing is a good fit when you need to:

- give complete document content to an LLM
- build search, retrieval, or citation workflows
- retain page numbers with stored chunks
- inspect or transform content before you know its final schema
- produce readable Markdown from a PDF or image

The parser does not select a fixed set of business fields. Its contract is the
document's Markdown representation.

## Extraction produces schema-valid JSON

Extraction applies instructions and a JSON Schema to a document or text. It
returns only the fields in that contract. A job cannot complete successfully
unless the result satisfies the extractor schema.

Extraction is a good fit when you need to:

- populate application or database fields
- classify a document into a closed set of values
- normalize dates, amounts, identifiers, or other typed values
- enforce a stable response shape for downstream code
- distinguish a missing value from an omitted field

The extractor can work directly from PDFs, images, text, or Markdown. Parsing is
not a required preprocessing step.

## Choose by the output you need

| Need                                      | Use        | Output                                      |
| ----------------------------------------- | ---------- | ------------------------------------------- |
| Preserve the complete source              | Parsing    | Page-aware Markdown                         |
| Return a fixed set of fields              | Extraction | JSON validated against an extraction schema |
| Keep page references for retrieval        | Parsing    | `pages[].page_number` and Markdown          |
| Feed stable values into application logic | Extraction | `result.data`                               |
| Search first and define fields later      | Parsing    | Complete document content                   |
| Apply both outcomes to one upload         | Both       | Independent parse and extraction jobs       |

Do not use extraction as a substitute for complete transcription. A small JSON
schema can discard content that is important later. Do not use parsing as a
substitute for a stable application contract. Markdown can preserve content but
does not guarantee named, typed business fields.

## Combine the workflows when useful

One uploaded `file_...` resource can be used by both an extraction job and a
parse job. This is useful when an application needs structured fields for
automation and complete Markdown for review, search, or later LLM work.

You can also pass parsed Markdown to a later extraction job as inline text or a
Markdown file. Use that sequence only when the Markdown representation is the
input you want. Direct extraction from the source document can retain layout
and visual context that an intermediate text form does not.

## Separate resource pairs

| Workflow   | Reusable definition | Asynchronous run | Completed result                    |
| ---------- | ------------------- | ---------------- | ----------------------------------- |
| Parsing    | Parser              | Parse job        | `result.pages` and `result.content` |
| Extraction | Extractor           | Extraction job   | `result.data`                       |

Parsers live at `/v1/parsers`, and parse jobs live at `/v1/parse-jobs`.
Extractors live at `/v1/extractors`, and extraction jobs live at
`/v1/extraction-jobs`.

Continue with the [Markdown tutorial](/tutorials/document-to-markdown/) or the
[structured JSON tutorial](/tutorials/first-extraction/).
