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
# Migration 008 — source finder tables
# ---------------------------------------------------------------------------

_MIGRATION_008_SQL = """
CREATE TABLE IF NOT EXISTS source_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES oh_accounts(id),
    username TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    step_reached INTEGER NOT NULL DEFAULT 0,
    query_used TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_searches_account
    ON source_searches(account_id, started_at DESC);

CREATE TABLE IF NOT EXISTS source_search_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL REFERENCES source_searches(id),
    username TEXT NOT NULL,
    full_name TEXT,
    follower_count INTEGER NOT NULL DEFAULT 0,
    bio TEXT,
    source_type TEXT NOT NULL DEFAULT 'suggested',
    is_private INTEGER NOT NULL DEFAULT 0,
    is_verified INTEGER NOT NULL DEFAULT 0,
    is_enriched INTEGER NOT NULL DEFAULT 0,
    avg_er REAL,
    ai_score REAL,
    ai_category TEXT,
    profile_pic_url TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_candidates_search
    ON source_search_candidates(search_id);

CREATE TABLE IF NOT EXISTS source_search_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL REFERENCES source_searches(id),
    candidate_id INTEGER NOT NULL REFERENCES source_search_candidates(id),
    rank INTEGER NOT NULL,
    added_to_sources INTEGER NOT NULL DEFAULT 0,
    added_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_results_search
    ON source_search_results(search_id, rank)
"""

# ---------------------------------------------------------------------------
# Migration 009 — bulk discovery tables
# ---------------------------------------------------------------------------

_MIGRATION_009_SQL = """
CREATE TABLE IF NOT EXISTS bulk_discovery_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at       TEXT    NOT NULL,
    completed_at     TEXT,
    status           TEXT    NOT NULL DEFAULT 'running',
    min_threshold    INTEGER NOT NULL,
    auto_add_top_n   INTEGER NOT NULL,
    total_accounts   INTEGER NOT NULL DEFAULT 0,
    accounts_done    INTEGER NOT NULL DEFAULT 0,
    accounts_failed  INTEGER NOT NULL DEFAULT 0,
    total_added      INTEGER NOT NULL DEFAULT 0,
    machine          TEXT,
    error_message    TEXT,
    reverted_at      TEXT,
    revert_status    TEXT
);

CREATE INDEX IF NOT EXISTS idx_bulk_runs_status
    ON bulk_discovery_runs(status, started_at DESC);

CREATE TABLE IF NOT EXISTS bulk_discovery_items (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                INTEGER NOT NULL REFERENCES bulk_discovery_runs(id),
    account_id            INTEGER NOT NULL REFERENCES oh_accounts(id),
    username              TEXT    NOT NULL,
    device_id             TEXT    NOT NULL,
    search_id             INTEGER REFERENCES source_searches(id),
    sources_before        INTEGER NOT NULL DEFAULT 0,
    sources_added         INTEGER NOT NULL DEFAULT 0,
    sources_after         INTEGER NOT NULL DEFAULT 0,
    status                TEXT    NOT NULL DEFAULT 'queued',
    added_sources_json    TEXT,
    original_sources_json TEXT,
    error_message         TEXT
);

CREATE INDEX IF NOT EXISTS idx_bulk_items_run
    ON bulk_discovery_items(run_id);

CREATE INDEX IF NOT EXISTS idx_bulk_items_account
    ON bulk_discovery_items(account_id)
"""

# ---------------------------------------------------------------------------
# Migration 010 — smart source discovery: profiles, FBR stats, search columns
# ---------------------------------------------------------------------------

_MIGRATION_010_SQL = """
CREATE TABLE IF NOT EXISTS source_profiles (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name      TEXT    NOT NULL UNIQUE,
    niche_category   TEXT,
    niche_confidence REAL,
    language         TEXT,
    location         TEXT,
    follower_count   INTEGER,
    bio              TEXT,
    avg_er           REAL,
    is_active_source INTEGER NOT NULL DEFAULT 1,
    first_seen_at    TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    profile_json     TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_profiles_niche
    ON source_profiles(niche_category);

CREATE TABLE IF NOT EXISTS source_fbr_stats (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name           TEXT    NOT NULL UNIQUE,
    total_accounts_used   INTEGER NOT NULL DEFAULT 0,
    total_follows         INTEGER NOT NULL DEFAULT 0,
    total_followbacks     INTEGER NOT NULL DEFAULT 0,
    avg_fbr_pct           REAL    NOT NULL DEFAULT 0.0,
    weighted_fbr_pct      REAL    NOT NULL DEFAULT 0.0,
    quality_account_count INTEGER NOT NULL DEFAULT 0,
    last_analyzed_at      TEXT,
    updated_at            TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_source_fbr_stats_name
    ON source_fbr_stats(source_name);

ALTER TABLE source_searches ADD COLUMN target_category TEXT;
ALTER TABLE source_searches ADD COLUMN target_niche TEXT;
ALTER TABLE source_searches ADD COLUMN target_bio TEXT;
ALTER TABLE source_searches ADD COLUMN target_followers INTEGER;
ALTER TABLE source_searches ADD COLUMN target_location TEXT;
ALTER TABLE source_searches ADD COLUMN target_language TEXT;
ALTER TABLE source_searches ADD COLUMN target_profile_json TEXT;

ALTER TABLE source_search_candidates ADD COLUMN niche_category_local TEXT;
ALTER TABLE source_search_candidates ADD COLUMN niche_match_score REAL;
ALTER TABLE source_search_candidates ADD COLUMN composite_score REAL;
ALTER TABLE source_search_candidates ADD COLUMN search_strategy TEXT;
ALTER TABLE source_search_candidates ADD COLUMN language TEXT;
ALTER TABLE source_search_candidates ADD COLUMN location TEXT
"""

