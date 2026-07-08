from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterator

import pytest

from parsehawk.core.domain.models import extractor_name_suffix
from parsehawk.server.adapters.persistence.migrations import (
    apply_pending,
    discover_migrations,
    migration_status,
    migrations_disabled,
)
from parsehawk.server.adapters.persistence.migrations.runner import (
    _register_functions,
    _split_statements,
)
from parsehawk.server.adapters.persistence.sqlite import connect, init_db

# Migration ids (each ``.sql`` filename without the suffix), in apply order.
BASELINE_ID = "20260701092442_initial_schema"
ADD_PROVIDERS_ID = "20260701121138_add_providers"
EXTRACTOR_DISPLAY_NAMES_ID = "20260702160000_extractor_display_names"
PROVIDER_CONFIGURATION_ID = "20260708093000_provider_configuration"
REMOVE_FOUNDRY_API_VERSION_CONFIG_ID = "20260708112000_remove_foundry_api_version_config"
INHERIT_OPENAI_COMPATIBLE_DEFAULT_MODEL_ID = (
    "20260708130000_inherit_openai_compatible_default_model"
)
ALL_MIGRATION_IDS = [
    BASELINE_ID,
    ADD_PROVIDERS_ID,
    EXTRACTOR_DISPLAY_NAMES_ID,
    PROVIDER_CONFIGURATION_ID,
    REMOVE_FOUNDRY_API_VERSION_CONFIG_ID,
    INHERIT_OPENAI_COMPATIBLE_DEFAULT_MODEL_ID,
]

# The full current schema after all migrations. ALTER-added columns
# (provider_name, model) are appended after the original extractor columns.
EXPECTED_COLUMNS = {
    "files": [
        "id",
        "file_name",
        "content_type",
        "size_bytes",
        "sha256",
        "storage_path",
        "source",
        "seed_key",
        "seed_version",
        "created_at",
    ],
    "extractors": [
        "id",
        "name",
        "display_name",
        "instructions",
        "enable_thinking",
        "schema",
        "examples",
        "source",
        "seed_key",
        "seed_version",
        "created_at",
        "updated_at",
        "provider_name",
        "model",
    ],
    "jobs": [
        "id",
        "extractor_id",
        "file_id",
        "source_text",
        "status",
        "result",
        "error",
        "created_at",
        "started_at",
        "completed_at",
    ],
    "providers": [
        "name",
        "base_url",
        "created_at",
        "updated_at",
        "configuration",
    ],
    "provider_secrets": [
        "provider_name",
        "ciphertext",
        "created_at",
        "updated_at",
    ],
}


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "parsehawk.db")
    try:
        yield connection
    finally:
        connection.close()


def test_migrations_are_named_with_timestamp_prefix() -> None:
    migrations = discover_migrations()

    assert migrations, "expected at least the baseline migration to be discovered"
    assert [migration.id for migration in migrations] == sorted(m.id for m in migrations)
    assert migrations[0].id == BASELINE_ID


def test_baseline_applied_to_fresh_db_matches_current_schema(conn: sqlite3.Connection) -> None:
    applied = apply_pending(conn)

    assert applied == ALL_MIGRATION_IDS
    for table, expected in EXPECTED_COLUMNS.items():
        assert columns(conn, table) == expected
    assert indexes(conn, "jobs") == {
        "idx_jobs_extractor_id",
        "idx_jobs_status_created_at",
    }
    assert "idx_extractors_name" in indexes(conn, "extractors")
    assert foreign_keys(conn, "jobs") == {
        ("file_id", "files", "id", "CASCADE"),
        ("extractor_id", "extractors", "id", "CASCADE"),
    }


def test_apply_pending_is_idempotent(conn: sqlite3.Connection) -> None:
    assert apply_pending(conn) == ALL_MIGRATION_IDS

    assert apply_pending(conn) == []

    status = migration_status(conn)
    assert status.applied == ALL_MIGRATION_IDS
    assert status.pending == []


def test_migration_status_reports_pending_before_apply(conn: sqlite3.Connection) -> None:
    status = migration_status(conn)

    assert status.applied == []
    assert status.pending == ALL_MIGRATION_IDS


