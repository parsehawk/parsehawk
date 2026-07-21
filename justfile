set dotenv-load := true

export PARSEHAWK_DATA_DIR := env_var_or_default("PARSEHAWK_DATA_DIR", "data")
export PARSEHAWK_DATABASE_PATH := env_var_or_default("PARSEHAWK_DATABASE_PATH", "data/parsehawk.db")

default:
    @just --list

check-prereqs:
    @scripts/check-dev-prereqs.sh

check-runtime-prereqs:
    @scripts/check-dev-prereqs.sh --runtime

setup: check-prereqs
    uv sync --all-extras
    pnpm install
    uv run pre-commit install

start: check-runtime-prereqs
    uv run parsehawk start

dev: check-runtime-prereqs
    uv run parsehawk dev --reload

worker:
    uv run parsehawk-worker

test:
    uv run pytest

test-unit:
    uv run pytest tests/unit

test-concurrency:
    uv run pytest --no-cov -m concurrency

e2e:
    uv run pytest --no-cov -m e2e tests/e2e

format:
    uv run ruff format src tests openapi scripts

format-check:
    uv run ruff format --check src tests openapi scripts

lint:
    uv run ruff check src tests openapi scripts

typecheck:
    uv run ty check src tests openapi scripts

openapi-export:
    uv run python openapi/export_openapi.py

openapi-check-sync:
    uv run python openapi/export_openapi.py --check

openapi-validate:
    uv run python openapi/validate_openapi.py

openapi-lint:
    scripts/speakeasy_lint.sh

openapi-check: openapi-check-sync openapi-validate openapi-lint

references-export:
    uv run python scripts/export_reference_docs.py

references-check:
    uv run python scripts/export_reference_docs.py --check

docs-dev:
    pnpm --dir apps/docs dev

docs-format:
    pnpm --dir apps/docs format

docs-format-check:
    pnpm --dir apps/docs format:check

docs-typecheck:
    pnpm --dir apps/docs typecheck

docs-build:
    pnpm --dir apps/docs build

docs-artifacts-check: docs-build
    cmp openapi/openapi.yaml apps/docs/dist/openapi.yaml
    cmp docs/schemas/parsehawk-extraction-schema.schema.json apps/docs/dist/schemas/parsehawk-extraction-schema.schema.json
    test -f apps/docs/dist/reference/api/index.html
    test -f apps/docs/dist/reference/api/operations/uploadfile/index.html
    test -f apps/docs/dist/reference/api/operations/downloadfilecontent/index.html
    grep -q '<table' apps/docs/dist/how-to/providers/index.html
    test -f apps/docs/dist/pagefind/pagefind.js
    test -f apps/docs/dist/llms.txt
    test -f apps/docs/dist/404.html

docs-check: openapi-check-sync references-check docs-format-check docs-typecheck docs-artifacts-check

web-dev:
    pnpm --dir apps/web dev

web-build:
    CI=true pnpm --dir apps/web build

web-test:
    CI=true pnpm --dir apps/web test

web-typecheck:
    CI=true pnpm --dir apps/web typecheck

check: format-check lint typecheck test openapi-check references-check docs-format-check docs-typecheck docs-artifacts-check web-typecheck web-test web-build licenses

# Permissive SPDX ids osv-scanner treats as always-allowed, so it only surfaces the
# licenses worth adjudicating. The real block/flag/allow decision is made by
# scripts/check_dep_licenses.py, so this list only needs to be safe, not exhaustive.
license_allow := "MIT,Apache-2.0,BSD-2-Clause,BSD-3-Clause,ISC,MPL-2.0,0BSD,Python-2.0,PSF-2.0,Unlicense,CC0-1.0,BlueOak-1.0.0,OFL-1.1,Zlib,BSL-1.0,MIT-0,CC-BY-4.0"

# License compliance (issue #92): Apache-2.0 shipping surface. Runs both halves.
licenses: licenses-deps licenses-manifest

# Dependency licenses: osv-scanner reads both uv.lock and pnpm-lock.yaml in one pass
# (licenses via deps.dev) and feeds one policy in scripts/check_dep_licenses.py.
# Needs osv-scanner on PATH and network (deps.dev). Locally it degrades to a
# skip-with-warning when osv-scanner is absent, so `just check` and pre-commit stay
# green for contributors without it; CI installs osv-scanner and is the authority.
licenses-deps:
    #!/usr/bin/env bash
    set -eu
    if ! command -v osv-scanner >/dev/null 2>&1; then
        echo "⚠ osv-scanner not found — skipping dependency license scan (CI runs it)." >&2
        echo "  install: https://google.github.io/osv-scanner/installation/" >&2
        exit 0
    fi
    osv-scanner scan source --format json --licenses="{{license_allow}}" --lockfile uv.lock --lockfile pnpm-lock.yaml | uv run python scripts/check_dep_licenses.py --source osv

# Bundled-image manifest guard: fails on any Dockerfile FROM or Compose image: ref
# missing from the reviewed manifest (e.g. the ELv2 Phoenix image), which no
# dependency scanner sees. Offline and instant (file + TOML parsing only), so it
# also runs in pre-commit.
licenses-manifest:
    uv run python scripts/check_bundled_images.py

# Additionally pull the small referenced images and check for in-image license
# drift with trivy (catches a vendor relicensing an image). Needs trivy + Docker.
licenses-images:
    uv run python scripts/check_bundled_images.py --scan-images

hooks-install:
    uv run pre-commit install

hooks-run:
    uv run pre-commit run --all-files
