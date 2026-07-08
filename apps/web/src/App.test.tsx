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
          provider_name_used: null,
          model_used: null,
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
          display_name: "Invoice",
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
    await userEvent.type(screen.getByLabelText("Display name"), "Invoice");
    await userEvent.type(screen.getByLabelText("Instructions"), "Extract invoice fields.");
    await userEvent.click(screen.getByRole("checkbox", { name: "Enable thinking" }));
    await userEvent.click(screen.getByRole("button", { name: "Create extractor" }));

    await waitFor(() => {
      expect(createPayload?.enable_thinking).toBe(true);
    });
    expect(createPayload).not.toHaveProperty("name");
  });

  it("sends a manually edited extractor name on create", async () => {
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
          name: String(createPayload?.name),
          display_name: "Invoice",
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
    await userEvent.type(screen.getByLabelText("Display name"), "Invoice");
    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.type(screen.getByLabelText("Name"), "invoice_v1");
    await userEvent.type(screen.getByLabelText("Instructions"), "Extract invoice fields.");
    await userEvent.click(screen.getByRole("button", { name: "Create extractor" }));

    await waitFor(() => {
      expect(createPayload?.name).toBe("invoice_v1");
    });
  });

  it("allows long display names to rely on API-generated extractor names", async () => {
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
          name: "very-long-generated-name",
          display_name: createPayload?.display_name,
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
    await userEvent.type(
      screen.getByLabelText("Display name"),
      "Invoice Extractor With A Very Long Display Name That Should Still Be Saveable"
    );
    await userEvent.type(screen.getByLabelText("Instructions"), "Extract invoice fields.");
    await userEvent.click(screen.getByRole("button", { name: "Create extractor" }));

    await waitFor(() => {
      expect(createPayload).not.toHaveProperty("name");
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
          display_name: "Invoice",
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
    await userEvent.type(screen.getByLabelText("Display name"), "Invoice");
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
            provider_name_used: "openai_compatible_api",
            model_used: "numind/NuExtract3-W4A16",
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
    expect(screen.getByText("numind/NuExtract3-W4A16")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Raw" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Validation" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("Delete job job_123"));
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(screen.queryByText("job_123")).not.toBeInTheDocument();
    });
    expect(requests).toContainEqual({ method: "DELETE", url: "/v1/jobs/job_123" });
  });

  it("renders deleting jobs as active", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
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
      if (url === "/v1/jobs?extractor_id=extractor_123") {
        return jsonResponse([
          {
            id: "job_deleting",
            extractor_id: "extractor_123",
            file_id: null,
            source_text: "Corner Market",
            provider_name_used: "openai_compatible_api",
            model_used: "numind/NuExtract3-W4A16",
            status: "deleting",
            result: null,
            error: null,
            created_at: "2026-06-21T00:00:00Z",
            started_at: "2026-06-21T00:00:01Z",
            completed_at: null
          }
        ]);
      }
      return jsonResponse({ detail: "unexpected request" }, { status: 500 });
    });

    render(<App />);

    expect(await screen.findByText("Deleting")).toBeInTheDocument();
    expect(screen.getAllByText("ParseHawk is stopping and removing this job.").length).toBeGreaterThan(0);
    expect(screen.queryByText("Extraction failed")).not.toBeInTheDocument();
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
            provider_name_used: "openai_compatible_api",
            model_used: "numind/NuExtract3-W4A16",
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
            provider_name_used: "openai_compatible_api",
            model_used: "numind/NuExtract3-W4A16",
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

    const textJobRow = (await screen.findByLabelText("Copy job ID job_text")).closest("[role='button']");
    expect(textJobRow).not.toBeNull();
    await userEvent.click(textJobRow!);

    expect(await screen.findByText("Text input")).toBeInTheDocument();
    expect(screen.getAllByText("Archived inline text").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Copy receipt_id")).toBeInTheDocument();
  });

  it("sends the selected provider and model on create", async () => {
    let createPayload: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/v1/files") {
        return jsonResponse([]);
      }
      if (url.startsWith("/v1/providers/") && url.endsWith("/models")) {
        return jsonResponse({ models: ["gpt-4o-mini", "gpt-4o"] });
      }
      if (url === "/v1/extractors" && init?.method === "POST") {
        createPayload = JSON.parse(String(init.body));
        return jsonResponse({
          id: "extractor_123",
          name: "invoice",
          display_name: "Invoice",
          instructions: "Extract invoice fields.",
          enable_thinking: false,
          provider_name: createPayload?.provider_name,
          model: createPayload?.model,
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
    await userEvent.type(screen.getByLabelText("Display name"), "Invoice");
    await userEvent.type(screen.getByLabelText("Instructions"), "Extract invoice fields.");
    await userEvent.selectOptions(screen.getByLabelText("Provider"), "openai");
    await userEvent.type(screen.getByLabelText("Model"), "gpt-4o-mini");
    await userEvent.click(screen.getByRole("button", { name: "Create extractor" }));

    await waitFor(() => {
      expect(createPayload?.provider_name).toBe("openai");
      expect(createPayload?.model).toBe("gpt-4o-mini");
    });
  });

  it("sends null model to inherit the OpenAI-compatible runtime default", async () => {
    let createPayload: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/v1/files") {
        return jsonResponse([]);
      }
      if (url.startsWith("/v1/providers/") && url.endsWith("/models")) {
        return jsonResponse({ models: ["numind/NuExtract3-W4A16"] });
      }
      if (url === "/v1/extractors" && init?.method === "POST") {
        createPayload = JSON.parse(String(init.body));
        return jsonResponse({
          id: "extractor_123",
          name: "invoice",
          display_name: "Invoice",
          instructions: "Extract invoice fields.",
          enable_thinking: false,
          provider_name: "openai_compatible_api",
          model: null,
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
    expect(screen.getByPlaceholderText("Use current bundled runtime model")).toBeInTheDocument();
    expect(screen.getByText(/inherit the model selected for the bundled runtime/i)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Display name"), "Invoice");
    await userEvent.type(screen.getByLabelText("Instructions"), "Extract invoice fields.");
    await userEvent.click(screen.getByRole("button", { name: "Create extractor" }));

    await waitFor(() => {
      expect(createPayload?.provider_name).toBe("openai_compatible_api");
      expect(createPayload?.model).toBeNull();
    });
    expect(screen.getByLabelText("Model")).toHaveValue("");
  });

  it("updates the visible provider model from the saved extractor response", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/v1/files") {
        return jsonResponse([]);
      }
      if (url.startsWith("/v1/providers/") && url.endsWith("/models")) {
        return jsonResponse({ models: ["draft-model", "server-model"] });
      }
      if (url === "/v1/extractors" && init?.method === "POST") {
        const createPayload = JSON.parse(String(init.body));
        return jsonResponse({
          id: "extractor_123",
          name: "invoice",
          display_name: "Invoice",
          instructions: "Extract invoice fields.",
          enable_thinking: false,
          provider_name: createPayload.provider_name,
          model: "server-model",
          schema: createPayload.schema,
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
    await userEvent.type(screen.getByLabelText("Display name"), "Invoice");
    await userEvent.type(screen.getByLabelText("Instructions"), "Extract invoice fields.");
    await userEvent.selectOptions(screen.getByLabelText("Provider"), "openai");
    await userEvent.type(screen.getByLabelText("Model"), "draft-model");
    await userEvent.click(screen.getByRole("button", { name: "Create extractor" }));

    await waitFor(() => {
      expect(screen.getByLabelText("Model")).toHaveValue("server-model");
    });
  });

  it("hints to configure the provider but still allows manual model entry when the model list fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/v1/files") {
        return jsonResponse([]);
      }
      if (url === "/v1/extractors") {
        return jsonResponse([]);
      }
      if (url.startsWith("/v1/providers/") && url.endsWith("/models")) {
        return jsonResponse({ detail: "model provider is unreachable" }, { status: 400 });
      }
      return jsonResponse({ detail: "unexpected request" }, { status: 500 });
    });

    render(<App />);

    await userEvent.click(await screen.findByRole("button", { name: "New" }));

    expect(await screen.findByText(/leave blank to inherit the bundled runtime model/i)).toBeInTheDocument();

    const modelInput = screen.getByLabelText("Model");
    await userEvent.type(modelInput, "my-deployment");
    expect(modelInput).toHaveValue("my-deployment");
  });

  it("configures a provider without ever revealing the api key", async () => {
    let patchPayload: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/v1/files") {
        return jsonResponse([]);
      }
      if (url === "/v1/extractors") {
        return jsonResponse([]);
      }
      if (url === "/v1/providers" && method === "GET") {
        return jsonResponse([
          {
            name: "openai_compatible_api",
            base_url: "http://127.0.0.1:8080/v1",
            configuration: {},
            has_api_key: false,
            created_at: "2026-06-21T00:00:00Z",
            updated_at: "2026-06-21T00:00:00Z"
          },
          {
            name: "openai",
            base_url: "https://api.openai.com/v1",
            configuration: {},
            has_api_key: true,
            created_at: "2026-06-21T00:00:00Z",
            updated_at: "2026-06-21T00:00:00Z"
          },
          {
            name: "microsoft_foundry",
            base_url: null,
            configuration: {},
            has_api_key: false,
            created_at: "2026-06-21T00:00:00Z",
            updated_at: "2026-06-21T00:00:00Z"
          }
        ]);
      }
      if (url === "/v1/providers/openai" && method === "PATCH") {
        patchPayload = JSON.parse(String(init?.body));
        return jsonResponse({
          name: "openai",
          base_url: "https://api.openai.com/v1",
          configuration: {},
          has_api_key: true,
          created_at: "2026-06-21T00:00:00Z",
          updated_at: "2026-06-21T00:00:00Z"
        });
      }
      return jsonResponse({ detail: "unexpected request" }, { status: 500 });
    });

    render(<App />);

    await userEvent.click(await screen.findByRole("button", { name: "Configure model providers" }));

    await screen.findByText("OpenAI-compatible API");
    expect(screen.getAllByText("Configured").length).toBe(2);
    expect(screen.getAllByText("Not configured").length).toBe(1);

    // openai is the second provider in the fixed order; set a new key and save it.
    await userEvent.type(screen.getAllByLabelText("API key")[1], "sk-secret");
    await userEvent.click(screen.getAllByRole("button", { name: "Save" })[1]);

    await waitFor(() => {
      expect(patchPayload?.api_key).toBe("sk-secret");
    });
    // The key is write-only: it is cleared after saving and never rendered back.
    expect(screen.queryByDisplayValue("sk-secret")).not.toBeInTheDocument();
  });

  it("stores Microsoft Foundry project settings in provider configuration", async () => {
    let patchPayload: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/v1/files") {
        return jsonResponse([]);
      }
      if (url === "/v1/extractors") {
        return jsonResponse([]);
      }
      if (url === "/v1/providers" && method === "GET") {
        return jsonResponse([
          {
            name: "microsoft_foundry",
            base_url: "",
            configuration: {},
            has_api_key: false,
            created_at: "2026-06-21T00:00:00Z",
            updated_at: "2026-06-21T00:00:00Z"
          }
        ]);
      }
      if (url === "/v1/providers/microsoft_foundry" && method === "PATCH") {
        patchPayload = JSON.parse(String(init?.body));
        return jsonResponse({
          name: "microsoft_foundry",
          base_url: "https://resource.services.ai.azure.com/openai/v1",
          configuration: {
            project_url: "https://resource.services.ai.azure.com/api/projects/project"
          },
          has_api_key: true,
          created_at: "2026-06-21T00:00:00Z",
          updated_at: "2026-06-21T00:00:00Z"
        });
      }
      return jsonResponse({ detail: "unexpected request" }, { status: 500 });
    });

    render(<App />);

    await userEvent.click(await screen.findByRole("button", { name: "Configure model providers" }));
    expect(await screen.findByRole("dialog")).toHaveClass("sm:max-w-2xl", "lg:max-w-3xl");
    expect(screen.getByLabelText("Base URL")).toHaveAttribute(
      "placeholder",
      "https://your-resource-name.services.ai.azure.com/openai/v1"
    );
    expect(screen.getByLabelText("Base URL")).toHaveAttribute(
      "title",
      "https://your-resource-name.services.ai.azure.com/openai/v1"
    );
    expect(screen.getByLabelText("Project URL")).toHaveAttribute(
      "placeholder",
      "https://your-resource-name.services.ai.azure.com/api/projects/your-project-name"
    );
    expect(screen.getByLabelText("Project URL")).toHaveAttribute(
      "title",
      "https://your-resource-name.services.ai.azure.com/api/projects/your-project-name"
    );
    await userEvent.type(screen.getByLabelText("Base URL"), "https://resource.services.ai.azure.com/openai/v1");
    await userEvent.type(
      screen.getByLabelText("Project URL"),
      "https://resource.services.ai.azure.com/api/projects/project"
    );
    await userEvent.type(screen.getByLabelText("API key"), "sk-secret");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(patchPayload).toMatchObject({
        base_url: "https://resource.services.ai.azure.com/openai/v1",
        configuration: {
          project_url: "https://resource.services.ai.azure.com/api/projects/project"
        },
        api_key: "sk-secret"
      });
    });
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
