from __future__ import annotations

import sqlite3

from parsehawk.config import Settings
from parsehawk.core.application.ports import (
    ExtractionEngine,
    ExtractionRequest,
    ExtractionResponse,
)
from parsehawk.core.application.services import ExtractorService, FileService, JobService
from parsehawk.server.adapters.persistence.sqlite import (
    SQLiteExtractorRepository,
    SQLiteFileRepository,
    SQLiteJobRepository,
    connect,
    init_db,
)
from parsehawk.server.adapters.storage.local import LocalFileStorage
from parsehawk.server.runtime.inference.runtime_engine import (
    NuExtractRuntimeConfig,
    NuExtractRuntimeEngine,
)


class UnavailableEngine:
    """Engine placeholder used when no model runtime is configured.

    Building the container must not require a live model (seeding, lifecycle
    checks), so an unconfigured engine is not an error at construction time. The
    error is deferred to extraction, where it surfaces as a clear, actionable
    message instead of silently falling back to a fake engine.
    """

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def extract(self, request: ExtractionRequest) -> ExtractionResponse:
        raise RuntimeError(self._reason)


class Container:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.conn = connect(settings.resolved_database_path)
        init_db(self.conn)
        self.storage = LocalFileStorage(
            settings.data_dir,
            pdf_max_pages=settings.pdf_max_pages,
            pdf_render_dpi=settings.pdf_render_dpi,
        )
        self.files = SQLiteFileRepository(self.conn)
        self.extractors = SQLiteExtractorRepository(self.conn)
        self.jobs = SQLiteJobRepository(self.conn)
        self.engine = build_engine(settings)
        self.file_service = FileService(self.files, self.storage)
        self.extractor_service = ExtractorService(self.extractors, self.files)
        self.job_service = JobService(
            self.jobs, self.files, self.extractors, self.storage, self.engine
        )

    def close(self) -> None:
        self.conn.close()


def build_engine(settings: Settings) -> ExtractionEngine:
    if settings.inference_engine == "vllm":
        return NuExtractRuntimeEngine(
            NuExtractRuntimeConfig(
                model=settings.vllm_model,
                base_url=settings.vllm_base_url,
                max_tokens=settings.vllm_max_tokens,
                temperature=settings.vllm_temperature,
                timeout_seconds=settings.vllm_timeout_seconds,
                include_enable_thinking_field=False,
                log_model_io=settings.log_model_io,
            )
        )
    return UnavailableEngine(
        f"no model runtime is configured (inference_engine={settings.inference_engine!r}). "
        "Run `parsehawk start` on macOS Apple Silicon or Linux x86_64 with an NVIDIA GPU, "
        "or set PARSEHAWK_INFERENCE_ENGINE to 'vllm'."
    )


def build_container(settings: Settings | None = None) -> Container:
    return Container(settings or Settings.from_env())


def close_safely(conn: sqlite3.Connection) -> None:
    conn.close()
