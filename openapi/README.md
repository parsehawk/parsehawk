# ParseHawk OpenAPI contract

`openapi.yaml` is the committed, distributable API contract. FastAPI routes and
Pydantic models are authoritative; never edit the YAML directly.

```bash
just openapi-export       # regenerate after changing the API
just openapi-check-sync   # fail with a diff when the artifact is stale
just openapi-validate     # validate OpenAPI 3.1 structure
just openapi-lint         # run the pinned Speakeasy SDK-readiness linter
just openapi-check        # run every contract check
```

The Speakeasy binary is downloaded from its pinned GitHub release into the
ignored `.cache/tools/` directory. The installer verifies the published SHA-256
checksum before executing it.
