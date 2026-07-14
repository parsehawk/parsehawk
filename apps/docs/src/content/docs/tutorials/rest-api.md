---
title: Integrate the REST API
description: Upload a file, create an asynchronous extraction job, and read its result with curl.
sidebar:
  order: 3
---

This tutorial performs the first-extraction workflow directly over HTTP. It uses
the seeded `receipt` extractor and the repository's bundled receipt image.

## 1. Set the API address

Start ParseHawk, then define a short shell variable:

```console
API=http://127.0.0.1:8000
```

## 2. Upload the file

```console
FILE_ID=$(
  curl --fail --silent --show-error \
    --request POST "$API/v1/files" \
    --form "upload=@tests/fixtures/receipt/receipt.jpg;type=image/jpeg" |
    jq -r '.id'
)

printf '%s\n' "$FILE_ID"
```

The API stores the file locally and returns a public ID beginning with `file_`.

## 3. Create a job

```console
JOB_ID=$(
  curl --fail --silent --show-error \
    --request POST "$API/v1/jobs" \
    --header "Content-Type: application/json" \
    --data "{\"extractor_name\":\"receipt\",\"file_id\":\"$FILE_ID\"}" |
    jq -r '.id'
)

printf '%s\n' "$JOB_ID"
```

Creating a job is asynchronous. A successful response does not mean extraction
has completed; it means the job was accepted.

## 4. Poll until terminal

```console
while true; do
  JOB=$(curl --fail --silent --show-error "$API/v1/jobs/$JOB_ID")
  STATUS=$(jq -r '.status' <<<"$JOB")
  printf 'status=%s\n' "$STATUS"

  case "$STATUS" in
    completed|failed|canceled) break ;;
  esac
  sleep 1
done

jq '.result.data' <<<"$JOB"
```

Production clients should use bounded retries, backoff, and their own timeout.
Treat `completed`, `failed`, and `canceled` as terminal states.

## 5. Use the contract as your source of truth

The [generated REST API reference](/reference/api/) documents every operation,
request, response, and error. Download the exact OpenAPI 3.1 document from
[`/openapi.yaml`](/openapi.yaml) for code generation or contract tests.