def test_baseline_converges_existing_v012_db_without_data_loss(conn: sqlite3.Connection) -> None:
    # Simulate a v0.1.2 database: baseline tables present with real data (applied
    # via the migration's own SQL), but no migration ledger.
    baseline = next(m for m in discover_migrations() if m.id == BASELINE_ID)
    conn.executescript(baseline.path.read_text(encoding="utf-8"))
    conn.execute(
        """
        INSERT INTO extractors (
            id, name, instructions, enable_thinking, schema, examples,
            source, seed_key, seed_version, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("ex_1", "Receipt", "Extract.", 0, "{}", "[]", "custom", None, None, "t0", "t1"),
    )
    conn.commit()
    assert _table_exists(conn, "schema_migrations") is False

    applied = apply_pending(conn)

    assert applied == ALL_MIGRATION_IDS
    assert migration_status(conn).applied == ALL_MIGRATION_IDS
    row = conn.execute(
        "SELECT name, display_name FROM extractors WHERE id = ?", ("ex_1",)
    ).fetchone()
    assert row is not None and tuple(row) == ("receipt", "Receipt")


def test_extractor_name_migration_suffixes_user_collision_with_prebuilt_receipt(
    conn: sqlite3.Connection,
) -> None:
    baseline = next(m for m in discover_migrations() if m.id == BASELINE_ID)
    providers = next(m for m in discover_migrations() if m.id == ADD_PROVIDERS_ID)
    conn.executescript(baseline.path.read_text(encoding="utf-8"))
    conn.executescript(providers.path.read_text(encoding="utf-8"))
    conn.execute("CREATE TABLE schema_migrations (id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.executemany(
        "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)",
        [(BASELINE_ID, "t"), (ADD_PROVIDERS_ID, "t")],
    )
    rows = [
        ("extractor_prebuilt", "Receipt", "prebuilt", "prebuilt:receipt:v1"),
        ("extractor_userabc", "Receipt", "user", None),
    ]
    for extractor_id, name, source, seed_key in rows:
        conn.execute(
            """
            INSERT INTO extractors (
                id, name, instructions, enable_thinking, schema, examples,
                source, seed_key, seed_version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (extractor_id, name, "Extract.", 0, "{}", "[]", source, seed_key, 1, "t0", "t1"),
        )
    conn.commit()

    apply_pending(conn)

    migrated = {
        row["id"]: (row["name"], row["display_name"])
        for row in conn.execute("SELECT id, name, display_name FROM extractors")
    }
    assert migrated["extractor_prebuilt"] == ("receipt", "Receipt")
    assert migrated["extractor_userabc"] == (
        f"receipt-{extractor_name_suffix('extractor_userabc')}",
        "Receipt",
    )


def test_extractor_name_migration_suffixes_sortable_id_collisions(
    conn: sqlite3.Connection,
) -> None:
    baseline = next(m for m in discover_migrations() if m.id == BASELINE_ID)
    providers = next(m for m in discover_migrations() if m.id == ADD_PROVIDERS_ID)
    conn.executescript(baseline.path.read_text(encoding="utf-8"))
    conn.executescript(providers.path.read_text(encoding="utf-8"))
    conn.execute("CREATE TABLE schema_migrations (id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.executemany(
        "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)",
        [(BASELINE_ID, "t"), (ADD_PROVIDERS_ID, "t")],
    )
    extractor_ids = [
        "extractor_01kwjg0q5932zneyp7hhwr57ey",
        "extractor_01kwjg0q5932zneyp7hhwr57ez",
    ]
    for extractor_id in extractor_ids:
        conn.execute(
            """
            INSERT INTO extractors (
                id, name, instructions, enable_thinking, schema, examples,
                source, seed_key, seed_version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                extractor_id,
                "Invoice Extractor",
                "Extract.",
                0,
                "{}",
                "[]",
                "user",
                None,
                None,
                "t0",
                "t1",
            ),
        )
    conn.commit()

    apply_pending(conn)

    names = [row["name"] for row in conn.execute("SELECT name FROM extractors ORDER BY id")]
    assert names == [
        f"invoice-extractor-{extractor_name_suffix(extractor_ids[0])}",
        f"invoice-extractor-{extractor_name_suffix(extractor_ids[1])}",
    ]


def test_extractor_name_migration_preserves_job_foreign_keys(conn: sqlite3.Connection) -> None:
    baseline = next(m for m in discover_migrations() if m.id == BASELINE_ID)
    providers = next(m for m in discover_migrations() if m.id == ADD_PROVIDERS_ID)
    conn.executescript(baseline.path.read_text(encoding="utf-8"))
    conn.executescript(providers.path.read_text(encoding="utf-8"))
    conn.execute("CREATE TABLE schema_migrations (id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.executemany(
        "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)",
        [(BASELINE_ID, "t"), (ADD_PROVIDERS_ID, "t")],
    )
    conn.execute(
        """
        INSERT INTO extractors (
            id, name, instructions, enable_thinking, schema, examples,
            source, seed_key, seed_version, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "extractor_invoice",
            "Invoice Extractor",
            "Extract.",
            0,
            "{}",
            "[]",
            "user",
            None,
            1,
            "t0",
            "t1",
        ),
    )
    conn.execute(
        """
        INSERT INTO jobs (
            id, extractor_id, file_id, source_text, status, result, error,
            created_at, started_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("job_1", "extractor_invoice", None, "text", "completed", "{}", None, "t2", "t3", "t4"),
    )
    conn.commit()

    apply_pending(conn)

    job = conn.execute("SELECT extractor_id FROM jobs WHERE id = ?", ("job_1",)).fetchone()
    extractor = conn.execute(
        "SELECT id, name, display_name FROM extractors WHERE id = ?",
        ("extractor_invoice",),
    ).fetchone()
    assert tuple(job) == ("extractor_invoice",)
    assert tuple(extractor) == ("extractor_invoice", "invoice-extractor", "Invoice Extractor")


def test_provider_configuration_migration_renames_foundry_without_data_loss(
    conn: sqlite3.Connection,
) -> None:
    applied_ids = [BASELINE_ID, ADD_PROVIDERS_ID]
    for migration_id in applied_ids:
        migration = next(
            migration for migration in discover_migrations() if migration.id == migration_id
        )
        conn.executescript(migration.path.read_text(encoding="utf-8"))
    conn.execute("CREATE TABLE schema_migrations (id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.executemany(
        "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)",
        [(migration_id, "t") for migration_id in applied_ids],
    )
    conn.execute(
        """
        INSERT INTO providers (name, base_url, api_version, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "azure_openai",
            "https://resource.services.ai.azure.com/openai/v1",
            "2025-05-01",
            "t0",
            "t1",
        ),
    )
    conn.execute(
        """
        INSERT INTO provider_secrets (provider_name, ciphertext, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        ("azure_openai", "ciphertext", "t2", "t3"),
    )
    conn.execute(
        """
        INSERT INTO extractors (
            id, name, instructions, enable_thinking, schema, examples,
            source, seed_key, seed_version, created_at, updated_at, provider_name, model
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "extractor_invoice",
            "Invoice",
            "Extract.",
            0,
            "{}",
            "[]",
            "user",
            None,
            None,
            "t0",
            "t1",
            "azure_openai",
            "deployment-name",
        ),
    )
    conn.commit()

    assert apply_pending(conn) == [
        EXTRACTOR_DISPLAY_NAMES_ID,
        PROVIDER_CONFIGURATION_ID,
        REMOVE_FOUNDRY_API_VERSION_CONFIG_ID,
        INHERIT_OPENAI_COMPATIBLE_DEFAULT_MODEL_ID,
    ]

    assert columns(conn, "providers") == EXPECTED_COLUMNS["providers"]
    provider = conn.execute(
        "SELECT * FROM providers WHERE name = ?", ("microsoft_foundry",)
    ).fetchone()
    assert provider is not None
    assert provider["base_url"] == "https://resource.services.ai.azure.com/openai/v1"
    assert json.loads(provider["configuration"]) == {}
    assert (
        conn.execute("SELECT 1 FROM providers WHERE name = ?", ("azure_openai",)).fetchone() is None
    )
    secret = conn.execute("SELECT provider_name FROM provider_secrets").fetchone()
    assert tuple(secret) == ("microsoft_foundry",)
    extractor = conn.execute(
        "SELECT provider_name FROM extractors WHERE id = ?", ("extractor_invoice",)
    ).fetchone()
    assert tuple(extractor) == ("microsoft_foundry",)


def test_remove_foundry_api_version_config_migration_strips_already_migrated_config(
    conn: sqlite3.Connection,
) -> None:
    _register_functions(conn)
    applied_ids = [
        BASELINE_ID,
        ADD_PROVIDERS_ID,
        EXTRACTOR_DISPLAY_NAMES_ID,
        PROVIDER_CONFIGURATION_ID,
    ]
    for migration_id in applied_ids:
        migration = next(
            migration for migration in discover_migrations() if migration.id == migration_id
        )
        conn.executescript(migration.path.read_text(encoding="utf-8"))
    conn.execute("CREATE TABLE schema_migrations (id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.executemany(
        "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)",
        [(migration_id, "t") for migration_id in applied_ids],
    )
    conn.execute(
        """
        INSERT INTO providers (name, base_url, configuration, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "microsoft_foundry",
            "https://resource.services.ai.azure.com/openai/v1",
            '{"api_version":"2025-05-01","project_url":"https://resource.services.ai.azure.com/api/projects/project"}',
            "t0",
            "t1",
        ),
    )
    conn.commit()

    assert apply_pending(conn) == [
        REMOVE_FOUNDRY_API_VERSION_CONFIG_ID,
        INHERIT_OPENAI_COMPATIBLE_DEFAULT_MODEL_ID,
    ]

    provider = conn.execute(
        "SELECT configuration FROM providers WHERE name = ?", ("microsoft_foundry",)
    ).fetchone()
    assert json.loads(provider["configuration"]) == {
        "project_url": "https://resource.services.ai.azure.com/api/projects/project"
    }


def test_inherit_openai_compatible_default_model_migration_preserves_custom_models(
    conn: sqlite3.Connection,
) -> None:
    _register_functions(conn)
    applied_ids = [
        BASELINE_ID,
        ADD_PROVIDERS_ID,
        EXTRACTOR_DISPLAY_NAMES_ID,
        PROVIDER_CONFIGURATION_ID,
        REMOVE_FOUNDRY_API_VERSION_CONFIG_ID,
    ]
    for migration_id in applied_ids:
        migration = next(
            migration for migration in discover_migrations() if migration.id == migration_id
        )
        conn.executescript(migration.path.read_text(encoding="utf-8"))
    conn.execute("CREATE TABLE schema_migrations (id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.executemany(
        "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)",
        [(migration_id, "t") for migration_id in applied_ids],
    )
    rows = [
        ("extractor_default", "openai_compatible_api", "numind/NuExtract3-W4A16"),
        ("extractor_custom_local", "openai_compatible_api", "custom/local-model"),
        ("extractor_openai", "openai", "numind/NuExtract3-W4A16"),
    ]
    for extractor_id, provider_name, model in rows:
        conn.execute(
            """
            INSERT INTO extractors (
                id, name, display_name, instructions, enable_thinking, schema, examples,
                source, seed_key, seed_version, created_at, updated_at, provider_name, model
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                extractor_id,
                extractor_id.removeprefix("extractor_"),
                extractor_id,
                "Extract.",
                0,
                "{}",
                "[]",
                "user",
                None,
                None,
                "t0",
                "t1",
                provider_name,
                model,
            ),
        )
    conn.commit()

    assert apply_pending(conn) == [INHERIT_OPENAI_COMPATIBLE_DEFAULT_MODEL_ID]

    models = {
        row["id"]: row["model"]
        for row in conn.execute("SELECT id, model FROM extractors ORDER BY id")
    }
    assert models == {
        "extractor_custom_local": "custom/local-model",
        "extractor_default": None,
        "extractor_openai": "numind/NuExtract3-W4A16",
    }


def test_apply_pending_is_atomic_on_failure(tmp_path: Path) -> None:
    # A migration whose second statement fails must leave no partial schema and no
    # ledger row: the whole migration runs in one transaction.
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "20990101000000_bad.sql").write_text(
        "CREATE TABLE good (id TEXT);\nCREATE TABLE good (id TEXT);\n",
        encoding="utf-8",
    )
    connection = connect(tmp_path / "db.sqlite")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "parsehawk.server.adapters.persistence.migrations.runner._MIGRATIONS_DIR",
        migrations_dir,
    )
    try:
        with pytest.raises(sqlite3.OperationalError):
            apply_pending(connection)
        assert _table_exists(connection, "good") is False
        assert migration_status(connection).applied == []
    finally:
        monkeypatch.undo()
        connection.close()


