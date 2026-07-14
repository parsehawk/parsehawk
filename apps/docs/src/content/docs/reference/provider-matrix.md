---
title: Provider matrix
description: Exact provider names, connection fields, model discovery, and multimodal requirements.
sidebar:
  order: 5
---

| Provider name           | Default endpoint                   | Key      | Extra configuration | Model discovery                                           |
| ----------------------- | ---------------------------------- | -------- | ------------------- | --------------------------------------------------------- |
| `openai_compatible_api` | Platform-specific bundled vLLM URL | Optional | None                | `GET {base_url}/models`                                   |
| `openai`                | OpenAI SDK default                 | Required | None                | OpenAI models endpoint, filtered to plausible chat models |
| `microsoft_foundry`     | Operator-supplied `/openai/v1` URL | Required | `project_url`       | Foundry project deployments API                           |

Provider names are fixed. `PUT /v1/providers/{name}` updates connection state;
providers cannot be created or deleted.

## Extractor selection

| Extractor field    | Behavior when omitted                                                       |
| ------------------ | --------------------------------------------------------------------------- |
| `provider_name`    | Uses `openai_compatible_api`                                                |
| `model`            | Uses `PARSEHAWK_VLLM_MODEL`, currently `numind/NuExtract3-W4A16` by default |
| `reasoning_effort` | Leaves the model at its provider-defined default                            |

## OpenAI-compatible extraction contract

The configured endpoint needs streaming `POST /v1/chat/completions`. Generic
models receive `max_completion_tokens` and a strict `json_schema` response
format. ParseHawk retries once with legacy `max_tokens` when a server explicitly
rejects the modern field.

Images and rendered PDF pages are sent as OpenAI `image_url` content parts using
data URLs. The selected model and server must support that content shape.

## Secret handling

`api_key` and `api_key_env` are write-only configuration inputs. Read responses
expose only `has_api_key`. Stored values are encrypted with:

1. `PARSEHAWK_SECRET_KEY`, when set; otherwise
2. a generated mode-`0600` key file in the data directory.

API and worker processes must share the same key source. Key loss requires
re-entering provider credentials.

## Setup guides

- [Bundled vLLM](/how-to/bundled-runtime/)
- [Ollama](/how-to/ollama/)
- [OpenAI](/how-to/openai/)
- [Microsoft Foundry](/how-to/microsoft-foundry/)
- [Generic OpenAI-compatible API](/how-to/openai-compatible/)
