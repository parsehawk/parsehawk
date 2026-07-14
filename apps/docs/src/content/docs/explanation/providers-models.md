---
title: Providers and model adapters
description: How one extraction contract moves between local and cloud model servers.
sidebar:
  order: 5
---

ParseHawk treats provider connection details, model identity, and extraction
behavior as separate concerns.

## Provider slots hold connections

The three provider slots store a base URL, provider-specific configuration, and
an encrypted API key where needed. They are fixed so APIs and UI controls can
remain predictable; operators configure them rather than creating arbitrary
provider kinds.

The `openai_compatible_api` slot is deliberately broad. It can point at the
bundled vLLM runtime, Ollama, LM Studio, or another compatible server. Because it
is one slot, it points to one compatible endpoint at a time.

## Extractors choose execution

Each extractor records a provider name and optional model. A missing provider
uses `openai_compatible_api`; a missing model inherits the configured bundled
model default.

When a worker claims a job, it resolves that pair and records execution metadata
with the job. Changing an extractor affects new jobs, not completed outcomes.

## One transport, two payload adapters

All provider paths use the OpenAI Python client and chat-completions transport.
The selected model determines the payload:

| Model                              | Adapter behavior                                                                                     |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Exact supported NuExtract3 variant | Fine-tuned NuExtract template, semantic types, and runtime-specific arguments                        |
| Any other model                    | Standard chat messages, schema-derived template, semantic reference, and JSON Schema response format |

The generic path enables broad compatibility without pretending all model
servers behave identically. A server must still implement the required
streaming and structured-response features, and the model must be capable enough
for the document type.

## Capability follows the selected model

Provider compatibility does not imply multimodal capability. Text-only models
can process inline text and text documents. Images and rendered PDF pages require
a model that accepts OpenAI `image_url` content parts.

Reasoning effort is also provider- and model-dependent. ParseHawk forwards an
explicit value on the generic path; the provider decides whether it is valid.

Use the [provider chooser](/how-to/providers/) for concrete configuration.
