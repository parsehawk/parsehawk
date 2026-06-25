import { parseJsonObject, prettyJson } from "./schema";
import type { Extractor, ExtractorExample } from "./types";

export type EditableExample = {
  id: string;
  inputType: "text" | "file";
  text: string;
  fileId: string;
  outputText: string;
};

export function newEditableExample(inputType: EditableExample["inputType"] = "text"): EditableExample {
  return {
    id: newExampleId(),
    inputType,
    text: "",
    fileId: "",
    outputText: "{\n  \n}",
  };
}

export function examplesToPayload(examples: EditableExample[]): ExtractorExample[] {
  return examples.map((example, index) => {
    const output = parseExampleOutput(example.outputText, index);
    if (example.inputType === "file") {
      if (!example.fileId) {
        throw new Error(`Example ${index + 1} needs a file.`);
      }
      return {
        input: { type: "file", file_id: example.fileId },
        output,
      };
    }
    if (!example.text.trim()) {
      throw new Error(`Example ${index + 1} needs input text.`);
    }
    return {
      input: { type: "text", text: example.text },
      output,
    };
  });
}

export function examplesFromExtractor(extractor: Extractor): EditableExample[] {
  return extractor.examples.map((example) => {
    if (typeof example.input === "string") {
      return editableExample({
        inputType: "text",
        text: example.input,
        outputText: outputToText(example.output),
      });
    }
    if (example.input.type === "file") {
      return editableExample({
        inputType: "file",
        fileId: example.input.file_id,
        outputText: outputToText(example.output),
      });
    }
    return editableExample({
      inputType: "text",
      text: example.input.text,
      outputText: outputToText(example.output),
    });
  });
}

export function examplesDraftFingerprint(examples: EditableExample[]): string {
  return JSON.stringify(
    examples.map((example) => ({
      inputType: example.inputType,
      text: example.text,
      fileId: example.fileId,
      outputText: example.outputText,
    }))
  );
}

function editableExample(patch: Partial<EditableExample>): EditableExample {
  return {
    ...newEditableExample(patch.inputType),
    ...patch,
  };
}

function parseExampleOutput(value: string, index: number): Record<string, unknown> | string {
  const trimmed = value.trim();
  if (!trimmed) {
    throw new Error(`Example ${index + 1} needs expected output.`);
  }
  if (!trimmed.startsWith("{")) {
    return value;
  }
  const parsed = parseJsonObject(trimmed);
  if (!isRecord(parsed) || Array.isArray(parsed)) {
    throw new Error(`Example ${index + 1} output must be a JSON object or plain text.`);
  }
  return parsed;
}

function outputToText(output: ExtractorExample["output"]): string {
  return typeof output === "string" ? output : prettyJson(output);
}

function newExampleId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `example_${Date.now()}_${Math.random().toString(36).slice(2)}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
