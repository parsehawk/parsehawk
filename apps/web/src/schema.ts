export const receiptSchema = {
  type: "object",
  additionalProperties: false,
  properties: {
    merchant_name: { type: ["string", "null"] },
    receipt_id: { type: ["string", "null"] },
    date: { type: ["string", "null"] },
    total: { type: ["number", "null"] },
    currency: { type: ["string", "null"], enum: ["EUR", "USD", "GBP", null] }
  },
  required: ["merchant_name", "receipt_id", "date", "total", "currency"]
};

export function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export function parseJsonObject(value: string): Record<string, unknown> {
  const parsed = JSON.parse(value);
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("Expected a JSON object");
  }
  return parsed as Record<string, unknown>;
}