# ---------------------------------------------------------------------------
# Migration 011 — source blacklist + account operator notes
# ---------------------------------------------------------------------------

_MIGRATION_011_SQL = """
CREATE TABLE IF NOT EXISTS source_blacklist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT    NOT NULL UNIQUE,
    reason      TEXT,
    added_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_blacklist_name
    ON source_blacklist(source_name);

ALTER TABLE oh_accounts ADD COLUMN operator_notes TEXT
"""

# ---------------------------------------------------------------------------
# Migration 012 — campaign templates
# ---------------------------------------------------------------------------

_MIGRATION_012_SQL = """
CREATE TABLE IF NOT EXISTS campaign_templates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    description     TEXT,
    niche           TEXT,
    language        TEXT    DEFAULT 'pl',
    min_sources     INTEGER DEFAULT 10,
    source_niche    TEXT,
    follow_limit    INTEGER DEFAULT 200,
    like_limit      INTEGER DEFAULT 100,
    tb_level        INTEGER DEFAULT 1,
    limits_level    INTEGER DEFAULT 1,
    settings_json   TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_templates_niche
    ON campaign_templates(niche)
"""

# ---------------------------------------------------------------------------
# Migration 013 — error reporting, block detection, account groups
# ---------------------------------------------------------------------------

_MIGRATION_013_SQL = """
CREATE TABLE IF NOT EXISTS error_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id       TEXT    NOT NULL UNIQUE,
    error_type      TEXT    NOT NULL,
    error_message   TEXT,
    traceback       TEXT,
    oh_version      TEXT,
    os_version      TEXT,
    python_version  TEXT,
    db_stats        TEXT,
    log_tail        TEXT,
    user_note       TEXT,
    sent_at         TEXT,
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS block_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL REFERENCES oh_accounts(id),
    event_type      TEXT    NOT NULL,
    detected_at     TEXT    NOT NULL,
    evidence        TEXT,
    resolved_at     TEXT,
    auto_detected   INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_block_events_account
    ON block_events(account_id, detected_at DESC);

CREATE TABLE IF NOT EXISTS account_groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    color       TEXT    DEFAULT '#5B8DEF',
    description TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS account_group_members (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    INTEGER NOT NULL REFERENCES account_groups(id) ON DELETE CASCADE,
    account_id  INTEGER NOT NULL REFERENCES oh_accounts(id),
    added_at    TEXT    NOT NULL,
    UNIQUE(group_id, account_id)
);

CREATE INDEX IF NOT EXISTS idx_group_members_group
    ON account_group_members(group_id);

CREATE INDEX IF NOT EXISTS idx_group_members_account
    ON account_group_members(account_id)
"""

# ---------------------------------------------------------------------------
# Migration 014 — auto-fix actions log
# ---------------------------------------------------------------------------

_MIGRATION_014_SQL = """
CREATE TABLE IF NOT EXISTS auto_fix_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fix_type        TEXT    NOT NULL,
    target_username TEXT,
    target_device   TEXT,
    details         TEXT,
    items_affected  INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auto_fix_created
    ON auto_fix_actions(created_at DESC)
"""

# ---------------------------------------------------------------------------
# Migration 015 — warmup templates
# ---------------------------------------------------------------------------