def test_init_db_delegates_to_the_runner(conn: sqlite3.Connection) -> None:
    init_db(conn)

    assert migration_status(conn).applied == ALL_MIGRATION_IDS
    assert columns(conn, "files") == EXPECTED_COLUMNS["files"]


def test_migrations_disabled_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PARSEHAWK_SKIP_MIGRATIONS", raising=False)
    assert migrations_disabled() is False

    for value in ("1", "true", "yes", "on"):
        monkeypatch.setenv("PARSEHAWK_SKIP_MIGRATIONS", value)
        assert migrations_disabled() is True

    for value in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("PARSEHAWK_SKIP_MIGRATIONS", value)
        assert migrations_disabled() is False


def test_split_statements_ignores_semicolons_in_comments_and_strings() -> None:
    script = """
    -- a comment; not a boundary
    CREATE TABLE a (note TEXT DEFAULT 'x; y');
    /* block; comment */
    CREATE TABLE b (id TEXT);
    """

    statements = _split_statements(script)

    assert statements == [
        "CREATE TABLE a (note TEXT DEFAULT 'x; y')",
        "CREATE TABLE b (id TEXT)",
    ]


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]


def indexes(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(f"PRAGMA index_list({table})")
        if not str(row["name"]).startswith("sqlite_")
    }


def foreign_keys(conn: sqlite3.Connection, table: str) -> set[tuple[str, str, str, str]]:
    return {
        (row["from"], row["table"], row["to"], row["on_delete"])
        for row in conn.execute(f"PRAGMA foreign_key_list({table})")
    }


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None
