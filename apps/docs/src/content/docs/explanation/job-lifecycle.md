---
title: Job lifecycle
description: The asynchronous state machine behind extraction, cancellation, and deletion.
sidebar:
  order: 6
---

An extraction job is a persistent state machine. The API accepts it quickly; a
worker performs model inference outside the request lifecycle.

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
response proves acceptance, not successful extraction. Clients should persist
the returned job ID.

## Execution

A worker claims queued work and moves it to `running`. It loads the input and
examples, resolves provider and model configuration, performs the model call,
and validates the returned object.

- valid output produces `completed` with `result.data`
- an unrecoverable processing or provider error produces `failed`
- a cancellation request moves active work through `canceling`

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
Files and extractors referenced by a job remain protected from deletion until
the job itself has been removed.

## Client design

Use bounded polling with backoff, distinguish every terminal state, and do not
automatically duplicate a job after an ambiguous network response. The API does
not currently expose idempotency keys for job creation.
