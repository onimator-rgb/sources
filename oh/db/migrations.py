"""
Migration runner for the OH local database.

Adding a new migration:
  1. Write the SQL as a new _MIGRATION_NNN_SQL string.
  2. Add a (version, name, sql) tuple to _MIGRATIONS.
  3. Restart OH — migrations apply automatically on startup.

Rules:
  - Never modify an already-applied migration.
  - Only ADD columns/tables in new migrations (SQLite cannot drop columns).
  - Each migration runs inside a single transaction; if anything fails the
    whole migration is rolled back and the version stays unrecorded.

FIX: executescript() was used previously. It issues a silent COMMIT before
running, which breaks the surrounding transaction and makes the DDL and the
schema_migrations INSERT non-atomic. We now split the SQL on semicolons and
use conn.execute() so everything stays inside one 'with conn:' transaction.
"""
import sqlite3
import logging
from datetime import datetime, timezone
from typing import List, Tuple

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


def _run_sql_statements(conn: sqlite3.Connection, sql: str) -> None:
    """
    Execute multiple semicolon-separated DDL/DML statements with
    conn.execute() so they participate in the caller's transaction.
    Empty statements (trailing semicolons) are silently skipped.
    """
    for stmt in sql.split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)


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
    ON sync_events (sync_run_id, event_type)
"""

# ---------------------------------------------------------------------------
# Migration 002 — FBR snapshot tables
# ---------------------------------------------------------------------------

_MIGRATION_002_SQL = """
CREATE TABLE IF NOT EXISTS fbr_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id          INTEGER NOT NULL REFERENCES oh_accounts(id),
    device_id           TEXT    NOT NULL,
    username            TEXT    NOT NULL,
    analyzed_at         TEXT    NOT NULL,
    min_follows         INTEGER NOT NULL DEFAULT 100,
    min_fbr_pct         REAL    NOT NULL DEFAULT 10.0,
    total_sources       INTEGER NOT NULL DEFAULT 0,
    quality_sources     INTEGER NOT NULL DEFAULT 0,
    best_fbr_pct        REAL,
    best_fbr_source     TEXT,
    highest_vol_source  TEXT,
    highest_vol_count   INTEGER,
    below_volume_count  INTEGER NOT NULL DEFAULT 0,
    anomaly_count       INTEGER NOT NULL DEFAULT 0,
    warnings_json       TEXT,
    status              TEXT    NOT NULL DEFAULT 'ok',
    schema_error        TEXT
);

CREATE TABLE IF NOT EXISTS fbr_source_results (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id      INTEGER NOT NULL REFERENCES fbr_snapshots(id),
    source_name      TEXT    NOT NULL,
    follow_count     INTEGER NOT NULL DEFAULT 0,
    followback_count INTEGER NOT NULL DEFAULT 0,
    fbr_percent      REAL    NOT NULL DEFAULT 0.0,
    is_quality       INTEGER NOT NULL DEFAULT 0,
    anomaly          TEXT
);

CREATE INDEX IF NOT EXISTS idx_fbr_snapshots_account
    ON fbr_snapshots (account_id, analyzed_at DESC);

CREATE INDEX IF NOT EXISTS idx_fbr_source_results_snapshot
    ON fbr_source_results (snapshot_id)
"""

# ---------------------------------------------------------------------------
# Migration 003 — source assignments table
# ---------------------------------------------------------------------------

_MIGRATION_003_SQL = """
CREATE TABLE IF NOT EXISTS source_assignments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL REFERENCES oh_accounts(id),
    source_name TEXT    NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 0,
    snapshot_id INTEGER REFERENCES fbr_snapshots(id),
    updated_at  TEXT    NOT NULL,
    UNIQUE (account_id, source_name)
);

CREATE INDEX IF NOT EXISTS idx_source_assignments_account
    ON source_assignments (account_id);

CREATE INDEX IF NOT EXISTS idx_source_assignments_source
    ON source_assignments (source_name)
"""

# ---------------------------------------------------------------------------
# Migration 004 — source deletion history tables
# ---------------------------------------------------------------------------

_MIGRATION_004_SQL = """
CREATE TABLE IF NOT EXISTS source_delete_actions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    deleted_at              TEXT    NOT NULL,
    delete_type             TEXT    NOT NULL,
    scope                   TEXT    NOT NULL,
    total_sources           INTEGER NOT NULL DEFAULT 0,
    total_accounts_affected INTEGER NOT NULL DEFAULT 0,
    threshold_pct           REAL,
    machine                 TEXT,
    notes                   TEXT
);

CREATE TABLE IF NOT EXISTS source_delete_items (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id            INTEGER NOT NULL REFERENCES source_delete_actions(id),
    source_name          TEXT    NOT NULL,
    affected_accounts_json TEXT  NOT NULL DEFAULT '[]',
    files_removed        INTEGER NOT NULL DEFAULT 0,
    files_not_found      INTEGER NOT NULL DEFAULT 0,
    files_failed         INTEGER NOT NULL DEFAULT 0,
    errors_json          TEXT
);

