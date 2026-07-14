from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Annotated, Any, cast

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Path,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse as FastAPIFileResponse
from fastapi.responses import JSONResponse

from parsehawk import telemetry, tracing
from parsehawk.core.application.services import NOT_PROVIDED, DeleteJobResult
from parsehawk.core.domain.errors import NotFoundError, ProviderRequestError, ValidationFailure
from parsehawk.core.domain.models import ProviderName
from parsehawk.core.domain.schemas import (
    MODE_JSON_SCHEMA,
    validate_extraction_schema,
)
from parsehawk.core.domain.schemas import (
    SchemaDiagnostic as CoreSchemaDiagnostic,
)
from parsehawk.logging import configure_logging
from parsehawk.server.api.fastapi.schemas import (
    ApiErrorResponse,
    ConfigureProviderRequest,
    CreateExtractorRequest,
    CreateJobRequest,
    ExtractorResponse,
    FileResponse,
    HealthResponse,
    JobResponse,
    ProviderModelsResponse,
    ProviderResponse,
    RootResponse,
    SchemaDiagnostic,
    UpdateExtractorRequest,
    UpsertExtractorRequest,
    ValidateSchemaRequest,
    ValidateSchemaResponse,
)
from parsehawk.server.bootstrap.seeds import seed_prebuilt_data_in_container
from parsehawk.server.container import Container, build_container
from parsehawk.server.runtime.inference.openai_engine import (
    list_foundry_chat_deployments,
    list_models,
    list_openai_chat_models,
)

configure_logging("parsehawk", configure_uvicorn=True)
logger = logging.getLogger(__name__)


def get_container(request: Request) -> Container:
    return cast(Container, request.app.state.container)


ContainerDep = Annotated[Container, Depends(get_container)]
UploadFileDep = Annotated[
    UploadFile,
    File(description="PDF, image, text, or Markdown document to store for extraction."),
]

OPENAPI_TAGS = [
    {
        "name": "health",
        "description": "API discovery and process liveness.",
    },
    {
        "name": "files",
        "description": "Upload documents once, inspect their metadata, and reuse them across jobs.",
    },
    {
        "name": "schemas",
        "description": "Validate extraction schemas before attaching them to extractors.",
    },
    {
        "name": "extractors",
        "description": "Reusable extraction instructions, schemas, examples, provider, and model choices.",
    },
    {
        "name": "providers",
        "description": "Configure local or hosted model providers without exposing stored secrets.",
    },
    {
        "name": "jobs",
        "description": "Create, inspect, cancel, and delete asynchronous extraction jobs.",
    },
]

VALIDATION_ERROR_RESPONSE = {
    "model": ApiErrorResponse,
    "description": "The request or domain input failed validation.",
}
NOT_FOUND_RESPONSE = {
    "model": ApiErrorResponse,
    "description": "The requested ParseHawk resource does not exist.",
}
PROVIDER_ERROR_RESPONSE = {
    "model": ApiErrorResponse,
    "description": "The configured model provider rejected the request or could not be reached.",
}
SERVER_ERROR_RESPONSE = {
    "model": ApiErrorResponse,
    "description": "Unexpected server error.",
}

