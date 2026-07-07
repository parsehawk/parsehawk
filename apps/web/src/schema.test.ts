import { describe, expect, it, vi } from "vitest";

import { deleteJob, formatApiError } from "./api";
import { parseJsonObject, prettyJson, receiptSchema } from "./schema";
import {
  field,
  fieldSchemaFromFields,
  fieldsFromFieldSchema,
  fieldsFromNuextractTemplate,
  fieldsFromSchema,
  nuextractTypeMetadata,
  nuextractTypes,
  nuextractTemplateFromFields,
  schemaFromFields
} from "./schemaBuilder";

describe("schema helpers", () => {
  it("formats the default receipt schema", () => {
    expect(prettyJson(receiptSchema)).toContain("merchant_name");
  });

  it("parses JSON objects and rejects arrays", () => {
    expect(parseJsonObject('{"ok": true}')).toEqual({ ok: true });
    expect(() => parseJsonObject("[]")).toThrow("Expected a JSON object");
  });

  it("lists all supported NuExtract3 semantic types", () => {
    expect(nuextractTypes).toContain("duration");
    expect(nuextractTypes).toContain("email-address");
    expect(nuextractTypes).toContain("region:DE");
    expect(nuextractTypes).not.toContain("email");
    expect(nuextractTypeMetadata["iban"].description).toContain("International Bank Account");
  });

  it("builds JSON Schema from editable fields", () => {
    expect(
      schemaFromFields([
        field({ name: "vendor", type: "verbatim-string", nullable: true }),
        field({ name: "currency", type: "currency", enumText: "EUR, USD", nullable: true }),
        field({ name: "line_items", type: "string", list: true, nullable: false }),
        field({
          name: "vendor_account",
          nullable: false,
          validationPreset: "exact_digits",
          validationLength: "10"
        }),
        field({
          name: "order_code",
          nullable: false,
          validationPreset: "exact_alphanumeric",
          validationLength: "8"
        })
      ])
    ).toEqual({
      type: "object",
      additionalProperties: false,
      properties: {
        vendor: {
          type: ["string", "null"],
          "x-parsehawk": { semantic: "verbatim-string" }
        },
        currency: {
          type: ["string", "null"],
          enum: ["EUR", "USD", null],
          "x-parsehawk": { semantic: "currency" }
        },
        line_items: {
          type: "array",
          items: { type: "string" }
        },
        vendor_account: {
          type: "string",
          pattern: "^\\d{10}$",
          minLength: 10,
          maxLength: 10
        },
        order_code: {
          type: "string",
          pattern: "^[A-Za-z0-9]{8}$",
          minLength: 8,
          maxLength: 8
        }
      },
      required: ["vendor", "currency", "line_items", "vendor_account", "order_code"]
    });
  });

  it("loads editable fields from JSON Schema", () => {
    const fields = fieldsFromSchema({
      type: "object",
      properties: {
        currency: {
          type: ["string", "null"],
          enum: ["EUR", "USD", null],
          "x-parsehawk": { semantic: "currency" }
        },
        vendor_account: {
          type: "string",
          pattern: "^\\d{10}$",
          minLength: 10,
          maxLength: 10
        },
        order_code: {
          type: "string",
          pattern: "^[A-Za-z0-9]{8}$",
          minLength: 8,
          maxLength: 8
        }
      },
      required: ["currency", "vendor_account", "order_code"]
    });

    expect(fields).toMatchObject([
      {
        name: "currency",
        type: "currency",
        required: true,
        nullable: true,
        enumText: "EUR, USD"
      },
      {
        name: "vendor_account",
        validationPreset: "exact_digits",
        validationLength: "10"
      },
      {
        name: "order_code",
        validationPreset: "exact_alphanumeric",
        validationLength: "8"
      }
    ]);
  });

  it("builds canonical field schema from editable fields", () => {
    expect(
      fieldSchemaFromFields([
        field({ name: "vendor", type: "verbatim-string", nullable: true }),
        field({ name: "currency", enumText: "EUR, USD", nullable: true }),
        field({ name: "tags", enumText: "paid, urgent", list: true }),
        field({
          name: "vendor_account",
          validationPreset: "exact_digits",
          validationLength: "10",
          nullable: false
        })
      ])
    ).toEqual({
      fields: [
        {
          key: "vendor",
          kind: "scalar",
          json_type: "string",
          nuextract_type: "verbatim-string",
          required: true,
          nullable: true
        },
        {
          key: "currency",
          kind: "enum",
          json_type: "string",
          nuextract_type: "enum",
          required: true,
          nullable: true,
          enum: ["EUR", "USD"]
        },
        {
          key: "tags",
          kind: "multi_enum",
          json_type: "array",
          nuextract_type: "multi_enum",
          required: true,
          nullable: false,
          enum: ["paid", "urgent"]
        },
        {
          key: "vendor_account",
          kind: "scalar",
          json_type: "string",
          nuextract_type: "string",
          required: true,
          nullable: false,
          pattern: "^\\d{10}$",
          minLength: 10,
          maxLength: 10
        }
      ]
    });
  });

  it("round-trips flat field schema and NuExtract templates into editable fields", () => {
    expect(
      fieldsFromFieldSchema({
        fields: [
          {
            key: "total",
            kind: "scalar",
            json_type: "number",
            nuextract_type: "number",
            required: true,
            nullable: true
          }
        ]
      })
    ).toMatchObject([{ name: "total", type: "number", required: true, nullable: true }]);

    expect(nuextractTemplateFromFields([field({ name: "currency", enumText: "EUR, USD" })])).toEqual({
      currency: ["EUR", "USD"]
    });
    expect(fieldsFromNuextractTemplate({ tags: [["paid", "urgent"]] })).toMatchObject([
      { name: "tags", shape: "array", itemShape: "scalar", enumText: "paid, urgent" }
    ]);
  });

  it("builds nested objects and arrays of objects from editable fields", () => {
    const fields = [
      field({
        name: "customer",
        shape: "object",
        nullable: true,
        fields: [field({ name: "name", type: "verbatim-string", nullable: false })]
      }),
      field({
        name: "line_items",
        shape: "array",
        itemShape: "object",
        required: false,
        fields: [
          field({ name: "description", type: "verbatim-string" }),
          field({ name: "total", type: "number", required: false })
        ]
      })
    ];

    expect(schemaFromFields(fields)).toEqual({
      type: "object",
      additionalProperties: false,
      properties: {
        customer: {
          type: ["object", "null"],
          additionalProperties: false,
          properties: {
            name: {
              type: "string",
              "x-parsehawk": { semantic: "verbatim-string" }
            }
          },
          required: ["name"]
        },
        line_items: {
          type: "array",
          items: {
            type: "object",
            additionalProperties: false,
            properties: {
              description: {
                type: ["string", "null"],
                "x-parsehawk": { semantic: "verbatim-string" }
              },
              total: { type: ["number", "null"] }
            },
            required: ["description"]
          }
        }
      },
      required: ["customer"]
    });

    expect(fieldSchemaFromFields(fields)).toEqual({
      fields: [
        {
          key: "customer",
          kind: "object",
          json_type: "object",
          nuextract_type: "object",
          required: true,
          nullable: true,
          fields: [
            {
              key: "name",
              kind: "scalar",
              json_type: "string",
              nuextract_type: "verbatim-string",
              required: true,
              nullable: false
            }
          ]
        },
        {
          key: "line_items",
          kind: "array",
          json_type: "array",
          nuextract_type: "array",
          required: false,
          nullable: false,
          items: {
            kind: "object",
            json_type: "object",
            nuextract_type: "object",
            fields: [
              {
                key: "description",
                kind: "scalar",
                json_type: "string",
                nuextract_type: "verbatim-string",
                required: true,
                nullable: true
              },
              {
                key: "total",
                kind: "scalar",
                json_type: "number",
                nuextract_type: "number",
                required: false,
                nullable: true
              }
            ]
          }
        }
      ]
    });

    expect(nuextractTemplateFromFields(fields)).toEqual({
      customer: { name: "verbatim-string" },
      line_items: [{ description: "verbatim-string", total: "number" }]
    });
  });

  it("imports nested JSON Schema and field schema into editable fields", () => {
    expect(
      fieldsFromSchema({
        type: "object",
        properties: {
          line_items: {
            type: "array",
            items: {
              type: "object",
              properties: {
                total: { type: "number" }
              },
              required: ["total"]
            }
          }
        },
        required: ["line_items"]
      })
    ).toMatchObject([
      {
        name: "line_items",
        shape: "array",
        itemShape: "object",
        required: true,
        nullable: false,
        fields: [{ name: "total", shape: "scalar", type: "number", required: true }]
      }
    ]);

    expect(
      fieldsFromFieldSchema({
        fields: [
          {
            key: "customer",
            kind: "object",
            fields: [{ key: "email", kind: "scalar", json_type: "string", nuextract_type: "email-address" }]
          }
        ]
      })
    ).toMatchObject([
      {
        name: "customer",
        shape: "object",
        fields: [{ name: "email", type: "email-address" }]
      }
    ]);
  });
});

describe("api helpers", () => {
  it("accepts successful empty responses", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 202 }));

    await expect(deleteJob("job_123")).resolves.toBeUndefined();

    expect(fetch).toHaveBeenCalledWith("/v1/jobs/job_123", { method: "DELETE" });
    fetch.mockRestore();
  });

  it("formats FastAPI validation errors for display", () => {
    expect(
      formatApiError(
        JSON.stringify({
          detail: [
            {
              loc: ["body", "file_id"],
              msg: "Field required"
            }
          ]
        }),
        422
      )
    ).toBe("file_id: Field required");
  });
});
