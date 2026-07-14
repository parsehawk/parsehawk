---
title: Use Microsoft Foundry
description: Connect ParseHawk to an OpenAI-compatible Foundry deployment and discover chat models.
sidebar:
  order: 7
---

The `microsoft_foundry` provider separates the inference endpoint from the
project endpoint used to discover deployments.

## Collect the two URLs

You need:

- the OpenAI-compatible endpoint ending in `/openai/v1`
- the project endpoint ending in `/api/projects/<project-name>`
- an API key allowed to call the deployment and read project deployments

## Configure the provider

```console
export MICROSOFT_FOUNDRY_API_KEY=...

parsehawk providers configure microsoft_foundry \
  --base-url https://resource.services.ai.azure.com/openai/v1 \
  --project-url https://resource.services.ai.azure.com/api/projects/project-name \
  --api-key-env MICROSOFT_FOUNDRY_API_KEY
```

Inspect the stored non-secret configuration and list compatible deployments:

```console
parsehawk providers get microsoft_foundry
parsehawk providers models microsoft_foundry
```

## Assign the deployment

The extractor's `model` is the chat-completions deployment name, not necessarily
the underlying catalog model name:

```console
parsehawk extractors update invoice_v1 \
  --provider microsoft_foundry \
  --model my-chat-deployment
```

Choose a deployment that supports structured chat completions. Image and PDF
inputs also require image capability.

## Start without the bundled runtime

```console
parsehawk start -x runtime
```

Provider keys remain encrypted in the shared ParseHawk data directory. Both API
and worker must use the same database and secret-key source.
