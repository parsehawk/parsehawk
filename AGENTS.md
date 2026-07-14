# Repository Guidelines

## Git

Use conventional commits for every commit, keep commits atomic, and explain the reasoning for the change in the commit body. The subject should say what changed; the body should say why this change is the right shape.

When a change is ready, commit the atomic slice immediately and keep moving. If a defect is discovered right after, fix it in the next atomic commit or amend the fresh commit when that is clearly the tighter history.

Every commit must be deployable. Do not create intermediate commits that leave the repository in a broken or half-finished state.

Before committing, check `git status` and stage only the files that belong to the current logical change.

Prefer a short-lived branch for the work. Keep the branch focused, rebase on `main` when needed, and preserve a clean linear history.

This repository uses trunk-based development. Do not merge feature branches into
`main` directly from the local checkout. Before integration, fetch the latest
`main`, rebase the current branch onto `origin/main`, fix any conflicts, push
the rebased branch, create a pull request, and use GitHub's rebase-merge to land
it on `main`. After the pull request is merged, update the local `main` branch
from `origin/main` and delete the merged local branch.

Suggested commit format:

```text
<type>(<scope>): <description>

<why this change is needed and why this implementation is appropriate>
```

Recommended conventions:

- `docs(...)` for repository guidance or documentation-only changes.
- `feat(...)` for new user-facing or developer-facing functionality.
- `fix(...)` for bug fixes.
- `chore(...)` for maintenance that does not change behavior.

For multi-line commit messages, preserve real newlines in the body. Do not use literal `\n` escape sequences.

## Developer documentation

Developer documentation is part of the product contract and the definition of
done. Any change to public behavior must update the relevant documentation in
the same pull request; do not defer documentation to a follow-up. This includes
REST routes and schemas, errors, CLI commands and output, configuration and
defaults, extraction schemas, providers and models, runtime behavior, supported
platforms, installation and deployment, paths and ports, observability, and Web
UI workflows.

Keep reference material self-documenting and generated from the implementation:

- Put API descriptions, examples, operation metadata, and schema details in the
  FastAPI and Pydantic source, then run `just openapi-export`.
- Put CLI help and configuration metadata in their typed source definitions,
  then run `just references-export`.
- Never hand-edit `openapi/openapi.yaml` or a file marked as generated. Change
  its source and regenerate it instead.
- Update the appropriate tutorial, how-to guide, explanation, or hand-written
  reference under `apps/docs/src/content/docs/` when generated metadata alone
  does not explain the user workflow or design.
- Keep commands and examples executable against the current implementation,
  and keep internal links valid.

Run `just docs-check` for every documentation change and every change to a
documented public contract. It verifies generated references, formatting,
Astro types, links, and the final static artifacts.

## Verification

For changes that affect runtime startup, model serving, extraction behavior,
Docker Compose, platform detection, or end-to-end workflows, verify the full
local runtime path before opening or updating a pull request:

```bash
parsehawk restart
just e2e
```

When feasible, run this verification on both supported local-runtime platforms:

- macOS Apple Silicon, which uses vLLM Metal on the host
- Linux with an NVIDIA GPU, which uses the Docker Compose vLLM runtime service

If one platform is not available, say so explicitly in the PR or final summary.
