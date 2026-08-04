---
title: Versioning reference
description: ParseHawk release, REST path, OpenAPI, CLI, and extractor-schema versioning rules.
sidebar:
  order: 9
---

| Surface            | Versioning rule                                  | Consumer guidance                                                               |
| ------------------ | ------------------------------------------------ | ------------------------------------------------------------------------------- |
| ParseHawk releases | Semantic Versioning                              | Pin a release; below 1.0, review every minor upgrade                            |
| REST resources     | `/v1` path prefix                                | Do not infer release compatibility from the path alone during developer preview |
| OpenAPI            | Generated from the app and committed per release | Generate clients from the artifact matching the deployed version                |
| CLI                | Ships with the ParseHawk Python package          | Keep CLI and server on the same release where possible                          |
| Extractor output   | Defined by each extractor schema                 | Use a new stable name for a breaking output shape                               |

## v0.3 to v0.4 extraction-job migration

| Release | Canonical surface                        | Compatibility surface                       |
| ------- | ---------------------------------------- | ------------------------------------------- |
| v0.3    | `/v1/extraction-jobs`, `extraction-jobs` | `/v1/jobs`, `parsehawk jobs` are deprecated |
| v0.4    | `/v1/extraction-jobs`, `extraction-jobs` | Generic job aliases are removed             |

The v0.3 aliases use the same extraction service, rows, transitions, status
codes, and response schema. Existing `job_...` identifiers remain valid and are
not rewritten. New parsing work is separate at `/v1/parse-jobs` and uses
`parse_job_...` identifiers.

## Contract artifacts

- Human REST reference: [`/reference/api/`](/reference/api/)
- OpenAPI 3.1 YAML: [`/openapi.yaml`](/openapi.yaml)
- Extraction meta-schema: [`/schemas/parsehawk-extraction-schema.schema.json`](/schemas/parsehawk-extraction-schema.schema.json)
- CLI reference: [`/reference/cli/`](/reference/cli/)
- Configuration reference: [`/reference/configuration/`](/reference/configuration/)

Explicit OpenAPI `operationId` values are the intended method-name source for
future SDK generators. A contract diff that changes them should be treated as a
client-facing change.

## Pre-1.0 policy

The project is currently a developer preview. `/v1` establishes the resource
namespace, while a 1.0 release will establish the stronger compatibility
baseline. Until then, pin deployments and inspect release notes and OpenAPI
diffs before upgrading production integrations.
