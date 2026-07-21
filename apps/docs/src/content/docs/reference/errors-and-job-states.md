---
title: Errors and job states
description: HTTP error envelopes, common status codes, and the complete asynchronous job state contract.
sidebar:
  order: 7
---

## API error envelope

Domain and server errors use a `detail` field. Actionable or retryable errors
also include a stable `code`:

```json
{
  "code": "persistence_busy",
  "detail": "Persistence is temporarily busy; retry the request"
}
```

The `code` field is omitted when an error has no machine-readable code. FastAPI
request-shape validation can return structured validation details in `detail`.
Clients should not assume `detail` is always a string.

## Common HTTP statuses

| Status                      | Meaning                                                                    |
| --------------------------- | -------------------------------------------------------------------------- |
| `200 OK`                    | Read or update completed                                                   |
| `201 Created`               | File, extractor, or job created                                            |
| `202 Accepted`              | Deletion requested for active work and will finish asynchronously          |
| `204 No Content`            | Resource deleted synchronously                                             |
| `400 Bad Request`           | Provider/model request failed or the operation is invalid in current state |
| `404 Not Found`             | Referenced resource does not exist, or asynchronous deletion finished      |
| `409 Conflict`              | Resource identity conflicts with existing state                            |
| `422 Unprocessable Content` | Request, schema, or domain input failed validation                         |
| `503 Service Unavailable`   | SQLite write contention exceeded its wait; retry with backoff              |
| `500 Internal Server Error` | Unexpected server failure                                                  |

Use the [generated API operation](/reference/api/) for the exact statuses a
specific endpoint declares.

## Job states

| State       | Terminal | Result | Error | Meaning                                    |
| ----------- | -------- | ------ | ----- | ------------------------------------------ |
| `queued`    | No       | No     | No    | Accepted and waiting for a worker          |
| `running`   | No       | No     | No    | Claimed and actively extracting            |
| `canceling` | No       | No     | No    | Cancellation requested; worker is stopping |
| `deleting`  | No       | No     | No    | Deletion requested; record will be removed |
| `completed` | Yes      | Yes    | No    | `result.data` contains schema-valid JSON   |
| `failed`    | Yes      | No     | Yes   | `error` describes the terminal failure     |
| `canceled`  | Yes      | No     | No    | Work ended by cancellation                 |

Job error objects contain a machine-oriented `code` and human-oriented
`message`. Do not parse prose to implement retry policy.

## Polling rules

- Persist the job ID before polling.
- Stop on `completed`, `failed`, or `canceled`.
- For `deleting`, stop when the API returns 404.
- Apply a client-side deadline and backoff.
- Do not assume a timed-out creation request failed; check for accepted work
  before submitting a duplicate.