files_router = APIRouter(prefix="/files", tags=["files"])
extractors_router = APIRouter(prefix="/extractors", tags=["extractors"])
providers_router = APIRouter(prefix="/providers", tags=["providers"])
jobs_router = APIRouter(prefix="/jobs", tags=["jobs"])
schemas_router = APIRouter(prefix="/schemas", tags=["schemas"])
health_router = APIRouter(tags=["health"])


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        tracing.configure_tracing(service_name="parsehawk-api")
        container = build_container()
        # Not every deployment starts through the CLI (Docker runs uvicorn
        # directly), so the API guarantees the fixed providers and prebuilt
        # extractors itself. Idempotent: existing operator config survives.
        seed_prebuilt_data_in_container(container)
        app.state.container = container
        try:
            yield
        finally:
            container.close()

    app = FastAPI(
        title="ParseHawk API",
        summary="Local-first document extraction API",
        description=(
            "Turn PDFs, images, scans, Markdown, and text into validated JSON. "
            "ParseHawk is self-hosted and exposes the same local API used by its CLI and web UI."
        ),
        version=version("parsehawk"),
        contact={
            "name": "ParseHawk support",
            "url": "https://github.com/parsehawk/parsehawk/issues",
        },
        license_info={"name": "Apache License 2.0", "identifier": "Apache-2.0"},
        servers=[
            {
                "url": "http://127.0.0.1:8000",
                "description": "Default local ParseHawk API",
            }
        ],
        openapi_tags=OPENAPI_TAGS,
        responses={500: SERVER_ERROR_RESPONSE},
        lifespan=lifespan,
    )

    @app.exception_handler(NotFoundError)
    async def not_found_handler(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValidationFailure)
    async def validation_handler(_: Request, exc: ValidationFailure) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ProviderRequestError)
    async def provider_request_handler(_: Request, exc: ProviderRequestError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API request error", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

    api_router = APIRouter(prefix="/v1")
    api_router.include_router(files_router)
    api_router.include_router(extractors_router)
    api_router.include_router(providers_router)
    api_router.include_router(jobs_router)
    api_router.include_router(schemas_router)
    app.include_router(health_router)
    app.include_router(api_router)

    generated_openapi = app.openapi

    def openapi_with_explicit_security() -> dict[str, Any]:
        schema = generated_openapi()
        # ParseHawk currently relies on host/network isolation instead of an API
        # authentication scheme. Keep that posture explicit for SDK generators.
        schema["security"] = []
        return schema

    app.openapi = cast(Any, openapi_with_explicit_security)
    return app


@health_router.get(
    "/health",
    operation_id="getHealth",
    summary="Check API health",
    description="Return a lightweight liveness response without accessing the database or model runtime.",
)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@health_router.get(
    "/",
    operation_id="getApiRoot",
    summary="Discover the API",
    description="Return a welcome message and the canonical developer documentation URL.",
)
async def root() -> RootResponse:
    return RootResponse(
        message=(
            "Welcome to the ParseHawk API! Documentation is available at https://docs.parsehawk.com"
        )
    )


@schemas_router.post(
    "/validate",
    operation_id="validateSchema",
    summary="Validate an extraction schema",
    description=(
        "Check a JSON Schema against the ParseHawk authoring dialect and return its canonical form "
        "plus machine-readable diagnostics."
    ),
    responses={422: VALIDATION_ERROR_RESPONSE},
    openapi_extra={
        "externalDocs": {
            "description": "ParseHawk extraction schema dialect",
            "url": "https://docs.parsehawk.com/schemas/parsehawk-extraction-schema.schema.json",
        }
    },
)
def validate_schema(request: ValidateSchemaRequest) -> ValidateSchemaResponse:
    result = validate_extraction_schema(
        mode=MODE_JSON_SCHEMA,
        json_schema=request.schema_,
    )

    return ValidateSchemaResponse(
        valid=result.valid,
        schema=result.json_schema,
        warnings=[_schema_diagnostic(warning) for warning in result.warnings],
        errors=[_schema_diagnostic(error) for error in result.errors],
    )


@files_router.post(
    "",
    operation_id="uploadFile",
    summary="Upload a file",
    description="Store a document locally and return metadata for use in extraction jobs.",
    status_code=status.HTTP_201_CREATED,
    responses={422: VALIDATION_ERROR_RESPONSE},
    openapi_extra={
        "x-codeSamples": [
            {
                "lang": "bash",
                "label": "curl",
                "source": """API="${PARSEHAWK_API_URL:-http://127.0.0.1:8000}"
curl --fail --silent --show-error \\
  --request POST "$API/v1/files" \\
  --form "upload=@document.pdf;type=application/pdf" | jq .""",
            }
        ]
    },
)
async def upload_file(upload: UploadFileDep, container: ContainerDep) -> FileResponse:
    content = await upload.read()
    record = container.file_service.upload(
        file_name=upload.filename or "upload.bin",
        content_type=upload.content_type or "application/octet-stream",
        content=content,
    )
    return FileResponse.from_domain(record)


@files_router.get(
    "",
    operation_id="listFiles",
    summary="List files",
    description="List metadata for every uploaded and built-in example file.",
)
def list_files(container: ContainerDep) -> list[FileResponse]:
    return [FileResponse.from_domain(file) for file in container.file_service.list()]


@files_router.get(
    "/{file_id}",
    operation_id="getFile",
    summary="Get file metadata",
    description="Retrieve metadata for one stored file without returning its content.",
    responses={404: NOT_FOUND_RESPONSE},
)
def get_file(
    file_id: Annotated[str, Path(description="Immutable file identifier.")],
    container: ContainerDep,
) -> FileResponse:
    return FileResponse.from_domain(container.file_service.get(file_id))


@files_router.get(
    "/{file_id}/content",
    operation_id="downloadFileContent",
    summary="Download file content",
    description="Stream the original stored bytes with their recorded media type and filename.",
    response_class=FastAPIFileResponse,
    responses={
        200: {
            "description": "Original file bytes.",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        },
        404: NOT_FOUND_RESPONSE,
    },
    openapi_extra={
        "x-codeSamples": [
            {
                "lang": "bash",
                "label": "curl",
                "source": """API="${PARSEHAWK_API_URL:-http://127.0.0.1:8000}"
curl --fail --silent --show-error \\
  "$API/v1/files/file_.../content" \\
  --output document.pdf""",
            }
        ]
    },
)
def get_file_content(
    file_id: Annotated[str, Path(description="Immutable file identifier.")],
    container: ContainerDep,
) -> FastAPIFileResponse:
    file = container.file_service.get(file_id)
    path = container.storage.resolve_path(file.storage_path)
    if not path.is_file():
        raise NotFoundError("file content", file_id)
    return FastAPIFileResponse(
        path=path,
        filename=file.file_name,
        media_type=file.content_type,
        content_disposition_type="inline",
    )


@files_router.delete(
    "/{file_id}",
    operation_id="deleteFile",
    summary="Delete a file",
    description="Delete one stored file and its local content.",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: NOT_FOUND_RESPONSE},
)
def delete_file(
    file_id: Annotated[str, Path(description="Immutable file identifier.")],
    container: ContainerDep,
) -> None:
    container.file_service.delete(file_id)


