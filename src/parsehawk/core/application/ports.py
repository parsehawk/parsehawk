from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Protocol

from parsehawk.core.domain.models import Extractor, File, Job, JobStatus, Provider, ProviderName


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


class JobRepository(Protocol):  # pragma: no cover
    def save(self, job: Job) -> None: ...

    def save_if_status(self, job: Job, expected: Iterable[JobStatus]) -> bool: ...

    def list(self, extractor_id: str | None = None) -> List[Job]: ...

    def get(self, job_id: str) -> Job | None: ...

    def delete(self, job_id: str) -> None: ...

    def delete_if_status(self, job_id: str, expected: Iterable[JobStatus]) -> bool: ...

    def claim_next_queued(self) -> Job | None: ...


class ProviderRepository(Protocol):  # pragma: no cover
    def save(self, provider: Provider) -> None: ...

    def list(self) -> List[Provider]: ...

    def get(self, name: ProviderName) -> Provider | None: ...


class SecretStore(Protocol):  # pragma: no cover
    def put(self, provider_name: ProviderName, api_key: str) -> None: ...

    def get(self, provider_name: ProviderName) -> str | None: ...

    def delete(self, provider_name: ProviderName) -> None: ...

    def has(self, provider_name: ProviderName) -> bool: ...


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
    def for_extractor(self, extractor: Extractor) -> ExtractionEngine: ...


class ExtractionRequest:
    def __init__(
        self,
        *,
        source_text: str,
        source_storage_path: str | None = None,
        source_content_type: str | None = None,
        source_images: list[PreparedImage] | None = None,
        instructions: str,
        enable_thinking: bool,
        schema: dict,
        examples: list[dict],
    ) -> None:
        self.source_text = source_text
        self.source_storage_path = source_storage_path
        self.source_content_type = source_content_type
        self.source_images = source_images or []
        self.instructions = instructions
        self.enable_thinking = enable_thinking
        self.schema = schema
        self.examples = examples


class ExtractionResponse:
    def __init__(
        self,
        *,
        data: dict,
    ) -> None:
        self.data = data
