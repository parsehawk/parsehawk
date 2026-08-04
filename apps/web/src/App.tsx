import { useEffect, useMemo, useRef, useState } from "react";
import type { ClipboardEvent, ComponentType, ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import {
  AlertCircle,
  ArrowLeft,
  Braces,
  Check,
  CheckCircle2,
  CircleX,
  Clock3,
  Copy,
  Download,
  Eye,
  FileImage,
  FileJson,
  FileText,
  HelpCircle,
  LayoutTemplate,
  Loader2,
  Moon,
  Pencil,
  PlayCircle,
  Plus,
  RefreshCw,
  Settings,
  Sun,
  Trash2,
  UploadCloud
} from "lucide-react";

import {
  configureProvider,
  cancelParseJob,
  createExtractor,
  createExtractionJob,
  createParseJob,
  createParser,
  deleteExtractor,
  deleteParseJob,
  deleteParser,
  deleteFile,
  deleteExtractionJob,
  fileContentUrl,
  getExtractionJob,
  getParseJob,
  listExtractors,
  listFiles,
  listExtractionJobs,
  listParseJobs,
  listParsers,
  listProviderModels,
  listProviders,
  readFilePreview,
  updateExtractor,
  updateParser,
  uploadFile,
  validateSchema
} from "./api";
import logo from "./assets/logo.svg";
import logoDark from "./assets/logo-dark.svg";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOptGroup, NativeSelectOption } from "@/components/ui/native-select";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import {
  examplesDraftFingerprint,
  examplesFromExtractor,
  examplesToPayload,
  newEditableExample,
  type EditableExample
} from "./examples";
import { parseJsonObject, prettyJson } from "./schema";
import {
  field,
  fieldSchemaFromFields,
  fieldsFromSchema,
  nuextractTypeGroups,
  nuextractTypeMetadata,
  nuextractTypeOptions,
  schemaFromFields
} from "./schemaBuilder";
import type { SchemaField, ValidationPreset } from "./schemaBuilder";
import type {
  Extractor,
  FileRecord,
  ExtractionJob,
  JobStatus,
  ParseJob,
  Parser,
  Provider,
  ProviderName,
  ReasoningEffort,
  SchemaValidation,
  SchemaValidationRequest
} from "./types";

const terminalStates = new Set(["completed", "failed", "canceled"]);
const activeStates = new Set<JobStatus>(["running", "canceling", "deleting"]);
const FILE_UPLOAD_CONCURRENCY = 3;
type SchemaMode = "builder" | "json";
type MainView = "run" | "editor";
type RunInputMode = "file" | "text";
type Workflow = "extract" | "parse";
type ParseResultView = "document" | "pages" | "raw";
type UploadProgressState = { total: number; completed: number; failed: number };

// Fixed set of providers, in the order they are shown. Names come from the
// backend ProviderName enum; the label is the human-readable UI text.
const PROVIDERS: { name: ProviderName; label: string }[] = [
  { name: "openai_compatible_api", label: "OpenAI-compatible API" },
  { name: "openai", label: "OpenAI" },
  { name: "microsoft_foundry", label: "Microsoft Foundry" }
];
const DEFAULT_PROVIDER_NAME: ProviderName = "openai_compatible_api";
// "" is the UI spelling for null: use the model's own default reasoning.
const REASONING_EFFORT_OPTIONS: { value: ReasoningEffort | ""; label: string }[] = [
  { value: "", label: "Model default" },
  { value: "none", label: "None" },
  { value: "minimal", label: "Minimal" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "xhigh", label: "Extra high" }
];
const FOUNDRY_BASE_URL_PLACEHOLDER = "https://your-resource-name.services.ai.azure.com/openai/v1";
const FOUNDRY_PROJECT_URL_PLACEHOLDER =
  "https://your-resource-name.services.ai.azure.com/api/projects/your-project-name";
const providerLabel = (name: ProviderName): string =>
  PROVIDERS.find((provider) => provider.name === name)?.label ?? name;
const providerModelPlaceholder = (name: ProviderName): string => {
  if (name === "openai_compatible_api") return "Use current bundled runtime model";
  if (name === "microsoft_foundry") return "your-chat-deployment-name";
  return "gpt-4o-mini";
};
const providerModelDescription = (name: ProviderName, hasProviderModelsError: boolean): string => {
  if (hasProviderModelsError) {
    return name === "openai_compatible_api"
      ? "Couldn't load models — leave blank to inherit the bundled runtime model, or type one manually."
      : "Couldn't load models — configure this provider first, or type the model name.";
  }
  if (name === "openai_compatible_api") {
    return "Leave blank to inherit the model selected for the bundled runtime.";
  }
  if (name === "microsoft_foundry") {
    return "Enter a chat-completions deployment name.";
  }
  return "Pick a suggested model or type one manually.";
};

const emptyExtractorName = "";
const emptyDisplayName = "";
const emptyInstructions = "";
const emptySchema = schemaFromFields([]);