@extractors_router.post(
    "",
    operation_id="createExtractor",
    summary="Create an extractor",
    description="Create a reusable extraction definition from instructions, a schema, and optional examples.",
    status_code=status.HTTP_201_CREATED,
    responses={422: VALIDATION_ERROR_RESPONSE},
)
def create_extractor(request: CreateExtractorRequest, container: ContainerDep) -> ExtractorResponse:
    extractor = container.extractor_service.create(
        name=request.name,
        display_name=request.display_name,
        instructions=request.instructions,
        reasoning_effort=request.reasoning_effort,
        provider_name=request.provider_name,
        model=request.model,
        schema=request.schema_,
        examples=[example.model_dump() for example in request.examples],
    )
    return ExtractorResponse.from_domain(extractor)


@extractors_router.get(
    "",
    operation_id="listExtractors",
    summary="List extractors",
    description="List custom and built-in extraction definitions.",
)
def list_extractors(container: ContainerDep) -> list[ExtractorResponse]:
    return [
        ExtractorResponse.from_domain(extractor) for extractor in container.extractor_service.list()
    ]


@extractors_router.get(
    "/{extractor_ref}",
    operation_id="getExtractor",
    summary="Get an extractor",
    description="Retrieve an extractor by immutable ID or stable name.",
    responses={404: NOT_FOUND_RESPONSE},
)
def get_extractor(
    extractor_ref: Annotated[str, Path(description="Extractor ID or stable name.")],
    container: ContainerDep,
) -> ExtractorResponse:
    return ExtractorResponse.from_domain(container.extractor_service.get_by_ref(extractor_ref))


@extractors_router.patch(
    "/{extractor_ref}",
    operation_id="updateExtractor",
    summary="Update an extractor",
    description="Partially update a custom extractor while preserving omitted fields.",
    responses={404: NOT_FOUND_RESPONSE, 422: VALIDATION_ERROR_RESPONSE},
)
def update_extractor(
    extractor_ref: Annotated[str, Path(description="Extractor ID or stable name.")],
    request: UpdateExtractorRequest,
    container: ContainerDep,
) -> ExtractorResponse:
    extractor = container.extractor_service.update(
        extractor_ref,
        display_name=request.display_name,
        instructions=request.instructions,
        reasoning_effort=request.reasoning_effort
        if "reasoning_effort" in request.model_fields_set
        else NOT_PROVIDED,
        provider_name=request.provider_name,
        model=request.model if "model" in request.model_fields_set else NOT_PROVIDED,
        schema=request.schema_,
        examples=[example.model_dump() for example in request.examples]
        if request.examples is not None
        else None,
    )
    return ExtractorResponse.from_domain(extractor)


