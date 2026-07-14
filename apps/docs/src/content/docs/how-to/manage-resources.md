---
title: Manage files and extractors
description: Upload, inspect, synchronize, and remove the persistent resources used by extraction jobs.
sidebar:
  order: 10
---

## Files

Upload and capture the returned metadata:

```console
parsehawk files upload document.pdf
parsehawk files list
parsehawk files get file_...
```

Delete a stored file when no longer needed:

```console
parsehawk files delete file_...
```

An existing job retains its record, but deleting source content can prevent new
work or later content retrieval. Apply a retention policy to both files and job
results.

## Extractors

Use a stable, lowercase name with ASCII letters, digits, hyphens, or underscores.
It cannot begin with the reserved `extractor_` prefix.

For source-controlled definitions, keep instructions, schema, and examples in
files and synchronize idempotently:

```console
parsehawk extractors put invoice_v1 \
  --display-name "Invoice extractor" \
  --instructions instructions.txt \
  --schema invoice.schema.json \
  --examples examples.json
```

Use a partial update for an intentional one-field change:

```console
parsehawk extractors update invoice_v1 --display-name "Invoices"
```

Inspect and remove definitions:

```console
parsehawk extractors list
parsehawk extractors get invoice_v1
parsehawk extractors delete invoice_v1
```

## Version definitions in Git

Treat the files passed to `extractors put` as the reviewable source of truth.
When the output shape changes incompatibly, create a new stable extractor name
instead of silently replacing the contract used by existing consumers.

Few-shot file examples reference uploaded `file_...` IDs and are therefore tied
to the target ParseHawk data store. Inline-text examples are easier to move
between installations.

See [operate asynchronous jobs](/how-to/jobs/) for execution and retention
behavior after resources exist.
