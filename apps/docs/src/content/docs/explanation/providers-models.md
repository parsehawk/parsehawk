---
title: Providers and model adapters
description: How extraction and parsing select local or cloud model behavior without exposing adapter internals.
sidebar:
  order: 5
---

ParseHawk treats provider connection details, model identity, and workflow
behavior as separate concerns.

## Provider slots hold connections

The three provider slots store a base URL, provider-specific configuration, and
an encrypted API key where needed. They are fixed so APIs and UI controls can
remain predictable; operators configure them rather than creating arbitrary
provider kinds.

The `openai_compatible_api` slot is deliberately broad. It can point at the
bundled vLLM runtime, Ollama, LM Studio, or another compatible server. Because it
is one slot, it points to one compatible endpoint at a time.

## Extractors and parsers choose execution

Each extractor and parser records a provider name and optional model. A missing
provider uses `openai_compatible_api`; a missing model on that provider inherits
the configured bundled model default. Hosted providers require an explicit
model.

When a worker claims a job, it resolves that pair and records execution metadata
with the job. Parse jobs additionally record the internal adapter name and
execute their immutable parser snapshot.

## Workflow-specific payload adapters

All provider paths use the OpenAI Python client and chat-completions transport.
The selected model determines the payload:

| Workflow   | Model                              | Adapter behavior                                                                                  |
| ---------- | ---------------------------------- | ------------------------------------------------------------------------------------------------- |
| Extraction | Exact supported NuExtract3 variant | Fine-tuned extraction template, semantic types, and runtime-specific arguments                    |
| Extraction | Any other model                    | Schema-derived prompt and JSON Schema response format                                             |
| Parsing    | Exact supported NuExtract3 variant | `chat_template_kwargs.mode=markdown`; no extraction template and no JSON response format          |
| Parsing    | Any other model                    | Page-aware vision messages and a Markdown-transcription prompt; no structured response constraint |

NuExtract3 parsing forwards optional parser instructions as a system message and
removes thinking blocks and generation controls from returned Markdown. The
generic parser asks the model to preserve reading order, headings, lists,
tables, code, formulas, and meaningful visual descriptions without adding
commentary. Adapter selection is internal and cannot be written through the
Parser API.

## Capability follows the selected model

Provider compatibility does not imply multimodal capability. Text-only models
can process inline text and text extraction inputs. Parse jobs always send an
image—or rendered PDF page—as an OpenAI `image_url` content part, so a custom
parsing model must support vision. A provider rejection that identifies this
mismatch is stored as `model_modality_incompatible`.

Reasoning effort is also provider- and model-dependent. ParseHawk forwards an
explicit value on the generic path; the provider decides whether it is valid.

Use the [provider chooser](/how-to/providers/) for concrete configuration.
