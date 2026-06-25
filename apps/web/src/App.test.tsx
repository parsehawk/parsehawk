import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

describe("App run workflow", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows job progress as UI instead of raw create-job JSON", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/v1/files") {
        return jsonResponse([]);
      }
      if (url === "/v1/extractors") {
        return jsonResponse([
          {
            id: "extractor_123",
            name: "receipt_v1",
            instructions: "Extract receipt fields.",
            schema: { type: "object" },
            examples: [],
            created_at: "2026-06-21T00:00:00Z",
            updated_at: "2026-06-21T00:00:00Z"
          }
        ]);
      }
      if (url === "/v1/jobs?extractor_id=extractor_123" && init?.method !== "POST") {
        return jsonResponse([]);
      }
      if (url === "/v1/jobs" && init?.method === "POST") {
        return jsonResponse({
          id: "job_123",
          extractor_id: "extractor_123",
          file_id: null,
          source_text: "Corner Market",
          status: "queued",
          result: null,
          error: null,
          created_at: "2026-06-21T00:00:00Z",
          started_at: null,
          completed_at: null
        });
      }
      return jsonResponse({ detail: "unexpected request" }, { status: 500 });
    });

    render(<App />);

    await userEvent.click(await screen.findByRole("tab", { name: "Text" }));
    await userEvent.click(screen.getByRole("button", { name: "Run extraction" }));

    expect(await screen.findByText("Job progress")).toBeInTheDocument();
    expect(screen.getAllByText("Queued").length).toBeGreaterThan(0);
    expect(screen.queryByText("artifact_dir")).not.toBeInTheDocument();
  });

  it("starts fresh extractor drafts empty when no extractors are saved", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/v1/files") {
        return jsonResponse([]);
      }
      if (url === "/v1/extractors") {
        return jsonResponse([]);
      }
      return jsonResponse({ detail: "unexpected request" }, { status: 500 });
    });

    render(<App />);

    expect(await screen.findByText("No extractors saved")).toBeInTheDocument();

    await userEvent.click(await screen.findByRole("button", { name: "New" }));

    expect(screen.getByLabelText("Name")).toHaveValue("");
    expect(screen.getByLabelText("Instructions")).toHaveValue("");
    expect(screen.getByText("No fields yet")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("receipt_v1")).not.toBeInTheDocument();
  });

  it("uploads multiple selected files through the single-file api with limited concurrency", async () => {
    const uploadedRecords: unknown[] = [];
    let activeUploads = 0;
    let maxActiveUploads = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/v1/files" && init?.method === "POST") {
        activeUploads += 1;
        maxActiveUploads = Math.max(maxActiveUploads, activeUploads);
        const formData = init.body as FormData;
        const file = formData.get("upload") as File;
        await new Promise((resolve) => setTimeout(resolve, 10));
        activeUploads -= 1;
        const record = {
          id: `file_${uploadedRecords.length + 1}`,
          file_name: file.name,
          content_type: file.type || "text/plain",
          size_bytes: file.size,
          sha256: `sha-${uploadedRecords.length + 1}`,
          created_at: "2026-06-21T00:00:00Z"
        };
        uploadedRecords.push(record);
        return jsonResponse(record);
      }
      if (url === "/v1/files") {
        return jsonResponse(uploadedRecords);
      }
      if (url === "/v1/extractors") {
        return jsonResponse([]);
      }
      return jsonResponse({ detail: "unexpected request" }, { status: 500 });
    });

    render(<App />);

    const input = await screen.findByLabelText(/add documents/i);
    const files = Array.from(
      { length: 20 },
      (_, index) => new File([`file ${index + 1}`], `document-${index + 1}.txt`, { type: "text/plain" })
    );
    await userEvent.upload(input, files);

    await waitFor(() => {
      expect(screen.getAllByText("document-20.txt").length).toBeGreaterThan(0);
    });
    expect(uploadedRecords).toHaveLength(20);
    expect(maxActiveUploads).toBeLessThanOrEqual(3);
  });

  it("saves the extractor thinking setting", async () => {
    let createPayload: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/v1/files") {
        return jsonResponse([]);
      }
      if (url === "/v1/extractors" && init?.method === "POST") {
        createPayload = JSON.parse(String(init.body));
        return jsonResponse({
          id: "extractor_123",
          name: "invoice",
          instructions: "Extract invoice fields.",
          enable_thinking: true,
          schema: createPayload?.schema,
          examples: [],
          created_at: "2026-06-21T00:00:00Z",
          updated_at: "2026-06-21T00:00:00Z"
        });
      }
      if (url === "/v1/extractors") {
        return jsonResponse([]);
      }
      return jsonResponse({ detail: "unexpected request" }, { status: 500 });
    });

    render(<App />);

    await userEvent.click(await screen.findByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Name"), "invoice");
    await userEvent.type(screen.getByLabelText("Instructions"), "Extract invoice fields.");
    await userEvent.click(screen.getByRole("checkbox", { name: "Enable thinking" }));
    await userEvent.click(screen.getByRole("button", { name: "Create extractor" }));

    await waitFor(() => {
      expect(createPayload?.enable_thinking).toBe(true);
    });
  });

  it("saves builder validation presets as JSON Schema constraints", async () => {
    let createPayload: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/v1/files") {
        return jsonResponse([]);
      }
      if (url === "/v1/extractors" && init?.method === "POST") {
        createPayload = JSON.parse(String(init.body));
        return jsonResponse({
          id: "extractor_123",
          name: "invoice",
          instructions: "Extract invoice fields.",
          enable_thinking: false,
          schema: createPayload?.schema,
          examples: [],
          created_at: "2026-06-21T00:00:00Z",
          updated_at: "2026-06-21T00:00:00Z"
        });
      }
      if (url === "/v1/extractors") {
        return jsonResponse([]);
      }
      return jsonResponse({ detail: "unexpected request" }, { status: 500 });
    });

    render(<App />);

    await userEvent.click(await screen.findByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Name"), "invoice");
    await userEvent.type(screen.getByLabelText("Instructions"), "Extract invoice fields.");
    await userEvent.click(screen.getByRole("button", { name: "Add field" }));
    await userEvent.clear(screen.getByLabelText("Field key"));
    await userEvent.type(screen.getByLabelText("Field key"), "vendor_account");
    await userEvent.selectOptions(screen.getByLabelText("Text pattern"), "exact_digits");
    await userEvent.clear(screen.getByLabelText("Exact pattern length"));
    await userEvent.type(screen.getByLabelText("Exact pattern length"), "10");
    await userEvent.click(screen.getByRole("button", { name: "Create extractor" }));

    await waitFor(() => {
      expect(createPayload?.schema).toMatchObject({
        properties: {
          vendor_account: {
            type: ["string", "null"],
            pattern: "^\\d{10}$",
            minLength: 10,
            maxLength: 10
          }
        }
      });
    });
  });

  it("does not infer examples from receipt-like user records and resets edited extractors", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/v1/files") {
        return jsonResponse([
          {
            id: "file_123",
            file_name: "receipt.png",
            content_type: "image/png",
            size_bytes: 42,
            sha256: "abc",
            created_at: "2026-06-21T00:00:00Z"
          }
        ]);
      }
      if (url === "/v1/extractors") {
        return jsonResponse([
          {
            id: "extractor_123",
            name: "receipt_v1",
            instructions: "Extract receipt fields.",
            schema: {
              type: "object",
              properties: { receipt_id: { type: "string" } },
              required: ["receipt_id"]
            },
            examples: [],
            created_at: "2026-06-21T00:00:00Z",
            updated_at: "2026-06-21T00:00:00Z"
          }
        ]);
      }
      if (url === "/v1/jobs?extractor_id=extractor_123") {
        return jsonResponse([]);
      }
      return jsonResponse({ detail: "unexpected request" }, { status: 500 });
    });

    render(<App />);

    expect((await screen.findAllByText("receipt.png")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Example file")).not.toBeInTheDocument();

    expect((await screen.findAllByText("receipt_v1")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Prebuilt")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Edit extractor" }));
    expect(screen.getByLabelText("Name")).toHaveValue("receipt_v1");
    expect(screen.getByLabelText("Instructions")).toHaveValue("Extract receipt fields.");

    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    await userEvent.click(screen.getByRole("button", { name: "New" }));

    expect(screen.getByLabelText("Name")).toHaveValue("");
    expect(screen.getByLabelText("Instructions")).toHaveValue("");
    expect(screen.getByText("No fields yet")).toBeInTheDocument();
  });

  it("labels records only when the api marks them as examples or prebuilt", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/v1/files") {
        return jsonResponse([
          {
            id: "file_example",
            file_name: "receipt.png",
            content_type: "image/png",
            size_bytes: 42,
            sha256: "abc",
            created_at: "2026-06-21T00:00:00Z",
            source: "example"
          }
        ]);
      }
      if (url === "/v1/extractors") {
        return jsonResponse([
          {
            id: "extractor_example",
            name: "receipt_v1",
            instructions: "Extract receipt fields.",
            schema: { type: "object" },
            examples: [],
            created_at: "2026-06-21T00:00:00Z",
            updated_at: "2026-06-21T00:00:00Z",
            source: "prebuilt"
          }
        ]);
      }
      if (url === "/v1/jobs?extractor_id=extractor_example") {
        return jsonResponse([]);
      }
      return jsonResponse({ detail: "unexpected request" }, { status: 500 });
    });

    render(<App />);

    expect(await screen.findByText("Example file")).toBeInTheDocument();
    expect(await screen.findByText("Prebuilt")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "View extractor" }));
    expect(screen.getByLabelText("Name")).toBeDisabled();
    expect(screen.getByLabelText("Instructions")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Update extractor" })).not.toBeInTheDocument();
  });

  it("loads and deletes jobs from extractor history", async () => {
    const requests: Array<{ method: string; url: string }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      requests.push({ method, url });
      if (url === "/v1/files") {
        return jsonResponse([]);
      }
      if (url === "/v1/extractors") {
        return jsonResponse([
          {
            id: "extractor_123",
            name: "receipt_v1",
            instructions: "Extract receipt fields.",
            schema: { type: "object" },
            examples: [],
            created_at: "2026-06-21T00:00:00Z",
            updated_at: "2026-06-21T00:00:00Z"
          }
        ]);
      }
      if (url === "/v1/jobs?extractor_id=extractor_123") {
        return jsonResponse([
          {
            id: "job_123",
            extractor_id: "extractor_123",
            file_id: null,
            source_text: "Corner Market",
            status: "completed",
            result: {
              data: { receipt_id: "R-42" }
            },
            error: null,
            created_at: "2026-06-21T00:00:00Z",
            started_at: "2026-06-21T00:00:01Z",
            completed_at: "2026-06-21T00:00:02Z"
          }
        ]);
      }
      if (url === "/v1/jobs/job_123" && method === "DELETE") {
        return new Response(null, { status: 204 });
      }
      return jsonResponse({ detail: "unexpected request" }, { status: 500 });
    });

    render(<App />);

    expect(await screen.findByText("Jobs")).toBeInTheDocument();
    expect(await screen.findByText("job_123")).toBeInTheDocument();
    expect((await screen.findAllByText("1s")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("tab", { name: "Raw" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Validation" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("Delete job job_123"));
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(screen.queryByText("job_123")).not.toBeInTheDocument();
    });
    expect(requests).toContainEqual({ method: "DELETE", url: "/v1/jobs/job_123" });
  });

  it("switches the input preview when selecting file and text jobs from history", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/v1/files") {
        return jsonResponse([
          {
            id: "file_123",
            file_name: "receipt.md",
            content_type: "text/markdown",
            size_bytes: 12,
            sha256: "abc",
            created_at: "2026-06-21T00:00:00Z"
          }
        ]);
      }
      if (url === "/v1/files/file_123/content") {
        return new Response("Uploaded receipt text", {
          status: 200,
          headers: { "Content-Type": "text/markdown" }
        });
      }
      if (url === "/v1/extractors") {
        return jsonResponse([
          {
            id: "extractor_123",
            name: "receipt_v1",
            instructions: "Extract receipt fields.",
            schema: { type: "object" },
            examples: [],
            created_at: "2026-06-21T00:00:00Z",
            updated_at: "2026-06-21T00:00:00Z"
          }
        ]);
      }
      if (url === "/v1/jobs?extractor_id=extractor_123") {
        return jsonResponse([
          {
            id: "job_file",
            extractor_id: "extractor_123",
            file_id: "file_123",
            source_text: null,
            status: "completed",
            result: {
              data: { receipt_id: "R-file" }
            },
            error: null,
            created_at: "2026-06-21T00:01:00Z",
            started_at: "2026-06-21T00:01:01Z",
            completed_at: "2026-06-21T00:01:02Z"
          },
          {
            id: "job_text",
            extractor_id: "extractor_123",
            file_id: null,
            source_text: "Archived inline text",
            status: "completed",
            result: {
              data: { receipt_id: "R-text" }
            },
            error: null,
            created_at: "2026-06-21T00:00:00Z",
            started_at: "2026-06-21T00:00:01Z",
            completed_at: "2026-06-21T00:00:02Z"
          }
        ]);
      }
      return jsonResponse({ detail: "unexpected request" }, { status: 500 });
    });

    render(<App />);

    expect((await screen.findAllByText("receipt.md")).length).toBeGreaterThan(0);
    expect(await screen.findByText("Uploaded receipt text")).toBeInTheDocument();

    await userEvent.click(await screen.findByText("job_text"));

    expect(await screen.findByText("Text input")).toBeInTheDocument();
    expect(screen.getAllByText("Archived inline text").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Copy receipt_id")).toBeInTheDocument();
  });
});

function jsonResponse(payload: unknown, init: ResponseInit = {}) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
      ...init
    })
  );
}
