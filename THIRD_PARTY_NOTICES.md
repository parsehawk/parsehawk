# Third-Party Notices

ParseHawk source code is licensed under the Apache License, Version 2.0. See
[`LICENSE`](LICENSE).

Third-party software, container images, packages, fonts, and other components
referenced by this repository retain their own licenses. This file documents
the third-party components that ParseHawk intentionally bundles, builds from, or
installs through its package manifests and Dockerfiles.

## Bundled services and container images

### Arize Phoenix

ParseHawk can start a self-hosted Arize Phoenix tracing backend through the
`phoenix` Docker Compose profile. The wrapper image is defined in
[`services/phoenix/Dockerfile.phoenix`](services/phoenix/Dockerfile.phoenix) and
builds from the upstream `arizephoenix/phoenix` image.

- Project: <https://github.com/Arize-ai/phoenix>
- Image: `arizephoenix/phoenix`
- License: Elastic License 2.0
- License text: <https://github.com/Arize-ai/phoenix/blob/main/LICENSE>

Phoenix is not licensed under Apache-2.0. It is an optional third-party tracing
service that retains its upstream license. In particular, the Elastic License
2.0 restricts providing Phoenix itself to others as a hosted or managed service.

### Docker base images

ParseHawk Dockerfiles build from these upstream images:

| Image | Used by | Notes |
| --- | --- | --- |
| `python:3.12-slim` | `docker/Dockerfile.api` | Python runtime image. |
| `node:22-alpine` | `docker/Dockerfile.web` | Web build image. |
| `nginx:1.27-alpine` | `docker/Dockerfile.web` | Web runtime image. |
| `vllm/vllm-openai:v0.23.0` | `docker/runtime/Dockerfile.linux-vllm` | Default Linux vLLM OpenAI-compatible runtime image. |

These images and the operating-system packages inside them retain their own
upstream licenses and notices.

## Python packages

The API image installs Python dependencies from [`pyproject.toml`](pyproject.toml)
and [`uv.lock`](uv.lock). Direct runtime dependencies include:

| Package | License |
| --- | --- |
| `cryptography` | Apache-2.0 OR BSD-3-Clause |
| `fastapi` | MIT |
| `jsonschema` | MIT |
| `openai` | Apache-2.0 |
| `pillow` | MIT-CMU |
| `posthog` | MIT |
| `pydantic` | MIT |
| `pydantic-settings` | MIT |
| `pypdfium2` | BSD-3-Clause, Apache-2.0, and bundled dependency licenses |
| `python-multipart` | Apache-2.0 |
| `uvicorn` | BSD-3-Clause |

The optional `tracing` extra also installs:

| Package | License |
| --- | --- |
| `openinference-instrumentation-openai` | Apache-2.0 |
| `opentelemetry-exporter-otlp-proto-http` | Apache-2.0 |
| `opentelemetry-sdk` | Apache-2.0 |

Transitive Python dependencies are pinned in `uv.lock` and retain their own
licenses.

## Web packages and fonts

The web app installs Node dependencies from
[`apps/web/package.json`](apps/web/package.json) and [`pnpm-lock.yaml`](pnpm-lock.yaml).
Direct production dependencies include:

| Package | License |
| --- | --- |
| `@fontsource-variable/dm-sans` | OFL-1.1 |
| `@fontsource/dm-mono` | OFL-1.1 |
| `@tailwindcss/vite` | MIT |
| `@vitejs/plugin-react` | MIT |
| `class-variance-authority` | Apache-2.0 |
| `clsx` | MIT |
| `lucide-react` | ISC |
| `radix-ui` | MIT |
| `react` | MIT |
| `react-dom` | MIT |
| `shadcn` | MIT |
| `tailwind-merge` | MIT |
| `tailwindcss` | MIT |
| `tw-animate-css` | MIT |
| `typescript` | Apache-2.0 |
| `vite` | MIT |

The web dependency tree also includes development and transitive packages under
permissive, weak-copyleft, font, and content/data licenses such as 0BSD,
Apache-2.0, BlueOak-1.0.0, BSD-2-Clause, BSD-3-Clause, CC-BY-4.0, ISC, MIT,
MPL-2.0, OFL-1.1, and Python-2.0. The complete pinned dependency set is
recorded in `pnpm-lock.yaml`, and each package retains its own license.
