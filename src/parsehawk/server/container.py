from __future__ import annotations

import sqlite3

from parsehawk.config import Settings
from parsehawk.core.application.services import (
    ExtractorService,
    FileService,
    JobService,
    ProviderService,
)
from parsehawk.server.adapters.persistence.migrations import migrations_disabled
from parsehawk.server.adapters.persistence.sqlite import (
    SQLiteExtractorRepository,
    SQLiteFileRepository,
    SQLiteJobRepository,
    SQLiteProviderRepository,
    SQLiteSecretStore,
    connect,
    init_db,
)
from parsehawk.server.adapters.security import load_secret_cipher
from parsehawk.server.adapters.storage.local import LocalFileStorage
from parsehawk.server.runtime.inference.factory import EngineFactory


class Container:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.conn = connect(settings.resolved_database_path)
        # Serving processes bring the schema up to date on construction. The
        # PARSEHAWK_SKIP_MIGRATIONS opt-out lets an operator take ownership of when
        # migrations run (e.g. via `parsehawk migrate`) instead of auto-applying.
        if not migrations_disabled():
            init_db(self.conn)
        self.storage = LocalFileStorage(
            settings.data_dir,
            pdf_max_pages=settings.pdf_max_pages,
            pdf_render_dpi=settings.pdf_render_dpi,
        )
        self.files = SQLiteFileRepository(self.conn)
        self.extractors = SQLiteExtractorRepository(self.conn)
        self.jobs = SQLiteJobRepository(self.conn)
        self.providers = SQLiteProviderRepository(self.conn)
        self.secrets = SQLiteSecretStore(
            self.conn, load_secret_cipher(settings.data_dir, settings.secret_key)
        )
        self.engine_factory = EngineFactory(self.providers, self.secrets, settings)
        self.file_service = FileService(self.files, self.storage)
        self.extractor_service = ExtractorService(
            self.extractors, self.files, default_model=settings.vllm_model
        )
        self.provider_service = ProviderService(self.providers, self.secrets)
        self.job_service = JobService(
            self.jobs, self.files, self.extractors, self.storage, self.engine_factory
        )

    def close(self) -> None:
        self.conn.close()


def build_container(settings: Settings | None = None) -> Container:
    return Container(settings or Settings.from_env())


def close_safely(conn: sqlite3.Connection) -> None:
    conn.close()
