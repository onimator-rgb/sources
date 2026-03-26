"""
Migration runner for the OH local database.

Adding a new migration:
  1. Write the SQL as a new _MIGRATION_NNN_SQL string.
  2. Add a (version, name, sql) tuple to _MIGRATIONS.
  3. Restart OH — migrations apply automatically on startup.

Rules:
  - Never modify an already-applied migration.
  - Only ADD columns/tables in new migrations (SQLite cannot drop columns).
  - Each migration runs inside a transaction; failure rolls back cleanly.
"""
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Tuple, List

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            version    INTEGER NOT NULL UNIQUE,
            name       TEXT    NOT NULL,
            applied_at TEXT    NOT NULL
        )
    """)
    conn.commit()


def _applied_versions(conn: sqlite3.Connection) -> set:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row["version"] for row in rows}


# ---------------------------------------------------------------------------
# Migration 001 — initial schema
# ---------------------------------------------------------------------------

_MIGRATION_001_SQL = """
CREATE TABLE IF NOT EXISTS oh_config (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS oh_devices (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT    NOT NULL UNIQUE,
    device_name         TEXT    NOT NULL,
    last_known_status   TEXT,
    first_discovered_at TEXT    NOT NULL,
    last_synced_at      TEXT    NOT NULL,
    is_active           INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS oh_accounts (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id                TEXT    NOT NULL REFERENCES oh_devices(device_id),
    username                 TEXT    NOT NULL,
    discovered_at            TEXT    NOT NULL,
    last_seen_at             TEXT    NOT NULL,
    removed_at               TEXT,
    removal_sync_run_id      INTEGER,
    start_time               TEXT,
    end_time                 TEXT,
    follow_enabled           INTEGER,
    unfollow_enabled         INTEGER,
    limit_per_day            TEXT,
    last_metadata_updated_at TEXT,
    data_db_exists           INTEGER NOT NULL DEFAULT 0,
    sources_txt_exists       INTEGER NOT NULL DEFAULT 0,
    UNIQUE (device_id, username)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at          TEXT    NOT NULL,
    completed_at        TEXT,
    status              TEXT    NOT NULL DEFAULT 'running',
    triggered_by        TEXT    NOT NULL DEFAULT 'manual',
    devices_scanned     INTEGER NOT NULL DEFAULT 0,
    accounts_scanned    INTEGER NOT NULL DEFAULT 0,
    accounts_added      INTEGER NOT NULL DEFAULT 0,
    accounts_removed    INTEGER NOT NULL DEFAULT 0,
    accounts_updated    INTEGER NOT NULL DEFAULT 0,
    accounts_unchanged  INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT
);

CREATE TABLE IF NOT EXISTS sync_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_run_id     INTEGER NOT NULL REFERENCES sync_runs(id),
    event_type      TEXT    NOT NULL,
    device_id       TEXT    NOT NULL,
    username        TEXT    NOT NULL,
    account_id      INTEGER REFERENCES oh_accounts(id),
    changed_fields  TEXT,
    created_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_accounts_active
    ON oh_accounts (removed_at, device_id, username);

CREATE INDEX IF NOT EXISTS idx_accounts_device
    ON oh_accounts (device_id);

CREATE INDEX IF NOT EXISTS idx_sync_events_run
    ON sync_events (sync_run_id, event_type);
"""

# ---------------------------------------------------------------------------
# Registry of all migrations — add new entries here
# ---------------------------------------------------------------------------

_MIGRATIONS: List[Tuple[int, str, str]] = [
    (1, "initial_schema", _MIGRATION_001_SQL),
]


def run_migrations(conn: sqlite3.Connection) -> None:
    _ensure_migrations_table(conn)
    applied = _applied_versions(conn)

    pending = [(v, n, sql) for v, n, sql in _MIGRATIONS if v not in applied]
    if not pending:
        logger.debug("Database schema is up to date.")
        return

    for version, name, sql in sorted(pending, key=lambda m: m[0]):
        logger.info(f"Applying migration {version}: {name}")
        try:
            with conn:
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, _utcnow())
                )
            logger.info(f"Migration {version} applied.")
        except sqlite3.Error as e:
            logger.error(f"Migration {version} failed: {e}")
            raise
