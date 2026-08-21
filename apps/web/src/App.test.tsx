import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
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
      if (url === "/v1/extraction-jobs?extractor_id=extractor_123" && init?.method !== "POST") {
        return jsonResponse([]);
      }
      if (url === "/v1/extraction-jobs" && init?.method === "POST") {
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

    expect(await screen.findByText("Extraction job progress")).toBeInTheDocument();
    expect(screen.getAllByText("Queued").length).toBeGreaterThan(0);
    expect(screen.queryByText("artifact_dir")).not.toBeInTheDocument();
  });

  it("renders document, per-page, and raw Markdown parse results", async () => {
    const parser = {
      id: "parser_123",
      name: "document-to-markdown",
      display_name: "Document to Markdown",
      output_format: "markdown",
      instructions: "",
      reasoning_effort: null,
      provider_name: null,
      model: null,
      source: "prebuilt",
      is_prebuilt: true,
      created_at: "2026-06-21T00:00:00Z",
      updated_at: "2026-06-21T00:00:00Z"
    };
    const content = [
      "# Invoice",
      "",
      "<figure><img src=\"img_1.png\" alt=\"Invoice logo\"></figure>",
      "",
      "**First page**",
      "",
      "[Open invoice](https://example.com/invoice)",
      "",
      "<table><tbody><tr><td>Service</td><td>€ 42</td></tr></tbody></table>",
      "",
      "<!-- page-break -->",
      "",
      "## Page two",
      "",
      "| Item | Total |",
      "| --- | ---: |",
      "| Support | € 7 |"
    ].join("\n");
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/v1/files") {
        return jsonResponse([
          {
            id: "file_123",
            file_name: "invoice.pdf",
            content_type: "application/pdf",
            size_bytes: 42,
            sha256: "abc",
            created_at: "2026-06-21T00:00:00Z"
          },
          {
            id: "file_other",
            file_name: "currently-selected.png",
            content_type: "image/png",
            size_bytes: 24,
            sha256: "def",
            created_at: "2026-06-21T00:00:00Z"
          }
        ]);
      }
      if (url === "/v1/extractors") return jsonResponse([]);
      if (url === "/v1/parsers") return jsonResponse([parser]);
      if (url === "/v1/parse-jobs?parser_id=parser_123") {
        return jsonResponse([
          {
            id: "parse_job_123",
            parser_id: parser.id,
            file_id: "file_123",
            parser_snapshot: { ...parser, parser_id: parser.id },
            provider_name_used: "openai_compatible_api",
            model_used: "numind/NuExtract3-2B",
            reasoning_effort_used: null,
            model_adapter_used: "nuextract_markdown",
            status: "completed",
            result: {
              format: "markdown",
              content,
              page_count: 2,
              pages: [
                {
                  page_number: 1,
                  content:
                    "# Invoice\n\n**First page**\n\n[Open invoice](https://example.com/invoice)\n\n<table><tbody><tr><td>Service</td><td>€ 42</td></tr></tbody></table>"
                },
                {
                  page_number: 2,
                  content: "## Page two\n\n| Item | Total |\n| --- | ---: |\n| Support | € 7 |"
                }
              ]
            },
            error: null,
            created_at: "2026-06-21T00:00:00Z",
            started_at: "2026-06-21T00:00:01Z",
            completed_at: "2026-06-21T00:00:03Z"
          }
        ]);
      }
      return jsonResponse({ detail: `unexpected request: ${url}` }, { status: 500 });
    });

    render(<App />);
    await userEvent.click(screen.getByRole("tab", { name: "Parse" }));

    await userEvent.selectOptions(
      await screen.findByRole("combobox", { name: "File" }),
      "file_other"
    );
    expect(await screen.findByRole("button", { name: "Download invoice.md" })).toBeInTheDocument();

    const documentResult = within(await screen.findByRole("tabpanel", { name: "Document" }));
    expect(documentResult.getByRole("heading", { name: "Invoice" })).toBeInTheDocument();
    expect(documentResult.getByText("Invoice logo")).toBeInTheDocument();
    expect(documentResult.queryByRole("img", { name: "Invoice logo" })).not.toBeInTheDocument();
    expect(documentResult.getByText("First page").tagName).toBe("STRONG");
    expect(documentResult.getByRole("link", { name: "Open invoice" })).toHaveAttribute(
      "href",
      "https://example.com/invoice"
    );
    expect(documentResult.getAllByRole("table")[0]).toHaveTextContent("Service€ 42");
    expect(screen.getByText("nuextract_markdown")).toBeInTheDocument();
    expect(screen.getByText("2s")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Per page (2)" }));
    await userEvent.selectOptions(screen.getByLabelText("Parsed page"), "2");
    const pageResult = within(screen.getByRole("tabpanel", { name: "Per page (2)" }));
    expect(pageResult.getByRole("heading", { name: "Page two" })).toBeInTheDocument();
    expect(pageResult.getByRole("table")).toHaveTextContent("Support€ 7");
    expect(pageResult.queryByText("First page")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Raw Markdown" }));
    expect(
      screen.getByText((_, element) => element?.tagName === "PRE" && element.textContent === content)
    ).toBeInTheDocument();
  });

  it("keeps parse history scoped to the latest selected parser", async () => {
    const parserAlpha = parserFixture("parser_alpha", "alpha", "Alpha parser");
    const parserBeta = parserFixture("parser_beta", "beta", "Beta parser");
    const fileAlpha = fileFixture("file_alpha", "alpha.png");
    const fileBeta = fileFixture("file_beta", "beta.png");
    const jobAlpha = parseJobFixture("job_alpha", parserAlpha, fileAlpha.id, "completed");
    const jobBeta = parseJobFixture("job_beta", parserBeta, fileBeta.id, "completed");
    let alphaListCalls = 0;
    let resolveStaleAlphaJobs!: (response: Response) => void;
    const staleAlphaJobs = new Promise<Response>((resolve) => {
      resolveStaleAlphaJobs = resolve;
    });

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/v1/files") return jsonResponse([fileAlpha, fileBeta]);
      if (url === "/v1/extractors") return jsonResponse([]);
      if (url === "/v1/parsers") return jsonResponse([parserAlpha, parserBeta]);
      if (url === "/v1/parse-jobs?parser_id=parser_alpha") {
        alphaListCalls += 1;
        return alphaListCalls === 1 ? jsonResponse([jobAlpha]) : staleAlphaJobs;
      }
      if (url === "/v1/parse-jobs?parser_id=parser_beta") return jsonResponse([jobBeta]);
      return jsonResponse({ detail: `unexpected request: ${url}` }, { status: 500 });
    });

    render(<App />);
    await userEvent.click(screen.getByRole("tab", { name: "Parse" }));

    expect(await screen.findByLabelText("Delete parse job job_alpha")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Refresh parse jobs"));
    await waitFor(() => expect(alphaListCalls).toBe(2));

    const betaParserCard = screen.getByText("Beta parser").closest<HTMLElement>("[role='button']");
    expect(betaParserCard).not.toBeNull();
    await userEvent.click(betaParserCard!);

    expect(await screen.findByLabelText("Delete parse job job_beta")).toBeInTheDocument();
    expect(screen.queryByLabelText("Delete parse job job_alpha")).not.toBeInTheDocument();

    await act(async () => {
      resolveStaleAlphaJobs(await jsonResponse([jobAlpha]));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(screen.getByLabelText("Delete parse job job_beta")).toBeInTheDocument();
    expect(screen.queryByLabelText("Delete parse job job_alpha")).not.toBeInTheDocument();
  });

  it("removes a running parse job after deletion is accepted", async () => {
    const parser = parserFixture("parser_123", "document-to-markdown", "Document to Markdown");
    const file = fileFixture("file_123", "page.png");
    let deleting = false;

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/v1/files") return jsonResponse([file]);
      if (url === "/v1/extractors") return jsonResponse([]);
      if (url === "/v1/parsers") return jsonResponse([parser]);
      if (url === "/v1/parse-jobs?parser_id=parser_123") {
        return jsonResponse([
          parseJobFixture("job_running", parser, file.id, deleting ? "deleting" : "running")
        ]);
      }
      if (url === "/v1/parse-jobs/job_running" && init?.method === "DELETE") {
        deleting = true;
        return new Response(null, { status: 202 });
      }
      return jsonResponse({ detail: `unexpected request: ${url}` }, { status: 500 });
    });

    render(<App />);
    await userEvent.click(screen.getByRole("tab", { name: "Parse" }));

    await userEvent.click(await screen.findByLabelText("Delete parse job job_running"));

    await waitFor(() => {
      expect(screen.queryByLabelText("Delete parse job job_running")).not.toBeInTheDocument();
    });
    expect(screen.queryByText("Parsing needs attention")).not.toBeInTheDocument();
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

  it("saves the extractor reasoning effort setting", async () => {
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
          reasoning_effort: "high",
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
    await userEvent.selectOptions(screen.getByLabelText("Reasoning effort"), "high");
    await userEvent.click(screen.getByRole("button", { name: "Create extractor" }));

    await waitFor(() => {
      expect(createPayload?.reasoning_effort).toBe("high");
    });
    expect(createPayload).not.toHaveProperty("name");
  });

  it("sends a null reasoning effort for the model default", async () => {
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
          reasoning_effort: null,
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
    await userEvent.click(screen.getByRole("button", { name: "Create extractor" }));

    await waitFor(() => {
      expect(createPayload?.reasoning_effort).toBeNull();
    });
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
          reasoning_effort: null,
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
          reasoning_effort: null,
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
          reasoning_effort: null,
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

  it("allows spaces and new lines while editing enum choices", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/v1/files" || url === "/v1/extractors") {
        return jsonResponse([]);
      }
      return jsonResponse({ detail: "unexpected request" }, { status: 500 });
    });

    render(<App />);

    await userEvent.click(await screen.findByRole("button", { name: "New" }));
    await userEvent.click(screen.getByRole("button", { name: "Add field" }));

    const enumValues = screen.getByLabelText("Enum values");
    await userEvent.type(enumValues, "Pending review{enter}Needs follow up");

    expect(enumValues).toHaveValue("Pending review\nNeeds follow up");
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
      if (url === "/v1/extraction-jobs?extractor_id=extractor_123") {
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
      if (url === "/v1/extraction-jobs?extractor_id=extractor_example") {
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
      if (url === "/v1/extraction-jobs?extractor_id=extractor_123") {
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
      if (url === "/v1/extraction-jobs/job_123" && method === "DELETE") {
        return new Response(null, { status: 204 });
      }
      return jsonResponse({ detail: "unexpected request" }, { status: 500 });
    });

    render(<App />);

    expect(await screen.findByText("Extraction jobs")).toBeInTheDocument();
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
    expect(requests).toContainEqual({ method: "DELETE", url: "/v1/extraction-jobs/job_123" });
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
      if (url === "/v1/extraction-jobs?extractor_id=extractor_123") {
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
      if (url === "/v1/extraction-jobs?extractor_id=extractor_123") {
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
          reasoning_effort: null,
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
          reasoning_effort: null,
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
          reasoning_effort: null,
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

function parserFixture(id: string, name: string, displayName: string) {
  return {
    id,
    name,
    display_name: displayName,
    output_format: "markdown",
    instructions: "",
    reasoning_effort: null,
    provider_name: null,
    model: null,
    source: "user",
    is_prebuilt: false,
    created_at: "2026-06-21T00:00:00Z",
    updated_at: "2026-06-21T00:00:00Z"
  };
}

function fileFixture(id: string, fileName: string) {
  return {
    id,
    file_name: fileName,
    content_type: "image/png",
    size_bytes: 42,
    sha256: `${id}-sha`,
    created_at: "2026-06-21T00:00:00Z"
  };
}

function parseJobFixture(
  id: string,
  parser: ReturnType<typeof parserFixture>,
  fileId: string,
  status: "queued" | "running" | "canceling" | "deleting" | "canceled" | "completed" | "failed"
) {
  const completed = status === "completed";
  return {
    id,
    parser_id: parser.id,
    file_id: fileId,
    parser_snapshot: { ...parser, parser_id: parser.id },
    provider_name_used: completed ? "openai_compatible_api" : null,
    model_used: completed ? "numind/NuExtract3-W4A16" : null,
    reasoning_effort_used: null,
    model_adapter_used: completed ? "nuextract_markdown" : null,
    status,
    result: completed
      ? {
          format: "markdown",
          content: "# Parsed",
          page_count: 1,
          pages: [{ page_number: 1, content: "# Parsed" }]
        }
      : null,
    error: null,
    created_at: "2026-06-21T00:00:00Z",
    started_at: status === "queued" ? null : "2026-06-21T00:00:01Z",
    completed_at: completed ? "2026-06-21T00:00:02Z" : null
  };
}
