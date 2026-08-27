---
title: Customize Markdown parsing
description: Create a reusable parser with additional Markdown instructions and a model chosen for your documents.
sidebar:
  order: 6
---

Use a custom parser when you need the standard document-to-Markdown behavior
with additional instructions, a different provider, or a different model. The
built-in `document-to-markdown` parser is read-only.

## Create a custom parser

Create or replace a parser with a stable name:

```console
parsehawk parsers put technical-markdown \
  --display-name "Technical document Markdown" \
  --instructions "Preserve section numbers. Describe diagrams without adding conclusions."
```

When the provider and model are omitted, the parser uses the local
`openai_compatible_api` provider and its default model.

Inspect the saved definition:

```console
parsehawk parsers get technical-markdown
```

## Run the parser

```console
parsehawk parse report.pdf \
  --parser technical-markdown \
  --wait \
  --output report.md
```

Parsing requires a PDF, JPEG, or PNG. A custom parser still produces the same
complete-document and per-page result contract as the built-in parser.

## Write focused instructions

The base parsing prompt already asks the model to preserve reading order,
headings, paragraphs, lists, tables, code, formulas, and meaningful visual
information. Add only rules that are specific to your use case, such as:

- preserve legal clause and section numbers
- use a fixed heading level for document titles
- describe diagrams, stamps, or handwritten notes
- keep repeated headers or footers that have evidential value
- omit repeated decorative headers when they have no content value

Do not ask a parser to return a fixed JSON object. Use an
[extractor](/tutorials/reusable-extractor/) when you need named, typed fields.

## Select another provider and model

Configure the provider first, then assign a vision-capable model:

```console
parsehawk providers models openai

parsehawk parsers update technical-markdown \
  --provider openai \
  --model YOUR_VISION_MODEL_ID
```

Parse jobs always send image content. A text-only model fails with
`model_modality_incompatible`. See the [provider guides](/how-to/providers/) for
connection setup.

## Change a parser without changing queued work

Each parse job stores an immutable `parser_snapshot` when it is created. An
update affects new jobs only:

```console
parsehawk parsers update technical-markdown \
  --instructions "Preserve section numbers and all table footnotes."
```

Use a new stable name, such as `technical-markdown-v2`, when consumers must
adopt a material behavior change on their own schedule. Keep the full `parsers
put` command and its instruction file in version control for repeatable
deployments.

## Delete a custom parser

A parser that is referenced by a parse job cannot be deleted. Remove its jobs
first, then delete the parser:

```console
parsehawk parse-jobs delete parse_job_...
parsehawk parsers delete technical-markdown
```

The built-in `document-to-markdown` parser cannot be updated or deleted.
