---
title: Operate asynchronous jobs
description: Create, poll, cancel, delete, and retry extraction jobs safely.
sidebar:
  order: 6
---

ParseHawk extraction is asynchronous. `POST /v1/jobs` accepts work; a worker
claims it, performs the model call, validates the result, and stores the outcome.

## Create and inspect

```console
parsehawk jobs create receipt --file-id file_...
parsehawk jobs get job_...
parsehawk jobs list --extractor receipt
```

Use the one-shot helper when a shell script should upload and wait in one command:

```console
parsehawk extract document.pdf \
  --extractor invoice_v1 \
  --wait \
  --timeout-seconds 900 \
  --output result.json
```

## Handle lifecycle states

| State       | Meaning                              | Client action                                 |
| ----------- | ------------------------------------ | --------------------------------------------- |
| `queued`    | Accepted and waiting for a worker    | Poll with backoff or cancel                   |
| `running`   | A worker is extracting               | Poll; do not submit a duplicate automatically |
| `canceling` | Cancellation requested while running | Wait for `canceled`                           |
| `deleting`  | Deletion requested while running     | Stop polling once the resource returns 404    |
| `completed` | Validated result stored              | Read `result.data`                            |
| `failed`    | Processing ended with an error       | Inspect the error before deciding to retry    |
| `canceled`  | Work stopped without a result        | Submit a new job if still needed              |

## Cancel or delete

The REST API exposes a dedicated cancel operation. The CLI's delete command
applies the appropriate lifecycle behavior:

```console
parsehawk jobs delete job_...
```

A queued or terminal job can be removed immediately. A running job first enters
`deleting` while the worker observes the cancellation request.

A file or extractor referenced by any job cannot be deleted. Delete the job
explicitly first, then delete its parent resources. This preserves every job ID
that the API has returned until the client deliberately removes that job.

## Retry deliberately

Job creation does not currently accept an idempotency key. To avoid duplicates:

1. Persist the returned job ID before polling.
2. On a network timeout, query the jobs collection before submitting again.
3. Retry terminal failures only when the error is transient or the extractor has
   changed.
4. Put a client-side deadline around polling.

See [errors and job states](/reference/errors-and-job-states/) for the exact
client contract.
