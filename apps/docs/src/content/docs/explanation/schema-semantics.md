---
title: Schemas and semantic types
description: Why ParseHawk uses a focused JSON Schema dialect plus semantic extraction hints.
sidebar:
  order: 4
---

JSON Schema describes storage types well, but document extraction often needs
meaning that a primitive cannot express. A date, IBAN, literal transcription,
and free-form name are all strings in JSON, yet they require different model
behavior.

ParseHawk combines two layers:

1. a focused JSON Schema dialect for structure and validation
2. `x-parsehawk.semantic` for extraction meaning

## One contract across the pipeline

The extractor schema becomes:

- a model-facing template
- a structured response constraint for compatible providers
- the validator for returned JSON
- the contract consumed by your application

Keeping these roles together prevents a prompt from promising one shape while a
validator or SDK expects another.

## Why the dialect is focused

General JSON Schema can express constructs that small models and structured
decoders cannot implement reliably. ParseHawk intentionally supports a narrower
authoring surface: objects, arrays, scalar values, enums, nullable unions, and a
small set of string constraints.

Unsupported and unknown keywords fail schema validation early. That makes
accepted extractor definitions portable across the supported provider paths.

## Semantic hints

This field asks for an ISO-style date rather than an arbitrary string:

```json
{
  "type": ["string", "null"],
  "description": "The invoice date shown on the document.",
  "x-parsehawk": { "semantic": "date" }
}
```

Semantic hints include dates and times, currencies and countries, language
identifiers, contact details, financial identifiers, units, and selected region
formats. They guide extraction; the output remains ordinary JSON.

## How models receive semantics

NuExtract3 variants understand their fine-tuned semantic template. Other models
receive a generic system prompt containing the same semantic-type reference and
a template derived from the schema. ParseHawk also requests JSON
Schema-constrained decoding from the provider.

The provider constraint improves shape reliability, but server-side validation
remains authoritative. A job cannot be `completed` with an invalid result.

See the [generated extraction schema reference](/reference/extraction-schema/)
for the exact accepted contract.
