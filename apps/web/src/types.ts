export type FileRecord = {
  id: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  created_at: string;
  source?: "user" | "example";
  is_example?: boolean;
};

export type ProviderName = "openai" | "azure_openai" | "openai_compatible_api";

export type Provider = {
  name: ProviderName;
  base_url: string | null;
  api_version: string | null;
  has_api_key: boolean;
  created_at: string;
  updated_at: string;
};

export type Extractor = {
  id: string;
  name: string;
  display_name: string;
  instructions: string;
  enable_thinking: boolean;
  provider_name: ProviderName | null;
  model: string | null;
  schema: Record<string, unknown>;
  examples: ExtractorExample[];
  created_at: string;
  updated_at: string;
  source?: "user" | "prebuilt";
  is_example?: boolean;
  is_prebuilt?: boolean;
};

export type ExtractorExampleInput =
  | {
      type: "text";
      text: string;
      file_id?: null;
    }
  | {
      type: "file";
      file_id: string;
      text?: null;
    };

export type ExtractorExample = {
  input: ExtractorExampleInput | string;
  output: Record<string, unknown> | string;
};

export type JobStatus = "queued" | "running" | "completed" | "failed" | "canceling" | "deleting" | "canceled";

export type Job = {
  id: string;
  extractor_id: string;
  file_id: string | null;
  source_text: string | null;
  status: JobStatus;
  result: null | {
    data: Record<string, unknown>;
  };
  error: null | {
    message: string;
    code: string;
  };
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type SchemaValidation = {
  valid: boolean;
  warnings: Array<{ message: string; code: string; path: string }>;
  errors: Array<{ message: string; code: string; path: string }>;
  schema: Record<string, unknown> | null;
};

export type SchemaValidationRequest = {
  schema: Record<string, unknown>;
};
