"""
Read/write access to the oh_config key-value table.
New settings are added via seed_defaults() — zero schema changes required.
"""
import socket
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CONFIG_DEFAULTS = [
    ("bot_root_path",                None,    "Absolute path to the Onimator installation folder"),
    ("pc_name",                      None,    "This machine identifier (auto-set on first run)"),
    ("min_follows_threshold",        "100",   "Minimum follow count for FBR source inclusion"),
    ("min_fbr_threshold",            "10.0",  "Minimum FBR% to flag a source as quality"),
    ("theme",                        "dark",  "UI theme: dark or light"),
    ("weak_source_delete_threshold", "5.0",   "FBR% at or below which a source is considered weak for bulk deletion"),
    ("min_source_count_warning",     "5",     "Warn if an account has fewer active sources than this"),
    ("hiker_api_key",               "",      "HikerAPI access key for Instagram data"),
    ("gemini_api_key",              "",      "Google Gemini API key for AI scoring"),
    ("min_source_for_bulk_discovery", "10",  "Minimum active sources — accounts below this qualify for bulk discovery"),
    ("bulk_auto_add_top_n",          "5",   "How many top results to auto-add per account in bulk discovery"),
    ("auto_scan_enabled",            "0",   "Enable automatic periodic Scan & Sync"),
    ("auto_scan_interval_hours",     "6",   "Hours between automatic scans"),
    ("update_check_enabled",         "1",   "Enable automatic update checking on startup"),
    ("update_skipped_version",       "",    "Version that was skipped by user"),
    ("auto_fix_source_cleanup",      "0",   "Detect dead sources (wFBR~0) after Scan"),
    ("auto_fix_source_threshold",    "0.5", "wFBR% threshold for auto source cleanup"),
    ("auto_fix_tb_escalation",       "0",   "Detect TB escalation candidates after Scan"),
    ("auto_fix_dead_device_alert",   "0",   "Detect devices with 0 activity today"),
    ("auto_fix_duplicate_cleanup",   "0",   "Detect duplicate sources in sources.txt"),
    ("onboarding_done",              "0",   "Whether the first-run onboarding wizard has been completed"),
    ("last_seen_version",            "",    "Last version for which What's New was shown"),
    ("show_help_tips",               "0",   "Show contextual help buttons (?) in the UI"),
    ("tour_completed",               "0",   "Whether the guided tour has been completed"),
]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class SettingsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def seed_defaults(self) -> None:
        """Insert default config rows; skip any key that already exists."""
        now = _utcnow()
        for key, value, description in _CONFIG_DEFAULTS:
            self._conn.execute(
                "INSERT OR IGNORE INTO oh_config (key, value, updated_at, description) "
                "VALUES (?, ?, ?, ?)",
                (key, value, now, description),
            )
        # Auto-detect pc_name if not yet set
        row = self._conn.execute(
            "SELECT value FROM oh_config WHERE key='pc_name'"
        ).fetchone()
        if row is None or row["value"] is None:
            self._conn.execute(
                "UPDATE oh_config SET value=?, updated_at=? WHERE key='pc_name'",
                (socket.gethostname(), now),
            )
        self._conn.commit()

    def get(self, key: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value FROM oh_config WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO oh_config (key, value, updated_at, description) VALUES (?, ?, ?, '') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, _utcnow()),
        )
        self._conn.commit()

    def get_bot_root(self) -> Optional[str]:
        return self.get("bot_root_path")

    def set_bot_root(self, path: str) -> None:
        """Set bot root after validating it is a safe, existing directory."""
        resolved = Path(path).resolve()

        # Must be an existing directory
        if not resolved.is_dir():
            raise ValueError(f"Bot root is not an existing directory: {path}")

        # Must not be a system directory
        _BLOCKED_PREFIXES = [
            "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
            "C:\\ProgramData",
        ]
        resolved_str = str(resolved)
        for prefix in _BLOCKED_PREFIXES:
            if resolved_str.lower().startswith(prefix.lower()):
                raise ValueError(
                    f"Bot root must not be a system directory: {resolved_str}"
                )

        self.set("bot_root_path", str(resolved))

    def get_fbr_thresholds(self) -> tuple:
        """Returns (min_follows: int, min_fbr: float) with fallback defaults."""
        min_follows = int(self.get("min_follows_threshold") or "100")
        min_fbr = float(self.get("min_fbr_threshold") or "10.0")
        return min_follows, min_fbr

    def get_weak_source_threshold(self) -> float:
        """Returns the FBR% threshold used for bulk weak-source deletion."""
        return float(self.get("weak_source_delete_threshold") or "5.0")

    def get_min_source_count_warning(self) -> int:
        """Returns the minimum active source count below which to warn."""
        return int(self.get("min_source_count_warning") or "5")

    def get_all(self) -> dict:
        rows = self._conn.execute("SELECT key, value, description FROM oh_config").fetchall()
        return {r["key"]: {"value": r["value"], "description": r["description"]} for r in rows}
