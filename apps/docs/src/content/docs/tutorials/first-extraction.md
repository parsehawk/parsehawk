---
title: Extract your first document
description: Start ParseHawk and turn the bundled receipt image into validated JSON.
sidebar:
  order: 1
---

In this tutorial you will start the local stack, run a known receipt through the
prebuilt `receipt` extractor, and inspect the structured result.

## Before you begin

Use a supported [macOS or Linux installation](/start-here/choose-installation/).
From a fresh checkout, install the editable CLI:

```console
git clone https://github.com/parsehawk/parsehawk.git
cd parsehawk
uv tool install --editable .
```

## 1. Start ParseHawk

```console
parsehawk start
```

The first start can take several minutes while the runtime downloads model
weights and warms up. Wait for the command to report that the services are
ready. If it exits early, run `parsehawk doctor` and follow the reported fix.

## 2. Run the bundled receipt

The repository includes a deterministic fixture and a seeded extractor with the
stable name `receipt`:

```console
parsehawk extract tests/fixtures/receipt/receipt.jpg \
  --extractor receipt \
  --wait
```

The CLI uploads the image, creates an asynchronous job, waits for it to finish,
and prints the job. The extracted data should contain these values:

```json
{
  "merchant_name": "PARSEHAWK COFFEE",
  "receipt_id": "R-1001",
  "date": "2026-06-21",
  "total": 11.22,
  "currency": "EUR"
}
```

Small local models can vary in formatting, but the result is accepted only when
it satisfies the extractor's schema.

## 3. Inspect the same run in the Web UI

Open `http://127.0.0.1:5173`, select **Jobs**, and open the newest job. The page
shows the source file, extractor, lifecycle state, and canonical JSON stored in
`job.result.data`.

## 4. Check local model traces

Open `http://127.0.0.1:6006` to see the bundled Phoenix trace. It records the
model request, response, latency, and token use in local storage under
`data/phoenix/`.

## What you built

You exercised the full path:

```text
document → uploaded file → extraction job → model → schema validation → JSON
```

Continue with [build a reusable extractor](/tutorials/reusable-extractor/) to
define your own output contract.
