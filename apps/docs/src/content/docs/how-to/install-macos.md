---
title: Install on macOS Apple Silicon
description: Run ParseHawk locally with Docker Desktop and the host-native vLLM Metal runtime.
sidebar:
  order: 1
---

On Apple Silicon, ParseHawk runs the API, worker, Web UI, and Phoenix in Docker.
The model server runs natively on the host through vLLM Metal so it can use the
Mac's GPU and unified memory.

## Requirements

- An Apple Silicon Mac
- 16 GB unified memory minimum; 32 GB or more for larger context windows
- [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Xcode Command Line Tools

ParseHawk is verified on M3 Pro machines with 18 GB and 36 GB unified memory.

## Install prerequisites

Install the Apple developer tools if they are not already present:

```console
xcode-select --install
```

Start Docker Desktop and wait until its engine is ready. Then confirm the
command-line prerequisites:

```console
docker info
uv --version
xcode-select -p
```

## Install the CLI

```console
git clone https://github.com/parsehawk/parsehawk.git
cd parsehawk
uv tool install --editable .
```

Reinstall after dependency or entry-point changes:

```console
uv tool install --editable . --force
```

## Start the stack

```console
parsehawk start
```

On the first run, ParseHawk provisions its pinned vLLM Metal environment under
`~/.parsehawk/runtimes/`, downloads the configured model, and warms the runtime.
This can take several minutes. Later starts reuse the environment and model
cache.

Verify all services:

```console
parsehawk status
parsehawk doctor
```

Then open `http://127.0.0.1:5173` or continue to
[your first extraction](/tutorials/first-extraction/).

## Tune for available memory

ParseHawk selects conservative runtime settings from the detected memory tier.
Override them only when you know the workload fits:

```console
PARSEHAWK_VLLM_MAX_MODEL_LEN=16384 parsehawk restart
```

If the runtime is killed or the machine becomes unresponsive, lower the context
length before changing other settings. See [deployment and hardware](/explanation/deployment-hardware/)
for the trade-offs.
