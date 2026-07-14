---
title: Use OpenAI
description: Store an OpenAI API key and assign a first-party model to an extractor.
sidebar:
  order: 6
---

The `openai` provider uses the OpenAI SDK's first-party API defaults. ParseHawk
stores the key encrypted and sends only inputs for extractors explicitly
assigned to this provider.

## Configure the key

Export the key in the shell where you run the CLI, then ask ParseHawk to encrypt
and store it:

```console
export OPENAI_API_KEY=...
parsehawk providers configure openai --api-key-env OPENAI_API_KEY
```

`--api-key-env` avoids placing the literal secret in shell history. The key is
not returned by provider read endpoints.

## Choose a model

List model IDs visible to the configured account:

```console
parsehawk providers models openai
```

Assign an appropriate chat-completions model to a saved extractor:

```console
parsehawk extractors update invoice_v1 \
  --provider openai \
  --model YOUR_MODEL_ID
```

ParseHawk requests structured JSON and streams the response. For image or PDF
inputs, choose a model that accepts image content.

## Run without the bundled model

```console
parsehawk start -x runtime
```

Only extractors assigned to `openai` send document data to OpenAI. Other
extractors keep their own provider selection.

## Rotate or clear the key

Run the configure command again to rotate it. To clear the stored value:

```console
parsehawk providers configure openai --api-key ""
```

If you supply `PARSEHAWK_SECRET_KEY`, keep the same value available to API and
worker processes; losing it makes stored provider keys unreadable.
