---
title: Troubleshoot a local stack
description: Diagnose startup, Docker, runtime, provider, job, and storage failures.
sidebar:
  order: 9
---

Start with ParseHawk's own view of the system:

```console
parsehawk status
parsehawk doctor
```

## A service does not start

Read the component logs:

```console
ls data/logs
tail -f data/logs/api.log
tail -f data/logs/worker.log
tail -f data/logs/runtime.log
```

Then perform a controlled restart:

```console
parsehawk restart
```

The first runtime start is slower because it downloads model weights, profiles
memory, and warms kernels.

## A port is already in use

`parsehawk start` refuses to hide an unknown process behind a stale or missing
state file. Check the standard ports—5173, 8000, 6006, and 8080—and stop the
process that owns the conflicting one. Then start ParseHawk again.

## The model runtime runs out of memory

Reduce context first:

```console
PARSEHAWK_VLLM_MAX_MODEL_LEN=8192 parsehawk restart
```

On Linux, also reduce `PARSEHAWK_VLLM_MAX_NUM_SEQS` or GPU memory utilization.
Large PDFs multiply image-token and memory requirements; lower
`PARSEHAWK_PDF_MAX_PAGES` when appropriate.

## Jobs remain queued

Check that the worker is healthy and is using the same database and data
directory as the API. A healthy API alone cannot process a job. Review
`data/logs/worker.log` for a provider connection or credential error.

## An external provider is unreachable

```console
parsehawk providers get openai_compatible_api
parsehawk providers models openai_compatible_api
```

For a server on the Mac host while ParseHawk runs in Docker, use
`host.docker.internal`, not `127.0.0.1`. For Ollama, follow the
[connection checklist](/how-to/ollama/#troubleshoot-the-connection).

## Local data was removed while services were running

Stop every ParseHawk process before restoring or recreating storage. Processes
can keep deleted SQLite files open. If the state file is gone, locate and stop
the process holding the API or worker resources before starting again.

## Get a clean diagnostic

When reporting an issue, include:

- `parsehawk doctor` output
- `parsehawk status` output
- host OS, architecture, memory, and GPU
- the failing component's log excerpt with secrets and document content removed
- ParseHawk version or Git commit
- provider and model names, without API keys
