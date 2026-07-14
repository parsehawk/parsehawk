---
title: What local-first means
description: The privacy boundary of ParseHawk's default setup and the deliberate ways data can leave it.
sidebar:
  order: 2
---

Local-first means ParseHawk's default extraction path stores and processes
documents on infrastructure you run. It does not require a third-party model API
to produce structured JSON.

## What stays local by default

- uploaded PDFs, images, text, and Markdown
- extractor instructions, schemas, and examples
- job records and extracted JSON
- provider credentials, encrypted in the data directory
- NuExtract3 inference through vLLM or vLLM Metal
- Phoenix model traces

The standard service ports bind to `127.0.0.1`, not every network interface.

## What can make outbound requests

Local-first is not identical to offline or air-gapped:

- Initial setup pulls packages, containers, and model weights.
- Anonymous telemetry reports an install event and extraction-start events
  unless disabled. It excludes document content, filenames, instructions,
  schemas, and extracted data.
- An extractor assigned to OpenAI, Microsoft Foundry, Ollama on another host, or
  any remote compatible endpoint sends that extractor's model input to the
  configured server.
- An external OTLP endpoint receives model traces, which can contain sensitive
  inputs and outputs.

Provider choice is per extractor. Using a cloud provider for one extractor does
not silently reroute the others.

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
host security. The `data/` directory can contain original documents, extracted
values, provider keys, and model traces. Apply access controls, encrypted disks,
backups, retention policies, and deletion procedures appropriate to that data.