@extractors_router.put(
    "/{extractor_ref}",
    operation_id="upsertExtractor",
    summary="Create or replace an extractor",
    description="Create a named extractor when absent or replace its complete definition when present.",
    responses={422: VALIDATION_ERROR_RESPONSE},
)
def upsert_extractor(
    extractor_ref: Annotated[str, Path(description="Stable extractor name.")],
    request: UpsertExtractorRequest,
    container: ContainerDep,
) -> ExtractorResponse:
    extractor = container.extractor_service.upsert(
        extractor_ref,
        body_name=request.name,
        display_name=request.display_name,
        instructions=request.instructions,
        reasoning_effort=request.reasoning_effort,
        provider_name=request.provider_name,
        model=request.model,
        schema=request.schema_,
        examples=[example.model_dump() for example in request.examples],
    )
    return ExtractorResponse.from_domain(extractor)


@extractors_router.delete(
    "/{extractor_ref}",
    operation_id="deleteExtractor",
    summary="Delete an extractor",
    description="Delete a custom extractor. Built-in extractors cannot be deleted.",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: NOT_FOUND_RESPONSE, 422: VALIDATION_ERROR_RESPONSE},
)
def delete_extractor(
    extractor_ref: Annotated[str, Path(description="Extractor ID or stable name.")],
    container: ContainerDep,
) -> None:
    container.extractor_service.delete(extractor_ref)


@providers_router.get(
    "",
    operation_id="listProviders",
    summary="List providers",
    description="List all fixed provider slots and their non-secret configuration.",
)
def list_providers(container: ContainerDep) -> list[ProviderResponse]:
    service = container.provider_service
    return [
        ProviderResponse.from_domain(provider, has_api_key=service.has_api_key(provider.name))
        for provider in service.list()
    ]


@providers_router.get(
    "/{name}",
    operation_id="getProvider",
    summary="Get a provider",
    description="Retrieve non-secret configuration for one provider.",
    responses={422: VALIDATION_ERROR_RESPONSE},
)
def get_provider(
    name: Annotated[ProviderName, Path(description="Stable provider name.")],
    container: ContainerDep,
) -> ProviderResponse:
    service = container.provider_service
    provider = service.get(name)
    return ProviderResponse.from_domain(provider, has_api_key=service.has_api_key(name))


@providers_router.patch(
    "/{name}",
    operation_id="configureProvider",
    summary="Configure a provider",
    description="Update a provider endpoint, non-secret settings, or securely stored API key.",
    responses={422: VALIDATION_ERROR_RESPONSE},
)
def configure_provider(
    name: Annotated[ProviderName, Path(description="Stable provider name.")],
    request: ConfigureProviderRequest,
    container: ContainerDep,
) -> ProviderResponse:
    service = container.provider_service
    provider = service.configure(
        name,
        base_url=request.base_url,
        configuration=request.configuration,
        api_key=request.api_key,
        api_key_env=request.api_key_env,
    )
    return ProviderResponse.from_domain(provider, has_api_key=service.has_api_key(name))


@providers_router.get(
    "/{name}/models",
    operation_id="listProviderModels",
    summary="List provider models",
    description="Query the configured provider and return the model identifiers it currently advertises.",
    responses={400: PROVIDER_ERROR_RESPONSE, 422: VALIDATION_ERROR_RESPONSE},
)
def list_provider_models(
    name: Annotated[ProviderName, Path(description="Stable provider name.")],
    container: ContainerDep,
) -> ProviderModelsResponse:
    provider = container.provider_service.get(name)
    api_key = container.secrets.get(name) or "EMPTY"
    if provider.name == ProviderName.MICROSOFT_FOUNDRY:
        models = list_foundry_chat_deployments(
            project_url=provider.project_url,
            api_key=api_key,
        )
    elif provider.name == ProviderName.OPENAI:
        models = list_openai_chat_models(
            base_url=provider.base_url,
            api_key=api_key,
        )
    else:
        models = list_models(
            base_url=provider.base_url,
            api_key=api_key,
        )
    return ProviderModelsResponse(models=models)


@jobs_router.post(
    "",
    operation_id="createJob",
    summary="Create a job",
    description="Enqueue extraction for one uploaded file or inline text input.",
    status_code=status.HTTP_201_CREATED,
    responses={404: NOT_FOUND_RESPONSE, 422: VALIDATION_ERROR_RESPONSE},
    openapi_extra={
        "x-codeSamples": [
            {
                "lang": "bash",
                "label": "curl",
                "source": """API="${PARSEHAWK_API_URL:-http://127.0.0.1:8000}"
curl --fail --silent --show-error \\
  --request POST "$API/v1/jobs" \\
  --header "Content-Type: application/json" \\
  --data '{"extractor_name":"receipt","file_id":"file_..."}' | jq .""",
            }
        ]
    },
)
def create_job(request: CreateJobRequest, container: ContainerDep) -> JobResponse:
    job = container.job_service.create(
        extractor_id=request.extractor_id,
        extractor_name=request.extractor_name,
        file_id=request.file_id,
        text=request.text,
    )
    telemetry.track_run_started(
        input_type="file" if request.file_id is not None else "text",
        data_dir=container.settings.data_dir,
    )
    return JobResponse.from_domain(job)


@jobs_router.get(
    "",
    operation_id="listJobs",
    summary="List jobs",
    description="List extraction jobs, optionally filtered by extractor ID or stable name.",
)
def list_jobs(
    container: ContainerDep,
    extractor_id: Annotated[
        str | None,
        Query(description="Only return jobs for this immutable extractor ID."),
    ] = None,
    extractor_name: Annotated[
        str | None,
        Query(description="Only return jobs for this stable extractor name."),
    ] = None,
) -> list[JobResponse]:
    return [
        JobResponse.from_domain(job)
        for job in container.job_service.list(
            extractor_id=extractor_id,
            extractor_name=extractor_name,
        )
    ]


@jobs_router.get(
    "/{job_id}",
    operation_id="getJob",
    summary="Get a job",
    description="Retrieve the current state, result, or failure details for one extraction job.",
    responses={404: NOT_FOUND_RESPONSE},
    openapi_extra={
        "x-codeSamples": [
            {
                "lang": "bash",
                "label": "curl",
                "source": """API="${PARSEHAWK_API_URL:-http://127.0.0.1:8000}"
curl --fail --silent --show-error "$API/v1/jobs/job_..." | jq .""",
            }
        ]
    },
)
def get_job(
    job_id: Annotated[str, Path(description="Immutable job identifier.")],
    container: ContainerDep,
) -> JobResponse:
    return JobResponse.from_domain(container.job_service.get(job_id))


@jobs_router.post(
    "/{job_id}/cancel",
    operation_id="cancelJob",
    summary="Cancel a job",
    description="Request cancellation and return the resulting job state.",
    responses={404: NOT_FOUND_RESPONSE, 422: VALIDATION_ERROR_RESPONSE},
)
def cancel_job(
    job_id: Annotated[str, Path(description="Immutable job identifier.")],
    container: ContainerDep,
) -> JobResponse:
    return JobResponse.from_domain(container.job_service.cancel(job_id))


@jobs_router.delete(
    "/{job_id}",
    operation_id="deleteJob",
    summary="Delete a job",
    description=(
        "Delete a terminal job immediately, or return 202 while cancellation completes for a running job."
    ),
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_202_ACCEPTED: {"description": "Cancellation and deletion accepted."},
        404: NOT_FOUND_RESPONSE,
    },
)
def delete_job(
    job_id: Annotated[str, Path(description="Immutable job identifier.")],
    container: ContainerDep,
) -> Response:
    result = container.job_service.delete(job_id)
    if result == DeleteJobResult.ACCEPTED:
        return Response(status_code=status.HTTP_202_ACCEPTED)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


app = create_app()


def _schema_diagnostic(diagnostic: CoreSchemaDiagnostic) -> SchemaDiagnostic:
    return SchemaDiagnostic(
        message=diagnostic.message,
        code=diagnostic.code,
        path=diagnostic.path,
    )
