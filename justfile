set dotenv-load := true

export PARSEHAWK_DATA_DIR := env_var_or_default("PARSEHAWK_DATA_DIR", "data")
export PARSEHAWK_DATABASE_PATH := env_var_or_default("PARSEHAWK_DATABASE_PATH", "data/parsehawk.db")

setup:
    uv sync
    pnpm install
    uv run pre-commit install

start:
    uv run parsehawk start

dev:
    uv run parsehawk dev --reload

worker:
    uv run parsehawk-worker

test:
    uv run pytest

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
    pnpm --dir apps/web build

web-test:
    pnpm --dir apps/web test

web-typecheck:
    pnpm --dir apps/web typecheck

check: format-check lint typecheck test web-typecheck web-test web-build

hooks-install:
    uv run pre-commit install

hooks-run:
    uv run pre-commit run --all-files
