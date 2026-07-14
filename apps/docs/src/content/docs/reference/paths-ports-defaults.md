---
title: Paths, ports, and defaults
description: Filesystem locations, service bindings, input limits, and cross-cutting environment controls.
sidebar:
  order: 8
---

## Filesystem paths

| Purpose                                                | Default                            |
| ------------------------------------------------------ | ---------------------------------- |
| Persistent CLI configuration                           | `~/.parsehawk/config.json`         |
| Data directory in a source checkout                    | `./data`                           |
| Data directory for an installed CLI outside a checkout | `~/.parsehawk/data`                |
| SQLite database                                        | `<data-dir>/parsehawk.db`          |
| Uploaded files                                         | `<data-dir>/files/`                |
| Service logs                                           | `<data-dir>/logs/`                 |
| Local process/Compose state                            | `<data-dir>/parsehawk-state.json`  |
| Phoenix data                                           | `<data-dir>/phoenix/`              |
| Anonymous install identifier                           | `<data-dir>/telemetry-id`          |
| macOS vLLM Metal runtime                               | `~/.parsehawk/runtimes/vllm-metal` |
| Managed Linux vLLM environment                         | `~/.cache/parsehawk/vllm-venv`     |

Override persistent CLI configuration with `PARSEHAWK_CONFIG_PATH`. Set the data
location with `parsehawk config set data.dir PATH` or `PARSEHAWK_DATA_DIR` for
service processes.

## Host ports

| Service       | Host        | Port   | Start override                                     |
| ------------- | ----------- | ------ | -------------------------------------------------- |
| Web UI        | `127.0.0.1` | `5173` | `--web-host`, `--web-port`                         |
| REST API      | `127.0.0.1` | `8000` | `--host`, `--port`                                 |
| Phoenix       | `127.0.0.1` | `6006` | `PARSEHAWK_PHOENIX_HOST`, `PARSEHAWK_PHOENIX_PORT` |
| Model runtime | `127.0.0.1` | `8080` | `--runtime-port`                                   |

## Supported input files

| Kind       | Extensions              |
| ---------- | ----------------------- |
| PDF        | `.pdf`                  |
| Image      | `.jpg`, `.jpeg`, `.png` |
| Plain text | `.txt`                  |
| Markdown   | `.md`, `.markdown`      |

PDFs render at 170 DPI and accept at most 25 pages by default. Override with
`PARSEHAWK_PDF_RENDER_DPI` and `PARSEHAWK_PDF_MAX_PAGES`.

## Cross-cutting controls

| Environment variable                             | Purpose                               |
| ------------------------------------------------ | ------------------------------------- |
| `PARSEHAWK_SKIP_MIGRATIONS`                      | Skip automatic migrations at startup  |
| `PARSEHAWK_VLLM_IMAGE`                           | Override the Linux runtime image      |
| `PARSEHAWK_VLLM_CACHE_HOME`                      | Override the Linux vLLM host cache    |
| `PARSEHAWK_TELEMETRY_DISABLED` or `DO_NOT_TRACK` | Disable anonymous product telemetry   |
| `OTEL_SDK_DISABLED`                              | Disable trace export                  |
| `OTEL_EXPORTER_OTLP_ENDPOINT`                    | External OTLP/HTTP collector base URL |
| `OTEL_EXPORTER_OTLP_HEADERS`                     | Encoded OTLP authentication headers   |

The [generated configuration reference](/reference/configuration/) lists the
typed service settings and persistent CLI keys directly from source metadata.
