from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Protocol, Self

from parsehawk.core.domain.models import (
    ExtractionJob,
    Extractor,
    File,
    JobStatus,
    ParseJob,
    Parser,
    ParserSnapshot,
    Provider,
    ProviderName,
    ReasoningEffort,
)


@dataclass(frozen=True)
class PreparedImage:
    storage_path: str
    content_type: str
    page_number: int | None = None


@dataclass(frozen=True)
class PreparedDocument:
    text: str
    storage_path: str
    content_type: str
    images: list[PreparedImage]


@dataclass(frozen=True)
class ResolvedExecutionConfig:
    provider_name: ProviderName
    model: str


@dataclass(frozen=True)
class ResolvedParsingConfig:
    provider_name: ProviderName
    model: str
    reasoning_effort: ReasoningEffort | None
    model_adapter: str


class FileRepository(Protocol):  # pragma: no cover
    def save(self, file: File) -> None: ...

    def list(self) -> List[File]: ...

    def get(self, file_id: str) -> File | None: ...

    def delete(self, file_id: str) -> None: ...


class ExtractorRepository(Protocol):  # pragma: no cover
    def save(self, extractor: Extractor) -> None: ...

    def list(self) -> List[Extractor]: ...

    def get(self, extractor_id: str) -> Extractor | None: ...

    def get_by_name(self, name: str) -> Extractor | None: ...

    def delete(self, extractor_id: str) -> None: ...


class ParserRepository(Protocol):  # pragma: no cover
    def save(self, parser: Parser) -> None: ...

    def list(self) -> List[Parser]: ...

    def get(self, parser_id: str) -> Parser | None: ...

    def get_by_name(self, name: str) -> Parser | None: ...

    def delete(self, parser_id: str) -> None: ...


class ExtractionJobRepository(Protocol):  # pragma: no cover
    def save(self, job: ExtractionJob) -> None: ...

    def save_if_status(self, job: ExtractionJob, expected: Iterable[JobStatus]) -> bool: ...

    def list(self, extractor_id: str | None = None) -> List[ExtractionJob]: ...

    def get(self, job_id: str) -> ExtractionJob | None: ...

    def delete(self, job_id: str) -> None: ...

    def delete_if_status(self, job_id: str, expected: Iterable[JobStatus]) -> bool: ...

    def claim_next_queued(self) -> ExtractionJob | None: ...

    def has_for_file(self, file_id: str) -> bool: ...

    def has_for_extractor(self, extractor_id: str) -> bool: ...


class ParseJobRepository(Protocol):  # pragma: no cover
    def save(self, job: ParseJob) -> None: ...

    def save_if_status(self, job: ParseJob, expected: Iterable[JobStatus]) -> bool: ...

    def list(self, parser_id: str | None = None) -> List[ParseJob]: ...

    def get(self, job_id: str) -> ParseJob | None: ...

    def delete(self, job_id: str) -> None: ...

    def delete_if_status(self, job_id: str, expected: Iterable[JobStatus]) -> bool: ...

    def claim_next_queued(self) -> ParseJob | None: ...

    def has_for_file(self, file_id: str) -> bool: ...

    def has_for_parser(self, parser_id: str) -> bool: ...


class ProviderRepository(Protocol):  # pragma: no cover
    def save(self, provider: Provider) -> None: ...

    def list(self) -> List[Provider]: ...

    def get(self, name: ProviderName) -> Provider | None: ...


class SecretStore(Protocol):  # pragma: no cover
    def put(self, provider_name: ProviderName, api_key: str) -> None: ...

    def get(self, provider_name: ProviderName) -> str | None: ...

    def delete(self, provider_name: ProviderName) -> None: ...

    def has(self, provider_name: ProviderName) -> bool: ...


class UnitOfWork(Protocol):  # pragma: no cover
    """Application transaction boundary independent of a database toolkit."""

    files: FileRepository
    extractors: ExtractorRepository
    parsers: ParserRepository
    extraction_jobs: ExtractionJobRepository
    parse_jobs: ParseJobRepository
    providers: ProviderRepository
    secrets: SecretStore

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class UnitOfWorkFactory(Protocol):  # pragma: no cover
    def __call__(self, *, write: bool = False) -> UnitOfWork: ...


class FileStorage(Protocol):  # pragma: no cover
    def write_file(self, file_id: str, file_name: str, content: bytes) -> str: ...

    def read_text(self, file: File) -> str: ...

    def prepare_document(self, file: File) -> PreparedDocument: ...

    def delete_file(self, file: File) -> None: ...


class ExtractionEngine(Protocol):  # pragma: no cover
    def extract(
        self,
        request: "ExtractionRequest",
        cancellation_check: Callable[[], bool] | None = None,
    ) -> "ExtractionResponse": ...


class EngineFactory(Protocol):  # pragma: no cover
    def resolve_extractor_config(self, extractor: Extractor) -> ResolvedExecutionConfig: ...

    def for_extractor(
        self,
        extractor: Extractor,
        *,
        provider: Provider | None = None,
        api_key: str | None = None,
    ) -> ExtractionEngine: ...


class ParsingEngine(Protocol):  # pragma: no cover
    def parse_page(
        self,
        request: "ParsingRequest",
        cancellation_check: Callable[[], bool] | None = None,
    ) -> "ParsingResponse": ...


class ParsingEngineFactory(Protocol):  # pragma: no cover
    def resolve_parser_config(self, parser: ParserSnapshot) -> ResolvedParsingConfig: ...

    def for_parser(
        self,
        parser: ParserSnapshot,
        *,
        provider: Provider | None = None,
        api_key: str | None = None,
    ) -> ParsingEngine: ...


class ExtractionRequest:
    def __init__(
        self,
        *,
        source_text: str,
        source_storage_path: str | None = None,
        source_content_type: str | None = None,
        source_images: list[PreparedImage] | None = None,
        instructions: str,
        reasoning_effort: str | None = None,
        schema: dict,
        examples: list[dict],
    ) -> None:
        self.source_text = source_text
        self.source_storage_path = source_storage_path
        self.source_content_type = source_content_type
        self.source_images = source_images or []
        self.instructions = instructions
        self.reasoning_effort = reasoning_effort
        self.schema = schema
        self.examples = examples


class ExtractionResponse:
    def __init__(
        self,
        *,
        data: dict,
    ) -> None:
        self.data = data


class ParsingRequest:
    def __init__(
        self,
        *,
        image: PreparedImage,
        instructions: str,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> None:
        self.image = image
        self.instructions = instructions
        self.reasoning_effort = reasoning_effort


class ParsingResponse:
    def __init__(self, *, content: str) -> None:
        self.content = content
