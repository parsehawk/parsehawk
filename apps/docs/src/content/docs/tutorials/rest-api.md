---
title: Parse and extract through the REST API
description: Upload one document, create both job types, and read Markdown and structured JSON with curl.
sidebar:
  order: 4
---

This tutorial uses one receipt image to exercise both ParseHawk workflows. You
will upload the file once, extract schema-valid JSON, and parse complete Markdown
through the REST API.

Start ParseHawk before you continue. The examples also require `curl` and `jq`.

## 1. Set the API address

```console
API=http://127.0.0.1:8000
```

## 2. Upload the file once

```console
FILE_ID=$(
  curl --fail --silent --show-error \
    --request POST "$API/v1/files" \
    --form "upload=@tests/fixtures/receipt/receipt.jpg;type=image/jpeg" |
    jq -r '.id'
)

printf '%s\n' "$FILE_ID"
```

The returned public ID starts with `file_`. Both jobs will refer to this stored
file.

## 3. Create an extraction job and a parse job

Create structured extraction with the seeded `receipt` extractor:

```console
EXTRACTION_JOB_ID=$(
  curl --fail --silent --show-error \
    --request POST "$API/v1/extraction-jobs" \
    --header "Content-Type: application/json" \
    --data "{\"extractor_name\":\"receipt\",\"file_id\":\"$FILE_ID\"}" |
    jq -r '.id'
)
```

Create Markdown parsing with the seeded `document-to-markdown` parser:

```console
PARSE_JOB_ID=$(
  curl --fail --silent --show-error \
    --request POST "$API/v1/parse-jobs" \
    --header "Content-Type: application/json" \
    --data "{\"parser_name\":\"document-to-markdown\",\"file_id\":\"$FILE_ID\"}" |
    jq -r '.id'
)

printf 'extraction=%s\nparsing=%s\n' "$EXTRACTION_JOB_ID" "$PARSE_JOB_ID"
```

Both `201 Created` responses prove that the API accepted work. Model execution
continues asynchronously in the worker.

## 4. Wait for both jobs

Define one polling helper for the two resource collections:

```console
wait_for_job() {
  resource=$1
  job_id=$2

  while true; do
    job=$(curl --fail --silent --show-error "$API/v1/$resource/$job_id")
    status=$(printf '%s' "$job" | jq -r '.status')

    case "$status" in
      completed|failed|canceled)
        printf '%s\n' "$job"
        return
        ;;
    esac

    sleep 1
  done
}

EXTRACTION_JOB=$(wait_for_job extraction-jobs "$EXTRACTION_JOB_ID")
PARSE_JOB=$(wait_for_job parse-jobs "$PARSE_JOB_ID")
```

Production clients should add backoff and a deadline. They must handle
`completed`, `failed`, and `canceled` as terminal states.

## 5. Compare the results

Check both states:

```console
printf 'extraction: %s\n' "$(printf '%s' "$EXTRACTION_JOB" | jq -r '.status')"
printf 'parsing: %s\n' "$(printf '%s' "$PARSE_JOB" | jq -r '.status')"
```

Read the fixed JSON fields from the extraction job:

```console
printf '%s' "$EXTRACTION_JOB" | jq '.result.data'
```

Read the complete Markdown from the parse job:

```console
printf '%s' "$PARSE_JOB" | jq -r '.result.content'
```

The extraction result follows the `receipt` JSON Schema. The parsing result
preserves the receipt as Markdown and also includes `result.pages` for page
attribution.

## 6. Clean up the tutorial resources

Jobs protect the file they reference. Delete both jobs before the file:

```console
curl --fail --silent --show-error \
  --request DELETE "$API/v1/extraction-jobs/$EXTRACTION_JOB_ID"
curl --fail --silent --show-error \
  --request DELETE "$API/v1/parse-jobs/$PARSE_JOB_ID"
curl --fail --silent --show-error \
  --request DELETE "$API/v1/files/$FILE_ID"
```

You can now repeat the tutorial without retaining its file or job records.

## Use the contract as your source of truth

The [generated REST API reference](/reference/api/) documents every operation,
request, response, and error. Download the exact OpenAPI 3.1 document from
[`/openapi.yaml`](/openapi.yaml) for code generation or contract tests.
