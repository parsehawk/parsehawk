import { describe, expect, it } from "vitest";

import {
  examplesDraftFingerprint,
  examplesFromExtractor,
  examplesToPayload,
  newEditableExample,
  type EditableExample,
} from "./examples";
import type { Extractor } from "./types";

describe("examples", () => {
  it("serializes text and file examples for the API", () => {
    const textExample: EditableExample = {
      ...newEditableExample("text"),
      text: "Invoice number 123",
      outputText: '{ "invoice_number": "123" }',
    };
    const fileExample: EditableExample = {
      ...newEditableExample("file"),
      fileId: "file_123",
      outputText: "plain text output",
    };

    expect(examplesToPayload([textExample, fileExample])).toEqual([
      {
        input: { type: "text", text: "Invoice number 123" },
        output: { invoice_number: "123" },
      },
      {
        input: { type: "file", file_id: "file_123" },
        output: "plain text output",
      },
    ]);
  });

  it("restores extractor examples into editable drafts", () => {
    const extractor: Extractor = {
      id: "extractor_123",
      name: "invoice",
      display_name: "Invoice",
      instructions: "extract",
      reasoning_effort: null,
      provider_name: "openai_compatible_api",
      model: null,
      schema: { type: "object" },
      examples: [
        {
          input: { type: "file", file_id: "file_123" },
          output: { answer: "ok" },
        },
      ],
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };

    expect(examplesFromExtractor(extractor)[0]).toMatchObject({
      inputType: "file",
      fileId: "file_123",
      outputText: '{\n  "answer": "ok"\n}',
    });
  });

  it("fingerprints drafts without unstable ids", () => {
    const example = { ...newEditableExample(), text: "A", outputText: "{}" };

    expect(examplesDraftFingerprint([example])).toBe(
      JSON.stringify([{ inputType: "text", text: "A", fileId: "", outputText: "{}" }])
    );
  });
});
