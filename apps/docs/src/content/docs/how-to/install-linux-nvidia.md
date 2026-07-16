---
title: Install on Linux with NVIDIA
description: Run ParseHawk with Docker Compose and a GPU-backed vLLM service.
sidebar:
  order: 2
---

On Linux x86_64 and ARM64, ParseHawk runs the complete stack in Docker Compose, including
the vLLM model server.

## Requirements

- Linux on x86_64 or ARM64
- An NVIDIA GPU with 16 GB VRAM minimum; 24 GB or more for larger contexts
- NVIDIA driver and NVIDIA Container Toolkit
- Docker Engine with the Compose plugin
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

ParseHawk is verified on an NVIDIA L4 with 24 GB VRAM.

## Verify the GPU path

Before installing ParseHawk, these commands must succeed:

```console
nvidia-smi
docker info
docker compose version
uv --version
```

Also verify that Docker can expose the GPU to a container using the NVIDIA
Container Toolkit instructions for your distribution.

## Install the CLI

```console
git clone https://github.com/parsehawk/parsehawk.git
cd parsehawk
uv tool install --editable .
```

## Start and verify

```console
parsehawk start
parsehawk status
parsehawk doctor
```

The first run downloads the pinned vLLM image and model weights, then profiles
GPU memory. Wait for readiness before treating a slow first start as a failure.

The Web UI is available at `http://127.0.0.1:5173` and the API at
`http://127.0.0.1:8000`.

## Tune the runtime

The automatic profile favors reliable startup. Larger GPUs can opt into more
context or concurrency:

```console
PARSEHAWK_VLLM_MAX_MODEL_LEN=16384 \
PARSEHAWK_VLLM_MAX_NUM_SEQS=2 \
PARSEHAWK_VLLM_GPU_MEMORY_UTILIZATION=0.6 \
parsehawk restart
```

Change one dimension at a time and run a representative extraction after each
change. More context, concurrent sequences, and image pages all increase memory
pressure.
