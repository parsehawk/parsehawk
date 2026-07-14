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
