# ParseHawk developer docs

The developer documentation is an Astro Starlight application deployed to
`https://docs.parsehawk.com`.

## Commands

From the repository root:

```console
just docs-dev
just docs-format
just docs-typecheck
just docs-build
just docs-check
```

Install workspace dependencies with `pnpm install`. API, CLI, configuration,
and extraction-schema references are generated; update them with:

```console
just openapi-export
just references-export
```

Do not edit generated reference pages or `openapi/openapi.yaml` by hand.

## Information architecture

- Tutorials teach one guaranteed path end to end.
- How-to guides solve a specific operational task.
- Explanation pages build a mental model.
- Reference pages state exact contracts and defaults.

Keep one page focused on one reader need. Link to generated references instead
of copying option lists or request schemas into human-authored pages.

## Ownership and verification

Git history is the ownership and last-verified record for human-authored pages;
Starlight displays each page's last update and edit link. Code owners of the
documented surface review related docs. Generated pages carry a notice and are
checked for drift in pre-commit and CI.

Tutorial commands should use repository fixtures and be exercised during the
related end-to-end verification. Keep UI documentation workflow-oriented and
screenshot-light unless an image materially reduces confusion.

## Deployment

The Pages workflow builds from `main`, uploads `apps/docs/dist`, and deploys the
static artifact. `public/CNAME` records the custom domain. GitHub Pages must be
enabled for Actions and `docs.parsehawk.com` must point to the repository's
organization Pages hostname before HTTPS can be enforced.