CREATE INDEX IF NOT EXISTS idx_delete_items_action
    ON source_delete_items (action_id);

CREATE INDEX IF NOT EXISTS idx_delete_items_source
    ON source_delete_items (source_name)
"""

# ---------------------------------------------------------------------------
# Migration 005 — delete revert support
# ---------------------------------------------------------------------------

_MIGRATION_005_SQL = """
ALTER TABLE source_delete_actions ADD COLUMN status TEXT NOT NULL DEFAULT 'completed';
ALTER TABLE source_delete_actions ADD COLUMN reverted_at TEXT;
ALTER TABLE source_delete_actions ADD COLUMN revert_of_action_id INTEGER;
ALTER TABLE source_delete_items ADD COLUMN affected_details_json TEXT
"""

# ---------------------------------------------------------------------------
# Migration 006 — session snapshots, account tags, review flag
# ---------------------------------------------------------------------------

_MIGRATION_006_SQL = """
CREATE TABLE IF NOT EXISTS session_snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     INTEGER NOT NULL REFERENCES oh_accounts(id),
    device_id      TEXT    NOT NULL,
    username       TEXT    NOT NULL,
    snapshot_date  TEXT    NOT NULL,
    slot           TEXT    NOT NULL,
    follow_count   INTEGER NOT NULL DEFAULT 0,
    like_count     INTEGER NOT NULL DEFAULT 0,
    dm_count       INTEGER NOT NULL DEFAULT 0,
    unfollow_count INTEGER NOT NULL DEFAULT 0,
    follow_limit   INTEGER,
    like_limit     INTEGER,
    has_activity   INTEGER NOT NULL DEFAULT 0,
    collected_at   TEXT    NOT NULL,
    UNIQUE (account_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_session_snap_account
    ON session_snapshots (account_id, snapshot_date DESC);

CREATE INDEX IF NOT EXISTS idx_session_snap_date
    ON session_snapshots (snapshot_date, has_activity);

CREATE TABLE IF NOT EXISTS account_tags (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   INTEGER NOT NULL REFERENCES oh_accounts(id),
    tag_source   TEXT    NOT NULL,
    tag_category TEXT    NOT NULL,
    tag_value    TEXT    NOT NULL,
    tag_level    INTEGER,
    updated_at   TEXT    NOT NULL,
    UNIQUE (account_id, tag_source, tag_value)
);

CREATE INDEX IF NOT EXISTS idx_account_tags_account
    ON account_tags (account_id);

CREATE INDEX IF NOT EXISTS idx_account_tags_category
    ON account_tags (tag_category, tag_value);

ALTER TABLE oh_accounts ADD COLUMN review_flag INTEGER NOT NULL DEFAULT 0;
ALTER TABLE oh_accounts ADD COLUMN review_note TEXT;
ALTER TABLE oh_accounts ADD COLUMN review_set_at TEXT;
ALTER TABLE oh_accounts ADD COLUMN bot_tags_raw TEXT;
ALTER TABLE oh_accounts ADD COLUMN like_limit_perday TEXT;
ALTER TABLE oh_accounts ADD COLUMN follow_limit_perday TEXT
"""

# ---------------------------------------------------------------------------
# Migration 007 — operator action audit trail
# ---------------------------------------------------------------------------

_MIGRATION_007_SQL = """
CREATE TABLE IF NOT EXISTS operator_actions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   INTEGER NOT NULL REFERENCES oh_accounts(id),
    username     TEXT    NOT NULL,
    device_id    TEXT    NOT NULL,
    action_type  TEXT    NOT NULL,
    old_value    TEXT,
    new_value    TEXT,
    note         TEXT,
    performed_at TEXT    NOT NULL,
    machine      TEXT
);

CREATE INDEX IF NOT EXISTS idx_op_actions_account
    ON operator_actions (account_id);

CREATE INDEX IF NOT EXISTS idx_op_actions_type
    ON operator_actions (action_type, performed_at DESC)
"""

# ---------------------------------------------------------------------------
# Registry — append new entries here, never modify existing ones
# ---------------------------------------------------------------------------

_MIGRATIONS: List[Tuple[int, str, str]] = [
    (1, "initial_schema",       _MIGRATION_001_SQL),
    (2, "fbr_snapshots",        _MIGRATION_002_SQL),
    (3, "source_assignments",   _MIGRATION_003_SQL),
    (4, "delete_history",       _MIGRATION_004_SQL),
    (5, "delete_revert_support", _MIGRATION_005_SQL),
    (6, "session_and_tags",     _MIGRATION_006_SQL),
    (7, "operator_actions",     _MIGRATION_007_SQL),
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
            with conn:  # single transaction: DDL + schema_migrations INSERT
                _run_sql_statements(conn, sql)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (version, name, _utcnow()),
                )
            logger.info(f"Migration {version} applied.")
        except sqlite3.Error as e:
            logger.error(f"Migration {version} failed: {e}")
            raise
