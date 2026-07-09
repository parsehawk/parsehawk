from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, cast

from fastapi import APIRouter, Depends, FastAPI, File, Query, Request, Response, UploadFile, status
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
    ConfigureProviderRequest,
    CreateExtractorRequest,
    CreateJobRequest,
    ExtractorResponse,
    FileResponse,
    JobResponse,
    ProviderModelsResponse,
    ProviderResponse,
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


def get_container(request: Request) -> Container:
    return cast(Container, request.app.state.container)


ContainerDep = Annotated[Container, Depends(get_container)]
UploadFileDep = Annotated[UploadFile, File()]

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

    app = FastAPI(title="ParseHawk", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(NotFoundError)
    async def not_found_handler(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValidationFailure)
    async def validation_handler(_: Request, exc: ValidationFailure) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ProviderRequestError)
    async def provider_request_handler(_: Request, exc: ProviderRequestError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    api_router = APIRouter(prefix="/v1")
    api_router.include_router(files_router)
    api_router.include_router(extractors_router)
    api_router.include_router(providers_router)
    api_router.include_router(jobs_router)
    api_router.include_router(schemas_router)
    app.include_router(health_router)
    app.include_router(api_router)
    return app


@health_router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@health_router.get("/")
async def root() -> dict[str, str]:
    return {
        "message": "Welcome to the ParseHawk API! Documentation is available at https://docs.parsehawk.com"
    }


@schemas_router.post(
    "/validate",
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


@files_router.post("", status_code=status.HTTP_201_CREATED)
async def upload_file(upload: UploadFileDep, container: ContainerDep) -> FileResponse:
    content = await upload.read()
    record = container.file_service.upload(
        file_name=upload.filename or "upload.bin",
        content_type=upload.content_type or "application/octet-stream",
        content=content,
    )
    return FileResponse.from_domain(record)


@files_router.get("")
def list_files(container: ContainerDep) -> list[FileResponse]:
    return [FileResponse.from_domain(file) for file in container.file_service.list()]


@files_router.get("/{file_id}")
def get_file(file_id: str, container: ContainerDep) -> FileResponse:
    return FileResponse.from_domain(container.file_service.get(file_id))


@files_router.get("/{file_id}/content")
def get_file_content(file_id: str, container: ContainerDep) -> FastAPIFileResponse:
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


@files_router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(file_id: str, container: ContainerDep) -> None:
    container.file_service.delete(file_id)


@extractors_router.post("", status_code=status.HTTP_201_CREATED)
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


@extractors_router.get("")
def list_extractors(container: ContainerDep) -> list[ExtractorResponse]:
    return [
        ExtractorResponse.from_domain(extractor) for extractor in container.extractor_service.list()
    ]


@extractors_router.get("/{extractor_ref}")
def get_extractor(extractor_ref: str, container: ContainerDep) -> ExtractorResponse:
    return ExtractorResponse.from_domain(container.extractor_service.get_by_ref(extractor_ref))


@extractors_router.patch("/{extractor_ref}")
def update_extractor(
    extractor_ref: str,
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


@extractors_router.put("/{extractor_ref}")
def upsert_extractor(
    extractor_ref: str,
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


@extractors_router.delete("/{extractor_ref}", status_code=status.HTTP_204_NO_CONTENT)
def delete_extractor(extractor_ref: str, container: ContainerDep) -> None:
    container.extractor_service.delete(extractor_ref)


@providers_router.get("")
def list_providers(container: ContainerDep) -> list[ProviderResponse]:
    service = container.provider_service
    return [
        ProviderResponse.from_domain(provider, has_api_key=service.has_api_key(provider.name))
        for provider in service.list()
    ]


@providers_router.get("/{name}")
def get_provider(name: ProviderName, container: ContainerDep) -> ProviderResponse:
    service = container.provider_service
    provider = service.get(name)
    return ProviderResponse.from_domain(provider, has_api_key=service.has_api_key(name))


@providers_router.patch("/{name}")
def configure_provider(
    name: ProviderName, request: ConfigureProviderRequest, container: ContainerDep
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


@providers_router.get("/{name}/models")
def list_provider_models(name: ProviderName, container: ContainerDep) -> ProviderModelsResponse:
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


@jobs_router.post("", status_code=status.HTTP_201_CREATED)
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


@jobs_router.get("")
def list_jobs(
    container: ContainerDep,
    extractor_id: Annotated[str | None, Query()] = None,
    extractor_name: Annotated[str | None, Query()] = None,
) -> list[JobResponse]:
    return [
        JobResponse.from_domain(job)
        for job in container.job_service.list(
            extractor_id=extractor_id,
            extractor_name=extractor_name,
        )
    ]


@jobs_router.get("/{job_id}")
def get_job(job_id: str, container: ContainerDep) -> JobResponse:
    return JobResponse.from_domain(container.job_service.get(job_id))


@jobs_router.post("/{job_id}/cancel")
def cancel_job(job_id: str, container: ContainerDep) -> JobResponse:
    return JobResponse.from_domain(container.job_service.cancel(job_id))


@jobs_router.delete(
    "/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={status.HTTP_202_ACCEPTED: {"description": "Deletion accepted"}},
)
def delete_job(job_id: str, container: ContainerDep) -> Response:
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
