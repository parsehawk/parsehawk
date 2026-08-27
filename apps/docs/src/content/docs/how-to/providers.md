---
title: Choose a model provider
description: Pick the bundled runtime, Ollama, OpenAI, Microsoft Foundry, or another OpenAI-compatible server.
sidebar:
  order: 3
---

Every extractor and parser selects a `provider` and `model`. Start with the path
that matches where you want inference to run:

| Path                  | Best when                                                                | Setup                                                      |
| --------------------- | ------------------------------------------------------------------------ | ---------------------------------------------------------- |
| Bundled vLLM runtime  | You want ParseHawk's default, fully local NuExtract3 setup               | [Use the bundled runtime](/how-to/bundled-runtime/)        |
| Ollama                | You want a simple local model manager or a small vision-language model   | [Use Ollama locally](/how-to/ollama/)                      |
| OpenAI                | You want a first-party OpenAI model                                      | [Use OpenAI](/how-to/openai/)                              |
| Microsoft Foundry     | Your organization deploys models through Foundry                         | [Use Microsoft Foundry](/how-to/microsoft-foundry/)        |
| Any compatible server | You operate LM Studio, a separate vLLM server, or another implementation | [Use an OpenAI-compatible API](/how-to/openai-compatible/) |

The bundled runtime, Ollama, and generic servers share the
`openai_compatible_api` provider slot. Changing that slot changes the endpoint
for every extractor and parser assigned to it. Use separate ParseHawk
installations when you must target multiple compatible endpoints at the same
time.

## Inspect current configuration

```console
parsehawk providers list
parsehawk providers get openai_compatible_api
parsehawk providers models openai_compatible_api
```

API keys are encrypted at rest and are never returned by the API.

## Skip the bundled runtime

If every active extractor and parser uses a separate endpoint, avoid loading
NuExtract3:

```console
parsehawk start -x runtime
```

Use this for every provider path except the bundled runtime. The API, worker,
Web UI, and Phoenix still start normally.

## Assign a provider and model

Provider configuration stores connection details. Each extractor or parser
stores which slot and model it should use:

```console
parsehawk extractors update invoice_v1 \
  --provider openai_compatible_api \
  --model my-model

parsehawk parsers update technical-markdown \
  --provider openai_compatible_api \
  --model my-vision-model
```

New jobs use the current definition. Parse jobs snapshot parser configuration at
creation time. Each job records the provider and model that execution resolved.
