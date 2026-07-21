from __future__ import annotations

from parsehawk.config import Settings
from parsehawk.core.application.services import (
    ExtractorService,
    FileService,
    JobService,
    ProviderService,
)
from parsehawk.server.adapters.persistence.migrations import migrations_disabled
from parsehawk.server.adapters.persistence.sqlite import (
    DEFAULT_BUSY_TIMEOUT_MS,
    SQLiteUnitOfWorkFactory,
    create_sqlite_engine,
    init_engine,
)
from parsehawk.server.adapters.security import load_secret_cipher
from parsehawk.server.adapters.storage.local import LocalFileStorage
from parsehawk.server.runtime.inference.factory import EngineFactory


class Container:
    def __init__(
        self,
        settings: Settings,
        *,
        sqlite_busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        self.settings = settings
        self.engine = create_sqlite_engine(
            settings.resolved_database_path,
            busy_timeout_ms=sqlite_busy_timeout_ms,
        )
        # Serving processes bring the schema up to date on construction. The
        # PARSEHAWK_SKIP_MIGRATIONS opt-out lets an operator take ownership of when
        # migrations run (e.g. via `parsehawk migrate`) instead of auto-applying.
        if not migrations_disabled():
            init_engine(self.engine)
        self.storage = LocalFileStorage(
            settings.data_dir,
            pdf_max_pages=settings.pdf_max_pages,
            pdf_render_dpi=settings.pdf_render_dpi,
        )
        self.uow_factory = SQLiteUnitOfWorkFactory(
            self.engine,
            load_secret_cipher(settings.data_dir, settings.secret_key),
        )
        self.engine_factory = EngineFactory(settings)
        self.file_service = FileService(self.uow_factory, self.storage)
        self.extractor_service = ExtractorService(
            self.uow_factory, default_model=settings.vllm_model
        )
        self.provider_service = ProviderService(self.uow_factory)
        self.job_service = JobService(self.uow_factory, self.storage, self.engine_factory)

    def close(self) -> None:
        self.uow_factory.close()


def build_container(settings: Settings | None = None) -> Container:
    return Container(settings or Settings.from_env())
