---
title: API stability and versioning
description: What the v1 resource paths, SemVer releases, and checked OpenAPI contract guarantee today.
sidebar:
  order: 8
---

ParseHawk follows Semantic Versioning and exposes resource paths under `/v1`.
The project is still a developer preview below version 1.0, so consumers should
pin releases and review upgrade notes.

## The contract is generated from the application

FastAPI route and Pydantic model metadata generate an OpenAPI 3.1 document. The
repository commits a deterministic YAML snapshot at `openapi/openapi.yaml`.
Pre-commit and CI regenerate it and fail when implementation and artifact drift.

The same contract drives the [generated API reference](/reference/api/) and is
available from [`/openapi.yaml`](/openapi.yaml) for tools and future SDK
generation.

## SDK-facing identifiers are deliberate

Every operation has an explicit, stable `operationId` such as `uploadFile`,
`createExtractionJob`, or `createParseJob`. Schemas include descriptions,
formats, examples, and consistent error responses. Automated linting checks the
document for structural and SDK-readiness problems.

These choices reduce accidental generator churn, but they are not a promise
that every pre-1.0 shape is frozen.

## Extraction-job migration in v0.3

`/v1/extraction-jobs` is the canonical extraction collection beginning in v0.3.
The older `/v1/jobs` paths remain compatibility aliases throughout v0.3: they
read and mutate the same records with the same status codes and response data.
Every legacy operation is marked deprecated in OpenAPI.

Use `parsehawk extraction-jobs ...` in scripts. `parsehawk jobs ...` remains an
alias in v0.3 and prints a migration warning. Both the REST and CLI aliases are
removed in v0.4. Extraction job IDs keep their existing opaque `job_...` form;
there is no identifier rewrite during migration.

Parsing is not added as a variant of the old collection. Parsers live at
`/v1/parsers`, and their asynchronous work lives independently at
`/v1/parse-jobs` with `parse_job_...` identifiers.

## Treat extractor schemas as your own API

The ParseHawk REST contract controls resources. Each extractor schema separately
controls the JSON your application consumes. A schema change can be breaking
even when the REST API version does not change.

Use stable extractor names for compatible evolution. Create a new versioned
name, such as `invoice_v2`, when consumers need to adopt a breaking output shape
on their own schedule.

## Recommended client posture

- Pin a ParseHawk release or deployment version.
- Generate clients from the committed OpenAPI document for that version.
- Preserve unknown response fields when your language allows it.
- Handle documented non-2xx responses and every terminal job state.
- Contract-test the extractor schemas your application relies on.
- Review the OpenAPI diff and release notes before upgrading.
