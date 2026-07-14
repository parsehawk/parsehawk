---
title: Deployment and hardware
description: Why the macOS and Linux runtime topologies differ and how memory settings interact.
sidebar:
  order: 7
---

ParseHawk presents one local product surface on both supported platforms, but
the model runtime topology follows the available GPU stack.

## macOS Apple Silicon

The API, worker, Web UI, and Phoenix run in Linux containers. vLLM Metal runs on
the macOS host, where it can access Metal and unified memory. Containers reach
it through `host.docker.internal`.

Unified memory is shared by the operating system, applications, model weights,
KV cache, and intermediate tensors. A configuration that nominally fits can
still create system-wide pressure.

## Linux NVIDIA

The model runtime joins the Docker Compose network as the `runtime` service and
uses the NVIDIA Container Toolkit. API and worker reach it by service name;
port 8080 is also published on host loopback for diagnostics.

GPU VRAM is separate from host RAM. Model weights, KV cache, and concurrent
sequences must fit in VRAM even when the server has abundant system memory.

## The three main memory levers

| Setting                                 | Effect                                                                          |
| --------------------------------------- | ------------------------------------------------------------------------------- |
| `PARSEHAWK_VLLM_MAX_MODEL_LEN`          | Maximum context; larger values reserve more KV-cache capacity                   |
| `PARSEHAWK_VLLM_MAX_NUM_SEQS`           | Concurrent decoding; higher values improve throughput but multiply active state |
| `PARSEHAWK_VLLM_GPU_MEMORY_UTILIZATION` | Fraction available to vLLM on NVIDIA; leaving headroom improves stability       |

PDF page count and render DPI also affect multimodal input size. ParseHawk
defaults to 25 pages at 170 DPI.

Automatic platform profiles favor reliable startup over maximum throughput.
Tune one variable at a time with representative documents.

## Network exposure

Default host bindings use `127.0.0.1`. The developer-preview API currently has
no application authentication, so do not expose it directly to an untrusted
network. Put deliberate network controls and an authenticated reverse proxy in
front of any shared deployment.

## Persistence and scale

The default architecture uses SQLite and a shared local file directory. It is a
good fit for a single host and local team workflows, not an implicit
multi-machine control plane. API and worker need consistent access to the same
database, files, and encryption-key source.
