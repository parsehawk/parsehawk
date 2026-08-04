---
title: Parse a document to Markdown
description: Parse a PDF or image with the bundled NuExtract3 parser and consume whole-document and per-page Markdown.
sidebar:
  order: 4
---

This tutorial uses the read-only `document-to-markdown` parser that ships with a
fresh ParseHawk installation. Parsing is a separate workflow from structured
extraction: it produces source-faithful Markdown for LLM prompts, citations, and
vector-database ingestion.

## Run the one-shot CLI workflow

Start ParseHawk, then run:

```console
parsehawk parse tests/fixtures/receipt/receipt.pdf \
  --wait \
  --output receipt.md
```

The command uploads the file, creates a parse job, polls with a bounded timeout,
and writes complete-document Markdown. `document-to-markdown` is selected when
`--parser` is omitted. Use `--timeout-seconds` to change the 600-second client
deadline, or omit `--output` to print Markdown to stdout.

## Run the same workflow over HTTP

```console
API=http://127.0.0.1:8000

FILE_ID=$(
  curl --fail --silent --show-error \
    --request POST "$API/v1/files" \
    --form "upload=@tests/fixtures/receipt/receipt.pdf;type=application/pdf" |
    jq -r '.id'
)

PARSE_JOB_ID=$(
  curl --fail --silent --show-error \
    --request POST "$API/v1/parse-jobs" \
    --header "Content-Type: application/json" \
    --data "{\"parser_name\":\"document-to-markdown\",\"file_id\":\"$FILE_ID\"}" |
    jq -r '.id'
)
```

Poll the top-level parse-job resource:

```console
while true; do
  PARSE_JOB=$(curl --fail --silent --show-error "$API/v1/parse-jobs/$PARSE_JOB_ID")
  STATUS=$(jq -r '.status' <<<"$PARSE_JOB")
  case "$STATUS" in
    completed|failed|canceled) break ;;
  esac
  sleep 1
done

jq -r '.result.content' <<<"$PARSE_JOB" > receipt.md
```

Production clients should add backoff and a deadline and handle every terminal
state.

## Understand the result

For a two-page document, the completed result has this shape:

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

`pages` is canonical and strictly one-based. ParseHawk derives `content` by
joining ordered pages with `\n\n<!-- page-break -->\n\n`; `page_count` always
equals the array length. A JPEG or PNG has one page. Every page must succeed, so
the MVP never returns a partial document.

Store `pages[].page_number` beside vector chunks when downstream retrieval needs
page citations. Use `content` when an LLM or tool expects one Markdown document.

## Use the Web UI

Open `http://127.0.0.1:5173`, select **Parse**, upload a PDF or image, keep
**Document to Markdown** selected, and run parsing. The result panel offers:

- rendered whole-document and per-page views
- raw Markdown
- copy and download actions
- provider, model, adapter, and duration metadata
- cancellation, deletion, and actionable errors

Custom parsers can add instructions or choose another vision-capable configured
model. The server-wide per-page generation budget defaults to 4,096 tokens and
is configured with `PARSEHAWK_PARSING_MAX_TOKENS`.
