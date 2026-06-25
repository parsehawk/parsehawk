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
