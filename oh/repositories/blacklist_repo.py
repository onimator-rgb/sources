"""Read/write access to source_blacklist table."""
import sqlite3
import logging
from typing import List, Set

from oh.utils import utcnow

logger = logging.getLogger(__name__)


class BlacklistRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, source_name: str, reason: str = "") -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO source_blacklist (source_name, reason, added_at) VALUES (?, ?, ?)",
            (source_name.strip().lower(), reason, utcnow()),
        )
        self._conn.commit()

    def remove(self, source_name: str) -> None:
        self._conn.execute(
            "DELETE FROM source_blacklist WHERE source_name = ?",
            (source_name.strip().lower(),),
        )
        self._conn.commit()

    def is_blacklisted(self, source_name: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM source_blacklist WHERE source_name = ?",
            (source_name.strip().lower(),),
        ).fetchone()
        return row is not None

    def get_all(self) -> List[dict]:
        rows = self._conn.execute(
            "SELECT source_name, reason, added_at FROM source_blacklist ORDER BY source_name"
        ).fetchall()
        return [{"source_name": r["source_name"], "reason": r["reason"], "added_at": r["added_at"]} for r in rows]

    def get_blacklisted_set(self) -> Set[str]:
        rows = self._conn.execute("SELECT source_name FROM source_blacklist").fetchall()
        return {r["source_name"] for r in rows}

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM source_blacklist").fetchone()[0]
