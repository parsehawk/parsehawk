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

e2e:
    uv run pytest --no-cov -m e2e tests/e2e

format:
    uv run ruff format src tests

format-check:
    uv run ruff format --check src tests

lint:
    uv run ruff check src tests

typecheck:
    uv run ty check src tests

web-dev:
    pnpm --dir apps/web dev

web-build:
    CI=true pnpm --dir apps/web build

web-test:
    CI=true pnpm --dir apps/web test

web-typecheck:
    CI=true pnpm --dir apps/web typecheck

check: format-check lint typecheck test web-typecheck web-test web-build

hooks-install:
    uv run pre-commit install

hooks-run:
    uv run pre-commit run --all-files
