---
title: Design reliable extraction schemas
description: Shape JSON Schema contracts that guide the model and validate every result.
sidebar:
  order: 5
---

An extraction schema serves three purposes at once: it tells the model what to
return, validates the response, and becomes the downstream data contract.

## Make absence explicit

Use nullable fields when a document may legitimately omit a value, and keep the
field in `required`. This distinguishes “the extractor considered this field and
found nothing” from an unstable response shape.

```json
{
  "type": "object",
  "properties": {
    "purchase_order": {
      "type": ["string", "null"],
      "description": "Purchase-order reference exactly as printed."
    }
  },
  "required": ["purchase_order"],
  "additionalProperties": false
}
```

## Write field-level instructions

Descriptions should settle ambiguity close to the field. State units, expected
normalization, and what not to infer. Keep the extractor-level instruction for
rules that apply to the whole document.

Prefer:

```json
"net_amount": {
  "type": ["number", "null"],
  "description": "Net amount before tax, as a decimal number in the invoice currency. Do not calculate it when absent."
}
```

Avoid vague descriptions such as `"The amount"`.

## Use enums for closed choices

```json
"document_type": {
  "type": ["string", "null"],
  "enum": ["invoice", "credit_note", "receipt", null],
  "description": "Choose only from the listed document types."
}
```

## Add semantic hints where they clarify intent

```json
"supplier_iban": {
  "type": ["string", "null"],
  "description": "Supplier IBAN without inventing missing digits.",
  "x-parsehawk": { "semantic": "iban" }
}
```

The [generated extraction-schema reference](/reference/extraction-schema/)
lists every accepted shape and semantic value.

## Validate before updating an extractor

```console
parsehawk schemas validate invoice.schema.json
```

Then synchronize the reusable extractor:

```console
parsehawk extractors put invoice_v1 \
  --display-name "Invoice extractor" \
  --instructions instructions.txt \
  --schema invoice.schema.json
```

Treat schema changes like API changes: review them, test representative
documents, and version stable extractor names when downstream consumers cannot
accept a breaking shape.
