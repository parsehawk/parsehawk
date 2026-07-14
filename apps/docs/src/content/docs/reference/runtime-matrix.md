---
title: Runtime matrix
description: Supported host platforms, service topology, hardware guidance, and runtime defaults.
sidebar:
  order: 6
---

## Supported bundled-runtime platforms

| Host                 | Architecture            | Accelerator            | Runtime location                 | Status             |
| -------------------- | ----------------------- | ---------------------- | -------------------------------- | ------------------ |
| macOS                | Apple Silicon (`arm64`) | Metal / unified memory | Host-native vLLM Metal           | Supported          |
| Linux                | x86_64                  | NVIDIA CUDA            | Docker Compose `runtime` service | Supported          |
| Windows              | —                       | —                      | —                                | Not supported      |
| macOS Intel          | `x86_64`                | —                      | —                                | Not supported      |
| Linux without NVIDIA | x86_64                  | CPU or other GPU       | External provider only           | No bundled runtime |

The API stack can still use a separately operated provider when the bundled
runtime is unavailable. Start with `parsehawk start -x runtime`.

## Verified and recommended hardware

| Platform | Verified                                   | Recommended minimum  |
| -------- | ------------------------------------------ | -------------------- |
| macOS    | M3 Pro with 18 GB and 36 GB unified memory | 16 GB unified memory |
| Linux    | NVIDIA L4 with 24 GB VRAM                  | 16 GB VRAM           |

32 GB unified memory or 24 GB VRAM gives more room for larger contexts.

## Default model and limits

| Setting                   | Default                                     |
| ------------------------- | ------------------------------------------- |
| Model                     | `numind/NuExtract3-W4A16`                   |
| Maximum generated tokens  | `2048`                                      |
| Base maximum model length | `8192` before platform-profile adjustment   |
| Base maximum sequences    | `1` before platform-profile adjustment      |
| Linux vLLM package/image  | `vllm==0.23.0` / `vllm/vllm-openai:v0.23.0` |
| PDF pages                 | `25`                                        |
| PDF render DPI            | `170`                                       |
| Model request timeout     | `600` seconds                               |

ParseHawk applies platform- and memory-tier runtime profiles at startup. The
effective values can therefore differ from the base settings. Run:

```console
parsehawk runtime info --json
parsehawk config list --json
```

## Default addresses

| Surface       | Host address               |
| ------------- | -------------------------- |
| Web UI        | `http://127.0.0.1:5173`    |
| REST API      | `http://127.0.0.1:8000`    |
| Phoenix       | `http://127.0.0.1:6006`    |
| Model runtime | `http://127.0.0.1:8080/v1` |
