---
title: Choose an installation path
description: Pick the supported ParseHawk setup for your hardware and model provider.
sidebar:
  order: 1
---

ParseHawk has two supported bundled-runtime paths. Both expose the same Web UI,
CLI, and REST API.

| Host                     | Bundled model runtime  | Recommended hardware                                            | Setup guide                                       |
| ------------------------ | ---------------------- | --------------------------------------------------------------- | ------------------------------------------------- |
| macOS on Apple Silicon   | vLLM Metal on the host | 16 GB unified memory minimum; 32 GB or more for larger contexts | [Install on macOS](/how-to/install-macos/)        |
| Linux x86_64 or ARM64 with NVIDIA | vLLM in Docker Compose | 16 GB VRAM minimum; 24 GB or more for larger contexts           | [Install on Linux](/how-to/install-linux-nvidia/) |

Windows and Intel Macs are not currently supported for the bundled runtime.

## Use another model server

You can run the ParseHawk API, worker, and Web UI without launching the bundled
runtime:

```console
parsehawk start -x runtime
```

Then point the `openai_compatible_api` provider at Ollama, LM Studio, a separate
vLLM server, or another compatible endpoint. You can also configure OpenAI or
Microsoft Foundry. See [model providers](/how-to/providers/) for the exact setup.

## What starts locally

A default `parsehawk start` exposes four services on loopback:

| Service       | Address                 | Purpose                                        |
| ------------- | ----------------------- | ---------------------------------------------- |
| Web UI        | `http://127.0.0.1:5173` | Human workflow for files, extractors, and jobs |
| REST API      | `http://127.0.0.1:8000` | Data plane used by the UI and CLI              |
| Phoenix       | `http://127.0.0.1:6006` | Local model-call tracing                       |
| Model runtime | `http://127.0.0.1:8080` | Bundled OpenAI-compatible inference server     |

Run `parsehawk doctor` after installation to check the host prerequisites and
service health.

## Next step

Once the stack is healthy, continue to [your first extraction](/tutorials/first-extraction/).
