---
title: What local-first means
description: The privacy boundary of ParseHawk's default setup and the deliberate ways data can leave it.
sidebar:
  order: 2
---

Local-first means ParseHawk's default parsing and extraction paths store and
process documents on infrastructure you run. They do not require a third-party
model API to produce Markdown or structured JSON.

## What stays local by default

- uploaded PDFs, images, text, and Markdown
- extractor instructions, schemas, and examples
- parser instructions and parser configuration
- extraction jobs, parse jobs, extracted JSON, and parsed Markdown
- provider credentials, encrypted in the data directory
- NuExtract3 inference through vLLM or vLLM Metal
- Phoenix model traces

The standard service ports bind to `127.0.0.1`, not every network interface.

## What can make outbound requests

Local-first is not identical to offline or air-gapped:

- Initial setup pulls packages, containers, and model weights.
- Anonymous telemetry reports an install event and job-start events
  unless disabled. It excludes document content, filenames, instructions,
  schemas, extracted JSON, and parsed Markdown.
- An extractor or parser assigned to OpenAI, Microsoft Foundry, Ollama on
  another host, or any remote compatible endpoint sends that job's model input
  to the configured server.
- An external OTLP endpoint receives model traces, which can contain sensitive
  inputs and outputs.

Provider choice is per extractor and parser. Using a cloud provider for one
definition does not silently reroute other definitions.

## Make an installation more isolated

Disable anonymous telemetry:

```console
export PARSEHAWK_TELEMETRY_DISABLED=1
# or
export DO_NOT_TRACK=1
```

Keep the bundled provider and Phoenix, bind service ports to loopback, and avoid
external OTLP endpoints. For a truly air-gapped deployment, pre-stage every
container, Python package, Node package, model artifact, and runtime dependency;
the default installer assumes it can reach their registries.

## Treat local storage as sensitive

Local processing removes a third-party transmission, but it does not replace
host security. The `data/` directory can contain original documents, parsed
Markdown, extracted values, provider keys, and model traces. Apply access
controls, encrypted disks, backups, retention policies, and deletion procedures
appropriate to that data.
