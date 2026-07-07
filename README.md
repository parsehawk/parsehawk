# ParseHawk

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/parsehawk/parsehawk/main/apps/web/src/assets/logo.svg">
    <img src="https://raw.githubusercontent.com/parsehawk/parsehawk/main/apps/web/src/assets/logo-dark.svg" alt="ParseHawk" width="420">
  </picture>
</p>

<p align="center">
  <strong>Turn documents into structured JSON with local-first document AI.</strong>
  <br>
  <strong>Run 100% locally by default, with API, CLI, and Web UI.</strong>
</p>

<p align="center">
  <a href="https://github.com/parsehawk/parsehawk/releases"><img src="https://img.shields.io/github/v/release/parsehawk/parsehawk?sort=semver" alt="Latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="License: Apache 2.0"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg" alt="Python 3.11 | 3.12"></a>
  <img src="https://img.shields.io/badge/platform-macOS%20%C2%B7%20Linux-lightgrey.svg" alt="Platform: macOS · Linux">
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Linted with Ruff"></a>
  <a href="https://github.com/parsehawk/parsehawk/stargazers"><img src="https://img.shields.io/github/stars/parsehawk/parsehawk?style=social" alt="GitHub stars"></a>
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> ·
  <a href="#first-extraction">First extraction</a> ·
  <a href="#api-cli-and-web-ui">API, CLI, and Web UI</a> ·
  <a href="#requirements">Requirements</a> ·
  <a href="#contributing">Contributing</a>
</p>

ParseHawk turns PDFs, scans, images, text files, and Markdown into structured
JSON without sending sensitive documents to a third-party AI API. It is built
for developers and teams working with private data: invoices, receipts,
contracts, internal documents, customer files, medical or financial records, and
other unstructured inputs that should stay under your control.

The default setup runs fully locally. ParseHawk uses vLLM on Linux NVIDIA
machines and vLLM Metal on macOS Apple Silicon, so you can run practical
document extraction on a server or even on your MacBook. You can drive the same
workflow from the browser, from `curl`, or from the `parsehawk` CLI.

<p align="center">
  <img src="docs/assets/parsehawk-demo.svg" alt="ParseHawk turns a document into validated structured JSON, 100% locally" width="820">
</p>

## What You Get

- Extract structured JSON from unstructured PDFs, scans, images, text, and Markdown
- Define your own schemas for the data you want back
- Run zero-shot extraction with only instructions and a schema
- Add few-shot examples when a document type needs more guidance
- Improve extraction quality without training a model
- Improve extractors over time with better instructions, schemas, and examples
- Get validated JSON output using JSON Schema Draft 2020-12
- Keep files, jobs, extractors, and results local by default
- Use the Web UI for humans and the REST API or CLI for scripts, services, and agents
- Control both the local stack and the extraction API from one `parsehawk` CLI
- Run on Linux with vLLM or on macOS Apple Silicon with vLLM Metal

## Requirements

ParseHawk runs on macOS Apple Silicon and Linux x86_64 with an NVIDIA GPU.
Windows is not supported yet.

<details>
<summary>macOS Apple Silicon details</summary>

Required:

- `uv`
- Docker Desktop
- Xcode Command Line Tools
- Apple Silicon Mac with enough unified memory for NuExtract3-W4A16

Verified:

- MacBook Pro M3 Pro with 18 GB unified memory
- MacBook Pro M3 Pro with 36 GB unified memory

Recommended:

- 16 GB unified memory minimum for the default local workflow
- 32 GB or more for larger context lengths

</details>

<details>
<summary>Linux NVIDIA details</summary>

Required:

- `uv`
- Docker Engine
- Docker Compose
- NVIDIA driver
- NVIDIA Container Toolkit
- NVIDIA GPU with enough VRAM for NuExtract3-W4A16

Verified:

- NVIDIA L4 with 24 GB VRAM

Recommended:

- 16 GB VRAM minimum for the default local workflow
- 24 GB VRAM or more for larger context lengths

</details>

## Quickstart

Run ParseHawk from a Git checkout with
[`uv`](https://docs.astral.sh/uv/getting-started/installation/) and install the
CLI as an editable local tool:

```bash
git clone https://github.com/parsehawk/parsehawk.git
cd parsehawk
uv tool install --editable .
parsehawk start
```

Then open:

- Web UI: [http://127.0.0.1:5173](http://127.0.0.1:5173)
- API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- OpenAPI JSON: [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)

Stop ParseHawk:

```bash
parsehawk stop
```

Check your local setup:

```bash
parsehawk doctor
```

## Database Migrations

The SQLite schema is managed by ordered, tracked migrations. `parsehawk start`
applies any pending migrations automatically before serving, so upgrades converge
without manual steps.

```bash
# Show applied and pending migrations
parsehawk migrate status

# Apply pending migrations manually
parsehawk migrate
```

To take ownership of when migrations run, opt out of the automatic apply at start
with `parsehawk start -x migrate` or `PARSEHAWK_SKIP_MIGRATIONS=1`, then run
`parsehawk migrate` yourself.

## First Extraction

The easiest first run is image-to-JSON extraction with the bundled receipt image
and the seeded prebuilt `Receipt` extractor. Its stable API name is `receipt`.

### Option A: Web UI

1. Start ParseHawk with `parsehawk start`.
2. Open [http://127.0.0.1:5173](http://127.0.0.1:5173).
3. Upload [`tests/fixtures/receipt/receipt.jpg`](tests/fixtures/receipt/receipt.jpg).
4. Select the prebuilt `Receipt` extractor.
5. Select the uploaded file and click **Run extraction**.
6. Inspect the extracted fields and JSON result.

Expected fields include:

```json
{
  "merchant_name": "PARSEHAWK COFFEE",
  "receipt_id": "R-1001",
  "date": "2026-06-21",
  "total": 11.22,
  "currency": "EUR"
}
```

### Option B: CLI

```bash
parsehawk files upload tests/fixtures/receipt/receipt.jpg
parsehawk extract \
  tests/fixtures/receipt/receipt.jpg \
  --extractor receipt \
  --wait
```

### Option C: API

```bash
API=http://127.0.0.1:8000

FILE_ID=$(
  curl -s -X POST "$API/v1/files" \
    -F "upload=@tests/fixtures/receipt/receipt.jpg;type=image/jpeg" |
    jq -r '.id'
)

JOB_ID=$(
  curl -s -X POST "$API/v1/jobs" \
    -H "Content-Type: application/json" \
    -d "{\"extractor_name\":\"receipt\",\"file_id\":\"$FILE_ID\"}" |
    jq -r '.id'
)

curl -s "$API/v1/jobs/$JOB_ID" | jq .
```

Jobs are asynchronous. Poll `GET /v1/jobs/{job_id}` until `status` is terminal:
`completed`, `failed`, or `canceled`. In-progress jobs can be `queued`,
`running`, `canceling`, or `deleting`.

## API, CLI, And Web UI

ParseHawk exposes one local API. The CLI and Web UI are clients of that API.
The CLI has two jobs: it controls the local ParseHawk stack (`start`, `stop`,
`status`, `doctor`, `restart`) and it works with the data plane (`files`,
`extractors`, `schemas`, `jobs`, and one-shot `extract`).

![ParseHawk Web UI](docs/assets/parsehawk-web-ui.png)

Core resources:

```text
POST   /v1/files
GET    /v1/files
GET    /v1/files/{file_id}
GET    /v1/files/{file_id}/content
DELETE /v1/files/{file_id}

POST   /v1/schemas/validate

POST   /v1/extractors
GET    /v1/extractors
GET    /v1/extractors/{extractor_ref}
PATCH  /v1/extractors/{extractor_ref}
PUT    /v1/extractors/{extractor_ref}
DELETE /v1/extractors/{extractor_ref}

POST   /v1/jobs
GET    /v1/jobs
GET    /v1/jobs/{job_id}
POST   /v1/jobs/{job_id}/cancel
DELETE /v1/jobs/{job_id}
```

Jobs return the canonical extracted JSON inline as `job.result.data` once
completed.

Canceling a queued job marks it `canceled`; canceling a running job marks it
`canceling` until the worker stops the extraction. Deleting a queued or terminal
job removes it immediately with `204 No Content`. Deleting a running or
canceling job returns `202 Accepted`, marks it `deleting`, and removes it after
the worker observes the cancellation request.

Useful CLI commands:

```bash
parsehawk files upload document.pdf
parsehawk files list
parsehawk schemas validate schema.json
parsehawk extractors create --name invoice_v1 --display-name "Invoice Extractor" --schema schema.json --instructions "Extract invoice fields."
parsehawk extractors put invoice_v1 --display-name "Invoice Extractor" --schema schema.json --instructions "Extract invoice fields."
parsehawk jobs create --extractor receipt --file-id file_...
parsehawk jobs get job_...
parsehawk extract document.pdf --schema schema.json --instructions "Extract invoice fields." --wait
```

Public IDs are TypeID-style strings with resource prefixes such as `file_...`,
`extractor_...`, and `job_...`.

Extractor `id` is the server-generated canonical ID. Extractor `name` is a
user-controlled API-safe identifier, such as `receipt` or `invoice_v1`; it uses
lowercase ASCII letters, digits, hyphen, and underscore, cannot start with the
reserved `extractor_` prefix, and is immutable after creation through normal
update flows. `display_name` is the editable label shown to people. Use
`PUT /v1/extractors/{name}` or `parsehawk extractors put <name>` to sync a full
extractor definition idempotently from external config or CI. In ParseHawk
Cloud, names are intended to be unique per organization/workspace resolved from
the bearer API key, not globally.

## Extractors And Schemas

An extractor combines:

- an immutable stable `name` for API and CLI references, unique in the local workspace
- a mutable `display_name` for human-facing UI text
- natural-language instructions
- JSON Schema Draft 2020-12
- optional few-shot examples
- optional thinking mode

![ParseHawk schema builder](docs/assets/parsehawk-schema-builder.png)

A minimal extractor schema:

```json
{
  "type": "object",
  "properties": {
    "invoice_number": {
      "type": ["string", "null"],
      "description": "The invoice number exactly as shown on the document."
    },
    "total_amount": {
      "type": ["number", "null"],
      "description": "The final total amount to pay."
    }
  },
  "required": ["invoice_number", "total_amount"],
  "additionalProperties": false
}
```

Few-shot examples can use inline text or uploaded files:

```json
{
  "name": "invoice_v1",
  "display_name": "Invoice Extractor",
  "instructions": "Extract the invoice fields exactly.",
  "schema": {
    "type": "object",
    "properties": {
      "invoice_number": { "type": ["string", "null"] }
    },
    "required": ["invoice_number"],
    "additionalProperties": false
  },
  "examples": [
    {
      "input": { "type": "text", "text": "Invoice #A-123" },
      "output": { "invoice_number": "A-123" }
    },
    {
      "input": { "type": "file", "file_id": "file_..." },
      "output": { "invoice_number": "B-456" }
    }
  ]
}
```

ParseHawk validates model output against the schema and stores the canonical
result under `job.result.data`.

The schema dialect is documented in
[`docs/schemas/parsehawk-extraction-schema.schema.json`](docs/schemas/parsehawk-extraction-schema.schema.json).
It supports JSON Schema plus optional `x-parsehawk.semantic` metadata for
NuExtract3-oriented scalar hints.

## Runtime Defaults

The default model is:

```text
numind/NuExtract3-W4A16
```

ParseHawk talks to the runtime through an OpenAI-compatible API. On macOS, the
runtime runs on the host through vLLM Metal because Metal acceleration is not
available inside a normal Linux container. On Linux, the runtime runs as part
of Docker Compose.

Current defaults:

| Setting | Default |
| --- | --- |
| vLLM package | `vllm==0.23.0` |
| Linux runtime image | `vllm/vllm-openai:v0.23.0` |
| Model | `numind/NuExtract3-W4A16` |
| GPU memory utilization | platform- and memory-tier specific |
| Max model length | platform- and memory-tier specific |
| Max concurrent sequences | platform- and memory-tier specific |
| PDF render DPI | `170` |
| PDF max pages | `25` |

For known bundled models, ParseHawk chooses conservative runtime defaults from
the detected platform and memory tier. Apple Silicon uses unified memory; Linux
uses NVIDIA GPU VRAM. These defaults favor reliable local startup over maximum
throughput. Increase the context length, memory utilization, or concurrent
sequence limit manually if you are running on a larger machine.

Common overrides:

```bash
PARSEHAWK_VLLM_MAX_MODEL_LEN=16384 parsehawk start
PARSEHAWK_VLLM_GPU_MEMORY_UTILIZATION=0.6 parsehawk start
PARSEHAWK_VLLM_MAX_NUM_SEQS=4 parsehawk start
PARSEHAWK_VLLM_MODEL=numind/NuExtract3-W4A16 parsehawk start
PARSEHAWK_VLLM_IMAGE=vllm/vllm-openai:v0.23.0 parsehawk start
```

## Model Providers

By default ParseHawk extracts with **NuExtract3** on the bundled runtime. Each
extractor also carries a `provider` and a `model`, so you can point individual
extractors at any OpenAI-API-compatible endpoint — cloud or local.

Three providers ship preconfigured. You configure them; you cannot create or
delete them.

| Provider (`provider_name`) | Base URL | Notes |
| --- | --- | --- |
| `openai_compatible_api` | bundled runtime `http://127.0.0.1:8080/v1` | **Default.** Serves NuExtract3; also point it at Ollama, LM Studio, or your own vLLM. |
| `openai` | `https://api.openai.com/v1` | Configure an API key to use OpenAI models. |
| `azure_openai` | your Azure endpoint | Set `base_url` to your Azure OpenAI **v1** endpoint; `model` is the deployment name. |

Configure a provider and target it from an extractor (the API key is encrypted
at rest and never returned by the API):

```bash
# Use OpenAI for one extractor:
parsehawk providers configure openai --api-key "$OPENAI_API_KEY"
parsehawk extractors update invoice_v1 --provider openai --model gpt-4o-mini

# ...or import the key from an environment variable:
parsehawk providers configure openai --api-key-env OPENAI_API_KEY

# Inspect providers and the models they offer:
parsehawk providers list
parsehawk providers models openai
```

Only NuExtract3's exact model variants use its fine-tuned chat template. Every
other model receives a standard chat request that embeds NuExtract3's semantic
type reference in the system prompt, with JSON-Schema-constrained decoding.

Provider API keys are encrypted at rest with a master key taken from
`PARSEHAWK_SECRET_KEY` when set, otherwise a `0600` key file generated in the
data directory on first run. The same source must be visible to both the API and
worker processes; losing it means re-entering provider keys.

To run against a configured cloud (or your own local) provider without launching
the bundled runtime:

```bash
parsehawk start -x runtime
```

## Configuration

ParseHawk uses Pydantic settings. Common environment variables:

| Environment variable | Default | Description |
| --- | --- | --- |
| `PARSEHAWK_DATA_DIR` | `data` | Local storage directory for SQLite, uploaded files, logs, and local state. |
| `PARSEHAWK_DATABASE_PATH` | `data/parsehawk.db` | SQLite database path. |
| `PARSEHAWK_SKIP_MIGRATIONS` | `false` | When truthy, skip automatically applying database migrations at start; apply them manually with `parsehawk migrate`. |
| `PARSEHAWK_LOG_LEVEL` | `INFO` | Log level for API, worker, runtime, and Web UI logs. |
| `PARSEHAWK_LOG_MODEL_IO` | `false` | When `true` and `PARSEHAWK_LOG_LEVEL=DEBUG`, log model-runtime request and response JSON from the API/worker process. Image data URLs are redacted. |
| `PARSEHAWK_SECRET_KEY` | generated | Master key used to encrypt provider API keys. When unset, a `0600` key file is generated in the data directory on first run. Set the same value for the API and worker in multi-host deployments. |
| `PARSEHAWK_VLLM_BASE_URL` | `http://127.0.0.1:8080/v1` | Base URL the bundled `openai_compatible_api` provider is seeded with. |
| `PARSEHAWK_VLLM_MODEL` | `numind/NuExtract3-W4A16` | Default model new extractors use, served by the bundled runtime. |
| `PARSEHAWK_VLLM_MAX_MODEL_LEN` | platform-specific | vLLM context length. Overrides the automatic runtime-profile default. |
| `PARSEHAWK_VLLM_MAX_NUM_SEQS` | platform-specific | vLLM maximum concurrent decode sequences. Overrides the automatic runtime-profile default. |
| `PARSEHAWK_VLLM_GPU_MEMORY_UTILIZATION` | platform-specific | vLLM memory reservation fraction. On Apple Silicon this is also mapped to `VLLM_METAL_MEMORY_FRACTION`. |
| `PARSEHAWK_VLLM_IMAGE` | `vllm/vllm-openai:v0.23.0` | Linux Docker runtime image. |
| `PARSEHAWK_VLLM_CACHE_HOME` | `~/.cache/vllm` | Linux host cache for vLLM compile artifacts. |
| `PARSEHAWK_PDF_MAX_PAGES` | `25` | Maximum PDF pages rendered for one extraction. |
| `PARSEHAWK_PDF_RENDER_DPI` | `170` | PDF page image render DPI. |
| `PARSEHAWK_TELEMETRY_DISABLED` | `false` | When truthy, disables anonymous usage analytics. |

CLI config:

```bash
parsehawk config list
parsehawk config set log.level DEBUG
parsehawk restart
```

## Telemetry

ParseHawk collects **anonymous usage analytics**. Two events are sent to
[PostHog](https://posthog.com):

- `install` — once per install, the first time you start ParseHawk.
- `run_started` — each time a user starts an extraction run.

Each event carries only coarse, non-identifying data:

- a random per-install id stored in `data/telemetry-id`
- the input type (`file` or `text`, on runs)
- the ParseHawk version and your operating system name
- an approximate location (country/region)

ParseHawk never sends file contents, file names, extractor instructions,
schemas, or extracted data, and it never creates a personal profile from the
per-install id. The first time you run `parsehawk start` or `parsehawk dev`, you
will see a notice describing this.

To opt out, set either of these before starting ParseHawk:

```bash
export PARSEHAWK_TELEMETRY_DISABLED=1
export DO_NOT_TRACK=1
```

When ParseHawk runs in Docker, these variables are passed through to the API and
worker containers automatically.

Maintainers can tag internal usage instead of dropping it:

```bash
export PARSEHAWK_TELEMETRY_INTERNAL=1
```

## Tracing

ParseHawk traces every LM request (prompts, outputs, latency, token usage) and
ships with a bundled, self-hosted [Arize Phoenix](https://arize.com/docs/phoenix)
backend to view them. `parsehawk start` starts Phoenix alongside the other
services; open the UI at `http://127.0.0.1:6006`. Traces stay on your machine:
they are stored in Phoenix's own SQLite database under `data/phoenix/` and
survive restarts.

To start without the bundled Phoenix (this also turns tracing off):

```bash
parsehawk start -x phoenix
```

The API and worker are tracing-backend agnostic: all LM requests go through the
OpenAI SDK, instrumented with [OpenInference](https://github.com/Arize-ai/openinference)
and exported over standard OTLP. Point them at any OTLP collector instead of the
bundled Phoenix with the standard OpenTelemetry variables:

| Environment variable | Default | Description |
| --- | --- | --- |
| `OTEL_SDK_DISABLED` | `false` | Master switch for tracing. `parsehawk start -x phoenix` sets it to `true` unless you set it yourself. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://phoenix:6006` | OTLP/HTTP collector **base URL** — the exporter appends `/v1/traces` itself. If the collector URL you were handed already ends in `/v1/traces`, strip that suffix. |
| `OTEL_EXPORTER_OTLP_HEADERS` | unset | Optional headers, e.g. `authorization=Bearer <api key>` for an auth-enabled collector. Values are URL-encoded per the OTLP spec (space → `%20`). |
| `OTEL_SERVICE_NAME` | `parsehawk-api` / `parsehawk-worker` | Service name on exported spans. |
| `OTEL_RESOURCE_ATTRIBUTES` | `openinference.project.name=parsehawk` | Extra resource attributes. `openinference.project.name` sets the Phoenix project traces are grouped under (an OpenInference convention — other backends ignore it and group by service name). |

Bring-your-own collector example:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=https://collector.example.com  # base URL, no /v1/traces
export OTEL_EXPORTER_OTLP_HEADERS="authorization=Bearer%20my-key"
export OTEL_SDK_DISABLED=false
parsehawk start -x phoenix
```

### Configuring the bundled Phoenix

The Phoenix container itself is configured with its native `PHOENIX_*` variables,
which pass through to the service (see the
[Phoenix configuration docs](https://arize.com/docs/phoenix/self-hosting/configuration)):

| Environment variable | Default | Description |
| --- | --- | --- |
| `PARSEHAWK_PHOENIX_VERSION` | `latest` | Phoenix image tag. |
| `PARSEHAWK_PHOENIX_HOST` / `PARSEHAWK_PHOENIX_PORT` | `127.0.0.1` / `6006` | Host binding for the Phoenix UI/collector. |
| `PHOENIX_SQL_DATABASE_URL` | SQLite under `data/phoenix/` | Trace storage. Set a `postgresql://` URL to use an external Postgres. |
| `PHOENIX_DEFAULT_RETENTION_POLICY_DAYS` | `0` (keep forever) | Auto-delete traces older than this many days. |
| `PHOENIX_ENABLE_AUTH` + `PHOENIX_SECRET` | `false` / unset | Enable Phoenix authentication (`PHOENIX_SECRET` must be 32+ characters). |

To enable authentication end to end: set `PHOENIX_ENABLE_AUTH=true` and a
`PHOENIX_SECRET`, restart, create an API key in the Phoenix UI (Settings), and
hand it to the API/worker via
`OTEL_EXPORTER_OTLP_HEADERS="authorization=Bearer <api key>"`.

For the long tail (OAuth2/LDAP, token expiry, admin accounts, …) drop a
`phoenix.env` file next to `docker/docker-compose.yml` (or point
`PARSEHAWK_PHOENIX_ENV_FILE` at one); it is loaded into the Phoenix container
when present.

## Local Data

By default ParseHawk stores local state under `data/`:

```text
data/
  parsehawk.db
  files/
  logs/
  parsehawk-state.json
  phoenix/
  telemetry-id
```

Stop ParseHawk before deleting `data/`:

```bash
parsehawk stop
rm -rf data
parsehawk start
```

If `data/` is deleted while ParseHawk is still running, old processes can keep
serving from already-open SQLite handles. `parsehawk start` refuses to start
when target ports are already occupied without a live state file. In that case,
stop the process using the port and start again.

## Contributing

ParseHawk welcomes issues and pull requests. For local development setup,
quality checks, pull request expectations, coverage requirements, and licensing
terms, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Troubleshooting

Start with the built-in health checks:

Check status:

```bash
parsehawk status
```

Read logs:

```bash
ls data/logs
tail -f data/logs/api.log
tail -f data/logs/worker.log
tail -f data/logs/runtime.log
```

Restart:

```bash
parsehawk restart
```

If Docker or the runtime gets into a strange state, stop ParseHawk before
removing local data:

```bash
parsehawk stop
rm -rf data
parsehawk start
```

If the Model Runtime is slow to become ready, give it a few minutes on first
startup while vLLM loads model weights, profiles memory, and warms kernels.

## Credits

ParseHawk stands on excellent open-source projects, including:

- [FastAPI](https://github.com/fastapi/fastapi) for the API framework and OpenAPI docs
- [vLLM](https://github.com/vllm-project/vllm) and [vLLM Metal](https://github.com/vllm-project/vllm-metal) for local model serving
- [NuExtract3](https://huggingface.co/numind/NuExtract3-W4A16) for the default extraction model
- [Pydantic](https://github.com/pydantic/pydantic), [Ruff](https://github.com/astral-sh/ruff), and [uv](https://github.com/astral-sh/uv) for the Python toolchain
- [React](https://github.com/facebook/react), [Vite](https://github.com/vitejs/vite), and [Tailwind CSS](https://github.com/tailwindlabs/tailwindcss) for the Web UI

## Roadmap

Near-term focus:

- make the macOS and Linux runtime paths boringly reliable
- publish an installable CLI package
- improve the Web UI schema builder
- add stronger end-to-end runtime smoke tests
- document deployment options for VPS and container platforms

Later:

- Python SDK
- PostgreSQL support
- batch extraction
- review/correction workflows
- eval tooling

## Enterprise

ParseHawk is developed by Totoy GmbH in Vienna, Austria. If you are interested
in an enterprise deployment, private-cloud setup, or managed infrastructure for
sensitive document workflows, contact [support@totoy.ai](mailto:support@totoy.ai).

## Versioning

ParseHawk follows SemVer.

Until `v1.0.0`, ParseHawk is in developer preview. Breaking changes may happen
in any minor release, for example from `v0.1.0` to `v0.2.0`.

Patch releases, such as `v0.1.1`, are intended to be backward-compatible bug
fixes for that minor line.

We will move to `v1.0.0` once the core CLI commands, the REST API, and the
config file format are stable enough for users to rely on.

## License

ParseHawk is open source under the Apache-2.0 license. See [`LICENSE`](LICENSE).

Third-party dependencies retain their own licenses.