export default function App() {
  const [workflow, setWorkflow] = useState<Workflow>("extract");
  const [files, setFiles] = useState<FileRecord[]>([]);
  const [extractors, setExtractors] = useState<Extractor[]>([]);
  const [selectedFileIds, setSelectedFileIds] = useState<string[]>([]);
  const [confirmDeleteFiles, setConfirmDeleteFiles] = useState(false);
  const [confirmDeleteExtractor, setConfirmDeleteExtractor] = useState(false);
  const [selectedExtractorId, setSelectedExtractorId] = useState<string>("");
  const [mainView, setMainView] = useState<MainView>("run");
  const [schemaMode, setSchemaMode] = useState<SchemaMode>("builder");
  const [schemaFields, setSchemaFields] = useState<SchemaField[]>([]);
  const [schemaText, setSchemaText] = useState(prettyJson(emptySchema));
  const [draftExtractorId, setDraftExtractorId] = useState<string | null>(null);
  const [name, setName] = useState(emptyExtractorName);
  const [nameManuallyEdited, setNameManuallyEdited] = useState(false);
  const [displayName, setDisplayName] = useState(emptyDisplayName);
  const [instructions, setInstructions] = useState(emptyInstructions);
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort | "">("");
  const [providerName, setProviderName] = useState<ProviderName>(DEFAULT_PROVIDER_NAME);
  const [model, setModel] = useState("");
  const [providerModels, setProviderModels] = useState<string[]>([]);
  const [providerModelsError, setProviderModelsError] = useState(false);
  const [examples, setExamples] = useState<EditableExample[]>([]);
  const [savedExtractorDraft, setSavedExtractorDraft] = useState(() =>
    extractorDraftSnapshot({
      name: emptyExtractorName,
      displayName: emptyDisplayName,
      instructions: emptyInstructions,
      reasoningEffort: "",
      providerName: DEFAULT_PROVIDER_NAME,
      model: "",
      schemaText: prettyJson(fieldSchemaFromFields([])),
      examplesText: prettyJson([])
    })
  );
  const [schemaValidation, setSchemaValidation] = useState<SchemaValidation | null>(null);
  const [preview, setPreview] = useState("");
  const [runInputMode, setRunInputMode] = useState<RunInputMode>("file");
  const [runText, setRunText] = useState(
    "Corner Market\nReceipt #R-42\nDate: 2026-06-21\nTotal EUR 12.40"
  );
  const [job, setJob] = useState<ExtractionJob | null>(null);
  const [jobs, setJobs] = useState<ExtractionJob[]>([]);
  const [uploadProgress, setUploadProgress] = useState<UploadProgressState | null>(null);
  const [runProgress, setRunProgress] = useState<UploadProgressState | null>(null);
  const [, setMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [pendingLeave, setPendingLeave] = useState<null | (() => void)>(null);

  const jobFileId = job?.file_id ?? "";
  const jobFile = useMemo(
    () => files.find((fileRecord) => fileRecord.id === jobFileId) ?? null,
    [files, jobFileId]
  );
  const jobFileMissing = Boolean(jobFileId) && !jobFile;
  const selectedFiles = useMemo(
    () => selectedFileIds.map((id) => files.find((fileRecord) => fileRecord.id === id)).filter((file): file is FileRecord => file != null),
    [files, selectedFileIds]
  );
  const deletableSelectedFiles = useMemo(
    () => selectedFiles.filter((file) => !isExampleFile(file)),
    [selectedFiles]
  );
  const selectedExtractor = useMemo(
    () => extractors.find((extractor) => extractor.id === selectedExtractorId) ?? null,
    [extractors, selectedExtractorId]
  );
  const draftExtractor = useMemo(
    () => extractors.find((extractor) => extractor.id === draftExtractorId) ?? null,
    [draftExtractorId, extractors]
  );
  const draftExtractorIsPrebuilt = draftExtractor ? isPrebuiltExtractor(draftExtractor) : false;
  const schemaDraftText = schemaDraftFingerprint(schemaMode, schemaFields, schemaText);
  const extractorDraft = extractorDraftSnapshot({
    name,
    displayName,
    instructions,
    reasoningEffort,
    providerName,
    model,
    schemaText: schemaDraftText,
    examplesText: examplesDraftFingerprint(examples)
  });
  const hasUnsavedExtractorChanges = extractorDraft !== savedExtractorDraft;

  const sourceReady =
    runInputMode === "file" ? selectedFileIds.length > 0 : runText.trim().length > 0;
  const extractorReady = Boolean(selectedExtractor);
  const runReady = sourceReady && extractorReady;

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [mainView]);

  // Populate the model suggestions from the selected provider while the editor
  // is open. An unconfigured/unreachable provider returns HTTP 400, so we clear
  // the list and flag the error to hint the user without blocking manual entry.
  useEffect(() => {
    if (mainView !== "editor") return;
    let cancelled = false;
    setProviderModelsError(false);
    listProviderModels(providerName)
      .then((models) => {
        if (!cancelled) setProviderModels(models);
      })
      .catch(() => {
        if (!cancelled) {
          setProviderModels([]);
          setProviderModelsError(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [mainView, providerName]);

  useEffect(() => {
    if (!jobFile) {
      setPreview("");
      return;
    }
    if (isPdf(jobFile)) {
      setPreview("");
      return;
    }
    if (isImage(jobFile)) {
      setPreview("");
      return;
    }
    readFilePreview(jobFile).then(setPreview).catch((error) => showError(error));
  }, [jobFile]);

  useEffect(() => {
    if (!job) return;
    if (terminalStates.has(job.status)) {
      setMessage(`Extraction job ${job.status}`);
      return;
    }
    const timer = window.setInterval(() => {
      getExtractionJob(job.id)
        .then((nextJob) => {
          setJob(nextJob);
          setJobs((current) => upsertJob(current, nextJob));
        })
        .catch((error) => showError(error));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [job]);

  useEffect(() => {
    if (!selectedExtractorId) {
      setJobs([]);
      setJob(null);
      return;
    }
    void refreshJobs(selectedExtractorId);
  }, [selectedExtractorId]);

  async function refresh() {
    try {
      const [nextFiles, nextExtractors] = await Promise.all([listFiles(), listExtractors()]);
      setFiles(nextFiles);
      setExtractors(nextExtractors);
      setSelectedFileIds((current) => {
        const availableIds = nextFiles.map((fileRecord) => fileRecord.id);
        return current.filter((id) => availableIds.includes(id));
      });
      setSelectedExtractorId((current) => keepSelection(current, nextExtractors.map((extractor) => extractor.id)));
      setErrorMessage("");
    } catch (error) {
      showError(error);
    }
  }

  async function refreshJobs(extractorId = selectedExtractorId) {
    if (!extractorId) {
      setJobs([]);
      setJob(null);
      return;
    }
    try {
      const nextJobs = sortJobs(await listExtractionJobs(extractorId));
      setJobs(nextJobs);
      setJob((current) => {
        if (current?.extractor_id === extractorId) {
          return nextJobs.find((nextJob) => nextJob.id === current.id) ?? current;
        }
        return nextJobs[0] ?? null;
      });
      setErrorMessage("");
    } catch (error) {
      showError(error);
    }
  }

  async function onUpload(filesToUpload: File[]) {
    const filesToUploadList = Array.from(filesToUpload);
    if (filesToUploadList.length === 0) return;
    try {
      setUploadProgress({ total: filesToUploadList.length, completed: 0, failed: 0 });
      setMessage(
        filesToUploadList.length === 1
          ? "Uploading file..."
          : `Uploading ${filesToUploadList.length} files...`
      );
      const result = await uploadFilesWithConcurrency(
        filesToUploadList,
        FILE_UPLOAD_CONCURRENCY,
        setUploadProgress
      );
      await refresh();
      if (result.uploaded.length > 0) {
        setSelectedFileIds(result.uploaded.map((file) => file.id));
      }
      if (result.failures.length > 0) {
        setMessage(`Uploaded ${result.uploaded.length} of ${filesToUploadList.length} files`);
        setErrorMessage(uploadFailuresMessage(result.failures));
      } else {
        setMessage(
          result.uploaded.length === 1
            ? `Uploaded ${result.uploaded[0].file_name}`
            : `Uploaded ${result.uploaded.length} files`
        );
        setErrorMessage("");
      }
    } catch (error) {
      showError(error);
    } finally {
      setUploadProgress(null);
    }
  }

  async function onDeleteSelectedFiles() {
    if (deletableSelectedFiles.length === 0) {
      return;
    }
    const deletedIds = deletableSelectedFiles.map((file) => file.id);
    try {
      for (const fileId of deletedIds) {
        await deleteFile(fileId);
      }
      setSelectedFileIds((current) => current.filter((id) => !deletedIds.includes(id)));
      await refresh();
      setMessage(deletedIds.length === 1 ? "File deleted" : `${deletedIds.length} files deleted`);
    } catch (error) {
      showError(error);
    } finally {
      setConfirmDeleteFiles(false);
    }
  }

  async function onValidateSchema() {
    try {
      const validation = await validateSchema(currentSchemaValidationRequest());
      setSchemaValidation(validation);
      applyValidationArtifacts(validation);
      setErrorMessage("");
    } catch (error) {
      setSchemaValidation({
        valid: false,
        warnings: [],
        errors: [{ message: error instanceof Error ? error.message : "Something went wrong", code: "request_failed", path: "" }],
        schema: null,
      });
    }
  }

  async function onSaveExtractor() {
    if (draftExtractorIsPrebuilt) {
      setMessage("Prebuilt extractors are read-only. Create a new extractor for your own version.");
      return;
    }
    try {
      const payload = currentExtractorPayload();
      const extractor = draftExtractorId
        ? await updateExtractor(draftExtractorId, payload)
        : await createExtractor(payload);
      setName(extractor.name);
      setDisplayName(extractorLabel(extractor));
      setNameManuallyEdited(false);
      setProviderName(extractor.provider_name ?? DEFAULT_PROVIDER_NAME);
      setModel(extractor.model ?? "");
      applyExtractorArtifacts(extractor);
      setDraftExtractorId(extractor.id);
      await refresh();
      setSelectedExtractorId(extractor.id);
      setMessage(`${draftExtractorId ? "Updated" : "Created"} extractor ${extractorLabel(extractor)}`);
      setErrorMessage("");
    } catch (error) {
      showError(error);
    }
  }

  async function onDeleteExtractor(extractorId: string) {
    const target = extractors.find((extractor) => extractor.id === extractorId);
    if (target && isPrebuiltExtractor(target)) {
      setMessage("Prebuilt extractors are read-only and cannot be deleted.");
      return;
    }
    try {
      await deleteExtractor(extractorId);
      if (draftExtractorId === extractorId) {
        resetExtractorDraft();
        setMainView("run");
      }
      setSelectedExtractorId((current) => (current === extractorId ? "" : current));
      setConfirmDeleteExtractor(false);
      await refresh();
      setMessage("Extractor deleted");
      setErrorMessage("");
    } catch (error) {
      showError(error);
    }
  }

  async function onRunJob() {
    if (!selectedExtractor) {
      setMessage("Select an extractor first");
      return;
    }
    if (runInputMode === "file" && selectedFileIds.length === 0) {
      setMessage("Select a file first");
      return;
    }
    if (runInputMode === "text" && !runText.trim()) {
      setMessage("Enter text first");
      return;
    }
    if (runInputMode === "text") {
      try {
        setMessage("Starting extraction job...");
        const created = await createExtractionJob(selectedExtractor.name, { text: runText });
        setJob(created);
        setJobs((current) => upsertJob(current, created));
        setMessage(`Extraction job ${created.id} queued`);
        setErrorMessage("");
      } catch (error) {
        showError(error);
      }
      return;
    }
    const fileIds = selectedFileIds;
    try {
      setRunProgress({ total: fileIds.length, completed: 0, failed: 0 });
      setMessage(fileIds.length === 1 ? "Starting extraction job..." : `Queuing ${fileIds.length} jobs...`);
      // Create jobs sequentially: the API persists to a single shared SQLite
      // connection, so firing the inserts concurrently races and drops one.
      const created: ExtractionJob[] = [];
      let firstError: unknown = null;
      for (const fileId of fileIds) {
        try {
          const job = await createExtractionJob(selectedExtractor.name, { file_id: fileId });
          created.push(job);
        } catch (error) {
          firstError ??= error;
        }
        setRunProgress({ total: fileIds.length, completed: created.length, failed: 0 });
      }
      const failed = fileIds.length - created.length;
      if (created.length > 0) {
        setJobs((current) => created.reduce((acc, nextJob) => upsertJob(acc, nextJob), current));
        setJob(created[0]);
      }
      setRunProgress({ total: fileIds.length, completed: created.length, failed });
      if (failed > 0) {
        const detail = firstError instanceof Error ? `: ${firstError.message}` : "";
        setMessage(`Queued ${created.length} of ${fileIds.length} jobs`);
        setErrorMessage(`${failed} job${failed === 1 ? "" : "s"} failed to start${detail}`);
      } else {
        setMessage(created.length === 1 ? `Extraction job ${created[0].id} queued` : `Queued ${created.length} extraction jobs`);
        setErrorMessage("");
      }
    } catch (error) {
      showError(error);
    } finally {
      setRunProgress(null);
    }
  }

  async function onDeleteJob(jobId: string) {
    try {
      await deleteExtractionJob(jobId);
      const nextJobs = jobs.filter((nextJob) => nextJob.id !== jobId);
      setJobs(nextJobs);
      setJob((current) => (current?.id === jobId ? (nextJobs[0] ?? null) : current));
      setMessage("Extraction job deleted");
      setErrorMessage("");
    } catch (error) {
      showError(error);
    }
  }

  function selectJob(nextJob: ExtractionJob) {
    setJob(nextJob);
  }

  function currentSchemaValidationRequest(): SchemaValidationRequest {
    return { schema: jsonSchemaFromCurrentDraft() };
  }

  function currentExtractorPayload() {
    const trimmedModel = model.trim();
    const base = {
      display_name: displayName,
      instructions,
      reasoning_effort: reasoningEffort || null,
      provider_name: providerName,
      model: trimmedModel || null,
      examples: examplesToPayload(examples)
    };
    const payload = draftExtractorId || !nameManuallyEdited ? base : { ...base, name };
    if (schemaMode === "json") {
      return { ...payload, schema: parseJsonObject(schemaText) };
    }
    return { ...payload, schema: schemaFromFields(schemaFields) };
  }

  function switchSchemaMode(nextMode: SchemaMode) {
    try {
      if (nextMode === "json") {
        setSchemaText(prettyJson(jsonSchemaFromCurrentDraft()));
      } else if (schemaMode === "json") {
        setSchemaFields(fieldsFromSchema(parseJsonObject(schemaText)));
      }
      setSchemaMode(nextMode);
      setErrorMessage("");
    } catch (error) {
      showError(error);
    }
  }

  function updateField(fieldId: string, patch: Partial<SchemaField>) {
    setSchemaFields((current) => updateSchemaFieldTree(current, fieldId, patch));
  }

  function addChildField(parentId: string) {
    setSchemaFields((current) => addSchemaChildField(current, parentId));
  }

  function removeField(fieldId: string) {
    setSchemaFields((current) => removeSchemaFieldTree(current, fieldId));
  }

  function updateExample(exampleId: string, patch: Partial<EditableExample>) {
    setExamples((current) => current.map((example) => (example.id === exampleId ? { ...example, ...patch } : example)));
  }

  function addExample(inputType: EditableExample["inputType"] = "text") {
    setExamples((current) => [...current, newEditableExample(inputType)]);
  }

  function removeExample(exampleId: string) {
    setExamples((current) => current.filter((example) => example.id !== exampleId));
  }

  function loadExtractor(extractor: Extractor) {
    setDraftExtractorId(extractor.id);
    setName(extractor.name);
    setNameManuallyEdited(false);
    setDisplayName(extractorLabel(extractor));
    setInstructions(extractor.instructions);
    setReasoningEffort(extractor.reasoning_effort ?? "");
    setProviderName(extractor.provider_name ?? DEFAULT_PROVIDER_NAME);
    setModel(extractor.model ?? "");
    applyExtractorArtifacts(extractor);
    setSchemaMode("builder");
    setSchemaValidation(null);
    setMessage(`${isPrebuiltExtractor(extractor) ? "Viewing" : "Editing"} extractor ${extractorLabel(extractor)}`);
    setErrorMessage("");
  }

  function resetExtractorDraft() {
    const nextSchemaFields: SchemaField[] = [];
    const nextSchemaText = prettyJson(schemaFromFields(nextSchemaFields));
    const nextExamples: EditableExample[] = [];
    setDraftExtractorId(null);
    setName(emptyExtractorName);
    setNameManuallyEdited(false);
    setDisplayName(emptyDisplayName);
    setInstructions(emptyInstructions);
    setReasoningEffort("");
    setProviderName(DEFAULT_PROVIDER_NAME);
    setModel("");
    setExamples(nextExamples);
    setSchemaFields(nextSchemaFields);
    setSchemaText(nextSchemaText);
    setSchemaMode("builder");
    setSchemaValidation(null);
    setSavedExtractorDraft(
      extractorDraftSnapshot({
        name: emptyExtractorName,
        displayName: emptyDisplayName,
        instructions: emptyInstructions,
        reasoningEffort: "",
        providerName: DEFAULT_PROVIDER_NAME,
        model: "",
        schemaText: prettyJson(fieldSchemaFromFields(nextSchemaFields)),
        examplesText: examplesDraftFingerprint(nextExamples)
      })
    );
    setMessage("New extractor draft");
    setErrorMessage("");
  }

  function showError(error: unknown) {
    setErrorMessage(error instanceof Error ? error.message : "Something went wrong");
  }

  function applyValidationArtifacts(validation: SchemaValidation) {
    if (validation.schema) {
      setSchemaFields(fieldsFromSchema(validation.schema));
      setSchemaText(prettyJson(validation.schema));
    }
  }

  function applyExtractorArtifacts(extractor: Extractor) {
    const nextSchemaText = prettyJson(extractor.schema);
    const nextFields = fieldsFromSchema(extractor.schema);
    const nextExamples = examplesFromExtractor(extractor);
    setSchemaText(nextSchemaText);
    setSchemaFields(nextFields);
    setExamples(nextExamples);
    setSavedExtractorDraft(
      extractorDraftSnapshot({
        name: extractor.name,
        displayName: extractorLabel(extractor),
        instructions: extractor.instructions,
        reasoningEffort: extractor.reasoning_effort ?? "",
        providerName: extractor.provider_name ?? DEFAULT_PROVIDER_NAME,
        model: extractor.model ?? "",
        schemaText: prettyJson(fieldSchemaFromFields(nextFields)),
        examplesText: examplesDraftFingerprint(nextExamples)
      })
    );
  }

  function jsonSchemaFromCurrentDraft(): Record<string, unknown> {
    if (schemaMode === "json") return parseJsonObject(schemaText);
    return schemaFromFields(schemaFields);
  }

  function leaveEditor(proceed: () => void) {
    if (hasUnsavedExtractorChanges && !draftExtractorIsPrebuilt) {
      setPendingLeave(() => proceed);
      return;
    }
    proceed();
  }

  return (
    <TooltipProvider>
      <div className="min-h-screen bg-background">
        <header className="sticky top-0 z-50 border-b bg-background">
          <div className="mx-auto flex max-w-[1500px] items-center justify-between gap-4 px-5 py-2.5 lg:px-8">
            <div className="flex items-center gap-3">
              <img src={logo} alt="ParseHawk" className="h-12 w-auto dark:hidden" />
              <img src={logoDark} alt="ParseHawk" className="hidden h-12 w-auto dark:block" />
            </div>
            <Tabs
              value={workflow}
              onValueChange={(value) => setWorkflow(value as Workflow)}
              aria-label="Document workflow"
            >
              <TabsList>
                <TabsTrigger value="extract">Extract</TabsTrigger>
                <TabsTrigger value="parse">Parse</TabsTrigger>
              </TabsList>
            </Tabs>
            <div className="flex items-center gap-1">
              <ProvidersDialog />
              <HelpDialog />
              <ThemeToggle />
            </div>
          </div>
        </header>

        {workflow === "parse" ? (
          <ParseWorkspace />
        ) : (
        <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-5 px-5 py-6 lg:flex-row lg:items-start lg:gap-6 lg:px-8">
          {mainView === "editor" ? null : (
            <aside className="flex w-full shrink-0 flex-col gap-4 lg:sticky lg:top-21 lg:w-[340px]">
              <Card>
                <CardHeader>
                  <CardTitle>Files</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-4">
                  <UploadCard onUpload={onUpload} uploadProgress={uploadProgress} />
                  {files.length > 0 ? (
                    <div className="overflow-hidden rounded-xl border">
                      <div className="flex flex-col gap-1.5 border-b bg-muted/30 px-3 py-2">
                        <div className="flex items-center gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2"
                            disabled={selectedFileIds.length === files.length}
                            onClick={() => setSelectedFileIds(files.map((file) => file.id))}
                          >
                            Select all
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2"
                            disabled={selectedFileIds.length === 0}
                            onClick={() => setSelectedFileIds([])}
                          >
                            Clear
                          </Button>
                          <div className="ml-auto flex items-center gap-0.5">
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="icon-sm"
                                  className="size-7"
                                  aria-label="Delete selected files"
                                  disabled={deletableSelectedFiles.length === 0}
                                  onClick={() => setConfirmDeleteFiles(true)}
                                >
                                  <Trash2 />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Delete selected</TooltipContent>
                            </Tooltip>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="icon-sm"
                                  className="size-7"
                                  aria-label="Refresh files"
                                  onClick={() => void refresh()}
                                >
                                  <RefreshCw />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Refresh</TooltipContent>
                            </Tooltip>
                          </div>
                        </div>

                      </div>
                      <FileList
                        files={files}
                        selectedFileIds={selectedFileIds}
                        onToggle={(fileId) =>
                          setSelectedFileIds((current) =>
                            current.includes(fileId)
                              ? current.filter((id) => id !== fileId)
                              : [...current, fileId]
                          )
                        }
                      />
                    </div>
                  ) : null}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Extractors</CardTitle>
                  <CardDescription>Build your custom extractor or select a prebuilt one.</CardDescription>
                  <CardAction>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        resetExtractorDraft();
                        setMainView("editor");
                      }}
                    >
                      <Plus data-icon="inline-start" />
                      New
                    </Button>
                  </CardAction>
                </CardHeader>
                <CardContent>
                  <ExtractorList
                    extractors={extractors}
                    selectedExtractorId={selectedExtractorId}
                    onEdit={(extractor) => {
                      loadExtractor(extractor);
                      setMainView("editor");
                    }}
                    onSelect={setSelectedExtractorId}
                  />
                </CardContent>
              </Card>
            </aside>
          )}

          <main className="flex min-w-0 flex-1 flex-col gap-5">
            {errorMessage ? (
              <Alert variant="destructive">
                <AlertCircle />
                <AlertTitle>Something needs attention</AlertTitle>
                <AlertDescription>{errorMessage}</AlertDescription>
              </Alert>
            ) : null}

            {mainView === "editor" ? (
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Back"
                      className="-ml-1"
                      onClick={() => leaveEditor(() => setMainView("run"))}
                    >
                      <ArrowLeft />
                    </Button>
                    {draftExtractorIsPrebuilt ? "View extractor" : draftExtractorId ? "Edit extractor" : "Create extractor"}
                  </CardTitle>
                  {draftExtractorIsPrebuilt ? (
                    <CardDescription>
                      This prebuilt extractor is seeded by ParseHawk and cannot be modified.
                    </CardDescription>
                  ) : null}
                  <CardAction>
                    <Badge
                      variant="outline"
                      className={cn(!(hasUnsavedExtractorChanges && !draftExtractorIsPrebuilt) && "invisible")}
                    >
                      Unsaved
                    </Badge>
                  </CardAction>
                </CardHeader>
                <CardContent className="flex flex-col gap-5">
                  <FieldGroup className="grid gap-4 lg:grid-cols-[320px_320px_minmax(0,1fr)]">
                    <Field>
                      <FieldLabel htmlFor="extractor-display-name">Display name</FieldLabel>
                      <Input
                        id="extractor-display-name"
                        value={displayName}
                        placeholder="Invoice Extractor"
                        disabled={draftExtractorIsPrebuilt}
                        onChange={(event) => {
                          const nextDisplayName = event.target.value;
                          setDisplayName(nextDisplayName);
                          if (!draftExtractorId && !nameManuallyEdited) {
                            setName(slugifyExtractorName(nextDisplayName));
                          }
                        }}
                      />
                      <FieldDescription>Human-readable label shown in the UI. You can change it later.</FieldDescription>
                    </Field>
                    <Field>
                      <FieldLabel htmlFor="extractor-name">Name</FieldLabel>
                      <Input
                        id="extractor-name"
                        value={name}
                        placeholder="invoice_v1"
                        maxLength={64}
                        disabled={draftExtractorIsPrebuilt || Boolean(draftExtractorId)}
                        onChange={(event) => {
                          setNameManuallyEdited(true);
                          setName(event.target.value);
                        }}
                      />
                      <FieldDescription>Stable API name used in requests and CLI commands. It is set on create and cannot be changed later.</FieldDescription>
                      {name && !isValidExtractorName(name) ? (
                        <FieldDescription>Use lowercase letters, digits, hyphen, or underscore; start and end with a letter or digit. The extractor_ prefix is reserved.</FieldDescription>
                      ) : name.length >= 64 ? (
                        <FieldDescription>Maximum of 64 characters reached.</FieldDescription>
                      ) : null}
                    </Field>
                    <Field>
                      <FieldLabel htmlFor="extractor-instructions">Instructions</FieldLabel>
                      <Textarea
                        id="extractor-instructions"
                        value={instructions}
                        placeholder="Extract the fields exactly as they appear in the document."
                        disabled={draftExtractorIsPrebuilt}
                        onChange={(event) => setInstructions(event.target.value)}
                        rows={4}
                      />
                    </Field>
                    <Field>
                      <FieldLabel htmlFor="extractor-provider">Provider</FieldLabel>
                      <NativeSelect
                        id="extractor-provider"
                        value={providerName}
                        disabled={draftExtractorIsPrebuilt}
                        onChange={(event) => {
                          setProviderName(event.target.value as ProviderName);
                          setModel("");
                        }}
                      >
                        {PROVIDERS.map((provider) => (
                          <NativeSelectOption key={provider.name} value={provider.name}>
                            {provider.label}
                          </NativeSelectOption>
                        ))}
                      </NativeSelect>
                      <FieldDescription>The model provider this extractor runs against.</FieldDescription>
                    </Field>
                    <Field>
                      <FieldLabel htmlFor="extractor-model">Model</FieldLabel>
                      <Input
                        id="extractor-model"
                        value={model}
                        list="extractor-model-options"
                        placeholder={providerModelPlaceholder(providerName)}
                        disabled={draftExtractorIsPrebuilt}
                        onChange={(event) => setModel(event.target.value)}
                      />
                      <datalist id="extractor-model-options">
                        {providerModels.map((modelName) => (
                          <option key={modelName} value={modelName} />
                        ))}
                      </datalist>
                      <FieldDescription>
                        {providerModelDescription(providerName, providerModelsError)}
                      </FieldDescription>
                    </Field>
                    <Field>
                      <FieldLabel htmlFor="extractor-reasoning-effort">
                        Reasoning effort
                      </FieldLabel>
                      <NativeSelect
                        id="extractor-reasoning-effort"
                        value={reasoningEffort}
                        disabled={draftExtractorIsPrebuilt}
                        onChange={(event) =>
                          setReasoningEffort(event.target.value as ReasoningEffort | "")
                        }
                      >
                        {REASONING_EFFORT_OPTIONS.map((option) => (
                          <NativeSelectOption key={option.value} value={option.value}>
                            {option.label}
                          </NativeSelectOption>
                        ))}
                      </NativeSelect>
                      <FieldDescription>
                        How much the model reasons before answering. Model default sends no
                        reasoning parameter; models that do not support the selected level fail
                        at extraction time with the provider&apos;s error.
                      </FieldDescription>
                    </Field>
                  </FieldGroup>

                  <Separator />

                  <Tabs value={schemaMode} onValueChange={(value) => switchSchemaMode(value as SchemaMode)}>
                    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                      <TabsList>
                        <TabsTrigger value="builder">Builder</TabsTrigger>
                        <TabsTrigger value="json">json schema</TabsTrigger>
                      </TabsList>
                      {schemaMode === "builder" ? (
                        <Button
                          variant="outline"
                          disabled={draftExtractorIsPrebuilt}
                          onClick={() => setSchemaFields((current) => [...current, field({ name: `field_${current.length + 1}` })])}
                        >
                          <Plus data-icon="inline-start" />
                          Add field
                        </Button>
                      ) : null}
                    </div>
                    <TabsContent value="builder">
                      <SchemaBuilder
                        fields={schemaFields}
                        onAddChild={addChildField}
                        onChange={updateField}
                        onRemove={removeField}
                        readOnly={draftExtractorIsPrebuilt}
                      />
                    </TabsContent>
                    <TabsContent value="json">
                      <JsonEditor value={schemaText} onChange={setSchemaText} readOnly={draftExtractorIsPrebuilt} />
                    </TabsContent>
                  </Tabs>

                  {draftExtractorIsPrebuilt ? null : (
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                      <Button variant="outline" className="sm:self-start" onClick={() => void onValidateSchema()}>
                        <Braces data-icon="inline-start" />
                        Validate schema
                      </Button>
                      {schemaValidation ? (
                        <div className="min-w-0 flex-1">
                          <SchemaValidationPanel validation={schemaValidation} />
                        </div>
                      ) : null}
                    </div>
                  )}

                  <Separator />

                  <ExamplesEditor
                    examples={examples}
                    files={files}
                    onAdd={addExample}
                    onChange={updateExample}
                    onRemove={removeExample}
                    readOnly={draftExtractorIsPrebuilt}
                  />

                  <div className="flex flex-wrap gap-2">
                    {draftExtractorIsPrebuilt ? null : (
                      <Button disabled={!hasUnsavedExtractorChanges || !displayName.trim() || (!draftExtractorId && nameManuallyEdited && !isValidExtractorName(name))} onClick={() => void onSaveExtractor()}>
                        {draftExtractorId ? "Save changes" : "Create extractor"}
                      </Button>
                    )}
                    <Button
                      variant="secondary"
                      disabled={!draftExtractorId}
                      onClick={() =>
                        leaveEditor(() => {
                          if (draftExtractorId) setSelectedExtractorId(draftExtractorId);
                          setMainView("run");
                        })
                      }
                    >
                      <PlayCircle data-icon="inline-start" />
                      Use this extractor
                    </Button>
                    {draftExtractorId ? (
                      <CopyTextButton value={name} label="Copy extractor name" copiedLabel="Copied name!" />
                    ) : null}
                    {draftExtractorId && !draftExtractorIsPrebuilt ? (
                      <Button variant="destructive" onClick={() => setConfirmDeleteExtractor(true)}>
                        <Trash2 data-icon="inline-start" />
                        Delete
                      </Button>
                    ) : null}
                  </div>
                </CardContent>
              </Card>

            ) : (
              <>
                <Card>
                  <CardHeader>
                    <CardTitle>Runner</CardTitle>
                    <CardDescription className="flex flex-wrap items-center gap-1.5">
                      <span>Run extractor</span>
                      {selectedExtractor ? (
                        <Badge variant="secondary" className="border-transparent bg-primary/25">{extractorLabel(selectedExtractor)}</Badge>
                      ) : (
                        <Badge variant="outline">No extractor selected</Badge>
                      )}
                      <span>on your chosen input.</span>
                    </CardDescription>
                    <CardAction>
                      <Button size="lg" disabled={!runReady || runProgress !== null} onClick={() => void onRunJob()}>
                        <PlayCircle data-icon="inline-start" />
                        {runProgress
                          ? `Running ${runProgress.completed}/${runProgress.total}...`
                          : "Run extraction"}
                      </Button>
                    </CardAction>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-4">
                    <Tabs value={runInputMode} onValueChange={(value) => setRunInputMode(value as RunInputMode)}>
                      <Field>
                        <FieldLabel>Input</FieldLabel>
                        <TabsList>
                          <TabsTrigger value="file">Files</TabsTrigger>
                          <TabsTrigger value="text">Text</TabsTrigger>
                        </TabsList>
                      </Field>
                    </Tabs>
                    {runInputMode === "file" ? (
                      <p className="text-sm text-muted-foreground">
                        {selectedFiles.length === 0
                          ? "No files selected - select files in the Files panel."
                          : `Running ${selectedFiles.length === 1 ? "1 file" : `${selectedFiles.length} files`} selected in Files.`}
                      </p>
                    ) : (
                      <Field>
                        <FieldLabel htmlFor="run-text">Text</FieldLabel>
                        <Textarea
                          id="run-text"
                          value={runText}
                          onChange={(event) => setRunText(event.target.value)}
                          rows={4}
                        />
                      </Field>
                    )}
                  </CardContent>
                </Card>

                <ExtractionJobHistory
                  extractor={selectedExtractor}
                  jobs={jobs}
                  selectedJobId={job?.id ?? ""}
                  onDelete={(jobId) => void onDeleteJob(jobId)}
                  onRefresh={() => void refreshJobs()}
                  onSelect={selectJob}
                />

                {job ? (
                  <Card className="min-h-[680px]">
                    <CardHeader className="flex flex-row items-start justify-between gap-4">
                      <div className="grid gap-1">
                        <CardTitle>Extraction job result</CardTitle>
                        <CardDescription>{jobStatusCopy(job.status).description}</CardDescription>
                      </div>
                      <div className="flex shrink-0 gap-3">
                        <JobFact label="Status" value={job.status} className="min-w-[140px]" />
                        {job.model_used ? (
                          <JobFact
                            label="Model"
                            value={job.model_used}
                            title={job.provider_name_used ? providerLabel(job.provider_name_used) : undefined}
                            className="min-w-[180px]"
                          />
                        ) : null}
                        <JobFact label="Duration" value={formatJobDuration(job)} className="min-w-[140px]" />
                      </div>
                    </CardHeader>
                    <CardContent>
                      <div className="grid gap-6 xl:h-[600px] xl:grid-cols-2">
                        {job.file_id ? (
                          <DocumentSection file={jobFile} preview={preview} missing={jobFileMissing} />
                        ) : (
                          <TextInputSection text={job.source_text ?? runText} />
                        )}
                        <ResultSection job={job} />
                      </div>
                    </CardContent>
                  </Card>
                ) : null}
              </>
            )}
          </main>
        </div>
        )}
      </div>

      <AlertDialog open={pendingLeave !== null} onOpenChange={(open) => (open ? null : setPendingLeave(null))}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>
              This extractor has unsaved changes. If you leave now, your edits will be lost.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setPendingLeave(null)}>Keep editing</AlertDialogCancel>
            <AlertDialogAction
              className={buttonVariants({ variant: "destructive" })}
              onClick={() => {
                pendingLeave?.();
                setPendingLeave(null);
              }}
            >
              Discard changes
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirmDeleteFiles} onOpenChange={setConfirmDeleteFiles}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {deletableSelectedFiles.length === 1
                ? "Delete this file?"
                : `Delete ${deletableSelectedFiles.length} files?`}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {deletableSelectedFiles.length === 1
                ? "This file will be removed from local storage. This cannot be undone."
                : "These files will be removed from local storage. This cannot be undone."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className={buttonVariants({ variant: "destructive" })}
              onClick={() => void onDeleteSelectedFiles()}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirmDeleteExtractor} onOpenChange={setConfirmDeleteExtractor}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this extractor?</AlertDialogTitle>
            <AlertDialogDescription>
              This extractor will be permanently removed. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className={buttonVariants({ variant: "destructive" })}
              onClick={() => {
                if (draftExtractorId) void onDeleteExtractor(draftExtractorId);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </TooltipProvider>
  );
}

function ParseWorkspace() {
  const [files, setFiles] = useState<FileRecord[]>([]);
  const [parsers, setParsers] = useState<Parser[]>([]);
  const [jobs, setJobs] = useState<ParseJob[]>([]);
  const [selectedFileId, setSelectedFileId] = useState("");
  const [selectedParserId, setSelectedParserId] = useState("");
  const [selectedJobId, setSelectedJobId] = useState("");
  const [uploadProgress, setUploadProgress] = useState<UploadProgressState | null>(null);
  const [creatingJob, setCreatingJob] = useState(false);
  const [error, setError] = useState("");
  const [editingParserId, setEditingParserId] = useState<string | null>(null);
  const [showParserEditor, setShowParserEditor] = useState(false);
  const [parserName, setParserName] = useState("");
  const [parserDisplayName, setParserDisplayName] = useState("");
  const [parserInstructions, setParserInstructions] = useState("");
  const [parserProvider, setParserProvider] = useState<ProviderName>(DEFAULT_PROVIDER_NAME);
  const [parserModel, setParserModel] = useState("");
  const [parserReasoning, setParserReasoning] = useState<ReasoningEffort | "">("");
  const [parserModels, setParserModels] = useState<string[]>([]);
  const [savingParser, setSavingParser] = useState(false);
  const [resultView, setResultView] = useState<ParseResultView>("document");
  const [selectedPage, setSelectedPage] = useState(1);

  const parseFiles = useMemo(() => files.filter(isParseFile), [files]);
  const selectedFile = useMemo(
    () => files.find((file) => file.id === selectedFileId) ?? null,
    [files, selectedFileId]
  );
  const selectedParser = useMemo(
    () => parsers.find((parser) => parser.id === selectedParserId) ?? null,
    [parsers, selectedParserId]
  );
  const editingParser = useMemo(
    () => parsers.find((parser) => parser.id === editingParserId) ?? null,
    [editingParserId, parsers]
  );
  const selectedJob = useMemo(
    () => jobs.find((candidate) => candidate.id === selectedJobId) ?? jobs[0] ?? null,
    [jobs, selectedJobId]
  );
  const selectedResultPage = selectedJob?.result?.pages.find(
    (page) => page.page_number === selectedPage
  );

  useEffect(() => {
    void refreshParseWorkspace();
  }, []);

  useEffect(() => {
    if (!selectedParserId) {
      setJobs([]);
      setSelectedJobId("");
      return;
    }
    listParseJobs(selectedParserId)
      .then((nextJobs) => {
        const sorted = sortParseJobs(nextJobs);
        setJobs(sorted);
        setSelectedJobId((current) =>
          sorted.some((candidate) => candidate.id === current) ? current : (sorted[0]?.id ?? "")
        );
      })
      .catch(showParseError);
  }, [selectedParserId]);

  useEffect(() => {
    const active = jobs.filter((candidate) => !terminalStates.has(candidate.status));
    if (active.length === 0) return;
    const timer = window.setInterval(() => {
      Promise.all(active.map((candidate) => getParseJob(candidate.id)))
        .then((updates) => {
          setJobs((current) => sortParseJobs(updates.reduce(upsertParseJob, current)));
        })
        .catch(showParseError);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [jobs]);

  useEffect(() => {
    if (!showParserEditor) return;
    listProviderModels(parserProvider)
      .then(setParserModels)
      .catch(() => setParserModels([]));
  }, [parserProvider, showParserEditor]);

  useEffect(() => {
    setSelectedPage(selectedJob?.result?.pages[0]?.page_number ?? 1);
    setResultView("document");
  }, [selectedJob?.id]);

  async function refreshParseWorkspace() {
    try {
      const [nextFiles, nextParsers] = await Promise.all([listFiles(), listParsers()]);
      setFiles(nextFiles);
      setParsers(nextParsers);
      setSelectedFileId((current) =>
        nextFiles.some((file) => file.id === current && isParseFile(file)) ? current : ""
      );
      setSelectedParserId((current) => {
        if (nextParsers.some((parser) => parser.id === current)) return current;
        return (
          nextParsers.find((parser) => parser.name === "document-to-markdown")?.id ??
          nextParsers[0]?.id ??
          ""
        );
      });
      setError("");
    } catch (cause) {
      showParseError(cause);
    }
  }

  function showParseError(cause: unknown) {
    setError(cause instanceof Error ? cause.message : "Could not complete the parsing request");
  }

  async function onUpload(filesToUpload: File[]) {
    const supported = filesToUpload.filter((file) =>
      /\.(pdf|jpe?g|png)$/i.test(file.name)
    );
    if (supported.length === 0) {
      setError("Parsing supports PDF, JPG/JPEG, and PNG files.");
      return;
    }
    setUploadProgress({ total: supported.length, completed: 0, failed: 0 });
    try {
      const result = await uploadFilesWithConcurrency(
        supported,
        FILE_UPLOAD_CONCURRENCY,
        setUploadProgress
      );
      await refreshParseWorkspace();
      if (result.uploaded[0]) setSelectedFileId(result.uploaded[0].id);
      setError(result.failures.length ? uploadFailuresMessage(result.failures) : "");
    } catch (cause) {
      showParseError(cause);
    } finally {
      setUploadProgress(null);
    }
  }

  async function onCreateParseJob() {
    if (!selectedFile || !selectedParser) return;
    setCreatingJob(true);
    try {
      const created = await createParseJob(selectedParser.name, selectedFile.id);
      setJobs((current) => sortParseJobs(upsertParseJob(current, created)));
      setSelectedJobId(created.id);
      setError("");
    } catch (cause) {
      showParseError(cause);
    } finally {
      setCreatingJob(false);
    }
  }

  function openNewParser() {
    setEditingParserId(null);
    setParserName("");
    setParserDisplayName("");
    setParserInstructions("");
    setParserProvider(DEFAULT_PROVIDER_NAME);
    setParserModel("");
    setParserReasoning("");
    setShowParserEditor(true);
  }

  function openParser(parser: Parser) {
    setEditingParserId(parser.id);
    setParserName(parser.name);
    setParserDisplayName(parser.display_name);
    setParserInstructions(parser.instructions);
    setParserProvider(parser.provider_name ?? DEFAULT_PROVIDER_NAME);
    setParserModel(parser.model ?? "");
    setParserReasoning(parser.reasoning_effort ?? "");
    setShowParserEditor(true);
  }

  async function onSaveParser() {
    if (!parserDisplayName.trim()) return;
    setSavingParser(true);
    try {
      const payload = {
        display_name: parserDisplayName.trim(),
        instructions: parserInstructions,
        reasoning_effort: parserReasoning || null,
        provider_name: parserProvider,
        model: parserModel.trim() || null
      };
      const saved = editingParserId
        ? await updateParser(editingParserId, payload)
        : await createParser({
            ...payload,
            ...(parserName.trim() ? { name: parserName.trim() } : {})
          });
      await refreshParseWorkspace();
      setSelectedParserId(saved.id);
      setShowParserEditor(false);
      setError("");
    } catch (cause) {
      showParseError(cause);
    } finally {
      setSavingParser(false);
    }
  }

  async function onDeleteParser(parser: Parser) {
    try {
      await deleteParser(parser.id);
      setShowParserEditor(false);
      await refreshParseWorkspace();
    } catch (cause) {
      showParseError(cause);
    }
  }

  async function onCancelJob(job: ParseJob) {
    try {
      const updated = await cancelParseJob(job.id);
      setJobs((current) => sortParseJobs(upsertParseJob(current, updated)));
    } catch (cause) {
      showParseError(cause);
    }
  }

  async function onDeleteJob(job: ParseJob) {
    try {
      await deleteParseJob(job.id);
      const nextJobs = sortParseJobs(await listParseJobs(selectedParserId));
      setJobs(nextJobs);
      setSelectedJobId(nextJobs[0]?.id ?? "");
    } catch (cause) {
      showParseError(cause);
    }
  }

  return (
    <div className="mx-auto grid w-full max-w-[1500px] gap-5 px-5 py-6 lg:grid-cols-[360px_minmax(0,1fr)] lg:gap-6 lg:px-8">
      <aside className="flex flex-col gap-4 lg:sticky lg:top-21 lg:self-start">
        <Card>
          <CardHeader>
            <CardTitle>Parse files</CardTitle>
            <CardDescription>Upload and select one PDF or image.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <UploadCard onUpload={onUpload} uploadProgress={uploadProgress} />
            <Field>
              <FieldLabel htmlFor="parse-file">File</FieldLabel>
              <NativeSelect
                id="parse-file"
                value={selectedFileId}
                onChange={(event) => setSelectedFileId(event.target.value)}
              >
                <NativeSelectOption value="">Select a PDF or image</NativeSelectOption>
                {parseFiles.map((file) => (
                  <NativeSelectOption key={file.id} value={file.id}>
                    {file.file_name}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
              {files.length > parseFiles.length ? (
                <FieldDescription>Text and Markdown files remain available in Extract.</FieldDescription>
              ) : null}
            </Field>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Parsers</CardTitle>
            <CardDescription>Choose a reusable Markdown parser.</CardDescription>
            <CardAction>
              <Button variant="outline" size="sm" onClick={openNewParser}>
                <Plus data-icon="inline-start" />
                New
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {parsers.map((parser) => (
              <div
                role="button"
                tabIndex={0}
                key={parser.id}
                className={cn(
                  "flex w-full items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left text-sm",
                  parser.id === selectedParserId && "border-primary bg-primary/10"
                )}
                onClick={() => setSelectedParserId(parser.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setSelectedParserId(parser.id);
                  }
                }}
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium">{parser.display_name}</span>
                  <span className="block truncate text-xs text-muted-foreground">{parser.name}</span>
                </span>
                <span className="flex items-center gap-1">
                  {parser.is_prebuilt ? <Badge variant="secondary">Prebuilt</Badge> : null}
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Edit ${parser.display_name}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      openParser(parser);
                    }}
                  >
                    <Pencil />
                  </Button>
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      </aside>

      <main className="flex min-w-0 flex-col gap-5">
        {error ? (
          <Alert variant="destructive">
            <AlertCircle />
            <AlertTitle>Parsing needs attention</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        {showParserEditor ? (
          <Card>
            <CardHeader>
              <CardTitle>{editingParserId ? "Parser settings" : "Create parser"}</CardTitle>
              <CardDescription>
                Model-specific adapters are selected automatically from the configured model.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-2">
              <Field>
                <FieldLabel htmlFor="parser-display-name">Display name</FieldLabel>
                <Input
                  id="parser-display-name"
                  value={parserDisplayName}
                  disabled={Boolean(editingParser?.is_prebuilt)}
                  onChange={(event) => setParserDisplayName(event.target.value)}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="parser-name">Name</FieldLabel>
                <Input
                  id="parser-name"
                  value={parserName}
                  placeholder="document-to-markdown"
                  disabled={Boolean(editingParserId)}
                  onChange={(event) => setParserName(event.target.value)}
                />
              </Field>
              <Field className="md:col-span-2">
                <FieldLabel htmlFor="parser-instructions">Instructions</FieldLabel>
                <Textarea
                  id="parser-instructions"
                  value={parserInstructions}
                  disabled={Boolean(editingParser?.is_prebuilt)}
                  placeholder="Preserve page headers, footnotes, and section numbering."
                  onChange={(event) => setParserInstructions(event.target.value)}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="parser-provider">Provider</FieldLabel>
                <NativeSelect
                  id="parser-provider"
                  value={parserProvider}
                  disabled={Boolean(editingParser?.is_prebuilt)}
                  onChange={(event) => {
                    setParserProvider(event.target.value as ProviderName);
                    setParserModel("");
                  }}
                >
                  {PROVIDERS.map((provider) => (
                    <NativeSelectOption key={provider.name} value={provider.name}>
                      {provider.label}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </Field>
              <Field>
                <FieldLabel htmlFor="parser-model">Model</FieldLabel>
                <Input
                  id="parser-model"
                  list="parser-model-options"
                  value={parserModel}
                  disabled={Boolean(editingParser?.is_prebuilt)}
                  placeholder={providerModelPlaceholder(parserProvider)}
                  onChange={(event) => setParserModel(event.target.value)}
                />
                <datalist id="parser-model-options">
                  {parserModels.map((modelName) => (
                    <option key={modelName} value={modelName} />
                  ))}
                </datalist>
              </Field>
              <Field>
                <FieldLabel htmlFor="parser-reasoning">Reasoning effort</FieldLabel>
                <NativeSelect
                  id="parser-reasoning"
                  value={parserReasoning}
                  disabled={Boolean(editingParser?.is_prebuilt)}
                  onChange={(event) =>
                    setParserReasoning(event.target.value as ReasoningEffort | "")
                  }
                >
                  {REASONING_EFFORT_OPTIONS.map((option) => (
                    <NativeSelectOption key={option.value} value={option.value}>
                      {option.label}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </Field>
              <Field>
                <FieldLabel htmlFor="parser-output-tokens">Output token budget per page</FieldLabel>
                <Input id="parser-output-tokens" value="8192" readOnly />
                <FieldDescription>
                  Server-controlled by PARSEHAWK_PARSING_MAX_TOKENS.
                </FieldDescription>
              </Field>
              <div className="flex flex-wrap gap-2 md:col-span-2">
                {editingParser?.is_prebuilt ? null : (
                  <Button
                    disabled={!parserDisplayName.trim() || savingParser}
                    onClick={() => void onSaveParser()}
                  >
                    {savingParser ? "Saving..." : editingParserId ? "Save parser" : "Create parser"}
                  </Button>
                )}
                <Button variant="secondary" onClick={() => setShowParserEditor(false)}>
                  Close
                </Button>
                {editingParser && !editingParser.is_prebuilt ? (
                  <Button variant="destructive" onClick={() => void onDeleteParser(editingParser)}>
                    <Trash2 data-icon="inline-start" />
                    Delete parser
                  </Button>
                ) : null}
              </div>
            </CardContent>
          </Card>
        ) : null}

        <Card>
          <CardHeader>
            <CardTitle>Markdown parser</CardTitle>
            <CardDescription>
              {selectedParser
                ? `Parse ${selectedFile?.file_name ?? "a selected file"} with ${selectedParser.display_name}.`
                : "Select a parser and file to begin."}
            </CardDescription>
            <CardAction>
              <Button
                size="lg"
                disabled={!selectedFile || !selectedParser || creatingJob}
                onClick={() => void onCreateParseJob()}
              >
                <PlayCircle data-icon="inline-start" />
                {creatingJob ? "Queueing..." : "Run parsing"}
              </Button>
            </CardAction>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Parse jobs</CardTitle>
            <CardDescription>History for the selected parser.</CardDescription>
            <CardAction>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Refresh parse jobs"
                onClick={() =>
                  selectedParserId &&
                  listParseJobs(selectedParserId)
                    .then((next) => setJobs(sortParseJobs(next)))
                    .catch(showParseError)
                }
              >
                <RefreshCw />
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {jobs.length === 0 ? (
              <p className="text-sm text-muted-foreground">No parse jobs yet.</p>
            ) : (
              jobs.map((candidate) => (
                <div
                  key={candidate.id}
                  className={cn(
                    "flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2",
                    candidate.id === selectedJob?.id && "border-primary bg-primary/5"
                  )}
                >
                  <button
                    type="button"
                    className="min-w-0 flex-1 text-left"
                    onClick={() => setSelectedJobId(candidate.id)}
                  >
                    <span className="block truncate text-sm font-medium">
                      {files.find((file) => file.id === candidate.file_id)?.file_name ?? candidate.file_id}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {formatDateTime(candidate.created_at)} · {candidate.status}
                    </span>
                  </button>
                  {candidate.status === "queued" || candidate.status === "running" ? (
                    <Button variant="outline" size="sm" onClick={() => void onCancelJob(candidate)}>
                      Cancel
                    </Button>
                  ) : null}
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Delete parse job ${candidate.id}`}
                    onClick={() => void onDeleteJob(candidate)}
                  >
                    <Trash2 />
                  </Button>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        {selectedJob ? (
          <Card>
            <CardHeader>
              <CardTitle>Parse result</CardTitle>
              <CardDescription>{jobStatusCopy(selectedJob.status).description}</CardDescription>
              <CardAction className="flex gap-2">
                <Badge variant="outline">{selectedJob.status}</Badge>
                {selectedJob.result ? (
                  <>
                    <CopyTextButton value={selectedJob.result.content} label="Copy Markdown" />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        downloadText(
                          `${selectedFile?.file_name.replace(/\.[^.]+$/, "") ?? "document"}.md`,
                          selectedJob.result?.content ?? ""
                        )
                      }
                    >
                      <Download data-icon="inline-start" />
                      Download
                    </Button>
                  </>
                ) : null}
              </CardAction>
            </CardHeader>
            <CardContent className="flex flex-col gap-5">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <JobFact label="Provider" value={selectedJob.provider_name_used ?? "Pending"} />
                <JobFact label="Model" value={selectedJob.model_used ?? "Pending"} />
                <JobFact label="Adapter" value={selectedJob.model_adapter_used ?? "Pending"} />
                <JobFact label="Duration" value={formatJobDuration(selectedJob)} />
              </div>
              {selectedJob.error ? (
                <Alert variant="destructive">
                  <CircleX />
                  <AlertTitle>{selectedJob.error.code}</AlertTitle>
                  <AlertDescription>{selectedJob.error.message}</AlertDescription>
                </Alert>
              ) : null}
              {selectedJob.result ? (
                <Tabs value={resultView} onValueChange={(value) => setResultView(value as ParseResultView)}>
                  <TabsList>
                    <TabsTrigger value="document">Document</TabsTrigger>
                    <TabsTrigger value="pages">Per page ({selectedJob.result.page_count})</TabsTrigger>
                    <TabsTrigger value="raw">Raw Markdown</TabsTrigger>
                  </TabsList>
                  <TabsContent value="document">
                    <MarkdownPreview content={selectedJob.result.content} />
                  </TabsContent>
                  <TabsContent value="pages" className="flex flex-col gap-3">
                    <NativeSelect
                      aria-label="Parsed page"
                      value={String(selectedPage)}
                      onChange={(event) => setSelectedPage(Number(event.target.value))}
                    >
                      {selectedJob.result.pages.map((page) => (
                        <NativeSelectOption key={page.page_number} value={String(page.page_number)}>
                          Page {page.page_number}
                        </NativeSelectOption>
                      ))}
                    </NativeSelect>
                    <MarkdownPreview content={selectedResultPage?.content ?? ""} />
                  </TabsContent>
                  <TabsContent value="raw">
                    <pre className="max-h-[640px] overflow-auto whitespace-pre-wrap rounded-xl border bg-muted/30 p-4 font-mono text-sm">
                      {selectedJob.result.content}
                    </pre>
                  </TabsContent>
                </Tabs>
              ) : selectedJob.status === "queued" || selectedJob.status === "running" ? (
                <div className="flex items-center gap-3 rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  ParseHawk is processing the document page by page.
                </div>
              ) : null}
            </CardContent>
          </Card>
        ) : null}
      </main>
    </div>
  );
}

function MarkdownPreview(props: { content: string }) {
  const content = props.content.replaceAll("<!-- page-break -->", "\n\n---\n\n");

  return (
    <article className="markdown-preview min-h-48 rounded-xl border bg-card p-5 text-sm leading-7">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, rehypeSanitize]}
        components={{
          a: ({ node: _node, ...linkProps }) => (
            <a {...linkProps} target="_blank" rel="noreferrer" />
          ),
          img: ({ node: _node, alt, src }) => (
            <span className="markdown-image-reference">
              <FileImage aria-hidden="true" />
              <span>{alt || "Image reference"}</span>
              {src ? <code>{src}</code> : null}
            </span>
          ),
          table: ({ node: _node, ...tableProps }) => (
            <div className="markdown-table-wrap">
              <table {...tableProps} />
            </div>
          )
        }}
      >
        {content}
      </ReactMarkdown>
    </article>
  );
}

function ProvidersDialog() {
  const [open, setOpen] = useState(false);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadProviders() {
    setLoading(true);
    try {
      setProviders(await listProviders());
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load providers");
    } finally {
      setLoading(false);
    }
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (next) void loadProviders();
  }

  // Show providers in the fixed PROVIDERS order, ignoring the list order the API returns.
  const orderedProviders = PROVIDERS.map(({ name }) =>
    providers.find((provider) => provider.name === name)
  ).filter((provider): provider is Provider => Boolean(provider));

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <Tooltip>
        <TooltipTrigger asChild>
          <DialogTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Configure model providers">
              <Settings />
            </Button>
          </DialogTrigger>
        </TooltipTrigger>
        <TooltipContent>Providers</TooltipContent>
      </Tooltip>
      <DialogContent className="sm:max-w-2xl lg:max-w-3xl">
        <DialogHeader className="gap-1">
          <DialogTitle>Model providers</DialogTitle>
          <DialogDescription>
            Configure the providers your extractors can use. API keys are write-only — they are never
            shown back.
          </DialogDescription>
        </DialogHeader>
        {error ? (
          <Alert variant="destructive">
            <AlertCircle />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
        <div className="flex max-h-[60vh] flex-col gap-4 overflow-y-auto pr-1">
          {loading && orderedProviders.length === 0 ? (
            <p className="text-sm text-muted-foreground">Loading providers…</p>
          ) : (
            orderedProviders.map((provider) => (
              <ProviderCard
                key={provider.name}
                provider={provider}
                onConfigured={(updated) =>
                  setProviders((current) =>
                    current.map((item) => (item.name === updated.name ? updated : item))
                  )
                }
              />
            ))
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ProviderCard(props: { provider: Provider; onConfigured: (provider: Provider) => void }) {
  const { provider } = props;
  const [baseUrl, setBaseUrl] = useState(provider.base_url ?? "");
  const [projectUrl, setProjectUrl] = useState(provider.configuration.project_url ?? "");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  const showFoundryConfig = provider.name === "microsoft_foundry";
  const baseUrlPlaceholder = showFoundryConfig
    ? FOUNDRY_BASE_URL_PLACEHOLDER
    : "https://api.openai.com/v1";
  const configured = isProviderConfigured(provider);

  async function onSave() {
    setSaving(true);
    setError("");
    try {
      const payload: {
        base_url?: string | null;
        configuration?: { project_url?: string | null };
        api_key?: string;
      } = {
        base_url: baseUrl.trim() ? baseUrl.trim() : null
      };
      if (showFoundryConfig) {
        payload.configuration = {
          project_url: projectUrl.trim() ? projectUrl.trim() : null
        };
      }
      if (apiKey) {
        payload.api_key = apiKey;
      }
      const updated = await configureProvider(provider.name, payload);
      props.onConfigured(updated);
      setApiKey("");
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save provider");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-xl border p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{providerLabel(provider.name)}</span>
        <Badge variant={configured ? "secondary" : "outline"}>
          {configured ? "Configured" : "Not configured"}
        </Badge>
      </div>
      <FieldGroup className="flex flex-col gap-3">
        <Field>
          <FieldLabel htmlFor={`provider-${provider.name}-base-url`}>Base URL</FieldLabel>
          <Input
            id={`provider-${provider.name}-base-url`}
            value={baseUrl}
            placeholder={baseUrlPlaceholder}
            title={baseUrl || baseUrlPlaceholder}
            onChange={(event) => {
              setBaseUrl(event.target.value);
              setSaved(false);
            }}
          />
          {provider.name === "microsoft_foundry" ? (
            <FieldDescription>Set this to your Microsoft Foundry OpenAI-compatible endpoint.</FieldDescription>
          ) : null}
        </Field>
        {showFoundryConfig ? (
          <Field>
            <FieldLabel htmlFor={`provider-${provider.name}-project-url`}>Project URL</FieldLabel>
            <Input
              id={`provider-${provider.name}-project-url`}
              value={projectUrl}
              placeholder={FOUNDRY_PROJECT_URL_PLACEHOLDER}
              title={projectUrl || FOUNDRY_PROJECT_URL_PLACEHOLDER}
              onChange={(event) => {
                setProjectUrl(event.target.value);
                setSaved(false);
              }}
            />
            <FieldDescription>Used to discover chat-completions deployment names.</FieldDescription>
          </Field>
        ) : null}
        <Field>
          <FieldLabel htmlFor={`provider-${provider.name}-api-key`}>API key</FieldLabel>
          <Input
            id={`provider-${provider.name}-api-key`}
            type="password"
            value={apiKey}
            autoComplete="off"
            placeholder={provider.has_api_key ? "•••••••• (configured)" : "Not set"}
            onChange={(event) => {
              setApiKey(event.target.value);
              setSaved(false);
            }}
          />
          <FieldDescription>Leave blank to keep the current key.</FieldDescription>
        </Field>
      </FieldGroup>
      {error ? (
        <Alert variant="destructive">
          <AlertCircle />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      <div className="flex items-center gap-2">
        <Button size="sm" disabled={saving} onClick={() => void onSave()}>
          {saving ? "Saving…" : "Save"}
        </Button>
        {saved ? (
          <span className="flex items-center gap-1 text-sm text-muted-foreground">
            <Check className="size-4" />
            Saved
          </span>
        ) : null}
      </div>
    </div>
  );
}

function isProviderConfigured(provider: Provider): boolean {
  if (provider.name === "openai_compatible_api") {
    return Boolean(provider.base_url);
  }
  if (provider.name === "microsoft_foundry") {
    return Boolean(provider.base_url && provider.configuration.project_url && provider.has_api_key);
  }
  return provider.has_api_key;
}

function HelpDialog() {
  return (
    <Dialog>
      <Tooltip>
        <TooltipTrigger asChild>
          <DialogTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="How to use ParseHawk">
              <HelpCircle />
            </Button>
          </DialogTrigger>
        </TooltipTrigger>
        <TooltipContent>Help</TooltipContent>
      </Tooltip>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader className="gap-1">
          <DialogTitle>How to use ParseHawk</DialogTitle>
          <DialogDescription>
            ParseHawk turns documents into structured data in three steps.
          </DialogDescription>
        </DialogHeader>
        <ol className="flex flex-col gap-4 text-sm">
          <li className="flex gap-3">
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/30 text-xs font-semibold text-foreground">
              1
            </span>
            <div>
              <p className="font-medium">Add files</p>
              <p className="text-muted-foreground">
                Upload PDFs, images, text, or Markdown files in the Files panel, then select the files you
                want to run on. You can also paste raw text directly in the runner.
              </p>
            </div>
          </li>
          <li className="flex gap-3">
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/30 text-xs font-semibold text-foreground">
              2
            </span>
            <div>
              <p className="font-medium">Choose or build an extractor</p>
              <p className="text-muted-foreground">
                Pick a prebuilt extractor or click New to define your own. An extractor is a schema of
                the fields you want pulled out, plus optional instructions and examples.
              </p>
            </div>
          </li>
          <li className="flex gap-3">
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/30 text-xs font-semibold text-foreground">
              3
            </span>
            <div>
              <p className="font-medium">Run and review</p>
              <p className="text-muted-foreground">
                Hit Run extraction to queue a job per file. Watch progress in the job history and open
                any job to compare the input file against the extracted JSON.
              </p>
            </div>
          </li>
        </ol>
      </DialogContent>
    </Dialog>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    if (typeof window === "undefined") return "light";
    const stored = window.localStorage.getItem("parsehawk-theme");
    if (stored === "light" || stored === "dark") return stored;
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    window.localStorage.setItem("parsehawk-theme", theme);
  }, [theme]);

  const isDark = theme === "dark";

  const label = isDark ? "Toggle light mode" : "Toggle dark mode";

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={label}
          onClick={() => setTheme(isDark ? "light" : "dark")}
        >
          {isDark ? <Sun /> : <Moon />}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

function UploadCard(props: { onUpload: (files: File[]) => void; uploadProgress: UploadProgressState | null }) {
  const isUploading = props.uploadProgress !== null;
  const [isDragActive, setIsDragActive] = useState(false);
  const progressValue =
    props.uploadProgress && props.uploadProgress.total > 0
      ? Math.round((props.uploadProgress.completed / props.uploadProgress.total) * 100)
      : 0;
  return (
    <label
      htmlFor="file-upload"
      onDragOver={(event) => {
        if (isUploading) return;
        event.preventDefault();
        setIsDragActive(true);
      }}
      onDragLeave={(event) => {
        event.preventDefault();
        setIsDragActive(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setIsDragActive(false);
        if (isUploading) return;
        const files = Array.from(event.dataTransfer.files ?? []);
        if (files.length > 0) void props.onUpload(files);
      }}
      className={cn(
        "group flex cursor-pointer flex-col items-center gap-4 rounded-xl border border-dashed bg-muted/35 p-6 text-center transition-colors hover:bg-muted/55",
        isDragActive && "border-primary bg-muted/70",
        isUploading && "cursor-wait opacity-80"
      )}
    >
      <Input
        id="file-upload"
        className="pointer-events-none absolute size-px opacity-0"
        type="file"
        multiple
        disabled={isUploading}
        accept=".pdf,.png,.jpg,.jpeg,.txt,.md,text/*,image/*,application/pdf"
        onChange={(event) => {
          void props.onUpload(Array.from(event.target.files ?? []));
          event.currentTarget.value = "";
        }}
      />
      <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-background ring-1 ring-border">
        <UploadCloud className="size-5 text-muted-foreground" />
      </div>
      <div>
        <p className="font-medium">Click or drag to add documents</p>
        <p className="text-sm text-muted-foreground">Choose PDF, image, text, or Markdown files.</p>
        {props.uploadProgress ? (
          <div className="mt-3 grid gap-2">
            <Progress value={progressValue} />
            <p className="text-xs text-muted-foreground">
              {props.uploadProgress.completed} of {props.uploadProgress.total} uploaded
              {props.uploadProgress.failed > 0 ? `, ${props.uploadProgress.failed} failed` : ""}
            </p>
          </div>
        ) : null}
      </div>
    </label>
  );
}

function SchemaBuilder(props: {
  fields: SchemaField[];
  onAddChild: (fieldId: string) => void;
  onChange: (fieldId: string, patch: Partial<SchemaField>) => void;
  onRemove: (fieldId: string) => void;
  readOnly?: boolean;
}) {
  if (props.fields.length === 0) {
    return (
      <EmptyState
        icon={Braces}
        title="No fields yet"
        body={props.readOnly ? "This extractor has no configured fields." : "Add the first field to define the extractor output."}
      />
    );
  }
  return (
    <FieldGroup className="flex flex-col gap-3">
      {props.fields.map((schemaField) => (
        <SchemaFieldEditor
          key={schemaField.id}
          field={schemaField}
          level={0}
          onAddChild={props.onAddChild}
          onChange={props.onChange}
          onRemove={props.onRemove}
          readOnly={props.readOnly}
        />
      ))}
    </FieldGroup>
  );
}

function SchemaFieldEditor(props: {
  field: SchemaField;
  level: number;
  onAddChild: (fieldId: string) => void;
  onChange: (fieldId: string, patch: Partial<SchemaField>) => void;
  onRemove: (fieldId: string) => void;
  readOnly?: boolean;
}) {
  const isContainer = props.field.shape === "object" || (props.field.shape === "array" && props.field.itemShape === "object");
  const usesScalarControls = props.field.shape === "scalar" || (props.field.shape === "array" && props.field.itemShape === "scalar");
  const typeLabel = props.field.shape === "array" ? "Item type" : "Type";
  const enumLabel = props.field.shape === "array" ? "Item enum choices" : "Enum choices";
  const canUseTextPattern = usesScalarControls && props.field.type === "string" && props.field.enumValues.length === 0;
  const selectedType = nuextractTypeMetadata[props.field.type];
  const enumEditorValue = props.field.enumValues.join("\n");

  return (
    <section
      className={cn(
        "flex flex-col gap-4 rounded-xl border bg-background p-4",
        props.level > 0 && "bg-muted/20"
      )}
    >
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{props.level === 0 ? "Field" : "Nested field"}</Badge>
          <span className="font-mono text-sm text-muted-foreground">{props.field.name || "untitled"}</span>
        </div>
        <Button
          variant="destructive"
          size="icon-sm"
          aria-label={`Delete ${props.field.name || "field"}`}
          disabled={props.readOnly}
          onClick={() => props.onRemove(props.field.id)}
        >
          <Trash2 />
        </Button>
      </div>

      <FieldGroup className="grid gap-3 lg:grid-cols-[minmax(180px,1fr)_160px_minmax(160px,180px)_minmax(180px,1fr)]">
        <Field>
          <FieldLabel htmlFor={`${props.field.id}-key`}>Key</FieldLabel>
          <Input
            id={`${props.field.id}-key`}
            aria-label="Field key"
            value={props.field.name}
            disabled={props.readOnly}
            onChange={(event) => props.onChange(props.field.id, { name: event.target.value })}
          />
        </Field>
        <Field>
          <FieldLabel htmlFor={`${props.field.id}-shape`}>Shape</FieldLabel>
          <NativeSelect
            id={`${props.field.id}-shape`}
            className="w-full"
            aria-label="Field shape"
            value={props.field.shape}
            disabled={props.readOnly}
            onChange={(event) => props.onChange(props.field.id, { shape: event.target.value as SchemaField["shape"] })}
          >
            <NativeSelectOption value="scalar">Value</NativeSelectOption>
            <NativeSelectOption value="object">Object</NativeSelectOption>
            <NativeSelectOption value="array">List</NativeSelectOption>
          </NativeSelect>
        </Field>
        {props.field.shape === "array" ? (
          <Field>
            <FieldLabel htmlFor={`${props.field.id}-item-shape`}>Items</FieldLabel>
            <NativeSelect
              id={`${props.field.id}-item-shape`}
              className="w-full"
              aria-label="Array item shape"
              value={props.field.itemShape}
              disabled={props.readOnly}
              onChange={(event) =>
                props.onChange(props.field.id, { itemShape: event.target.value as SchemaField["itemShape"] })
              }
            >
              <NativeSelectOption value="scalar">Values</NativeSelectOption>
              <NativeSelectOption value="object">Objects</NativeSelectOption>
            </NativeSelect>
          </Field>
        ) : (
          <Field>
            <FieldLabel htmlFor={`${props.field.id}-nullable`}>Presence</FieldLabel>
            <div className="grid min-h-9 gap-2 rounded-lg border bg-muted/25 px-3 py-2">
              <CheckboxField
                id={`${props.field.id}-nullable`}
                label="Nullable"
                checked={props.field.nullable}
                disabled={props.readOnly}
                onChange={(checked) => props.onChange(props.field.id, { nullable: checked })}
              />
            </div>
          </Field>
        )}
        <Field>
          <FieldLabel htmlFor={`${props.field.id}-required`}>Required</FieldLabel>
          <div className="grid min-h-9 gap-2 rounded-lg border bg-muted/25 px-3 py-2">
            <CheckboxField
              id={`${props.field.id}-required`}
              label="Required"
              checked={props.field.required}
              disabled={props.readOnly}
              onChange={(checked) => props.onChange(props.field.id, { required: checked })}
            />
          </div>
        </Field>
      </FieldGroup>

      {usesScalarControls ? (
        <FieldGroup className="grid gap-3 lg:grid-cols-[180px_minmax(220px,1fr)_minmax(220px,1fr)]">
          <Field>
            <FieldLabel htmlFor={`${props.field.id}-type`}>{typeLabel}</FieldLabel>
            <NativeSelect
              id={`${props.field.id}-type`}
              className="w-full"
              aria-label="Field type"
              value={props.field.type}
              disabled={props.readOnly}
              onChange={(event) => props.onChange(props.field.id, { type: event.target.value as SchemaField["type"] })}
            >
              {nuextractTypeGroups.map((group) => (
                <NativeSelectOptGroup key={group} label={group}>
                  {nuextractTypeOptions
                    .filter((option) => option.group === group)
                    .map((option) => (
                      <NativeSelectOption key={option.value} value={option.value}>
                        {option.value}
                      </NativeSelectOption>
                    ))}
                </NativeSelectOptGroup>
              ))}
            </NativeSelect>
            {selectedType ? (
              <p className="text-xs leading-5 text-muted-foreground">
                {selectedType.description} Example: {selectedType.examples}
              </p>
            ) : null}
          </Field>
          <Field>
            <FieldLabel htmlFor={`${props.field.id}-enum`}>{enumLabel}</FieldLabel>
            <Textarea
              id={`${props.field.id}-enum`}
              aria-label="Enum values"
              placeholder={"EUR\nUSD\nOther"}
              value={enumEditorValue}
              disabled={props.readOnly}
              rows={Math.min(8, Math.max(2, props.field.enumValues.length))}
              onChange={(event) =>
                props.onChange(props.field.id, { enumValues: enumValuesFromEditorText(event.target.value) })
              }
              onPaste={(event) => {
                const pastedValues = pastedCommaSeparatedEnumValues(event);
                if (pastedValues.length === 0) return;
                event.preventDefault();
                props.onChange(props.field.id, {
                  enumValues: [...props.field.enumValues, ...pastedValues]
                });
              }}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor={`${props.field.id}-description`}>Description</FieldLabel>
            <Input
              id={`${props.field.id}-description`}
              aria-label="Field description"
              value={props.field.description}
              disabled={props.readOnly}
              onChange={(event) => props.onChange(props.field.id, { description: event.target.value })}
            />
          </Field>
        </FieldGroup>
      ) : (
        <Field>
          <FieldLabel htmlFor={`${props.field.id}-description`}>Description</FieldLabel>
          <Input
            id={`${props.field.id}-description`}
            aria-label="Field description"
            value={props.field.description}
            disabled={props.readOnly}
            onChange={(event) => props.onChange(props.field.id, { description: event.target.value })}
          />
        </Field>
      )}

      {canUseTextPattern ? (
        <FieldGroup className="grid gap-3 lg:grid-cols-[220px_160px_minmax(260px,1fr)]">
          <Field>
            <FieldLabel htmlFor={`${props.field.id}-validation-preset`}>Text pattern</FieldLabel>
            <NativeSelect
              id={`${props.field.id}-validation-preset`}
              className="w-full"
              aria-label="Text pattern"
              value={props.field.validationPreset}
              disabled={props.readOnly}
              onChange={(event) =>
                props.onChange(props.field.id, {
                  validationPreset: event.target.value as ValidationPreset
                })
              }
            >
              <NativeSelectOption value="none">None</NativeSelectOption>
              <NativeSelectOption value="digits">Digits only</NativeSelectOption>
              <NativeSelectOption value="exact_digits">Exactly N digits</NativeSelectOption>
              <NativeSelectOption value="exact_alphanumeric">Exactly N alphanumeric characters</NativeSelectOption>
              <NativeSelectOption value="custom">Custom regex</NativeSelectOption>
            </NativeSelect>
          </Field>
          {props.field.validationPreset === "exact_digits" || props.field.validationPreset === "exact_alphanumeric" ? (
            <Field>
              <FieldLabel htmlFor={`${props.field.id}-validation-length`}>Length</FieldLabel>
              <Input
                id={`${props.field.id}-validation-length`}
                aria-label="Exact pattern length"
                inputMode="numeric"
                min={1}
                type="number"
                value={props.field.validationLength}
                disabled={props.readOnly}
                onChange={(event) => props.onChange(props.field.id, { validationLength: event.target.value })}
              />
            </Field>
          ) : (
            <div className="hidden lg:block" />
          )}
          {props.field.validationPreset === "custom" ? (
            <Field>
              <FieldLabel htmlFor={`${props.field.id}-validation-pattern`}>Pattern</FieldLabel>
              <Input
                id={`${props.field.id}-validation-pattern`}
                aria-label="Custom regex pattern"
                placeholder="^\\d{10}$"
                value={props.field.validationPattern}
                disabled={props.readOnly}
                onChange={(event) => props.onChange(props.field.id, { validationPattern: event.target.value })}
              />
            </Field>
          ) : (
            <div className="hidden lg:block" />
          )}
        </FieldGroup>
      ) : null}

      {isContainer ? (
        <div className="flex flex-col gap-3 rounded-lg border bg-muted/20 p-3">
          <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-sm font-medium">
                {props.field.shape === "array" ? "Item fields" : "Object fields"}
              </p>
              <p className="text-xs text-muted-foreground">
                {props.field.fields.length} {props.field.fields.length === 1 ? "field" : "fields"}
              </p>
            </div>
            <Button variant="outline" size="sm" disabled={props.readOnly} onClick={() => props.onAddChild(props.field.id)}>
              <Plus data-icon="inline-start" />
              Add field
            </Button>
          </div>
          {props.field.fields.length === 0 ? (
            <EmptyState icon={Braces} title="No nested fields" body="Add a field for this nested shape." />
          ) : (
            <FieldGroup className="flex flex-col gap-3">
              {props.field.fields.map((childField) => (
                <SchemaFieldEditor
                  key={childField.id}
                  field={childField}
                  level={props.level + 1}
                  onAddChild={props.onAddChild}
                  onChange={props.onChange}
                  onRemove={props.onRemove}
                  readOnly={props.readOnly}
                />
              ))}
            </FieldGroup>
          )}
        </div>
      ) : null}
    </section>
  );
}

function updateSchemaFieldTree(fields: SchemaField[], fieldId: string, patch: Partial<SchemaField>): SchemaField[] {
  return fields.map((schemaField) => {
    const nextField =
      schemaField.id === fieldId ? normalizeSchemaField({ ...schemaField, ...patch }) : schemaField;
    return {
      ...nextField,
      fields: updateSchemaFieldTree(nextField.fields, fieldId, patch)
    };
  });
}

function addSchemaChildField(fields: SchemaField[], parentId: string): SchemaField[] {
  return fields.map((schemaField) => {
    if (schemaField.id === parentId) {
      return {
        ...schemaField,
        fields: [...schemaField.fields, field({ name: `field_${schemaField.fields.length + 1}` })]
      };
    }
    return {
      ...schemaField,
      fields: addSchemaChildField(schemaField.fields, parentId)
    };
  });
}

function removeSchemaFieldTree(fields: SchemaField[], fieldId: string): SchemaField[] {
  return fields
    .filter((schemaField) => schemaField.id !== fieldId)
    .map((schemaField) => ({
      ...schemaField,
      fields: removeSchemaFieldTree(schemaField.fields, fieldId)
    }));
}

function normalizeSchemaField(schemaField: SchemaField): SchemaField {
  const nextField = {
    ...schemaField,
    nullable: schemaField.shape === "array" ? false : schemaField.nullable
  };
  if (nextField.shape === "object" && nextField.fields.length === 0) {
    return { ...nextField, fields: [field({ name: "field_1" })] };
  }
  if (nextField.shape === "array" && nextField.itemShape === "object" && nextField.fields.length === 0) {
    return { ...nextField, fields: [field({ name: "field_1" })] };
  }
  return nextField;
}

function enumValuesFromEditorText(value: string): string[] {
  return value === "" ? [] : value.split(/\r?\n/);
}

function pastedCommaSeparatedEnumValues(event: ClipboardEvent<HTMLTextAreaElement>): string[] {
  const text = event.clipboardData.getData("text");
  if (!text.includes(",") || /\r?\n/.test(text)) return [];
  return text
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function ExamplesEditor(props: {
  examples: EditableExample[];
  files: FileRecord[];
  onAdd: (inputType?: EditableExample["inputType"]) => void;
  onChange: (exampleId: string, patch: Partial<EditableExample>) => void;
  onRemove: (exampleId: string) => void;
  readOnly?: boolean;
}) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 className="text-base font-medium">Examples</h3>
          <p className="text-sm text-muted-foreground">Add optional few-shot examples using text or uploaded files.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" disabled={props.readOnly} onClick={() => props.onAdd("text")}>
            <Plus data-icon="inline-start" />
            Text example
          </Button>
          <Button variant="outline" disabled={props.readOnly} onClick={() => props.onAdd("file")}>
            <Plus data-icon="inline-start" />
            File example
          </Button>
        </div>
      </div>

      {props.examples.length === 0 ? (
        <EmptyState icon={FileText} title="No examples yet" body="Examples are optional, but useful for domain-specific extraction behavior." />
      ) : (
        <div className="flex flex-col gap-3">
          {props.examples.map((example, index) => (
            <div key={example.id} className="rounded-xl border bg-background p-4">
              <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <Badge variant="secondary">Example {index + 1}</Badge>
                <Button variant="destructive" size="sm" disabled={props.readOnly} onClick={() => props.onRemove(example.id)}>
                  <Trash2 data-icon="inline-start" />
                  Remove
                </Button>
              </div>
              <FieldGroup className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)_minmax(0,1fr)]">
                <Field>
                  <FieldLabel htmlFor={`${example.id}-input-type`}>Input type</FieldLabel>
                  <NativeSelect
                    id={`${example.id}-input-type`}
                    value={example.inputType}
                    disabled={props.readOnly}
                    onChange={(event) =>
                      props.onChange(example.id, {
                        inputType: event.target.value as EditableExample["inputType"],
                      })
                    }
                  >
                    <NativeSelectOption value="text">Text</NativeSelectOption>
                    <NativeSelectOption value="file">Uploaded file</NativeSelectOption>
                  </NativeSelect>
                </Field>
                {example.inputType === "file" ? (
                  <Field>
                    <FieldLabel htmlFor={`${example.id}-file`}>File</FieldLabel>
                    <NativeSelect
                      id={`${example.id}-file`}
                      value={example.fileId}
                      disabled={props.readOnly}
                      onChange={(event) => props.onChange(example.id, { fileId: event.target.value })}
                    >
                      <NativeSelectOption value="">Select file</NativeSelectOption>
                      {props.files.map((fileRecord) => (
                        <NativeSelectOption key={fileRecord.id} value={fileRecord.id}>
                          {fileRecord.file_name}
                        </NativeSelectOption>
                      ))}
                    </NativeSelect>
                  </Field>
                ) : (
                  <Field>
                    <FieldLabel htmlFor={`${example.id}-text`}>Input text</FieldLabel>
                    <Textarea
                      id={`${example.id}-text`}
                      value={example.text}
                      disabled={props.readOnly}
                      onChange={(event) => props.onChange(example.id, { text: event.target.value })}
                      rows={7}
                    />
                  </Field>
                )}
                <Field>
                  <FieldLabel htmlFor={`${example.id}-output`}>Expected output</FieldLabel>
                  <Textarea
                    id={`${example.id}-output`}
                    className="font-mono"
                    value={example.outputText}
                    disabled={props.readOnly}
                    onChange={(event) => props.onChange(example.id, { outputText: event.target.value })}
                    rows={7}
                  />
                </Field>
              </FieldGroup>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function CheckboxField(props: {
  id: string;
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <Field orientation="horizontal" className="gap-2">
      <Checkbox
        id={props.id}
        checked={props.checked}
        disabled={props.disabled}
        onCheckedChange={(checked) => props.onChange(checked === true)}
      />
      <FieldLabel htmlFor={props.id} className="font-normal">
        {props.label}
      </FieldLabel>
    </Field>
  );
}

function FileList(props: {
  files: FileRecord[];
  selectedFileIds: string[];
  onToggle: (fileId: string) => void;
}) {
  if (props.files.length === 0) {
    return;
  }
  return (
    <div className="max-h-72 overflow-y-auto">
      <div className="flex flex-col divide-y">
        {props.files.map((fileRecord) => {
          const isSelected = props.selectedFileIds.includes(fileRecord.id);
          return (
            <div
              key={fileRecord.id}
              role="checkbox"
              tabIndex={0}
              aria-checked={isSelected}
              aria-label={`Select ${fileRecord.file_name}`}
              onClick={() => props.onToggle(fileRecord.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  props.onToggle(fileRecord.id);
                }
              }}
              className={cn(
                "grid cursor-pointer grid-cols-[auto_minmax(0,1fr)] items-center gap-3 p-3 outline-none transition-colors focus-visible:bg-muted/50",
                isSelected ? "bg-muted/50" : "[&:hover:not(:has(button:hover))]:bg-muted/50"
              )}
            >
              <Checkbox checked={isSelected} aria-hidden tabIndex={-1} className="pointer-events-none" />
              <div className="px-2 py-1.5 text-left">
                <span className="min-w-0">
                  <span className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="truncate font-medium">{fileRecord.file_name}</span>
                    {isExampleFile(fileRecord) ? <Badge variant="outline">Example file</Badge> : null}
                  </span>
                  <span className="block text-xs text-muted-foreground">
                    {formatFileType(fileRecord.content_type)} · {formatBytes(fileRecord.size_bytes)}
                  </span>
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ExtractorList(props: {
  extractors: Extractor[];
  selectedExtractorId: string;
  onEdit: (extractor: Extractor) => void;
  onSelect: (extractorId: string) => void;
}) {
  if (props.extractors.length === 0) {
    return <EmptyState icon={LayoutTemplate} title="No extractors saved" body="Save an extractor to run it against uploaded files." />;
  }
  return (
    <ScrollArea className="max-h-[720px] rounded-xl border [&_[data-slot=scroll-area-viewport]>div]:block!">
      <div className="flex flex-col divide-y">
        {props.extractors.map((extractor) => {
          const isPrebuilt = isPrebuiltExtractor(extractor);
          const isSelected = extractor.id === props.selectedExtractorId;
          return (
            <div
              key={extractor.id}
              role="radio"
              tabIndex={0}
              aria-checked={isSelected}
              onClick={() => props.onSelect(extractor.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  props.onSelect(extractor.id);
                }
              }}
              className={cn(
                "flex cursor-pointer flex-col gap-3 p-3 transition-colors outline-none [&:hover:not(:has(button:hover))]:bg-muted/50 focus-visible:bg-muted/50",
                isSelected && "bg-muted/50"
              )}
            >
              <div className="flex items-center gap-2.5 px-2 py-1.5 text-left">
                <span
                  aria-hidden
                  className={cn(
                    "flex size-4 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
                    isSelected ? "border-primary" : "border-muted-foreground/40"
                  )}
                >
                  {isSelected ? <span className="size-1.5 rounded-full bg-primary" /> : null}
                </span>
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="min-w-0 truncate font-medium">{extractorLabel(extractor)}</span>
                    {isPrebuilt ? <Badge variant="outline" className="shrink-0">Prebuilt</Badge> : null}
                  </span>
                  <CopyableId id={extractor.name} label="extractor name" className="text-xs" />
                </span>
                <Button
                  variant="outline"
                  size="icon-sm"
                  aria-label={isPrebuilt ? "View extractor" : "Edit extractor"}
                  onClick={(event) => {
                    event.stopPropagation();
                    props.onEdit(extractor);
                  }}
                >
                  {isPrebuilt ? <Eye /> : <Pencil />}
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </ScrollArea>
  );
}

function ExtractionJobHistory(props: {
  extractor: Extractor | null;
  jobs: ExtractionJob[];
  selectedJobId: string;
  onDelete: (jobId: string) => void;
  onRefresh: () => void;
  onSelect: (job: ExtractionJob) => void;
}) {
  const [confirmJobId, setConfirmJobId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const topJobId = props.jobs[0]?.id ?? null;
  const previousTopJobId = useRef<string | null>(topJobId);
  useEffect(() => {
    if (topJobId && topJobId !== previousTopJobId.current) {
      scrollRef.current?.scrollTo({ top: 0 });
    }
    previousTopJobId.current = topJobId;
  }, [topJobId]);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Extraction jobs</CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-1.5">
          {props.extractor ? (
            <>
              <span>Pending and completed runs for</span>
              <Badge variant="secondary" className="border-transparent bg-primary/30">{extractorLabel(props.extractor)}</Badge>
            </>
          ) : (
            "Select an extractor to inspect previous runs."
          )}
        </CardDescription>
        <CardAction>
          <Button variant="outline" size="sm" disabled={!props.extractor} onClick={props.onRefresh}>
            <RefreshCw data-icon="inline-start" />
            Refresh
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        {!props.extractor ? (
          <EmptyState icon={Clock3} title="No extractor selected" body="Choose an extractor to load its jobs." />
        ) : props.jobs.length === 0 ? (
          <EmptyState icon={Clock3} title="No jobs yet" body="Run an extraction and the job will appear here." />
        ) : (
          <div className="overflow-hidden rounded-xl border">
            <div ref={scrollRef} className="max-h-80 overflow-y-auto">
              <div className="divide-y">
                {props.jobs.map((historyJob) => {
                  const status = jobStatusCopy(historyJob.status);
                  const Icon = status.icon;
                  return (
                    <div
                      key={historyJob.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => props.onSelect(historyJob)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          props.onSelect(historyJob);
                        }
                      }}
                      className={cn(
                        "grid cursor-pointer gap-3 p-3 outline-none transition-colors focus-visible:bg-muted/50 md:grid-cols-[minmax(0,1fr)_auto] md:items-center",
                        historyJob.id === props.selectedJobId
                          ? "bg-primary/30"
                          : "[&:hover:not(:has(button:hover))]:bg-muted/50"
                      )}
                    >
                      <div className="flex items-center gap-3 px-2 py-1.5 text-left">
                        <Icon
                          data-icon="inline-start"
                          className={cn("size-4 shrink-0", activeStates.has(historyJob.status) && "animate-spin")}
                        />
                        <span className="min-w-0">
                          <span className="flex flex-wrap items-center gap-2">
                            <CopyableId
                              id={historyJob.id}
                              label="job ID"
                              className="text-sm font-medium text-foreground"
                            />
                          </span>
                          <span className="mt-1 block text-xs text-muted-foreground">
                            {formatDateTime(historyJob.created_at)} ·{" "}
                            {historyJob.file_id ? (
                              <CopyableId id={historyJob.file_id} label="file ID" className="text-xs" />
                            ) : (
                              "Inline text"
                            )}
                          </span>
                        </span>
                      </div>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="outline"
                            size="icon-sm"
                            aria-label={`Delete job ${historyJob.id}`}
                            onClick={(event) => {
                              event.stopPropagation();
                              setConfirmJobId(historyJob.id);
                            }}
                          >
                            <Trash2 />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>Delete job</TooltipContent>
                      </Tooltip>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </CardContent>

      <AlertDialog open={confirmJobId !== null} onOpenChange={(open) => (open ? null : setConfirmJobId(null))}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this job?</AlertDialogTitle>
            <AlertDialogDescription>
              This run and its result will be permanently removed. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className={buttonVariants({ variant: "destructive" })}
              onClick={() => {
                if (confirmJobId) props.onDelete(confirmJobId);
                setConfirmJobId(null);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}

function SectionHeading(props: { title: string; subtitle: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <h3 className="text-sm font-semibold">{props.title}</h3>
      <p className="truncate text-xs text-muted-foreground">{props.subtitle}</p>
    </div>
  );
}

function DocumentSection(props: { file: FileRecord | null; preview: string; missing?: boolean }) {
  return (
    <div className="flex flex-col gap-3 xl:h-full xl:min-h-0">
      <SectionHeading title="Document" subtitle={props.file?.file_name ?? (props.missing ? "File missing" : "No file selected")} />
      {props.missing ? (
        <div className="flex h-[560px] items-center justify-center rounded-xl border border-dashed bg-muted/25 p-6 text-center xl:h-auto xl:min-h-0 xl:flex-1">
          <p className="text-sm text-muted-foreground">
            The file used for this job is no longer in storage, so its document can&apos;t be shown.
          </p>
        </div>
      ) : props.file && isImage(props.file) ? (
        <div className="flex max-h-[560px] min-h-[360px] items-center justify-center overflow-hidden rounded-xl border bg-muted/25 xl:max-h-none xl:min-h-0 xl:flex-1">
          <img className="max-h-[560px] w-full object-contain xl:max-h-full" src={fileContentUrl(props.file)} alt={props.file.file_name} />
        </div>
      ) : props.file && isPdf(props.file) ? (
        <div className="h-[560px] overflow-hidden rounded-xl border bg-muted/25 xl:h-auto xl:min-h-0 xl:flex-1">
          <object className="size-full" data={fileContentUrl(props.file)} type="application/pdf" aria-label={props.file.file_name}>
            <iframe className="size-full" src={fileContentUrl(props.file)} title={props.file.file_name} />
          </object>
        </div>
      ) : (
        <ScrollArea className="h-[560px] rounded-xl border bg-muted/25 xl:h-auto xl:min-h-0 xl:flex-1">
          <pre className="whitespace-pre-wrap p-4 font-mono text-sm leading-6 text-foreground">
            {props.preview || "Upload or select a text document."}
          </pre>
        </ScrollArea>
      )}
    </div>
  );
}

function TextInputSection(props: { text: string }) {
  return (
    <div className="flex flex-col gap-3 xl:h-full xl:min-h-0">
      <SectionHeading title="Text input" subtitle="Inline extraction input" />
      <ScrollArea className="h-[560px] rounded-xl border bg-muted/25 xl:h-auto xl:min-h-0 xl:flex-1">
        <pre className="whitespace-pre-wrap p-4 font-mono text-sm leading-6 text-foreground">
          {props.text || "Enter text to run this extractor without uploading a file."}
        </pre>
      </ScrollArea>
    </div>
  );
}

function ResultSection(props: { job: ExtractionJob }) {
  const data = props.job.result?.data ?? null;
  const showResultTabs = Boolean(props.job.result);
  return (
    <div className="flex flex-col gap-3 xl:h-full xl:min-h-0">
      <div aria-hidden className="hidden shrink-0 flex-col gap-0.5 xl:flex">
        <h3 className="text-sm font-semibold">{" "}</h3>
        <p className="text-xs text-muted-foreground">{" "}</p>
      </div>
      {showResultTabs ? (
        <Tabs defaultValue="fields" className="gap-0 overflow-hidden rounded-xl border xl:flex xl:min-h-0 xl:flex-1 xl:flex-col">
          <div className="shrink-0 border-b bg-muted/30 px-2 py-2">
            <TabsList>
              <TabsTrigger value="fields">Fields</TabsTrigger>
              <TabsTrigger value="json">json</TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="fields" className="mt-0 xl:min-h-0 xl:flex-1">
            {data ? <ResultFields data={data} /> : <JsonBlock value={prettyJson(props.job)} />}
          </TabsContent>
          <TabsContent value="json" className="mt-0 xl:min-h-0 xl:flex-1">
            <JsonBlock value={data ? prettyJson(data) : prettyJson(props.job)} />
          </TabsContent>
        </Tabs>
      ) : (
        <JobProgressPanel job={props.job} />
      )}
    </div>
  );
}

function JobProgressPanel(props: { job: ExtractionJob | null }) {
  if (!props.job) {
    return (
      <EmptyState
        icon={PlayCircle}
        title="Ready to run"
        body="Choose an extractor and input, then start an extraction job."
      />
    );
  }

  const status = jobStatusCopy(props.job.status);
  const Icon = status.icon;
  return (
    <div className="flex flex-col gap-5">
      <div className="rounded-xl border bg-muted/25 p-5">
        <div className="flex flex-col gap-4">
          <div className="flex items-start gap-3">
            <div className="flex size-10 items-center justify-center">
              <Icon
                className={cn(
                  "size-5",
                  status.tone === "destructive" && "text-destructive",
                  status.tone === "success" && "text-primary",
                  activeStates.has(props.job.status) && "animate-spin"
                )}
              />
            </div>
            <div>
              <h3 className="text-base font-medium">{status.title}</h3>
              <p className="text-sm text-muted-foreground">{status.description}</p>
            </div>
          </div>

          <Field>
            <div className="flex items-center justify-between gap-3">
              <FieldLabel>Extraction job progress</FieldLabel>
              <span className="text-sm text-muted-foreground">{status.progress}%</span>
            </div>
            <Progress value={status.progress} />
          </Field>
        </div>
      </div>

      {props.job.error ? (
        <Alert variant="destructive">
          <AlertCircle />
          <AlertTitle>Extraction failed</AlertTitle>
          <AlertDescription>{props.job.error.message}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

function JobFact(props: { label: string; value: string; title?: string; className?: string }) {
  return (
    <div className={cn("rounded-lg border bg-background px-3 py-2", props.className)}>
      <p className="text-xs text-muted-foreground">{props.label}</p>
      {props.title ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <p className="truncate font-mono text-sm">{props.value}</p>
          </TooltipTrigger>
          <TooltipContent className="font-mono">{props.title}</TooltipContent>
        </Tooltip>
      ) : (
        <p className="truncate font-mono text-sm">{props.value}</p>
      )}
    </div>
  );
}

function ResultFields(props: { data: Record<string, unknown> }) {
  const entries = Object.entries(props.data);
  if (entries.length === 0) {
    return <EmptyState icon={FileJson} title="No fields returned" body="The extraction completed without structured fields." />;
  }
  return (
    <div className="h-[520px] overflow-y-auto xl:h-full">
      <div className="divide-y">
        {entries.map(([key, value]) => (
          <div className="grid gap-2 p-3 md:grid-cols-[180px_minmax(0,1fr)_auto] md:items-center" key={key}>
            <span className="font-mono text-sm text-muted-foreground">{key}</span>
            <strong className="min-w-0 whitespace-pre-wrap break-words text-sm font-medium">{formatResultValue(value)}</strong>
            <CopyButton value={formatResultValue(value)} label={`Copy ${key}`} />
          </div>
        ))}
      </div>
    </div>
  );
}

function SchemaValidationPanel(props: { validation: SchemaValidation }) {
  const valid = props.validation.valid;
  return (
    <Alert
      variant={valid ? "default" : "destructive"}
      className={cn("border-0 bg-transparent px-0", valid && "text-success")}
    >
      {valid ? <CheckCircle2 /> : <AlertCircle />}
      <AlertTitle>{valid ? "Schema is valid" : "Schema has errors"}</AlertTitle>
      {valid ? null : (
        <AlertDescription>
          {props.validation.errors.length > 0
            ? props.validation.errors.map((error) => error.message).join("; ")
            : "The API returned a canonical schema."}
        </AlertDescription>
      )}
    </Alert>
  );
}

function JsonEditor(props: { value: string; readOnly?: boolean; onChange: (value: string) => void }) {
  return (
    <div className="relative grid min-h-[460px] overflow-hidden rounded-xl border bg-muted/30 font-mono text-sm">
      <div className="absolute right-3 top-3 z-10">
        <CopyButton value={props.value} label="Copy JSON schema" />
      </div>
      <pre className="pointer-events-none col-start-1 row-start-1 overflow-auto whitespace-pre p-4 pr-16 leading-6" aria-hidden="true">
        <JsonTokens value={props.value} />
      </pre>
      <textarea
        className="col-start-1 row-start-1 min-h-[460px] resize-y overflow-auto bg-transparent p-4 pr-16 leading-6 text-transparent caret-foreground outline-none disabled:cursor-not-allowed"
        spellCheck={false}
        value={props.value}
        readOnly={props.readOnly}
        onChange={(event) => props.onChange(event.target.value)}
        onScroll={(event) => {
          const highlight = event.currentTarget.previousElementSibling;
          if (highlight instanceof HTMLElement) {
            highlight.scrollTop = event.currentTarget.scrollTop;
            highlight.scrollLeft = event.currentTarget.scrollLeft;
          }
        }}
      />
    </div>
  );
}

function JsonBlock(props: { value: string }) {
  return (
    <div className="relative">
      <div className="absolute right-3 top-3 z-10">
        <CopyButton value={props.value} label="Copy JSON" />
      </div>
      <ScrollArea className="h-[520px] xl:h-full">
        <pre className="whitespace-pre-wrap p-4 pr-16 font-mono text-sm leading-6">
          <JsonTokens value={props.value} />
        </pre>
      </ScrollArea>
    </div>
  );
}

function CopyButton(props: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const Icon = copied ? Check : Copy;

  async function onCopy() {
    await copyToClipboard(props.value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="icon-sm"
      aria-label={copied ? "Copied" : props.label}
      onClick={() => void onCopy()}
    >
      <Icon />
    </Button>
  );
}

function CopyTextButton(props: { value: string; label: string; copiedLabel?: string }) {
  const [copied, setCopied] = useState(false);
  const Icon = copied ? Check : Copy;

  async function onCopy() {
    await copyToClipboard(props.value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <Button variant="secondary" onClick={() => void onCopy()}>
      <Icon data-icon="inline-start" />
      {/* Stack both labels in one grid cell so the width stays put when the
          text swaps to "Copied!" and the surrounding row doesn't shift. */}
      <span className="grid place-items-center">
        <span className={cn("col-start-1 row-start-1", copied && "invisible")}>{props.label}</span>
        <span className={cn("col-start-1 row-start-1", !copied && "invisible")} aria-hidden={!copied}>
          {props.copiedLabel ?? "Copied ID!"}
        </span>
      </span>
    </Button>
  );
}

function CopyableId(props: { id: string; label?: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState(false);
  const label = props.label ?? "ID";

  async function onCopy(event: React.MouseEvent) {
    // Stop the click from toggling the surrounding row's selection.
    event.stopPropagation();
    await copyToClipboard(props.id);
    setCopied(true);
    // Radix dismisses the tooltip on click, so keep it open to surface the
    // "Copied!" confirmation, then close after a short beat.
    setOpen(true);
    window.setTimeout(() => {
      setCopied(false);
      setOpen(false);
    }, 1200);
  }

  return (
    <Tooltip open={open} onOpenChange={(next) => setOpen(next || copied)}>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={`Copy ${label} ${props.id}`}
          onClick={(event) => void onCopy(event)}
          className={cn(
            "inline-flex w-fit max-w-full items-center font-mono text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:text-foreground",
            props.className
          )}
        >
          <span className="truncate">{shortId(props.id)}</span>
        </button>
      </TooltipTrigger>
      <TooltipContent>{copied ? "Copied!" : `Click to copy full ${label}`}</TooltipContent>
    </Tooltip>
  );
}

function JsonTokens(props: { value: string }) {
  return (
    <>
      {jsonTokens(props.value).map((token, index) => (
        <span className={`json-token ${token.kind}`} key={`${index}-${token.value}`}>
          {token.value}
        </span>
      ))}
    </>
  );
}

function EmptyState(props: { icon: React.ComponentType; title: string; body: string; action?: ReactNode }) {
  const Icon = props.icon;
  return (
    <Empty className="min-h-[220px] border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Icon />
        </EmptyMedia>
        <EmptyTitle>{props.title}</EmptyTitle>
        <EmptyDescription>{props.body}</EmptyDescription>
      </EmptyHeader>
      {props.action ? <EmptyContent>{props.action}</EmptyContent> : null}
    </Empty>
  );
}

function keepSelection(current: string, ids: string[]) {
  if (ids.includes(current)) return current;
  return ids[0] ?? "";
}

function isExampleFile(file: FileRecord) {
  return file.source === "example" || file.is_example === true;
}

function isPrebuiltExtractor(extractor: Extractor) {
  return extractor.source === "prebuilt" || extractor.is_prebuilt === true || extractor.is_example === true;
}

function extractorLabel(extractor: Extractor) {
  return extractor.display_name || extractor.name;
}

function isValidExtractorName(name: string) {
  return !name.startsWith("extractor_") && /^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$/.test(name);
}

function slugifyExtractorName(displayName: string) {
  const slug = displayName
    .normalize("NFKD")
    .replace(/[^\x00-\x7F]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
  const truncated = slug.slice(0, 64).replace(/-$/g, "");
  return truncated || "extractor";
}

function schemaDraftFingerprint(mode: SchemaMode, fields: SchemaField[], jsonText: string) {
  try {
    if (mode === "json") {
      return prettyJson(fieldSchemaFromFields(fieldsFromSchema(parseJsonObject(jsonText))));
    }
    return prettyJson(fieldSchemaFromFields(fields));
  } catch {
    return `${mode}:${jsonText}`;
  }
}

function extractorDraftSnapshot(props: {
  name: string;
  displayName: string;
  instructions: string;
  reasoningEffort: ReasoningEffort | "";
  providerName: ProviderName;
  model: string;
  schemaText: string;
  examplesText: string;
}) {
  return JSON.stringify({
    name: props.name,
    displayName: props.displayName,
    instructions: props.instructions,
    reasoningEffort: props.reasoningEffort,
    providerName: props.providerName,
    model: props.model,
    schemaText: props.schemaText,
    examplesText: props.examplesText
  });
}

type FileUploadFailure = { file: File; error: unknown };

async function uploadFilesWithConcurrency(
  files: File[],
  concurrency: number,
  onProgress: (progress: UploadProgressState) => void
) {
  const uploadedByIndex: Array<FileRecord | undefined> = new Array(files.length);
  const failures: FileUploadFailure[] = [];
  let nextIndex = 0;
  let completed = 0;

  async function worker() {
    while (nextIndex < files.length) {
      const index = nextIndex;
      const file = files[nextIndex];
      nextIndex += 1;
      try {
        uploadedByIndex[index] = await uploadFile(file);
      } catch (error) {
        failures.push({ file, error });
      } finally {
        completed += 1;
        onProgress({
          total: files.length,
          completed,
          failed: failures.length
        });
      }
    }
  }

  const workerCount = Math.min(Math.max(1, concurrency), files.length);
  await Promise.all(Array.from({ length: workerCount }, () => worker()));
  return { uploaded: uploadedByIndex.filter((file): file is FileRecord => file !== undefined), failures };
}

function uploadFailuresMessage(failures: FileUploadFailure[]) {
  const failedFiles = failures.map(({ file }) => file.name).join(", ");
  return `Could not upload ${failures.length} file${failures.length === 1 ? "" : "s"}: ${failedFiles}`;
}

function jsonTokens(value: string): Array<{ kind: string; value: string }> {
  const tokens: Array<{ kind: string; value: string }> = [];
  const pattern =
    /("(?:\\.|[^"\\])*"(?=\s*:))|("(?:\\.|[^"\\])*")|\b(true|false)\b|\bnull\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;
  let lastIndex = 0;
  for (const match of value.matchAll(pattern)) {
    if (match.index === undefined) continue;
    if (match.index > lastIndex) {
      tokens.push({ kind: "plain", value: value.slice(lastIndex, match.index) });
    }
    tokens.push({ kind: tokenKind(match), value: match[0] });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < value.length) {
    tokens.push({ kind: "plain", value: value.slice(lastIndex) });
  }
  return tokens;
}

function tokenKind(match: RegExpMatchArray) {
  if (match[1]) return "key";
  if (match[2]) return "string";
  if (match[3]) return "boolean";
  if (match[0] === "null") return "null";
  return "number";
}

async function copyToClipboard(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

function isImage(fileRecord: FileRecord) {
  return fileRecord.content_type.startsWith("image/");
}

function isPdf(fileRecord: FileRecord) {
  return fileRecord.content_type === "application/pdf" || fileRecord.file_name.toLowerCase().endsWith(".pdf");
}

function isParseFile(fileRecord: FileRecord) {
  const name = fileRecord.file_name.toLowerCase();
  return (
    isPdf(fileRecord) ||
    fileRecord.content_type === "image/png" ||
    fileRecord.content_type === "image/jpeg" ||
    /\.(png|jpe?g)$/.test(name)
  );
}

function formatResultValue(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "string") return value || "";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return prettyJson(value);
}

function jobStatusCopy(status: JobStatus): {
  title: string;
  description: string;
  progress: number;
  tone: "default" | "success" | "destructive";
  icon: ComponentType<{ className?: string }>;
} {
  if (status === "queued") {
    return {
      title: "Queued",
      description: "The job is queued.",
      progress: 20,
      tone: "default",
      icon: Clock3
    };
  }
  if (status === "running") {
    return {
      title: "Extracting",
      description: "ParseHawk is working on this job.",
      progress: 65,
      tone: "default",
      icon: Loader2
    };
  }
  if (status === "completed") {
    return {
      title: "Completed",
      description: "The result is ready to review.",
      progress: 100,
      tone: "success",
      icon: CheckCircle2
    };
  }
  if (status === "canceling" || status === "deleting") {
    return {
      title: status === "deleting" ? "Deleting" : "Canceling",
      description:
        status === "deleting"
          ? "ParseHawk is stopping and removing this job."
          : "ParseHawk is stopping this job.",
      progress: 50,
      tone: "default",
      icon: Loader2
    };
  }
  return {
    title: status === "canceled" ? "Canceled" : "Failed",
    description:
      status === "canceled"
        ? "This job was canceled before it produced a result."
        : "This job did not produce a usable result.",
    progress: 100,
    tone: "destructive",
    icon: CircleX
  };
}

function shortId(value: string) {
  if (value.length <= 16) return value;
  return `${value.slice(0, 10)}...${value.slice(-4)}`;
}

function formatDateTime(value: string | null) {
  if (!value) return "Not started";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}

function formatJobDuration(job: ExtractionJob | ParseJob) {
  if (!job.completed_at) {
    return "In progress";
  }
  const startedAt = Date.parse(job.started_at ?? job.created_at);
  const completedAt = Date.parse(job.completed_at);
  if (!Number.isFinite(startedAt) || !Number.isFinite(completedAt)) {
    return "Unknown";
  }
  return formatDurationMs(Math.max(0, completedAt - startedAt));
}

function formatDurationMs(milliseconds: number) {
  if (milliseconds < 1000) return `${milliseconds} ms`;
  const totalSeconds = milliseconds / 1000;
  if (totalSeconds < 10) return `${trimTrailingZero(totalSeconds.toFixed(1))}s`;
  const roundedSeconds = Math.round(totalSeconds);
  if (roundedSeconds < 60) return `${roundedSeconds}s`;
  const minutes = Math.floor(roundedSeconds / 60);
  const seconds = roundedSeconds % 60;
  return seconds > 0 ? `${minutes}m ${String(seconds).padStart(2, "0")}s` : `${minutes}m`;
}

function trimTrailingZero(value: string) {
  return value.endsWith(".0") ? value.slice(0, -2) : value;
}

function upsertJob(jobs: ExtractionJob[], job: ExtractionJob) {
  return sortJobs([job, ...jobs.filter((current) => current.id !== job.id)]);
}

function sortJobs(jobs: ExtractionJob[]) {
  return [...jobs].sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at));
}

function upsertParseJob(jobs: ParseJob[], job: ParseJob) {
  return sortParseJobs([job, ...jobs.filter((current) => current.id !== job.id)]);
}

function sortParseJobs(jobs: ParseJob[]) {
  return [...jobs].sort(
    (left, right) => Date.parse(right.created_at) - Date.parse(left.created_at)
  );
}

function downloadText(fileName: string, content: string) {
  const url = URL.createObjectURL(new Blob([content], { type: "text/markdown;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}

function formatFileType(contentType: string) {
  const subtype = contentType.split("/").pop() ?? contentType;
  return subtype.split("+")[0] || contentType;
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
