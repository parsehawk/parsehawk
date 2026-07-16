---
title: Use the bundled vLLM runtime
description: Run the default NuExtract3 model locally through vLLM or vLLM Metal.
sidebar:
  order: 4
---

The bundled runtime is ParseHawk's zero-configuration provider path. It serves
`numind/NuExtract3-W4A16` through an OpenAI-compatible API and keeps document
content on the local machine.

## Start the default stack

```console
parsehawk start
```

ParseHawk chooses the platform implementation automatically:

- macOS Apple Silicon runs vLLM Metal natively on the host.
- Linux x86_64 or ARM64 with NVIDIA runs vLLM in Docker Compose.

## Inspect and test the runtime

```console
parsehawk runtime info
parsehawk runtime doctor
parsehawk runtime test
```

The runtime API listens on `http://127.0.0.1:8080/v1` by default. The first
start downloads model artifacts and warms the engine, so readiness takes longer
than on later starts.

## Assign an extractor

New extractors default to the `openai_compatible_api` provider. Leave the model
unset to inherit the active bundled model, or set it explicitly:

```console
parsehawk extractors update invoice_v1 \
  --provider openai_compatible_api \
  --model numind/NuExtract3-W4A16
```

Exact NuExtract3 variants receive the fine-tuned NuExtract chat template. Other
model names use ParseHawk's generic structured-extraction prompt.

## Change runtime resources

```console
PARSEHAWK_VLLM_MAX_MODEL_LEN=16384 \
PARSEHAWK_VLLM_MAX_NUM_SEQS=2 \
parsehawk restart
```

Context length and concurrency consume more unified memory or VRAM. See
[deployment and hardware](/explanation/deployment-hardware/) before raising
defaults on a constrained machine.

## Return after using another compatible server

Ollama and other compatible servers reuse the same provider slot. To restore
the bundled endpoint, configure the URL visible to the Docker worker, then
restart with the runtime enabled:

```console
# macOS Apple Silicon
parsehawk providers configure openai_compatible_api \
  --base-url http://host.docker.internal:8080/v1
parsehawk restart
```

On Linux Compose, use the service-network URL instead:

```console
parsehawk providers configure openai_compatible_api \
  --base-url http://runtime:8080/v1
parsehawk restart
```
