"""
Read/write access to the oh_config key-value table.
New settings are added via seed_defaults() — zero schema changes required.
"""
import socket
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_CONFIG_DEFAULTS = [
    ("bot_root_path",         None,    "Absolute path to the Onimator installation folder"),
    ("pc_name",               None,    "This machine identifier (auto-set on first run)"),
    ("min_follows_threshold", "100",   "Minimum follow count for FBR source inclusion"),
    ("min_fbr_threshold",     "10.0",  "Minimum FBR% to flag a source as quality"),
    ("theme",                 "dark",  "UI theme: dark or light"),
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
        self.set("bot_root_path", path)

    def get_fbr_thresholds(self) -> tuple:
        """Returns (min_follows: int, min_fbr: float) with fallback defaults."""
        min_follows = int(self.get("min_follows_threshold") or "100")
        min_fbr = float(self.get("min_fbr_threshold") or "10.0")
        return min_follows, min_fbr

    def get_all(self) -> dict:
        rows = self._conn.execute("SELECT key, value, description FROM oh_config").fetchall()
        return {r["key"]: {"value": r["value"], "description": r["description"]} for r in rows}
