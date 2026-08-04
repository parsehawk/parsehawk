---
title: Job lifecycle
description: The shared asynchronous state machine behind extraction jobs, parse jobs, cancellation, and deletion.
sidebar:
  order: 6
---

Extraction jobs and parse jobs are distinct persistent resources that use the
same lifecycle. The API accepts work quickly; a worker performs model inference
outside the request lifecycle.

```text
queued ───────────────▶ running ───────────────▶ completed
  │                       │  │
  │ cancel                │  └────────────────▶ failed
  ▼                       │ cancel
canceled                  ▼
                       canceling ──────────────▶ canceled

queued or terminal ── delete ──▶ removed
running/canceling ─── delete ──▶ deleting ─────▶ removed
```

## Submission

Creating a job validates its resource references and writes `queued`. The
response proves acceptance, not successful extraction or parsing. Clients should
persist the returned `job_...` or `parse_job_...` ID.

## Execution

A worker claims queued work and moves it to `running`. It loads the input,
resolves provider and model configuration, performs the model call, and validates
the workflow-specific result.

- extraction success produces `completed` with schema-valid `result.data`
- parsing success produces `completed` with canonical ordered `result.pages`
  plus derived `result.content` and `result.page_count`
- an unrecoverable processing or provider error produces `failed`
- a cancellation request moves active work through `canceling`

Parse jobs snapshot their parser when submitted. Editing a parser cannot change
queued work. All source pages must succeed in v0.3; one failed page fails the
whole parse job rather than returning a partial result.

## Cancellation

A queued job can become `canceled` immediately. A running job first becomes
`canceling`; the worker checks for cancellation while streaming model output and
then records `canceled`.

Cancellation is cooperative. The state acknowledges the request before the
worker has necessarily released every resource.

## Deletion

Queued and terminal jobs can be removed synchronously. Deleting a running or
canceling job records `deleting`, asks the worker to stop, and removes the record
after the worker observes the request.

Clients polling a deleting job should treat a later 404 as successful removal.
Files, extractors, and parsers referenced by their respective jobs remain
protected from deletion until the job itself has been removed.

## Client design

Use bounded polling with backoff, distinguish every terminal state, and do not
automatically duplicate a job after an ambiguous network response. The API does
not currently expose idempotency keys for job creation.
