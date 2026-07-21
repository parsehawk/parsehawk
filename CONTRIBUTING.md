# Contributing to ParseHawk

Thanks for helping improve ParseHawk. This guide explains the workflow we expect
for changes to the Apache-2.0 open-source core.

## Maintainers

Maintainers review issues and pull requests, make release decisions, and keep
the open-source core clearly separated from any future hosted cloud, enterprise,
or source-available work.

- Simon Hoffmann - Maintainer

  GitHub: [@simx11](https://github.com/simx11)

- Francis Rafal - Maintainer

  GitHub: [@francisrafal](https://github.com/francisrafal) · X:
  [@francisrafal](https://x.com/francisrafal)

- Benedikt Hielscher - Maintainer

  GitHub: [@benemanu](https://github.com/benemanu)

## Contribution Terms

Unless another written agreement says otherwise, contributions submitted to this
repository are accepted under the Apache-2.0 license used by the project.

By opening a pull request, you confirm that you have the right to contribute the
code, documentation, tests, and other materials in that pull request under those
terms. Do not include proprietary data, customer documents, secrets, private
model outputs, or assets that cannot be redistributed under the project license.

ParseHawk may later offer hosted cloud or enterprise products built around the
open-source core. The open-source core remains Apache-2.0, and any future
enterprise or source-available areas should be documented separately.

## Local Setup

Development requires:

- `git`
- `just`
- `uv`
- `node`
- `pnpm`
- Docker

`pnpm` is required for the standard development workflow because the Web UI
typecheck, tests, build, and pre-commit hooks use it. Backend-only changes may
not need `pnpm` for every edit-test loop, but a PR-ready checkout should have it
installed.

Docker is part of the development toolchain so contributors can build images and
run the local stack:

- macOS: Docker Desktop
- Linux: Docker Engine and Docker Compose

Clone the repository and install dependencies:

```bash
git clone https://github.com/parsehawk/parsehawk.git
cd parsehawk
just setup
```

`just setup` runs `uv sync --all-extras`, installs web dependencies with `pnpm`,
and installs the pre-commit hooks. It first checks that required development
tools are available and prints install links for anything missing; it does not
install system-level tools globally.

If you use the installed `parsehawk` CLI from this checkout, install it as an
editable tool:

```bash
uv tool install --editable .
```

After pulling a change that adds or updates Python dependencies, refresh the
editable tool environment:

```bash
uv tool install --force --editable .
```

## Development Commands

Use the `justfile` recipes as the source of truth for local development.

```bash
just start          # product-like Docker mode
just dev            # local-source development mode with reload
just worker         # run the worker process directly
just web-dev        # Web UI dev server only
```

You can also run the CLI commands directly:

```bash
parsehawk dev
parsehawk dev -x runtime    # API and Web UI without the bundled runtime
parsehawk start
parsehawk start -x runtime  # API and Web UI without the bundled runtime
```

Quality checks:

```bash
just format         # format Python with Ruff
just format-check   # check Python formatting
just lint           # Ruff linting
just typecheck      # ty type checking
just test           # Python tests with coverage gate
just test-unit      # Python unit tests only
just test-concurrency # SQLite isolation and parallel API regression tests
just web-typecheck  # TypeScript checks
just web-test       # Web UI tests
just web-build      # production Web UI build
just check          # standard Python and web checks
just hooks-run      # run pre-commit on all files
```

The Python test configuration enforces 100% coverage for:

- `parsehawk.core.domain`
- `parsehawk.core.application`

Changes in those packages should keep that coverage at 100%. If your change adds
domain or application behavior, add focused tests with the implementation.

Pre-commit hooks are not installed automatically by Git. Run `just setup` once
per clone, or run `just hooks-install` if dependencies are already installed.
The hooks run Ruff, ty, Python tests, Web UI typecheck, and Web UI tests. CI
should still run the same checks; hooks are just the fast local feedback loop.
Because `pre-commit` is installed in the project `uv` environment, run it via
`just hooks-run` or `uv run pre-commit run --all-files` instead of calling
`pre-commit` directly.

## End-to-End Verification

Most documentation, UI-only, and narrow unit-tested changes do not need the full
runtime path. For changes that affect runtime startup, model serving, extraction
behavior, Docker Compose, platform detection, or end-to-end workflows, verify the
local runtime path before asking for review:

```bash
parsehawk restart
just e2e
```

When feasible, run that verification on both supported local-runtime platforms:

- macOS Apple Silicon, which uses vLLM Metal on the host
- Linux with an NVIDIA GPU, which uses the Docker Compose vLLM runtime service

If one platform is not available, say so in the pull request.

## Pull Request Workflow

1. Open or find an issue before starting substantial work.
2. Create a short-lived branch from the latest `main`.
3. Keep the branch focused on one logical change.
4. Include tests or documentation updates that match the behavior you changed.
5. Run the relevant local checks before opening the pull request.
6. Reference the issue in the pull request title or body, for example
   `Closes #76`.
7. Describe what changed, why it changed, and which checks you ran.

This repository uses trunk-based development. Do not merge feature branches into
`main` directly from a local checkout. Maintainers integrate through pull
requests, after the branch is rebased on the latest `origin/main`; GitHub's
rebase-merge should be used to land the change on `main`.

## Commit Messages

Use conventional commits and keep commits atomic. The subject should say what
changed, and the body should explain why this implementation is the right shape.

Recommended commit types:

- `docs(...)` for documentation-only changes
- `feat(...)` for user-facing or developer-facing functionality
- `fix(...)` for bug fixes
- `chore(...)` for maintenance that does not change behavior

Suggested format:

```text
<type>(<scope>): <description>

<why this change is needed and why this implementation is appropriate>
```

For multi-line commit messages, use real newlines in the body. Do not use
literal `\n` escape sequences.

## Credit

We plan to credit all contributors in the README. That contributor list is
tracked separately from this guide; until then, GitHub issues, pull requests,
and commit history remain the source of truth for contribution attribution.

## Getting Help

If you get stuck, ask in the GitHub issue or pull request you are working from.
For broader questions, open a new issue with:

- what you are trying to do
- what you expected to happen
- what happened instead
- relevant commands, logs, screenshots, or environment details

Please redact secrets, customer data, and private documents before posting.
