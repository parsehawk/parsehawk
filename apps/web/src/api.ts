import type {
  Extractor,
  ExtractorExample,
  FileRecord,
  Job,
  Provider,
  ProviderConfiguration,
  ProviderName,
  SchemaValidation,
  SchemaValidationRequest
} from "./types";

async function request<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(formatApiError(body, response.status));
  }
  const body = await response.text();
  if (!body) {
    return undefined as T;
  }
  return JSON.parse(body) as T;
}

export function formatApiError(body: string, status: number): string {
  if (!body) return `Request failed with ${status}`;
  try {
    const payload = JSON.parse(body) as unknown;
    if (isRecord(payload) && typeof payload.detail === "string") {
      return payload.detail;
    }
    if (isRecord(payload) && Array.isArray(payload.detail)) {
      return payload.detail
        .map((item) => {
          if (!isRecord(item)) return String(item);
          const location = Array.isArray(item.loc) ? item.loc.filter((part) => part !== "body").join(".") : "";
          const message = typeof item.msg === "string" ? item.msg : "Invalid request";
          return location ? `${location}: ${message}` : message;
        })
        .join("; ");
    }
  } catch {
    return body;
  }
  return body;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function listFiles(): Promise<FileRecord[]> {
  return request<FileRecord[]>("/v1/files");
}

export function uploadFile(file: File): Promise<FileRecord> {
  const body = new FormData();
  body.append("upload", file);
  return request<FileRecord>("/v1/files", { method: "POST", body });
}

export function deleteFile(fileId: string): Promise<void> {
  return request<void>(`/v1/files/${fileId}`, { method: "DELETE" });
}

export async function readFilePreview(file: FileRecord): Promise<string> {
  const response = await fetch(`/v1/files/${file.id}/content`);
  if (!response.ok) {
    throw new Error(`Could not load preview for ${file.file_name}`);
  }
  return response.text();
}

export function fileContentUrl(file: FileRecord): string {
  return `/v1/files/${file.id}/content`;
}

export function listExtractors(): Promise<Extractor[]> {
  return request<Extractor[]>("/v1/extractors");
}

export function createExtractor(payload: {
  name?: string;
  display_name: string;
  instructions: string;
  enable_thinking: boolean;
  provider_name?: ProviderName;
  model?: string | null;
  schema: Record<string, unknown>;
  examples?: ExtractorExample[];
}): Promise<Extractor> {
  return request<Extractor>("/v1/extractors", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export function updateExtractor(
  extractorId: string,
  payload: {
    display_name: string;
    instructions: string;
    enable_thinking: boolean;
    provider_name?: ProviderName;
    model?: string | null;
    schema?: Record<string, unknown>;
    examples?: ExtractorExample[];
  }
): Promise<Extractor> {
  return request<Extractor>(`/v1/extractors/${extractorId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export function deleteExtractor(extractorId: string): Promise<void> {
  return request<void>(`/v1/extractors/${extractorId}`, { method: "DELETE" });
}

export function listProviders(): Promise<Provider[]> {
  return request<Provider[]>("/v1/providers");
}

export function configureProvider(
  name: ProviderName,
  payload: { base_url?: string | null; configuration?: ProviderConfiguration; api_key?: string }
): Promise<Provider> {
  return request<Provider>(`/v1/providers/${name}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function listProviderModels(name: ProviderName): Promise<string[]> {
  const response = await request<{ models: string[] }>(`/v1/providers/${name}/models`);
  return response.models;
}

export function validateSchema(payload: SchemaValidationRequest): Promise<SchemaValidation> {
  return request<SchemaValidation>("/v1/schemas/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export function createJob(
  extractorName: string,
  input: { file_id: string } | { text: string }
): Promise<Job> {
  return request<Job>("/v1/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ extractor_name: extractorName, ...input })
  });
}

export function listJobs(extractorId: string): Promise<Job[]> {
  return request<Job[]>(`/v1/jobs?extractor_id=${encodeURIComponent(extractorId)}`);
}

export function getJob(jobId: string): Promise<Job> {
  return request<Job>(`/v1/jobs/${jobId}`);
}

export function deleteJob(jobId: string): Promise<void> {
  return request<void>(`/v1/jobs/${jobId}`, { method: "DELETE" });
}