_MIGRATION_015_SQL = """
CREATE TABLE IF NOT EXISTS warmup_templates (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT    NOT NULL UNIQUE,
    description         TEXT,
    follow_start        INTEGER NOT NULL DEFAULT 10,
    follow_increment    INTEGER NOT NULL DEFAULT 5,
    follow_cap          INTEGER NOT NULL DEFAULT 50,
    like_start          INTEGER NOT NULL DEFAULT 20,
    like_increment      INTEGER NOT NULL DEFAULT 5,
    like_cap            INTEGER NOT NULL DEFAULT 80,
    auto_increment      INTEGER NOT NULL DEFAULT 1,
    enable_follow       INTEGER NOT NULL DEFAULT 1,
    enable_like         INTEGER NOT NULL DEFAULT 1,
    is_default          INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_warmup_templates_name
    ON warmup_templates(name);

INSERT INTO warmup_templates (name, description, follow_start, follow_increment, follow_cap,
    like_start, like_increment, like_cap, auto_increment, enable_follow, enable_like,
    is_default, created_at, updated_at)
VALUES
    ('Conservative', 'New or personal accounts — gentle ramp-up', 5, 5, 40, 10, 5, 60, 1, 1, 1, 1, datetime('now'), datetime('now')),
    ('Moderate', 'Established accounts — balanced growth', 15, 10, 70, 30, 10, 100, 1, 1, 1, 1, datetime('now'), datetime('now')),
    ('Aggressive', 'Mature accounts with high followers — fast scaling', 40, 15, 150, 60, 20, 200, 1, 1, 1, 1, datetime('now'), datetime('now'))
"""

# ---------------------------------------------------------------------------
# Migration 016 — add created_at to source_assignments for tracking when
# a source was first added to an account
# ---------------------------------------------------------------------------

_MIGRATION_016_SQL = """
ALTER TABLE source_assignments ADD COLUMN created_at TEXT;

UPDATE source_assignments SET created_at = updated_at WHERE created_at IS NULL;
"""

# ---------------------------------------------------------------------------
# Migration 017 — LBR (Like-Back Rate) tables: snapshots, source results,
# and like source assignments — mirrors FBR structure for like analytics
# ---------------------------------------------------------------------------

_MIGRATION_017_SQL = """
CREATE TABLE IF NOT EXISTS lbr_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id          INTEGER NOT NULL REFERENCES oh_accounts(id),
    device_id           TEXT    NOT NULL,
    username            TEXT    NOT NULL,
    analyzed_at         TEXT    NOT NULL,
    min_likes           INTEGER NOT NULL DEFAULT 50,
    min_lbr_pct         REAL    NOT NULL DEFAULT 5.0,
    total_sources       INTEGER NOT NULL DEFAULT 0,
    quality_sources     INTEGER NOT NULL DEFAULT 0,
    status              TEXT    NOT NULL DEFAULT 'ok',
    best_lbr_pct        REAL,
    best_lbr_source     TEXT,
    highest_vol_source  TEXT,
    highest_vol_count   INTEGER DEFAULT 0,
    below_volume_count  INTEGER NOT NULL DEFAULT 0,
    anomaly_count       INTEGER NOT NULL DEFAULT 0,
    warnings_json       TEXT,
    schema_error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_lbr_snapshots_account
    ON lbr_snapshots (account_id, analyzed_at DESC);

CREATE TABLE IF NOT EXISTS lbr_source_results (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id      INTEGER NOT NULL REFERENCES lbr_snapshots(id),
    source_name      TEXT    NOT NULL,
    like_count       INTEGER NOT NULL DEFAULT 0,
    followback_count INTEGER NOT NULL DEFAULT 0,
    lbr_percent      REAL    NOT NULL DEFAULT 0.0,
    is_quality       INTEGER NOT NULL DEFAULT 0,
    anomaly          TEXT
);

CREATE INDEX IF NOT EXISTS idx_lbr_source_results_snapshot
    ON lbr_source_results (snapshot_id);

CREATE TABLE IF NOT EXISTS like_source_assignments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL REFERENCES oh_accounts(id),
    source_name TEXT    NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1,
    snapshot_id INTEGER REFERENCES lbr_snapshots(id),
    updated_at  TEXT,
    created_at  TEXT,
    UNIQUE(account_id, source_name)
);

CREATE INDEX IF NOT EXISTS idx_like_source_assignments_account
    ON like_source_assignments (account_id);

CREATE INDEX IF NOT EXISTS idx_like_source_assignments_source
    ON like_source_assignments (source_name)
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
    (8, "source_finder",        _MIGRATION_008_SQL),
    (9, "bulk_discovery",       _MIGRATION_009_SQL),
    (10, "smart_source_discovery", _MIGRATION_010_SQL),
    (11, "blacklist_and_notes", _MIGRATION_011_SQL),
    (12, "campaign_templates",  _MIGRATION_012_SQL),
    (13, "error_reports_blocks_groups", _MIGRATION_013_SQL),
    (14, "auto_fix_actions",            _MIGRATION_014_SQL),
    (15, "warmup_templates",             _MIGRATION_015_SQL),
    (16, "source_created_at",            _MIGRATION_016_SQL),
    (17, "lbr_tables",                   _MIGRATION_017_SQL),
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
