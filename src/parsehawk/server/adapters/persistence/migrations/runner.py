"""Lightweight, ordered, tracked SQLite migration runner (stdlib only).

Schema changes live as plain ``.sql`` files in this package, named with a
Supabase-style ``<YYYYMMDDHHMMSS>_<snake_case_description>.sql`` UTC-timestamp
prefix so lexical sorting yields apply order. A ``schema_migrations`` table
records which ids (the filename without ``.sql``) have been applied, so the
runner is safe to call repeatedly: :func:`apply_pending` runs only the migrations
whose id is not yet recorded, each in its own transaction together with recording
its id, so a failure leaves the schema and the ledger consistent. Forward-only
for now (no down-migrations).

To add a migration, drop a new timestamped ``.sql`` file in this directory; no
code changes are needed.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_MIGRATIONS_DIR = Path(__file__).resolve().parent
# ``<14-digit UTC timestamp>_<snake_case>.sql`` — matches Supabase's convention.
_MIGRATION_FILE = re.compile(r"^\d{14}_[a-z0-9]+(?:_[a-z0-9]+)*\.sql$")

_SKIP_ENV_VAR = "PARSEHAWK_SKIP_MIGRATIONS"
_FALSEY = {"", "0", "false", "no", "off"}


@dataclass(frozen=True)
class Migration:
    """A single migration: its id (filename stem) and the ``.sql`` file path."""

    id: str
    path: Path


@dataclass(frozen=True)
class MigrationStatus:
    """Applied and pending migration ids, each in apply order."""

    applied: list[str]
    pending: list[str]


def migrations_disabled() -> bool:
    """Whether automatic migration application is opted out via the environment.

    Honored by callers that apply migrations implicitly (the DI container that
    backs the API and worker); the explicit ``parsehawk migrate`` command ignores
    it so an operator can always apply on demand.
    """
    value = os.getenv(_SKIP_ENV_VAR)
    return value is not None and value.strip().lower() not in _FALSEY


def discover_migrations() -> list[Migration]:
    """Return every timestamped ``.sql`` migration in this package, in apply order."""
    found = [
        Migration(id=path.name.removesuffix(".sql"), path=path)
        for path in _MIGRATIONS_DIR.iterdir()
        if _MIGRATION_FILE.match(path.name)
    ]
    found.sort(key=lambda migration: migration.id)
    return found


def apply_pending(conn: sqlite3.Connection) -> list[str]:
    """Apply every not-yet-recorded migration in order; return the ids applied.

    Safe to call repeatedly: already-recorded migrations are skipped, so a second
    run applies nothing and returns an empty list.
    """
    _ensure_migrations_table(conn)
    _register_functions(conn)
    applied = set(_recorded_ids(conn))
    newly_applied: list[str] = []
    for migration in discover_migrations():
        if migration.id in applied:
            continue
        statements = _split_statements(migration.path.read_text(encoding="utf-8"))
        try:
            conn.execute("BEGIN")
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)",
                (migration.id, datetime.now(UTC).isoformat()),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        newly_applied.append(migration.id)
    return newly_applied


def migration_status(conn: sqlite3.Connection) -> MigrationStatus:
    """Report which migrations are applied and which are still pending."""
    _ensure_migrations_table(conn)
    applied = _recorded_ids(conn)
    applied_set = set(applied)
    pending = [
        migration.id for migration in discover_migrations() if migration.id not in applied_set
    ]
    return MigrationStatus(applied=applied, pending=pending)


def _register_functions(conn: sqlite3.Connection) -> None:
    conn.create_function("parsehawk_slug", 1, _slugify, deterministic=True)
    conn.create_function("parsehawk_name_suffix", 1, _name_suffix, deterministic=True)


def _slugify(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        slug = "extractor"
    return slug[:64].strip("-") or "extractor"


def _name_suffix(value: str | None) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:8]


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _recorded_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT id FROM schema_migrations ORDER BY id").fetchall()
    return [row[0] for row in rows]


def _split_statements(script: str) -> list[str]:
    """Split a SQL script into individual statements on top-level semicolons.

    Semicolons inside single/double-quoted strings and ``--`` / ``/* */`` comments
    are ignored so a whole ``.sql`` file can be applied statement-by-statement
    inside one transaction (``executescript`` would force an intermediate commit).
    """
    statements: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    index = 0
    length = len(script)
    while index < length:
        char = script[index]
        if quote is not None:
            buffer.append(char)
            if char == quote:
                quote = None
            index += 1
        elif char in ("'", '"'):
            quote = char
            buffer.append(char)
            index += 1
        elif char == "-" and index + 1 < length and script[index + 1] == "-":
            while index < length and script[index] != "\n":
                index += 1
        elif char == "/" and index + 1 < length and script[index + 1] == "*":
            index += 2
            while index + 1 < length and not (script[index] == "*" and script[index + 1] == "/"):
                index += 1
            index += 2
        elif char == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            index += 1
        else:
            buffer.append(char)
            index += 1
    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements
